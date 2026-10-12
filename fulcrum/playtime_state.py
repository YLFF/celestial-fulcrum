"""Mutable per-area Playtime snapshots; no move-by-move event log."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .map_catalog import TemplateCatalog
from .component_box import new_component_box, validate_component_box
from .operators import validate_operator_pool
from .goals import new_goals, validate_goals
from .merchant_state import DEFAULT_INVESTMENT_BALANCE, SHOP_CATEGORIES, validate_viewed_shelves
from .node_identity import contextual_mark_id
from .opening import (
    SQUAD_NAMES, COCOON_NAMES, DEFAULT_TECHNOLOGY_COMBAT_BONUSES,
    build_opening, normalize_technology_combat_bonuses, opening_action_points,
)


ROOT = Path(__file__).resolve().parents[1]
EVENT_CATALOG = ROOT / "data" / "blackflow_encounter_pool.json"
AREA_SPECS = {
    "I": ("main", 1),
    "II": ("main", 2),
    "III": ("main", 3),
    "III-treehole": ("treehole", 3),
    "IV": ("main", 4),
    "IV-remembrance": ("main", 4),
    "IV-treehole": ("treehole", 4),
    "V": ("main", 5),
    "V-treehole": ("treehole", 5),
    "VI": ("source_confluence", 6),
}
KNOWN_MARK_EVENTS = {"node_mark_002": "encounter_022", "node_mark_005": "encounter_023"}
UNKNOWN_CATEGORIES = {None, "unknown_mystery", "unknown_ferocity"}
COMPLETION_STATES = {"unknown", "pending", "completed"}
VISIBILITY_STATES = {"unknown", "hidden", "revealed"}
UTOPIA_IDS = {f"utopia_{index:03}" for index in range(1, 10)}
FIXED_TEMPLATE_CATEGORIES = {
    "combat": "node_type_001", "danger-end": "node_type_015", "danger-enemy": "node_type_003",
    "encounter": "node_type_006", "fate-choice": "node_type_012",
    "rogue-trader": "node_type_004", "settlement": "node_type_019",
}


def _labels() -> tuple[set[str], set[str]]:
    labels = json.loads((ROOT / "data" / "vision_labels.json").read_text(encoding="utf-8"))
    return set(labels["nodeTypes"]), set(labels["nodeMarks"])


def _events() -> list[dict[str, Any]]:
    return json.loads(EVENT_CATALOG.read_text(encoding="utf-8"))["eventPool"]


def new_playtime(
    run_id: str, *, difficulty: int = 15, squad_id: str | None = None,
    cocoons: dict[str, int] | None = None,
    technology_combat_bonuses: dict[str, int | float] | None = None,
    lookout_split_unlocked: bool = True,
    initial_operators: list[dict[str, Any]] | None = None,
    investment_balance: int = DEFAULT_INVESTMENT_BALANCE,
    initial_supports: list[str] | None = None,
    initial_tickets: list[str] | None = None,
    promote_initial_mechanist: bool = False,
) -> dict[str, Any]:
    if not run_id:
        raise ValueError("run_id is required")
    opening_state = build_opening(
        difficulty=difficulty, squad_id=squad_id, cocoons=cocoons,
        technology_combat_bonuses=technology_combat_bonuses,
        lookout_split_unlocked=lookout_split_unlocked,
        initial_operators=initial_operators,
        investment_balance=investment_balance,
        initial_supports=initial_supports, initial_tickets=initial_tickets,
        promote_initial_mechanist=promote_initial_mechanist,
    )
    state = {
        "schemaVersion": 1,
        "runId": run_id,
        "currentAreaKey": None,
        "goals": new_goals(),
        **opening_state,
        "areas": {
            key: {"area": area, "floor": floor, "activeInstanceId": None, "instances": [], "encounterPool": []}
            for key, (area, floor) in AREA_SPECS.items()
        },
        "globalEncounterPool": [],
    }
    rebuild_derived(state)
    return state


def validate_playtime(state: dict[str, Any]) -> None:
    if "goals" in state:
        validate_goals(state["goals"])
    if state.get("schemaVersion") != 1 or set(state.get("areas", {})) != set(AREA_SPECS):
        raise ValueError("unsupported Playtime map schema")
    if state.get("currentAreaKey") not in set(AREA_SPECS) | {None}:
        raise ValueError("invalid current area")
    validate_component_box(state.get("componentBox", new_component_box()))
    opening = state.get("opening", {})
    if opening:
        if opening.get("squadId") not in set(SQUAD_NAMES) | {None}:
            raise ValueError("invalid opening squad")
        if type(opening.get("difficulty")) is not int or opening["difficulty"] < 0:
            raise ValueError("invalid opening difficulty")
        if not isinstance(opening.get("cocoons"), dict) or any(
            relic_id not in COCOON_NAMES or type(count) is not int or count < 1
            for relic_id, count in opening["cocoons"].items()
        ):
            raise ValueError("invalid opening cocoons")
        if "technologyCombatBonuses" in opening:
            bonuses = opening["technologyCombatBonuses"]
            if not isinstance(bonuses, dict) or set(bonuses) != set(DEFAULT_TECHNOLOGY_COMBAT_BONUSES):
                raise ValueError("incomplete technology combat bonuses")
            normalize_technology_combat_bonuses(bonuses)
        if "mechanistMasteryPreset" in opening and opening["mechanistMasteryPreset"] != "full":
            raise ValueError("unsupported mechanist mastery preset")
        if "lookoutSplitUnlocked" in opening and type(opening["lookoutSplitUnlocked"]) is not bool:
            raise ValueError("lookoutSplitUnlocked must be boolean")
    resources = state.get("resources", {})
    if "investmentBalance" in resources and (type(resources["investmentBalance"]) is not int or resources["investmentBalance"] < 0):
        raise ValueError("invalid confirmed investment balance")
    for field in ("life", "experience"):
        row = resources.get(field, {})
        if not isinstance(row, dict) or any(value is not None and (type(value) is not int or value < 0) for value in row.values()):
            raise ValueError(f"invalid resource {field}")
    for field in ("shield", "level", "hope", "originiumIngot", "investmentBalance"):
        value = resources.get(field)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"invalid resource {field}")
    for field in ("carrySlots", "deploymentSlots", "recruitmentTicketCapacity"):
        if field in resources and (type(resources[field]) is not int or resources[field] < 0):
            raise ValueError(f"invalid resource {field}")
    if not isinstance(state.get("relics", []), list) or not isinstance(state.get("operators", []), list):
        raise ValueError("invalid opening relic or operator list")
    validate_operator_pool(state.get("operators", []))
    if not isinstance(state.get("recruitmentTickets", []), list):
        raise ValueError("invalid recruitment tickets")
    for key, (area, floor) in AREA_SPECS.items():
        slot = state["areas"][key]
        if slot.get("area") != area or slot.get("floor") != floor:
            raise ValueError(f"invalid area slot {key}")
        ids = [instance["instanceId"] for instance in slot["instances"]]
        if len(ids) != len(set(ids)) or (slot["activeInstanceId"] is not None and slot["activeInstanceId"] not in ids):
            raise ValueError(f"invalid instance IDs in {key}")
        valid_categories, valid_marks = _labels()
        valid_events = {event["id"] for event in _events()}
        for instance in slot["instances"]:
            if "planningGoalIds" in instance.get("strategy", {}):
                from .ending_prediction import validate_target_ids
                validate_target_ids(instance["strategy"]["planningGoalIds"])
            sandbox_ids = instance.get("entrySandboxRelicIds")
            if sandbox_ids is not None and (key != "V" or not isinstance(sandbox_ids, list)
                    or len(sandbox_ids) != len(set(sandbox_ids))
                    or not set(sandbox_ids) <= {"relic_225", "relic_226"}):
                raise ValueError("invalid fifth-floor entry sandboxes")
            utopia_id = instance.get("utopiaId")
            if utopia_id is not None and (not isinstance(utopia_id, str) or utopia_id not in UTOPIA_IDS):
                raise ValueError(f"invalid utopia in {key}")
            if utopia_id is not None and "treehole" not in key:
                raise ValueError("乌托邦只能记录在树洞层")
            if utopia_id is not None and instance.get("dystopia", {}).get("active"):
                raise ValueError("乌托邦与实托邦不能同时生效")
            reserve = instance.get("strategy", {}).get("scoringOptions", {}).get("merchantReserve")
            if reserve is not None and (type(reserve) is not int or reserve < 0):
                raise ValueError("本层留钱金额必须为非负整数")
            nodes = instance["nodes"]
            if "dystopia" in instance:
                from .dystopia import validate_dystopia
                validate_dystopia(instance["dystopia"], nodes)
            if instance.get("areaKey") != key or "0,0" not in nodes:
                raise ValueError(f"invalid map instance in {key}")
            if instance.get("playerPosition") is not None and instance["playerPosition"] not in nodes:
                raise ValueError(f"invalid player position in {key}")
            if instance.get("playerPositionCandidate") is not None and instance["playerPositionCandidate"] not in nodes:
                raise ValueError(f"invalid player position candidate in {key}")
            if instance.get("actionPoints") is not None and (not isinstance(instance["actionPoints"], int) or instance["actionPoints"] < 0):
                raise ValueError(f"invalid action points in {key}")
            for node_id, node in nodes.items():
                if "merchantViewedShelves" in node:
                    validate_viewed_shelves(node["merchantViewedShelves"])
                    if (node.get("resolvedCategoryId") or node.get("observedCategoryId")) not in SHOP_CATEGORIES:
                        raise ValueError("merchant shelves require a confirmed shop category")
                if node["id"] != node_id or len(node["coord"]) != 2 or len(node["slot"]) != 2:
                    raise ValueError(f"invalid node geometry in {key}")
                if node.get("observedCategoryId") not in valid_categories | {None} or node.get("resolvedCategoryId") not in valid_categories | {None}:
                    raise ValueError(f"invalid node category in {key}:{node_id}")
                if node.get("fateRole", "unknown") not in {"unknown", "true", "fake"}:
                    raise ValueError(f"invalid fate role in {key}:{node_id}")
                if node.get("fateRole", "unknown") != "unknown" and node.get("resolvedCategoryId") != "node_type_012":
                    raise ValueError(f"fate role requires a fate node in {key}:{node_id}")
                if node.get("fateRole") == "fake" and "node_mark_003" in node.get("confirmedMarkIds", []):
                    raise ValueError(f"fake fate node conflicts with truth mark in {key}:{node_id}")
                if node.get("completion") not in COMPLETION_STATES or node.get("visibility") not in VISIBILITY_STATES:
                    raise ValueError(f"invalid node state in {key}:{node_id}")
                completed_category = node.get("completedCategoryId")
                if completed_category not in valid_categories | {None} or completed_category in UNKNOWN_CATEGORIES - {None}:
                    raise ValueError(f"invalid completed category in {key}:{node_id}")
                if completed_category is not None and node["completion"] != "completed":
                    raise ValueError(f"completed category requires completed node in {key}:{node_id}")
                if not set(node.get("confirmedMarkIds", [])) <= valid_marks or node.get("encounterId") not in valid_events | {None}:
                    raise ValueError(f"invalid node mark or encounter in {key}:{node_id}")
            for left, right in instance["edges"]:
                if left not in nodes or right not in nodes or left == right:
                    raise ValueError(f"invalid edge in {key}")


def active_instance(state: dict[str, Any], area_key: str) -> dict[str, Any]:
    validate_playtime(state)
    if area_key not in AREA_SPECS:
        raise ValueError(f"unknown area {area_key}")
    slot = state["areas"][area_key]
    for instance in slot["instances"]:
        if instance["instanceId"] == slot["activeInstanceId"]:
            return instance
    raise ValueError(f"no active map instance for {area_key}")


def _confirmed_marks(observed: dict[str, Any]) -> list[str]:
    return sorted({mark["id"] for mark in observed.get("marks", []) if mark.get("status") == "confirmed"})


def _node_from_observation(
    observed: dict[str, Any], area_key: str, ambiguous_hints: set[str],
) -> dict[str, Any]:
    category = observed.get("categoryId")
    area, floor = AREA_SPECS[area_key]
    marks = sorted({mapped for mark in _confirmed_marks(observed)
                    if (mapped := contextual_mark_id(mark, area, floor)) is not None})
    encounter = next((KNOWN_MARK_EVENTS[mark] for mark in marks if mark in KNOWN_MARK_EVENTS), None)
    fixed = FIXED_TEMPLATE_CATEGORIES.get(observed.get("templateHint"))
    if observed.get("templateHint") in ambiguous_hints:
        fixed = None
    resolved = "node_type_006" if encounter else "node_type_012" if "node_mark_003" in marks else (
        category if category not in UNKNOWN_CATEGORIES and category != "node_type_020" else fixed
    )
    return {
        "id": str(observed["id"]),
        "coord": list(observed["coord"]),
        "slot": list(observed["slot"]),
        "observedCategoryId": category,
        "resolvedCategoryId": resolved,
        "visibility": observed.get("visibility", "unknown"),
        "completion": "unknown",
        "completedCategoryId": None,
        "confirmedMarkIds": marks,
        "markCandidates": observed.get("marks", []),
        "encounterId": encounter,
        "encounterOutcome": None,
        "templateHint": observed.get("templateHint"),
        "fateRole": "true" if "node_mark_003" in marks else "unknown",
    }


def _validate_observation(observation: dict[str, Any], area_key: str) -> None:
    if not observation.get("success") or not observation.get("templateId") or not observation.get("nodes"):
        raise ValueError("a confirmed, matched map observation is required")
    area, floor = AREA_SPECS[area_key]
    if observation.get("area") != area or observation.get("floor") not in (None, floor):
        raise ValueError(f"observation does not belong to {area_key}")
    candidates = {template.id for template in TemplateCatalog().candidates(area, floor)}
    if observation["templateId"] not in candidates:
        raise ValueError(f"template does not belong to {area_key}")
    ids = [str(node["id"]) for node in observation["nodes"]]
    if len(ids) != len(set(ids)) or "0,0" not in ids:
        raise ValueError("map must have distinct node IDs and start 0,0")
    for left, right in observation.get("edges", []):
        if left not in ids or right not in ids or left == right:
            raise ValueError("map contains an invalid edge")
    valid_categories, valid_marks = _labels()
    for node in observation["nodes"]:
        if node.get("categoryId") not in valid_categories | {None}:
            raise ValueError(f"unknown observed category at {node['id']}")
        if any(mark.get("id") not in valid_marks for mark in node.get("marks", [])):
            raise ValueError(f"unknown observed mark at {node['id']}")
    position = observation.get("playerPositionObservation") or {}
    if position.get("nodeId") is not None and position["nodeId"] not in ids:
        raise ValueError("observed player position is not on the map")


def merge_map_observation(
    state: dict[str, Any], area_key: str, observation: dict[str, Any], *,
    new_instance: bool = False, player_position: str | None = None,
    initial_area_entry: bool = False,
    entry_sandbox_relic_ids: list[str] | None = None,
) -> dict[str, Any]:
    validate_playtime(state)
    if area_key not in AREA_SPECS:
        raise ValueError(f"unknown area {area_key}")
    _validate_observation(observation, area_key)
    if entry_sandbox_relic_ids is not None and (area_key != "V"
            or not isinstance(entry_sandbox_relic_ids, list)
            or len(entry_sandbox_relic_ids) != len(set(entry_sandbox_relic_ids))
            or not set(entry_sandbox_relic_ids) <= {"relic_225", "relic_226"}):
        raise ValueError("invalid fifth-floor entry sandboxes")
    slot = state["areas"][area_key]
    hint_counts = Counter(node.get("templateHint") for node in observation["nodes"])
    ambiguous_hints = {hint for hint in ("danger-end", "rogue-trader") if hint_counts[hint] > 1}
    existing = None if new_instance or slot["activeInstanceId"] is None else active_instance(state, area_key)
    position_observation = observation.get("playerPositionObservation") or {}
    confirmed_position = player_position or (
        position_observation.get("nodeId") if position_observation.get("status") == "recognized" else None
    )
    if initial_area_entry and (
        area_key != "I" or slot["instances"] or state["currentAreaKey"] is not None
        or confirmed_position != "0,0"
    ):
        raise ValueError("opening action override requires a fresh first-floor map at confirmed start")
    if existing is not None:
        if existing["templateId"] != observation["templateId"]:
            raise ValueError("template changed; confirm a new instance explicitly")
        if set(existing["nodes"]) != {str(node["id"]) for node in observation["nodes"]}:
            raise ValueError("node geometry changed; confirm a new instance explicitly")
        if {frozenset(edge) for edge in existing["edges"]} != {frozenset(edge) for edge in observation["edges"]}:
            raise ValueError("map edges changed; confirm a new instance explicitly")
        instance = existing
        for observed in observation["nodes"]:
            node = instance["nodes"][str(observed["id"])]
            current = _node_from_observation(observed, area_key, ambiguous_hints)
            if current["observedCategoryId"] is not None:
                node["observedCategoryId"] = current["observedCategoryId"]
            node["markCandidates"] = current["markCandidates"]
            if current["visibility"] == "revealed":
                node["visibility"] = "revealed"
            if current["resolvedCategoryId"] is not None:
                old = node["resolvedCategoryId"]
                if old is None:
                    node["resolvedCategoryId"] = current["resolvedCategoryId"]
                elif old != current["resolvedCategoryId"] and current["resolvedCategoryId"] != "node_type_020":
                    node["needsCategoryReview"] = [old, current["resolvedCategoryId"]]
            node["confirmedMarkIds"] = sorted(set(node["confirmedMarkIds"]) | set(current["confirmedMarkIds"]))
            if current["encounterId"] and node["encounterId"] is None:
                node["encounterId"] = current["encounterId"]
                node["resolvedCategoryId"] = "node_type_006"
            if current["fateRole"] == "true":
                node["fateRole"] = "true"
    else:
        instance_id = f"{area_key}-{len(slot['instances']) + 1}"
        instance = {
            "instanceId": instance_id,
            "areaKey": area_key,
            "templateId": observation["templateId"],
            "templateSourceRegionId": observation.get("templateSourceRegionId"),
            "playerPosition": None,
            "playerPositionCandidate": None,
            "actionPoints": None,
            "utopiaId": None,
            "predictionDistanceMode": "standard",
            "sourceScreenshot": observation.get("screenshot"),
            "mapImage": None,
            "nodes": {str(node["id"]): _node_from_observation(node, area_key, ambiguous_hints) for node in observation["nodes"]},
            "edges": [list(edge) for edge in observation["edges"]],
            "nodePool": {},
            "prediction": {},
            "strategy": {"goal": None, "nodeWeights": {}, "notes": None},
        }
        if initial_area_entry:
            for node in instance["nodes"].values():
                if node["observedCategoryId"] == "node_type_020":
                    node["resolvedCategoryId"] = "node_type_020"
        if area_key == "IV-remembrance":
            instance["predictionDistanceMode"] = "remembrance"
        slot["instances"].append(instance)
        slot["activeInstanceId"] = instance_id
    if player_position is not None:
        set_player_position(instance, player_position)
    elif position_observation.get("status") == "recognized" and position_observation.get("nodeId"):
        set_player_position(instance, position_observation["nodeId"])
    elif position_observation.get("status") == "needs_review":
        instance["playerPositionCandidate"] = position_observation.get("nodeId")
    if not initial_area_entry:
        merge_resource_observation(state, observation.get("resourceObservation"))
    merge_action_observation(instance, observation.get("resourceObservation"))
    if initial_area_entry:
        instance["openingObservedActionPoints"] = instance["actionPoints"]
        instance["actionPoints"] = opening_action_points(state.get("opening", {}), area_key)
    if entry_sandbox_relic_ids is not None:
        instance["entrySandboxRelicIds"] = sorted(entry_sandbox_relic_ids)
    _apply_ending2_entry(instance)
    from .dystopia import merge_dystopia_observation
    merge_dystopia_observation(instance, observation.get("dystopiaObservation"))
    state["currentAreaKey"] = area_key
    rebuild_derived(state)
    return instance


def _apply_ending2_entry(instance: dict[str, Any]) -> None:
    if instance["areaKey"] != "V":
        return
    sandbox_ids = instance.get("entrySandboxRelicIds")
    if sandbox_ids is None:
        instance["ending2Entry"] = {"status": "unknown", "sandboxCount": None}
        return
    count = len(sandbox_ids)
    instance["ending2Entry"] = {
        "status": "confirmed", "sandboxCount": count, "fateNodeCount": 3 if count else 0,
        "endingAvailable": bool(count), "autoMarkTrueNode": count == 2,
        "paidMarkAllowed": count == 1, "shopSellsSandbox": False, "informantAvailable": False,
    }
    for node in instance["nodes"].values():
        if node.get("templateHint") != "fate-choice":
            continue
        if not count and node.get("resolvedCategoryId") == "node_type_012":
            if node.get("fateRole") == "true" or "node_mark_003" in node.get("confirmedMarkIds", []):
                node["needsCategoryReview"] = ["no_fate_nodes_without_entry_sandbox", "node_type_012"]
            elif node.get("observedCategoryId") in UNKNOWN_CATEGORIES | {"node_type_020"}:
                node["resolvedCategoryId"] = ("node_type_020" if node["observedCategoryId"] == "node_type_020" else None)
                node["fateRole"] = "unknown"
            else:
                node["needsCategoryReview"] = ["no_fate_nodes_without_entry_sandbox", "node_type_012"]
        elif count and node.get("resolvedCategoryId") in (None, "node_type_012"):
            node["resolvedCategoryId"] = "node_type_012"
            node["visibility"] = "revealed"
    # Entry rules never guess which of the three nodes is the real ending.


def set_entry_sandboxes(state: dict[str, Any], relic_ids: list[str]) -> dict[str, Any]:
    instance = active_instance(state, "V")
    if (not isinstance(relic_ids, list) or len(relic_ids) != len(set(relic_ids))
            or not set(relic_ids) <= {"relic_225", "relic_226"}):
        raise ValueError("invalid fifth-floor entry sandboxes")
    instance["entrySandboxRelicIds"] = sorted(relic_ids)
    _apply_ending2_entry(instance)
    rebuild_derived(state)
    return instance


def set_player_position(instance: dict[str, Any], node_id: str) -> None:
    if node_id not in instance["nodes"]:
        raise ValueError(f"unknown player position {node_id}")
    instance["playerPosition"] = node_id
    instance["playerPositionCandidate"] = None
    node = instance["nodes"][node_id]
    node["completion"] = "completed"
    if not node.get("completedCategoryId") and node.get("resolvedCategoryId"):
        node["completedCategoryId"] = ("node_type_021" if "node_mark_001" in node.get("confirmedMarkIds", [])
                                       else node["resolvedCategoryId"])


def merge_resource_observation(state: dict[str, Any], observation: dict[str, Any] | None) -> None:
    if not observation or not isinstance(observation.get("fields"), dict):
        return
    resources = state.setdefault("resources", {})
    field_names = {"life": "life", "shield": "shield", "level": "level", "experience": "experience",
                   "hope": "hope", "originium_ingot": "originiumIngot"}
    for observed_name, target_name in field_names.items():
        field = observation["fields"].get(observed_name, {})
        if field.get("status") not in ("recognized", "absent_zero"):
            continue
        if observed_name in ("life", "experience"):
            if type(field.get("current")) is int and type(field.get("max")) is int:
                resources[target_name] = {"current": field["current"], "max": field["max"]}
        elif type(field.get("value")) is int:
            resources[target_name] = field["value"]


def merge_action_observation(instance: dict[str, Any], observation: dict[str, Any] | None) -> None:
    field = (observation or {}).get("fields", {}).get("action_points", {})
    if field.get("status") == "recognized" and type(field.get("value")) is int:
        instance["actionPoints"] = field["value"]


def update_node(
    state: dict[str, Any], area_key: str, node_id: str, *,
    category_id: str | None = None, completion: str | None = None,
    visibility: str | None = None, confirmed_mark_ids: list[str] | None = None,
    encounter_id: str | None = None, encounter_outcome: str | None = None,
    clear_encounter: bool = False,
    completed_category_id: str | None = None,
    fate_role: str | None = None,
) -> dict[str, Any]:
    instance = active_instance(state, area_key)
    if node_id not in instance["nodes"]:
        raise ValueError(f"unknown node {node_id}")
    node = instance["nodes"][node_id]
    valid_categories, valid_marks = _labels()
    if category_id is not None and category_id not in valid_categories:
        raise ValueError(f"unknown category {category_id}")
    if confirmed_mark_ids is not None and not set(confirmed_mark_ids) <= valid_marks:
        raise ValueError("unknown confirmed mark")
    # Manual choices are semantic identities; only image observations remap identical icons.
    if confirmed_mark_ids is not None:
        confirmed_mark_ids = sorted(set(confirmed_mark_ids))
    if completion is not None and completion not in COMPLETION_STATES:
        raise ValueError("completion must be unknown, pending, or completed")
    if visibility is not None and visibility not in VISIBILITY_STATES:
        raise ValueError("visibility must be unknown, hidden, or revealed")
    if encounter_id is not None and encounter_id not in {event["id"] for event in _events()}:
        raise ValueError(f"unknown encounter {encounter_id}")
    if encounter_id is not None and clear_encounter:
        raise ValueError("cannot set and clear an encounter together")
    if completed_category_id is not None:
        if completed_category_id not in valid_categories or completed_category_id in UNKNOWN_CATEGORIES:
            raise ValueError("completion requires a concrete category")
        if (completion or node["completion"]) != "completed":
            raise ValueError("completed category requires a completed node")
    marks_after = node["confirmedMarkIds"] if confirmed_mark_ids is None else confirmed_mark_ids
    completed_resident_before = node["completion"] == "completed" and "node_mark_001" in node["confirmedMarkIds"]
    marked_event = next((KNOWN_MARK_EVENTS[mark] for mark in marks_after if mark in KNOWN_MARK_EVENTS), None)
    event_after = encounter_id if encounter_id is not None else (None if clear_encounter else node["encounterId"])
    if clear_encounter and marked_event is not None:
        raise ValueError("clear the identifying mark together with the encounter")
    if marked_event is not None and event_after is not None and event_after != marked_event:
        raise ValueError("encounter conflicts with confirmed special mark")
    if category_id is not None and category_id != "node_type_006" and (marked_event or event_after):
        raise ValueError("non-encounter category conflicts with the confirmed event")
    if fate_role is not None and fate_role not in {"unknown", "true", "fake"}:
        raise ValueError("invalid fate role")
    role_category = category_id if category_id not in (None, "node_type_020") else node["resolvedCategoryId"]
    if fate_role not in (None, "unknown") and (role_category != "node_type_012" or marked_event or event_after):
        raise ValueError("fate role requires a fate node")
    if fate_role == "fake" and "node_mark_003" in marks_after:
        raise ValueError("fake fate node conflicts with truth mark")
    if category_id is not None:
        if category_id in UNKNOWN_CATEGORIES:
            raise ValueError("confirmation requires a concrete node category")
        if category_id == "node_type_020" and node["resolvedCategoryId"] not in (None, "node_type_020"):
            node["observedCategoryId"] = category_id
        else:
            node["resolvedCategoryId"] = category_id
            node["observedCategoryId"] = category_id
            if category_id != "node_type_012":
                node["fateRole"] = "unknown"
        node.pop("needsCategoryReview", None)
        node["visibility"] = "revealed"
    if completion is not None:
        node["completion"] = completion
    if visibility is not None:
        node["visibility"] = visibility
    if confirmed_mark_ids is not None:
        node["confirmedMarkIds"] = sorted(set(confirmed_mark_ids))
        marked_event = next((KNOWN_MARK_EVENTS[mark] for mark in node["confirmedMarkIds"] if mark in KNOWN_MARK_EVENTS), None)
        if marked_event:
            node["encounterId"] = marked_event
            node["resolvedCategoryId"] = "node_type_006"
            node["fateRole"] = "unknown"
            node["visibility"] = "revealed"
        elif "node_mark_003" in node["confirmedMarkIds"]:
            node["resolvedCategoryId"] = "node_type_012"
            node["fateRole"] = "true"
            node["visibility"] = "revealed"
    if fate_role is not None:
        node["fateRole"] = fate_role
    if encounter_id is not None:
        node["encounterId"] = encounter_id
        node["resolvedCategoryId"] = "node_type_006"
        node["fateRole"] = "unknown"
        node["visibility"] = "revealed"
    elif clear_encounter:
        node["encounterId"] = None
        node["encounterOutcome"] = None
    if encounter_outcome is not None:
        node["encounterOutcome"] = encounter_outcome
    if node["resolvedCategoryId"] not in SHOP_CATEGORIES:
        node.pop("merchantViewedShelves", None)
    if node["completion"] != "completed":
        node["completedCategoryId"] = None
    elif completed_category_id is not None:
        node["completedCategoryId"] = completed_category_id
    elif node.get("completedCategoryId") is None and (completion == "completed" or completed_resident_before):
        node["completedCategoryId"] = (
            "node_type_021" if completed_resident_before or "node_mark_001" in node["confirmedMarkIds"]
            else node["resolvedCategoryId"]
        )
    rebuild_derived(state)
    return node


def _event_status(
    event: dict[str, Any], area_key: str, completed: list[tuple[str, str, str]],
    instance: dict[str, Any] | None,
) -> dict[str, Any]:
    floor_roman = area_key.split("-")[0]
    local = [(key, instance_id, node_id) for key, instance_id, node_id in completed if key == area_key]
    all_count = len(completed)
    repeatability = event.get("repeatability", "unknown")
    if floor_roman not in event["floors"]:
        eligibility = "outside_floor_pool"
    elif repeatability in {"once_per_run", "until_entered"} and all_count:
        eligibility = "entered"
    elif repeatability == "inside_and_outside_once" and any(("treehole" in key) == ("treehole" in area_key) for key, _, _ in completed):
        eligibility = "entered_in_this_area_kind"
    else:
        eligibility = "possible"
    node_requirement = {
        "encounter_020": ("settlement_in_area", "node_type_019", "settlement"),
        "encounter_021": ("emergency_aid_in_area", "node_type_017", "emergency-aid"),
    }.get(event["id"])
    requirements = [node_requirement[0]] if node_requirement else []
    condition_status = "not_required"
    if node_requirement:
        _, category_id, prediction_type = node_requirement
        if instance is None:
            condition_status = "unknown"
        elif any(node["resolvedCategoryId"] == category_id for node in instance["nodes"].values()):
            condition_status = "confirmed"
        elif any(
            candidate["nodeType"] == prediction_type
            for unknown in instance["prediction"].get("unknownNodes", {}).values()
            for candidate in unknown["candidates"]
        ):
            condition_status = "possible"
        else:
            condition_status = "not_met"
            if eligibility == "possible":
                eligibility = "condition_not_met"
    return {
        "id": event["id"], "name": event["name"], "repeatability": repeatability,
        "specialMarkId": event.get("specialMarkId"),
        "eligibility": eligibility, "requirements": requirements, "conditionStatus": condition_status,
        "completedHere": len(local), "completedRun": all_count,
    }


def rebuild_derived(state: dict[str, Any]) -> None:
    from .relic_presentation import runtime_status
    state["relicRuntime"] = {row["id"]: runtime_status(state, row) for row in state.get("relics", [])}
    events = _events()
    completions: dict[str, list[tuple[str, str, str]]] = {event["id"]: [] for event in events}
    outcomes: dict[str, dict[str, str]] = {event["id"]: {} for event in events}
    for key, slot in state["areas"].items():
        for instance in slot["instances"]:
            for node in instance["nodes"].values():
                event_id = node["encounterId"]
                completed_category = node.get("completedCategoryId")
                event_was_completed = completed_category == "node_type_006" or (
                    completed_category is None and "node_mark_001" not in node["confirmedMarkIds"]
                )
                if node["completion"] == "completed" and event_id in completions and event_was_completed:
                    completions[event_id].append((key, instance["instanceId"], node["id"]))
                    if node.get("encounterOutcome"):
                        outcomes[event_id][f"{instance['instanceId']}:{node['id']}"] = node["encounterOutcome"]
    state["globalEncounterPool"] = [
        {
            "id": event["id"], "name": event["name"], "floors": event["floors"],
            "repeatability": event.get("repeatability", "unknown"),
            "completedCount": len(completions[event["id"]]),
            "completedAt": [f"{instance_id}:{node_id}" for _, instance_id, node_id in completions[event["id"]]],
            "outcomes": outcomes[event["id"]],
        }
        for event in events
    ]
    from .node_predictor import predict_instance, update_encounter_prediction

    for key, slot in state["areas"].items():
        for instance in slot["instances"]:
            fate_nodes = [node for node in instance["nodes"].values()
                          if node.get("resolvedCategoryId") == "node_type_012"]
            true_nodes = [node for node in fate_nodes if node.get("fateRole") == "true"
                          or "node_mark_003" in node.get("confirmedMarkIds", [])]
            if key == "V" and len(fate_nodes) == 3 and len(true_nodes) == 1:
                for node in fate_nodes:
                    if node is true_nodes[0]:
                        node["fateRole"] = "true"
                    elif node.get("fateRole", "unknown") == "unknown":
                        node["fateRole"] = "fake"
            prediction = predict_instance(instance)
            instance["prediction"] = prediction
            instance["nodePool"] = prediction["nodePool"]
            statuses = [
                _event_status(event, key, completions[event["id"]], instance)
                for event in events if key.split("-")[0] in event["floors"]
            ]
            update_encounter_prediction(prediction, instance, statuses)
            from .ending_prediction import attach_ending_prediction
            attach_ending_prediction(state, instance, prediction)
            from .node_posterior import attach_node_posterior
            attach_node_posterior(instance, prediction)
        current = next((instance for instance in slot["instances"] if instance["instanceId"] == slot["activeInstanceId"]), None)
        slot["encounterPool"] = [
            _event_status(event, key, completions[event["id"]], current)
            for event in events if key.split("-")[0] in event["floors"]
        ]
        if current:
            marked = {row["id"]: row for row in current["prediction"].get("encounterPool", {}).get("markedEvents", [])}
            for row in slot["encounterPool"]:
                if row["id"] in marked:
                    row["eligibility"] = marked[row["id"]]["eligibility"]
                    row["conditionStatus"] = marked[row["id"]].get("conditionStatus")
