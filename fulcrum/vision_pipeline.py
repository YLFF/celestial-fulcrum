from __future__ import annotations

from pathlib import Path
from collections import Counter

import cv2
import numpy as np

from .map_catalog import TemplateCatalog
from .map_model import MapNode, MapResult, TemplateMatch
from .vision_geometry import detect_circles, detect_map_viewport, match_templates, working_image
from .vision_icons import IconMatcher
from .vision_layer import recognize_layer
from .vision_player import recognize_player_position
from .vision_resources import HudRecognizer
from .vision_dystopia import recognize_header, connector_evidence, recognize_nodes


FIXED_NODE_TYPES = {
    "combat": "node_type_001",
    "danger-end": "node_type_015",
    "danger-enemy": "node_type_003",
    "encounter": "node_type_006",
    "fate-choice": "node_type_012",
    "rogue-trader": "node_type_004",
    "settlement": "node_type_007",
}
MIN_TEMPLATE_SCORE = 0.62
MIN_NODE_COVERAGE = 0.80


def match_quality(match, viewport, observed_coverage=None):
    radius = max(10, min(30, match.grid_step * 0.25))
    outside = [match.template.coord(slot).key for slot in match.template.occupied_slots
               if not (viewport[0] + radius <= match.pixel_at(slot)[0] <= viewport[2] - radius
                       and viewport[1] + radius <= match.pixel_at(slot)[1] <= viewport[3] - radius)]
    coverage = match.coverage if observed_coverage is None else observed_coverage
    return {"score": round(match.score, 4), "coverage": round(coverage, 4), "circleCoverage": round(match.coverage, 4),
            "minimumScore": MIN_TEMPLATE_SCORE, "minimumCoverage": MIN_NODE_COVERAGE,
            "clippedNodeIds": outside,
            "accepted": match.score >= MIN_TEMPLATE_SCORE and coverage >= MIN_NODE_COVERAGE and not outside}


class MapRecognizer:
    def __init__(self, catalog: TemplateCatalog | None = None, icons: IconMatcher | None = None) -> None:
        self.catalog = catalog or TemplateCatalog()
        self.icons = icons or IconMatcher()

    def recognize(
        self,
        screenshot: Path,
        *,
        area: str | None = None,
        floor: int | None = None,
        template_override: str | None = None,
        include_resources: bool = False,
        difficulty: int = 15,
    ) -> MapResult:
        image = cv2.imread(str(screenshot))
        if image is None:
            raise ValueError(f"could not read screenshot: {screenshot}")
        return self.recognize_image(
            image,
            screenshot=str(screenshot),
            area=area,
            floor=floor,
            template_override=template_override,
            include_resources=include_resources,
            difficulty=difficulty,
        )

    def recognize_image(
        self,
        image: np.ndarray,
        *,
        screenshot: str,
        area: str | None = None,
        floor: int | None = None,
        template_override: str | None = None,
        include_resources: bool = False,
        difficulty: int = 15,
    ) -> MapResult:
        layer = recognize_layer(image)
        requested_area, requested_floor = area, floor
        area = area or layer.area
        floor = floor if floor is not None else (layer.floor if area != "treehole" else None)
        height, width = image.shape[:2]
        result = MapResult(screenshot, (width, height), area, floor, success=False)
        result.layer_observation = layer.to_dict()
        if include_resources:
            try:
                result.resource_observation = HudRecognizer().recognize_image(image)
            except (OSError, RuntimeError) as exc:
                result.resource_observation = {"error": str(exc)}
                result.warnings.append(f"HUD OCR unavailable: {exc}")
        if area is None:
            result.warnings.append("Could not read the layer marker; supply area and floor to review this screenshot.")
            return result
        if requested_area is not None and layer.area is not None and requested_area != layer.area:
            result.warnings.append("Manual area overrides a different layer marker in the screenshot.")
        if requested_floor is not None and layer.floor is not None and requested_floor != layer.floor:
            result.warnings.append("Manual floor overrides a different layer marker in the screenshot.")
        candidates = self.catalog.candidates(area, floor)
        work, scale = working_image(image)
        viewport = detect_map_viewport(work)
        dystopia = recognize_header(work)
        result.dystopia_observation = dystopia
        result.map_viewport = tuple(round(value / scale) for value in viewport)
        circles = detect_circles(work, viewport)
        if dystopia.get("active"):
            for point in connector_evidence(work, viewport):
                if all(np.hypot(point.x-old.x, point.y-old.y) >= 12 for old in circles):
                    circles.append(point)
        matches = match_templates(circles, candidates, (work.shape[1], work.shape[0]), image=work,
                                  refine_connectors=bool(dystopia.get("active")))
        result.template_candidates = [match.summary() for match in matches[:5]]
        if not matches:
            result.warnings.append("No template could be aligned to detected node circles.")
            return result
        selected = matches[0]
        if template_override:
            selected = next((match for match in matches if match.template.id == template_override), None)
            if selected is None:
                raise ValueError(f"template not available in this area: {template_override}")
        classified = {}
        supported = selected.matched_slots
        # Completed small nodes and irregular combat icons can escape circle detection.
        # Only image evidence supplements coverage, never a template's fixed-node hints.
        if selected.coverage < MIN_NODE_COVERAGE:
            for slot in selected.template.occupied_slots:
                pixel = selected.pixel_at(slot)
                if any(np.hypot(pixel[0] - circle.x, pixel[1] - circle.y) <= min(20, selected.grid_step * .20) for circle in circles):
                    continue
                classified[slot] = self.icons.classify_node(work, pixel, selected.grid_step, circles, dystopia=bool(dystopia.get("active")))
                if classified[slot][0] is not None:
                    supported += 1
        result.match_quality = match_quality(selected, viewport, supported / len(selected.template.occupied_slots))
        if dystopia.get("active") and supported > selected.matched_slots:
            evidence_score = (supported - .75*selected.extra_slots) / len(selected.template.occupied_slots)
            result.match_quality.update(score=round(evidence_score, 4), scoreBasis="circles_and_distorted_icons")
            result.match_quality["accepted"] = ((selected.score >= MIN_TEMPLATE_SCORE
                or (selected.score >= .50 and (selected.edge_score or 0) >= .10))
                and evidence_score >= MIN_TEMPLATE_SCORE
                and result.match_quality["coverage"] >= MIN_NODE_COVERAGE and not result.match_quality["clippedNodeIds"])
        if not result.match_quality["accepted"]:
            result.warnings.append("地图覆盖率不足、匹配分过低或节点被画面边缘裁切；请缩小地图后上传完整截图。")
            return result
        if not template_override:
            margin = float("inf")
            edge_tie_break = False
            if len(matches) > 1:
                second = matches[1]
                margin = (selected.ranking_score if selected.ranking_score is not None else selected.score) - (
                    second.ranking_score if second.ranking_score is not None else second.score
                )
                same_occupancy = (
                    selected.template.grid_shape == second.template.grid_shape
                    and set(selected.template.occupied_slots) == set(second.template.occupied_slots)
                )
                edge_tie_break = (
                    same_occupancy
                    and selected.coverage >= 0.9
                    and selected.edge_score is not None
                    and second.edge_score is not None
                    and selected.edge_score >= 0.8
                    and selected.edge_score - second.edge_score >= 0.12
                    and margin >= 0.025
                )
            if margin < 0.06 and not edge_tie_break:
                result.match_quality["accepted"] = False
                result.match_quality["reason"] = "ambiguous_template"
                result.warnings.append("Template match is weak or ambiguous; review candidates before accepting a map.")
                return result
        result.success = True
        result.template_id = selected.template.id
        pixels = [selected.pixel_at(slot) for slot in selected.template.occupied_slots]
        padding = max(25.0, selected.grid_step * 0.52)
        result.map_roi = (
            round(max(viewport[0], min(point[0] for point in pixels) - padding) / scale),
            round(max(viewport[1], min(point[1] for point in pixels) - padding) / scale),
            round(min(viewport[2], max(point[0] for point in pixels) + padding) / scale),
            round(min(viewport[3], max(point[1] for point in pixels) + padding) / scale),
        )
        result.region_id = f"treehole_floor_{floor}" if area == "treehole" and floor is not None else (
            "treehole" if area == "treehole" else selected.template.region_id
        )
        result.template_source_region_id = selected.template.region_id
        template = selected.template
        hint_counts = Counter(template.fixed_nodes.values())
        hint_counts[template.terminal_type] += len(template.terminal_slots)
        ambiguous_hints = {hint for hint in ("danger-end", "rogue-trader") if hint_counts[hint] > 1}
        for slot in template.occupied_slots:
            coord = template.coord(slot)
            wx, wy = selected.pixel_at(slot)
            node = MapNode(coord=coord, slot=slot, pixel=(wx / scale, wy / scale))
            node.template_hint = template.fixed_nodes.get(slot)
            if slot in template.terminal_slots:
                node.template_hint = template.terminal_type or "terminal"
            if slot == template.start_slot:
                node.category_id = "start"
                node.category_name = self.icons.node_labels["start"]
                node.category_score = 1.0
                node.visibility = "revealed"
            else:
                chosen, alternatives = classified[slot] if slot in classified else self.icons.classify_node(work, (wx, wy), selected.grid_step, circles, dystopia=bool(dystopia.get("active")))
                node.category_candidates = [
                    {"id": item.id, "name": item.name, "score": item.score} for item in alternatives
                ]
                if chosen:
                    node.category_id = chosen.id
                    node.category_name = chosen.name
                    node.category_score = chosen.score
                    node.visibility = "hidden" if chosen.id.startswith("unknown_") else "revealed"
                elif node.template_hint in FIXED_NODE_TYPES and node.template_hint not in ambiguous_hints:
                    node.category_id = FIXED_NODE_TYPES[node.template_hint]
                    node.category_name = self.icons.node_labels[node.category_id]
                    node.review_reasons.append("category_from_template_not_image")
                else:
                    node.review_reasons.append("category_ambiguous")
            node.marks = self.icons.detect_marks(work, (wx, wy), selected.grid_step, area=area, floor=floor)
            if node.marks:
                node.review_reasons.append("mark_candidate_requires_confirmation")
            result.nodes.append(node)
        result.edges = [
            (template.coord(a).key, template.coord(b).key) for a, b in template.edges
        ]
        work_nodes = [MapNode(node.coord, node.slot, (node.pixel[0]*scale, node.pixel[1]*scale),
                             category_id=node.category_id, category_score=node.category_score) for node in result.nodes]
        result.dystopia_observation = recognize_nodes(work, work_nodes, selected.grid_step, dystopia, difficulty=difficulty)
        if result.dystopia_observation.get("headerPixel"):
            result.dystopia_observation["headerPixel"] = [round(value/scale, 1) for value in dystopia["headerPixel"]]
        if dystopia.get("active"):
            result.warnings.append("实托邦覆盖与理想源是视觉候选；请确认范围内、范围外和待确认节点后导入。")
        result.player_position_observation = recognize_player_position(image, result.nodes)
        if result.player_position_observation["status"] != "recognized":
            result.warnings.append("Player position requires review or manual confirmation.")
        unresolved = sum(node.category_id is None for node in result.nodes)
        if unresolved:
            result.warnings.append(f"{unresolved} node categories require review.")
        result.warnings.append("Mark absence and node completion are not confirmed from one screenshot.")
        return result


def render_overlay(image: np.ndarray, result: MapResult) -> np.ndarray:
    overlay = image.copy()
    factor = max(1.0, image.shape[1] / 1280)
    line_width = round(2 * factor)
    circle_radius = round(13 * factor)
    text_offset = round(16 * factor)
    if result.map_roi:
        x0, y0, x1, y1 = result.map_roi
        cv2.rectangle(overlay, (x0, y0), (x1, y1), (75, 210, 210), line_width, cv2.LINE_AA)
    by_id = {node.coord.key: node for node in result.nodes}
    for a, b in result.edges:
        first, second = by_id[a], by_id[b]
        cv2.line(
            overlay,
            (round(first.pixel[0]), round(first.pixel[1])),
            (round(second.pixel[0]), round(second.pixel[1])),
            (230, 190, 90),
            line_width,
            cv2.LINE_AA,
        )
    for node in result.nodes:
        center = (round(node.pixel[0]), round(node.pixel[1]))
        color = (80, 220, 100) if node.category_id == "start" else (
            (220, 155, 40) if node.visibility == "hidden" else (
                (90, 210, 240) if node.category_id else (0, 190, 255)
            )
        )
        cv2.circle(overlay, center, circle_radius, color, line_width, cv2.LINE_AA)
        cv2.putText(
            overlay,
            node.coord.key,
            (center[0] + text_offset, center[1] - text_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48 * factor,
            color,
            max(1, round(1.5 * factor)),
            cv2.LINE_AA,
        )
        if node.marks:
            cv2.circle(overlay, (center[0] - text_offset, center[1] - text_offset), round(5 * factor), (210, 60, 210), -1)
        dystopia = result.dystopia_observation or {}
        if node.coord.key in dystopia.get("affectedNodeIds", []):
            cv2.circle(overlay, center, circle_radius*3, (190, 110, 210), line_width, cv2.LINE_AA)
        if node.coord.key == dystopia.get("idealSourceNodeId"):
            cv2.drawMarker(overlay, center, (80, 80, 255), cv2.MARKER_STAR, circle_radius*5, line_width)
    player = result.player_position_observation or {}
    if player.get("nodeId") in by_id:
        node = by_id[player["nodeId"]]
        color = (30, 220, 30) if player.get("status") == "recognized" else (0, 170, 255)
        cv2.circle(overlay, (round(node.pixel[0]), round(node.pixel[1])), circle_radius * 2, color, line_width, cv2.LINE_AA)
    return cv2.addWeighted(image, 0.45, overlay, 0.55, 0)
