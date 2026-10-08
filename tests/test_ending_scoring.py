from copy import deepcopy
import unittest

from fulcrum.component_box import add_component
from fulcrum.goals import goal_summary, planning_pursuit
from fulcrum.node_scoring import SnapshotScorer
from fulcrum.playtime_route import route_inputs
from fulcrum.route_planner import RoutePlanner, SCORE_SCALE
from tests.test_local_service import fixture
from tests.test_route_planner import make_map, state
from tests.test_snapshot_scoring import context


class EndingScoringTests(unittest.TestCase):
    def test_sandbox_milestone_requires_alpha_not_beta(self):
        run = {"goals": {"endingV": "ending2"}, "relics": [{"id": "relic_226"}]}
        milestone = goal_summary(run)["milestones"][0]
        self.assertEqual(milestone["name"], "是否已通过线人节点")
        self.assertEqual(milestone["status"], "unknown")
        run["relics"].append({"id": "relic_225"})
        self.assertEqual(goal_summary(run)["milestones"][0]["status"], "completed")

    def test_unknown_fates_have_two_thirds_relic_value(self):
        nodes = [{"id": str(i), "categoryId": "node_type_012"} for i in range(3)]
        c = context("V")
        for ending in ("normal1", "pursuit1"):
            c["goals"]["endingV"] = ending
            scorer = SnapshotScorer(nodes, c, state(5))
            for row in scorer.values.values():
                self.assertEqual(row["points"], 100)
                self.assertEqual(row["fakeFateProbability"], 2 / 3)

    def test_truth_mark_or_manual_role_sets_other_fates_fake(self):
        for truth in ({"confirmedMarkIds": ["node_mark_003"]}, {"fateRole": "true"}):
            nodes = [{"id": "a", "categoryId": "node_type_012", **truth},
                     {"id": "b", "categoryId": "node_type_012"}, {"id": "c", "categoryId": "node_type_012"}]
            before = deepcopy(nodes)
            scorer = SnapshotScorer(nodes, context("V"), state(5))
            self.assertEqual(scorer.values["a"]["points"], 0)
            self.assertEqual(scorer.values["b"]["points"], 150)
            self.assertEqual(scorer.values["c"]["points"], 150)
            self.assertEqual(nodes, before)

    def test_conflicting_truth_nodes_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "multiple true fate"):
            SnapshotScorer([{"id": str(i), "categoryId": "node_type_012", "fateRole": "true"}
                            for i in range(2)], context("V"), state(3))

    def test_first_ending_controls_fifth_floor_pursuit_and_exit(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_012"),
                      (0, 1, "node_type_003"), (2, 0, "node_type_015")],
                     [("0,0", "1,0"), ("1,0", "2,0"), ("0,0", "0,1")])
        planner = RoutePlanner(m)
        c = context("V")
        c["goals"]["endingV"] = "normal1"
        result = planner.plan(state(2, pursuit=True, scoringContext=c))
        self.assertEqual(result["mode"], "exit")
        self.assertTrue(result["routes"])
        self.assertEqual({row["endNode"] for row in result["routes"]}, {"0,1"})
        c["goals"]["endingV"] = "pursuit1"
        result = planner.plan(state(2, pursuit=False, scoringContext=c))
        self.assertEqual(result["mode"], "pursuit")
        self.assertTrue(result["routes"])
        self.assertTrue(all(row["goalType"] == "pursuit" for row in result["routes"]))
        self.assertTrue(all(step["arrived"] != "0,1" for row in result["routes"] for step in row["steps"]))
        self.assertTrue(planning_pursuit(c["goals"], "V-treehole", True))
        self.assertFalse(planning_pursuit(c["goals"], "III", False))

    def test_plan_inputs_include_goals_and_held_relics(self):
        run = fixture()
        before = deepcopy(run)
        _, inputs = route_inputs(run)
        self.assertEqual(inputs["scoringContext"]["goals"], run.get("goals", {}))
        self.assertEqual(inputs["scoringContext"]["relics"], run["relics"])
        self.assertEqual(run, before)

    def test_beacon_branch_omits_promotion_until_goal_complete(self):
        c = context()
        node = {"id": "dispatch", "categoryId": "node_type_009"}
        ordinary = SnapshotScorer([node], c, state(3)).values["dispatch"]
        c["goals"]["endingVI"] = "normal3"
        planned = SnapshotScorer([node], c, state(3)).values["dispatch"]
        self.assertEqual(planned["plannedOption"], "beacon")
        self.assertEqual(planned["parts"]["promotion"], 0)
        self.assertAlmostEqual(ordinary["points"] - planned["points"], 93.75)
        c["goals"]["progress"]["ending3_beacon"] = {"status": "completed"}
        complete = SnapshotScorer([node], c, state(3)).values["dispatch"]
        self.assertEqual(complete["plannedOption"], "promotion")
        c["goals"]["progress"] = {}
        c["goals"]["preferences"]["ending3_beacon"] = "ignored"
        self.assertEqual(SnapshotScorer([node], c, state(3)).values["dispatch"]["plannedOption"], "promotion")

    def test_planned_tribute_prices_random_two_naturals_instead_of_exchange(self):
        c = context()
        c["goals"]["preferences"]["ending3_trade"] = "required"
        add_component(c["componentBox"], "component_009", estimated_value=8)
        node = {"id": "trade", "categoryId": "node_type_008", "confirmedMarkIds": ["node_mark_006"]}
        before = deepcopy(c)
        value = SnapshotScorer([node], c, state(3)).values["trade"]
        self.assertEqual(value["plannedOption"], "tribute")
        self.assertEqual(value["points"], 0)
        self.assertAlmostEqual(value["referenceLoss"]["points"], -2 * (250 + 250 + 2000) / 3)
        self.assertFalse(value["referenceLoss"]["includedInPlanningScore"])
        self.assertEqual(value["expectedAppraisalDelta"], -8)
        self.assertNotIn("exchangeOpportunity", value["parts"])
        self.assertEqual(c, before)
        c["goals"]["progress"]["ending3_trade"] = {"status": "completed"}
        self.assertEqual(SnapshotScorer([node], c, state(3)).values["trade"]["points"], 200)

    def test_painted_agor_bonus_survives_tribute_branch(self):
        c = context()
        c["goals"]["preferences"]["ending3_trade"] = "required"
        add_component(c["componentBox"], "component_030", estimated_value=1)
        scorer = SnapshotScorer([{"id": "trade", "categoryId": "node_type_008",
                                  "confirmedMarkIds": ["node_mark_006"]}], c, state(3))
        value = scorer.step(["trade"], {"trade"}, [], before_done=set(), prefix_cash=10,
                            appraisal=5, path_steps=1, processing=True)
        self.assertEqual(value["nodeTerms"][0]["parts"]["paintedBonus"], 200)
        self.assertEqual(value["nodeTerms"][0]["plannedOption"], "tribute")
        self.assertEqual(value["nodeValue"], 200)
        self.assertEqual(value["referenceLossPoints"], -500)

    def test_tribute_needs_two_naturals_and_only_applies_to_marked_node(self):
        c = context()
        c["goals"]["preferences"]["ending3_trade"] = "required"
        c["componentBox"]["items"] = c["componentBox"]["items"][:1]
        node = {"id": "trade", "categoryId": "node_type_008", "confirmedMarkIds": ["node_mark_006"]}
        value = SnapshotScorer([node], c, state(3)).values["trade"]
        self.assertFalse(value["goalFeasible"])
        self.assertEqual(value["points"], 200)
        node["confirmedMarkIds"] = []
        self.assertEqual(SnapshotScorer([node], c, state(3)).values["trade"]["points"], 200)

    def test_informant_uses_planned_alpha_branch_until_complete(self):
        c = context("II")
        c["goals"]["endingV"] = "ending2"
        scorer = SnapshotScorer([], c, state(3))
        self.assertEqual(scorer.encounter("encounter_022")["plannedOption"], "sandboxAlpha")
        self.assertEqual(scorer.encounter("encounter_022")["points"], 0)
        c["relics"].append({"id": "relic_225"})
        self.assertGreater(SnapshotScorer([], c, state(3)).encounter("encounter_022")["points"], 0)

    def test_cash_tribute_loss_is_reference_only_and_updates_at_arrival(self):
        c = context("II")
        node = {"id": "tribute", "categoryId": "node_type_006", "confirmedMarkIds": ["node_mark_005"]}
        before = deepcopy(c)
        scorer = SnapshotScorer([node], c, state(3))
        value = scorer.values["tribute"]
        self.assertEqual(value["points"], 0)
        self.assertEqual(value["referenceLoss"]["points"], -80)
        self.assertEqual(value["expectedCashDelta"], -10)
        step = scorer.step(["tribute"], {"tribute"}, [], before_done=set(), prefix_cash=15,
                           appraisal=9, path_steps=2, processing=False)
        self.assertEqual(step["nodeValue"], 0)
        self.assertEqual(step["referenceLossPoints"], -136)
        self.assertEqual(step["nodeTerms"][0]["referenceLoss"]["expectedCashLost"], 17)
        self.assertEqual(step["merchantTransition"]["cashAfter"], 0)
        self.assertEqual(step["merchantTransition"]["movementProxyStepsAfter"], 0)
        self.assertEqual(step["merchantTransition"]["appraisalAfter"], 9)
        repeated = scorer.step(["tribute"], set(), [], before_done={"tribute"}, prefix_cash=2,
                               appraisal=9, path_steps=1, processing=False)
        self.assertEqual(repeated["referenceLossPoints"], 0)
        self.assertEqual(c, before)

    def test_route_exposes_tribute_losses_without_subtracting_them_twice(self):
        c = context("II")
        c["goals"]["preferences"]["ending3_trade"] = "required"
        m = make_map([(0, 0, "start"), (1, 0, "node_type_008"), (1, 1, "node_type_006"), (2, 1, "node_type_015")],
                     [("0,0", "1,0"), ("1,0", "1,1"), ("1,1", "2,1")])
        m["nodes"][1]["confirmedMarkIds"] = ["node_mark_006"]
        m["nodes"][2]["confirmedMarkIds"] = ["node_mark_005"]
        result = RoutePlanner(m).plan(state(3, scoringContext=c))
        self.assertTrue(result["routes"])
        route = result["routes"][0]
        self.assertEqual(route["referenceLossPoints"], -596)
        self.assertEqual(route["steps"][0]["referenceLossPoints"], -500)
        self.assertEqual(route["steps"][1]["referenceLossPoints"], -96)
        self.assertAlmostEqual(route["metrics"]["weightedValue"],
                               sum(step["weightedValue"] for step in route["steps"]) + route["terminalScore"]["points"],
                               delta=1 / SCORE_SCALE)


if __name__ == "__main__":
    unittest.main()
