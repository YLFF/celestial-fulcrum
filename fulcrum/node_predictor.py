"""Offline Lubiao-style candidate filtering and distance-frequency lookup."""

from __future__ import annotations

from collections import Counter, deque
from functools import lru_cache
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PREDICTION_DATA_PATH = ROOT / "data" / "lubiao_prediction_data.json"
TEMPLATES_PATH = ROOT / "data" / "blackstream_map_templates.json"
FLOORS = ("I", "II", "III", "IV", "V")
MYSTERY_TYPES = (
    "encounter", "wish", "first-step", "rogue-trader", "secret-trader", "safe-corner",
    "narrow-meet", "gain-loss", "emergency-aid", "wrong-turn",
)
FEROCITY_TYPES = ("combat", "emergency-combat")
TYPE_TO_CATEGORY = {
    "combat": "node_type_001", "emergency-combat": "node_type_002",
    "danger-enemy": "node_type_003", "rogue-trader": "node_type_004",
    "safe-corner": "node_type_005", "encounter": "node_type_006",
    "wish": "node_type_007", "gain-loss": "node_type_008",
    "first-step": "node_type_009", "wrong-turn": "node_type_010",
    "narrow-meet": "node_type_011", "secret-trader": "node_type_013",
    "winding-path": "node_type_014", "danger-end": "node_type_015",
    "danger-path": "node_type_016", "emergency-aid": "node_type_017",
    "overlook": "node_type_018", "settlement": "node_type_019",
    "forest-clearing": "node_type_020",
    "fate-choice": "node_type_012",
}
CATEGORY_TO_TYPE = {category: node_type for node_type, category in TYPE_TO_CATEGORY.items()}


@lru_cache(maxsize=4)
def _cached_catalogs(
    data_stamp: int, templates_stamp: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    data = json.loads(PREDICTION_DATA_PATH.read_text(encoding="utf-8"))
    templates = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    by_id = {template["id"]: template for region in templates["regions"] for template in region["templates"]}
    return data, data, by_id


def _catalogs() -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    return _cached_catalogs(
        PREDICTION_DATA_PATH.stat().st_mtime_ns, TEMPLATES_PATH.stat().st_mtime_ns,
    )


def _in_range(raw: str, distance: int) -> bool:
    for part in raw.replace("–", "-").split(","):
        if not part:
            continue
        bounds = [int(value) for value in part.split("-")]
        if len(bounds) == 1 and distance == bounds[0]:
            return True
        if len(bounds) == 2 and bounds[0] <= distance <= bounds[1]:
            return True
    return False


def _count_bounds(raw: str) -> tuple[int, int] | None:
    if not raw:
        return None
    values = [int(value) for value in raw.replace("–", "-").split("-")]
    return (values[0], values[-1])


def _distances(instance: dict[str, Any], start: str = "0,0") -> dict[str, int]:
    adjacent: dict[str, set[str]] = {node_id: set() for node_id in instance["nodes"]}
    for left, right in instance["edges"]:
        if left not in adjacent or right not in adjacent:
            raise ValueError(f"edge references unknown node: {left}, {right}")
        adjacent[left].add(right)
        adjacent[right].add(left)
    for node_id, node in instance["nodes"].items():
        if node.get("resolvedCategoryId") == "node_type_015" or node.get("templateHint") == "danger-end":
            neighbors = list(adjacent[node_id])
            for left in neighbors:
                adjacent[left].update(other for other in neighbors if other != left)
    if start not in adjacent:
        raise ValueError("start node 0,0 is missing")
    distances = {start: 0}
    queue = deque([start])
    while queue:
        node_id = queue.popleft()
        for neighbor in adjacent[node_id]:
            if neighbor not in distances:
                distances[neighbor] = distances[node_id] + 1
                queue.append(neighbor)
    return distances


def _frequency(stats: dict[str, Any], node_type: str, floor_index: int, distance: int) -> dict[str, Any]:
    samples = stats["distanceSamples"].get(node_type, {}).get(str(floor_index))
    if not samples:
        return {"distanceFrequency": None, "distanceSampleCount": 0, "typeSampleCount": 0}
    total = sum(samples.values())
    count = samples.get(str(distance), 0)
    frequency = count / total
    return {"distanceFrequency": frequency, "distanceSampleCount": count, "typeSampleCount": total}


def _area_frequency(
    stats: dict[str, Any], area_key: str, node_type: str, floor_index: int, distance: int,
) -> dict[str, Any]:
    if area_key == "IV-remembrance":
        samples = stats["distanceSamples"].get(node_type, {}).get("remembrance", {})
        if not samples:
            return {"distanceFrequency": None,
                    "distanceSampleCount": 0, "typeSampleCount": 0}
        total = sum(samples.values())
        count = samples.get(str(distance), 0)
        return {"distanceFrequency": count / total,
                "distanceSampleCount": count, "typeSampleCount": total}
    return _frequency(stats, node_type, floor_index, distance)


def _settlement_candidates(
    instance: dict[str, Any], distance_by_node: dict[str, int], distance_rules: dict[str, Any],
    floor_key: str, distance_index: int,
) -> list[str]:
    if floor_key not in ("II", "IV", "V"):
        return []
    if any(node.get("resolvedCategoryId") == TYPE_TO_CATEGORY["settlement"] for node in instance["nodes"].values()):
        return []
    marked = [
        node_id for node_id, node in instance["nodes"].items()
        if "node_mark_001" in node.get("confirmedMarkIds", [])
    ]
    result = []
    for node_id, node in instance["nodes"].items():
        if node.get("resolvedCategoryId") or node.get("observedCategoryId") != "unknown_ferocity":
            continue
        distance = distance_by_node.get(node_id)
        if distance is None or not _in_range(distance_rules["settlement"][distance_index], distance):
            continue
        local_distances = _distances(instance, node_id)
        if any(not 1 <= local_distances.get(mark_id, -1) <= 5 for mark_id in marked):
            continue
        if instance.get("predictionDistanceMode") != "remembrance" and len(marked) <= 2:
            clearings = sum(
                (other["resolvedCategoryId"] == "node_type_020" or (
                    other["resolvedCategoryId"] is None and other["observedCategoryId"] == "node_type_020"
                )) and 0 < local_distances.get(other_id, 99) <= 5
                for other_id, other in instance["nodes"].items()
            )
            if clearings != len(marked):
                continue
        result.append(node_id)
    return result


def predict_instance(instance: dict[str, Any]) -> dict[str, Any]:
    """Return candidates and P(distance | type, floor), not P(type | this node)."""
    rules, stats, templates = _catalogs()
    area_key = instance["areaKey"]
    if area_key not in FLOORS and area_key != "IV-remembrance":
        reason = "treehole_prediction_not_implemented" if "treehole" in area_key else "floor_vi_prediction_not_implemented"
        return {"status": "not_applicable", "reason": reason, "nodePool": {}, "unknownNodes": {}, "warnings": []}
    count_floor_key = "IV" if area_key == "IV-remembrance" else area_key
    floor_index = FLOORS.index(count_floor_key)
    rule_index = rules["floors"].index("IV追忆" if area_key == "IV-remembrance" else area_key)
    count_rules = rules["countRanges"]
    distance_rules = rules["distanceRanges"]
    allowed_types = set(rules["allowedTypes"]["IV追忆" if area_key == "IV-remembrance" else area_key])
    counts = Counter(
        CATEGORY_TO_TYPE[node["resolvedCategoryId"]]
        for node in instance["nodes"].values()
        if node.get("resolvedCategoryId") in CATEGORY_TO_TYPE
    )
    counts["total-nodes"] = len(instance["nodes"])
    completed_counts = Counter(
        CATEGORY_TO_TYPE[node["resolvedCategoryId"]]
        for node in instance["nodes"].values()
        if node.get("resolvedCategoryId") in CATEGORY_TO_TYPE and node.get("completion") == "completed"
    )
    distance_by_node = _distances(instance)
    template = templates.get(instance["templateId"])
    evidence = template.get("dangerPathEvidenceSlots", []) if template else []
    settlement_candidates = _settlement_candidates(instance, distance_by_node, distance_rules, count_floor_key, rule_index)
    resident_mark_count = sum(
        "node_mark_001" in node.get("confirmedMarkIds", []) for node in instance["nodes"].values()
    )
    warnings = []
    conflicted_count_types = set()
    if template is None:
        warnings.append("template ID is absent from the local catalog; fixed-template evidence was skipped")
    if any(node.get("observedCategoryId") is None and node.get("resolvedCategoryId") is None for node in instance["nodes"].values()):
        warnings.append("unresolved visual categories can make known-type counts incomplete")
    if any(node.get("needsCategoryReview") for node in instance["nodes"].values()):
        warnings.append("some newly observed categories conflict with confirmed map state")
    node_pool = {}
    for node_type, by_floor in count_rules.items():
        bounds = _count_bounds(by_floor[rule_index])
        if bounds is None:
            continue
        known = counts[node_type]
        minimum, maximum = bounds
        if node_type == "fate-choice" and area_key == "V":
            entry_ids = instance.get("entrySandboxRelicIds")
            if entry_ids is not None:
                minimum = maximum = 3 if entry_ids else 0
        count_rule_conflict = known > maximum
        node_pool[node_type] = {
            "categoryId": TYPE_TO_CATEGORY.get(node_type), "minimum": minimum, "maximum": maximum,
            "knownCount": known, "completedCount": completed_counts[node_type],
            "minimumRemaining": max(0, minimum - known),
            "maximumRemaining": None if count_rule_conflict else max(0, maximum - known),
            "countRuleConflict": count_rule_conflict,
        }
        if count_rule_conflict:
            conflicted_count_types.add(node_type)
            warnings.append(
                f"confirmed {node_type} count {known} exceeds the floor maximum {maximum}; "
                "the count cap is not used to exclude further candidates"
            )
    unknown_nodes = {}
    for node_id, node in instance["nodes"].items():
        if node.get("resolvedCategoryId") is not None:
            continue
        unknown_family = node.get("observedCategoryId")
        if unknown_family not in ("unknown_mystery", "unknown_ferocity"):
            continue
        distance = distance_by_node.get(node_id)
        choices = []
        family_types = (
            (*MYSTERY_TYPES, "danger-path") if unknown_family == "unknown_mystery"
            else (*FEROCITY_TYPES, "settlement")
        )
        if distance is not None:
            family_type = "unknown-mystery" if unknown_family == "unknown_mystery" else "unknown-ferocity"
            if _in_range(distance_rules[family_type][rule_index], distance):
                candidate_types = list(MYSTERY_TYPES if unknown_family == "unknown_mystery" else FEROCITY_TYPES)
                if count_floor_key == "I" and unknown_family == "unknown_mystery":
                    candidate_types.remove("rogue-trader")
                if unknown_family == "unknown_mystery" and node["slot"] in evidence:
                    candidate_types.append("danger-path")
                if node_id in settlement_candidates:
                    candidate_types.append("settlement")
                for node_type in candidate_types:
                    if node_type not in allowed_types:
                        continue
                    if not _in_range(distance_rules.get(node_type, [""] * 6)[rule_index], distance):
                        continue
                    bounds = _count_bounds(count_rules.get(node_type, [""] * 6)[rule_index])
                    if bounds is not None and counts[node_type] >= bounds[1] and node_type not in conflicted_count_types:
                        continue
                    if resident_mark_count and len(settlement_candidates) == 1 and node_id == settlement_candidates[0] and node_type != "settlement":
                        continue
                    choices.append({
                        "nodeType": node_type,
                        "categoryId": TYPE_TO_CATEGORY[node_type],
                        "countRuleConflict": node_type in conflicted_count_types,
                        **_area_frequency(stats, area_key, node_type, floor_index, distance),
                    })
        candidate_by_type = {choice["nodeType"]: choice for choice in choices}
        unknown_nodes[node_id] = {
            "unknownFamily": unknown_family, "distanceFromStart": distance, "candidates": choices,
            "categories": {
                node_type: (
                    {"isCandidate": True, **_area_frequency(stats, area_key, node_type, floor_index, distance)}
                    if node_type in candidate_by_type and distance is not None
                    else {"isCandidate": False, "distanceFrequency": 0.0, "distanceSampleCount": 0, "typeSampleCount": 0}
                )
                for node_type in family_types
            },
        }
    return {
        "status": "needs_review" if conflicted_count_types else "ok",
        "method": "lubiao_candidates_and_distance_frequency",
        "ruleVersion": rules["ruleVersion"],
        "frequencyMeaning": "P(distance from start | node type, selected floor mode); not a normalized node posterior",
        "sampleSource": stats["sourceChunk"],
        "sampleVersion": stats["statisticsUpdatedAt"][:10],
        "nodePool": node_pool, "unknownNodes": unknown_nodes, "warnings": warnings,
    }


def update_encounter_prediction(
    prediction: dict[str, Any], instance: dict[str, Any], event_statuses: list[dict[str, Any]],
) -> None:
    """Attach current event candidates without changing node-type distance frequencies."""
    ordinary = [row for row in event_statuses if row["specialMarkId"] is None]
    candidates = [dict(row) for row in ordinary if row["eligibility"] == "possible"]
    candidate_ids = [row["id"] for row in candidates]
    prediction["encounterPool"] = {
        "candidates": candidates,
        "excluded": [dict(row) for row in ordinary if row["eligibility"] != "possible"],
        "markedEvents": [dict(row) for row in event_statuses if row["specialMarkId"] is not None],
    }
    encounter_nodes = {}
    for node_id, node in instance["nodes"].items():
        if node.get("completion") == "completed" or "node_mark_001" in node.get("confirmedMarkIds", []):
            continue
        category = node.get("resolvedCategoryId")
        if category == "node_type_006":
            event_id = node.get("encounterId")
            encounter_nodes[node_id] = {
                "basis": "confirmed_identity" if event_id else "remaining_event_pool",
                "eventCandidateIds": [event_id] if event_id else list(candidate_ids),
            }
        elif category is None:
            unknown = prediction["unknownNodes"].get(node_id, {})
            if unknown.get("categories", {}).get("encounter", {}).get("isCandidate"):
                encounter_nodes[node_id] = {
                    "basis": "conditional_on_encounter", "eventCandidateIds": list(candidate_ids),
                }
    prediction["encounterNodes"] = encounter_nodes
