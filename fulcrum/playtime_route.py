"""Adapt a confirmed Playtime snapshot to the deterministic route planner."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .component_box import route_items
from .playtime_state import active_instance, validate_playtime, rebuild_derived
from .merchant_state import snapshot_shelves
from .goals import planning_pursuit
from .scoring_profile import PROFILE
from .residents import resident_active


def route_inputs(
    playtime: dict[str, Any], area_key: str | None = None, *, pursuit: bool = False, top_n: int = PROFILE["search"]["defaultTopN"],
    recruitment_scores: Mapping[str, float] | None = None,
    scoring_mode: str = "snapshot",
    planning_goal_ids: list[str] | None = None,
    use_item_ids: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_playtime(playtime)
    playtime = deepcopy(playtime)
    rebuild_derived(playtime)
    area_key = area_key or playtime.get("currentAreaKey")
    if area_key is None:
        raise ValueError("no current area; confirm a map first")
    pursuit = planning_pursuit(playtime.get("goals", {}), area_key, pursuit)
    instance = active_instance(playtime, area_key)
    from .ending_prediction import planning_check, validate_target_ids
    selected = instance.get("strategy", {}).get("planningGoalIds", []) if planning_goal_ids is None else planning_goal_ids
    validate_target_ids(selected)
    check = planning_check(playtime, instance)
    targets = [row for row in check["targets"] if row["id"] in selected]
    if planning_goal_ids is not None and set(selected) - {row["id"] for row in check["targets"]}:
        raise ValueError("所选前置目标不适用于当前地图，请重新选择本层目标")
    position = instance.get("playerPosition")
    action = instance.get("actionPoints")
    if position is None or action is None:
        raise ValueError("player position and action points must be confirmed before route planning")
    completed = [node_id for node_id, node in instance["nodes"].items()
                 if node["completion"] == "completed" and not resident_active(node)]
    if "0,0" not in completed:
        completed.append("0,0")
    if position not in completed:
        raise ValueError("complete the current node before route planning")
    map_result = {
        "success": True, "templateId": instance["templateId"],
        "nodes": [
            {"id": node_id, "coord": node["coord"],
             "categoryId": ("node_type_020" if node["completion"] == "completed" and resident_active(node)
                            else node["resolvedCategoryId"] or node["observedCategoryId"]),
             "visibility": node["visibility"], "templateHint": node["templateHint"],
             "encounterId": node.get("encounterId"), "stageName": node.get("stageName"),
             "confirmedMarkIds": node.get("confirmedMarkIds", []), "fateRole": node.get("fateRole", "unknown"),
             "merchantViewedShelves": snapshot_shelves(node)}
            for node_id, node in instance["nodes"].items()
        ],
        "edges": instance["edges"],
    }
    if recruitment_scores is not None:
        unknown = set(recruitment_scores) - instance["nodes"].keys()
        if unknown:
            raise ValueError(f"recruitment_scores references unknown nodes: {sorted(unknown)}")
        for node in map_result["nodes"]:
            if node["id"] in recruitment_scores:
                node["recruitmentScore"] = recruitment_scores[node["id"]]
    box = playtime.get("componentBox", {"capacity": 8, "items": []})
    items = route_items(box)
    movement_item_ids = [item["instanceId"] for item in items]
    if use_item_ids is not None:
        eligible = {item["instanceId"] for item in box["items"]
                    if (item.get("remainingUses") or 0) > 0 and item["componentId"] != "component_019"}
        if (not isinstance(use_item_ids, list) or any(not isinstance(item, str) for item in use_item_ids)
                or len(set(use_item_ids)) != len(use_item_ids) or set(use_item_ids) - eligible):
            raise ValueError("所选加工品不在可用库存中，或包含随机移动的小八戒")
        movement_item_ids = list(use_item_ids)
        if scoring_mode == "legacy":
            items = [{"instanceId": item["instanceId"], "componentId": item["componentId"],
                      "remainingUses": item["remainingUses"]} for item in box["items"]
                     if item["instanceId"] in movement_item_ids]
    if scoring_mode == "snapshot":
        items = [{"instanceId": item["instanceId"], "componentId": item["componentId"],
                  "remainingUses": item["remainingUses"]} for item in box["items"]
                 if (item.get("remainingUses") or 0) > 0]
    values = {item["instanceId"]: item.get("estimatedValue") for item in box["items"]}
    for item in items:
        item["estimatedValue"] = values[item["instanceId"]]
    state = {
        "position": position, "actionPoints": action, "completedNodes": completed,
        "revealedNodes": [node_id for node_id, node in instance["nodes"].items() if node["visibility"] == "revealed"],
        "items": items,
        "componentBoxFreeSlots": max(0, box["capacity"] - len(box["items"])),
        "pursuit": pursuit, "topN": top_n,
        "difficulty": playtime.get("opening", {}).get("difficulty", 15),
        "lookoutSplitUnlocked": playtime.get("opening", {}).get("lookoutSplitUnlocked", True),
        "utopiaId": instance.get("utopiaId"),
        "dystopia": deepcopy(instance.get("dystopia")),
        "planningTargets": deepcopy(targets),
    }
    if scoring_mode == "snapshot":
        state["useItemIds"] = movement_item_ids
        state["groupByPriority"] = True
    if scoring_mode not in {"snapshot", "legacy"}:
        raise ValueError("scoring_mode must be snapshot or legacy")
    if scoring_mode == "snapshot":
        state["scoringContext"] = deepcopy({
            "areaKey": area_key, "resources": playtime["resources"],
            "opening": playtime.get("opening", {}), "operators": playtime.get("operators", []),
            "squad": playtime.get("squad", []), "grantedEffects": playtime.get("grantedEffects", []),
            "goals": playtime.get("goals", {}), "relics": playtime.get("relics", []),
            "recruitmentTickets": playtime.get("recruitmentTickets", []), "componentBox": box,
            "prediction": instance["prediction"], "globalEncounterPool": playtime.get("globalEncounterPool", []),
            "options": {**instance.get("strategy", {}).get("scoringOptions", {}),
                        "nodeWeights": instance.get("strategy", {}).get("nodeWeights", {}), "planningGoalIds": selected},
        })
    return map_result, state
