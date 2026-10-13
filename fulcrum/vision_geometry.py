from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

from .map_model import MapTemplate, TemplateMatch


WORKING_WIDTH = 1280
CONNECTOR_ASSETS = Path(__file__).resolve().parents[1] / "assets" / "vision"


@dataclass(frozen=True)
class Circle:
    x: float
    y: float
    radius: float
    source: str = "hough"


@dataclass(frozen=True)
class AxisFit:
    origin: float
    step: float
    score: float


def working_image(image: np.ndarray) -> tuple[np.ndarray, float]:
    scale = min(1.0, WORKING_WIDTH / image.shape[1])
    if scale == 1.0:
        return image, scale
    size = (round(image.shape[1] * scale), round(image.shape[0] * scale))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA), scale


def detect_map_viewport(image: np.ndarray) -> tuple[int, int, int, int]:
    """Locate the playable area from pillarbox edges and the bottom HUD divider."""
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    rows = np.median(gray[:, round(width * 0.20):round(width * 0.80)], axis=1)
    row_change = np.abs(np.diff(rows))
    low, high = round(height * 0.78), round(height * 0.93)
    bottom_edge = low + int(np.argmax(row_change[low:high]))
    bottom = bottom_edge + 1 if row_change[bottom_edge] >= 8 else round(height * 0.88)
    columns = np.median(gray[round(height * 0.17):round(height * 0.83), :], axis=0)
    column_change = np.abs(np.diff(columns))
    left_range = (round(width * 0.02), round(width * 0.12))
    right_range = (round(width * 0.88), round(width * 0.98))
    left_edge = left_range[0] + int(np.argmax(column_change[slice(*left_range)]))
    right_edge = right_range[0] + int(np.argmax(column_change[slice(*right_range)]))
    left = left_edge + 1 if column_change[left_edge] >= 10 else 0
    right = right_edge + 1 if column_change[right_edge] >= 7 else width
    return left, round(height * 0.10), right, bottom


@lru_cache(maxsize=1)
def _connector_templates() -> tuple[np.ndarray, ...]:
    templates = []
    for name in ("connector_dark.png", "connector_bright.png"):
        template = cv2.imread(str(CONNECTOR_ASSETS / name), cv2.IMREAD_GRAYSCALE)
        if template is not None:
            templates.append(template)
    return tuple(templates)


def _connector_circles(gray: np.ndarray, offset: tuple[int, int]) -> list[Circle]:
    templates = _connector_templates()
    if not templates:
        return []
    scores = np.maximum.reduce([
        cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED) for template in templates
    ])
    peaks = (scores >= 0.73) & (scores >= cv2.dilate(scores, np.ones((19, 19), np.uint8)))
    yy, xx = np.where(peaks)
    half = templates[0].shape[0] // 2
    return [Circle(float(x + half + offset[0]), float(y + half + offset[1]), 8.0, "connector") for x, y in zip(xx, yy)]


def detect_circles(
    image: np.ndarray, viewport: tuple[int, int, int, int] | None = None,
    *, enhance_contrast: bool = False,
) -> list[Circle]:
    height, width = image.shape[:2]
    x0, y0, x1, y1 = viewport or (0, 0, width, height)
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    if enhance_contrast:
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16)).apply(gray)
    gray = cv2.GaussianBlur(gray, (7, 7), 1.5)
    found = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(25, round(width * 0.03)),
        param1=95,
        param2=25,
        minRadius=max(3, round(width * 0.003)),
        maxRadius=max(35, round(width * 0.038)),
    )
    circles = []
    if found is not None:
        for local_x, local_y, radius in found[0]:
            x, y = float(local_x + x0), float(local_y + y0)
            if x > width * 0.82 and y < height * 0.28:
                continue
            if x < width * 0.11 and y > height * 0.64:
                continue
            circles.append(Circle(x, y, float(radius)))
    for connector in _connector_circles(cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY), (x0, y0)):
        if all(np.hypot(connector.x - item.x, connector.y - item.y) >= 12 for item in circles):
            circles.append(connector)
    return circles


def _axis_clusters(values: list[float], tolerance: float = 11.0) -> list[tuple[float, int]]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if not groups or value - float(np.median(groups[-1])) > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [(float(np.median(group)), len(group)) for group in groups]


def fit_axis(values: list[float], count: int, extent: int, limit: int = 24) -> list[AxisFit]:
    clusters = _axis_clusters(values)
    if count == 1:
        ranked = sorted(clusters, key=lambda item: item[1], reverse=True)[:limit]
        return [AxisFit(center, 1.0, float(weight)) for center, weight in ranked]
    if len(clusters) < 2:
        return []
    centers = np.array([center for center, _ in clusters], dtype=np.float32)
    weights = np.array([weight for _, weight in clusters], dtype=np.float32)
    min_step = max(36.0, extent / (count + 17))
    max_step = min(260.0, extent / max(1, count - 1) * 1.4)
    step_votes: dict[float, int] = {}
    for (left, _), (right, _) in combinations(clusters, 2):
        for gap in range(1, count):
            step = (right - left) / gap
            if min_step <= step <= max_step:
                key = round(step / 2) * 2.0
                step_votes[key] = step_votes.get(key, 0) + 1
    if not step_votes:
        return []
    # A genuine lattice step is supported by many independent point pairs.
    steps = sorted(step_votes, key=lambda step: step_votes[step], reverse=True)[:50]
    fits: list[AxisFit] = []
    for step in steps:
        for center in centers:
            for index in range(count):
                origin = float(center - index * step)
                if origin < -20 or origin + (count - 1) * step > extent + 20:
                    continue
                nearest = np.rint((centers - origin) / step).astype(int)
                offset = np.abs(centers - (origin + nearest * step))
                tolerance = min(13.0, step * 0.17)
                aligned = (nearest >= 0) & (nearest < count) & (offset <= tolerance)
                if not np.any(aligned):
                    continue
                quality = 1.0 - np.square(offset[aligned] / tolerance)
                support = float(np.sum(weights[aligned] * quality))
                coverage = len(set(nearest[aligned].tolist()))
                fits.append(AxisFit(origin, step, support + 0.35 * coverage))
    ranked = sorted(fits, key=lambda fit: fit.score, reverse=True)
    distinct: list[AxisFit] = []
    for fit in ranked:
        if any(abs(fit.origin - old.origin) < 9 and abs(fit.step - old.step) < 4 for old in distinct):
            continue
        distinct.append(fit)
        if len(distinct) >= limit:
            break
    return distinct


def _score_template(
    template: MapTemplate, xfit: AxisFit, yfit: AxisFit, points: np.ndarray
) -> TemplateMatch:
    columns, rows = template.grid_shape
    occupied = set(template.occupied_slots)
    slots = [(col, row) for col in range(columns) for row in range(rows)]
    expected = np.array(
        [[xfit.origin + col * xfit.step, yfit.origin + row * yfit.step] for col, row in slots],
        dtype=np.float32,
    )
    distances = np.min(np.linalg.norm(expected[:, None, :] - points[None, :, :], axis=2), axis=1)
    active_steps = [xfit.step if columns > 1 else float("inf"), yfit.step if rows > 1 else float("inf")]
    tolerance = min(20.0, min(active_steps) * 0.20)
    supported = {slot for slot, distance in zip(slots, distances) if distance <= tolerance}
    matched = len(occupied & supported)
    extras = len(supported - occupied)
    # A circle beyond a single-row/column grid distinguishes a longer chain.
    extension_slots = [(-1, 0), (columns, 0)] if rows == 1 else (
        [(0, -1), (0, rows)] if columns == 1 else []
    )
    for col, row in extension_slots:
        target = np.array(
            [xfit.origin + col * xfit.step, yfit.origin + row * yfit.step], dtype=np.float32
        )
        if float(np.min(np.linalg.norm(points - target, axis=1))) <= tolerance:
            extras += 1
    coverage = matched / len(occupied)
    score = (matched - 0.75 * extras) / len(occupied)
    return TemplateMatch(
        template,
        xfit.origin,
        yfit.origin,
        xfit.step,
        yfit.step,
        score,
        coverage,
        matched,
        extras,
        matched / len(points),
    )


def _edge_contrast(gray: np.ndarray, first: tuple[float, float], second: tuple[float, float]) -> float:
    start = np.array(first, dtype=np.float32)
    end = np.array(second, dtype=np.float32)
    direction = end - start
    length = float(np.linalg.norm(direction))
    if length < 35:
        return 0.0
    close_to_border = (
        min(start[0], end[0], start[1], end[1]) < 20
        or max(start[0], end[0]) >= gray.shape[1] - 20
        or max(start[1], end[1]) >= gray.shape[0] - 20
    )
    if close_to_border:
        return 0.0
    normal = np.array([-direction[1], direction[0]], dtype=np.float32) / length
    points = np.stack([start + direction * t for t in np.linspace(0.29, 0.71, 9)])
    # Keep the same corridor and sample precision, batching its percentile calculation.
    corridor = points[:, None, :] + normal * np.arange(-8, 9, 2, dtype=np.float32)[None, :, None]
    sides = points[:, None, :] + normal * np.array([-17, 17], dtype=np.float32)[None, :, None]
    corridor = np.rint(corridor).astype(np.intp)
    sides = np.rint(sides).astype(np.intp)
    center = np.percentile(gray[corridor[..., 1], corridor[..., 0]], 80, axis=1)
    flank = gray[sides[..., 1], sides[..., 0]]
    return float(np.median(center) - np.median(flank))


def _edge_agreement(gray: np.ndarray, match: TemplateMatch, *, contrast_cache=None) -> float:
    template = match.template
    occupied = set(template.occupied_slots)
    edges = {frozenset((a, b)) for a, b in template.edges}
    values: list[float] = []
    for col, row in occupied:
        for neighbor in ((col + 1, row), (col, row + 1)):
            if neighbor not in occupied:
                continue
            a, b = match.pixel_at((col, row)), match.pixel_at(neighbor)
            if any(not (0 <= point[0] < gray.shape[1] and 0 <= point[1] < gray.shape[0]) for point in (a, b)):
                continue
            key = (a, b)
            if contrast_cache is None:
                contrast = _edge_contrast(gray, a, b)
            else:
                if key not in contrast_cache:
                    contrast_cache[key] = _edge_contrast(gray, a, b)
                contrast = contrast_cache[key]
            evidence = np.tanh((contrast - 8.0) / 16.0)
            sign = 1 if frozenset(((col, row), neighbor)) in edges else -1
            values.append(float(sign * evidence))
    return float(np.mean(values)) if values else 0.0


def _refine_connector_fit(match: TemplateMatch, circles: list[Circle], points: np.ndarray) -> TemplateMatch:
    anchors = []
    for slot in match.template.occupied_slots:
        pixel = match.pixel_at(slot)
        near = [circle for circle in circles if circle.source == "connector"
                and np.hypot(circle.x - pixel[0], circle.y - pixel[1]) < match.grid_step * .22]
        if near:
            anchors.append((slot, min(near, key=lambda circle: np.hypot(circle.x - pixel[0], circle.y - pixel[1]))))
    if len(anchors) < 3:
        return match
    fits = []
    for axis, origin, step in ((0, match.origin_x, match.step_x), (1, match.origin_y, match.step_y)):
        indices = np.array([slot[axis] for slot, _ in anchors])
        values = np.array([getattr(circle, "x" if axis == 0 else "y") for _, circle in anchors])
        slopes = [(values[b] - values[a]) / (indices[b] - indices[a])
                  for a, b in combinations(range(len(indices)), 2) if abs(indices[b] - indices[a]) >= 2]
        if slopes:
            refined_step = float(np.median(slopes))
            if abs(refined_step - step) <= step * .12:
                step = refined_step
        if len(set(indices)) >= 2:
            origin = float(np.median(values - indices * step))
        fits.append(AxisFit(origin, step, 0))
    return _score_template(match.template, *fits, points)


def differing_edge_evidence(image: np.ndarray, first: TemplateMatch, second: TemplateMatch) -> tuple[int, float, float]:
    """Compare only the links that distinguish two layouts with identical slots."""
    first_edges = {frozenset(edge) for edge in first.template.edges}
    second_edges = {frozenset(edge) for edge in second.template.edges}
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    values = []
    for edge in first_edges ^ second_edges:
        a, b = tuple(edge)
        contrast = _edge_contrast(gray, first.pixel_at(a), first.pixel_at(b))
        evidence = float(np.tanh((contrast - 8) / 16))
        values.append(evidence if edge in first_edges else -evidence)
    return (len(values), float(np.mean(values)) if values else 0,
            sum(value > 0 for value in values) / len(values) if values else 0)


def match_templates(
    circles: list[Circle],
    templates: list[MapTemplate],
    image_size: tuple[int, int],
    image: np.ndarray | None = None,
    refine_connectors: bool = False,
) -> list[TemplateMatch]:
    if not circles:
        return []
    points = np.array([(circle.x, circle.y) for circle in circles], dtype=np.float32)
    width, height = image_size
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image is not None else None
    contrast_cache = {}
    fits_by_shape: dict[tuple[int, int], tuple[list[AxisFit], list[AxisFit]]] = {}
    results: list[TemplateMatch] = []
    for template in templates:
        shape = template.grid_shape
        if shape not in fits_by_shape:
            fits_by_shape[shape] = (
                fit_axis([circle.x for circle in circles], shape[0], width),
                fit_axis([circle.y for circle in circles], shape[1], height),
            )
        xfits, yfits = fits_by_shape[shape]
        if not xfits or not yfits:
            continue
        best = max(
            (_score_template(template, xfit, yfit, points) for xfit in xfits for yfit in yfits),
            key=lambda match: (match.score, match.coverage),
        )
        if refine_connectors and len(template.occupied_slots) >= 20:
            for _ in range(2):
                anchors = []
                for slot in template.occupied_slots:
                    pixel = best.pixel_at(slot)
                    near = [circle for circle in circles if circle.radius <= 14
                            and np.hypot(circle.x-pixel[0], circle.y-pixel[1]) < best.grid_step*.18]
                    if near:
                        nearest = min(near, key=lambda circle: np.hypot(circle.x-pixel[0], circle.y-pixel[1]))
                        anchors.append((slot, nearest))
                fits = []
                for axis, old_origin, old_step in ((0, best.origin_x, best.step_x), (1, best.origin_y, best.step_y)):
                    if len({slot[axis] for slot, _ in anchors}) < 2:
                        fits.append(AxisFit(old_origin, old_step, 0))
                        continue
                    indices = np.array([slot[axis] for slot, _ in anchors])
                    values = np.array([getattr(circle, "x" if axis == 0 else "y") for _, circle in anchors])
                    steps = [(values[b]-values[a])/(indices[b]-indices[a]) for a, b in combinations(range(len(indices)), 2)
                             if abs(indices[b]-indices[a]) >= 2]
                    step = float(np.median(steps)) if steps else old_step
                    origin = float(np.median(values-indices*step))
                    fits.append(AxisFit(origin, step, 0))
                best = _score_template(template, *fits, points)
        if gray is not None:
            refined = _refine_connector_fit(best, circles, points)
            def evidence(candidate):
                return candidate.score + .20 * _edge_agreement(gray, candidate, contrast_cache=contrast_cache) + .18 * candidate.point_explanation
            if refined.score >= best.score and evidence(refined) > evidence(best):
                best = refined
        results.append(best)
    if image is not None and results:
        refined: list[TemplateMatch] = []
        for match in results:
            edge_score = _edge_agreement(gray, match, contrast_cache=contrast_cache)
            refined.append(
                replace(
                    match,
                    edge_score=edge_score,
                    ranking_score=match.score + 0.20 * edge_score + 0.18 * match.point_explanation,
                )
            )
        results = refined
    return sorted(
        results,
        key=lambda match: (
            match.ranking_score if match.ranking_score is not None else match.score,
            match.coverage,
        ),
        reverse=True,
    )
