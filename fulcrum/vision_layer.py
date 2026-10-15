from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import subprocess

import cv2
import numpy as np


@dataclass(frozen=True)
class LayerObservation:
    label: str | None
    area: str | None
    floor: int | None
    roi: tuple[int, int, int, int] | None
    confidence: float
    source: str = "marker_geometry"
    candidates: tuple[tuple[str, float], ...] = ()

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "area": self.area,
            "floor": self.floor,
            "roi": list(self.roi) if self.roi else None,
            "confidence": self.confidence,
            "source": self.source,
            "candidates": [{"label": label, "score": score} for label, score in self.candidates],
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


def _recognize_geometry(image: np.ndarray) -> LayerObservation:
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
    question_heads = [box for box in boxes[1:]
                      if left[1] + left[3] <= box[cv2.CC_STAT_LEFT]
                      and box[cv2.CC_STAT_LEFT] + box[cv2.CC_STAT_WIDTH] <= right[1]
                      and box[cv2.CC_STAT_WIDTH] >= left[4] * .25
                      and box[cv2.CC_STAT_HEIGHT] >= left[4] * .45]
    # Resizing can join one question mark to its lower dot; Roman numerals have no such detached dot.
    if len(dots) >= 2 or (dots and len(question_heads) >= 2):
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


def _normalize_marker(mask: np.ndarray, height: int = 40) -> np.ndarray:
    ys, xs = np.where(mask > 0)
    if not len(xs):
        return np.zeros((height, height), np.uint8)
    tight = mask[ys.min():ys.max()+1, xs.min():xs.max()+1]
    return cv2.resize(tight, (max(1, round(tight.shape[1]*height/tight.shape[0])), height),
                      interpolation=cv2.INTER_AREA)


@lru_cache(maxsize=1)
def _marker_templates():
    path = Path(__file__).resolve().parents[1] / "assets/vision/layers/markers.npz"
    if not path.is_file():
        return ()
    with np.load(path) as data:
        return tuple((key.rsplit("_", 1)[0], _normalize_marker(data[key])) for key in data.files)


def _marker_groups(gold, image_height):
    count, _, stats, _ = cv2.connectedComponentsWithStats(gold)
    parts = [tuple(map(int, stats[i])) for i in range(1, count)
             if 4 <= stats[i, 4] and image_height*.003 <= stats[i, 3] <= image_height*.04
             and stats[i, 2] <= image_height*.05]
    groups = []
    for part in sorted(parts):
        x, y, w, h, _ = part
        for group in groups:
            gx, gy, gx1, gy1 = group
            gh = gy1-gy
            if x-gx1 <= max(h, gh)*.65 and min(y+h, gy1)-max(y, gy) >= min(h, gh)*.3:
                group[:] = [min(x, gx), min(y, gy), max(x+w, gx1), max(y+h, gy1)]
                break
        else:
            groups.append([x, y, x+w, y+h])
    return [box for box in groups if image_height*.009 <= box[3]-box[1] <= image_height*.04
            and .8 <= (box[2]-box[0])/(box[3]-box[1]) <= 4]


def _observation(label, roi, score, source, candidates=()):
    floor = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}.get(label)
    area = "treehole" if label == "treehole" else "source_confluence" if floor == 6 else "main" if floor else None
    return LayerObservation(label, area, floor, roi, round(score, 4), source, candidates)


def recognize_layer(image: np.ndarray) -> LayerObservation:
    """Compare complete gold markers; individual brackets are auxiliary evidence."""
    height, width = image.shape[:2]
    scale = min(1., 2048/width)
    work = cv2.resize(image, (round(width*scale), round(height*scale)), interpolation=cv2.INTER_AREA) if scale < 1 else image
    h, w = work.shape[:2]
    x0, y0, x1, y1 = round(w*.40), round(h*.035), round(w*.59), round(h*.105)
    gold = cv2.inRange(cv2.cvtColor(work[y0:y1, x0:x1], cv2.COLOR_BGR2HSV), (10,70,100), (47,255,255))
    scores, rectangles = {}, {}
    for left, top, right, bottom in _marker_groups(gold, h):
        query = _normalize_marker(gold[top:bottom, left:right])
        for label, reference in _marker_templates():
            ratio = query.shape[1]/reference.shape[1]
            if not .78 <= ratio <= 1.28:
                continue
            resized = cv2.resize(reference, (query.shape[1], 40), interpolation=cv2.INTER_AREA)
            padded = cv2.copyMakeBorder(query, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=0)
            score = float(cv2.matchTemplate(padded, resized, cv2.TM_CCOEFF_NORMED).max()) - .12*abs(np.log(ratio))
            if score > scores.get(label, -1):
                scores[label] = score
                rectangles[label] = tuple(round(value/scale) for value in (x0+left, y0+top, x0+right, y0+bottom))
    ranked = tuple((key, round(value, 4)) for key, value in sorted(scores.items(), key=lambda row: row[1], reverse=True))
    geometry = _recognize_geometry(image)
    if ranked:
        label, score = ranked[0]
        margin = score-ranked[1][1] if len(ranked) > 1 else 1
        if score >= .76 and margin >= .045:
            if geometry.label and geometry.label != label:
                return LayerObservation(None, None, None, None, 0., "marker_conflict", ranked)
            return _observation(label, rectangles[label], score, "whole_marker", ranked)
    if geometry.label:
        return LayerObservation(geometry.label, geometry.area, geometry.floor, geometry.roi,
                                geometry.confidence, "marker_geometry", ranked)
    return LayerObservation(None, None, None, None, 0., "unconfirmed", ranked)


def recognize_layer_title(image: np.ndarray) -> LayerObservation:
    """An independent, exact-name fallback; never infer a floor from a partial name."""
    from .vision_node_text import run_label_ocr

    h, w = image.shape[:2]
    box = (round(w*.40), 0, round(w*.64), round(h*.065))
    x0, y0, x1, y1 = box
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(255-gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    names = {"玻利瓦尔肤层": "I", "甜美的伤口": "II", "血色空脉": "III", "受害者腐殖": "IV",
             "卡德霍之颅": "V", "源流交汇处": "VI", "未萌生的摇篮": "treehole",
             "未亡者遗愿": "treehole", "全知者盲区": "treehole"}
    try:
        text = "".join(run_label_ocr(gray).get("text", "").split())
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        return LayerObservation(None, None, None, box, 0., "title_unavailable")
    found = {label for name, label in names.items() if name in text}
    if len(found) == 1:
        return _observation(found.pop(), box, .9, "title_text")
    return LayerObservation(None, None, None, box, 0., "title_unconfirmed")
