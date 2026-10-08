from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .vision_geometry import Circle


ROOT = Path(__file__).resolve().parents[1]


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
    ) -> float:
        height, width = image.shape[:2]
        radius = min(115, max(55, round(step * radius_fraction)))
        x, y = round(pixel[0]), round(pixel[1])
        x0, x1 = max(0, x - radius), min(width, x + radius)
        y0, y1 = max(0, y - radius), min(height, y + radius)
        patch = image[y0:y1, x0:x1]
        best = -1.0
        for scale in scales:
            template = cv2.resize(icon, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            th, tw = template.shape[:2]
            if patch.shape[0] < th or patch.shape[1] < tw:
                continue
            if template.ndim == 3 and template.shape[2] == 4:
                mask = template[:, :, 3]
                scores = cv2.matchTemplate(patch, template[:, :, :3], cv2.TM_CCOEFF_NORMED, mask=mask)
            else:
                scores = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
            # A label or nearby icon must not win a search far from the mapped cell.
            cx = x - x0 - tw / 2
            cy = y - y0 - th / 2
            slack = max(9, step * search_fraction)
            left = max(0, int(cx - slack))
            right = min(scores.shape[1], int(cx + slack) + 1)
            top = max(0, int(cy - slack))
            bottom = min(scores.shape[0], int(cy + slack) + 1)
            if left < right and top < bottom:
                local = scores[top:bottom, left:right]
                finite = local[np.isfinite(local)]
                if finite.size:
                    best = max(best, min(1.0, float(np.max(finite))))
        return best

    def _empty_score(self, image: np.ndarray, pixel: tuple[float, float], circles: list[Circle]) -> float:
        x, y = pixel
        near = [circle for circle in circles if abs(circle.x - x) < 13 and abs(circle.y - y) < 13]
        if near:
            radius = min(circle.radius for circle in near)
            if radius <= 16:
                xi, yi = round(x), round(y)
                patch = image[max(0, yi - 22):yi + 23, max(0, xi - 22):xi + 23]
                hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
                colorful = (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 75)
                if int(np.count_nonzero(colorful)) < 80:
                    return 1.0 if radius <= 13 else 0.9
        templates = self.connector_templates + ([self.empty_template] if self.empty_template is not None else [])
        if not templates:
            return -1.0
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        score = max(self._score(gray, pixel, 60, template, (0.65, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5)) for template in templates)
        return score if score >= 0.72 else -1.0

    def classify_node(
        self, image: np.ndarray, pixel: tuple[float, float], step: float, circles: list[Circle], *, dystopia: bool = False
    ) -> tuple[IconMatch | None, list[IconMatch]]:
        empty_score = self._empty_score(image, pixel, circles)
        texture_scores = []
        if dystopia:
            from .vision_dystopia import classify_texture
            texture_scores = classify_texture(image, pixel, step)
            if texture_scores[0][0] == "node_type_020" and texture_scores[0][1] >= .78:
                empty_score = max(empty_score, texture_scores[0][1])
        if empty_score >= 0.85 or (texture_scores and texture_scores[0][0] == "node_type_020"
                                and texture_scores[0][1] >= .76
                                and texture_scores[0][1]-texture_scores[1][1] >= .08):
            match = IconMatch("node_type_020", self.node_labels["node_type_020"], round(empty_score, 4), 0.0)
            return match, [match]
        scores: dict[str, float] = {}
        for node_id, icon in self.node_templates:
            scales = (0.55, 0.65, 0.75, 0.85, 1.0, 1.15, 1.3, 1.45, 1.6, 1.8, 2.0)
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
            scales = tuple(base_scale * relative for relative in (.7, .85, 1.0, 1.15, 1.3, 1.5, 1.65))
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
        if score < minimum:
            return []
        if len(ranked) > 1 and score - ranked[1][1] < 0.07:
            return []
        return [{"id": mark_id, "name": self.mark_labels[mark_id], "score": round(score, 4), "status": "candidate"}]
