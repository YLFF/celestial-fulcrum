from __future__ import annotations

import copy
from itertools import product
import random
import unittest

from fulcrum.map_catalog import TemplateCatalog
from fulcrum.route_frontier import InventoryFrontier
from fulcrum.route_planner import RoutePlanner
from tests.test_route_planner import make_map, state


def best_per_goal(result: dict, field: str = "routes") -> dict:
    scores = {}
    for route in result[field]:
        key = (route["goalType"], route["endNode"])
        metrics = route["metrics"]
        value = (metrics["weightedValue"], metrics["newNodes"], metrics["newlyRevealedOtherNodes"],
                 metrics["treeholesReached"], metrics["survivingProcessingItems"], metrics["remainingItemUses"])
        scores[key] = max(scores.get(key, value), value)
    return scores


class RouteOptimizationTests(unittest.TestCase):
    def compare(self, game_map: dict, inputs: dict) -> tuple[dict, dict]:
        planner = RoutePlanner(game_map)
        results = [planner.plan({**inputs, "searchMode": mode, "maxStates": 200000, "topN": 50})
                   for mode in ("reference", "target")]
        for result in results:
            self.assertTrue(result["searchComplete"])
            for route in result["routes"] + result["treeholeBranches"]:
                self.assertAlmostEqual(sum(step["weightedValue"] for step in route["steps"])
                                       + route["treeholeEntryValue"], route["metrics"]["weightedValue"])
        self.assertEqual(best_per_goal(results[0]), best_per_goal(results[1]))
        self.assertEqual(best_per_goal(results[0], "treeholeBranches"), best_per_goal(results[1], "treeholeBranches"))
        return results[0], results[1]

    def test_frontier_keeps_incomparable_inventories(self) -> None:
        frontier = InventoryFrontier()
        self.assertTrue(frontier.admit(("same-state",), (1, 3), 0))
        self.assertFalse(frontier.admit(("same-state",), (1, 2), 1))
        self.assertTrue(frontier.admit(("same-state",), (2, 2), 2))
        self.assertTrue(frontier.admit(("same-state",), (2, 3), 3))
        self.assertEqual(frontier.obsolete, {0, 2})
        self.assertTrue(frontier.admit(("other-state",), (0, 0), 4))

    def test_packed_inventory_comparison_matches_each_component(self) -> None:
        frontier = InventoryFrontier((3, 3, 3))
        vectors = list(product(range(4), repeat=3))
        for left in vectors:
            for right in vectors:
                self.assertEqual(frontier._at_least(frontier._vector(left), frontier._vector(right)),
                                 all(a >= b for a, b in zip(left, right)))
        with self.assertRaisesRegex(ValueError, "bounds"):
            frontier.admit(("overflow",), (4, 0, 0), 0)

    def test_walk_preserves_items_at_equal_ap_cost(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_006"), (2, 0, "node_type_003")],
                            [("0,0", "1,0"), ("1,0", "2,0")])
        reference, target = self.compare(game_map, state(2, items=[
            {"instanceId": "wheel", "componentId": "component_013", "remainingUses": 1},
            {"instanceId": "engine", "componentId": "component_015", "remainingUses": 3},
        ]))
        self.assertEqual([step["movement"] for step in target["routes"][0]["steps"]], ["walk", "walk"])
        self.assertLess(target["generatedStates"], reference["generatedStates"])
        self.assertGreater(target["searchDiagnostics"]["walkingEquivalentItemActionsSkipped"], 0)

    def test_last_ap_can_use_controller_before_walking(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_006"), (2, 0, "node_type_003")],
                            [("0,0", "1,0"), ("1,0", "2,0")])
        items = [{"instanceId": "control", "componentId": "component_024", "remainingUses": 1}]
        _, target = self.compare(game_map, state(1, items=items))
        self.assertEqual(target["routes"][0]["steps"][0]["itemInstanceId"], "control")
        self.assertGreater(target["searchDiagnostics"]["lastActionPointExceptions"], 0)
        excluded = RoutePlanner(game_map).plan(state(1, items=items, excludeItemIds=["control"]))
        self.assertEqual(excluded["routes"], [])
        self.assertEqual(excluded["searchDiagnostics"]["lastActionPointExceptions"], 0)

    def test_last_ap_can_use_zero_cost_spring(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_006"), (2, 0, "node_type_003")],
                            [("0,0", "1,0"), ("1,0", "2,0")])
        _, target = self.compare(game_map, state(1, items=[
            {"instanceId": "spring", "componentId": "component_016", "remainingUses": 1},
        ]))
        self.assertEqual(target["routes"][0]["metrics"]["weightedValue"], 1)
        self.assertEqual(target["routes"][0]["steps"][0]["actionCost"], 0)

    def test_zero_profit_connector_and_item_launch_position_are_not_removed(self) -> None:
        game_map = make_map([(0, 0, "start"), (0, 1, "node_type_001"), (1, 0, "node_type_020"),
                             (2, 1, "node_type_006"), (3, 1, "node_type_003")],
                            [("0,0", "0,1"), ("0,0", "1,0"), ("2,1", "3,1")])
        _, target = self.compare(game_map, state(3, items=[
            {"instanceId": "engine", "componentId": "component_015", "remainingUses": 1},
        ]))
        self.assertEqual([step["arrived"] for step in target["routes"][0]["steps"]],
                         ["1,0", "2,1", "3,1"])

    def test_resource_producing_item_usage_is_not_inventory_dominated(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_006")], [("0,0", "1,0")])
        records = []
        RoutePlanner(game_map).plan(state(1, pursuit=True, items=[
            {"instanceId": "melt", "componentId": "component_021", "remainingUses": 1},
        ]), on_expand=records.append)
        self.assertEqual({record["step"]["movement"] for record in records if record["step"]}, {"walk", "item"})

    def test_tight_box_does_not_prune_consumption_choices(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_006"), (2, 0, "node_type_003")],
                            [("0,0", "1,0"), ("1,0", "2,0")])
        _, target = self.compare(game_map, state(2, componentBoxFreeSlots=1, items=[
            {"instanceId": "engine", "componentId": "component_015", "remainingUses": 1},
        ]))
        self.assertFalse(target["searchDiagnostics"]["inventoryDominanceEnabled"])

    def test_pass_end_then_return_retains_once_only_recruitment_score(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_015"), (2, 0, "node_type_006")],
                            [("0,0", "1,0"), ("1,0", "2,0")])
        game_map["nodes"][1]["recruitmentScore"] = 0.4
        _, target = self.compare(game_map, state(3))
        route = target["routes"][0]
        self.assertEqual([step["arrived"] for step in route["steps"]], ["1,0", "2,0", "1,0"])
        self.assertEqual([step["recruitmentValue"] for step in route["steps"]], [0.4, 0.0, 0.0])
        self.assertEqual(route["metrics"]["weightedValue"], 1.4)
        self.assertEqual(route["metrics"]["recruitmentValue"], 0.4)

    def test_pursuit_can_pass_end_without_leaving(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_015"), (2, 0, "node_type_006")],
                            [("0,0", "1,0"), ("1,0", "2,0")])
        _, target = self.compare(game_map, state(2, pursuit=True))
        self.assertEqual(target["routes"][0]["endNode"], "2,0")
        self.assertEqual(target["routes"][0]["goalType"], "pursuit")
        _, at_end = self.compare(game_map, state(1, pursuit=True))
        self.assertEqual(at_end["routes"][0]["endNode"], "1,0")
        self.assertEqual(at_end["routes"][0]["goalType"], "pursuit")

    def test_end_remains_a_vision_blocker_after_visiting(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_015"), (2, 0, "unknown_mystery")],
                            [("0,0", "1,0"), ("1,0", "2,0")], hidden={"2,0"})
        planner = RoutePlanner(game_map)
        self.assertFalse(planner._visible_after(0, 3, 0, None) & 4)
        self.assertTrue(planner._visible_after(1, 3, 0, None) & 4)

    def test_clearings_transmit_vision_without_being_completed(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_020"), (2, 0, "node_type_020"),
                             (3, 0, "unknown_mystery")], [("0,0", "1,0"), ("1,0", "2,0"), ("2,0", "3,0")], hidden={"3,0"})
        planner = RoutePlanner(game_map)
        self.assertEqual(planner._visible_after(0, 1, 1, None), 15)
        game_map["nodes"][1]["confirmedMarkIds"] = ["node_mark_001"]
        planner = RoutePlanner(game_map)
        self.assertFalse(planner._visible_after(0, 1, 1, None) & 8)
        self.assertTrue(planner._visible_after(0, 3, 1, None) & 8)

    def test_lookout_revealed_clearing_transmits_vision(self) -> None:
        game_map = make_map([(0, 0, "node_type_018"), (1, 0, "node_type_020"), (2, 0, "unknown_mystery")],
                            [("0,0", "1,0"), ("1,0", "2,0")], hidden={"1,0", "2,0"})
        planner = RoutePlanner(game_map)
        self.assertTrue(planner._visible_after(0, 1, 1, 0) & 4)

    def test_hidden_template_end_is_known_without_rewriting_visibility(self) -> None:
        template = TemplateCatalog().candidates("main", 1)[0]
        nodes = [(template.coord(slot).x, template.coord(slot).y,
                  "start" if slot == template.start_slot else "unknown_mystery")
                 for slot in template.occupied_slots]
        edges = [(template.coord(a).key, template.coord(b).key) for a, b in template.edges]
        game_map = make_map(nodes, edges, hidden={f"{x},{y}" for x, y, _ in nodes if (x, y) != (0, 0)})
        game_map["templateId"] = template.id
        before = copy.deepcopy(game_map)
        planner = RoutePlanner(game_map)
        terminal = template.coord(template.terminal_slots[0]).key
        index = planner.index[terminal]
        self.assertEqual(planner.nodes[index].category, "node_type_015")
        self.assertFalse(planner.nodes[index].revealed)
        self.assertFalse(planner.mystery_mask & (1 << index))
        self.assertEqual(game_map, before)
        result = planner.plan(state(8))
        self.assertTrue(result["routes"])
        self.assertEqual(result["planningNodeKnowledge"][0]["nodeId"], terminal)
        self.assertEqual(result["planningNodeKnowledge"][0]["gameVisibility"], "hidden")

    def test_explicit_hint_works_without_catalog_and_concrete_category_is_not_overwritten(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, None)], [("0,0", "1,0")], hidden={"1,0"})
        game_map["nodes"][1]["templateHint"] = "danger-end"
        self.assertEqual(RoutePlanner(game_map).nodes[1].category, "node_type_015")
        game_map["nodes"][1]["categoryId"] = "node_type_003"
        self.assertEqual(RoutePlanner(game_map).nodes[1].category, "node_type_003")

    def test_exhaustive_seeded_small_maps_agree_with_reference(self) -> None:
        rng = random.Random(4104)
        coords = [(0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (2, 1)]
        edges = [("0,0", "1,0"), ("0,0", "0,1"), ("1,0", "1,1"),
                 ("0,1", "1,1"), ("1,0", "2,0"), ("1,1", "2,1"), ("2,0", "2,1")]
        pool = ["component_013", "component_015", "component_016", "component_017", "component_020",
                "component_021", "component_022", "component_023", "component_024"]
        for case in range(100):
            with self.subTest(case=case):
                categories = ["start"] + [rng.choice(["node_type_006", "node_type_020", "node_type_018",
                              "node_type_010", "node_type_004", "unknown_mystery", "unknown_ferocity"])
                              for _ in range(4)] + [rng.choice(["node_type_003", "node_type_015", "node_type_016"])]
                if case % 10 == 0:
                    categories[1], categories[3] = "node_type_014", "node_type_014"
                game_map = make_map([(x, y, category) for (x, y), category in zip(coords, categories)], edges,
                                    hidden={f"{x},{y}" for x, y in coords if rng.choice([True, False])})
                game_map["nodes"][-1]["recruitmentScore"] = 0.3 if categories[-1] == "node_type_015" else 0
                if case % 9 == 0:
                    if game_map["nodes"][2]["categoryId"] == "node_type_004":
                        game_map["nodes"][2]["categoryId"] = "node_type_006"
                    game_map["nodes"][2]["confirmedMarkIds"] = ["node_mark_001", "node_mark_007"]
                items = [{"instanceId": f"item-{i}", "componentId": rng.choice(pool), "remainingUses": rng.randint(1, 2)}
                         for i in range(rng.randint(0, 3))]
                inputs = state(rng.randint(1, 3), items=items, pursuit=case % 3 == 0,
                               componentBoxFreeSlots=1 if case % 7 == 0 else 3)
                if case % 11 == 0:
                    inputs["utopiaId"] = "utopia_005"
                if items and case % 6 == 0:
                    inputs["excludeItemIds"] = [items[0]["instanceId"]]
                self.compare(game_map, inputs)


if __name__ == "__main__":
    unittest.main()
