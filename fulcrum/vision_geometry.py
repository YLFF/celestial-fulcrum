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


def _connector_circles(gray: np.ndarray, offset: tuple[int, int], *, adaptive=False) -> list[Circle]:
    templates = _connector_templates()
    if not templates:
        return []
    if adaptive:
        points = []
        for factor in (.6, .8, 1., 1.25, 1.5):
            for original in templates:
                icon = cv2.resize(original, None, fx=factor, fy=factor)
                if min(gray.shape) < max(icon.shape):
                    continue
                scores = cv2.matchTemplate(gray, icon, cv2.TM_CCOEFF_NORMED)
                peaks = (scores >= .78) & (scores >= cv2.dilate(scores, np.ones((15, 15), np.uint8)))
                for y, x in zip(*np.where(peaks)):
                    center = (x+icon.shape[1]/2+offset[0], y+icon.shape[0]/2+offset[1])
                    if all(np.hypot(center[0]-point.x, center[1]-point.y) >= 8 for point in points):
                        points.append(Circle(*center, min(icon.shape)*.42, "connector"))
        return points
    scores = np.maximum.reduce([
        cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED) for template in templates
    ])
    peaks = (scores >= 0.73) & (scores >= cv2.dilate(scores, np.ones((19, 19), np.uint8)))
    yy, xx = np.where(peaks)
    half = templates[0].shape[0] // 2
    return [Circle(float(x + half + offset[0]), float(y + half + offset[1]), 8.0, "connector") for x, y in zip(xx, yy)]


def detect_circles(
    image: np.ndarray, viewport: tuple[int, int, int, int] | None = None,
    *, enhance_contrast: bool = False, adaptive=False, filter_hud=True,
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
        minDist=14 if adaptive else max(25, round(width * 0.03)),
        param1=95,
        param2=25,
        minRadius=max(3, round(width * 0.003)),
        maxRadius=max(35, round(width * 0.038)),
    )
    circles = []
    if found is not None:
        for local_x, local_y, radius in found[0]:
            x, y = float(local_x + x0), float(local_y + y0)
            if filter_hud and x > width * 0.82 and y < height * 0.28:
                continue
            if filter_hud and x < width * 0.11 and y > height * 0.64:
                continue
            circles.append(Circle(x, y, float(radius), "contrast" if enhance_contrast else "hough"))
    for connector in _connector_circles(cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY), (x0, y0), adaptive=adaptive):
        near = next((index for index, item in enumerate(circles)
                     if np.hypot(connector.x - item.x, connector.y - item.y) < 12), None)
        if near is None:
            circles.append(connector)
        else:
            circles[near] = connector
    return circles


def _axis_clusters(values: list[float], tolerance: float = 11.0) -> list[tuple[float, int]]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if not groups or value - float(np.median(groups[-1])) > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [(float(np.median(group)), len(group)) for group in groups]


def fit_axis(values: list[float], count: int, extent: int, limit: int = 24, *, minimum_step=36.) -> list[AxisFit]:
    clusters = _axis_clusters(values, tolerance=11. if minimum_step >= 36 else minimum_step*.30)
    if count == 1:
        ranked = sorted(clusters, key=lambda item: item[1], reverse=True)[:limit]
        return [AxisFit(center, 1.0, float(weight)) for center, weight in ranked]
    if len(clusters) < 2:
        return []
    centers = np.array([center for center, _ in clusters], dtype=np.float32)
    weights = np.array([weight for _, weight in clusters], dtype=np.float32)
    min_step = max(minimum_step, extent / (count + 17))
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
    template: MapTemplate, xfit: AxisFit, yfit: AxisFit, points: np.ndarray, support_cache=None,
) -> TemplateMatch:
    columns, rows = template.grid_shape
    occupied = set(template.occupied_slots)
    cache_key = (columns, rows, xfit.origin, xfit.step, yfit.origin, yfit.step)
    cached = support_cache.get(cache_key) if support_cache is not None else None
    if cached is None:
        slots = [(col, row) for col in range(columns) for row in range(rows)]
        expected = np.array([[xfit.origin + col * xfit.step, yfit.origin + row * yfit.step] for col, row in slots],
                            dtype=np.float32)
        distances = np.min(np.linalg.norm(expected[:, None, :] - points[None, :, :], axis=2), axis=1)
        active_steps = [xfit.step if columns > 1 else float("inf"), yfit.step if rows > 1 else float("inf")]
        tolerance = min(20.0, min(active_steps) * 0.20)
        supported = {slot for slot, distance in zip(slots, distances) if distance <= tolerance}
        extension_slots = [(-1, 0), (columns, 0)] if rows == 1 else (
            [(0, -1), (0, rows)] if columns == 1 else [])
        extension_count = sum(float(np.min(np.linalg.norm(points - np.array(
            [xfit.origin + col*xfit.step, yfit.origin + row*yfit.step], dtype=np.float32), axis=1))) <= tolerance
            for col, row in extension_slots)
        cached = supported, extension_count
        if support_cache is not None:
            support_cache[cache_key] = cached
    supported, extension_count = cached
    matched = len(occupied & supported)
    extras = len(supported - occupied) + extension_count
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


def refine_node_positions(match: TemplateMatch, image, circles):
    """Refine an accepted layout using independently detected connector anchors."""
    anchors = []
    for circle in circles:
        if circle.source != "connector":
            continue
        slot = min(match.template.occupied_slots, key=lambda s: np.hypot(
            circle.x-match.pixel_at(s)[0], circle.y-match.pixel_at(s)[1]))
        if np.hypot(circle.x-match.pixel_at(slot)[0], circle.y-match.pixel_at(slot)[1]) <= match.grid_step*.22:
            anchors.append((slot, circle))
    info = {"source": "connector_anchors", "anchorCount": len(anchors), "refined": False}
    if len(anchors) < 3:
        return match, info
    fits = []
    for axis, origin, step in ((0, match.origin_x, match.step_x), (1, match.origin_y, match.step_y)):
        values = [(slot[axis], getattr(circle, "x" if axis == 0 else "y")) for slot, circle in anchors]
        slopes = [(b[1]-a[1])/(b[0]-a[0]) for a, b in combinations(values, 2) if abs(a[0]-b[0]) >= 2]
        if not slopes:
            fits.append((origin, step))
            continue
        candidate_step = float(np.median(slopes))
        candidate_origin = float(np.median([value-index*candidate_step for index, value in values]))
        residuals = np.array([abs(value-candidate_origin-index*candidate_step) for index, value in values])
        inliers = residuals <= match.grid_step*.04
        if inliers.sum() < 3 or abs(candidate_step-step) > step*.12:
            fits.append((origin, step))
            continue
        # Refit the consensus only; stray circles cannot move the complete lattice.
        indices, positions = np.array(values)[inliers].T
        candidate_step, candidate_origin = np.polyfit(indices, positions, 1)
        fits.append((float(candidate_origin), float(candidate_step)))
    candidate = replace(match, origin_x=fits[0][0], step_x=fits[0][1], origin_y=fits[1][0], step_y=fits[1][1])
    def errors(fit):
        return [np.hypot(circle.x-fit.pixel_at(slot)[0], circle.y-fit.pixel_at(slot)[1]) for slot, circle in anchors]
    before, after = float(np.median(errors(match))), float(np.median(errors(candidate)))
    info.update(residualBeforePx=round(before, 3), residualAfterPx=round(after, 3))
    shift = max(np.hypot(*(np.array(candidate.pixel_at(s))-match.pixel_at(s))) for s in match.template.occupied_slots)
    if after > match.grid_step*.04 or after >= before*.6 or shift > match.grid_step*.25:
        return match, info
    info.update(refined=True, maxShiftPx=round(shift, 3))
    return candidate, info


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


def _whole_map_score(match: TemplateMatch) -> float:
    # Balance template recall with the fraction of observed points it explains.
    recall, precision = max(0.0, match.score), match.point_explanation
    return 2 * recall * precision / (recall + precision) if recall + precision else 0.0


def _with_label_support(match, image, points, cache):
    from .vision_node_text import label_crop

    columns, rows = match.template.grid_shape
    occupied = set(match.template.occupied_slots)
    supported = set()
    added = 0
    viewport = (0, 0, image.shape[1], image.shape[0])
    for col in range(columns):
        for row in range(rows):
            slot = (col, row)
            pixel = match.pixel_at(slot)
            if float(np.min(np.linalg.norm(points - pixel, axis=1))) <= min(20, match.grid_step * .20):
                supported.add(slot)
                continue
            key = (*map(round, pixel), round(match.grid_step))
            if key not in cache:
                cache[key] = label_crop(image, pixel, match.grid_step, viewport) is not None
            if cache[key]:
                supported.add(slot)
                added += 1
    matched, extras = len(occupied & supported), len(supported - occupied)
    return replace(match, score=(matched - .75 * extras) / len(occupied),
                   coverage=matched / len(occupied), matched_slots=matched, extra_slots=extras,
                   point_explanation=matched / (len(points) + added), circle_coverage=match.coverage)


def _refine_label_fit(match, image, points):
    from .vision_node_text import label_crop

    anchors = []
    viewport = (0, 0, image.shape[1], image.shape[0])
    for slot in match.template.occupied_slots:
        crop = label_crop(image, match.pixel_at(slot), match.grid_step, viewport, include_anchor=True)
        if crop is not None:
            anchors.append((slot[0], crop[2][0]))
    if len(anchors) < 4 or len({index for index, _ in anchors}) < 3:
        return match
    slopes = [(b_value - a_value) / (b_index - a_index)
              for (a_index, a_value), (b_index, b_value) in combinations(anchors, 2)
              if abs(b_index - a_index) >= 2]
    step = float(np.median(slopes))
    if abs(step - match.step_x) > match.step_x * .12:
        return match
    origin = float(np.median([value - index * step for index, value in anchors]))
    if np.median([abs(value - origin - index * step) for index, value in anchors]) > match.grid_step * .04:
        return match
    return _score_template(match.template, AxisFit(origin, step, 0), AxisFit(match.origin_y, match.step_y, 0), points)


def match_templates(
    circles: list[Circle],
    templates: list[MapTemplate],
    image_size: tuple[int, int],
    image: np.ndarray | None = None,
    refine_connectors: bool = False,
    minimum_step=36.,
) -> list[TemplateMatch]:
    if not circles:
        return []
    points = np.array([(circle.x, circle.y) for circle in circles], dtype=np.float32)
    width, height = image_size
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image is not None else None
    contrast_cache = {}
    label_cache = {}
    support_cache = {}
    fits_by_shape: dict[tuple[int, int], tuple[list[AxisFit], list[AxisFit]]] = {}
    results: list[TemplateMatch] = []
    for template in templates:
        shape = template.grid_shape
        if shape not in fits_by_shape:
            fits_by_shape[shape] = (
                fit_axis([circle.x for circle in circles], shape[0], width, minimum_step=minimum_step),
                fit_axis([circle.y for circle in circles], shape[1], height, minimum_step=minimum_step),
            )
        xfits, yfits = fits_by_shape[shape]
        if not xfits or not yfits:
            continue
        best = max(
            (_score_template(template, xfit, yfit, points, support_cache) for xfit in xfits for yfit in yfits),
            key=lambda match: (_whole_map_score(match), match.coverage),
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
            vertical_shift = max(abs(refined.pixel_at(slot)[1] - best.pixel_at(slot)[1])
                                 for slot in best.template.occupied_slots)
            anchor_fit = refined if (refined.score >= best.score or vertical_shift <= best.grid_step * .05) else best
            text_refined = _refine_label_fit(anchor_fit, image, points)
            has_text_fit = text_refined is not anchor_fit
            best = _with_label_support(best, image, points, label_cache)
            refined = _with_label_support(refined, image, points, label_cache)
            text_refined = _with_label_support(text_refined, image, points, label_cache)
            def evidence(candidate):
                return _whole_map_score(candidate) + .20 * _edge_agreement(gray, candidate, contrast_cache=contrast_cache)
            best = max((best, refined, text_refined), key=evidence)
            if has_text_fit and text_refined.score >= best.score - .05 and text_refined.coverage >= .8:
                best = text_refined
        results.append(best)
    if image is not None and results:
        refined: list[TemplateMatch] = []
        for match in results:
            edge_score = _edge_agreement(gray, match, contrast_cache=contrast_cache)
            refined.append(
                replace(
                    match,
                    edge_score=edge_score,
                    ranking_score=_whole_map_score(match) + 0.20 * edge_score,
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


def label_anchors(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 75), (179, 105, 255))
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    anchors = []
    for kernel in ((5, 1), (9, 2), (13, 2)):
        grouped = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones(kernel[::-1], np.uint8))
        contours, _ = cv2.findContours(grouped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if not (4 <= height <= 32 and 1.8 <= width/height <= 12 and width <= image.shape[1]*.24):
                continue
            glyphs = [s for s in stats[1:] if x <= s[0] and y <= s[1] and s[0]+s[2] <= x+width
                      and s[1]+s[3] <= y+height and s[3] >= height*.45 and s[4] >= 3]
            if len(glyphs) < 3:
                continue
            anchor = Circle(x+width/2, y-height*1.8, 0., "label")
            if all(np.hypot(anchor.x-old.x, anchor.y-old.y) >= height for old in anchors):
                anchors.append(anchor)
    return anchors


def colored_anchors(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    colorful = (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 40)
    colors = ((hsv[:, :, 0] >= 70) & (hsv[:, :, 0] <= 110)
              | (hsv[:, :, 0] >= 130) & (hsv[:, :, 0] <= 175))
    mask = (colorful & colors).astype(np.uint8)*255
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    anchors = []
    for x, y, width, height, area in stats[1:]:
        if (8 <= min(width, height) and max(width, height) <= min(100, image.shape[1]*.12)
                and .6 <= width/height <= 1.8 and area >= 35 and area/(width*height) >= .2):
            anchors.append(Circle(x+width/2, y+height/2, 0., "color"))
    return anchors


def recover_layout(image, work_scale, viewport, circles, templates, matches, *, refine_connectors=False):
    """Retry a failed layout in bounded original-image regions, then map anchors back."""
    height, width = image.shape[:2]
    broad = (0, max(0, round(height*.10)), width, min(height, round(viewport[3]/work_scale)))
    regions = [broad]
    if matches and matches[0].coverage >= .45:
        fit = matches[0]
        points = np.array([fit.pixel_at(slot) for slot in fit.template.occupied_slots])/work_scale
        padding = 1.5*fit.grid_step/work_scale
        regions.insert(0, (max(broad[0], round(points[:, 0].min()-padding)),
                           max(broad[1], round(points[:, 1].min()-padding)),
                           min(broad[2], round(points[:, 0].max()+padding)),
                           min(broad[3], round(points[:, 1].max()+padding))))
    accepted = []
    for attempt in range(2):
        if attempt >= len(regions):
            break
        left, top, right, bottom = regions[attempt]
        if right-left < 100 or bottom-top < 60:
            continue
        factor = min(2., 1280/(right-left))
        patch = cv2.resize(image[top:bottom, left:right], None, fx=factor, fy=factor,
                           interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC)
        points = detect_circles(patch, adaptive=True, filter_hud=False)
        for point in label_anchors(patch)+colored_anchors(patch):
            if all(np.hypot(point.x-old.x, point.y-old.y) >= 12 for old in points):
                points.append(point)
        if len(regions) == 1 and len(points) >= 2:
            xs = np.array([point.x/factor+left for point in points])
            ys = np.array([point.y/factor+top for point in points])
            pad = max(40., (xs.max()-xs.min())*.3, (ys.max()-ys.min())*.3)
            regions.append((max(broad[0], round(xs.min()-pad)), max(broad[1], round(ys.min()-pad)),
                            min(broad[2], round(xs.max()+pad)), min(broad[3], round(ys.max()+pad))))
        found = match_templates(points, templates, (patch.shape[1], patch.shape[0]), image=patch,
                                refine_connectors=refine_connectors, minimum_step=20.)
        if not found:
            continue
        best = found[0]
        margin = best.ranking_score-found[1].ranking_score if len(found) > 1 else 1.
        if (best.coverage < .95 or best.score < .85 or best.point_explanation < .65
                or (best.edge_score or 0) < .20 or margin < .08):
            continue
        conversion = work_scale/factor
        converted = [replace(match, origin_x=(match.origin_x/factor+left)*work_scale,
                             origin_y=(match.origin_y/factor+top)*work_scale,
                             step_x=match.step_x*conversion, step_y=match.step_y*conversion) for match in found]
        anchors = [Circle((point.x/factor+left)*work_scale, (point.y/factor+top)*work_scale,
                          point.radius*conversion, point.source) for point in points]
        bounds = tuple(value*work_scale for value in broad)
        radius = min(30, max(10, converted[0].grid_step*.25))
        if any(not (bounds[0]+radius <= x <= bounds[2]-radius and bounds[1]+radius <= y <= bounds[3]-radius)
               for x, y in (converted[0].pixel_at(slot) for slot in best.template.occupied_slots)):
            continue
        accepted.append((converted, anchors, bounds, {"method": "original_region_retry", "roi": [left, top, right, bottom],
                                                     "factor": round(factor, 3), "margin": round(margin, 4)}))
    if not accepted:
        return None
    if len({item[0][0].template.id for item in accepted}) > 1:
        return None
    return max(accepted, key=lambda item: item[0][0].ranking_score)
