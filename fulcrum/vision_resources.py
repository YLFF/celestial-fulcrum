from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .vision_geometry import detect_map_viewport, working_image
from .vision_action import recognize_action
from .runtime import node_runtime


ROOT = Path(__file__).resolve().parents[1]
OCR_SCRIPT = ROOT / "scripts" / "ocr_hud_batch.mjs"

# Coordinates are relative to a 2048x1152 game viewport. The left HUD is
# anchored at its left edge; currency is anchored at the right edge.
HUD_BOXES: dict[str, tuple[tuple[int, int, int, int], str]] = {
    "life": ((275, 50, 402, 87), "left"),
    "shield": ((435, 48, 473, 86), "left"),
    "level": ((488, 36, 543, 84), "left"),
    "level_alt": ((490, 42, 541, 81), "left"),
    "experience": ((559, 50, 696, 87), "left"),
    "hope": ((1350, 26, 1710, 88), "right"),
    "originium_ingot": ((1860, 26, 2025, 86), "right"),
    "action_points": ((1790, 185, 1875, 265), "right"),
}


def _box(
    image: np.ndarray,
    viewport: tuple[int, int, int, int],
    field: str,
    ui_scale: float = 1.0,
) -> tuple[int, int, int, int]:
    (x0, y0, x1, y1), anchor = HUD_BOXES[field]
    scale = image.shape[0] / 1152.0 * ui_scale
    origin_x = viewport[0] if anchor == "left" else viewport[2] - 2048 * scale
    return (
        max(0, round(origin_x + x0 * scale)),
        max(0, round(y0 * scale)),
        min(image.shape[1], round(origin_x + x1 * scale)),
        min(image.shape[0], round(y1 * scale)),
    )


def _grayscale_crop(crop: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    return cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)


def _level_digits(crop: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0, 0, 125), (179, 100, 255))
    return cv2.resize(white, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)


def _hope_digits(crop: np.ndarray, scale: float) -> np.ndarray | None:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gold = cv2.inRange(hsv, (10, 120, 120), (45, 255, 255))
    count, _, stats, _ = cv2.connectedComponentsWithStats(gold)
    bars = [
        stats[index]
        for index in range(1, count)
        if stats[index, cv2.CC_STAT_WIDTH] > 8 * scale
        and stats[index, cv2.CC_STAT_HEIGHT] >= 30 * scale
        and stats[index, cv2.CC_STAT_AREA] > 250 * scale * scale
    ]
    if not bars:
        return None
    bar = max(bars, key=lambda item: item[cv2.CC_STAT_LEFT] + item[cv2.CC_STAT_WIDTH])
    start = int(bar[cv2.CC_STAT_LEFT] + bar[cv2.CC_STAT_WIDTH] + round(18 * scale))
    if start >= crop.shape[1]:
        return None
    glyphs = gold[:, start:]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(glyphs)
    digit_labels = [
        index for index in range(1, count)
        if stats[index, cv2.CC_STAT_HEIGHT] >= 18 * scale
        and stats[index, cv2.CC_STAT_AREA] >= 20 * scale * scale
    ]
    if not digit_labels:
        return None
    digits = np.zeros_like(glyphs)
    digits[np.isin(labels, digit_labels)] = 255
    ys, xs = np.where(digits > 0)
    pad = max(2, round(4 * scale))
    digits = digits[
        max(0, int(ys.min()) - pad):min(digits.shape[0], int(ys.max()) + pad + 1),
        max(0, int(xs.min()) - pad):min(digits.shape[1], int(xs.max()) + pad + 1),
    ]
    digits = cv2.resize(digits, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
    return cv2.copyMakeBorder(digits, 15, 15, 20, 20, cv2.BORDER_CONSTANT, value=0)


def _node_runtime() -> tuple[str, str]:
    return node_runtime()


def _run_ocr(crops: dict[str, np.ndarray]) -> dict[str, dict[str, Any]]:
    node, modules = _node_runtime()
    with tempfile.TemporaryDirectory(prefix="fulcrum-hud-") as temp:
        jobs = []
        for field, crop in crops.items():
            path = Path(temp) / f"{field}.png"
            if not cv2.imwrite(str(path), crop):
                raise OSError(f"could not write OCR crop: {path}")
            jobs.append({"name": field, "path": str(path), "psm": "13" if field == "hope_alt" else "7"})
        env = os.environ.copy()
        env["NODE_PATH"] = modules + os.pathsep + env.get("NODE_PATH", "")
        try:
            completed = subprocess.run(
                [node, str(OCR_SCRIPT)],
                input=json.dumps(jobs),
                text=True,
                capture_output=True,
                cwd=ROOT,
                env=env,
                timeout=60,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("local HUD OCR timed out") from exc
    if completed.returncode:
        raise RuntimeError(f"local HUD OCR failed: {completed.stderr.strip()}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("local HUD OCR returned invalid JSON") from exc


def _parse_field(field: str, text: str) -> dict[str, int] | None:
    clean = re.sub(r"[^0-9/]", "", text)
    if field in ("life", "experience"):
        match = re.fullmatch(r"(\d+)/(\d+)", clean)
        return {"current": int(match[1]), "max": int(match[2])} if match else None
    if not re.fullmatch(r"\d+", clean):
        return None
    value = int(clean)
    if field in ("level", "level_alt") and not 1 <= value <= 10:
        return None
    return {"value": value}


class HudRecognizer:
    def recognize_image(
        self,
        image: np.ndarray,
        *,
        viewport: tuple[int, int, int, int] | None = None,
    ) -> dict[str, Any]:
        if viewport is None:
            work, scale = working_image(image)
            viewport = tuple(round(value / scale) for value in detect_map_viewport(work))
        result = self._recognize_fit(image, viewport, 1.0)
        def quality(candidate):
            fields = candidate["fields"]
            important = ("life", "experience", "level", "action_points")
            return (sum(fields[key]["status"] == "recognized" for key in important),
                    sum(fields[key].get("ocrConfidence") or 0 for key in important))
        if quality(result)[0] < 4:
            compact = self._recognize_fit(image, viewport, 0.9)
            if quality(compact) > quality(result):
                result = compact
        return result

    def _recognize_fit(self, image, viewport, ui_scale):
        crops: dict[str, np.ndarray] = {}
        boxes: dict[str, tuple[int, int, int, int]] = {}
        shield_blank = False
        hope_digits_found = False
        for field in HUD_BOXES:
            x0, y0, x1, y1 = boxes[field] = _box(image, viewport, field, ui_scale)
            if x1 <= x0 or y1 <= y0:
                raise ValueError(f"HUD ROI falls outside screenshot: {field}")
            raw = image[y0:y1, x0:x1]
            if field == "action_points":
                continue
            if field == "shield":
                gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
                shield_blank = float(np.percentile(gray, 95)) < 80 and int(gray.max()) < 95
            if field == "hope":
                processed = _hope_digits(raw, image.shape[0] / 1152.0 * ui_scale)
                hope_digits_found = processed is not None
                if processed is not None:
                    crops[field] = processed
                    crops["hope_alt"] = processed
            elif field == "level":
                crops[field] = _level_digits(raw)
            else:
                crops[field] = _grayscale_crop(raw)

        ocr = _run_ocr(crops)
        hud_present = (
            _parse_field("life", str(ocr.get("life", {}).get("text", ""))) is not None
            and _parse_field("experience", str(ocr.get("experience", {}).get("text", ""))) is not None
        )
        fields: dict[str, dict[str, Any]] = {}
        for field in HUD_BOXES:
            if field == "level_alt":
                continue
            if field == "action_points":
                x0, y0, x1, y1 = boxes[field]
                fields[field] = {
                    **recognize_action(image[y0:y1, x0:x1], image.shape[0] / 1152 * ui_scale),
                    "roi": list(boxes[field]), "method": "cv_glyph_atlas",
                }
                continue
            observed = ocr.get(field, {"text": "", "confidence": None})
            if field == "level":
                alternative = ocr.get("level_alt", {"text": "", "confidence": None})
                if _parse_field(field, str(alternative["text"])) is not None and (
                    _parse_field(field, str(observed["text"])) is None
                    or (alternative["confidence"] or 0) > (observed["confidence"] or 0)
                ):
                    observed = alternative
                    boxes[field] = boxes["level_alt"]
            if field == "hope":
                alternative = ocr.get("hope_alt", {"text": "", "confidence": None})
                if _parse_field(field, str(alternative["text"])) is not None and (
                    _parse_field(field, str(observed["text"])) is None
                    or (alternative["confidence"] or 0) > (observed["confidence"] or 0)
                ):
                    observed = alternative
            text = str(observed["text"])
            parsed = _parse_field(field, text)
            status = "recognized" if parsed is not None else "unreadable"
            if parsed is not None and (observed["confidence"] or 0) < 40:
                status = "needs_review"
            if parsed is not None and field in {"life", "experience"}:
                if parsed["current"] > parsed["max"] and (field == "life" or parsed["max"] > 0):
                    status = "needs_review"
            if field == "shield" and parsed is None and shield_blank and hud_present:
                parsed = {"value": 0}
                status = "absent_zero"
            if field == "hope" and not hope_digits_found:
                parsed = None
                status = "unreadable"
            fields[field] = {
                **(parsed or ({"current": None, "max": None} if field in ("life", "experience") else {"value": None})),
                "status": status,
                "roi": list(boxes[field]),
                "ocrText": text,
                "ocrConfidence": observed["confidence"],
            }
        return {"backend": "local_tesseract_js", "hudScale": ui_scale, "fields": fields}
