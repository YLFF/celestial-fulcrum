from __future__ import annotations

from copy import deepcopy
import unittest

from fulcrum.component_box import add_component
from fulcrum.map_catalog import TemplateCatalog
from fulcrum.node_scoring import SnapshotScorer
from fulcrum.operators import add_operator
from fulcrum.playtime_route import route_inputs
from fulcrum.playtime_state import merge_map_observation, new_playtime
from fulcrum.route_planner import RoutePlanner, _State
from tests.test_route_planner import make_map, state
from scripts.export_encounter_weights import convert


def context(area="III", *, options=None):
    playtime = new_playtime("utility-test")
    playtime["resources"].update(level=4, hope=30, originiumIngot=10, life={"current": 12, "max": 12})
    playtime["operators"] = [{"instanceId": f"test-{i}", "name": f"test-{i}", "source": "normal",
        "rarity": 6 if i < 9 else 3, "elite": 2 if i < 7 else 1, "remainingBattles": None} for i in range(13)]
    return {**playtime, "areaKey": area, "options": {**(options or {})}}


class SnapshotScoringTests(unittest.TestCase):
    def test_category_and_event_coverage_is_finite_not_fabricated(self):
        nodes = [{"id": "s", "categoryId": "start"}] + [
            {"id": str(i), "categoryId": f"node_type_{i:03}"} for i in range(1, 22)]
        scorer = SnapshotScorer(nodes, context(), state(6, completedNodes=["s"]))
        self.assertEqual(len(scorer.values), 22)
        self.assertEqual(scorer.values["20"]["points"], 0)
        self.assertEqual(scorer.values["18"]["points"], 0)  # Deterministic AP changes are handled by movement.
        for i in range(1, 24):
            value = scorer.encounter(f"encounter_{i:03}")
            self.assertIsInstance(value["points"], (int, float))
        self.assertEqual(scorer.encounter("encounter_010")["parts"]["hopefulSoil"], 600)

    def test_normalized_type_weights_leave_prediction_untouched(self):
        c = context()
        c["prediction"] = {"unknownNodes": {"1,0": {"candidates": [
            {"categoryId": "node_type_001", "distanceFrequency": .2},
            {"categoryId": "node_type_002", "distanceFrequency": .3}]}}}
        before = deepcopy(c)
        scorer = SnapshotScorer([{ "id": "1,0", "categoryId": "unknown_ferocity"}], c, state(2))
        probabilities = scorer.values["1,0"]["classification"]["probabilities"]
        self.assertAlmostEqual(probabilities["node_type_001"], .4)
        self.assertAlmostEqual(sum(probabilities.values()), 1)
        self.assertEqual(c, before)

    def test_zero_frequency_and_missing_treehole_rules_are_explicit(self):
        for area in ("III", "III-treehole"):
            scorer = SnapshotScorer([{"id": "a", "categoryId": "unknown_mystery"}], context(area), state(1))
            self.assertTrue(scorer.values["a"]["missingTerms"])
            self.assertEqual(scorer.values["a"]["points"], 0)

    def test_treehole_temporary_prior(self):
        scorer = SnapshotScorer([{"id": "a", "categoryId": "unknown_ferocity"},
            {"id": "b", "categoryId": "unknown_mystery"}],
            context("III-treehole", options={"treeholeMysteryCandidates": ["wish", "encounter"]}), state(1))
        self.assertEqual(scorer.probabilities(scorer.nodes["a"])["probabilities"],
                         {"node_type_001": 2 / 3, "node_type_002": 1 / 3})
        self.assertEqual(scorer.probabilities(scorer.nodes["b"])["probabilities"],
                         {"node_type_007": .5, "node_type_006": .5})

    def test_event_exclusion_renormalizes_remaining_weights(self):
        c = context()
        c["prediction"] = {"encounterPool": {"candidates": [{"id": "encounter_005"}, {"id": "encounter_014"}]}}
        scorer = SnapshotScorer([{"id": "a", "categoryId": "node_type_006"}], c, state(2))
        rows = scorer.event_distribution["events"]
        self.assertEqual({row["eventId"] for row in rows}, {"encounter_005", "encounter_014"})
        self.assertAlmostEqual(sum(row["probability"] for row in rows), 1)
        c["prediction"]["encounterPool"]["candidates"].pop()
        scorer2 = SnapshotScorer([{"id": "a", "categoryId": "node_type_006"}], c, state(2))
        self.assertEqual(scorer2.event_distribution["events"][0]["probability"], 1)

    def test_heavy_ticket_weight_tracks_current_mechanist(self):
        c = context()
        c["recruitmentTickets"] = ["重装招募券", "重装招募券", "重装招募券"]
        nodes = [{"id": "e", "categoryId": "node_type_015"}]
        a = SnapshotScorer(nodes, c, state(1))
        self.assertEqual(a.ticket_total, 350)
        c["operators"].append({"instanceId": "mechanist", "name": "机械师", "source": "normal", "elite": 2, "rarity": 6, "remainingBattles": None})
        b = SnapshotScorer(nodes, c, state(1))
        self.assertEqual(b.ticket_total, 150)

    def test_action_rewards_never_extend_executable_budget(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_006"), (2, 0, "node_type_001"), (3, 0, "node_type_001")],
                     [("0,0", "1,0"), ("1,0", "2,0"), ("2,0", "3,0")])
        m["nodes"][1]["encounterId"] = "encounter_004"
        c = context(options={"nodeScores": {"2,0": 1000}})
        result = RoutePlanner(m).plan(state(1, pursuit=True, scoringContext=c))
        self.assertTrue(result["routes"])
        for route in result["routes"]:
            self.assertEqual(len(route["steps"]), 1)
            self.assertEqual(route["remainingActionPoints"], 0)
        self.assertGreater(result["scoring"]["nodeValues"]["1,0"]["points"], 0)

    def test_exit_hope_has_baseline_when_threshold_is_met(self):
        scorer = SnapshotScorer([{"id": "e", "categoryId": "node_type_015"}], context("I"), state(3))
        self.assertTrue(scorer.threshold["met"])
        row = scorer.terminal("e", 2, pursuit=False)
        self.assertEqual(row["parts"]["remainingHope"], 20)
        self.assertEqual(row["convertedHope"], 2)
        self.assertNotIn("remainingHope", scorer.terminal("e", 0, pursuit=True)["parts"])

    def test_exit_hope_need_bonus_replaces_baseline_for_needed_portion(self):
        c = context("II", options={"teamThresholdOverride": "insufficient",
                                   "hopeDeficit": 2})
        scorer = SnapshotScorer([{"id": "e", "categoryId": "node_type_015"}], c, state(4))
        self.assertEqual(scorer.terminal("e", 3, pursuit=False)["parts"]["remainingHope"], 110)
        c["options"]["exitHopePointFloor"] = 0
        scorer = SnapshotScorer([{"id": "e", "categoryId": "node_type_015"}], c, state(4))
        self.assertEqual(scorer.terminal("e", 3, pursuit=False)["parts"]["remainingHope"], 100)
        c["options"]["exitHopePointFloor"] = -1
        with self.assertRaises(ValueError):
            SnapshotScorer([{"id": "e", "categoryId": "node_type_015"}], c, state(4))

    def test_normal_routes_skip_empty_end_reentry_but_allow_transit(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_015"), (2, 0, "node_type_001")],
                     [("0,0", "1,0"), ("1,0", "2,0")])
        s = state(3, topN=20, scoringContext=context("I"))
        result = RoutePlanner(m).plan(s)
        reference = RoutePlanner(m).plan({**s, "searchMode": "reference"})
        self.assertEqual([r["metrics"]["weightedValue"] for r in result["routes"]],
                         [r["metrics"]["weightedValue"] for r in reference["routes"]])
        self.assertGreater(result["searchDiagnostics"]["noEffectEndReentriesSkipped"], 0)
        self.assertTrue(any([step["arrived"] for step in r["steps"]] == ["1,0", "2,0", "1,0"]
                            for r in result["routes"]))
        self.assertFalse(any(step["from"] == step["arrived"] == "1,0"
                             for r in result["routes"] for step in r["steps"]))

    def test_pursuit_can_reenter_end_to_exhaust_ap(self):
        m = make_map([(0, 0, "node_type_015")], [])
        result = RoutePlanner(m).plan(state(3, pursuit=True, topN=20, scoringContext=context("I")))
        self.assertTrue(any([step["arrived"] for step in r["steps"]] == ["0,0"] * 3
                            for r in result["routes"]))
        self.assertEqual(result["searchDiagnostics"]["noEffectEndReentriesSkipped"], 0)

    def test_merchant_score_uses_net_prefix_cash_and_move_proxy(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "node_type_013"), (3, 0, "node_type_015")],
                     [("0,0", "1,0"), ("1,0", "2,0"), ("2,0", "3,0")])
        c = context()
        before = deepcopy(c)
        result = RoutePlanner(m).plan(state(3, scoringContext=c))
        route = result["routes"][0]
        combat_cash = result["scoring"]["nodeValues"]["1,0"]["expectedCashDelta"]
        shop = route["steps"][1]["scoreBreakdown"]["nodeTerms"][0]["merchant"]
        self.assertAlmostEqual(shop["economyInput"], 10 + combat_cash + 2 + 4)
        self.assertEqual(c, before)
        self.assertTrue(result["searchComplete"])
        self.assertAlmostEqual(route["metrics"]["weightedValue"], sum(s["weightedValue"] for s in route["steps"])
                               + round(route["terminalScore"]["points"] * 20) / 20)

    def test_unknown_merchant_contribution_is_repriced_without_claiming_identity(self):
        c = context()
        c["prediction"] = {"unknownNodes": {"a": {"candidates": [
            {"categoryId": "node_type_013", "distanceFrequency": .4},
            {"categoryId": "node_type_007", "distanceFrequency": .4}]}}}
        scorer = SnapshotScorer([{"id": "a", "categoryId": "unknown_mystery"}], c, state(2))
        score = scorer.step(["a"], {"a"}, [], before_done=set(), prefix_cash=20,
                            appraisal=4, path_steps=2, processing=False)
        term = score["nodeTerms"][0]
        self.assertGreater(term["parts"]["merchantPrefixAdjustment"], 0)
        self.assertEqual(term["merchantTypes"][0]["probability"], .5)
        self.assertEqual(scorer.nodes["a"]["categoryId"], "unknown_mystery")

    def test_item_cash_and_exhaustion_are_settled_before_shop_scoring(self):
        m = make_map([(0, 0, "start"), (5, 0, "node_type_013")], [])
        c = context()
        item = add_component(c["componentBox"], "component_022", estimated_value=10, remaining_uses=1)
        s = state(1, pursuit=True, scoringContext=c, items=[{
            "instanceId": item["instanceId"], "componentId": "component_022", "remainingUses": 1, "estimatedValue": 10}])
        route = RoutePlanner(m).plan(s)["routes"][0]
        shop = route["steps"][0]["scoreBreakdown"]["nodeTerms"][0]["merchant"]
        self.assertEqual(shop["economyInput"], 10 + 4 + 1 + 4)
        self.assertEqual(shop["points"], 570)
        self.assertEqual(route["expectedPrefixEconomy"]["cash"], 0)
        self.assertEqual(route["expectedPrefixEconomy"]["appraisal"], 0)

    def test_repeated_merchant_defaults_to_four_remaining_shelves(self):
        nodes = [{"id": "shop", "categoryId": "node_type_013"}]
        scorer = SnapshotScorer(nodes, context(), state(2, completedNodes=["shop"]))
        row = scorer.step(["shop"], set(), [], before_done={"shop"}, prefix_cash=10,
                          appraisal=4, path_steps=1, processing=False)
        self.assertEqual(row["nodeValue"], (10 + 4 + 1) * 30 * .8)

    def test_processing_painted_reward_not_pruned_as_walking_equivalent(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_007"), (2, 0, "node_type_015")],
                     [("0,0", "1,0"), ("1,0", "2,0")])
        c = context()
        add_component(c["componentBox"], "component_029", estimated_value=1)
        item = add_component(c["componentBox"], "component_013", estimated_value=2)
        s = state(2, scoringContext=c, items=[{"instanceId": item["instanceId"], "componentId": "component_013", "remainingUses": 1}])
        result = RoutePlanner(m).plan(s)
        self.assertEqual(result["routes"][0]["steps"][0]["movement"], "item")
        self.assertEqual(result["routes"][0]["steps"][0]["scoreBreakdown"]["nodeTerms"][0]["parts"]["paintedBonus"], 100)
        self.assertFalse(result["searchDiagnostics"]["inventoryDominanceEnabled"])

    def test_first_reveal_only_no_visit_reveal_duplication(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "unknown_mystery"),
                      (1, 1, "node_type_015")], [("0,0", "1,0"), ("1,0", "2,0"), ("1,0", "1,1")], {"2,0"})
        c = context(options={"nodeScores": {"2,0": 500}})
        result = RoutePlanner(m).plan(state(4, scoringContext=c))
        for route in result["routes"]:
            terms = [term for step in route["steps"] for term in step["scoreBreakdown"]["revealTerms"]]
            self.assertEqual(len(terms), 1)
            self.assertEqual(terms[0]["points"], 100)

    def test_visible_clearing_does_not_gain_reveal_reward(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_020"), (2, 0, "unknown_mystery"),
                      (1, 1, "node_type_015")], [("0,0", "1,0"), ("1,0", "2,0"), ("1,0", "1,1")], {"2,0"})
        c = context(options={"nodeScores": {"2,0": 500}})
        planner = RoutePlanner(m)
        preview = planner.score_snapshot(state(4, scoringContext=c))
        self.assertEqual(preview["nodeValues"]["1,0"]["revealValue"], 0)
        for mode in ("target", "reference"):
            result = planner.plan(state(4, scoringContext=c, searchMode=mode))
            self.assertTrue(result["searchComplete"])
            for route in result["routes"]:
                self.assertFalse([term for step in route["steps"] for term in step["scoreBreakdown"]["revealTerms"]])

    def test_prefix_economy_and_move_order_are_state_dimensions(self):
        a = _State(0, 2, 7, 7, 0, (), 10, 20, 4, 2)
        b = _State(0, 2, 7, 7, 0, (), 30, 30, 4, 2)
        self.assertNotEqual(RoutePlanner._state_key(a, ()), RoutePlanner._state_key(b, ()))
        c = _State(0, 2, 7, 7, 0, (), 100, 20, 4, 2)
        self.assertEqual(RoutePlanner._state_key(a, ()), RoutePlanner._state_key(c, ()))

    def test_target_and_reference_agree_on_exhaustible_case(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_001"), (0, 1, "node_type_013"),
                      (1, 1, "node_type_015")], [("0,0", "1,0"), ("0,0", "0,1"), ("1,0", "1,1"), ("0,1", "1,1"), ("1,0", "0,1")])
        s = state(4, scoringContext=context(), topN=10)
        optimized = RoutePlanner(m).plan(s)
        reference = RoutePlanner(m).plan({**s, "searchMode": "reference"})
        self.assertTrue(optimized["searchComplete"])
        self.assertTrue(reference["searchComplete"])
        self.assertEqual(optimized["routes"][0]["metrics"]["weightedValue"], reference["routes"][0]["metrics"]["weightedValue"])
        # Independent DFS of every walking sequence, without planner labels or pruning.
        scorer = SnapshotScorer(m["nodes"], s["scoringContext"], s)
        adjacent = {node["id"]: [] for node in m["nodes"]}
        for a, b in m["edges"]:
            adjacent[a].append(b)
            adjacent[b].append(a)
        exhaustive_values = []
        def dfs(position, ap, done, cash, appraisal, moves, bank, shelves, units):
            if position == "1,1":
                terminal = scorer.terminal(position, ap, pursuit=False)["points"]
                exhaustive_values.append((units + round(terminal * 20)) / 20)
            if not ap:
                return
            targets = adjacent[position] + ([position] if position == "0,1" else [])
            for target in targets:
                row = scorer.step([target], {target} - done, [], before_done=done,
                                  prefix_cash=cash, appraisal=appraisal, path_steps=moves + 1, processing=False,
                                  investment_balance=bank, merchant_shelves=shelves)
                score = row["nodeValue"] + row["revealValue"] + row["recruitmentValue"]
                transition = row["merchantTransition"]
                dfs(target, ap - 1, done | {target}, round(transition["cashAfter"], 6),
                    round(transition["appraisalAfter"], 6), round(transition["movementProxyStepsAfter"], 6),
                    round(transition["investmentBalanceAfter"], 6), transition["viewedShelvesAfter"], units + round(score * 20))
        dfs("0,0", 4, {"0,0"}, 10, 4, 0, 99, dict(scorer.merchant_shelves), 0)
        self.assertEqual(optimized["routes"][0]["metrics"]["weightedValue"], max(exhaustive_values))

    def test_search_budget_is_explicit_and_keeps_generated_exits(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_015"), (0, 1, "node_type_001")],
                     [("0,0", "1,0"), ("0,0", "0,1")])
        result = RoutePlanner(m).plan(state(4, scoringContext=context(), maxStates=2))
        self.assertFalse(result["searchComplete"])
        self.assertTrue(result["routes"])

    def test_saved_playtime_adapter_is_read_only_and_defaults_to_new_scoring(self):
        p = new_playtime("adapter")
        template = TemplateCatalog().candidates("main", 1)[0]
        observed = {"success": True, "area": "main", "floor": 1, "templateId": template.id,
            "nodes": [{"id": template.coord(slot).key, "coord": [template.coord(slot).x, template.coord(slot).y],
                       "slot": list(slot), "categoryId": "start" if slot == template.start_slot else
                       "node_type_015" if slot in template.terminal_slots else "node_type_001",
                       "visibility": "revealed", "marks": []} for slot in template.occupied_slots],
            "edges": [[template.coord(a).key, template.coord(b).key] for a, b in template.edges],
            "playerPositionObservation": {"status": "recognized", "nodeId": "0,0"}}
        instance = merge_map_observation(p, "I", observed)
        instance["actionPoints"] = 6
        before = deepcopy(p)
        m, s = route_inputs(p)
        result = RoutePlanner(m).plan(s)
        self.assertTrue(result["searchComplete"])
        self.assertEqual(result["schemaVersion"], 3)
        self.assertEqual(p, before)
        _, legacy = route_inputs(p, scoring_mode="legacy")
        self.assertNotIn("scoringContext", legacy)

    def test_per_search_items_do_not_change_inventory_or_global_exclusions(self):
        p = new_playtime("per-search-items")
        template = TemplateCatalog().candidates("main", 1)[0]
        observed = {"success": True, "area": "main", "floor": 1, "templateId": template.id,
            "nodes": [{"id": template.coord(slot).key, "coord": [template.coord(slot).x, template.coord(slot).y],
                       "slot": list(slot), "categoryId": "node_type_020", "visibility": "revealed", "marks": []}
                      for slot in template.occupied_slots],
            "edges": [[template.coord(a).key, template.coord(b).key] for a, b in template.edges],
            "playerPositionObservation": {"status": "recognized", "nodeId": "0,0"}}
        instance = merge_map_observation(p, "I", observed)
        instance["actionPoints"] = 2
        p["componentBox"]["items"] = [
            {"instanceId": id, "componentId": component, "remainingUses": 1, "estimatedValue": 8, "routeCandidate": False}
            for id, component in (("engine", "component_014"), ("pig", "component_019"))]
        before = deepcopy(p)
        _, selected = route_inputs(p, use_item_ids=["engine"])
        self.assertEqual(selected["useItemIds"], ["engine"])
        self.assertEqual({item["instanceId"] for item in selected["items"]}, {"engine", "pig"})
        _, legacy = route_inputs(p, scoring_mode="legacy", use_item_ids=["engine"])
        self.assertEqual([item["instanceId"] for item in legacy["items"]], ["engine"])
        _, walking = route_inputs(p, use_item_ids=[])
        self.assertEqual(walking["useItemIds"], [])
        for ids in (["pig"], ["missing"], ["engine", "engine"]):
            with self.assertRaises(ValueError):
                route_inputs(p, use_item_ids=ids)
        self.assertEqual(p, before)

    def test_initial_operator_rarity_and_invalid_input_are_validated(self):
        p = new_playtime("rarity", initial_operators=[{"name": "测试", "rarity": 6}])
        self.assertEqual(p["operators"][0]["rarity"], 6)
        before = deepcopy(p)
        with self.assertRaises(ValueError):
            add_operator(p, "无效", rarity=7)
        self.assertEqual(p, before)

    def test_blind_zone_estimation_uses_one_ap_without_rewriting_observed_ap(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_006"), (2, 0, "node_type_007")],
                     [("0,0", "1,0"), ("1,0", "2,0")])
        m["nodes"][1]["encounterId"] = "encounter_004"
        result = RoutePlanner(m).plan(state(10, scoringContext=context("III-treehole"), utopiaId="utopia_005"))
        self.assertEqual(result["planningPolicy"]["observedActionPoints"], 10)
        self.assertEqual(result["planningPolicy"]["planningActionPoints"], 1)
        self.assertGreater(result["scoring"]["actionOpportunity"]["onePoint"], 0)
        self.assertEqual(len(result["routes"][0]["steps"]), 1)
        self.assertEqual(result["routes"][0]["remainingActionPoints"], 9)

    def test_path_carry_factor_removes_core_nodes_already_passed(self):
        nodes = [{"id": "p", "categoryId": "node_type_016"}] + [
            {"id": str(i), "categoryId": "node_type_006"} for i in range(5)]
        scorer = SnapshotScorer(nodes, context("IV"), state(2))
        before = scorer.terminal("p", 2, pursuit=False, done={"p"})
        after = scorer.terminal("p", 2, pursuit=False, done={"p", "0", "1", "2", "3", "4"})
        self.assertAlmostEqual(before["carryFactor"], .4)
        self.assertEqual(after["carryFactor"], 1)
        self.assertGreater(after["points"], before["points"])

    def test_vi_final_battle_has_no_rewards_or_missing_terms(self):
        scorer = SnapshotScorer([{"id": "b", "categoryId": "node_type_003"}], context("VI"), state(2))
        row = scorer.values["b"]
        self.assertEqual(row["points"], 0)
        self.assertEqual(row["expectedCashDelta"], 0)
        self.assertEqual(row["missingTerms"], [])
        self.assertEqual(scorer.terminal("b", 0, pursuit=True)["points"], 0)

    def test_red_moss_prices_cash_and_configured_soil(self):
        c = context()
        add_component(c["componentBox"], "component_012")
        scorer = SnapshotScorer([{"id": "s", "categoryId": "start"}], c, state(2))
        row = scorer.encounter("encounter_010")
        self.assertEqual(row["points"], 840)
        self.assertEqual(row["expectedCashDelta"], 30)
        self.assertFalse(row["missingTerms"])

    def test_agency_reference_is_not_a_chosen_home_profession_ticket(self):
        c = context()
        c["opening"]["squadId"] = "squad_005"
        scorer = SnapshotScorer([{"id": "s", "categoryId": "start"}], c, state(2))
        self.assertEqual(scorer.encounter("encounter_019")["points"], 100)

    def test_shop_raw_value_includes_current_mechanist_ticket_correction(self):
        scorer = SnapshotScorer([{"id": "s", "categoryId": "node_type_004"}], context(), state(2))
        value = scorer.shop("node_type_004", 50, 0, done={"s"}, repeated=True)
        self.assertAlmostEqual(value["rawPoints"] * value["repeatFactor"] + value["withdrawalPoints"], value["points"])

    def test_selector_export_preserves_ids_and_rejects_invalid_or_duplicate_weights(self):
        events = [{"id": "encounter_005", "name": "敲动杠杆"}]
        source = {"url": "test", "checked_at": "test", "json_responses": [{"floor_encounters": [{"events": [
            {"name": "敲动杠杆", "classification": "不期而遇", "sceneIds": ["lever_enter"]}]}]}],
            "encounter_weight_rows": [{"floor": 3, "treehole": False, "id": "lever", "weight": 2}]}
        result = convert(source, events)
        self.assertEqual(result["areas"]["III"]["encounter_005"]["weight"], 2)
        invalid = deepcopy(source)
        invalid["encounter_weight_rows"][0]["weight"] = -1
        with self.assertRaises(ValueError):
            convert(invalid, events)
        invalid = deepcopy(source)
        invalid["encounter_weight_rows"].append(dict(invalid["encounter_weight_rows"][0]))
        with self.assertRaises(ValueError):
            convert(invalid, events)


if __name__ == "__main__":
    unittest.main()
