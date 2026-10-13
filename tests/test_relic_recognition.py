from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from fulcrum.service.app import create_app
from fulcrum.vision_relics import RelicRecognizer, relic_atlas
from tests.test_playtime_prediction import chain_map

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def screenshot_result():
    return RelicRecognizer().recognize(ROOT / "samples/relics/visible_row.jpg")


class RelicVisionTests(unittest.TestCase):
    def test_all_catalog_icons_available(self):
        self.assertEqual(len(relic_atlas()), 243)

    def test_supplied_row_and_similar_items(self):
        result = screenshot_result()
        self.assertTrue(result["success"])
        self.assertEqual([row["id"] for row in result["slots"]],
                         ["relic_071", "relic_139", "relic_228", "relic_227", "relic_067", "relic_180", "relic_016"])
        self.assertEqual(result["slots"][1]["status"], "accepted")
        self.assertEqual(result["slots"][5]["status"], "needs_review")
        self.assertEqual(result["slots"][6]["status"], "needs_review")
        self.assertTrue(result["slots"][6]["partial"])
        self.assertNotIn("relic_016", result["acceptedRelicIds"])

    def test_resized_translated_row_is_located_not_fixed_roi(self):
        image = cv2.imread(str(ROOT / "samples/relics/visible_row.jpg"))
        image = cv2.resize(image, (1024, 466))
        image = cv2.copyMakeBorder(image, 40, 12, 75, 15, cv2.BORDER_CONSTANT)
        result = RelicRecognizer().recognize_image(image)
        self.assertTrue(result["success"])
        self.assertGreater(result["labelBox"][0], 200)
        self.assertEqual(result["slots"][1]["id"], "relic_139")
        self.assertEqual(result["slots"][5]["id"], "relic_180")

    def test_missing_hud_anchor_does_not_guess_inventory(self):
        result = RelicRecognizer().recognize_image(np.zeros((540, 960, 3), dtype=np.uint8))
        self.assertFalse(result["success"])
        self.assertEqual(result["slots"], [])
        self.assertEqual(result["acceptedRelicIds"], [])


class RelicServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(self.temp.name)
        self.client = self.enterContext(TestClient(self.app))
        self.headers = {"X-Fulcrum-Token": self.client.get('/api/session').json()["token"]}
        self.loaded = self.post('/api/runs', {"runId": "relic-test", "squadId": "squad_001"}).json()
        payload = (ROOT / "samples/relics/visible_row.jpg").read_bytes()
        self.asset = self.client.post('/api/images', headers=self.headers, files={"file": ("row.jpg", payload, "image/jpeg")}).json()

    def post(self, path, body):
        return self.client.post(path, headers=self.headers, json=body)

    def job(self, result=None):
        with patch("fulcrum.vision_relics.RelicRecognizer.recognize", return_value=deepcopy(result or screenshot_result())):
            job = self.post('/api/runs/relic-test/jobs/recognize-relics',
                            {"expectedRevision": self.loaded["revision"], "assetId": self.asset["assetId"]}).json()
            for _ in range(100):
                job = self.client.get('/api/jobs/'+job["jobId"], headers=self.headers).json()
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(.02)
        self.assertEqual(job["status"], "completed", job)
        return job

    def test_read_only_until_confirm_and_unique_append(self):
        held = [{"id": "relic_139", "count": 1, "state": None, "note": "keep"},
                {"id": "relic_033", "count": 1, "state": 3}]
        self.loaded = self.app.state.store.update("relic-test", self.loaded["revision"], lambda draft: draft.update(relics=held))
        before = deepcopy(self.loaded)
        job = self.job()
        self.assertEqual(self.app.state.store.load("relic-test"), before)
        ids = job["result"]["acceptedRelicIds"]
        response = self.post('/api/runs/relic-test/confirm-relics',
                             {"expectedRevision": before["revision"], "jobId": job["jobId"], "relicIds": ids+ids})
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()["state"]["relics"]
        self.assertEqual(rows[:2], held)
        self.assertEqual(len(rows), 6)
        self.assertNotIn("relic_180", {row["id"] for row in rows})

    def test_stale_confirmation_and_unlisted_candidate_rejected(self):
        job = self.job()
        response = self.post('/api/runs/relic-test/confirm-relics',
                             {"expectedRevision": self.loaded["revision"], "jobId": job["jobId"], "relicIds": ["relic_002"]})
        self.assertEqual(response.status_code, 422)
        self.app.state.store.update("relic-test", self.loaded["revision"], lambda draft: draft.update(memo="new"))
        response = self.post('/api/runs/relic-test/confirm-relics',
                             {"expectedRevision": self.loaded["revision"], "jobId": job["jobId"], "relicIds": []})
        self.assertEqual(response.status_code, 409)

    def test_manual_review_selection_and_foreign_job(self):
        job = self.job()
        response = self.post('/api/runs/relic-test/confirm-relics',
                             {"expectedRevision": self.loaded["revision"], "jobId": job["jobId"], "relicIds": ["relic_180", "relic_016"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.post('/api/runs', {"runId": "other", "squadId": "squad_001"})
        response = self.post('/api/runs/other/confirm-relics', {"expectedRevision": 1, "jobId": job["jobId"], "relicIds": []})
        self.assertEqual(response.status_code, 422)

    def test_repeatable_kettle_is_not_counted_twice(self):
        kettle = next(row for row in relic_atlas() if row[1] == '热水壶')[0]
        self.loaded = self.app.state.store.update("relic-test", self.loaded["revision"], lambda draft: draft.update(relics=[{"id": kettle, "count": 1}]))
        result = {"success": True, "slots": [{"candidates": [{"id": kettle}]}]}
        job = self.job(result)
        response = self.post('/api/runs/relic-test/confirm-relics',
                             {"expectedRevision": self.loaded["revision"], "jobId": job["jobId"], "relicIds": [kettle, kettle]})
        self.assertEqual(response.json()["state"]["relics"], [{"id": kettle, "count": 1}])

    def test_unmatched_map_never_runs_relic_recognition(self):
        result = SimpleNamespace(to_dict=lambda: {"success": False, "warnings": [], "nodes": []})
        with patch("fulcrum.vision_pipeline.MapRecognizer.recognize", return_value=result) as map_recognize, \
             patch("fulcrum.vision_relics.RelicRecognizer.recognize") as relic_recognize:
            job = self.post('/api/runs/relic-test/jobs/recognize',
                            {"expectedRevision": self.loaded["revision"], "assetId": self.asset["assetId"], "includeResources": False}).json()
            for _ in range(100):
                job = self.client.get('/api/jobs/'+job["jobId"], headers=self.headers).json()
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(.02)
            self.assertEqual(job["status"], "completed", job)
            relic_recognize.assert_not_called()
            self.assertEqual(map_recognize.call_args.kwargs["difficulty"], 15)
        self.assertEqual(self.app.state.store.load("relic-test"), self.loaded)

    def map_job(self, *, include_relics=True, relic_result=None, relic_error=None):
        result = SimpleNamespace(to_dict=lambda: chain_map(3))
        with patch("fulcrum.vision_pipeline.MapRecognizer.recognize", return_value=result), \
             patch("fulcrum.vision_relics.RelicRecognizer.recognize",
                   return_value=deepcopy(relic_result or screenshot_result()), side_effect=relic_error) as recognize:
            job = self.post('/api/runs/relic-test/jobs/recognize',
                            {"expectedRevision": self.loaded["revision"], "assetId": self.asset["assetId"],
                             "areaKey": "III", "includeRelics": include_relics}).json()
            for _ in range(100):
                job = self.client.get('/api/jobs/'+job["jobId"], headers=self.headers).json()
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(.02)
            self.assertEqual(job["status"], "completed", job)
            self.assertEqual(recognize.call_count, int(include_relics))
            if include_relics:
                self.assertEqual(recognize.call_args.args, (self.app.state.assets.path(self.asset["assetId"]),))
        return job

    def confirm_map(self, job, ids, **extras):
        return self.post('/api/runs/relic-test/confirm-recognition', {
            "expectedRevision": self.loaded["revision"], "jobId": job["jobId"], "areaKey": "III",
            "resourceFields": [], "relicIds": ids, **extras})

    def test_matched_map_sync_is_read_only_and_confirmation_is_one_checkpoint(self):
        held = [{"id": "relic_139", "count": 1, "state": None, "note": "keep"},
                {"id": "relic_033", "count": 1, "state": 3}]
        self.loaded = self.app.state.store.update("relic-test", self.loaded["revision"], lambda draft: draft.update(relics=held))
        before = deepcopy(self.loaded)
        job = self.map_job()
        self.assertEqual(self.app.state.store.load("relic-test"), before)
        ids = job["result"]["relicObservation"]["acceptedRelicIds"]
        self.assertNotIn("relic_180", ids)
        self.assertNotIn("relic_016", ids)
        # The unchecked relic is not appended; held and repeated IDs stay unique.
        chosen = [relic_id for relic_id in ids if relic_id != "relic_071"]
        response = self.confirm_map(job, chosen + chosen)
        self.assertEqual(response.status_code, 200, response.text)
        updated = response.json()
        self.assertEqual(updated["revision"], before["revision"] + 1)
        self.assertEqual(updated["history"]["undoCount"], 1)
        self.assertEqual(updated["state"]["relics"][:2], held)
        self.assertNotIn("relic_071", {row["id"] for row in updated["state"]["relics"]})
        undone = self.post('/api/runs/relic-test/undo', {"expectedRevision": updated["revision"]}).json()
        self.assertEqual(undone["state"]["relics"], held)
        self.assertIsNone(undone["state"]["areas"]["III"]["activeInstanceId"])
        redone = self.post('/api/runs/relic-test/redo', {"expectedRevision": undone["revision"]}).json()
        self.assertEqual(redone["state"]["relics"], updated["state"]["relics"])
        self.assertIsNotNone(redone["state"]["areas"]["III"]["activeInstanceId"])

    def test_sync_rejects_low_confidence_or_unlisted_ids_and_stale_result(self):
        job = self.map_job()
        before = deepcopy(self.loaded)
        for relic_id in ("relic_180", "relic_016", "relic_002"):
            response = self.confirm_map(job, [relic_id])
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(self.app.state.store.load("relic-test"), before)
        self.app.state.store.update("relic-test", before["revision"], lambda draft: draft.update(memo="changed"))
        self.assertEqual(self.confirm_map(job, []).status_code, 409)

    def test_sync_can_be_disabled_and_missing_relic_hud_does_not_block_map(self):
        job = self.map_job(include_relics=False)
        self.assertNotIn("relicObservation", job["result"])
        self.assertEqual(self.confirm_map(job, ["relic_071"]).status_code, 422)
        for failed in (False, True):
            with self.subTest(error=failed):
                result = {"success": False, "slots": [], "acceptedRelicIds": []}
                if failed:
                    with self.assertLogs("fulcrum.service.jobs", level="ERROR"):
                        job = self.map_job(relic_error=RuntimeError("broken atlas"))
                else:
                    job = self.map_job(relic_result=result)
                self.assertTrue(job["result"]["success"])
                self.assertFalse(job["result"]["relicObservation"]["success"])
                response = self.confirm_map(job, [])
                self.assertEqual(response.status_code, 200, response.text)
                self.loaded = response.json()

    def test_deselecting_all_relics_and_foreign_job_leave_inventory_unchanged(self):
        job = self.map_job()
        self.post('/api/runs', {"runId": "foreign-map", "squadId": "squad_001"})
        response = self.post('/api/runs/foreign-map/confirm-recognition', {
            "expectedRevision": 1, "jobId": job["jobId"], "areaKey": "III", "relicIds": []})
        self.assertEqual(response.status_code, 422)
        response = self.confirm_map(job, [])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"]["relics"], self.loaded["state"]["relics"])

    def test_resources_only_does_not_scan_map_or_relics(self):
        with patch("fulcrum.vision_pipeline.MapRecognizer.recognize") as map_recognize, \
             patch("fulcrum.vision_relics.RelicRecognizer.recognize") as relic_recognize, \
             patch("fulcrum.vision_resources.HudRecognizer.recognize_image", return_value={"fields": {}}):
            job = self.post('/api/runs/relic-test/jobs/recognize', {
                "expectedRevision": self.loaded["revision"], "assetId": self.asset["assetId"],
                "resourcesOnly": True, "includeRelics": True}).json()
            for _ in range(100):
                job = self.client.get('/api/jobs/'+job["jobId"], headers=self.headers).json()
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(.02)
            self.assertEqual(job["status"], "completed", job)
            map_recognize.assert_not_called()
            relic_recognize.assert_not_called()
        self.assertNotIn("relicObservation", job["result"])
        self.assertEqual(self.app.state.store.load("relic-test"), self.loaded)

    def test_invalid_confirmation_does_not_partially_save_map_or_relics(self):
        job = self.map_job()
        response = self.confirm_map(job, ["relic_071"], commands=[{
            "type": "resources", "values": {"hope": -1}}])
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.app.state.store.load("relic-test"), self.loaded)


if __name__ == "__main__":
    unittest.main()
