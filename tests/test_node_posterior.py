"""Production beta, scoring integration, and special-area input boundaries."""

from copy import deepcopy
from pathlib import Path
from time import perf_counter
import unittest

from fulcrum.playtime_state import (
    active_instance, merge_map_observation, new_playtime, rebuild_derived, update_node,
)
from fulcrum.playtime_route import route_inputs
from fulcrum.route_planner import RoutePlanner, _Candidate, _candidate_rank
from fulcrum.service.updates import apply_commands
from fulcrum.dystopia import empty_dystopia
from tests.test_playtime_prediction import chain_map, treehole_map


class PosteriorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fulcrum.vision_pipeline import MapRecognizer
        observation = MapRecognizer().recognize(Path("samples/maps/bluestacks_floor_3.png")).to_dict()
        assert observation["success"]
        cls.state = new_playtime("beta-production-test")
        merge_map_observation(cls.state, "III", observation, player_position="0,0")
        active_instance(cls.state, "III")["actionPoints"] = 2

    def test_beta_probabilities_flow_to_scoring_without_mutating_input(self):
        state = deepcopy(self.state)
        before = deepcopy(state)
        started = perf_counter()
        rebuild_derived(state)
        self.assertLess(perf_counter() - started, 2)
        predicted = active_instance(state, "III")["prediction"]
        self.assertEqual(predicted["posteriorBeta"]["families"]["unknown_mystery"]["status"], "ok")
        self.assertEqual(predicted["posteriorBeta"]["families"]["unknown_ferocity"]["status"], "ok")
        map_result, inputs = route_inputs(state, planning_goal_ids=[])
        scores = RoutePlanner(map_result).score_snapshot(inputs)
        for key, row in predicted["unknownNodes"].items():
            self.assertAlmostEqual(sum(row["categoryProbabilities"].values()), 1)
            actual = scores["nodeValues"][key]["classification"]
            self.assertEqual(actual["basis"], "count_prior_beta_exact_dp")
            for category, probability in row["categoryProbabilities"].items():
                self.assertAlmostEqual(actual["probabilities"][category], probability)
        self.assertEqual(state, before)

    def test_confirmed_shop_changes_other_slots_and_remains_stable_on_reload(self):
        state = deepcopy(self.state)
        original = active_instance(state, "III")["prediction"]
        key = next(key for key, row in original["unknownNodes"].items()
                   if row["ordinaryProbabilities"].get("node_type_013", 0) > 0)
        update_node(state, "III", key, category_id="node_type_013")
        posterior = active_instance(state, "III")["prediction"]
        self.assertNotIn(key, posterior["unknownNodes"])
        for row in posterior["unknownNodes"].values():
            if row["unknownFamily"] == "unknown_mystery":
                self.assertAlmostEqual(row["ordinaryProbabilities"].get("node_type_013", 0), 0)
        before = deepcopy(state)
        rebuild_derived(state)
        self.assertEqual(state, before)

    def test_special_occupancy_is_preserved_once_and_conflicts_fall_back(self):
        state = deepcopy(self.state)
        state["goals"]["progress"]["ending3_beacon"] = {"status": "completed"}
        rebuild_derived(state)
        posterior = active_instance(state, "III")["prediction"]
        for row in posterior["unknownNodes"].values():
            self.assertAlmostEqual(sum(row["categoryProbabilities"].values()), 1)
            self.assertTrue(row["endingOccupancy"])
        conflict = deepcopy(state)
        node = next(iter(active_instance(conflict, "III")["nodes"].values()))
        node["needsCategoryReview"] = ["node_type_001", "node_type_002"]
        rebuild_derived(conflict)
        for family in active_instance(conflict, "III")["prediction"]["posteriorBeta"]["families"].values():
            self.assertEqual(family["status"], "fallback")

    def test_known_ending_encounter_does_not_disable_ordinary_beta(self):
        state = deepcopy(self.state)
        instance = active_instance(state, "III")
        key = next(key for key, row in instance["prediction"]["unknownNodes"].items()
                   if row["ordinaryProbabilities"].get("node_type_006", 0) > 0)
        update_node(state, "III", key, category_id="node_type_006")
        plain = deepcopy(instance["prediction"])
        instance["nodes"][key]["confirmedMarkIds"] = ["node_mark_005"]
        rebuild_derived(state)
        prediction = instance["prediction"]
        self.assertEqual(prediction["posteriorBeta"]["families"]["unknown_mystery"]["status"], "ok")
        for key, row in prediction["unknownNodes"].items():
            self.assertEqual(row["ordinaryProbabilities"], plain["unknownNodes"][key]["ordinaryProbabilities"])

    def test_trade_mark_uses_ordinary_posterior_without_forcing_generation(self):
        state = deepcopy(self.state)
        for goal in ("ending2_sandbox", "ending3_autopsy", "ending3_tribute"):
            state["goals"]["progress"][goal] = {"status": "completed"}
        rebuild_derived(state)
        instance = active_instance(state, "III")
        plain = deepcopy(instance["prediction"])
        state["goals"]["progress"]["ending3_beacon"] = {"status": "completed"}
        rebuild_derived(state)
        prediction = instance["prediction"]
        trade = prediction["endingPlacements"]["ending3_trade"]
        self.assertTrue(trade["eligible"])
        self.assertFalse(trade["guaranteedGeneration"])
        self.assertGreater(sum(trade["positionProbabilities"].values()), 0)
        self.assertLess(sum(trade["positionProbabilities"].values()), 1)
        for key, row in prediction["unknownNodes"].items():
            self.assertEqual(row["categoryProbabilities"], plain["unknownNodes"][key]["categoryProbabilities"])
            self.assertNotIn("ending3_trade", [item["goalId"] for item in row["endingOccupancy"]])
            self.assertLessEqual(trade["positionProbabilities"].get(key, 0), row["categoryProbabilities"].get("node_type_008", 0))
        self.assertEqual(instance["nodePool"]["gain-loss"], plain["nodePool"]["gain-loss"])
        _, inputs = route_inputs(state, planning_goal_ids=["ending3_trade"])
        scores = RoutePlanner(route_inputs(state, planning_goal_ids=[])[0]).score_snapshot(inputs)
        for key, row in prediction["unknownNodes"].items():
            for category, probability in row["categoryProbabilities"].items():
                self.assertAlmostEqual(scores["nodeValues"][key]["classification"]["probabilities"][category], probability)

    def test_all_unlocated_ending_marks_leave_category_probabilities_unchanged(self):
        state = deepcopy(self.state)
        for goal in ("ending2_sandbox", "ending3_autopsy", "ending3_tribute", "ending3_trade"):
            state["goals"]["progress"][goal] = {"status": "completed"}
        rebuild_derived(state)
        instance = active_instance(state, "III")
        plain = deepcopy(instance["prediction"])
        state["goals"]["progress"]["ending3_beacon"] = {"status": "completed"}
        for goal in ("ending2_sandbox", "ending3_autopsy", "ending3_tribute", "ending3_trade"):
            state["goals"]["progress"][goal] = {"status": "pending"}
        rebuild_derived(state)
        prediction = instance["prediction"]
        geometry, inputs = route_inputs(state, planning_goal_ids=list(prediction["endingPlacements"]))
        values = RoutePlanner(geometry).score_snapshot(inputs)["nodeValues"]
        for key, row in prediction["unknownNodes"].items():
            self.assertEqual(row["categoryProbabilities"], plain["unknownNodes"][key]["categoryProbabilities"])
            self.assertEqual(row["ordinaryProbabilities"], row["categoryProbabilities"])
            markers = row["endingOccupancy"] + row["conditionalEndingPlacements"]
            for category, probability in row["categoryProbabilities"].items():
                self.assertLessEqual(sum(mark["probability"] for mark in markers if mark["categoryId"] == category), probability + 1e-9)
                self.assertAlmostEqual(values[key]["classification"]["probabilities"][category], probability)
            if row["unknownFamily"] == "unknown_mystery":
                event = next((value["score"] for value in values[key]["types"] if value["categoryId"] == "node_type_006"), None)
                if event:
                    self.assertAlmostEqual(sum(value["probability"] for value in event["events"]), 1)


class LayerSettingsTests(unittest.TestCase):
    def test_utopia_requires_treehole_and_excludes_dystopia(self):
        state = new_playtime("regions")
        merge_map_observation(state, "III", chain_map(3))
        with self.assertRaisesRegex(ValueError, "树洞"):
            apply_commands(state, [{"type": "utopia", "areaKey": "III", "value": "utopia_005"}])
        merge_map_observation(state, "III-treehole", treehole_map(3))
        apply_commands(state, [{"type": "utopia", "areaKey": "III-treehole", "value": "utopia_005"}])
        value = {**empty_dystopia(), "active": True, "ideologyId": "dystopia_001"}
        with self.assertRaisesRegex(ValueError, "同时"):
            apply_commands(deepcopy(state), [{"type": "dystopia", "areaKey": "III-treehole", "value": value}])
        apply_commands(state, [{"type": "utopia", "areaKey": "III-treehole", "value": None},
                               {"type": "dystopia", "areaKey": "III-treehole", "value": value}])
        self.assertTrue(active_instance(state, "III-treehole")["dystopia"]["active"])

    def test_reserve_is_a_nonnegative_integer(self):
        state = new_playtime("reserve")
        merge_map_observation(state, "III", chain_map(3))
        for invalid in (-1, 1.5, True):
            with self.assertRaisesRegex(ValueError, "留钱"):
                apply_commands(deepcopy(state), [{"type": "strategy", "areaKey": "III",
                    "value": {"scoringOptions": {"merchantReserve": invalid}}}])
        apply_commands(state, [{"type": "strategy", "areaKey": "III",
                    "value": {"scoringOptions": {"merchantReserve": 30}}}])
        self.assertEqual(active_instance(state, "III")["strategy"]["scoringOptions"]["merchantReserve"], 30)

    def test_search_coverage_is_an_explicit_priority_before_score(self):
        searched = _Candidate(0, "exit", (63740, 2), prerequisite_rank=(1, 500000))
        not_searched = _Candidate(1, "exit", (117175, 3), prerequisite_rank=(1, 0))
        self.assertLess(_candidate_rank(searched), _candidate_rank(not_searched))
