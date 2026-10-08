"""Independent, read-only visible relic row recognition using the local atlas."""

from functools import lru_cache
import json
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

from .vision_geometry import working_image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets/vision/relics"


@lru_cache(maxsize=1)
def relic_atlas():
    entries = json.loads((ROOT / "data/lubiao_reference_catalog.json").read_text(encoding="utf-8"))["entries"]
    result = []
    for entry in entries:
        if entry["category"] != "relic":
            continue
        icon = cv2.imread(str(ROOT / entry["imagePath"]))
        if icon is not None:
            result.append((entry["id"], entry["name"], icon))
    return result


@lru_cache(maxsize=12)
def scaled_atlas(label_width):
    templates = []
    for relic_id, name, icon in relic_atlas():
        variants = []
        for side in sorted({round(label_width * factor) for factor in (.75, .83, .91, .98, 1.06)}):
            template = cv2.resize(icon, (side, side), interpolation=cv2.INTER_AREA)
            yy, xx = np.indices((side, side))
            # Atlas images include unrelated UI at their edges; compare the item core.
            mask = (((xx-side/2)**2+(yy-side/2)**2) < (side*.40)**2).astype(np.uint8)*255
            variants.append((template, mask))
        templates.append((relic_id, name, variants))
    return templates


def locate_label(image, filename, region, scale_hint=None):
    reference = cv2.imread(str(ASSETS / filename), cv2.IMREAD_GRAYSCALE)
    if reference is None:
        raise FileNotFoundError(f"missing relic HUD anchor: {filename}")
    x0, y0, x1, y1 = region
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    best = None
    scales = np.arange(.65, 1.81, .05) if scale_hint is None else [scale_hint * f for f in (.9, .95, 1, 1.05, 1.1)]
    for scale in scales:
        template = cv2.resize(reference, None, fx=scale, fy=scale)
        h, w = template.shape
        if gray.shape[0] < h or gray.shape[1] < w:
            continue
        scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, at = cv2.minMaxLoc(scores)
        if best is None or score > best["score"]:
            best = {"score": float(score), "box": [at[0]+x0, at[1]+y0, w, h], "scale": float(scale)}
    return best if best and best["score"] >= .72 else None


def rank_slot(image, center, label_width, right):
    cx, cy = center
    radius = round(label_width * .60)
    x0, y0 = max(0, round(cx-radius)), max(0, round(cy-radius))
    x1, y1 = min(image.shape[1], round(cx+radius)), min(image.shape[0], round(cy+radius))
    patch = image[y0:y1, x0:x1]
    ranked = []
    for relic_id, name, variants in scaled_atlas(label_width):
        best = -1.0
        for template, mask in variants:
            side = template.shape[0]
            if patch.shape[0] < side or patch.shape[1] < side:
                continue
            if right < cx+label_width*.48:
                mask = mask.copy()
                mask[:, max(0, round(right-cx+side/2)):] = 0
                if np.count_nonzero(mask) < 40:
                    continue
            scores = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED, mask=mask)
            slack = max(3, label_width * .10)
            tx, ty = cx-x0-side/2, cy-y0-side/2
            local = scores[max(0, round(ty-slack)):min(scores.shape[0], round(ty+slack)+1),
                           max(0, round(tx-slack)):min(scores.shape[1], round(tx+slack)+1)]
            finite = local[np.isfinite(local)]
            if finite.size:
                best = max(best, min(1.0, float(finite.max())))
        ranked.append({"id": relic_id, "name": name, "score": round(best, 4)})
    ranked.sort(key=lambda row: row["score"], reverse=True)
    half = label_width * .48
    box = [max(0, round(cx-half)), max(0, round(cy-half)),
           min(right, round(cx+half)), min(image.shape[0], round(cy+half))]
    visible = min(1.0, max(0.0, (right-(cx-half))/(2*half)))
    return ranked[:5], box, visible


class RelicRecognizer:
    def recognize(self, path):
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError("could not decode relic screenshot")
        return self.recognize_image(image)

    def recognize_image(self, original):
        started = perf_counter()
        image, factor = working_image(original)
        height, width = image.shape[:2]
        anchor = locate_label(image, "inventory_label.png", (0, round(height*.65), round(width*.45), height))
        if anchor is None:
            return {"success": False, "reason": "未找到收藏品字样，请提供包含底部收藏品栏的游戏截图。",
                    "slots": [], "acceptedRelicIds": [], "elapsedSeconds": round(perf_counter()-started, 3)}
        x, y, w, h = anchor["box"]
        appraisal = locate_label(image, "appraisal_label.png", (x+w, round(height*.65), round(width*.80), height), anchor["scale"])
        if appraisal is None:
            return {"success": False, "reason": "未能确认收藏品栏右侧边界，未导入任何藏品。",
                    "slots": [], "acceptedRelicIds": [], "elapsedSeconds": round(perf_counter()-started, 3)}
        right = round(appraisal["box"][0] - .85*w)
        cx, cy = x+w*1.68, y-h*.39
        stride = w*.955
        slots = []
        while cx-w*.48 < right and len(slots) < 30:
            candidates, box, visible = rank_slot(image, (cx, cy), w, right)
            best, runner_up = candidates[:2]
            gap = best["score"]-runner_up["score"]
            if best["score"] < .50:
                break
            partial = visible < .9
            accepted = not partial and (best["score"] >= .78 and gap >= .055 or best["score"] >= .90 and gap >= .025)
            slots.append({"slot": len(slots)+1, "id": best["id"], "name": best["name"],
                          "score": best["score"], "margin": round(gap, 4),
                          "status": "accepted" if accepted else "needs_review", "partial": partial,
                          "visibleFraction": round(visible, 3), "box": [round(v/factor) for v in box],
                          "candidates": candidates})
            cx += stride
        return {"success": True, "labelBox": [round(v/factor) for v in (x, y, x+w, y+h)],
                "labelScore": round(anchor["score"], 4),
                "rowBox": [round(v/factor) for v in (x+w, cy-w*.6, right, cy+w*.6)],
                "slots": slots, "acceptedRelicIds": list(dict.fromkeys(row["id"] for row in slots if row["status"] == "accepted")),
                "elapsedSeconds": round(perf_counter()-started, 3)}
