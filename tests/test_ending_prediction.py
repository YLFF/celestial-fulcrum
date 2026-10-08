from copy import deepcopy
import unittest

from fulcrum.ending_prediction import attach_ending_prediction, ending_placements, planning_check, validate_target_ids
from fulcrum.goals import goal_summary
from fulcrum.node_scoring import SnapshotScorer
from fulcrum.route_planner import RoutePlanner
from tests.test_route_planner import make_map, state
from tests.test_snapshot_scoring import context


def node(category, *, marks=(), completion="pending", event=None):
    return {"resolvedCategoryId": category if category not in {"unknown_mystery", "unknown_ferocity"} else None,
            "observedCategoryId": category, "completion": completion, "confirmedMarkIds": list(marks), "encounterId": event}


def scenario(beacon=True):
    c = context("III")
    c["goals"]["progress"]["ending2_sandbox"] = {"status": "completed"}
    if beacon:
        c["goals"]["progress"]["ending3_beacon"] = {"status": "completed"}
    instance = {"areaKey": "III", "strategy": {}, "nodes": {
        "0,0": node("node_type_020", completion="completed"),
        "a": node("unknown_mystery"), "b": node("unknown_mystery"), "c": node("unknown_mystery"),
        "d": node("unknown_ferocity"), "e": node("unknown_ferocity"),
    }}
    prediction = {"unknownNodes": {key: {"candidates": [{"categoryId": "node_type_006" if key in "abc" else "node_type_001", "distanceFrequency": .3}]}
                                   for key in "abcde"}, "encounterPool": {"markedEvents": [],
                                       "candidates": [{"id": "encounter_006", "eligibility": "possible"}]}, "encounterNodes": {}}
    attach_ending_prediction(c, instance, prediction)
    c["prediction"] = prediction
    instance["prediction"] = prediction
    return c, instance


class EndingPlacementTests(unittest.TestCase):
    def test_uniform_placement_is_separate_from_lubiao_weights(self):
        c, instance = scenario()
        placements = ending_placements(c, instance)
        self.assertEqual(placements["ending3_autopsy"]["positionProbabilities"], {"d": .5, "e": .5})
        self.assertEqual(placements["ending3_trade"]["positionProbabilities"], {})
        self.assertFalse(placements["ending3_trade"]["guaranteedGeneration"])
        self.assertEqual(c["prediction"]["unknownNodes"]["a"]["candidates"][0]["distanceFrequency"], .3)

    def test_completed_prerequisite_and_known_location_remove_unknown_occupancy(self):
        c, instance = scenario()
        c["goals"]["progress"]["ending3_autopsy"] = {"status": "completed"}
        instance["nodes"]["a"] = node("node_type_008", marks=["node_mark_006"])
        del c["prediction"]["unknownNodes"]["a"]
        attach_ending_prediction(c, instance, c["prediction"])
        rows = ending_placements(c, instance)
        self.assertFalse(rows["ending3_autopsy"]["positionProbabilities"])
        self.assertFalse(rows["ending3_trade"]["positionProbabilities"])
        self.assertEqual(rows["ending3_trade"]["locatedNodeIds"], ["a"])
        self.assertEqual(rows["ending3_tribute"]["positionProbabilities"], {"b": .5, "c": .5})

    def test_no_beacon_no_weakening_or_treehole_placements(self):
        c, instance = scenario(False)
        self.assertFalse(ending_placements(c, instance)["ending3_trade"]["eligible"])
        instance["areaKey"] = "III-treehole"
        self.assertTrue(all(not row["eligible"] for row in ending_placements(c, instance).values()))
        instance["areaKey"] = "IV-remembrance"
        c["goals"]["progress"]["ending3_beacon"] = {"status": "completed"}
        self.assertTrue(ending_placements(c, instance)["ending3_trade"]["eligible"])

    def test_visited_informant_excluded_even_without_alpha(self):
        c, instance = scenario(False)
        c["goals"]["progress"].clear()
        c["globalEncounterPool"] = [{"id": "encounter_022", "completedCount": 1}]
        self.assertEqual(goal_summary(c)["milestones"][0]["status"], "completed")
        self.assertFalse(ending_placements(c, instance)["ending2_sandbox"]["eligible"])
        c["globalEncounterPool"] = []
        c["goals"]["progress"]["ending3_beacon"] = {"status": "completed"}
        self.assertTrue(ending_placements(c, instance)["ending2_sandbox"]["eligible"])

    def test_explicit_progress_overrides_old_history_and_owned_relic(self):
        c, instance = scenario(False)
        c["globalEncounterPool"] = [{"id": "encounter_022", "completedCount": 1}]
        c["relics"] = [{"id": "relic_225"}]
        c["goals"]["progress"]["ending2_sandbox"] = {"status": "pending"}
        self.assertEqual(goal_summary(c)["milestones"][0]["status"], "pending")
        self.assertTrue(ending_placements(c, instance)["ending2_sandbox"]["eligible"])
        c["goals"]["progress"]["ending2_sandbox"] = {"status": "unknown"}
        self.assertEqual(goal_summary(c)["milestones"][0]["status"], "completed")

    def test_treeholes_never_offer_prerequisites_including_dispatch(self):
        c, instance = scenario(False)
        c["goals"]["progress"].clear()
        instance["nodes"]["a"] = node("node_type_009")
        instance["prediction"] = {"unknownNodes": {"b": {"categories": {"first-step": {"isCandidate": True}}}}}
        for area in ("III-treehole", "IV-treehole", "V-treehole"):
            instance["areaKey"] = area
            self.assertFalse(planning_check(c, instance)["targets"])
            self.assertTrue(all(not row["eligible"] for row in ending_placements(c, instance).values()))
        instance["areaKey"] = "IV-remembrance"
        self.assertIn("ending3_beacon", [row["id"] for row in planning_check(c, instance)["targets"]])
        c["goals"]["progress"]["ending3_beacon"] = {"status": "completed"}
        instance["prediction"] = c["prediction"]
        attach_ending_prediction(c, instance, c["prediction"])
        self.assertEqual({row["id"] for row in planning_check(c, instance)["targets"]}, set(ending_placements(c, instance)) - {"ending3_trade"})

    def test_treehole_ending_marker_is_rejected(self):
        c, instance = scenario()
        instance["areaKey"] = "III-treehole"
        instance["nodes"]["a"] = node("node_type_008", marks=["node_mark_006"])
        self.assertIn("mark_floor", {row["code"] for row in planning_check(c, instance)["conflicts"]})

    def test_marked_events_are_inside_encounter_expectation(self):
        c, instance = scenario()
        c["options"]["planningGoalIds"] = ["ending3_trade", "ending3_tribute"]
        raw = [{"id": key, "categoryId": row["observedCategoryId"]} for key, row in instance["nodes"].items()]
        before = deepcopy(c)
        scorer = SnapshotScorer(raw, c, state(3))
        classification = scorer.values["a"]["classification"]
        self.assertAlmostEqual(sum(classification["probabilities"].values()), 1)
        self.assertAlmostEqual(classification["probabilities"]["node_type_006"], 1)
        event = next(row for row in scorer.values["a"]["types"] if row["categoryId"] == "node_type_006")
        tribute = next(row for row in event["score"]["events"] if row["eventId"] == "encounter_023")
        self.assertAlmostEqual(tribute["probability"], 1 / 3)
        self.assertEqual(tribute["score"]["points"], 0)
        self.assertLess(scorer.values["a"]["referenceLoss"]["points"], 0)
        autopsy = next(row for row in scorer.values["d"]["types"] if row["categoryId"] == "node_type_001")
        self.assertEqual(autopsy["score"]["branches"][0]["probability"], .5)
        self.assertEqual(c, before)

    def test_unknown_autopsy_contribution_enters_route_score(self):
        c, instance = scenario()
        geometry = make_map([(0, 0, "start"), (1, 0, "unknown_ferocity")], [("0,0", "1,0")], hidden={"1,0"})
        instance["nodes"] = {"0,0": node("node_type_020", completion="completed"), "1,0": node("unknown_ferocity")}
        prediction = {"unknownNodes": {"1,0": {"candidates": [{"categoryId": "node_type_001", "distanceFrequency": .3}]}}}
        attach_ending_prediction(c, instance, prediction)
        c["prediction"] = prediction
        result = RoutePlanner(geometry).plan(state(1, pursuit=True, scoringContext=c))
        value = result["scoring"]["nodeValues"]["1,0"]
        branches = value["types"][0]["score"]["branches"]
        self.assertEqual(branches[0]["score"]["stage"], "无效验尸")
        self.assertEqual(branches[0]["probability"], 1)
        self.assertEqual(value["points"], branches[0]["score"]["points"])
        self.assertAlmostEqual(result["routes"][0]["steps"][0]["nodeValue"], value["points"])

    def test_unknown_informant_reward_changes_with_floor_choice(self):
        c, instance = scenario(False)
        c["goals"]["progress"].clear()
        attach_ending_prediction(c, instance, c["prediction"])
        raw = [{"id": key, "categoryId": row["observedCategoryId"]} for key, row in instance["nodes"].items()]
        for selected in ([], ["ending2_sandbox"]):
            c["options"]["planningGoalIds"] = selected
            value = SnapshotScorer(raw, c, state(3)).values["a"]
            event = next(row for row in value["types"] if row["categoryId"] == "node_type_006")
            informant = next(row for row in event["score"]["events"] if row["eventId"] == "encounter_022")
            self.assertEqual(informant["score"]["plannedOption"], "sandboxAlpha" if selected else "processing")

    def test_progress_marker_conflicts_but_completed_history_allowed(self):
        c, instance = scenario()
        instance["nodes"]["a"] = node("node_type_008", marks=["node_mark_006"])
        c["goals"]["progress"]["ending3_trade"] = {"status": "completed"}
        self.assertIn("already_completed", {row["code"] for row in planning_check(c, instance)["conflicts"]})
        instance["nodes"]["a"]["completion"] = "completed"
        self.assertTrue(planning_check(c, instance)["valid"])

    def test_floor_category_beacon_and_unique_mark_checks(self):
        c, instance = scenario(False)
        instance["areaKey"] = "V"
        instance["nodes"]["a"] = node("node_type_001", marks=["node_mark_002", "node_mark_005"])
        codes = {row["code"] for row in planning_check(c, instance)["conflicts"]}
        self.assertTrue({"mark_floor", "mark_category", "missing_beacon", "multiple_ending_marks"} <= codes)

    def test_marks_do_not_require_extra_slots_or_boost_ordinary_categories(self):
        c, instance = scenario()
        c["goals"]["progress"]["ending2_sandbox"] = {"status": "pending"}
        del instance["nodes"]["b"], instance["nodes"]["c"]
        attach_ending_prediction(c, instance, c["prediction"])
        self.assertNotIn("insufficient_slots", {row["code"] for row in planning_check(c, instance)["conflicts"]})
        occupancy = c["prediction"]["unknownNodes"]["a"]["endingOccupancy"]
        self.assertEqual({row["goalId"]: row["probability"] for row in occupancy}, {"ending2_sandbox": .5, "ending3_tribute": .5})

    def test_resident_can_coexist_without_granting_goal(self):
        c, instance = scenario()
        instance["nodes"]["a"] = node("node_type_008", marks=["node_mark_001", "node_mark_006"])
        check = planning_check(c, instance)
        self.assertTrue(check["valid"])
        self.assertNotIn("ending3_trade", [row["id"] for row in check["targets"]])

    def test_selected_ids_are_strict(self):
        for ids in (["bad"], ["ending3_trade", "ending3_trade"], "ending3_trade", [1]):
            with self.assertRaises(ValueError):
                validate_target_ids(ids)

    def test_two_fifth_floor_exchanges_share_one_mark_without_changing_node_rewards(self):
        c, instance = scenario()
        instance["areaKey"] = "V"
        instance["nodes"]["a"] = node("node_type_008")
        instance["nodes"]["b"] = node("node_type_008")
        del c["prediction"]["unknownNodes"]["a"], c["prediction"]["unknownNodes"]["b"]
        attach_ending_prediction(c, instance, c["prediction"])
        trade = c["prediction"]["endingPlacements"]["ending3_trade"]
        self.assertEqual(trade["positionProbabilities"], {"a": .5, "b": .5})
        c["options"]["planningGoalIds"] = ["ending3_trade"]
        raw = [{"id": key, "categoryId": row["observedCategoryId"]} for key, row in instance["nodes"].items()]
        values = SnapshotScorer(raw, c, state(3)).values
        for key in ("a", "b"):
            self.assertEqual(values[key]["points"], 100)
            self.assertEqual(values[key]["branches"][0]["probability"], .5)
        instance["nodes"]["a"]["confirmedMarkIds"] = ["node_mark_006"]
        attach_ending_prediction(c, instance, c["prediction"])
        self.assertFalse(c["prediction"]["endingCategoryMarks"])
        self.assertFalse(c["prediction"]["endingPlacements"]["ending3_trade"]["positionProbabilities"])

    def test_unknown_exchange_mark_scoring_does_not_boost_its_category(self):
        c, instance = scenario()
        for key in ("ending3_tribute", "ending3_autopsy"):
            c["goals"]["progress"][key] = {"status": "completed"}
        c["prediction"]["unknownNodes"]["a"]["candidates"] = [
            {"categoryId": "node_type_008", "distanceFrequency": .2},
            {"categoryId": "node_type_007", "distanceFrequency": .8},
        ]
        attach_ending_prediction(c, instance, c["prediction"])
        c["options"]["planningGoalIds"] = ["ending3_trade"]
        value = SnapshotScorer([{"id": "a", "categoryId": "unknown_mystery"}], c, state(3)).values["a"]
        self.assertEqual(value["classification"]["probabilities"]["node_type_008"], .2)
        exchange = next(row for row in value["types"] if row["categoryId"] == "node_type_008")
        self.assertEqual(exchange["score"]["branches"][0]["probability"], 1)
        self.assertEqual(exchange["score"]["points"], 0)
        self.assertEqual(c["prediction"]["endingPlacements"]["ending3_trade"]["positionProbabilities"], {"a": .2})


class GoalAwareSearchTests(unittest.TestCase):
    def plan(self, *, selected=True, enough=True, max_states=10000):
        geometry = make_map([(0, 0, "start"), (-1, 0, "node_type_008"), (1, 0, "node_type_007"), (0, 1, "node_type_015")],
                            [("0,0", "-1,0"), ("0,0", "1,0"), ("0,0", "0,1")])
        geometry["nodes"][1]["confirmedMarkIds"] = ["node_mark_006"]
        c = context()
        c["options"].update(planningGoalIds=["ending3_trade"] if selected else [], nodeScores={"1,0": 2000})
        if not enough:
            c["componentBox"]["items"] = []
        target = {"id": "ending3_trade", "name": "失与得上贡", "knownNodeIds": ["-1,0"], "positionProbabilities": {}}
        return RoutePlanner(geometry).plan(state(2, scoringContext=c, pursuit=True, topN=5, maxStates=max_states,
                                                planningTargets=[target] if selected else []))

    def test_selected_zero_value_goal_beats_higher_raw_score(self):
        result = self.plan()
        self.assertTrue(result["searchComplete"])
        first = result["routes"][0]
        self.assertTrue(first["prerequisites"][0]["plannedCompletion"])
        self.assertIn("-1,0", [step["entered"] for step in first["steps"]])
        self.assertLess(first["metrics"]["weightedValue"], self.plan(selected=False)["routes"][0]["metrics"]["weightedValue"])
        self.assertEqual(result["searchDiagnostics"]["pursuitTerminalsPruned"], 0)

    def test_unselected_goal_and_infeasible_goal_do_not_force_bad_route(self):
        unselected = self.plan(selected=False)["routes"][0]
        self.assertIn("1,0", [step["entered"] for step in unselected["steps"]])
        infeasible = self.plan(enough=False)["routes"][0]
        self.assertFalse(infeasible["prerequisites"][0]["feasibleFromSnapshot"])
        self.assertIn("1,0", [step["entered"] for step in infeasible["steps"]])

    def test_unrevealed_goal_increases_search_coverage_without_fake_completion(self):
        geometry = make_map([(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "unknown_mystery"), (-1, 0, "node_type_007")],
                            [("0,0", "1,0"), ("1,0", "2,0"), ("0,0", "-1,0")], hidden={"2,0"})
        c = context()
        c["options"]["nodeScores"] = {"-1,0": 10000}
        target = {"id": "ending3_trade", "name": "失与得上贡", "knownNodeIds": [], "positionProbabilities": {"2,0": 1}}
        result = RoutePlanner(geometry).plan(state(1, pursuit=True, scoringContext=c, planningTargets=[target]))
        first = result["routes"][0]
        self.assertEqual(first["steps"][0]["entered"], "1,0")
        self.assertEqual(first["prerequisites"][0]["searchCoverage"], 1)
        self.assertFalse(first["prerequisites"][0]["plannedCompletion"])

    def test_more_targets_than_budget_returns_reachable_subset(self):
        geometry = make_map([(0, 0, "start"), (-1, 0, "node_type_001"), (1, 0, "node_type_009")],
                            [("0,0", "-1,0"), ("0,0", "1,0")])
        targets = [{"id": key, "name": key, "knownNodeIds": [node_id], "positionProbabilities": {}}
                   for key, node_id in (("ending3_autopsy", "-1,0"), ("ending3_beacon", "1,0"))]
        result = RoutePlanner(geometry).plan(state(1, pursuit=True, scoringContext=context(), planningTargets=targets, maxStates=10000))
        self.assertTrue(result["searchComplete"])
        self.assertTrue(result["routes"])
        self.assertEqual(sum(row["plannedCompletion"] for row in result["routes"][0]["prerequisites"]), 1)


class EventCalibrationTests(unittest.TestCase):
    def test_free_visit_rewards_have_no_process_warning(self):
        c = context()
        scorer = SnapshotScorer([{"id": "r", "categoryId": "node_type_019"},
                                 {"id": "a", "categoryId": "node_type_017"}], c, state(3))
        for event in ("encounter_020", "encounter_021"):
            value = scorer.encounter(event)
            self.assertIn("freeVisit", value["parts"])
            self.assertFalse(value.get("modelLimitations"))
            self.assertAlmostEqual(value["points"], sum(value["parts"].values()))

    def test_treehole_dispatch_never_chooses_beacon(self):
        c = context("III-treehole", options={"planningGoalIds": ["ending3_beacon"], "chooseEnding3Dispatch": True})
        scorer = SnapshotScorer([{"id": "dispatch", "categoryId": "node_type_009"}], c, state(3))
        self.assertEqual(scorer.values["dispatch"]["plannedOption"], "promotion")

    def test_red_moss_and_event_relic_values(self):
        c = context()
        c["componentBox"]["items"] = c["componentBox"]["items"][:1]
        scorer = SnapshotScorer([], c, state(3))
        self.assertEqual(scorer.encounter("encounter_010")["points"], 350)
        self.assertEqual(scorer.encounter("encounter_006")["points"], 200)
        self.assertEqual(scorer.encounter("encounter_007")["points"], 150)

    def test_unselected_cash_tribute_is_a_real_negative_and_dynamic(self):
        c = context()
        c["options"]["planningGoalIds"] = []
        scorer = SnapshotScorer([{"id": "t", "categoryId": "node_type_006", "confirmedMarkIds": ["node_mark_005"]}], c, state(3))
        self.assertEqual(scorer.values["t"]["points"], -80)
        step = scorer.step(["t"], {"t"}, [], before_done=set(), prefix_cash=20, appraisal=0, path_steps=1, processing=False)
        self.assertEqual(step["nodeValue"], -168)
        self.assertTrue(step["nodeTerms"][0]["referenceLoss"]["includedInPlanningScore"])
        self.assertTrue(scorer.report()["tributeLossIncludedInPlanningScore"])

    def test_explicit_floor_choice_overrides_old_dispatch_setting(self):
        c = context(options={"planningGoalIds": [], "chooseEnding3Dispatch": True})
        scorer = SnapshotScorer([{"id": "dispatch", "categoryId": "node_type_009"}], c, state(3))
        self.assertEqual(scorer.values["dispatch"]["plannedOption"], "promotion")


if __name__ == "__main__":
    unittest.main()
