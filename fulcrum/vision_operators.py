"""Offline squad-card layout, name OCR and promotion observations."""

import csv
import io
import re
from time import perf_counter
import unicodedata

import cv2
import numpy as np

from .operator_catalog import operators
from .vision_node_text import make_label_sheet, run_label_ocr


def normalized_name(text):
    return re.sub(r"[^\w\u4e00-\u9fff]", "", unicodedata.normalize("NFKC", text)).casefold()


def match_name(text, catalog):
    name = normalized_name(text)
    if name in catalog:
        return catalog[name], True
    if len(name) >= 4:
        close = [value for candidate, value in catalog.items() if len(candidate) == len(name)
                 and sum(a != b for a, b in zip(candidate, name)) == 1]
        if len(close) == 1:
            return close[0], False
    return None, False


def _runs(values):
    edges = np.diff(np.r_[0, np.asarray(values, dtype=int), 0])
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def locate_cards(image):
    scale = 1280 / image.shape[1]
    small = cv2.resize(image, (1280, round(image.shape[0] * scale)))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    mask = cv2.morphologyEx((gray < 120).astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((7, 9), np.uint8))
    rectangles = [cv2.boundingRect(c) for c in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]]
    singles = [(x, y, w, h) for x, y, w, h in rectangles
               if 170 < w < 480 and 2.6 < w / h < 3.5 and y > 25 and y + h < .94 * gray.shape[0]]
    if len(singles) < 2:
        return []
    width, height = np.median([(w, h) for _, _, w, h in singles], axis=0)
    groups = []
    for x, y, w, h in sorted(rectangles):
        if abs(w - width) > width * .08 or h < height * .75 or y < 25:
            continue
        group = next((g for g in groups if abs(g[0] - x) < width * .08), None)
        if group is None:
            groups.append([x, [(y, h)]])
        else:
            group[1].append((y, h))
    if not 1 <= len(groups) <= 3:
        return []
    pitch = height * 1.105
    cards = []
    for column, (x, spans) in enumerate(groups):
        # Card ends remain visible even when temporary-recruit banners join contours.
        stripe = gray[:, round(x + .94 * width):round(x + .975 * width)]
        dark = (np.mean(stripe < 125, axis=1) > .65).astype(np.uint8)
        dark = cv2.morphologyEx(dark[:, None], cv2.MORPH_CLOSE, np.ones((3, 1), np.uint8)).ravel()
        ends = [b for a, b in _runs(dark) if b - a > .25 * height and b < gray.shape[0] * .94]
        anchors = [y + h for y, h in spans if h < height * 1.2]
        if not anchors or not ends:
            continue
        anchor = min(anchors)
        aligned = [end for end in ends if abs((end - anchor) / pitch - round((end - anchor) / pitch)) < .1]
        if not aligned:
            continue
        if len(aligned) > 1:
            differences = np.diff(sorted(aligned))
            regular = [value for value in differences if .85 * pitch < value < 1.15 * pitch]
            if regular:
                local_pitch = float(np.median(regular))
            else:
                local_pitch = pitch
        else:
            local_pitch = pitch
        bottom = min(aligned)
        # Presence checks handle the staggered 4/5/4 grid, including empty columns.
        limit = 5
        for row in range(limit):
            end = round(bottom + row * local_pitch)
            nearby = [value for value in aligned if abs(value - end) < .12 * height]
            if nearby:
                end = min(nearby, key=lambda value: abs(value - end))
            top = round(end - height)
            if top < 0 or end > .94 * gray.shape[0]:
                break
            band = gray[round(end - .19 * height):round(end - .03 * height),
                        round(x + .55 * width):round(x + .90 * width)]
            if band.size == 0 or np.mean(band < 135) < .65:
                continue
            box = [round(v / scale) for v in (x, top, x + width, end)]
            cards.append({"slot": f"{column + 1}-{row + 1}", "column": column + 1, "row": row + 1, "box": box})
    return cards


def _name_crop(image, box):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    crop = image[round(y1 - .32 * h):round(y1 - .02 * h), round(x0 + .49 * w):round(x1 - .045 * w)]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    count, _, stats, _ = cv2.connectedComponentsWithStats((gray > 170).astype(np.uint8))
    glyphs = [s for s in stats[1:count] if .075 * h <= s[3] <= .24 * h
              and s[1] + s[3] >= crop.shape[0] - .09 * h and s[4] >= .0006 * w * h]
    if not glyphs:
        return None
    left = max(0, min(s[0] for s in glyphs) - 2)
    right = gray.shape[1]
    top = max(0, min(s[1] for s in glyphs) - round(.025 * h))
    bottom = min(gray.shape[0], max(s[1] + s[3] for s in glyphs) + round(.015 * h))
    tight = 255 - gray[top:bottom, left:right]
    ink_y, ink_x = np.where(tight < 100)
    if len(ink_x):
        tight = tight[max(0, ink_y.min() - 2):ink_y.max() + 3, max(0, ink_x.min() - 2):ink_x.max() + 3]
    tight = cv2.resize(tight, None, fx=42 / tight.shape[0], fy=42 / tight.shape[0], interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(tight, 12, 12, 20, 20, cv2.BORDER_CONSTANT, value=255)


def _promotion(image, box):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    crop = image[round(y1 - .65 * h):round(y1 - .30 * h), x0:round(x0 + .20 * w)]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, (5, 130, 180), (40, 255, 255))
    fraction = float(np.mean(orange > 0))
    return {"elite": 2 if fraction > .045 else 1, "orangeFraction": round(fraction, 4)}


def _tokens(tsv, top, bottom):
    tokens = []
    fields = ("level", "page_num", "block_num", "par_num", "line_num", "word_num", "left", "top", "width", "height", "conf", "text")
    for row in csv.DictReader(io.StringIO(tsv or ""), delimiter="\t", fieldnames=fields, quoting=csv.QUOTE_NONE):
        if row.get("level") == "5" and row.get("text", "").strip():
            cy = float(row["top"]) + float(row["height"]) / 2
            if top <= cy < bottom:
                tokens.append((float(row["left"]), row["text"], float(row["conf"])))
    tokens.sort()
    text = "".join(row[1] for row in tokens)
    confidence = sum(len(row[1]) * row[2] for row in tokens) / max(1, sum(len(row[1]) for row in tokens))
    return text, round(confidence, 2)


class OperatorRecognizer:
    def recognize(self, path):
        image = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("无法读取编队截图")
        return self.recognize_image(image)

    def recognize_image(self, image):
        started = perf_counter()
        cards = locate_cards(image)
        crops = {card["slot"] + "|gray": (crop, card["box"]) for card in cards
                 if (crop := _name_crop(image, card["box"])) is not None}
        if not crops:
            return {"success": False, "reason": "未找到编队干员卡片，请截取完整编队页面。", "slots": []}
        catalog = {normalized_name(row["name"]): row for row in operators() if not row.get("repeatable")}
        crops.update({key.replace("|gray", "|binary|gray"): (cv2.threshold(crop, 105, 255, cv2.THRESH_BINARY)[1], box)
                      for key, (crop, box) in list(crops.items())})
        for card in cards:
            x0, y0, x1, y1 = card["box"]
            w, h = x1 - x0, y1 - y0
            for variant, fraction in (("tight", .23), ("line", .27)):
                crop = cv2.cvtColor(image[round(y1 - fraction * h):round(y1 - .025 * h),
                                          round(x0 + .50 * w):round(x1 - .045 * w)], cv2.COLOR_BGR2GRAY)
                crop = cv2.resize(255 - crop, None, fx=42 / crop.shape[0], fy=42 / crop.shape[0], interpolation=cv2.INTER_CUBIC)
                crops[card["slot"] + f"|{variant}|gray"] = cv2.copyMakeBorder(crop, 12, 12, 20, 20, cv2.BORDER_CONSTANT, value=255), card["box"]
        sheet, rows = make_label_sheet(crops)
        ocr = run_label_ocr(sheet, rows=rows, labels=[row["name"] for row in catalog.values()])
        retries = {row["key"]: row["tsv"] for row in ocr.get("lineResults", [])}
        slots = []
        for card in cards:
            key = card["slot"] + "|gray"
            if key not in rows:
                continue
            choices = []
            for variant in (key, key.replace("|gray", "|binary|gray"), key.replace("|gray", "|tight|gray"), key.replace("|gray", "|line|gray")):
                row = rows[variant]
                choices.append(_tokens(ocr.get("tsv"), row["top"], row["bottom"]))
                if variant in retries:
                    choices.append(_tokens(retries[variant], 0, row["bottom"] - row["top"]))
            def quality(pair):
                entry, exact = match_name(pair[0], catalog)
                return (2 if exact else 1 if entry and pair[1] >= 45 else 0, pair[1])
            text, confidence = max(choices, key=quality)
            entry, exact = match_name(text, catalog)
            if not exact and confidence < 45:
                entry = None
            accepted = bool(entry and exact and confidence >= (65 if len(normalized_name(text)) > 1 else 80))
            if len({normalized_name(value) for value, score in choices if normalized_name(value) in catalog and score >= 65}) > 1:
                accepted = False
            promotion = _promotion(image, card["box"])
            if entry and entry["rarity"] < 4:
                if promotion["elite"] == 2:
                    accepted = False
                promotion["elite"] = 1 if entry["rarity"] == 3 else 0
            slots.append({**card, "text": text, "confidence": confidence,
                          "operatorId": entry["id"] if entry else None, "name": entry["name"] if entry else None,
                          "status": "accepted" if accepted else "needs_review" if entry else "ignored",
                          **promotion})
        if len(slots) > 13:
            return {"success": False, "reason": "检测到的卡片布局超出编队范围，请重新截取编队页面。", "slots": []}
        return {"success": True, "slots": slots, "elapsedSeconds": round(perf_counter() - started, 3)}
