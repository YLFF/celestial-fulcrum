from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from time import perf_counter

import cv2
import numpy as np

from .runtime import node_runtime
from .diagnostics import public_error


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "chi_sim.traineddata"
SCRIPT = ROOT / "scripts/ocr_node_labels.mjs"
MIN_CONFIDENCE = 75.0


def normalize_label(text: str) -> str:
    return re.sub(r"[\s“”‘’\"'，。！？、:：;；·]+", "", text)


def label_crop(image, pixel, step, viewport, *, binarize=False):
    x, y = pixel
    left, top, right, bottom = viewport
    box = (max(left, round(x - .54 * step)), max(top, round(y + .12 * step)),
           min(right, round(x + .54 * step)), min(bottom, round(y + .56 * step)))
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return None
    crop = image[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 85), (179, 75, 255))
    count, components, stats, _ = cv2.connectedComponentsWithStats(mask)
    useful = [index for index in range(1, count)
              if max(5, .045 * step) <= stats[index, cv2.CC_STAT_HEIGHT] <= .20 * step
              and stats[index, cv2.CC_STAT_AREA] >= max(6, .0003 * step * step)]
    if len(useful) < 2:
        return None
    lines = []
    for index in sorted(useful, key=lambda index: stats[index, cv2.CC_STAT_TOP]):
        cy = stats[index, cv2.CC_STAT_TOP] + stats[index, cv2.CC_STAT_HEIGHT] / 2
        group = next((line for line in lines if abs(line[0] - cy) <= .04 * step), None)
        if group is None:
            lines.append((cy, [index]))
        else:
            group[1].append(index)
    lines = [indices for cy, indices in lines if len(indices) >= 2 and y0 + cy >= y + .19 * step]
    if not lines:
        return None
    useful = max(lines, key=lambda indices: sum(stats[index, cv2.CC_STAT_AREA] for index in indices))
    line_top = max(0, min(stats[index, cv2.CC_STAT_TOP] for index in useful) - round(.04 * step))
    line_bottom = min(mask.shape[0], max(stats[index, cv2.CC_STAT_TOP] + stats[index, cv2.CC_STAT_HEIGHT]
                                       for index in useful) + round(.04 * step))
    line_left = max(0, min(stats[index, cv2.CC_STAT_LEFT] for index in useful) - round(.04 * step))
    line_right = min(mask.shape[1], max(stats[index, cv2.CC_STAT_LEFT] + stats[index, cv2.CC_STAT_WIDTH]
                                      for index in useful) + round(.04 * step))
    line_mask = np.zeros_like(mask)
    line_mask[line_top:line_bottom, line_left:line_right] = mask[line_top:line_bottom, line_left:line_right]
    ys, xs = np.where(line_mask > 0)
    if xs.max() - xs.min() < .10 * step:
        return None
    # Labels are centered under their own node; reject clipped or off-center neighboring text.
    center = x0 + (xs.min() + xs.max()) / 2
    if abs(center - x) > .18 * step or xs.min() < 2 or xs.max() >= mask.shape[1] - 2:
        return None
    tight = cv2.cvtColor(crop[ys.min():ys.max() + 1, xs.min():xs.max() + 1], cv2.COLOR_BGR2GRAY)
    tight = cv2.normalize(255 - tight, None, 0, 255, cv2.NORM_MINMAX)
    scale = 40 / tight.shape[0]
    binary = cv2.resize(tight, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if binarize:
        binary = cv2.threshold(binary, 64, 255, cv2.THRESH_BINARY)[1]
    binary = cv2.copyMakeBorder(binary, 10, 10, 16, 16, cv2.BORDER_CONSTANT, value=255)
    return binary, box


def make_label_sheet(crops):
    width = max(crop.shape[1] for crop, _ in crops.values()) + 32
    height = sum(crop.shape[0] + 28 for crop, _ in crops.values())
    sheet = np.full((height, width), 255, np.uint8)
    rows, y = {}, 14
    for node_id, (crop, box) in crops.items():
        x = (width - crop.shape[1]) // 2
        sheet[y:y + crop.shape[0], x:x + crop.shape[1]] = crop
        rows[node_id] = {"top": y, "bottom": y + crop.shape[0], "box": list(box),
                         "glyphAspect": (crop.shape[1] - 32) / max(1, crop.shape[0] - 20)}
        y += crop.shape[0] + 28
    return sheet, rows


def decode_label_sheet(tsv, rows, labels):
    names = {normalize_label(name): node_id for node_id, name in labels.items()
             if node_id not in {"start", "node_type_020"}}
    words = {node_id: [] for node_id in rows}
    fields = ("level", "page_num", "block_num", "par_num", "line_num", "word_num",
              "left", "top", "width", "height", "conf", "text")
    for token in csv.DictReader(io.StringIO(tsv or ""), delimiter="\t", fieldnames=fields):
        if token.get("level") != "5" or not token.get("text", "").strip():
            continue
        try:
            center = int(token["top"]) + int(token["height"]) / 2
            confidence = float(token["conf"])
            left = int(token["left"])
        except (ValueError, KeyError):
            continue
        owners = [node_id for node_id, row in rows.items() if row["top"] <= center < row["bottom"]]
        if len(owners) == 1:
            words[owners[0]].append((left, token["text"], confidence))
    observations = {}
    for node_id, tokens in words.items():
        tokens.sort()
        text = "".join(token[1] for token in tokens)
        normalized = normalize_label(text)
        letters = sum(len(normalize_label(token[1])) for token in tokens)
        confidence = sum(len(normalize_label(token[1])) * token[2] for token in tokens) / letters if letters else 0.0
        category_id = names.get(normalized)
        if (any(token[2] < 30 for token in tokens)
                or (normalized == "作战" and rows[node_id].get("glyphAspect", 2) > 2.8)):
            category_id = None
        accepted = category_id is not None and confidence >= MIN_CONFIDENCE
        observations[node_id] = {"text": text, "confidence": round(confidence, 2),
                                 "categoryId": category_id if accepted else None,
                                 "candidateCategoryId": category_id,
                                 "status": "recognized" if accepted else "unconfirmed",
                                 "pixelBox": rows[node_id]["box"]}
    return observations


def run_label_ocr(sheet):
    node, modules = node_runtime()
    with tempfile.TemporaryDirectory(prefix="fulcrum-node-labels-") as temp:
        path = Path(temp) / "labels.png"
        if not cv2.imwrite(str(path), sheet):
            raise OSError("无法保存节点文字识别临时图")
        env = os.environ.copy()
        env["NODE_PATH"] = modules + os.pathsep + env.get("NODE_PATH", "")
        completed = subprocess.run([node, str(SCRIPT)], input=json.dumps({"path": str(path)}),
                                   text=True, encoding="utf-8", capture_output=True, cwd=ROOT, env=env,
                                   timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if completed.returncode:
        raise RuntimeError(f"节点文字识别失败：{completed.stderr.strip()}")
    return json.loads(completed.stdout)


class NodeLabelRecognizer:
    def __init__(self, labels):
        self.labels = labels

    def recognize(self, image, positions, step, viewport):
        started = perf_counter()
        if not MODEL.is_file():
            return {"status": "unavailable", "observations": {}, "reason": "缺少离线中文识别模型"}
        crops = {f"{node_id}|{method}": crop for node_id, pixel in positions.items()
                 for method in ("gray", "binary")
                 if (crop := label_crop(image, pixel, step, viewport, binarize=method == "binary")) is not None}
        if not crops:
            return {"status": "no_text", "observations": {}, "cropCount": 0, "acceptedCount": 0,
                    "elapsedMs": round((perf_counter() - started) * 1000, 1)}
        sheet, rows = make_label_sheet(crops)
        try:
            data = run_label_ocr(sheet)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            return {"status": "unavailable", "observations": {}, "reason": public_error(exc),
                    "diagnosticDetail": str(exc), "elapsedMs": round((perf_counter() - started) * 1000, 1)}
        variants = decode_label_sheet(data.get("tsv"), rows, self.labels)
        observations = {}
        for node_id in positions:
            choices = [{**variants[key], "method": method} for method in ("gray", "binary")
                       if (key := f"{node_id}|{method}") in variants]
            if not choices:
                continue
            accepted = [row for row in choices if row["categoryId"]]
            candidates = [row for row in choices if row["candidateCategoryId"] and row["confidence"] >= 50]
            chosen = max(accepted or candidates or choices, key=lambda row: row["confidence"])
            if len({row["categoryId"] for row in accepted}) > 1:
                chosen = {**chosen, "categoryId": None, "status": "conflict"}
            observations[node_id] = {**chosen, "variants": choices}
        return {"status": "completed", "observations": observations, "cropCount": len(crops),
                "acceptedCount": sum(row["status"] == "recognized" for row in observations.values()),
                "elapsedMs": round((perf_counter() - started) * 1000, 1),
                "model": "tessdata_fast/chi_sim", "minimumConfidence": MIN_CONFIDENCE}
