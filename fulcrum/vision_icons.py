from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .vision_geometry import Circle


ROOT = Path(__file__).resolve().parents[1]


def node_patch(image, pixel, step, *, target_step=150, radius_fraction=.72):
    """Keep original node detail while bounding the work done by local retries."""
    radius = round(step*radius_fraction)
    x, y = pixel
    left, top = max(0, round(x-radius)), max(0, round(y-radius))
    right, bottom = min(image.shape[1], round(x+radius)), min(image.shape[0], round(y+radius))
    patch = image[top:bottom, left:right]
    if not patch.size or step <= 0:
        return None
    factor = min(1., target_step/step)
    if factor != 1.:
        patch = cv2.resize(patch, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    return patch, ((x-left)*factor, (y-top)*factor), step*factor


@dataclass(frozen=True)
class IconMatch:
    id: str
    name: str
    score: float
    runner_up_score: float


class IconMatcher:
    def __init__(self, root: Path = ROOT) -> None:
        labels = json.loads((root / "data" / "vision_labels.json").read_text(encoding="utf-8"))
        self.node_labels: dict[str, str] = labels["nodeTypes"]
        self.mark_labels: dict[str, str] = labels["nodeMarks"]
        self.node_templates: list[tuple[str, np.ndarray]] = []
        for node_id in self.node_labels:
            path = root / "assets" / "lubiao" / "node_type" / f"{node_id}.png"
            if path.exists():
                image = cv2.imread(str(path))
                if image is not None:
                    self.node_templates.append((node_id, image))
        for path in sorted((root / "assets" / "vision").glob("*.png")):
            node_id = path.stem.rsplit("_", 1)[0]
            if node_id not in self.node_labels:
                continue
            image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if image is not None:
                self.node_templates.append((node_id, image))
        self.mark_templates: list[tuple[str, np.ndarray]] = []
        self.body_templates = []
        counts = {}
        for kind, icon in self.node_templates:
            if counts.get(kind, 0) >= 3:
                continue
            counts[kind] = counts.get(kind, 0)+1
            yy, xx = np.ogrid[:icon.shape[0], :icon.shape[1]]
            mask = (((xx-(icon.shape[1]-1)/2)**2+(yy-(icon.shape[0]-1)/2)**2)
                    <= (min(icon.shape[:2])*.34)**2).astype(np.uint8)*255
            if icon.shape[2] == 4:
                mask = cv2.bitwise_and(mask, icon[:, :, 3])
            self.body_templates.append((kind, np.dstack((icon[:, :, :3], mask))))
        for mark_id in self.mark_labels:
            path = root / "assets" / "lubiao" / "node_mark" / f"{mark_id}.png"
            if path.exists():
                image = cv2.imread(str(path))
                if image is not None:
                    self.mark_templates.append((mark_id, image))
        for path in sorted((root / "assets" / "vision").glob("node_mark_*_*.png")):
            mark_id = path.stem.rsplit("_", 1)[0]
            if mark_id in self.mark_labels:
                image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
                if image is not None:
                    self.mark_templates.append((mark_id, image))
        self.empty_template = cv2.imread(
            str(root / "assets" / "vision" / "empty_connector.png"), cv2.IMREAD_GRAYSCALE
        )
        self.connector_templates = [template for filename in ("connector_dark.png", "connector_bright.png")
                                    if (template := cv2.imread(str(root / "assets" / "vision" / filename), cv2.IMREAD_GRAYSCALE)) is not None]

    @staticmethod
    def _score(
        image: np.ndarray,
        pixel: tuple[float, float],
        step: float,
        icon: np.ndarray,
        scales: tuple[float, ...],
        *,
        search_fraction: float = 0.12,
        radius_fraction: float = 0.59,
        locate: bool = False,
    ):
        height, width = image.shape[:2]
        radius = min(115, max(55, round(step * radius_fraction)))
        x, y = round(pixel[0]), round(pixel[1])
        x0, x1 = max(0, x - radius), min(width, x + radius)
        y0, y1 = max(0, y - radius), min(height, y + radius)
        patch = image[y0:y1, x0:x1]
        best = -1.0
        best_location = None
        for scale in scales:
            template = cv2.resize(icon, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            th, tw = template.shape[:2]
            if patch.shape[0] < th or patch.shape[1] < tw:
                continue
            # A label or nearby icon must not win a search far from the mapped cell.
            cx = x - x0 - tw / 2
            cy = y - y0 - th / 2
            slack = max(9, step * search_fraction)
            left = max(0, int(cx - slack))
            right = min(patch.shape[1] - tw + 1, int(cx + slack) + 1)
            top = max(0, int(cy - slack))
            bottom = min(patch.shape[0] - th + 1, int(cy + slack) + 1)
            if left < right and top < bottom:
                search = patch[top:bottom + th - 1, left:right + tw - 1]
                if template.ndim == 3 and template.shape[2] == 4:
                    local = cv2.matchTemplate(search, template[:, :, :3], cv2.TM_CCOEFF_NORMED,
                                             mask=template[:, :, 3])
                else:
                    local = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
                finite = local[np.isfinite(local)]
                if finite.size:
                    value = min(1.0, float(np.max(finite)))
                    if value > best:
                        best = value
                        if locate:
                            safe = np.where(np.isfinite(local), local, -1)
                            _, _, _, peak = cv2.minMaxLoc(safe)
                            best_location = (x0+left+peak[0]+tw/2, y0+top+peak[1]+th/2, tw, th)
        return (best, best_location) if locate else best

    def _empty_score(self, image: np.ndarray, pixel: tuple[float, float], circles: list[Circle]) -> float:
        x, y = pixel
        near = [circle for circle in circles if circle.source not in {"label", "color"}
                and abs(circle.x - x) < 13 and abs(circle.y - y) < 13]
        if near:
            radius = min(circle.radius for circle in near)
            if radius <= 16:
                xi, yi = round(x), round(y)
                left, top = max(0, xi - 22), max(0, yi - 22)
                patch = image[top:yi + 23, left:xi + 23]
                hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
                yy, xx = np.ogrid[:patch.shape[0], :patch.shape[1]]
                core = (xx - (xi - left)) ** 2 + (yy - (yi - top)) ** 2 <= radius ** 2
                colorful = core & (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 60)
                if np.count_nonzero(colorful) / max(1, np.count_nonzero(core)) < .08:
                    return 1.0 if radius <= 13 else 0.9
        templates = self.connector_templates + ([self.empty_template] if self.empty_template is not None else [])
        if not templates:
            return -1.0
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        score = max(self._score(gray, pixel, 60, template, (0.65, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5)) for template in templates)
        if .60 <= score < .72:
            # A dim connector under the player's crosshair can evade the full-map circle detector.
            xi, yi = round(x), round(y)
            left, top = max(0, xi - 24), max(0, yi - 24)
            patch = image[top:yi + 25, left:xi + 25]
            local = cv2.HoughCircles(cv2.GaussianBlur(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), (3, 3), .5),
                                     cv2.HOUGH_GRADIENT, dp=1, minDist=15, param1=60, param2=15,
                                     minRadius=5, maxRadius=13)
            if local is not None:
                for cx, cy, radius in local[0]:
                    if np.hypot(left + cx - x, top + cy - y) > 13:
                        continue
                    yy, xx = np.ogrid[:patch.shape[0], :patch.shape[1]]
                    core = (xx - cx) ** 2 + (yy - cy) ** 2 <= (radius + 2) ** 2
                    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
                    colorful = core & (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 60)
                    if np.count_nonzero(colorful) / np.count_nonzero(core) < .08:
                        return .9
        return score if score >= 0.72 else -1.0

    def classify_node(
        self, image: np.ndarray, pixel: tuple[float, float], step: float, circles: list[Circle], *,
        dystopia: bool = False, has_label: bool = False
    ) -> tuple[IconMatch | None, list[IconMatch]]:
        empty_score = self._empty_score(image, pixel, circles)
        trusted_connector = any(circle.source == "connector" and circle.radius <= .13*step
                                and np.hypot(circle.x-pixel[0], circle.y-pixel[1]) <= .08*step for circle in circles)
        large_rim = any((circle.source != "contrast" or not trusted_connector)
                        and .18*step <= circle.radius <= .46*step and
                        np.hypot(circle.x-pixel[0], circle.y-pixel[1])
                        <= (.25 if circle.source == "contrast" else .16)*step for circle in circles)
        if has_label or large_rim:
            empty_score = -1.
        if empty_score >= .85:
            match = IconMatch("node_type_020", self.node_labels["node_type_020"], round(empty_score, 4), 0.0)
            return match, [match]
        texture_scores = []
        if dystopia:
            from .vision_dystopia import classify_texture
            texture_scores = classify_texture(image, pixel, step)
            soil_empty = dict(texture_scores).get("node_type_020", -1)
            if soil_empty >= .82:
                x, y = map(round, pixel)
                radius = max(5, round(step * .12))
                core = image[max(0, y-radius):y+radius+1, max(0, x-radius):x+radius+1]
                hsv = cv2.cvtColor(core, cv2.COLOR_BGR2HSV)
                if np.mean((hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 60)) < .12:
                    empty_score = max(empty_score, soil_empty)
                    other = max((score for kind, score in texture_scores if kind != "node_type_020"), default=-1.)
                    reliable_rim = any(circle.source != "contrast" and .18*step <= circle.radius <= .46*step
                                       and np.hypot(circle.x-pixel[0], circle.y-pixel[1]) <= .16*step for circle in circles)
                    if not has_label and not reliable_rim and soil_empty >= .90 and soil_empty-other >= .12:
                        match = IconMatch("node_type_020", self.node_labels["node_type_020"], round(soil_empty, 4), round(other, 4))
                        return match, [match]
            if texture_scores[0][0] == "node_type_020" and texture_scores[0][1] >= .78:
                empty_score = max(empty_score, texture_scores[0][1])
        if has_label or large_rim:
            empty_score = -1.
        if empty_score >= 0.85 or (not has_label and not large_rim and texture_scores and texture_scores[0][0] == "node_type_020"
                                and texture_scores[0][1] >= .76
                                and texture_scores[0][1]-texture_scores[1][1] >= .08):
            match = IconMatch("node_type_020", self.node_labels["node_type_020"], round(empty_score, 4), 0.0)
            return match, [match]
        scores: dict[str, float] = {}
        for node_id, icon in self.node_templates:
            scales = (0.55, 0.60, 0.65, 0.75, 0.85, 1.0, 1.15, 1.3, 1.45, 1.6, 1.8, 2.0)
            value = self._score(image, pixel, step, icon, scales)
            scores[node_id] = max(value, scores.get(node_id, -1.0))
        for node_id, score in texture_scores:
            if node_id != "node_type_020":
                scores[node_id] = max(score, scores.get(node_id, -1.0))
        if dystopia:
            from .vision_dystopia import clean_textures
            for node_id, icon in clean_textures():
                score = self._score(image, pixel, step, icon, tuple(step/100 * factor for factor in (.7, .85, 1, 1.15, 1.3)))
                scores[node_id] = max(score, scores.get(node_id, -1.0))
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            return None, []
        node_id, score = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else -1.0
        if score-second < .05 or (has_label and node_id == "node_type_020"):
            body_scores = {}
            contenders = {kind for kind, _ in ranked[:4]}
            for kind, core in self.body_templates:
                if kind not in contenders:
                    continue
                value = self._score(image, pixel, step, core, (.55,.65,.75,.85,1.,1.15,1.3,1.45,1.6,1.8,2.))
                body_scores[kind] = max(value, body_scores.get(kind, -1))
            body_ranked = sorted(body_scores.items(), key=lambda row: row[1], reverse=True)
            if len(body_ranked) > 1 and body_ranked[0][1] >= .70 and body_ranked[0][1]-body_ranked[1][1] >= .08:
                kind, value = body_ranked[0]
                match = IconMatch(kind, self.node_labels[kind], round(value,4), round(body_ranked[1][1],4))
                return match, [match]+[IconMatch(key, self.node_labels[key], round(val,4),0.)
                                      for key,val in body_ranked[1:3]]
        if (not dystopia and score >= 0.70 and score - second < 0.035
                and {item_id for item_id, _ in ranked[:2]} == {"node_type_001", "node_type_002"}):
            # Ordinary and emergency fights share a silhouette; exclude the dark background for the close tie.
            foreground_scores = {}
            for item_id, icon in self.node_templates:
                if item_id not in {"node_type_001", "node_type_002"}:
                    continue
                color = icon[:, :, :3]
                mask = (np.max(color, axis=2) > 35).astype(np.uint8) * 255
                foreground = np.dstack((color, mask))
                value = self._score(image, pixel, step, foreground, scales)
                foreground_scores[item_id] = max(value, foreground_scores.get(item_id, -1.0))
            foreground_ranked = sorted(foreground_scores.items(), key=lambda item: item[1], reverse=True)
            if (foreground_ranked[0][1] >= 0.80
                    and foreground_ranked[0][1] - foreground_ranked[1][1] >= 0.05):
                scores.update(foreground_scores)
                ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
                node_id, score = ranked[0]
                second = ranked[1][1]
        if empty_score >= 0.72 and score < 0.60:
            match = IconMatch("node_type_020", self.node_labels["node_type_020"], round(empty_score, 4), round(score, 4))
            return match, [match]
        candidates = [
            IconMatch(
                item_id,
                self.node_labels[item_id],
                round(value, 4),
                round(ranked[index + 1][1], 4) if index + 1 < len(ranked) else 0.0,
            )
            for index, (item_id, value) in enumerate(ranked[:3])
        ]
        if score < 0.46 or (score - second < 0.035 and not (score >= 0.80 and score - second >= 0.025)):
            return None, candidates
        return IconMatch(node_id, self.node_labels[node_id], round(score, 4), round(second, 4)), candidates

    def confirm_text_candidate(self, image, pixel, step, category_id, *, minimum=.60, include_background=False,
                               search_fraction=.12):
        scores = []
        for node_id, icon in self.node_templates:
            if node_id != category_id:
                continue
            color = cv2.cvtColor(icon, cv2.COLOR_GRAY2BGR) if icon.ndim == 2 else icon[:, :, :3]
            mask = (np.max(color, axis=2) > 35).astype(np.uint8) * 255
            if icon.ndim == 3 and icon.shape[2] == 4:
                mask = cv2.bitwise_and(mask, icon[:, :, 3])
            if not np.count_nonzero(mask):
                continue
            foreground = np.dstack((color, mask))
            scores.append(self._score(image, pixel, step, foreground,
                                      (.55, .60, .65, .75, .85, 1., 1.15, 1.3, 1.45, 1.6, 1.8, 2.),
                                      search_fraction=search_fraction))
            if include_background:
                scores.append(self._score(image, pixel, step, icon,
                    (.55,.60,.65,.75,.85,1.,1.15,1.3,1.45,1.6,1.8,2.), search_fraction=search_fraction))
        score = max(scores, default=-1)
        return IconMatch(category_id, self.node_labels[category_id], round(score, 4), 0.0) if score >= minimum else None

    def refine_node(self, image, pixel, step, category_ids, *, has_label=False):
        local = node_patch(image, pixel, step)
        if local is None:
            return None
        patch, anchor, spacing = local
        contenders = set(category_ids)-{"start", "node_type_020"}
        scores = {}
        scales = tuple(spacing/100*factor for factor in (.55, .65, .75, .85, 1., 1.15, 1.3, 1.45, 1.6, 1.8))
        for kind, icon in self.node_templates + self.body_templates:
            if kind in contenders:
                score = self._score(patch, anchor, spacing, icon, scales, search_fraction=.16)
                scores[kind] = max(scores.get(kind, -1.), score)
        ranked = sorted(scores.items(), key=lambda row: row[1], reverse=True)
        if not ranked:
            return None
        kind, score = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else -1.
        minimum, margin = (.78, .08) if kind.startswith("unknown_") else (.72, .07)
        if score < minimum or score-second < margin:
            return None
        return IconMatch(kind, self.node_labels[kind], round(score, 4), round(second, 4))

    def refine_marks(self, image, pixel, step, *, area=None, floor=None):
        local = node_patch(image, pixel, step)
        if local is None:
            return []
        patch, anchor, spacing = local
        left, top = max(0, round(anchor[0]-.03*spacing)), max(0, round(anchor[1]-.48*spacing))
        badge = patch[top:round(anchor[1]+.04*spacing), left:round(anchor[0]+.49*spacing)]
        if not badge.size:
            return []
        hsv = cv2.cvtColor(badge, cv2.COLOR_BGR2HSV)
        if np.count_nonzero((hsv[:, :, 1] < 115) & (hsv[:, :, 2] > 130)) < max(14, spacing*.3):
            return []
        rings = cv2.HoughCircles(cv2.cvtColor(badge, cv2.COLOR_BGR2GRAY), cv2.HOUGH_GRADIENT,
            dp=1, minDist=10, param1=80, param2=14, minRadius=max(6, round(spacing*.09)), maxRadius=round(spacing*.27))
        if rings is None:
            return []
        angles = np.linspace(0, 2*np.pi, 48, endpoint=False)
        supported = False
        for cx, cy, radius in rings[0]:
            if np.hypot(cx-.23*spacing, cy-.30*spacing) > .17*spacing:
                continue
            xs = np.rint(cx+radius*np.cos(angles)).astype(int)
            ys = np.rint(cy+radius*np.sin(angles)).astype(int)
            if xs.min() < 0 or ys.min() < 0 or xs.max() >= hsv.shape[1] or ys.max() >= hsv.shape[0]:
                continue
            colors = hsv[ys, xs]
            if np.mean((colors[:, 1] < 115) & (colors[:, 2] > 130)) >= .65:
                supported = True
                break
        if not supported:
            return []
        marks = self.detect_marks(patch, anchor, spacing, area=area, floor=floor)
        return [{**mark, "resolution": "original_patch"} for mark in marks]

    def _badge_core(self, image, pixel, step, coarse, area, floor):
        from .node_identity import contextual_mark_id

        if not coarse or max(coarse.values()) < .55:
            return []
        x0, y0 = max(0, round(pixel[0]-.03*step)), max(0, round(pixel[1]-.48*step))
        patch = image[y0:round(pixel[1]+.04*step), x0:round(pixel[0]+.49*step)]
        if patch.size == 0:
            return []
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        if np.count_nonzero((hsv[:,:,1] < 115) & (hsv[:,:,2] > 130)) < max(14, step*.3):
            return []
        rings = cv2.HoughCircles(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), cv2.HOUGH_GRADIENT,
            dp=1, minDist=10, param1=80, param2=14, minRadius=max(6,round(step*.09)), maxRadius=round(step*.27))
        if rings is None:
            return []
        scores, peaks = {}, {}
        for source_id, icon in self.mark_templates:
            mark_id = contextual_mark_id(source_id, area, floor)
            if mark_id is None or (max(coarse.values()) >= .65 and coarse.get(mark_id, -1) < max(coarse.values())-.23):
                continue
            yy, xx = np.ogrid[:icon.shape[0], :icon.shape[1]]
            mask = (((xx-(icon.shape[1]-1)/2)**2+(yy-(icon.shape[0]-1)/2)**2)
                    <= (min(icon.shape[:2])*.34)**2).astype(np.uint8)*255
            if icon.shape[2] == 4:
                mask = cv2.bitwise_and(mask, icon[:, :, 3])
            core = np.dstack((icon[:, :, :3], mask))
            value, peak = self._score(image, (pixel[0]+.20*step, pixel[1]-.18*step), step, core,
                tuple(.34*step/max(icon.shape[:2])*factor for factor in np.arange(.7, 1.85, .04)),
                search_fraction=.18, radius_fraction=.5, locate=True)
            if value > scores.get(mark_id, -1):
                scores[mark_id], peaks[mark_id] = value, peak
        ranked = sorted(scores.items(), key=lambda row: row[1], reverse=True)
        if not ranked:
            return []
        mark_id, score = ranked[0]
        minimum = {"node_mark_001": .85, "node_mark_006": .88}.get(mark_id, .76)
        if score < minimum or (len(ranked) > 1 and score-ranked[1][1] < .05):
            return []
        if mark_id in {"node_mark_002", "node_mark_003"} and (area is None or floor is None):
            return []
        cx, cy, width, height = peaks[mark_id]
        angles = np.linspace(0, 2*np.pi, 48, endpoint=False)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        ring = 0.
        for fraction in (.38, .43, .48, .53, .58, .63):
            radius = min(width, height)*fraction
            xs = np.rint(cx+radius*np.cos(angles)).astype(int)
            ys = np.rint(cy+radius*np.sin(angles)).astype(int)
            if min(xs.min(), ys.min()) < 0 or xs.max() >= image.shape[1] or ys.max() >= image.shape[0]:
                continue
            colors = hsv[ys, xs]
            ring = max(ring, float(np.mean((colors[:,1] < 115) & (colors[:,2] > 130))))
        if ring < .65:
            return []
        return [{"id": mark_id, "name": self.mark_labels[mark_id], "score": round(score, 4),
                 "status": "candidate", "method": "localized_glyph_and_ring", "ringSupport": round(ring, 3)}]

    def detect_marks(self, image: np.ndarray, pixel: tuple[float, float], step: float, *,
                     area: str | None = None, floor: int | None = None) -> list[dict[str, object]]:
        from .node_identity import contextual_mark_id

        # Badges occupy a small, stable upper-right region, not the node body.
        anchor = (pixel[0] + .20 * step, pixel[1] - .18 * step)
        scores: dict[str, float] = {}
        for mark_id, icon in self.mark_templates:
            mapped_id = contextual_mark_id(mark_id, area, floor)
            if mapped_id is None:
                continue
            base_scale = .34 * step / max(icon.shape[:2])
            scales = tuple(base_scale * relative for relative in (.7, .85, 1, 1.15, 1.3, 1.5, 1.65))
            score = self._score(image, anchor, step, icon, scales,
                                search_fraction=.14, radius_fraction=.42)
            scores[mapped_id] = max(score, scores.get(mapped_id, -1.0))
        ranked = sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if not ranked:
            return []
        mark_id, score = ranked[0]
        if mark_id in {"node_mark_002", "node_mark_003"} and (area is None or floor is None):
            return []
        minimum = {"node_mark_001": 0.85, "node_mark_006": 0.88}.get(mark_id, 0.72)
        # Refine a clear but borderline candidate without lowering its acceptance threshold.
        if minimum - .035 <= score < minimum and (len(ranked) == 1 or score - ranked[1][1] >= .10):
            sides = np.arange(max(8, np.floor(.34 * step * .7) - 1), np.ceil(.34 * step * 1.65) + 1, .2)
            for source_id, icon in self.mark_templates:
                if contextual_mark_id(source_id, area, floor) == mark_id:
                    score = max(score, self._score(image, anchor, step, icon,
                        tuple(side / max(icon.shape[:2]) for side in sides),
                        search_fraction=.14, radius_fraction=.42))
        if score < minimum:
            return self._badge_core(image, pixel, step, scores, area, floor)
        if len(ranked) > 1 and score - ranked[1][1] < 0.07:
            core_scores = {}
            contenders = {key for key, value in ranked if value >= score - .12}
            for source_id, icon in self.mark_templates:
                mapped_id = contextual_mark_id(source_id, area, floor)
                if mapped_id not in contenders:
                    continue
                color = icon[:, :, :3]
                yy, xx = np.ogrid[:icon.shape[0], :icon.shape[1]]
                mask = ((xx - (icon.shape[1]-1)/2)**2 + (yy - (icon.shape[0]-1)/2)**2
                        <= (min(icon.shape[:2])*.35)**2).astype(np.uint8)*255
                if icon.shape[2] == 4:
                    mask = cv2.bitwise_and(mask, icon[:, :, 3])
                core = np.dstack((color, mask))
                base = .34 * step / max(icon.shape[:2])
                value = self._score(image, anchor, step, core,
                                    tuple(base * factor for factor in (.7, .85, 1, 1.15, 1.3, 1.5, 1.65)),
                                    search_fraction=.14, radius_fraction=.42)
                core_scores[mapped_id] = max(value, core_scores.get(mapped_id, -1))
            core_ranked = sorted(core_scores.items(), key=lambda row: row[1], reverse=True)
            if (len(core_ranked) < 2 or core_ranked[0][0] != mark_id or core_ranked[0][1] < .78
                    or core_ranked[0][1] - core_ranked[1][1] < .10):
                return self._badge_core(image, pixel, step, scores, area, floor)
        return [{"id": mark_id, "name": self.mark_labels[mark_id], "score": round(score, 4), "status": "candidate"}]
