from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from fulcrum.decision_advisor import DecisionAdvisor, advise
from fulcrum.playtime_route import route_inputs
from fulcrum.route_allocation import MoveChoice
from fulcrum.route_planner import RoutePlanner, SCORE_SCALE
from fulcrum.service.app import create_app
from tests.test_route_planner import make_map, state
from tests.test_snapshot_scoring import context


def item(component, uses=1):
    return {"instanceId": component, "componentId": component, "remainingUses": uses, "estimatedValue": 0}


class OneStepAdviceTests(unittest.TestCase):
    def inputs(self, ap=3, **kwargs):
        return state(ap, scoringContext=context("II"), maxStates=500, **kwargs)

    def simple(self, **kwargs):
        game = make_map([(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "node_type_015")],
                        [("0,0", "1,0"), ("1,0", "2,0")])
        return game, self.inputs(**kwargs)

    def test_input_read_only_and_global_scoring_unchanged(self):
        game, inputs = self.simple()
        original = deepcopy((game, inputs))
        before = RoutePlanner(game).score_snapshot(inputs)
        result = advise(game, inputs)
        self.assertEqual((game, inputs), original)
        self.assertEqual(RoutePlanner(game).score_snapshot(inputs), before)
        self.assertEqual(result["mode"], "advice")
        self.assertFalse(result["method"]["nodeWeightsChanged"])
        self.assertFalse(result["method"]["revealIncludedInRollout"])
        self.assertEqual(result["suggestions"][0]["firstStep"]["entered"], "1,0")

    def test_reveal_and_exit_settlement_are_not_double_counted(self):
        game, inputs = self.simple()
        advisor = DecisionAdvisor(game, inputs)
        root, first = advisor.move(advisor.initial, MoveChoice("walk", 1, None, 1, 0))
        self.assertAlmostEqual(first["weightedValue"], first["scoreDetails"]["nodeValue"] + first["scoreDetails"]["recruitmentValue"], places=2)
        after, end = advisor.move(root, MoveChoice("walk", 2, None, 1, 0))
        self.assertAlmostEqual(after.score_units / SCORE_SCALE, first["weightedValue"] + end["weightedValue"], delta=.06)
        self.assertGreater(end["terminalScore"]["points"], 0)

    def test_remote_clearings_do_not_reveal_from_map_recognition(self):
        game = make_map([(0, 0, "start"), (1, 0, "node_type_002"), (2, 0, "node_type_020"),
                         (3, 0, "unknown_ferocity"), (4, 0, "node_type_015")],
                        [("0,0", "1,0"), ("1,0", "2,0"), ("2,0", "3,0"), ("3,0", "4,0")])
        inputs = self.inputs(revealedNodes=["0,0", "1,0", "2,0"])
        advisor = DecisionAdvisor(game, inputs)
        self.assertFalse(advisor.initial.visible & (1 << 3))
        after, step = advisor.move(advisor.initial, MoveChoice("walk", 1, None, 1, 0))
        self.assertIn("3,0", step["newlyRevealedNodeIds"])
        self.assertTrue(after.visible & (1 << 3))

    def test_excluded_items_stay_excluded_and_actual_uses_consumed(self):
        game, inputs = self.simple(items=[item("component_020", 2)], useItemIds=[])
        result = advise(game, inputs)
        self.assertTrue(all(not row["firstStep"]["componentId"] for row in result["suggestions"]))
        advisor = DecisionAdvisor(game, {**inputs, "useItemIds": ["component_020"]})
        choice = next(c for c, _ in advisor.choices(advisor.initial) if c.item_index is not None)
        after, _ = advisor.move(advisor.initial, choice)
        self.assertEqual(after.uses, (1,))
        self.assertEqual(advisor.initial.uses, (2,))

    def test_tiny_budget_keeps_all_first_actions_and_reports_overrun(self):
        game, inputs = self.simple(items=[item("component_020")])
        inputs["maxStates"] = 1
        result = advise(game, inputs)
        advisor = DecisionAdvisor(game, inputs)
        self.assertEqual(result["metrics"]["firstActions"], len(list(advisor.choices(advisor.initial))))
        self.assertGreater(result["metrics"]["rootBudgetOverrun"], 0)
        self.assertFalse(result["searchComplete"])

    def test_zero_ap_cannot_move_with_free_item(self):
        game, inputs = self.simple(ap=0, items=[item("component_020"), item("component_019")])
        result = advise(game, inputs)
        self.assertEqual(result["suggestions"], [])
        self.assertEqual(result["metrics"]["firstActions"], 0)

    def test_no_known_exit_and_budget_exhaustion_are_distinct(self):
        game, inputs = self.simple()
        advisor = DecisionAdvisor(game, inputs)
        self.assertEqual(advisor.exit_status(advisor.initial, limit=0)["status"], "undetermined")
        self.assertEqual(advisor.exit_status(advisor.initial)["status"], "reachable")
        self.assertEqual(advisor.exit_status(replace(advisor.initial, action_points=0))["status"], "no_known_exit")

    def test_random_mixture_has_full_mass_and_does_not_draw_one_landing(self):
        game = make_map([(0, 0, "start"), (1, 0, "unknown_mystery"), (0, 1, "unknown_mystery"),
                         (2, 0, "node_type_015")], [("1,0", "2,0")])
        for node in game["nodes"]:
            if node["categoryId"] in {"unknown_mystery"}:
                node["categoryProbabilities"] = {"node_type_007": 1}
        result = advise(game, self.inputs(ap=1, items=[item("component_019")], useItemIds=[]))
        random = next(row for row in result["suggestions"] if row["random"])
        self.assertEqual(len(random["branches"]), 2)
        self.assertAlmostEqual(sum(row["probability"] for row in random["branches"]), 1)
        self.assertAlmostEqual(random["firstPoints"], sum(row["probability"] * row["firstPoints"] for row in random["branches"]))
        for branch in random["branches"]:
            self.assertEqual(branch["firstStep"]["actionPointsAfter"], 1)
            self.assertFalse(branch["remainingItems"])

    def test_goal_specific_continuation_retained_before_selection(self):
        game = make_map([(0, 0, "start"), (1, 0, "node_type_020"), (2, 0, "node_type_006"),
                         (1, 1, "node_type_004"), (2, 1, "node_type_015")],
                        [("0,0", "1,0"), ("1,0", "2,0"), ("1,0", "1,1"), ("1,1", "2,1"), ("2,0", "2,1")])
        target = {"id": "ending2_sandbox", "name": "线人", "knownNodeIds": ["2,0"], "positionProbabilities": {}}
        result = advise(game, self.inputs(planningTargets=[target]))
        row = result["suggestions"][0]
        self.assertIn(target["id"], row["relatedGoalIds"])
        option = next(o for o in row["continuations"] if o["policy"] == "goal:ending2_sandbox")
        self.assertTrue(option["goals"][0]["plannedCompletion"])
        self.assertIn("2,0", [s["entered"] for s in option["steps"]])

    def test_cancel_callback_propagates(self):
        game, inputs = self.simple()
        def cancel(_):
            raise RuntimeError("cancelled")
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            advise(game, inputs, on_expand=cancel)

    def test_shop_does_not_create_inventory(self):
        game = make_map([(0, 0, "start"), (1, 0, "node_type_004"), (2, 0, "node_type_015")],
                        [("0,0", "1,0"), ("1,0", "2,0")])
        result = advise(game, self.inputs())
        row = result["suggestions"][0]
        self.assertFalse(row["remainingItems"])
        self.assertTrue(any("商店" in reason for reason in row["reasons"]))

    def test_treehole_entry_value_requires_ap_and_sacrificable_inventory(self):
        game = make_map([(0, 0, "start"), (1, 0, "node_type_010"), (2, 0, "node_type_015")],
                        [("0,0", "1,0"), ("1,0", "2,0")])
        for items, expected in (([], False), ([item("component_014")], True)):
            row = next(r for r in advise(game, self.inputs(items=items))["suggestions"]
                       if r["firstStep"]["entered"] == "1,0" and not r["firstStep"]["componentId"])
            self.assertEqual(bool(row["firstStep"].get("treeholeChoicePending")), expected)
            self.assertEqual(row["exitCheck"]["status"], "transfer_boundary" if expected else "reachable")
            if expected:
                advisor = DecisionAdvisor(game, self.inputs(items=items))
                self.assertEqual(row["firstPoints"], advisor.scorer.terminal("1,0", 2, pursuit=False, treehole=True)["points"])
                self.assertEqual([s["entered"] for s in row["continuations"][0]["steps"]], [row["firstStep"]["entered"]])

    def test_pursuit_reward_is_shared_terminal_reward_not_new_risk_weight(self):
        game, inputs = self.simple(ap=1, pursuit=True)
        row = advise(game, inputs)["suggestions"][0]
        self.assertTrue(row["firstStep"]["pursuitTriggered"])
        self.assertGreater(row["firstStep"]["terminalScore"]["points"], 0)
        self.assertEqual(row["remainingActionPoints"], 0)

    def test_pursuit_excludes_boss_entry_but_can_check_normal_exit(self):
        game = make_map([(0, 0, "start"), (1, 0, "node_type_003"), (0, 1, "node_type_001")],
                        [("0,0", "1,0"), ("0,0", "0,1")])
        advisor = DecisionAdvisor(game, self.inputs(pursuit=True))
        self.assertTrue(all(choice.entry != 1 for choice, _ in advisor.choices(advisor.initial)))
        self.assertEqual(advisor.exit_status(advisor.initial)["status"], "reachable")

    def test_forced_treehole_return_policy_never_predicts_more_than_one_move(self):
        game, inputs = self.simple(items=[item("component_024")], utopiaId="utopia_005")
        result = advise(game, inputs)
        for row in result["suggestions"]:
            self.assertTrue(all(len(option["steps"]) == 1 for option in row["continuations"]))


class AdviceApiTests(unittest.TestCase):
    def test_background_endpoint_supports_both_modes_without_run_mutation(self):
        fixture = json.loads((Path(__file__).resolve().parents[1] / "runs/true-run-001/playtime.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(directory)) as client:
            token = client.get("/api/session").json()["token"]
            headers = {"X-Fulcrum-Token": token}
            restored = client.post("/api/runs/restore", json={"state": fixture, "runId": "advice-api-test"}, headers=headers)
            self.assertEqual(restored.status_code, 201, restored.text[:500])
            loaded = restored.json()
            body = {"expectedRevision": loaded["revision"], "topN": 5, "maxStates": 100, "planningGoalIds": []}
            for mode in ("global", "advice"):
                response = client.post("/api/runs/advice-api-test/jobs/plan", json={**body, "mode": mode}, headers=headers)
                self.assertEqual(response.status_code, 202, response.text)
                job_id = response.json()["jobId"]
                for _ in range(100):
                    job = client.get("/api/jobs/" + job_id, headers=headers).json()
                    if job["status"] not in {"running", "queued"}:
                        break
                    time.sleep(.02)
                self.assertEqual(job["status"], "completed", job)
                self.assertEqual(job["result"]["mode"], mode)
                self.assertIn("routes" if mode == "global" else "suggestions", job["result"])
            self.assertEqual(client.get("/api/runs/advice-api-test", headers=headers).json()["revision"], loaded["revision"])
            response = client.post("/api/runs/advice-api-test/jobs/plan", json={**body, "mode": "bad"}, headers=headers)
            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
