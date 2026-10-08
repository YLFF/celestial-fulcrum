"""Ending intent and confirmed milestones; goal-priority ranking remains separate."""

from copy import deepcopy


GOAL_DEFINITIONS = {
    "ending2_sandbox": {"name": "是否已通过线人节点", "relicIds": ["relic_225"], "deadlineFloor": 4},
    "ending3_beacon": {"name": "上层或之前已获取怦然信标", "relicIds": ["relic_227"]},
    "ending3_trade": {"name": "已获取焚毁“文明”", "relicIds": ["relic_230"]},
    "ending3_tribute": {"name": "已获取击坠“神明”", "relicIds": ["relic_228"]},
    "ending3_autopsy": {"name": "已获取湮没“光明”", "relicIds": ["relic_229"]},
}
STATUSES = {"unknown", "pending", "completed", "unavailable"}
PRIORITIES = {"required", "preferred", "ignored"}
BEACON_DISPATCH_AREAS = {"II", "III", "IV", "IV-remembrance"}


def new_goals():
    return {"endingV": None, "endingVI": None, "preferences": {}, "progress": {}, "note": ""}


def planning_pursuit(goals, area_key, pursuit):
    if area_key == "V" and goals.get("endingV") in {"normal1", "pursuit1"}:
        return goals["endingV"] == "pursuit1"
    return pursuit


def validate_goals(goals):
    if not isinstance(goals, dict) or set(goals) - set(new_goals()):
        raise ValueError("invalid ending goal fields")
    if goals.get("endingV") not in (None, "normal1", "pursuit1", "ending2"):
        raise ValueError("invalid fifth-floor ending")
    if goals.get("endingVI") not in (None, "normal3", "pursuit3"):
        raise ValueError("invalid sixth-floor ending")
    if not isinstance(goals.get("note", ""), str):
        raise ValueError("goal note must be text")
    for key in ("preferences", "progress"):
        if not isinstance(goals.get(key, {}), dict) or set(goals.get(key, {})) - set(GOAL_DEFINITIONS):
            raise ValueError(f"invalid goal {key}")
    if any(not isinstance(value, str) or value not in PRIORITIES for value in goals.get("preferences", {}).values()):
        raise ValueError("goal priority must be required, preferred or ignored")
    for value in goals.get("progress", {}).values():
        if not isinstance(value, dict) or set(value) - {"status", "note"}:
            raise ValueError("invalid goal progress")
        if not isinstance(value.get("status"), str) or value["status"] not in STATUSES or not isinstance(value.get("note", ""), str):
            raise ValueError("invalid milestone status or note")


def goal_summary(state):
    goals = {**new_goals(), **state.get("goals", {})}
    validate_goals(goals)
    held = {row["id"] for row in state.get("relics", []) if row.get("count", 1) > 0}
    rows = []
    for goal_id, definition in GOAL_DEFINITIONS.items():
        default_priority = "ignored"
        if goal_id == "ending2_sandbox" and goals["endingV"] == "ending2":
            default_priority = "required"
        elif goals["endingVI"] and goal_id.startswith("ending3_"):
            default_priority = "required" if goal_id == "ending3_beacon" else "preferred"
        recorded = goals["progress"].get(goal_id, {})
        status = recorded.get("status", "unknown")
        if status == "unknown" and held.intersection(definition["relicIds"]):
            status = "completed"
        if status == "unknown" and goal_id == "ending2_sandbox" and any(row.get("id") == "encounter_022" and row.get("completedCount", 0)
                                               for row in state.get("globalEncounterPool", [])):
            status = "completed"
        rows.append({"id": goal_id, **definition, "priority": goals["preferences"].get(goal_id, default_priority),
                     "status": status, "note": recorded.get("note", "")})
    return {**deepcopy(goals), "milestones": rows, "affectsRouteRanking": True,
            "prerequisitePriorityRanking": True}


def node_goal_annotations(state, instance):
    summary = goal_summary(state)
    goals = {row["id"]: row for row in summary["milestones"]}
    result = {}
    for node_id, node in instance["nodes"].items():
        category = node.get("resolvedCategoryId") or node.get("observedCategoryId")
        marks = set(node.get("confirmedMarkIds", []))
        ids = []
        if "node_mark_002" in marks or node.get("encounterId") == "encounter_022":
            ids.append("ending2_sandbox")
        if category == "node_type_009" and instance["areaKey"] in BEACON_DISPATCH_AREAS:
            ids.append("ending3_beacon")
        for mark, goal in (("node_mark_006", "ending3_trade"), ("node_mark_005", "ending3_tribute"),
                           ("node_mark_004", "ending3_autopsy")):
            if mark in marks:
                ids.append(goal)
        if ids:
            result[node_id] = {"goals": [deepcopy(goals[key]) for key in ids],
                               "completionRequiresPlayerConfirmation": True,
                               "affectsRouteRanking": True, "prerequisitePriorityRanking": True}
    return result
