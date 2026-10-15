from __future__ import annotations

from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import os
import re

import cv2
import numpy as np

from .map_catalog import TemplateCatalog
from .map_model import MapNode, MapResult, TemplateMatch
from .vision_geometry import detect_circles, detect_map_viewport, match_templates, working_image, differing_edge_evidence, recover_layout
from .vision_icons import IconMatch, IconMatcher
from .vision_node_text import NodeLabelRecognizer
from .vision_layer import recognize_layer, recognize_layer_title
from .vision_player import recognize_player_position
from .vision_resources import HudRecognizer
from .vision_dystopia import recognize_header, connector_evidence, recognize_nodes
from .diagnostics import public_error


FIXED_NODE_TYPES = {
    "combat": "node_type_001",
    "danger-end": "node_type_015",
    "danger-enemy": "node_type_003",
    "encounter": "node_type_006",
    "fate-choice": "node_type_012",
    "rogue-trader": "node_type_004",
    "settlement": "node_type_019",
}
MIN_TEMPLATE_SCORE = 0.62
MIN_NODE_COVERAGE = 0.80


def match_quality(match, viewport, observed_coverage=None):
    radius = max(10, min(30, match.grid_step * 0.25))
    outside = [match.template.coord(slot).key for slot in match.template.occupied_slots
               if not (viewport[0] + radius <= match.pixel_at(slot)[0] <= viewport[2] - radius
                       and viewport[1] + radius <= match.pixel_at(slot)[1] <= viewport[3] - radius)]
    coverage = match.coverage if observed_coverage is None else observed_coverage
    return {"score": round(match.score, 4), "coverage": round(coverage, 4),
            "circleCoverage": round(match.circle_coverage if match.circle_coverage is not None else match.coverage, 4),
            "minimumScore": MIN_TEMPLATE_SCORE, "minimumCoverage": MIN_NODE_COVERAGE,
            "clippedNodeIds": outside,
            "accepted": match.score >= MIN_TEMPLATE_SCORE and coverage >= MIN_NODE_COVERAGE and not outside}


class MapRecognizer:
    def __init__(self, catalog: TemplateCatalog | None = None, icons: IconMatcher | None = None, *,
                 use_node_text: bool = True) -> None:
        self.catalog = catalog or TemplateCatalog()
        self.icons = icons or IconMatcher()
        self.node_text = NodeLabelRecognizer(self.icons.node_labels) if use_node_text else None

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
            raise ValueError(f"无法读取截图：{screenshot}")
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
        if layer.area is None and area is None and layer.source != "marker_conflict":
            title = recognize_layer_title(image)
            if title.area is not None:
                layer = title
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
                result.resource_observation = {"error": public_error(exc), "diagnosticDetail": str(exc)}
                result.warnings.append(f"资源文字识别不可用：{public_error(exc)}")
        if requested_area is not None and layer.area is not None and requested_area != layer.area:
            result.warnings.append("手动选择的区域与截图识别结果不同，已按手动选择处理。")
        if requested_floor is not None and layer.floor is not None and requested_floor != layer.floor:
            result.warnings.append("手动选择的层数与截图识别结果不同，已按手动选择处理。")
        if area is None:
            candidates = self.catalog.candidates("treehole") + [
                template for template in self.catalog.templates if template.kind != "treehole"]
        else:
            candidates = self.catalog.candidates(area, floor)
        work, scale = working_image(image)
        viewport = detect_map_viewport(work)
        dystopia = recognize_header(work)
        result.dystopia_observation = dystopia
        result.map_viewport = tuple(round(value / scale) for value in viewport)
        circles = detect_circles(work, viewport)
        matches = match_templates(circles, candidates, (work.shape[1], work.shape[0]), image=work,
                                  refine_connectors=bool(dystopia.get("active")))
        strong_label_fit = (matches and matches[0].coverage >= .9 and matches[0].score >= .8
                            and (matches[0].edge_score or 0) >= .25 and matches[0].point_explanation >= .6
                            and (len(matches) == 1 or matches[0].ranking_score - matches[1].ranking_score >= .08))
        if not strong_label_fit and len(matches) > 1 and matches[0].coverage >= .9 and matches[0].score >= .8:
            first, second = matches[:2]
            if (first.template.grid_shape == second.template.grid_shape
                    and set(first.template.occupied_slots) == set(second.template.occupied_slots)
                    and first.ranking_score - second.ranking_score >= .025):
                count, evidence, agreement = differing_edge_evidence(work, first, second)
                strong_label_fit = count >= 4 and evidence >= .30 and agreement >= .8
        if (not matches or matches[0].score < MIN_TEMPLATE_SCORE or (
                not strong_label_fit and (matches[0].circle_coverage if matches[0].circle_coverage is not None else matches[0].coverage) < MIN_NODE_COVERAGE)):
            if dystopia.get("active") and dystopia.get("ideologyId") != "dystopia_008":
                for point in connector_evidence(work, viewport):
                    if all(np.hypot(point.x-old.x, point.y-old.y) >= 12 for old in circles):
                        circles.append(point)
            # Dark icon rims can disappear in grayscale; add contrast-enhanced evidence before rejecting the layout.
            for circle in detect_circles(work, viewport, enhance_contrast=True):
                if all(np.hypot(circle.x - old.x, circle.y - old.y) >= 12 for old in circles):
                    circles.append(circle)
            matches = match_templates(circles, candidates, (work.shape[1], work.shape[0]), image=work,
                                      refine_connectors=bool(dystopia.get("active")))
        recovery = None
        if (not matches or (not strong_label_fit and (matches[0].score < MIN_TEMPLATE_SCORE
                or (matches[0].circle_coverage if matches[0].circle_coverage is not None else matches[0].coverage) < MIN_NODE_COVERAGE))
                or (1 in matches[0].template.grid_shape and matches[0].coverage < 1.)
                or match_quality(matches[0], viewport)["clippedNodeIds"]):
            recovered = recover_layout(image, scale, viewport, circles, candidates, matches,
                                       refine_connectors=bool(dystopia.get("active")))
            if recovered:
                matches, circles, viewport, recovery = recovered
                result.map_viewport = tuple(round(value/scale) for value in viewport)
        result.template_candidates = [match.summary() for match in matches[:5]]
        if not matches:
            result.warnings.append("未找到与截图节点布局匹配的地图模板；请上传完整地图。")
            return result
        selected = matches[0]
        if area is None:
            margin = selected.ranking_score - matches[1].ranking_score if len(matches) > 1 else 1
            if selected.coverage < .9 or selected.score < .85 or margin < .10 or layer.source == "marker_conflict":
                result.warnings.append("层数尚未确认，已保留地图模板候选；请核对区域和层数后重试。")
                return result
            area = "treehole" if selected.template.kind == "treehole" else (
                "source_confluence" if selected.template.region_id == "floor_6_source_confluence" else "main")
            floor = None if area == "treehole" else int(selected.template.region_id.split("_")[1])
            result.area, result.floor = area, floor
            result.layer_observation.update(source="unique_template", area=area, floor=floor)
        if template_override:
            selected = next((match for match in matches if match.template.id == template_override), None)
            if selected is None:
                raise ValueError(f"当前区域没有可匹配的指定地图模板：{template_override}")
        classified = {}
        text_observations = {}
        from .vision_geometry import refine_node_positions
        selected, alignment = refine_node_positions(selected, work, circles)
        local_pixels = {}
        image_evidence = {}
        proposals = {}
        def icon_at(pixel, has_label=False):
            key = (*pixel, has_label)
            if key not in image_evidence:
                previous = image_evidence.get((*pixel, False)) if has_label else None
                if previous and previous[0] and previous[0].id != "node_type_020":
                    image_evidence[key] = previous
                    return previous
                image_evidence[key] = self.icons.classify_node(
                    work, pixel, selected.grid_step, circles,
                    dystopia=bool(dystopia.get("active")), has_label=has_label)
            return image_evidence[key]

        # Floating icon centers are proposals, not corrections to the map lattice.
        for slot in selected.template.occupied_slots:
            pixel = selected.pixel_at(slot)
            trusted_small = any(circle.source == "connector" and
                np.hypot(circle.x-pixel[0], circle.y-pixel[1]) <= .08*selected.grid_step for circle in circles)
            rims = [circle for circle in circles if circle.source != "contrast"
                    and .18*selected.grid_step <= circle.radius <= .46*selected.grid_step
                    and abs(circle.x-pixel[0]) <= .13*selected.grid_step
                    and abs(circle.y-pixel[1]) <= .24*selected.grid_step]
            nearest = min(rims, key=lambda circle: np.hypot(circle.x-pixel[0], circle.y-pixel[1])) if rims and not trusted_small else None
            local_pixels[slot] = pixel
            if nearest and np.hypot(nearest.x-pixel[0], nearest.y-pixel[1]) < .035*selected.grid_step:
                local_pixels[slot] = (nearest.x, nearest.y)
            if nearest and np.hypot(nearest.x-pixel[0], nearest.y-pixel[1]) >= .035*selected.grid_step:
                proposed = (nearest.x, nearest.y)
                original, _ = icon_at(pixel)
                shifted, _ = icon_at(proposed)
                accept = bool(shifted and (
                    (original is None and shifted.score >= .60)
                    or (original and shifted.id == original.id and shifted.score >= original.score+.04)
                    or (original and original.score < .60 and shifted.score >= max(.65, original.score+.15))))
                proposals[selected.template.coord(slot).key] = {
                    "offset": [round(a-b, 2) for a, b in zip(proposed, pixel)], "accepted": accept,
                    "gridScore": original.score if original else None,
                    "shiftedScore": shifted.score if shifted else None}
                if accept:
                    local_pixels[slot] = proposed
        alignment["localProposals"] = proposals
        alignment["localOffsets"] = {selected.template.coord(slot).key: [round(a-b,2) for a,b in zip(pixel,selected.pixel_at(slot))]
                                      for slot,pixel in local_pixels.items() if pixel != selected.pixel_at(slot)}
        if self.node_text is not None and selected.score >= .50 and not match_quality(selected, viewport)["clippedNodeIds"]:
            positions = {selected.template.coord(slot).key: tuple(value / scale for value in local_pixels[slot])
                         for slot in selected.template.occupied_slots if slot != selected.template.start_slot}
            result.node_text_observation = self.node_text.recognize(image, positions, selected.grid_step / scale,
                                                                   result.map_viewport)
            text_observations = result.node_text_observation["observations"]
        label_prefixes = {re.sub(r"[“”\s]", "", name)[:2] for name in self.icons.node_labels.values()}

        def classify(slot):
            if slot not in classified:
                text = text_observations.get(selected.template.coord(slot).key)
                if text and text.get("categoryId"):
                    chosen = IconMatch(text["categoryId"], self.icons.node_labels[text["categoryId"]],
                                       round(text["confidence"] / 100, 4), 0.0)
                    classified[slot] = chosen, [chosen]
                    if chosen.id.startswith("unknown_") or text["confidence"] < 75:
                        image_match, alternatives = icon_at(local_pixels[slot], True)
                        threshold = .72 if chosen.id.startswith("unknown_") else .85
                        if (image_match and image_match.id != chosen.id and image_match.id != "node_type_020"
                                and image_match.score >= threshold
                                and image_match.score-image_match.runner_up_score >= .10):
                            text["imageConflict"] = image_match.id
                            text["categoryId"] = None
                            text["status"] = "conflict"
                            classified[slot] = None, alternatives
                else:
                    readings = (text or {}).get("variants", [text or {}])
                    has_label = any(reading.get("candidateCategoryId") or reading.get("lexicalCategoryId")
                        or (reading.get("method") != "binary" and reading.get("confidence", 0) >= 20
                            and re.search(r"[\u4e00-\u9fff]{3}", reading.get("text", ""))
                            and (reading.get("text", "")[:2] in label_prefixes or
                                 sum(a==b for a,b in zip(reading.get("text", "")[:3], "未知的")) >= 2)) for reading in readings)
                    classified[slot] = icon_at(local_pixels[slot], bool(has_label))
                    if text and text.get("candidateCategoryId") and text.get("confidence", 0) >= 50 and text.get("status") != "conflict":
                        minimum = .52 if text.get("matchKind") == "exact" and not text["candidateCategoryId"].startswith("unknown_") else .60
                        confirmed = self.icons.confirm_text_candidate(work, local_pixels[slot], selected.grid_step,
                                                                      text["candidateCategoryId"], minimum=minimum)
                        if confirmed is None:
                            confirmed = self.icons.confirm_text_candidate(work, selected.pixel_at(slot), selected.grid_step,
                                text["candidateCategoryId"], search_fraction=.22)
                        if confirmed is None and text.get("confidence", 0) >= 65 and text.get("matchKind") not in {"approximate", "prefix"}:
                            alternate = self.icons.confirm_text_candidate(work, selected.pixel_at(slot), selected.grid_step,
                                text["candidateCategoryId"], minimum=.65, include_background=True, search_fraction=.22)
                            current = classified[slot][0]
                            if alternate and (current is None or alternate.score >= current.score+.05):
                                confirmed = alternate
                        if confirmed:
                            text["confirmedByIcon"] = True
                            classified[slot] = confirmed, [confirmed] + [item for item in classified[slot][1] if item.id != confirmed.id]
                    if classified[slot][0] is None and scale < .85 and (text or {}).get("status") != "conflict":
                        candidate_ids = [item.id for item in classified[slot][1]]
                        if text and text.get("candidateCategoryId"):
                            candidate_ids.append(text["candidateCategoryId"])
                        refined = self.icons.refine_node(image, tuple(value/scale for value in local_pixels[slot]),
                            selected.grid_step/scale, candidate_ids, has_label=bool(has_label))
                        if refined:
                            classified[slot] = refined, [refined]+[item for item in classified[slot][1] if item.id != refined.id]
                            if text is not None:
                                text["confirmedByOriginalImage"] = True
            return classified[slot]

        supported = selected.matched_slots
        # Completed small nodes and irregular combat icons can escape circle detection.
        # Only image evidence supplements coverage, never a template's fixed-node hints.
        if selected.coverage < MIN_NODE_COVERAGE:
            for slot in selected.template.occupied_slots:
                pixel = selected.pixel_at(slot)
                if any(np.hypot(pixel[0] - circle.x, pixel[1] - circle.y) <= min(20, selected.grid_step * .20) for circle in circles):
                    continue
                classify(slot)
                if classified[slot][0] is not None:
                    supported += 1
        result.match_quality = match_quality(selected, viewport, supported / len(selected.template.occupied_slots))
        result.match_quality["alignment"] = alignment
        if recovery:
            result.match_quality["recovery"] = recovery
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
            occupancy_tie_break = False
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
                if same_occupancy and result.match_quality["coverage"] >= .9 and margin >= .025:
                    edge_count, evidence, agreement = differing_edge_evidence(work, selected, second)
                    result.match_quality["differingEdgeCount"] = edge_count
                    result.match_quality["differingEdgeEvidence"] = round(evidence, 4)
                    result.match_quality["differingEdgeAgreement"] = round(agreement, 4)
                    edge_tie_break = edge_tie_break or (edge_count >= 4 and evidence >= .30 and agreement >= .8)
                # A complete shorter layout can explain the same points as a longer layout with a missing cell.
                if (selected.coverage == 1 and selected.matched_slots == second.matched_slots
                        and selected.point_explanation >= second.point_explanation
                        and selected.score - second.score >= .10
                        and (selected.edge_score or 0) - (second.edge_score or 0) >= .10):
                    second_pixels = [second.pixel_at(slot) for slot in second.template.occupied_slots]
                    occupancy_tie_break = all(
                        min(np.hypot(a[0] - b[0], a[1] - b[1]) for b in second_pixels)
                        <= min(20, selected.grid_step * .20)
                        for a in (selected.pixel_at(slot) for slot in selected.template.occupied_slots)
                    )
                    if occupancy_tie_break:
                        result.match_quality["disambiguation"] = "complete_aligned_subset_and_edges"
            if margin < 0.06 and not (edge_tie_break or occupancy_tie_break):
                result.match_quality["accepted"] = False
                result.match_quality["reason"] = "ambiguous_template"
                result.warnings.append("地图模板匹配不够明确；请核对候选模板后再导入。")
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
        slots = list(template.occupied_slots)
        # OpenCV releases the GIL. Bound concurrency and share immutable template arrays.
        with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as workers:
            list(workers.map(classify, [slot for slot in slots if slot != template.start_slot]))
            def recognize_marks(slot):
                marks = self.icons.detect_marks(work, local_pixels[slot], selected.grid_step, area=area, floor=floor)
                if not marks and scale < .85:
                    marks = self.icons.refine_marks(image, tuple(value/scale for value in local_pixels[slot]),
                        selected.grid_step/scale, area=area, floor=floor)
                return marks
            marks_by_slot = dict(zip(slots, workers.map(recognize_marks, slots)))
        hint_counts = Counter(template.fixed_nodes.values())
        hint_counts[template.terminal_type] += len(template.terminal_slots)
        ambiguous_hints = {"rogue-trader"} if hint_counts["rogue-trader"] > 1 else set()
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
                node.category_source = "template_start"
            else:
                node.text_observation = text_observations.get(coord.key)
                chosen, alternatives = classify(slot)
                node.category_candidates = [
                    {"id": item.id, "name": item.name, "score": item.score} for item in alternatives
                ]
                if chosen:
                    node.category_id = chosen.id
                    node.category_name = chosen.name
                    node.category_score = chosen.score
                    node.visibility = "hidden" if chosen.id.startswith("unknown_") else "revealed"
                    node.category_source = ("text" if node.text_observation and node.text_observation.get("categoryId") else
                                            "text_and_icon" if node.text_observation and node.text_observation.get("confirmedByIcon") else "icon")
                elif node.template_hint in FIXED_NODE_TYPES and node.template_hint not in ambiguous_hints:
                    node.category_id = FIXED_NODE_TYPES[node.template_hint]
                    node.category_name = self.icons.node_labels[node.category_id]
                    node.review_reasons.append("category_from_template_not_image")
                    node.category_source = "template_hint"
                else:
                    node.review_reasons.append("category_ambiguous")
            node.marks = marks_by_slot[slot]
            if node.marks:
                from .ending_prediction import PLACEMENTS
                specifications = {spec["markId"]: spec for spec in PLACEMENTS.values()}
                for mark in node.marks:
                    spec = specifications.get(mark["id"])
                    if spec is None or node.category_id in {spec["categoryId"], spec["family"]}:
                        continue
                    observation = node.text_observation or {}
                    readings = observation.get("variants", [observation])
                    lexical = any(reading.get("lexicalCategoryId") == spec["categoryId"]
                                  and reading.get("confidence", 0) >= 50 for reading in readings)
                    confirmed = self.icons.confirm_text_candidate(work, local_pixels[slot], selected.grid_step,
                        spec["categoryId"], minimum=.50, include_background=True) if lexical and mark["score"] >= .85 else None
                    if confirmed and observation.get("status") != "conflict":
                        node.category_id, node.category_name = confirmed.id, confirmed.name
                        node.category_score = confirmed.score
                        node.category_source = "text_icon_and_mark"
                        node.visibility = "revealed"
                        observation["confirmedByMarkAndIcon"] = True
                    else:
                        node.review_reasons.append("mark_category_conflict")
                        node.category_id = node.category_name = node.category_score = None
                        node.visibility = "unknown"
                        node.category_source = "conflicting_evidence"
            if node.marks:
                node.review_reasons.append("mark_candidate_requires_confirmation")
            result.nodes.append(node)
        result.edges = [
            (template.coord(a).key, template.coord(b).key) for a, b in template.edges
        ]
        work_nodes = [MapNode(node.coord, node.slot, (node.pixel[0]*scale, node.pixel[1]*scale),
                             category_id=node.category_id, category_score=node.category_score,
                             category_candidates=node.category_candidates) for node in result.nodes]
        result.dystopia_observation = recognize_nodes(work, work_nodes, selected.grid_step, dystopia,
            difficulty=difficulty, original_image=image, image_scale=scale)
        if result.dystopia_observation.get("headerPixel"):
            result.dystopia_observation["headerPixel"] = [round(value/scale, 1) for value in dystopia["headerPixel"]]
        if result.dystopia_observation.get("active"):
            result.warnings.append("实托邦覆盖与理想源是视觉候选；请确认范围内、范围外和待确认节点后导入。")
        result.player_position_observation = recognize_player_position(image, result.nodes)
        if result.player_position_observation["status"] != "recognized":
            result.warnings.append("玩家所在位置需要核对或手动确认。")
        unresolved = [node.coord.key for node in result.nodes if node.category_id is None]
        if unresolved:
            coordinates = "、".join(f"({node_id})" for node_id in unresolved)
            result.warnings.append(f"节点 {coordinates} 的类型未识别，请在“节点候选与修正”中选择类别；这不是完成状态提醒。")
        result.warnings.append("单张截图不能确认所有节点是否已完成，也不能因未识别到标记就判定标记不存在；请核对后导入。")
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
