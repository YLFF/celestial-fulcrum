from __future__ import annotations

import unittest

from fulcrum.movement_rules import MOVEMENT_RULES
from fulcrum.route_planner import RoutePlanner, item_preference


def make_map(nodes: list[tuple[int, int, str | None]], edges: list[tuple[str, str]],
             hidden: set[str] | None = None) -> dict:
    hidden = hidden or set()
    return {
        "success": True,
        "templateId": "synthetic",
        "nodes": [
            {
                "id": f"{x},{y}", "coord": [x, y], "categoryId": category,
                "visibility": "hidden" if f"{x},{y}" in hidden else "revealed",
            }
            for x, y, category in nodes
        ],
        "edges": [list(edge) for edge in edges],
    }


def state(ap: int, **changes: object) -> dict:
    return {"position": "0,0", "actionPoints": ap, "completedNodes": ["0,0"], **changes}


class MovementRulesTests(unittest.TestCase):
    def test_square_line_and_diamond_have_distinct_targets(self) -> None:
        engine = MOVEMENT_RULES["component_015"]
        wheel = MOVEMENT_RULES["component_013"]
        spring = MOVEMENT_RULES["component_016"]
        self.assertTrue(engine.reaches((0, 0), (1, 1), "node_type_001", True))
        self.assertFalse(engine.reaches((0, 0), (2, 0), "node_type_001", True))
        self.assertTrue(wheel.reaches((0, 0), (2, 0), "node_type_001", True))
        self.assertFalse(wheel.reaches((0, 0), (1, 1), "node_type_001", True))
        self.assertTrue(spring.reaches((0, 0), (1, 1), "node_type_001", True))
        self.assertTrue(spring.reaches((0, 0), (2, 0), "node_type_001", True))
        self.assertFalse(spring.reaches((0, 0), (2, 1), "node_type_001", True))

    def test_restricted_and_random_items(self) -> None:
        melt = MOVEMENT_RULES["component_021"]
        tendril = MOVEMENT_RULES["component_022"]
        self.assertTrue(melt.reaches((0, 0), (3, 2), "unknown_mystery", False))
        self.assertFalse(melt.reaches((0, 0), (3, 2), "unknown_ferocity", True))
        self.assertTrue(tendril.reaches((0, 0), (3, 2), "node_type_004", True))
        self.assertFalse(tendril.reaches((0, 0), (3, 2), "node_type_004", False))
        self.assertFalse(MOVEMENT_RULES["component_019"].reaches((0, 0), (3, 2), "node_type_005", True))


class RoutePlannerTests(unittest.TestCase):
    def test_only_confirmed_true_fate_can_be_reentered(self) -> None:
        for role in ("unknown", "fake", "true"):
            with self.subTest(role=role):
                game_map = make_map([(0, 0, "start"), (1, 0, "node_type_012")], [])
                game_map["nodes"][1]["fateRole"] = role
                planner = RoutePlanner(game_map)
                result = planner.plan(state(1, position="1,0", completedNodes=["0,0", "1,0"], pursuit=True))
                if role == "true":
                    self.assertEqual(result["routes"][0]["steps"][0]["movement"], "reenter")
                    self.assertTrue(result["routes"][0]["steps"][0]["fateChoicePending"])
                else:
                    self.assertEqual(result["routes"], [])

    def test_exit_requires_arrival_and_counts_new_node_once(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "node_type_015")],
            [("0,0", "1,0"), ("1,0", "2,0")],
        )
        result = RoutePlanner(game_map).plan(state(2))
        self.assertTrue(result["searchComplete"])
        route = result["routes"][0]
        self.assertEqual(route["endNode"], "2,0")
        self.assertEqual(route["remainingActionPoints"], 0)
        self.assertEqual(route["metrics"]["newNodes"], 1)
        self.assertEqual([step["movement"] for step in route["steps"]], ["walk", "walk"])

    def test_full_engine_is_used_before_destroying_last_prosthesis(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 1, "node_type_006"), (2, 1, "node_type_015")],
            [("1,1", "2,1")],
        )
        items = [
            {"instanceId": "leg", "componentId": "component_014", "remainingUses": 1},
            {"instanceId": "engine", "componentId": "component_015", "remainingUses": 3},
        ]
        planner = RoutePlanner(game_map)
        result = planner.plan(state(2, items=items))
        self.assertEqual(result["routes"][0]["steps"][0]["itemInstanceId"], "engine")
        self.assertEqual(result["routes"][0]["metrics"]["survivingProcessingItems"], 2)
        excluded = planner.plan(state(2, items=items, excludeItemIds=["engine"]))
        self.assertEqual(excluded["routes"][0]["steps"][0]["itemInstanceId"], "leg")
        self.assertEqual(excluded["routes"][0]["metrics"]["survivingProcessingItems"], 1)

    def test_pursuit_ends_at_zero_ap_without_entering_exit(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "node_type_015")],
            [("0,0", "1,0"), ("1,0", "2,0")],
        )
        result = RoutePlanner(game_map).plan(state(1, pursuit=True))
        self.assertEqual(result["routes"][0]["goalType"], "pursuit")
        self.assertEqual(result["routes"][0]["endNode"], "1,0")
        self.assertEqual(result["routes"][0]["remainingActionPoints"], 0)

    def test_zero_cost_arrival_at_lookout_still_adds_one_ap_and_reveals(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_018"), (2, 0, "node_type_015"), (4, 0, "unknown_mystery")],
            [("1,0", "2,0")], hidden={"2,0", "4,0"},
        )
        result = RoutePlanner(game_map).plan(state(1, items=[
            {"instanceId": "jet", "componentId": "component_020", "remainingUses": 1},
        ]))
        route = result["routes"][0]
        self.assertEqual(route["steps"][0]["actionCost"], 0)
        self.assertEqual(route["steps"][0]["actionGain"], 1)
        self.assertEqual(route["steps"][0]["actionPointsAfter"], 2)
        self.assertIn("4,0", route["steps"][0]["newlyRevealedOtherNodes"])
        self.assertNotIn("2,0", route["steps"][0]["newlyRevealedOtherNodes"])  # Already visible on spawn.
        self.assertEqual(route["metrics"]["newlyRevealedOtherNodes"], 1)

    def test_revealing_unknown_nodes_adds_weight_once(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_006"),
             (2, 0, "unknown_mystery"), (1, 1, "unknown_ferocity"),
             (3, 0, "node_type_015")],
            [("0,0", "1,0"), ("1,0", "2,0"), ("1,0", "1,1"), ("2,0", "3,0")],
            hidden={"2,0", "1,1", "3,0"},
        )
        route = RoutePlanner(game_map).plan(state(3))["routes"][0]
        first = route["steps"][0]
        self.assertEqual(first["revealedUnknownMysteryNodes"], ["2,0"])
        self.assertEqual(first["revealedUnknownFerocityNodes"], ["1,1"])
        self.assertEqual(first["nodeValue"], 1.0)
        self.assertEqual(first["revealValue"], 0.25)
        self.assertEqual(route["steps"][1]["nodeValue"], 0.5)
        self.assertEqual(route["steps"][1]["revealValue"], 0.0)
        self.assertEqual(route["metrics"]["weightedValue"], 1.75)
        self.assertEqual(route["metrics"]["revealedUnknownMystery"], 1)
        self.assertEqual(route["metrics"]["revealedUnknownFerocity"], 1)

    def test_known_node_ranks_above_unknown_ferocity_at_equal_cost(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_006"),
             (0, 1, "unknown_ferocity"), (1, 1, "node_type_015")],
            [("0,0", "1,0"), ("1,0", "1,1"),
             ("0,0", "0,1"), ("0,1", "1,1")],
        )
        planner = RoutePlanner(game_map)
        selected = planner.plan(state(2, topN=1))["routes"][0]
        self.assertEqual(selected["steps"][0]["arrived"], "1,0")
        self.assertEqual(selected["metrics"]["weightedValue"], 1.0)
        forced = planner.plan(state(2, blockedNodes=["1,0"]))["routes"][0]
        self.assertEqual(forced["steps"][0]["arrived"], "0,1")
        self.assertEqual(forced["metrics"]["weightedValue"], 0.8)

    def test_revisiting_does_not_reaward_node_or_reveal(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_006"), (2, 0, "unknown_mystery")],
            [("0,0", "1,0"), ("1,0", "2,0")], hidden={"2,0"},
        )
        route = RoutePlanner(game_map).plan(state(
            3, pursuit=True, blockedNodes=["2,0"],
        ))["routes"][0]
        self.assertEqual(len(route["steps"]), 3)
        self.assertEqual([step["weightedValue"] for step in route["steps"]], [1.2, 0.0, 0.0])
        self.assertEqual(route["metrics"]["weightedValue"], 1.2)

    def test_lookout_only_grants_ap_on_first_arrival(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_018")], [("0,0", "1,0")],
        )
        result = RoutePlanner(game_map).plan(state(2, pursuit=True))
        route = next(route for route in result["routes"] if len(route["steps"]) == 3)
        self.assertEqual([step["actionGain"] for step in route["steps"]], [1, 0, 0])
        self.assertEqual(route["endNode"], "1,0")

    def test_portal_transfer_is_atomic_and_has_no_node_reward(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_014"), (4, 0, "node_type_014"),
             (5, 0, "node_type_015")],
            [("0,0", "1,0"), ("4,0", "5,0")],
        )
        route = RoutePlanner(game_map).plan(state(2))["routes"][0]
        self.assertEqual(route["steps"][0]["entered"], "1,0")
        self.assertEqual(route["steps"][0]["arrived"], "4,0")
        self.assertTrue(route["steps"][0]["portalTransfer"])
        self.assertEqual(route["metrics"]["newNodes"], 0)

    def test_treehole_is_a_replanning_branch_not_an_exit(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_010"), (2, 0, "node_type_015")],
            [("0,0", "1,0"), ("1,0", "2,0")],
        )
        result = RoutePlanner(game_map).plan(state(2, items=[
            {"instanceId": "leg", "componentId": "component_014", "remainingUses": 1},
        ]))
        self.assertEqual(result["routes"][0]["endNode"], "2,0")
        self.assertEqual(result["routes"][0]["metrics"]["newNodes"], 0)
        branch = result["treeholeBranches"][0]
        self.assertEqual(branch["goalType"], "treehole_replan")
        self.assertEqual(branch["endNode"], "1,0")
        self.assertEqual(branch["treeholeEntryItemInstanceId"], "leg")
        self.assertEqual(branch["remainingItems"][0]["remainingUses"], 0)
        self.assertEqual(branch["metrics"]["treeholesReached"], 1)
        self.assertEqual(branch["metrics"]["newNodes"], 1)
        self.assertEqual(RoutePlanner(game_map).plan(state(2))["treeholeBranches"], [])

    def test_area_limited_item_does_not_count_as_saved_after_exit(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_015")], [("0,0", "1,0")],
        )
        result = RoutePlanner(game_map).plan(state(1, items=[
            {"instanceId": "spring", "componentId": "component_016", "remainingUses": 1},
        ]))
        for route in result["routes"]:
            self.assertEqual(route["metrics"]["survivingProcessingItems"], 0)
            self.assertEqual(route["remainingItems"][0]["remainingUses"], 0)

    def test_current_node_must_be_explicitly_completed(self) -> None:
        game_map = make_map([(0, 0, "start")], [])
        planner = RoutePlanner(game_map)
        with self.assertRaisesRegex(ValueError, "completedNodes are required"):
            planner.plan({"position": "0,0", "actionPoints": 1})
        with self.assertRaisesRegex(ValueError, "current position must be"):
            planner.plan(state(1, completedNodes=[]))

    def test_portal_pair_must_reference_distinct_portal_nodes(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_014"), (2, 0, "node_type_014")],
            [("0,0", "1,0")],
        )
        planner = RoutePlanner(game_map)
        with self.assertRaisesRegex(ValueError, "distinct"):
            planner.plan(state(1, portalPairs=[["1,0", "1,0"]]))
        with self.assertRaisesRegex(ValueError, "portal nodes"):
            planner.plan(state(1, portalPairs=[["0,0", "1,0"]]))
        with self.assertRaisesRegex(ValueError, "cover every"):
            planner.plan(state(1, portalPairs=[]))

    def test_random_item_does_not_claim_a_guaranteed_path(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (3, 2, "node_type_015")], [],
        )
        result = RoutePlanner(game_map).plan(state(1, items=[
            {"instanceId": "random", "componentId": "component_019", "remainingUses": 1},
        ]))
        self.assertEqual(result["routes"], [])
        self.assertTrue(any("random" in warning for warning in result["warnings"]))
        self.assertEqual(result["randomMovement"]["excludedItemInstanceIds"], ["random"])
        self.assertEqual(result["randomMovement"]["status"], "not_implemented")

    def test_completed_combat_node_is_noncombat_item_target(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "node_type_003")],
            [("1,0", "2,0")],
        )
        item = {"instanceId": "melt", "componentId": "component_021", "remainingUses": 1}
        planner = RoutePlanner(game_map)
        self.assertEqual(planner.plan(state(2, items=[item]))["routes"], [])
        result = planner.plan(state(2, completedNodes=["0,0", "1,0"], items=[item]))
        self.assertEqual(result["routes"][0]["endNode"], "2,0")
        self.assertEqual(result["routes"][0]["steps"][0]["itemInstanceId"], "melt")

    def test_state_limit_never_claims_full_optimality(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "node_type_015")],
            [("0,0", "1,0"), ("1,0", "2,0")],
        )
        result = RoutePlanner(game_map).plan(state(2, maxStates=1))
        self.assertFalse(result["searchComplete"])
        self.assertLessEqual(result["generatedStates"], 1)

    def test_blind_zone_returns_only_one_movement_even_with_ap_gain(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_006"), (2, 0, "node_type_015")],
            [("0,0", "1,0"), ("1,0", "2,0")],
        )
        inputs = state(8, utopiaId="utopia_005", items=[
            {"instanceId": "order", "componentId": "component_024", "remainingUses": 1},
        ])
        result = RoutePlanner(game_map).plan(inputs)
        self.assertEqual(inputs["actionPoints"], 8)
        self.assertEqual(result["mode"], "single_step")
        self.assertEqual(result["planningPolicy"]["planningActionPoints"], 1)
        self.assertTrue(result["planningPolicy"]["replanAfterMovement"])
        self.assertTrue(result["routes"])
        for route in result["routes"]:
            self.assertEqual(len(route["steps"]), 1)
            self.assertEqual(route["goalType"], "rolling_step")
            self.assertEqual(route["endNode"], "1,0")
            step = route["steps"][0]
            self.assertEqual(step["actualActionPointsBefore"], 8)
            self.assertEqual(route["remainingActionPoints"], 8 - step["actionCost"] + step["actionGain"])

    def test_blind_zone_does_not_fabricate_ap_or_pursuit(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_006")], [("0,0", "1,0")])
        result = RoutePlanner(game_map).plan(state(0, utopiaId="utopia_005", pursuit=True))
        self.assertEqual(result["planningPolicy"]["planningActionPoints"], 0)
        self.assertEqual(result["routes"], [])

    def test_resident_overrides_reward_without_rewriting_node_category(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "unknown_mystery")], [])
        game_map["nodes"][1]["confirmedMarkIds"] = ["node_mark_001"]
        planner = RoutePlanner(game_map)
        self.assertEqual(planner.nodes[1].category, "unknown_mystery")
        self.assertEqual(planner.nodes[1].effective_category, "node_type_021")
        game_map["edges"] = [["0,0", "1,0"]]
        route = RoutePlanner(game_map).plan(state(1, pursuit=True))["routes"][0]
        step = route["steps"][0]
        self.assertEqual(step["nodeValue"], 1.0)
        effect = step["nodeEffects"][0]
        self.assertTrue(effect["residentBattle"])
        self.assertTrue(effect["baseRewardSuppressed"])
        self.assertEqual(effect["effectiveCategoryId"], "node_type_021")

    def test_resident_stacks_with_lookout_and_fruit_only_once(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_018")], [("0,0", "1,0")])
        game_map["nodes"][1]["confirmedMarkIds"] = ["node_mark_001", "node_mark_007"]
        route = RoutePlanner(game_map).plan(state(2, pursuit=True))["routes"][0]
        self.assertEqual([step["actionGain"] for step in route["steps"]], [1, 0, 0])
        effect = route["steps"][0]["nodeEffects"][0]
        self.assertFalse(effect["baseRewardSuppressed"])
        self.assertTrue(effect["lookoutPreserved"])
        self.assertTrue(effect["fruitRewardAvailable"])
        revisit = route["steps"][-1]["nodeEffects"][0]
        self.assertFalse(revisit["residentBattle"])
        self.assertFalse(revisit["fruitRewardAvailable"])
        self.assertEqual(revisit["effectiveCategoryId"], "node_type_020")

    def test_fixed_identity_marks_do_not_add_a_second_node_reward(self) -> None:
        for mark, category in (("node_mark_002", "node_type_006"), ("node_mark_003", "node_type_012"),
                               ("node_mark_004", "node_type_001"), ("node_mark_005", "node_type_006"),
                               ("node_mark_006", "node_type_008")):
            with self.subTest(mark=mark):
                game_map = make_map([(0, 0, "start"), (1, 0, category)], [("0,0", "1,0")])
                baseline = RoutePlanner(game_map).plan(state(1, pursuit=True))["routes"][0]
                game_map["nodes"][1]["confirmedMarkIds"] = [mark]
                marked = RoutePlanner(game_map).plan(state(1, pursuit=True))["routes"][0]
                self.assertEqual(marked["steps"][0]["weightedValue"], baseline["steps"][0]["weightedValue"])
                effect = marked["steps"][0]["nodeEffects"][0]
                self.assertEqual(effect["effectiveCategoryId"], category)
                self.assertFalse(effect["residentBattle"])
                self.assertFalse(effect["fruitRewardAvailable"])

    def test_resident_can_override_fixed_event_while_fruit_still_stacks(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_006")], [("0,0", "1,0")])
        marks = ["node_mark_001", "node_mark_005", "node_mark_007"]
        game_map["nodes"][1]["confirmedMarkIds"] = marks
        planner = RoutePlanner(game_map)
        self.assertEqual(planner.nodes[1].category, "node_type_006")
        self.assertEqual(planner.nodes[1].effective_category, "node_type_021")
        route = planner.plan(state(1, pursuit=True))["routes"][0]
        effect = route["steps"][0]["nodeEffects"][0]
        self.assertTrue(effect["residentBattle"])
        self.assertTrue(effect["baseRewardSuppressed"])
        self.assertTrue(effect["fruitRewardAvailable"])
        self.assertEqual(route["steps"][0]["nodeValue"], 1.0)
        self.assertEqual(game_map["nodes"][1]["confirmedMarkIds"], marks)

    def test_resident_on_repeatable_node_requires_correction(self) -> None:
        for category in ("node_type_004", "node_type_013", "node_type_014",
                         "node_type_015", "node_type_016", "node_type_012"):
            game_map = make_map([(0, 0, category)], [])
            game_map["nodes"][0]["confirmedMarkIds"] = ["node_mark_001"]
            with self.assertRaisesRegex(ValueError, "resident mark cannot occupy"):
                RoutePlanner(game_map)

    def test_emergency_aid_cannot_be_reentered(self) -> None:
        game_map = make_map([(0, 0, "node_type_017")], [])
        result = RoutePlanner(game_map).plan(state(2, pursuit=True))
        self.assertEqual(result["routes"], [])

    def test_item_priority_prefers_less_scope_then_expiry_and_context_uses(self) -> None:
        wheel, exoskeleton = MOVEMENT_RULES["component_013"], MOVEMENT_RULES["component_017"]
        self.assertLess(item_preference(wheel, 1, 8, 4), item_preference(exoskeleton, 3, 12, 4))
        melt, principle = MOVEMENT_RULES["component_021"], MOVEMENT_RULES["component_023"]
        self.assertLess(item_preference(melt, 1, 10, 4), item_preference(principle, 3, 10, 4))
        spring, engine = MOVEMENT_RULES["component_016"], MOVEMENT_RULES["component_015"]
        self.assertLess(item_preference(spring, 1, 8, 4), item_preference(engine, 3, 8, 4))
        self.assertLess(item_preference(engine, 3, 8, 4), item_preference(engine, 1, 8, 4))
        self.assertLess(item_preference(engine, 1, 8, 1), item_preference(engine, 3, 8, 1))

    def test_equivalent_item_identities_do_not_multiply_states_or_routes(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 1, "node_type_006"), (2, 1, "node_type_015")],
                            [("1,1", "2,1")])
        items = [{"instanceId": f"engine-{i}", "componentId": "component_015", "remainingUses": 3}
                 for i in range(10)]
        result = RoutePlanner(game_map).plan(state(2, items=items))
        self.assertGreater(result["searchDiagnostics"]["equivalentItemActionsSkipped"], 0)
        self.assertIn([item["instanceId"] for item in items], result["searchDiagnostics"]["itemEquivalenceGroups"])
        paths = [tuple((step["entered"], step["arrived"]) for step in route["steps"]) for route in result["routes"]]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(result["searchComplete"])

    def test_same_geometry_with_different_ap_or_resource_effects_is_not_merged(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_006")], [("0,0", "1,0")])
        items = [{"instanceId": "engine", "componentId": "component_015", "remainingUses": 1},
                 {"instanceId": "control", "componentId": "component_024", "remainingUses": 1},
                 {"instanceId": "melt", "componentId": "component_021", "remainingUses": 1},
                 {"instanceId": "principle", "componentId": "component_023", "remainingUses": 1}]
        result = RoutePlanner(game_map).plan(state(1, utopiaId="utopia_005", items=items))
        self.assertEqual(len(result["searchDiagnostics"]["itemEquivalenceGroups"]), 4)

    def test_valuation_and_exclusion_prevent_inventory_equivalence(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_015")], [("0,0", "1,0")])
        items = [{"instanceId": "a", "componentId": "component_015", "remainingUses": 1, "estimatedValue": 2},
                 {"instanceId": "b", "componentId": "component_015", "remainingUses": 1, "estimatedValue": 3},
                 {"instanceId": "c", "componentId": "component_015", "remainingUses": 1, "estimatedValue": 2}]
        result = RoutePlanner(game_map).plan(state(1, items=items, excludeItemIds=["c"]))
        self.assertEqual(len(result["searchDiagnostics"]["itemEquivalenceGroups"]), 3)

    def test_inventory_symmetry_preserves_best_score_against_small_exhaustive_reference(self) -> None:
        class UnmergedPlanner(RoutePlanner):
            @staticmethod
            def _item_groups(items: tuple) -> tuple:
                return tuple((index,) for index in range(len(items)))

        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_006"), (0, 1, "node_type_007"), (1, 1, "node_type_015")],
            [("0,0", "1,0"), ("0,0", "0,1"), ("1,0", "1,1"), ("0,1", "1,1")],
        )
        inputs = state(3, items=[
            {"instanceId": "a", "componentId": "component_014", "remainingUses": 1},
            {"instanceId": "b", "componentId": "component_015", "remainingUses": 3},
            {"instanceId": "c", "componentId": "component_015", "remainingUses": 3},
        ])
        merged, reference = RoutePlanner(game_map).plan(inputs), UnmergedPlanner(game_map).plan(inputs)
        self.assertTrue(merged["searchComplete"] and reference["searchComplete"])
        self.assertEqual(merged["routes"][0]["metrics"], reference["routes"][0]["metrics"])
        self.assertLess(merged["generatedStates"], reference["generatedStates"])

    def test_budget_still_evaluates_generated_terminal_frontier(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_015"), (0, 1, "node_type_015")],
                            [("0,0", "1,0"), ("0,0", "0,1")])
        result = RoutePlanner(game_map).plan(state(1, maxStates=2))
        self.assertFalse(result["searchComplete"])
        self.assertEqual(result["generatedStates"], 2)
        self.assertEqual(result["routes"][0]["endNode"], "1,0")
        self.assertGreater(result["searchDiagnostics"]["terminalFrontierEvaluated"], 0)

    def test_danger_path_stops_the_route_on_arrival(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_016"), (2, 0, "node_type_006")],
            [("0,0", "1,0"), ("1,0", "2,0")],
        )
        route = RoutePlanner(game_map).plan(state(3))["routes"][0]
        self.assertEqual(route["endNode"], "1,0")
        self.assertEqual(len(route["steps"]), 1)
        self.assertEqual(route["remainingActionPoints"], 2)

    def test_queue_and_route_ranking_do_not_reward_exit_distance_or_remaining_ap(self) -> None:
        game_map = make_map(
            [(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "node_type_015")],
            [("0,0", "1,0"), ("1,0", "2,0")],
        )
        planner = RoutePlanner(game_map)
        metrics = (20, 1, 0, 0, 2, 3)
        self.assertEqual(planner._queue_priority(metrics, 1, 1, 4),
                         planner._queue_priority(metrics, 20, 10, 4))
        lower, higher = planner.plan(state(2)), planner.plan(state(3))
        self.assertEqual(lower["routes"][0]["metrics"], higher["routes"][0]["metrics"])
        self.assertEqual(lower["routes"][0]["remainingActionPoints"], 0)
        self.assertEqual(higher["routes"][0]["remainingActionPoints"], 1)
        self.assertNotIn("actionPoints", higher["searchDiagnostics"]["queueOrder"])

    def test_optional_expansion_observer_receives_parent_chain(self) -> None:
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_015")], [("0,0", "1,0")])
        records = []
        result = RoutePlanner(game_map).plan(state(1), on_expand=records.append)
        self.assertEqual(len(records), result["expandedStates"])
        self.assertIsNone(records[0]["parentLabelId"])
        self.assertEqual(records[1]["parentLabelId"], records[0]["labelId"])
        self.assertEqual(records[1]["step"]["arrived"], "1,0")


if __name__ == "__main__":
    unittest.main()
