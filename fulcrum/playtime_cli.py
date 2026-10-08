"""Confirm Playtime map, resource, inventory and roster snapshot updates."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from .component_box import add_component, remove_component, set_capacity, update_component
from .operators import SOURCE_LABELS, add_operator, complete_operator_battle, promote_operator, remove_operator
from .merchant_state import confirm_shop_visit, set_investment_balance, set_shop_shelves
from .playtime_state import (active_instance, merge_action_observation, merge_map_observation,
                             merge_resource_observation, rebuild_derived, set_player_position,
                             set_entry_sandboxes, update_node, validate_playtime, UTOPIA_IDS)
from .playtime_view import replace_runtime_sections


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("playtime", type=Path, help="structured Playtime JSON created by scripts/new_run.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_map = subparsers.add_parser("import-map", help="confirm a matched screenshot map")
    import_map.add_argument("area_key")
    import_map.add_argument("map_json", type=Path)
    import_map.add_argument("--new-instance", action="store_true")
    import_map.add_argument("--position")
    import_map.add_argument("--initial-area-entry", action="store_true", help="apply confirmed first-floor opening action points")
    import_map.add_argument("--entry-sandbox", nargs="*", choices=("relic_225", "relic_226"),
                            help="confirmed sandboxes held when entering V; an empty list confirms none")

    sandboxes = subparsers.add_parser("set-entry-sandboxes", help="correct the V entry snapshot, not current inventory")
    sandboxes.add_argument("relic_ids", nargs="*", choices=("relic_225", "relic_226"))

    investment = subparsers.add_parser("set-investment", help="confirm the remaining investment withdrawal budget")
    investment.add_argument("value", type=int)
    shelves = subparsers.add_parser("set-shop-shelves", help="correct total viewed shelves at one confirmed merchant")
    shelves.add_argument("area_key")
    shelves.add_argument("node_id")
    shelves.add_argument("viewed", type=int)
    visit = subparsers.add_parser("shop-visit", help="confirm a shop visit and optional actual investment withdrawal")
    visit.add_argument("area_key")
    visit.add_argument("node_id")
    visit.add_argument("--viewed-shelves", type=int, help="total seen incl. initial shelf; otherwise add one, capped at five")
    visit.add_argument("--withdrawn-ingots", type=int, default=0)
    visit.add_argument("--record-only", action="store_true", help="cash already confirmed by OCR/form; only deduct investment")

    import_resources = subparsers.add_parser("import-resources", help="confirm HUD observations even if the map is partial")
    import_resources.add_argument("map_json", type=Path)
    import_resources.add_argument("--area-key", help="active area for the action-point value")

    node = subparsers.add_parser("set-node", help="correct a node in the current map instance")
    node.add_argument("area_key")
    node.add_argument("node_id")
    node.add_argument("--category")
    node.add_argument("--completion", choices=("unknown", "pending", "completed"))
    node.add_argument("--completed-category", help="correct the actual completed category independently of original identity")
    node.add_argument("--fate-role", choices=("unknown", "true", "fake"), help="confirm a fate node's identity")
    node.add_argument("--visibility", choices=("unknown", "hidden", "revealed"))
    node.add_argument("--mark", action="append", dest="marks")
    node.add_argument("--clear-marks", action="store_true")
    node.add_argument("--encounter")
    node.add_argument("--outcome")
    node.add_argument("--clear-encounter", action="store_true")

    position = subparsers.add_parser("set-position", help="confirm the player's current node")
    position.add_argument("area_key")
    position.add_argument("node_id")

    action = subparsers.add_parser("set-action", help="confirm remaining action points")
    action.add_argument("area_key")
    action.add_argument("value", type=int)

    utopia = subparsers.add_parser("set-utopia", help="confirm or clear the current area's utopia")
    utopia.add_argument("area_key")
    utopia.add_argument("utopia_id", choices=sorted(UTOPIA_IDS) + ["none"])

    add_part = subparsers.add_parser("add-component", help="add one component instance to the box")
    add_part.add_argument("component_id")
    add_part.add_argument("--instance-id")
    add_part.add_argument("--value", type=int)
    add_part.add_argument("--uses", type=int)
    add_part.add_argument("--no-route", action="store_true")

    edit_part = subparsers.add_parser("update-component", help="update one component instance")
    edit_part.add_argument("instance_id")
    edit_part.add_argument("--value", type=int)
    edit_part.add_argument("--uses", type=int)
    edit_part.add_argument("--route", action=argparse.BooleanOptionalAction, default=None)

    delete_part = subparsers.add_parser("remove-component", help="remove one component instance")
    delete_part.add_argument("instance_id")

    capacity = subparsers.add_parser("set-component-capacity", help="set component-box capacity")
    capacity.add_argument("value", type=int)

    recruit = subparsers.add_parser("add-operator", help="confirm recruitment or a one-battle support")
    recruit.add_argument("name")
    recruit.add_argument("--source", choices=sorted(SOURCE_LABELS), default="normal")
    recruit.add_argument("--elite", type=int, choices=(0, 1, 2), default=1)
    recruit.add_argument("--profession")
    recruit.add_argument("--rarity", type=int, choices=range(1, 7))
    recruit.add_argument("--instance-id")
    recruit.add_argument("--initial", action="store_true")
    recruit.add_argument("--hope-cost", type=int, help="confirmed cost; overrides Mechanist N15+ default")
    recruit.add_argument("--ingot-cost", type=int, default=0, help="confirmed emergency-shop price or other cost")
    recruit.add_argument("--record-only", action="store_true", help="resources/rewards already confirmed; update roster only")

    promote = subparsers.add_parser("promote-operator", help="confirm an elite 1 to elite 2 promotion")
    promote.add_argument("instance_id")
    promote.add_argument("--hope-cost", type=int)
    promote.add_argument("--record-only", action="store_true", help="promotion resources/reward already confirmed")

    dismiss = subparsers.add_parser("remove-operator", help="remove an operator without repeating recruitment effects")
    dismiss.add_argument("instance_id")

    battle = subparsers.add_parser("operator-battle", help="confirm a battle and expire supports actually deployed")
    battle.add_argument("--deployed", action="append", required=True, help="operator instance ID; repeatable")

    weight = subparsers.add_parser("set-weight", help="override a node's planning weight")
    weight.add_argument("area_key")
    weight.add_argument("node_id")
    weight.add_argument("value", type=float)

    goal = subparsers.add_parser("set-goal", help="set the current area's planning goal")
    goal.add_argument("area_key")
    goal.add_argument("text")

    predict = subparsers.add_parser("predict", help="print the current per-node candidate table")
    predict.add_argument("area_key")
    predict.add_argument("--out", type=Path)

    args = parser.parse_args()
    state = json.loads(args.playtime.read_text(encoding="utf-8"))
    validate_playtime(state)
    if args.command == "import-map":
        observed = json.loads(args.map_json.read_text(encoding="utf-8"))
        merge_map_observation(
            state, args.area_key, observed, new_instance=args.new_instance,
            player_position=args.position, initial_area_entry=args.initial_area_entry,
            entry_sandbox_relic_ids=args.entry_sandbox,
        )
    elif args.command == "set-entry-sandboxes":
        set_entry_sandboxes(state, args.relic_ids)
    elif args.command == "set-investment":
        set_investment_balance(state, args.value)
    elif args.command == "set-shop-shelves":
        set_shop_shelves(state, args.area_key, args.node_id, args.viewed)
    elif args.command == "shop-visit":
        confirm_shop_visit(state, args.area_key, args.node_id, viewed=args.viewed_shelves,
                           withdrawn_ingots=args.withdrawn_ingots, record_only=args.record_only)
    elif args.command == "import-resources":
        observed = json.loads(args.map_json.read_text(encoding="utf-8"))
        resources = observed.get("resourceObservation")
        if not resources or not resources.get("fields"):
            parser.error("the observation has no HUD fields; recognize the screenshot with --resources")
        merge_resource_observation(state, resources)
        area_key = args.area_key or state.get("currentAreaKey")
        if area_key:
            merge_action_observation(active_instance(state, area_key), resources)
            state["currentAreaKey"] = area_key
    elif args.command == "set-node":
        if args.marks is not None and args.clear_marks:
            parser.error("--mark and --clear-marks cannot be combined")
        update_node(
            state, args.area_key, args.node_id,
            category_id=args.category, completion=args.completion, visibility=args.visibility,
            confirmed_mark_ids=[] if args.clear_marks else args.marks,
            encounter_id=args.encounter, encounter_outcome=args.outcome,
            clear_encounter=args.clear_encounter,
            completed_category_id=args.completed_category,
            fate_role=args.fate_role,
        )
    elif args.command == "set-position":
        set_player_position(active_instance(state, args.area_key), args.node_id)
        state["currentAreaKey"] = args.area_key
    elif args.command == "set-action":
        if args.value < 0:
            parser.error("action points cannot be negative")
        active_instance(state, args.area_key)["actionPoints"] = args.value
        state["currentAreaKey"] = args.area_key
    elif args.command == "set-utopia":
        if args.utopia_id != "none" and "treehole" not in args.area_key:
            parser.error("乌托邦只能记录在树洞层")
        active_instance(state, args.area_key)["utopiaId"] = (
            None if args.utopia_id == "none" else args.utopia_id
        )
        state["currentAreaKey"] = args.area_key
    elif args.command == "add-component":
        add_component(state.setdefault("componentBox", {"capacity": 8, "items": []}), args.component_id,
                      instance_id=args.instance_id, estimated_value=args.value,
                      remaining_uses=args.uses, route_candidate=not args.no_route)
    elif args.command == "update-component":
        changes = {}
        if args.value is not None:
            changes["estimatedValue"] = args.value
        if args.uses is not None:
            changes["remainingUses"] = args.uses
        if args.route is not None:
            changes["routeCandidate"] = args.route
        update_component(state["componentBox"], args.instance_id, **changes)
    elif args.command == "remove-component":
        remove_component(state["componentBox"], args.instance_id)
    elif args.command == "set-component-capacity":
        set_capacity(state["componentBox"], args.value)
    elif args.command in {"add-operator", "promote-operator", "remove-operator", "operator-battle"}:
        try:
            if args.command == "add-operator":
                add_operator(state, args.name, source=args.source, elite=args.elite,
                             rarity=args.rarity,
                             profession=args.profession, instance_id=args.instance_id, initial=args.initial,
                             hope_cost=args.hope_cost, ingot_cost=args.ingot_cost, record_only=args.record_only)
            elif args.command == "promote-operator":
                promote_operator(state, args.instance_id, hope_cost=args.hope_cost, record_only=args.record_only)
            elif args.command == "remove-operator":
                remove_operator(state, args.instance_id)
            else:
                complete_operator_battle(state, args.deployed)
        except ValueError as error:
            parser.error(str(error))
    elif args.command == "set-weight":
        instance = active_instance(state, args.area_key)
        if args.node_id not in instance["nodes"]:
            parser.error("weight references an unknown node")
        instance["strategy"]["nodeWeights"][args.node_id] = args.value
    elif args.command == "set-goal":
        active_instance(state, args.area_key)["strategy"]["goal"] = args.text
    elif args.command == "predict":
        rebuild_derived(state)
        result = active_instance(state, args.area_key)["prediction"]
        serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.out:
            args.out.write_text(serialized, encoding="utf-8")
        else:
            print(serialized, end="")
        return
    try:
        validate_playtime(state)
    except ValueError as error:
        parser.error(str(error))
    rebuild_derived(state)
    state["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    args.playtime.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = args.playtime.with_suffix(".md")
    if markdown.exists():
        markdown.write_text(replace_runtime_sections(markdown.read_text(encoding="utf-8"), state), encoding="utf-8")
    print(f"updated {args.playtime}")


if __name__ == "__main__":
    main()
