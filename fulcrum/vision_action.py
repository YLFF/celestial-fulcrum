"""Read the fixed action-point digits from the map HUD."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np


ATLAS = Path(__file__).resolve().parents[1] / "assets" / "vision" / "action_digits.npz"
NORMAL_SIZE = (32, 48)


def action_glyphs(crop: np.ndarray, scale: float) -> list[np.ndarray]:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 140), (179, 100, 255))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    bounds = [
        (index, *(int(value) for value in stats[index]))
        for index in range(1, count)
        if stats[index, cv2.CC_STAT_HEIGHT] >= 30 * scale
        and stats[index, cv2.CC_STAT_WIDTH] >= 3 * scale
        and stats[index, cv2.CC_STAT_AREA] >= 40 * scale * scale
        and stats[index, cv2.CC_STAT_LEFT] > 0 and stats[index, cv2.CC_STAT_TOP] > 0
        and stats[index, cv2.CC_STAT_LEFT] + stats[index, cv2.CC_STAT_WIDTH] < crop.shape[1]
        and stats[index, cv2.CC_STAT_TOP] + stats[index, cv2.CC_STAT_HEIGHT] < crop.shape[0]
    ]
    bounds.sort(key=lambda row: row[1])
    if not 1 <= len(bounds) <= 2:
        return []
    glyphs = []
    for index, x, y, width, height, _ in bounds:
        letter = (labels[y:y + height, x:x + width] == index).astype(np.uint8)
        target_width, target_height = NORMAL_SIZE
        ratio = min((target_width - 4) / width, (target_height - 4) / height)
        resized = cv2.resize(letter, (max(1, round(width * ratio)), max(1, round(height * ratio))),
                             interpolation=cv2.INTER_NEAREST)
        canvas = np.zeros((target_height, target_width), dtype=np.uint8)
        left = (target_width - resized.shape[1]) // 2
        top = (target_height - resized.shape[0]) // 2
        canvas[top:top + resized.shape[0], left:left + resized.shape[1]] = resized
        glyphs.append(canvas)
    return glyphs


@lru_cache(maxsize=1)
def _templates() -> dict[str, np.ndarray]:
    with np.load(ATLAS) as bundle:
        return {digit: bundle[digit].astype(np.uint8) for digit in bundle.files}


def recognize_action(crop: np.ndarray, scale: float) -> dict[str, Any]:
    glyphs = action_glyphs(crop, scale)
    if not glyphs:
        return {"value": None, "status": "unreadable", "matchScore": None, "digits": None}
    templates = _templates()
    results = []
    margins = []
    for glyph in glyphs:
        distances = sorted(
            (float(np.mean(np.abs(glyph.astype(np.int16) - template.astype(np.int16)))), digit)
            for digit, template in templates.items()
        )
        results.append(distances[0])
        margins.append(distances[1][0] - distances[0][0])
    score = max(distance for distance, _ in results)
    digits = "".join(digit for _, digit in results)
    margin = min(margins)
    status = "recognized" if score <= 0.12 and margin >= 0.025 else ("needs_review" if score <= 0.22 else "unreadable")
    return {"value": int(digits) if status != "unreadable" else None,
            "status": status, "matchScore": round(1 - score, 3), "matchMargin": round(margin, 3),
            "digits": digits if status != "unreadable" else None}
