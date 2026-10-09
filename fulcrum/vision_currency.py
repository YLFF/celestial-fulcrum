"""Angular currency digits, kept separate from the action-point typeface."""

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

ATLAS = Path(__file__).resolve().parents[1] / "assets/vision/currency_digits.npz"


def currency_glyphs(crop, scale):
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 120), (179, 100, 255))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    bounds = [index for index in range(1, count)
              if stats[index, cv2.CC_STAT_HEIGHT] >= 18 * scale
              and stats[index, cv2.CC_STAT_AREA] >= 20 * scale * scale
              and 0 < stats[index, cv2.CC_STAT_LEFT]
              and stats[index, cv2.CC_STAT_LEFT] + stats[index, cv2.CC_STAT_WIDTH] < crop.shape[1]
              and 0 < stats[index, cv2.CC_STAT_TOP]
              and stats[index, cv2.CC_STAT_TOP] + stats[index, cv2.CC_STAT_HEIGHT] < crop.shape[0]
              and stats[index, cv2.CC_STAT_WIDTH] < stats[index, cv2.CC_STAT_HEIGHT] * .9]
    bounds.sort(key=lambda index: stats[index, cv2.CC_STAT_LEFT])
    if not 1 <= len(bounds) <= 6:
        return []
    glyphs = []
    for index in bounds:
        x, y, width, height, _ = stats[index]
        letter = (labels[y:y + height, x:x + width] == index).astype(np.uint8)
        ratio = min(28 / width, 44 / height)
        resized = cv2.resize(letter, (max(1, round(width * ratio)), max(1, round(height * ratio))),
                             interpolation=cv2.INTER_NEAREST)
        canvas = np.zeros((48, 32), dtype=np.uint8)
        top, left = (48 - resized.shape[0]) // 2, (32 - resized.shape[1]) // 2
        canvas[top:top + resized.shape[0], left:left + resized.shape[1]] = resized
        glyphs.append(canvas)
    return glyphs


@lru_cache(maxsize=1)
def _templates():
    with np.load(ATLAS) as bundle:
        return {digit: bundle[digit].astype(np.uint8) for digit in bundle.files}


def recognize_currency(crop, scale):
    glyphs = currency_glyphs(crop, scale)
    if not glyphs:
        return {"value": None, "status": "unreadable", "digitCount": 0}
    ranked = [sorted((float(np.mean(np.abs(glyph.astype(np.int16) - reference.astype(np.int16)))), digit)
                     for digit, reference in _templates().items()) for glyph in glyphs]
    distance = max(row[0][0] for row in ranked)
    margin = min(row[1][0] - row[0][0] for row in ranked)
    digits = ''.join(row[0][1] for row in ranked)
    status = "recognized" if distance <= .12 and margin >= .025 else "needs_review" if distance <= .20 else "unreadable"
    return {"value": int(digits) if status != "unreadable" else None, "status": status,
            "digits": digits, "digitCount": len(glyphs), "matchScore": round(1 - distance, 3),
            "matchMargin": round(margin, 3)}
