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
        held = [{"id": "relic_139", "count": 1, "state": 3, "note": "keep"}, {"id": "relic_001", "count": 1}]
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

    def test_map_recognition_never_runs_relic_recognition(self):
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


if __name__ == "__main__":
    unittest.main()
