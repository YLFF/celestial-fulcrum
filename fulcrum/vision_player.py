"""Locate the left-side player avatar on a fitted map lattice."""

from __future__ import annotations

from typing import Any
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .map_model import MapNode
from .vision_geometry import working_image


@lru_cache(maxsize=1)
def _avatar_templates() -> tuple[np.ndarray, ...]:
    root = Path(__file__).resolve().parents[1] / "assets" / "vision"
    return tuple(template for path in sorted(root.glob("player_avatar_*.png"))
                 if (template := cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)) is not None)


def _avatar_score(white: np.ndarray, x: float, y: float, step: float) -> tuple[float, tuple[float, float] | None]:
    height, width = white.shape
    cx, cy = x - .25 * step, y
    x0, x1 = max(0, round(cx - .24 * step)), min(width, round(cx + .24 * step))
    y0, y1 = max(0, round(cy - .38 * step)), min(height, round(cy + .38 * step))
    patch = white[y0:y1, x0:x1]
    best, anchor = -1.0, None
    for template in _avatar_templates():
        for relative in (.7, .85, 1.0, 1.15, 1.3, 1.45):
            scale = step / 101 * relative
            resized = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            th, tw = resized.shape
            if patch.shape[0] < th or patch.shape[1] < tw:
                continue
            _, score, _, location = cv2.minMaxLoc(cv2.matchTemplate(patch, resized, cv2.TM_CCOEFF_NORMED))
            if score > best:
                best = score
                anchor = (x0 + location[0] + tw / 2, y0 + location[1] + th / 2)
    return best, anchor


def recognize_player_position(image: np.ndarray, nodes: list[MapNode]) -> dict[str, Any]:
    if not nodes:
        return {"status": "unreadable", "nodeId": None, "candidates": []}
    work, scale = working_image(image)
    xs = sorted({round(node.pixel[0] * scale) for node in nodes})
    ys = sorted({round(node.pixel[1] * scale) for node in nodes})
    gaps = [b - a for axis in (xs, ys) for a, b in zip(axis, axis[1:]) if b > a]
    if not gaps:
        return {"status": "unreadable", "nodeId": None, "candidates": []}
    step = min(gaps)
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    avatar_white = cv2.inRange(hsv, (0, 0, 205), (179, 80, 255))
    white = cv2.inRange(hsv, (0, 0, 150), (179, 120, 255))
    radius = max(2, int(step * 0.015))
    white = cv2.dilate(white, cv2.getStructuringElement(cv2.MORPH_RECT, (2 * radius + 1, 2 * radius + 1)))
    offsets = np.linspace(0.18, 0.45, 40) * step
    rows = []
    height, width = white.shape
    for node in nodes:
        x, y = round(node.pixel[0] * scale), round(node.pixel[1] * scale)
        rays = []
        for dx, dy in ((1, -1), (-1, 1)):
            px = np.rint(x + dx * offsets).astype(int)
            py = np.rint(y + dy * offsets).astype(int)
            inside = (px >= 0) & (px < width) & (py >= 0) & (py < height)
            rays.append(int(np.count_nonzero(white[py[inside], px[inside]])))
        avatar_score, anchor = _avatar_score(avatar_white, x, y, step)
        rows.append({"nodeId": node.coord.key, "score": round(avatar_score, 4), "rays": rays,
                     "anchorPixel": [round(value / scale, 1) for value in anchor] if anchor else None})
    rows.sort(key=lambda row: row["score"], reverse=True)
    best = rows[0]
    margin = best["score"] - (rows[1]["score"] if len(rows) > 1 else 0)
    recognized = best["score"] >= .60 and margin >= .10
    status = "recognized" if recognized else ("needs_review" if best["score"] >= .42 else "unreadable")
    return {
        "status": status,
        "nodeId": best["nodeId"] if status != "unreadable" else None,
        "score": best["score"],
        "margin": round(margin, 4),
        "source": "player_avatar",
        "anchorPixel": best["anchorPixel"] if status != "unreadable" else None,
        "candidates": rows[:3],
    }
