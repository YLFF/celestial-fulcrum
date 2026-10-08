"""Shared ending placement, map consistency checks and per-floor soft targets."""

from .goals import BEACON_DISPATCH_AREAS, GOAL_DEFINITIONS, goal_summary


PLACEMENTS = {
    "ending2_sandbox": {"markId": "node_mark_002", "categoryId": "node_type_006", "eventId": "encounter_022",
                         "family": "unknown_mystery", "areas": {"II", "III", "IV", "IV-remembrance"}, "name": "线人（沙盘α）"},
    "ending3_trade": {"markId": "node_mark_006", "categoryId": "node_type_008", "family": "unknown_mystery",
                       "areas": {"III", "IV", "V", "IV-remembrance"}, "name": "失与得上贡"},
    "ending3_tribute": {"markId": "node_mark_005", "categoryId": "node_type_006", "eventId": "encounter_023",
                         "family": "unknown_mystery", "areas": {"III", "IV", "V", "IV-remembrance"}, "name": "泪之聚落上贡"},
    "ending3_autopsy": {"markId": "node_mark_004", "categoryId": "node_type_001", "family": "unknown_ferocity",
                         "areas": {"III", "IV", "V", "IV-remembrance"}, "name": "无效验尸"},
}
TARGET_NAMES = {**{key: row["name"] for key, row in PLACEMENTS.items()}, "ending3_beacon": "先行一步取得怦然信标"}


def validate_target_ids(ids):
    if not isinstance(ids, list) or any(not isinstance(key, str) or key not in GOAL_DEFINITIONS for key in ids) or len(ids) != len(set(ids)):
        raise ValueError("本层前置目标必须是不重复的合法目标列表")


def _category(node):
    return node.get("resolvedCategoryId") or node.get("observedCategoryId")


def _located(node, spec):
    return spec["markId"] in node.get("confirmedMarkIds", []) or spec.get("eventId") is not None and node.get("encounterId") == spec["eventId"]


def ending_placements(state, instance):
    milestones = {row["id"]: row for row in goal_summary(state)["milestones"]}
    beacon = milestones["ending3_beacon"]["status"] == "completed"
    result = {}
    for key, spec in PLACEMENTS.items():
        located = [node_id for node_id, node in instance["nodes"].items() if _located(node, spec)]
        eligible = instance["areaKey"] in spec["areas"] and milestones[key]["status"] not in {"completed", "unavailable"}
        eligible &= key == "ending2_sandbox" or beacon
        saved = instance.get("prediction", {}).get("endingPlacements", {}).get(key, {})
        probabilities = saved.get("positionProbabilities", {}) if eligible and not located else {}
        result[key] = {"goalId": key, "name": spec["name"], "categoryId": spec["categoryId"], "markId": spec["markId"],
                       "eventId": spec.get("eventId"), "eligible": bool(eligible), "locatedNodeIds": located,
                       "positionProbabilities": probabilities,
                       "basis": "mark_conditional_on_ordinary_category",
                       "guaranteedGeneration": False,
                       "requiresBeacon": key != "ending2_sandbox"}
    return result


def attach_ending_prediction(state, instance, prediction):
    placements = ending_placements(state, instance)
    prediction["endingPlacements"] = placements
    for node_id, unknown in prediction.get("unknownNodes", {}).items():
        unknown["endingOccupancy"] = []
    marked = prediction.get("encounterPool", {}).get("markedEvents", [])
    for row in marked:
        key = "ending2_sandbox" if row["id"] == "encounter_022" else "ending3_tribute" if row["id"] == "encounter_023" else None
        if key:
            spec = placements[key]
            pending = any(instance["nodes"][key].get("completion") != "completed" for key in spec["locatedNodeIds"])
            if row.get("eligibility") != "entered":
                row["eligibility"] = "possible" if spec["eligible"] or pending else "excluded"
            row["conditionStatus"] = "ending_progress"
    attach_conditional_ending_prediction(instance, prediction)


def attach_conditional_ending_prediction(instance, prediction):
    """Marks subdivide ordinary outcomes; none may force a node category."""
    prediction["endingCategoryMarks"] = {}
    for row in prediction.get("unknownNodes", {}).values():
        row["endingOccupancy"] = []
        row["conditionalEndingPlacements"] = []
        row["endingOccupancyBasis"] = "conditional_on_beta_categories"
    for placement in prediction.get("endingPlacements", {}).values():
        _attach_marker_positions(instance, prediction, placement)
    for node_id, row in prediction.get("unknownNodes", {}).items():
        specials = [value for value in row["endingOccupancy"] if value.get("eventId")]
        target = prediction.get("encounterNodes", {}).get(node_id)
        if target:
            target.pop("markedEventPlacement", None)
        if specials:
            target = prediction.setdefault("encounterNodes", {}).setdefault(node_id, {"basis": "conditional_on_encounter", "eventCandidateIds": []})
            target["markedEventPlacement"] = [{"eventId": value["eventId"], "positionProbability": value["probability"], "goalId": value["goalId"]} for value in specials]
            target["eventCandidateIds"] = list(dict.fromkeys(target["eventCandidateIds"] + [value["eventId"] for value in specials]))


def _attach_marker_positions(instance, prediction, placement):
    if not placement["eligible"] or placement["locatedNodeIds"]:
        placement["positionProbabilities"] = {}
        return
    probabilities = {}
    for node_id, node in instance["nodes"].items():
        if node.get("completion") == "completed" or node.get("templateHint") in {"danger-end", "danger-path", "danger-enemy"}:
            continue
        if placement["goalId"] == "ending3_trade" and _category(node) == "node_type_008":
            probabilities[node_id] = 1.0
        elif node_id in prediction.get("unknownNodes", {}):
            row = prediction["unknownNodes"][node_id]
            ordinary = row.get("ordinaryProbabilities")
            if ordinary is None:
                weights = {item["categoryId"]: item.get("distanceFrequency") or 0 for item in row.get("candidates", [])}
                total = sum(weights.values())
                ordinary = {key: value / total for key, value in weights.items()} if total else {}
            probabilities[node_id] = ordinary.get(placement["categoryId"], 0)
    exact = placement.get("ordinaryMarkerProbabilities")
    competing = sum(row["eligible"] and not row["locatedNodeIds"] and row["categoryId"] == placement["categoryId"]
                    for row in prediction.get("endingPlacements", {}).values())
    positions = {}
    for node_id, probability in probabilities.items():
        if not probability:
            continue
        if exact is not None:
            positions[node_id] = min(probability, exact.get(node_id, 0))
        else:
            # Compatibility fallback: average one-of-K allocation over the
            # independent ordinary slot estimates, retaining the K=0 case.
            counts = {0: 1.0}
            for other_id, other in probabilities.items():
                if other_id == node_id:
                    continue
                next_counts = {}
                for count, mass in counts.items():
                    next_counts[count] = next_counts.get(count, 0) + mass * (1 - other)
                    next_counts[count + 1] = next_counts.get(count + 1, 0) + mass * other
                counts = next_counts
            positions[node_id] = probability * sum(mass / max(count + 1, competing) for count, mass in counts.items())
    placement["positionProbabilities"] = positions
    for node_id, probability in positions.items():
        value = {**placement, "probability": probability}
        if node_id in prediction.get("unknownNodes", {}):
            field = "conditionalEndingPlacements" if placement["goalId"] == "ending3_trade" else "endingOccupancy"
            prediction["unknownNodes"][node_id][field].append(value)
        else:
            prediction["endingCategoryMarks"][node_id] = [value]


def planning_check(state, instance):
    milestones = {row["id"]: row for row in goal_summary(state)["milestones"]}
    placements = ending_placements(state, instance)
    area = instance["areaKey"]
    conflicts = []

    def conflict(code, message, node_id=None):
        conflicts.append({"code": code, "areaKey": area, "nodeId": node_id, "message": message})

    for node_id, node in instance["nodes"].items():
        marks = set(node.get("confirmedMarkIds", []))
        special = marks & {row["markId"] for row in PLACEMENTS.values()} | marks & {"node_mark_003"}
        if len(special) > 1:
            conflict("multiple_ending_marks", f"({node_id}) 同时存在不兼容的结局标记，请修正标记。", node_id)
        for key, spec in PLACEMENTS.items():
            if not _located(node, spec):
                continue
            if area not in spec["areas"]:
                conflict("mark_floor", f"({node_id}) {spec['name']}不应出现在该层，请修正层级或标记。", node_id)
            category = _category(node)
            # A clearing may retain its completed original identity; residents may cover other marks.
            if category != spec["categoryId"] and not (category == "node_type_020" and node.get("completion") == "completed"):
                conflict("mark_category", f"({node_id}) {spec['name']}的标记与节点类别不匹配，请修正节点类型或标记。", node_id)
            elif (node.get("observedCategoryId") not in {None, "unknown_mystery", "unknown_ferocity", "node_type_020", "node_type_021", spec["categoryId"]}
                  and "node_mark_001" not in marks):
                conflict("mark_observation", f"({node_id}) 图像识别类别与{spec['name']}标记不符，请确认节点类型或修正标记。", node_id)
            if node.get("completion") != "completed":
                if milestones[key]["status"] == "completed":
                    conflict("already_completed", f"({node_id}) 仍有未完成的{spec['name']}，但结局进度已勾选完成，请修正进度或标记。", node_id)
                if key != "ending2_sandbox" and milestones["ending3_beacon"]["status"] != "completed":
                    conflict("missing_beacon", f"({node_id}) {spec['name']}需要怦然信标，请确认信标进度或删除错误标记。", node_id)
        if "node_mark_003" in marks and (area != "V" or _category(node) != "node_type_012"):
            conflict("truth_mark", f"({node_id}) 谜题与谜底仅适用于五层命运所指，请修正层级、类型或标记。", node_id)
        if "node_mark_001" in marks and (_category(node) in {"node_type_004", "node_type_013", "node_type_014", "node_type_015", "node_type_016"}
                                         or _category(node) == "node_type_012" and node.get("fateRole") != "fake"):
            conflict("resident_repeatable", f"({node_id}) 流窜居民不能占领可重复进入的节点，请修正节点类别或居民标记。", node_id)
    truths = [key for key, node in instance["nodes"].items() if "node_mark_003" in node.get("confirmedMarkIds", []) or node.get("fateRole") == "true"]
    if len(truths) > 1:
        conflict("multiple_truth_nodes", f"存在多个真命运所指：{', '.join(truths)}，请修正谜底标记或节点身份。")
    for key, row in placements.items():
        pending = [node_id for node_id in row["locatedNodeIds"] if instance["nodes"][node_id].get("completion") != "completed"]
        if len(pending) > 1:
            conflict("duplicate_prerequisite", f"{row['name']}有多个未完成位置：{', '.join(pending)}，请修正地图。")
    targets = []
    for key, row in placements.items():
        pending = [node_id for node_id in row["locatedNodeIds"] if instance["nodes"][node_id].get("completion") != "completed"
                   and "node_mark_001" not in instance["nodes"][node_id].get("confirmedMarkIds", [])]
        if key == "ending3_trade":
            pending += [node_id for node_id, probability in row["positionProbabilities"].items() if probability >= 1 - 1e-9]
        if row["eligible"] and (pending or row["positionProbabilities"]):
            targets.append({"id": key, "name": TARGET_NAMES[key], "knownNodeIds": pending, "positionProbabilities": row["positionProbabilities"]})
    if area in BEACON_DISPATCH_AREAS and milestones["ending3_beacon"]["status"] not in {"completed", "unavailable"}:
        known = [node_id for node_id, node in instance["nodes"].items() if _category(node) == "node_type_009"
                 and node.get("completion") != "completed" and "node_mark_001" not in node.get("confirmedMarkIds", [])]
        unknown = instance.get("prediction", {}).get("unknownNodes", {})
        possible = [node_id for node_id, row in unknown.items() if row.get("categories", {}).get("first-step", {}).get("isCandidate")]
        if known or possible:
            targets.append({"id": "ending3_beacon", "name": TARGET_NAMES["ending3_beacon"], "knownNodeIds": known,
                            "candidateNodeIds": possible, "positionProbabilities": {}})
    selected = instance.get("strategy", {}).get("planningGoalIds", [])
    return {"valid": not conflicts, "conflicts": conflicts, "targets": targets,
            "selectedGoalIds": [key for key in selected if any(row["id"] == key for row in targets)]}


def require_planning_valid(state, instance):
    check = planning_check(state, instance)
    if not check["valid"]:
        raise ValueError("\n".join(row["message"] for row in check["conflicts"]))
    return check
