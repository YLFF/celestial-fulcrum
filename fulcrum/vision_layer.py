from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class LayerObservation:
    label: str | None
    area: str | None
    floor: int | None
    roi: tuple[int, int, int, int] | None
    confidence: float

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "area": self.area,
            "floor": self.floor,
            "roi": list(self.roi) if self.roi else None,
            "confidence": self.confidence,
        }


def _curvature(labels: np.ndarray, index: int, box: np.ndarray) -> float:
    x, y, width, height, _ = box
    yy, xx = np.where(labels[y:y + height, x:x + width] == index)
    upper = xx[yy < height * 0.33]
    middle = xx[(yy >= height * 0.33) & (yy < height * 0.67)]
    lower = xx[yy >= height * 0.67]
    if not len(upper) or not len(middle) or not len(lower):
        return 0.0
    return float(np.mean(middle) - (np.mean(upper) + np.mean(lower)) / 2)


def recognize_layer(image: np.ndarray) -> LayerObservation:
    """Read the gold parenthesized layer marker, independent of its x offset."""
    height, width = image.shape[:2]
    scale = min(1.0, 2048 / width)
    if scale < 1.0:
        image = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    height, width = image.shape[:2]
    x0, x1 = round(width * 0.40), round(width * 0.59)
    y0, y1 = round(height * 0.035), round(height * 0.105)
    hsv = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    gold = cv2.inRange(hsv, (10, 70, 100), (47, 255, 255))
    count, labels, boxes, _ = cv2.connectedComponentsWithStats(gold)
    min_height = height * 0.013
    components = []
    for index in range(1, count):
        x, y, w, h, area = (int(value) for value in boxes[index])
        if not (min_height <= h <= height * 0.033 and 3 <= w <= height * 0.025 and area >= 18):
            continue
        components.append((index, x, y, w, h, area, _curvature(labels, index, boxes[index])))
    opens = [item for item in components if item[6] <= -0.55]
    closes = [item for item in components if item[6] >= 0.55]
    pairs = []
    for left in opens:
        for right in closes:
            gap = right[1] - left[1] - left[3]
            if not (4 <= gap <= height * 0.055):
                continue
            if abs(left[2] - right[2]) > height * 0.006 or abs(left[4] - right[4]) > height * 0.007:
                continue
            center_y = y0 + (left[2] + right[2]) / 2
            score = abs(left[6]) + abs(right[6]) - 0.5 * abs(center_y / height - 0.065)
            pairs.append((score, left, right))
    if not pairs:
        return LayerObservation(None, None, None, None, 0.0)
    _, left, right = max(pairs, key=lambda item: item[0])
    inner = [
        item for item in components
        if left[1] + left[3] <= item[1] and item[1] + item[3] <= right[1]
    ]
    # A question mark's detached lower dot is a reliable treehole cue.
    dots = [
        item for item in range(1, count)
        if boxes[item, cv2.CC_STAT_AREA] >= 4
        and boxes[item, cv2.CC_STAT_HEIGHT] <= left[4] * 0.35
        and left[1] + left[3] <= boxes[item, cv2.CC_STAT_LEFT]
        and boxes[item, cv2.CC_STAT_LEFT] + boxes[item, cv2.CC_STAT_WIDTH] <= right[1]
        and boxes[item, cv2.CC_STAT_TOP] >= left[2] + left[4] * 0.70
        and boxes[item, cv2.CC_STAT_TOP] <= left[2] + left[4]
    ]
    if len(dots) >= 2:
        label, area, floor = "treehole", "treehole", None
    else:
        glyphs = sorted(
            (item for item in inner if item[4] >= left[4] * 0.65 and item[5] >= 18),
            key=lambda item: item[1],
        )
        roman = "".join("V" if item[3] >= left[4] * 0.45 else "I" for item in glyphs)
        floor = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}.get(roman)
        if floor is None:
            return LayerObservation(None, None, None, None, 0.0)
        label, area = roman, "source_confluence" if floor == 6 else "main"
    rect = (
        round((x0 + left[1]) / scale),
        round((y0 + min(left[2], right[2])) / scale),
        round((x0 + right[1] + right[3]) / scale),
        round((y0 + max(left[2] + left[4], right[2] + right[4])) / scale),
    )
    return LayerObservation(label, area, floor, rect, 0.95)
