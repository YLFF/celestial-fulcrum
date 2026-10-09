"""Application boundary tests; existing game scoring stays in its own modules."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from fulcrum.goals import goal_summary, node_goal_annotations, validate_goals
from fulcrum.playtime_state import new_playtime, active_instance
from fulcrum.service.app import create_app
from fulcrum.service.store import RunStore, RevisionConflict, atomic_json
from fulcrum.service.updates import apply_commands
from fulcrum.window_capture import CaptureUnavailable, capture_window, select_window

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT / "runs/true-run-001/playtime.json").read_text(encoding="utf-8"))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RunStore(Path(self.temp.name) / "runs")
        self.loaded = self.store.create("unit")

    def test_defaults_and_restart(self):
        state = self.loaded["state"]
        self.assertEqual(state["opening"]["difficulty"], 15)
        self.assertEqual(len(state["componentBox"]["items"]), 2)
        self.assertEqual(state["resources"]["investmentBalance"], 99)
        self.assertEqual(RunStore(self.store.root).load("unit"), self.loaded)

    def test_revision_conflict_and_undo(self):
        updated = self.store.update("unit", 1, lambda s: apply_commands(s, [{"type": "resources", "values": {"hope": 12}}]), map_update=True)
        self.assertEqual(updated["revision"], 2)
        with self.assertRaises(RevisionConflict):
            self.store.update("unit", 1, lambda s: None)
        undone = self.store.undo("unit", 2)
        self.assertEqual(undone["revision"], 3)
        self.assertEqual(undone["state"]["resources"]["hope"], 6)
        redone = self.store.redo("unit", 3)
        self.assertEqual(redone["state"]["resources"]["hope"], 12)
        self.assertEqual(redone["revision"], 4)

    def test_manual_edits_are_grouped_with_map_updates(self):
        self.store.update("unit", 1, lambda s: s["resources"].update(hope=7))
        self.assertFalse(self.store.load("unit")["history"]["canUndo"])
        self.store.update("unit", 2, lambda s: s["resources"].update(hope=8), map_update=True)
        self.store.update("unit", 3, lambda s: s["resources"].update(hope=9))
        self.store.update("unit", 4, lambda s: s.update(memo="strategy edit"))
        self.assertEqual(self.store.load("unit")["history"]["undoCount"], 1)
        undone = self.store.undo("unit", 5)
        self.assertEqual(undone["state"]["resources"]["hope"], 7)
        self.assertEqual(undone["state"].get("memo", ""), "")
        restarted = RunStore(self.store.root)
        restored = restarted.redo("unit", 6)
        self.assertEqual(restored["state"]["resources"]["hope"], 9)
        self.assertEqual(restored["state"]["memo"], "strategy edit")
        self.assertNotIn("_serviceHistory", restored["state"])

    def test_multiple_undo_redo_and_branching(self):
        for revision, hope in ((1, 8), (2, 10), (3, 12)):
            self.store.update("unit", revision, lambda s, value=hope: s["resources"].update(hope=value), map_update=True)
        self.store.undo("unit", 4)
        undone = self.store.undo("unit", 5)
        self.assertEqual(undone["state"]["resources"]["hope"], 8)
        self.assertEqual(undone["history"]["redoCount"], 2)
        self.store.redo("unit", 6)
        changed = self.store.update("unit", 7, lambda s: s["resources"].update(hope=20))
        self.assertFalse(changed["history"]["canRedo"])
        with self.assertRaises(ValueError):
            self.store.redo("unit", 8)
        with self.assertRaises(RevisionConflict):
            self.store.undo("unit", 7)

    def test_history_restores_floor_maps_positions_and_strategy(self):
        from fulcrum.playtime_state import merge_map_observation
        from tests.test_playtime_prediction import chain_map
        self.store.update("unit", 1, lambda state: merge_map_observation(state, "III", chain_map(3)), map_update=True)
        self.store.update("unit", 2, lambda state: apply_commands(state, [
            {"type": "position", "areaKey": "III", "value": "1,0"},
            {"type": "strategy", "areaKey": "III", "value": {"scoringOptions": {"merchantReserveCash": 30}}},
        ]))
        self.store.update("unit", 3, lambda state: merge_map_observation(state, "IV", chain_map(4)), map_update=True)
        undone = self.store.undo("unit", 4)["state"]
        self.assertEqual(undone["currentAreaKey"], "III")
        self.assertEqual(active_instance(undone, "III")["playerPosition"], "1,0")
        self.assertEqual(active_instance(undone, "III")["strategy"]["scoringOptions"]["merchantReserveCash"], 30)
        self.assertFalse(undone["areas"]["IV"]["instances"])
        self.assertEqual(self.store.redo("unit", 5)["state"]["currentAreaKey"], "IV")

    def test_legacy_snapshot_is_reused_only_for_map_transition(self):
        from fulcrum.playtime_state import merge_map_observation
        from tests.test_playtime_prediction import chain_map
        original = deepcopy(self.loaded["state"])
        changed = deepcopy(original)
        changed["resources"]["hope"] = 20
        atomic_json(self.store.path("unit"), changed)
        atomic_json(self.store.path("unit").with_name("previous.json"), original)
        self.assertFalse(self.store.load("unit")["history"]["canUndo"])
        merge_map_observation(changed, "III", chain_map(3))
        atomic_json(self.store.path("unit"), changed)
        self.assertTrue(self.store.load("unit")["history"]["canUndo"])
        undone = self.store.undo("unit", 1)
        self.assertIsNone(undone["state"]["currentAreaKey"])
        self.assertEqual(self.store.redo("unit", 2)["state"]["currentAreaKey"], "III")

    def test_invalid_batch_does_not_save(self):
        commands = [{"type": "resources", "values": {"hope": 99}}, {"type": "componentAdd", "componentId": "bad"}]
        with self.assertRaises(ValueError):
            self.store.update("unit", 1, lambda s: apply_commands(s, commands))
        self.assertEqual(self.store.load("unit"), self.loaded)
        self.assertFalse(self.store.path("unit").with_name("previous.json").exists())

    def test_restore_duplicate_and_new_id(self):
        with self.assertRaises(RevisionConflict):
            self.store.restore(self.loaded["state"])
        self.assertEqual(self.store.restore(self.loaded["state"], run_id="copy")["revision"], 1)

    def test_path_and_malformed_input(self):
        for name in ("../bad", "CON", "x/y", "", "C:/tmp"):
            with self.assertRaises(ValueError):
                self.store.path(name)
        for state in ([], {}, {"runId": "bad", "goals": []}):
            with self.assertRaises(ValueError):
                self.store.restore(state)

    def test_inventory_roster_and_squad_edit(self):
        commands = [
            {"type": "relics", "items": [{"id": "relic_225", "count": 1}]},
            {"type": "componentAdd", "componentId": "component_023", "instanceId": "movement"},
            {"type": "componentUpdate", "instanceId": "movement", "changes": {"remainingUses": 2, "routeCandidate": False}},
            {"type": "operatorAdd", "name": "test", "instanceId": "op", "rarity": 6, "recordOnly": True},
            {"type": "operatorUpdate", "instanceId": "op", "changes": {"elite": 2}},
            {"type": "squad", "operatorIds": ["op"]},
            {"type": "tickets", "items": ["重装招募券"]},
        ]
        updated = self.store.update("unit", 1, lambda s: apply_commands(s, commands))["state"]
        self.assertEqual(updated["resources"]["hope"], 6)
        self.assertEqual(updated["squad"], ["op"])
        self.assertEqual(updated["goals"]["progress"]["ending2_sandbox"]["status"], "completed")
        self.assertFalse(updated["componentBox"]["items"][-1]["routeCandidate"])
        with self.assertRaises(ValueError):
            self.store.update("unit", 2, lambda s: apply_commands(s, [{"type": "squad", "operatorIds": ["missing"]}]))

    def test_goals_are_passed_to_scoring_without_mutating_map(self):
        from fulcrum.playtime_route import route_inputs
        state = fixture()
        original = route_inputs(state)
        apply_commands(state, [{"type": "goals", "value": {"endingV": "ending2", "endingVI": "normal3"}}])
        changed = route_inputs(state)
        self.assertEqual(changed[0], original[0])
        self.assertEqual(changed[1]["scoringContext"]["goals"], state["goals"])
        self.assertEqual(changed[1]["pursuit"], original[1]["pursuit"])
        self.assertTrue(goal_summary(state)["affectsRouteRanking"])
        self.assertTrue(goal_summary(state)["prerequisitePriorityRanking"])

    def test_goal_annotations_not_completion(self):
        state = fixture()
        state["goals"] = {"endingVI": "normal3"}
        instance = active_instance(state, "I")
        target = next(node for node in instance["nodes"].values() if node["id"] != "0,0")
        target["confirmedMarkIds"] = ["node_mark_004"]
        annotations = node_goal_annotations(state, instance)
        self.assertEqual(annotations[target["id"]]["goals"][0]["status"], "unknown")
        self.assertTrue(annotations[target["id"]]["completionRequiresPlayerConfirmation"])

    def test_unchecking_informant_survives_history_and_reload(self):
        source = fixture()
        node = active_instance(source, "I")["nodes"]["0,0"]
        node.update(encounterId="encounter_022", completion="completed", resolvedCategoryId="node_type_006",
                    completedCategoryId="node_type_006")
        source["goals"] = {"progress": {"ending2_sandbox": {"status": "completed"}}}
        loaded = self.store.restore(source, run_id="history")
        commands = [{"type": "goals", "value": {"progress": {"ending2_sandbox": {"status": "pending"}}}}]
        updated = self.store.update("history", loaded["revision"], lambda s: apply_commands(s, commands))
        for state in (updated["state"], RunStore(self.store.root).load("history")["state"]):
            self.assertEqual(goal_summary(state)["milestones"][0]["status"], "pending")
            self.assertTrue(any(row["id"] == "encounter_022" and row["completedCount"] for row in state["globalEncounterPool"]))

    def test_node_edit_and_reset(self):
        loaded = self.store.restore(fixture(), run_id="mapped")
        instance = active_instance(loaded["state"], "I")
        target = next(key for key in instance["nodes"] if key != "0,0")
        result = self.store.update("mapped", 1, lambda s: apply_commands(s, [
            {"type": "node", "areaKey": "I", "nodeId": target, "changes": {"encounterId": "encounter_001", "completion": "completed"}},
            {"type": "position", "areaKey": "I", "value": target},
        ]))
        self.assertEqual(active_instance(result["state"], "I")["playerPosition"], target)
        result = self.store.update("mapped", 2, lambda s: apply_commands(s, [
            {"type": "nodeReset", "areaKey": "I", "nodeId": target, "categoryId": "unknown_mystery"}]))
        node = active_instance(result["state"], "I")["nodes"][target]
        self.assertIsNone(node["encounterId"])
        self.assertEqual(node["completion"], "pending")

    def test_export_markdown_includes_goals(self):
        self.assertIn("目标进度", self.store.markdown("unit"))
        from fulcrum.playtime_view import replace_runtime_sections
        text = self.store.markdown("unit")
        self.assertIn("## 3. 地图、节点与本层策略", text)
        self.assertEqual(replace_runtime_sections(text, self.loaded["state"]), text)


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(self.temp.name)
        self.client = self.enterContext(TestClient(self.app))
        self.token = self.client.get("/api/session").json()["token"]
        self.client.headers["X-Fulcrum-Token"] = self.token
        self.run = self.client.post("/api/runs/restore", json={"state": fixture(), "runId": "api"}).json()

    def wait_job(self, response):
        self.assertEqual(response.status_code, 202, response.text)
        job_id = response.json()["jobId"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            row = self.client.get(f"/api/jobs/{job_id}").json()
            if row["status"] not in {"queued", "running"}:
                return row
            time.sleep(.02)
        self.fail("job timed out")

    def test_security_and_strict_body(self):
        self.assertEqual(self.client.get("/api/runs", headers={"X-Fulcrum-Token": "bad"}).status_code, 401)
        self.assertEqual(self.client.get("/api/session", headers={"Origin": "http://evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/session", headers={"Host": "evil.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/runs", json={"runId": "invalid", "difficulty": "15"}).status_code, 422)
        self.assertEqual(self.client.post("/api/runs", json={"runId": "invalid", "unknown": 1}).status_code, 422)

    def test_new_run_goals_and_resume(self):
        response = self.client.post("/api/runs", json={"runId": "new", "squadId": "squad_014", "goals": {"endingV": "ending2"}})
        self.assertEqual(response.status_code, 201, response.text)
        state = response.json()["state"]
        self.assertEqual(state["componentBox"]["capacity"], 12)
        self.assertEqual(self.client.get("/api/runs/new").json()["goalSummary"]["milestones"][0]["priority"], "required")
        self.assertEqual(self.client.post("/api/runs/restore", json={"state": state}).status_code, 409)
        self.assertIn("全局策略", self.client.get("/api/runs/new/markdown").text)

    def test_bad_nested_update_returns_422(self):
        for command in (
            {"type": "goals", "value": {"endingV": []}},
            {"type": "relics", "items": [{"id": []}]},
            {"type": "resources", "values": {"hope": -1}},
            {"type": "node", "areaKey": [], "nodeId": "0,0", "changes": {}},
        ):
            response = self.client.patch("/api/runs/api", json={"expectedRevision": 1, "commands": [command]})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get("/api/runs/api").json()["revision"], 1)

    def test_catalog_and_map(self):
        self.assertIn("labels", self.client.get("/api/catalog").json())
        data = self.client.get("/api/runs/api/maps/I").json()
        self.assertEqual(data["instance"]["playerPosition"], "0,0")
        self.assertTrue(data["instance"]["prediction"])
        self.assertFalse(self.client.get("/api/capabilities").json()["relicEffectAggregation"])

    def test_threshold_display_and_override_use_same_snapshot(self):
        before = self.client.get("/api/runs/api").json()
        self.assertEqual(before["teamThresholds"]["I"]["override"], "auto")
        response = self.client.patch("/api/runs/api", json={"expectedRevision": before["revision"], "commands": [
            {"type": "strategy", "areaKey": "I", "value": {"scoringOptions": {"teamThresholdOverride": "insufficient"}}}]})
        self.assertEqual(response.status_code, 200, response.text)
        loaded = self.client.get("/api/runs/api").json()
        self.assertFalse(loaded["teamThresholds"]["I"]["met"])
        self.assertTrue(loaded["teamThresholds"]["I"]["automaticMet"])
        self.assertEqual(loaded["state"]["operators"], before["state"]["operators"])

    def test_image_validation_and_no_path(self):
        self.assertEqual(self.client.post("/api/images", files={"file": ("bad.jpg", b"bad")}).status_code, 422)
        payload = cv2.imencode(".png", np.zeros((40, 60, 3), dtype=np.uint8))[1].tobytes()
        response = self.client.post("/api/images", files={"file": ("map.png", payload)})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["width"], 60)
        self.assertEqual(self.client.get(response.json()["imageUrl"]).headers["content-type"], "image/png")
        self.assertEqual(self.client.get("/api/images/invalid").status_code, 422)

    def test_score_plan_readonly_and_stale(self):
        before = deepcopy(self.client.get("/api/runs/api").json()["state"])
        row = self.wait_job(self.client.post("/api/runs/api/jobs/score", json={"expectedRevision": 1}))
        self.assertEqual(row["status"], "completed", row)
        self.assertIn("nodeValues", row["result"])
        plan = self.wait_job(self.client.post("/api/runs/api/jobs/plan", json={"expectedRevision": 1, "topN": 2, "maxStates": 10000}))
        self.assertEqual(plan["status"], "completed", plan)
        self.assertEqual(plan["result"]["mode"], "exit")
        self.assertEqual(self.client.get("/api/runs/api").json()["state"], before)
        self.client.patch("/api/runs/api", json={"expectedRevision": 1, "commands": [{"type": "memo", "value": "test"}]})
        self.assertTrue(self.client.get(f"/api/jobs/{row['jobId']}").json()["stale"])
        self.assertEqual(self.client.post("/api/runs/api/jobs/plan", json={"expectedRevision": 1}).status_code, 409)

    def ending_run(self, name="ending-api"):
        from fulcrum.playtime_state import merge_map_observation, rebuild_derived
        from tests.test_playtime_prediction import chain_map
        source = new_playtime(name)
        instance = merge_map_observation(source, "III", chain_map(3), player_position="0,0")
        instance["actionPoints"] = 2
        source["goals"]["progress"] = {
            "ending2_sandbox": {"status": "completed"}, "ending3_beacon": {"status": "completed"},
            "ending3_autopsy": {"status": "completed"}, "ending3_trade": {"status": "completed"},
        }
        target = instance["nodes"]["1,0"]
        target.update(observedCategoryId="node_type_006", resolvedCategoryId="node_type_006", visibility="revealed",
                      completion="pending", confirmedMarkIds=["node_mark_005"], encounterId="encounter_023")
        rebuild_derived(source)
        response = self.client.post("/api/runs/restore", json={"state": source})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_per_floor_goal_choice_reaches_scoring_without_writing_run(self):
        loaded = self.ending_run()
        check = self.client.post("/api/runs/ending-api/planning-check", json={"expectedRevision": 1}).json()
        self.assertTrue(check["valid"], check)
        self.assertEqual([row["id"] for row in check["targets"]], ["ending3_tribute"])
        for selected in ([], ["ending3_tribute"]):
            result = self.wait_job(self.client.post("/api/runs/ending-api/jobs/score", json={
                "expectedRevision": 1, "planningGoalIds": selected}))
            self.assertEqual(result["status"], "completed", result)
            value = result["result"]["nodeValues"]["1,0"]
            self.assertEqual(value["referenceLoss"]["includedInPlanningScore"], not bool(selected))
        self.assertEqual(self.client.get("/api/runs/ending-api").json()["state"], loaded["state"])

    def test_conflicting_progress_blocks_before_job_submission(self):
        self.ending_run()
        response = self.client.patch("/api/runs/ending-api", json={"expectedRevision": 1, "commands": [
            {"type": "goals", "value": {"progress": {"ending3_tribute": {"status": "completed"}}}}]})
        self.assertEqual(response.status_code, 200, response.text)
        before_jobs = len(self.app.state.jobs.records)
        check = self.client.post("/api/runs/ending-api/planning-check", json={"expectedRevision": 2}).json()
        self.assertFalse(check["valid"])
        self.assertIn("already_completed", {row["code"] for row in check["conflicts"]})
        response = self.client.post("/api/runs/ending-api/jobs/plan", json={"expectedRevision": 2})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("泪之聚落", response.text)
        self.assertEqual(len(self.app.state.jobs.records), before_jobs)

    def test_invalid_goal_selection_and_restored_strategy_rejected(self):
        loaded = self.ending_run()
        for selected in (["bad"], ["ending3_autopsy"], ["ending3_tribute", "ending3_tribute"]):
            response = self.client.post("/api/runs/ending-api/jobs/plan", json={
                "expectedRevision": 1, "planningGoalIds": selected})
            self.assertEqual(response.status_code, 422, response.text)
        instance = active_instance(loaded["state"], "III")
        instance["strategy"]["planningGoalIds"] = ["bad"]
        response = self.client.post("/api/runs/restore", json={"state": loaded["state"], "runId": "bad-strategy"})
        self.assertEqual(response.status_code, 422, response.text)

    def mock_recognition_job(self, observation):
        payload = cv2.imencode(".png", np.zeros((30, 30, 3), dtype=np.uint8))[1].tobytes()
        asset = self.client.post("/api/images", files={"file": ("mock.png", payload)}).json()
        with patch("fulcrum.vision_pipeline.MapRecognizer.recognize") as recognize:
            recognize.return_value.to_dict.return_value = deepcopy(observation)
            return self.wait_job(self.client.post("/api/runs/api/jobs/recognize", json={
                "expectedRevision": 1, "assetId": asset["assetId"], "areaKey": "I"}))

    def test_recognition_confirmation_preserves_review_fields(self):
        observation = json.loads((ROOT / "runs/true-run-001/map-state0.json").read_text(encoding="utf-8"))
        observation["resourceObservation"] = {"fields": {
            "hope": {"status": "needs_review", "value": 2},
            "originium_ingot": {"status": "recognized", "value": 88},
            "action_points": {"status": "recognized", "value": 6},
        }}
        before = self.client.get("/api/runs/api").json()
        row = self.mock_recognition_job(observation)
        self.assertEqual(self.client.get("/api/runs/api").json(), before)
        response = self.client.post("/api/runs/api/confirm-recognition", json={
            "expectedRevision": 1, "jobId": row["jobId"], "areaKey": "I"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"]["resources"]["hope"], 0)
        self.assertEqual(response.json()["state"]["resources"]["originiumIngot"], 88)
        self.assertEqual(response.json()["history"]["undoCount"], 1)
        self.assertEqual(self.client.post("/api/runs/api/confirm-recognition", json={
            "expectedRevision": 2, "jobId": row["jobId"], "areaKey": "I"}).status_code, 409)
        edited = self.client.patch("/api/runs/api", json={"expectedRevision": 2, "commands": [{"type": "memo", "value": "after move"}]})
        self.assertEqual(edited.status_code, 200, edited.text)
        undone = self.client.post("/api/runs/api/undo", json={"expectedRevision": 3})
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()["state"]["resources"]["originiumIngot"], before["state"]["resources"]["originiumIngot"])
        redone = self.client.post("/api/runs/api/redo", json={"expectedRevision": 4})
        self.assertEqual(redone.status_code, 200, redone.text)
        self.assertEqual(redone.json()["state"]["resources"]["originiumIngot"], 88)
        self.assertEqual(redone.json()["state"]["memo"], "after move")

    def test_partial_resource_confirmation_does_not_change_map(self):
        row = self.mock_recognition_job({"success": False, "resourceObservation": {"fields": {
            "hope": {"status": "recognized", "value": 5}, "originium_ingot": {"status": "recognized", "value": 88}}}})
        self.assertEqual(self.client.post("/api/runs/api/confirm-recognition", json={
            "expectedRevision": 1, "jobId": row["jobId"], "areaKey": "I"}).status_code, 422)
        response = self.client.post("/api/runs/api/confirm-recognition", json={
            "expectedRevision": 1, "jobId": row["jobId"], "confirmMap": False, "resourceFields": ["hope"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"]["resources"]["hope"], 5)
        self.assertEqual(response.json()["state"]["resources"]["originiumIngot"], self.run["state"]["resources"]["originiumIngot"])
        self.assertFalse(response.json()["history"]["canUndo"])

    def test_cancel_and_job_restart(self):
        row = self.wait_job(self.client.post("/api/runs/api/jobs/score", json={"expectedRevision": 1}))
        self.assertEqual(self.client.post(f"/api/jobs/{row['jobId']}/cancel").json()["status"], "completed")
        self.app.state.jobs.records.pop(row["jobId"])
        saved = self.app.state.jobs.get(row["jobId"])
        self.assertEqual(saved["result"]["nodeValues"], row["result"]["nodeValues"])

    def test_running_recognition_cancel_discards_result(self):
        from threading import Event
        entered, release = Event(), Event()
        payload = cv2.imencode(".png", np.zeros((30, 30, 3), dtype=np.uint8))[1].tobytes()
        asset = self.client.post("/api/images", files={"file": ("mock.png", payload)}).json()
        def blocked(*args, **kwargs):
            from fulcrum.map_model import MapResult
            entered.set()
            release.wait(5)
            return MapResult("mock", (30, 30), "main", 1, False)
        with patch("fulcrum.vision_pipeline.MapRecognizer.recognize", side_effect=blocked):
            response = self.client.post("/api/runs/api/jobs/recognize", json={
                "expectedRevision": 1, "assetId": asset["assetId"], "areaKey": "I"})
            self.assertTrue(entered.wait(5))
            job_id = response.json()["jobId"]
            self.client.post(f"/api/jobs/{job_id}/cancel")
            release.set()
            row = self.wait_job(response)
        self.assertEqual(row["status"], "cancelled")
        self.assertNotIn("result", row)
        self.assertEqual(self.client.get("/api/runs/api").json()["revision"], 1)

    def test_capture_endpoint_requires_explicit_window(self):
        self.assertEqual(self.client.post("/api/capture", json={"pid": 123}).status_code, 422)
        body = {"pid": 123, "windowId": "456", "authorizationId": "bad"}
        self.assertEqual(self.client.post("/api/capture", json=body).status_code, 403)
        with patch("fulcrum.service.app.select_window", return_value={"pid": 123, "windowId": "456"}):
            request = {"pid": 123, "windowId": "456", "consent": False}
            self.assertEqual(self.client.post("/api/capture/authorize", json=request).status_code, 403)
            request["consent"] = True
            grant = self.client.post("/api/capture/authorize", json=request).json()
        body["authorizationId"] = grant["authorizationId"]
        with patch("fulcrum.service.app.capture_window", side_effect=CaptureUnavailable("blank")):
            self.assertEqual(self.client.post("/api/capture", json=body).status_code, 503)
        self.assertEqual(self.client.post("/api/capture", json={**body, "pid": 124}).status_code, 403)
        self.client.post("/api/capture/revoke", json={"authorizationId": grant["authorizationId"]})
        self.assertEqual(self.client.post("/api/capture", json=body).status_code, 403)

    def test_local_only_and_no_pairing(self):
        with TestClient(self.app, client=("192.168.1.20", 5000)) as remote:
            self.assertEqual(remote.get("/api/session").status_code, 403)
        self.assertEqual(self.client.post("/api/pair", json={"code": "12345678"}).status_code, 404)

    def test_ui_static_and_unknown_icons(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn("/ui-assets/", self.client.get("/").text)
        catalog = self.client.get("/api/catalog").json()
        self.assertEqual(len(catalog["nodeIcons"]), 2)
        for row in catalog["nodeIcons"]:
            self.assertEqual(self.client.get(row["imageUrl"]).status_code, 200)
        self.assertEqual(self.client.get("/api/vision-icons/not-allowed").status_code, 404)

    def test_example_is_a_copy(self):
        original = fixture()
        response = self.client.post("/api/examples/true-run-001/restore", json={"runId": "example-copy"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["runId"], "example-copy")
        self.assertEqual(len(active_instance(response.json()["state"], "I")["nodes"]), 13)
        self.assertEqual(fixture(), original)


class CaptureTests(unittest.TestCase):
    def test_selection_ambiguity_and_minimized(self):
        with patch("fulcrum.window_capture.list_windows", return_value=[]):
            with self.assertRaises(CaptureUnavailable):
                select_window(123)
        rows = [{"windowId": "1", "minimized": False}, {"windowId": "2", "minimized": True}]
        with patch("fulcrum.window_capture.list_windows", return_value=rows):
            with self.assertRaises(CaptureUnavailable):
                select_window(123)
            self.assertEqual(select_window(123, "1")["windowId"], "1")
            with self.assertRaises(CaptureUnavailable):
                select_window(123, "2")

    def test_crop_method_timeout_validation(self):
        for values in ({"method": "auto"}, {"crop": [-1, 0, 5, 5]}, {"crop": [0, 0, 0, 1]}, {"timeout": 0}):
            with self.assertRaises(ValueError):
                capture_window(1, "2", **values)

    def test_goal_malformed_validation(self):
        for value in ({"endingV": []}, {"preferences": {"ending2_sandbox": []}}, {"progress": {"ending2_sandbox": {"status": []}}}):
            with self.assertRaises(ValueError):
                validate_goals(value)


class JobRestartTests(unittest.TestCase):
    def test_interrupted_jobs_and_completed_results_survive_restart(self):
        from fulcrum.service.jobs import JobManager
        from fulcrum.service.assets import AssetStore
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store, assets = RunStore(root / "runs"), AssetStore(root / "assets")
            store.create("restart")
            jobs = root / "jobs"
            jobs.mkdir()
            common = {"runId": "restart", "sourceRevision": 1}
            atomic_json(jobs / ("a" * 32 + ".json"), {**common, "jobId": "a" * 32, "status": "running"})
            legacy = {"ok": True, "warnings": ["1 node categories require review."]}
            atomic_json(jobs / ("b" * 32 + ".json"), {**common, "jobId": "b" * 32, "status": "completed", "result": legacy})
            manager = JobManager(jobs, store, assets)
            try:
                self.assertEqual(manager.get("a" * 32)["status"], "interrupted")
                result = manager.get("b" * 32)["result"]
                self.assertTrue(result["ok"])
                self.assertIn("节点类别需核对", result["warnings"][0])
                self.assertEqual(json.loads((jobs / ("b" * 32 + ".json")).read_text(encoding="utf-8"))["result"], legacy)
                self.assertFalse(manager.get("b" * 32)["stale"])
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
