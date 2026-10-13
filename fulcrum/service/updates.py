"""Validated UI commands mutate a draft snapshot, never a move/event replay log."""

from copy import deepcopy
import math

from ..component_box import add_component, acquire_component, apply_appraisal_event, update_component, remove_component, set_capacity
from ..goals import new_goals, validate_goals, GOAL_DEFINITIONS
from ..merchant_state import set_investment_balance, set_shop_shelves, confirm_shop_visit
from ..operators import add_operator, promote_operator, remove_operator, complete_operator_battle
from ..playtime_state import active_instance, update_node, set_player_position, set_entry_sandboxes, rebuild_derived, validate_playtime, UTOPIA_IDS, AREA_SPECS
from .catalog import entries

RESOURCE_FIELDS = {"life", "shield", "level", "experience", "hope", "originiumIngot", "totalEstimatedValue",
                   "carrySlots", "deploymentSlots", "recruitmentTicketCapacity", "investmentBalance"}
NODE_FIELDS = {"categoryId": "category_id", "completion": "completion", "visibility": "visibility",
               "markIds": "confirmed_mark_ids", "encounterId": "encounter_id", "encounterOutcome": "encounter_outcome",
               "clearEncounter": "clear_encounter", "completedCategoryId": "completed_category_id", "fateRole": "fate_role"}


def keys(data, required=(), optional=()):
    if not isinstance(data, dict) or not set(required) <= set(data) or set(data) - set(required) - set(optional):
        raise ValueError("missing or unsupported command fields")


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def validate_relics(rows):
    if not isinstance(rows, list):
        raise ValueError("relics must be a list")
    seen = set()
    for row in rows:
        keys(row, ("id",), ("count", "state", "source", "note", "enchantment"))
        entry = entries().get(row["id"])
        if not entry or entry["category"] != "relic" or row["id"] in seen:
            raise ValueError("invalid or duplicate relic ID")
        seen.add(row["id"])
        integer(row.get("count", 1), "relic count", 1)
        value = row.get("state")
        if value is not None and value not in ("active", "inactive", "已生效", "未生效"):
            integer(value, "relic layers")
        if any(key in row and not isinstance(row[key], str) for key in ("source", "note")):
            raise ValueError("relic source/note must be text")
        from ..relic_presentation import validate_binding
        validate_binding(row)


def seed_owned_milestones(state):
    held = {row["id"] for row in state.get("relics", [])}
    progress = state.setdefault("goals", new_goals()).setdefault("progress", {})
    for key, definition in GOAL_DEFINITIONS.items():
        if held.intersection(definition["relicIds"]) and key not in progress:
            progress[key] = {"status": "completed", "note": ""}


def validate_application_state(state):
    validate_playtime(state)
    validate_relics(state.get("relics", []))
    from ..team_status import OVERRIDES
    for slot in state["areas"].values():
        for instance in slot["instances"]:
            options = instance.get("strategy", {}).get("scoringOptions", {})
            if not isinstance(options, dict) or options.get("teamThresholdOverride", "auto") not in OVERRIDES:
                raise ValueError("invalid team threshold override")
    resources = state["resources"]
    if resources.get("level") is not None and not 1 <= resources["level"] <= 10:
        raise ValueError("command level must be between 1 and 10")
    for field in ("life", "experience"):
        value = resources[field]
        current, maximum = value.get("current"), value.get("max")
        if current is not None and maximum is not None and (field == "life" or maximum > 0) and current > maximum:
            raise ValueError(f"{field} current value cannot exceed its maximum")
    if resources.get("totalEstimatedValue") is not None:
        integer(resources["totalEstimatedValue"], "total estimated value")
    tickets = state.get("recruitmentTickets", [])
    if any(not isinstance(row, str) or not row.strip() for row in tickets):
        raise ValueError("recruitment tickets must be nonempty category names")
    if "memo" in state and not isinstance(state["memo"], str):
        raise ValueError("memo must be text")
    squad = state.get("squad", [])
    known = {row["instanceId"] for row in state.get("operators", [])}
    if not isinstance(squad, list) or any(not isinstance(value, str) for value in squad) or len(squad) != len(set(squad)) or not set(squad) <= known:
        raise ValueError("squad must contain distinct current operator IDs")
    if len(squad) > resources.get("carrySlots", 0):
        raise ValueError("squad exceeds confirmed carry slots")


def apply_commands(state, commands):
    if not isinstance(commands, list) or not 1 <= len(commands) <= 200:
        raise ValueError("submit between one and 200 snapshot commands")
    old_operator_ids = {row["instanceId"] for row in state.get("operators", [])}
    old_box = deepcopy(state["componentBox"])
    old_total = state["resources"].get("totalEstimatedValue")
    explicit_total = False
    for command in commands:
        kind = command.get("type") if isinstance(command, dict) else None
        if kind == "resources":
            keys(command, ("type", "values"))
            values = command["values"]
            explicit_total |= "totalEstimatedValue" in values
            keys(values, optional=RESOURCE_FIELDS)
            for field, value in values.items():
                if field in {"life", "experience"}:
                    keys(value, optional=("current", "max"))
                    state["resources"][field].update(value)
                else:
                    state["resources"][field] = value
        elif kind == "node":
            keys(command, ("type", "areaKey", "nodeId", "changes"))
            keys(command["changes"], optional=NODE_FIELDS)
            update_node(state, command["areaKey"], command["nodeId"],
                        **{NODE_FIELDS[key]: value for key, value in command["changes"].items()})
        elif kind == "nodeReset":
            keys(command, ("type", "areaKey", "nodeId", "categoryId"))
            if command["categoryId"] not in (None, "unknown_mystery", "unknown_ferocity", "node_type_020"):
                raise ValueError("reset category must be unknown or empty")
            instance = active_instance(state, command["areaKey"])
            if command["nodeId"] not in instance["nodes"]:
                raise ValueError("unknown node")
            node = instance["nodes"][command["nodeId"]]
            node.update(resolvedCategoryId=None, observedCategoryId=command["categoryId"], visibility="hidden",
                        completion="pending", completedCategoryId=None, confirmedMarkIds=[], encounterId=None,
                        encounterOutcome=None, fateRole="unknown")
            node.pop("merchantViewedShelves", None)
            node.pop("needsCategoryReview", None)
            node.pop("residentCompleted", None)
            node.pop("residentCleared", None)
        elif kind in {"position", "actionPoints", "utopia", "dystopia", "strategy"}:
            keys(command, ("type", "areaKey", "value"))
            instance = active_instance(state, command["areaKey"])
            value = command["value"]
            if kind == "position":
                set_player_position(instance, value)
            elif kind == "actionPoints":
                instance["actionPoints"] = integer(value, "action points")
            elif kind == "utopia":
                if value is not None and value not in UTOPIA_IDS:
                    raise ValueError("invalid utopia")
                if value is not None and "treehole" not in command["areaKey"]:
                    raise ValueError("乌托邦只能记录在树洞层")
                instance["utopiaId"] = value
            elif kind == "dystopia":
                from ..dystopia import set_dystopia
                set_dystopia(instance, value)
            else:
                keys(value, optional=("goal", "nodeWeights", "scoringOptions", "planningGoalIds"))
                if "planningGoalIds" in value:
                    from ..ending_prediction import validate_target_ids
                    validate_target_ids(value["planningGoalIds"])
                if "nodeWeights" in value:
                    for node_id, weight in value["nodeWeights"].items():
                        if node_id not in instance["nodes"] or type(weight) not in (int, float) or not math.isfinite(weight):
                            raise ValueError("invalid node weight")
                if "scoringOptions" in value and not isinstance(value["scoringOptions"], dict):
                    raise ValueError("scoring options must be an object")
                if "scoringOptions" in value:
                    from ..team_status import OVERRIDES
                    if value["scoringOptions"].get("teamThresholdOverride", "auto") not in OVERRIDES:
                        raise ValueError("invalid team threshold override")
                instance["strategy"].update(deepcopy(value))
            state["currentAreaKey"] = command["areaKey"]
        elif kind == "goals":
            keys(command, ("type", "value"))
            validate_goals(command["value"])
            goals = {**new_goals(), **deepcopy(state.get("goals", {})), **command["value"]}
            validate_goals(goals)
            state["goals"] = goals
        elif kind == "relics":
            keys(command, ("type", "items"))
            validate_relics(command["items"])
            from ..relic_presentation import preserve_bindings
            state["relics"] = preserve_bindings(state["relics"], command["items"])
            seed_owned_milestones(state)
        elif kind == "relicEnchant":
            keys(command, ("type", "relicId"), ("operatorInstanceId", "operatorInstanceIds"))
            if ("operatorInstanceId" in command) == ("operatorInstanceIds" in command):
                raise ValueError("请指定一个受益干员或受益干员列表")
            from ..relic_presentation import enchant_relic
            enchant_relic(state, command["relicId"], command.get("operatorInstanceIds", command.get("operatorInstanceId")))
        elif kind == "tickets":
            keys(command, ("type", "items"))
            if not isinstance(command["items"], list):
                raise ValueError("tickets must be a list of category names")
            state["recruitmentTickets"] = deepcopy(command["items"])
        elif kind == "memo":
            keys(command, ("type", "value"))
            state["memo"] = command["value"]
        elif kind == "squad":
            keys(command, ("type", "operatorIds"))
            state["squad"] = deepcopy(command["operatorIds"])
        elif kind == "currentArea":
            keys(command, ("type", "value"))
            if not isinstance(command["value"], str) or command["value"] not in AREA_SPECS:
                raise ValueError("invalid current area")
            active_instance(state, command["value"])
            state["currentAreaKey"] = command["value"]
        elif kind == "entrySandboxes":
            keys(command, ("type", "relicIds"))
            set_entry_sandboxes(state, command["relicIds"])
        elif kind == "componentAdd":
            keys(command, ("type", "componentId"), ("instanceId", "estimatedValue", "remainingUses", "routeCandidate", "recordOnly"))
            if type(command.get("recordOnly", False)) is not bool:
                raise ValueError("recordOnly must be boolean")
            add = add_component if command.get("recordOnly", False) else acquire_component
            add(state["componentBox"], command["componentId"], instance_id=command.get("instanceId"),
                          estimated_value=command.get("estimatedValue"), remaining_uses=command.get("remainingUses"),
                          route_candidate=command.get("routeCandidate", True))
        elif kind == "componentAppraisal":
            keys(command, ("type", "event"), ("count",))
            apply_appraisal_event(state["componentBox"], command["event"], command.get("count", 1))
        elif kind == "componentUpdate":
            keys(command, ("type", "instanceId", "changes"))
            update_component(state["componentBox"], command["instanceId"], **command["changes"])
        elif kind == "componentRemove":
            keys(command, ("type", "instanceId"))
            remove_component(state["componentBox"], command["instanceId"])
        elif kind == "componentCapacity":
            keys(command, ("type", "value"))
            set_capacity(state["componentBox"], command["value"])
        elif kind == "shopShelves":
            keys(command, ("type", "areaKey", "nodeId", "viewed"))
            set_shop_shelves(state, command["areaKey"], command["nodeId"], command["viewed"])
        elif kind == "shopVisit":
            keys(command, ("type", "areaKey", "nodeId"), ("viewed", "withdrawnIngots", "recordOnly"))
            confirm_shop_visit(state, command["areaKey"], command["nodeId"], viewed=command.get("viewed"),
                               withdrawn_ingots=command.get("withdrawnIngots", 0), record_only=command.get("recordOnly", False))
        elif kind == "operatorAdd":
            mapping = {"source": "source", "elite": "elite", "profession": "profession", "rarity": "rarity",
                       "instanceId": "instance_id", "hopeCost": "hope_cost", "ingotCost": "ingot_cost", "recordOnly": "record_only"}
            keys(command, ("type", "name"), mapping)
            add_operator(state, command["name"], **{new: command[old] for old, new in mapping.items() if old in command})
        elif kind == "operatorPromote":
            keys(command, ("type", "instanceId"), ("hopeCost", "recordOnly"))
            promote_operator(state, command["instanceId"], hope_cost=command.get("hopeCost"), record_only=command.get("recordOnly", False))
        elif kind == "operatorUpdate":
            keys(command, ("type", "instanceId", "changes"))
            keys(command["changes"], optional=("name", "profession", "rarity", "elite", "source", "remainingBattles", "initialRecruitment"))
            operator = next((row for row in state["operators"] if row["instanceId"] == command["instanceId"]), None)
            if operator is None:
                raise ValueError("unknown operator instance")
            operator.update(deepcopy(command["changes"]))
            from ..operator_catalog import find_operator
            entry = find_operator(operator["name"])
            if entry:
                operator["operatorId"] = entry["id"]
                if not entry.get("rarityEditable"):
                    operator["rarity"] = entry["rarity"]
                if not entry.get("professionEditable"):
                    operator["profession"] = entry["profession"]
            elif "name" in command["changes"]:
                operator.pop("operatorId", None)
        elif kind == "operatorRemove":
            keys(command, ("type", "instanceId"))
            remove_operator(state, command["instanceId"])
        elif kind == "operatorBattle":
            keys(command, ("type", "deployedIds"))
            complete_operator_battle(state, command["deployedIds"])
        else:
            raise ValueError(f"unsupported snapshot command: {kind}")
    known = {row["instanceId"] for row in state.get("operators", [])}
    if isinstance(state.get("squad", []), list):
        removed = old_operator_ids - known
        state["squad"] = [value for value in state.get("squad", []) if value not in removed]
    if state["componentBox"] != old_box and not explicit_total:
        before = sum(row.get("estimatedValue") or 0 for row in old_box["items"])
        after = sum(row.get("estimatedValue") or 0 for row in state["componentBox"]["items"])
        if old_total is not None:
            state["resources"]["totalEstimatedValue"] = max(0, old_total + after - before)
        elif all(row.get("estimatedValue") is not None for row in state["componentBox"]["items"]):
            state["resources"]["totalEstimatedValue"] = after
    rebuild_derived(state)
    validate_application_state(state)
