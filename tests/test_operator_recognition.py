from copy import deepcopy
import io
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from fulcrum.operator_catalog import find_operator
from fulcrum.operator_recognition import apply_operator_choices, operator_changes
from fulcrum.operators import add_operator
from fulcrum.playtime_state import new_playtime
from fulcrum.service.app import create_app
from fulcrum.vision_operators import locate_cards, match_name, normalized_name, _promotion, _tokens


def observation(name="机械师", elite=2, slot="1-1", status="accepted"):
    return {"success": True, "slots": [{"slot": slot, "name": name, "operatorId": find_operator(name)["id"],
            "elite": elite, "status": status, "box": [0, 0, 300, 100]}]}


class OperatorSyncTests(unittest.TestCase):
    def setUp(self):
        self.state = new_playtime("scan-test", initial_operators=[])
        self.state["operators"] = []

    def test_add_has_no_cost_reward_or_squad_side_effect(self):
        before = deepcopy(self.state)
        apply_operator_choices(self.state, observation(), [{"slot": "1-1"}])
        self.assertEqual(self.state["operators"][-1]["name"], "机械师")
        self.assertEqual(self.state["operators"][-1]["elite"], 2)
        for field in ("resources", "componentBox", "squad"):
            self.assertEqual(self.state.get(field), before.get(field), field)

    def test_promote_preserves_other_operators_resources_and_metadata(self):
        add_operator(self.state, "机械师", record_only=True, settle_rewards=False)
        add_operator(self.state, "林", record_only=True, settle_rewards=False)
        before = deepcopy(self.state)
        self.assertEqual(operator_changes(observation(), self.state)[0]["change"], "promote")
        apply_operator_choices(self.state, observation(), [{"slot": "1-1"}])
        self.assertEqual(self.state["operators"][0]["elite"], 2)
        self.assertEqual(self.state["operators"][1], before["operators"][1])
        for field in ("resources", "componentBox", "squad"):
            self.assertEqual(self.state.get(field), before.get(field), field)

    def test_no_downgrade_no_unknown_candidate_no_duplicate(self):
        add_operator(self.state, "机械师", elite=2, record_only=True, settle_rewards=False)
        with self.assertRaises(ValueError):
            apply_operator_choices(self.state, observation(elite=1), [{"slot": "1-1"}])
        with self.assertRaises(ValueError):
            apply_operator_choices(self.state, observation(), [{"slot": "9-9"}])
        with self.assertRaises(ValueError):
            apply_operator_choices(self.state, observation(), [{"slot": "1-1"}, {"slot": "1-1"}])

    def test_low_confidence_not_selected_by_default(self):
        self.assertFalse(operator_changes(observation(status="needs_review"), self.state)[0]["selected"])

    def test_invalid_later_selection_cannot_partially_mutate_state(self):
        before = deepcopy(self.state)
        with self.assertRaises(ValueError):
            apply_operator_choices(self.state, observation(), [{"slot": "1-1"}, {"slot": "missing"}])
        self.assertEqual(self.state, before)

    def test_legacy_unpromoted_values_are_equivalent_and_not_rewritten(self):
        add_operator(self.state, "林", elite=0, record_only=True, settle_rewards=False)
        result = observation("林", elite=1)
        self.assertEqual(operator_changes(result, self.state)[0]["change"], "unchanged")
        apply_operator_choices(self.state, result, [{"slot": "1-1"}])
        self.assertEqual(self.state["operators"][0]["elite"], 0)

    def test_ambiguous_target_requires_explicit_selection(self):
        add_operator(self.state, "林", record_only=True, settle_rewards=False)
        duplicate = deepcopy(self.state["operators"][0])
        duplicate["instanceId"] += "-other"
        self.state["operators"].append(duplicate)
        result = observation("林")
        self.assertEqual(operator_changes(result, self.state)[0]["change"], "ambiguous")
        with self.assertRaises(ValueError):
            apply_operator_choices(self.state, result, [{"slot": "1-1"}])
        apply_operator_choices(self.state, result, [{"slot": "1-1", "instanceId": duplicate["instanceId"]}])
        self.assertEqual(self.state["operators"][0]["elite"], 1)
        self.assertEqual(self.state["operators"][1]["elite"], 2)


class OperatorVisionTests(unittest.TestCase):
    def test_blank_and_map_like_inputs_rejected(self):
        self.assertEqual(locate_cards(np.zeros((720, 1280, 3), np.uint8)), [])
        self.assertEqual(locate_cards(np.full((720, 1280, 3), 240, np.uint8)), [])

    def test_all_thirteen_and_single_middle_column(self):
        for columns in ((0, 1, 2), (1,)):
            image = np.full((720, 1280, 3), 240, np.uint8)
            for column in columns:
                for row in range(5 if column == 1 else 4):
                    x, y = 80 + 370 * column, (80 if column == 1 else 130) + row * 110
                    cv2.rectangle(image, (x, y), (x + 300, y + 100), (45, 45, 45), -1)
            self.assertEqual(len(locate_cards(image)), 13 if len(columns) == 3 else 5)

    def test_stage_orange_and_black(self):
        image = np.zeros((100, 300, 3), np.uint8)
        self.assertEqual(_promotion(image, [0, 0, 300, 100])["elite"], 1)
        image[40:60, 5:35] = (0, 150, 255)
        self.assertEqual(_promotion(image, [0, 0, 300, 100])["elite"], 2)

    def test_tsv_quotes_and_punctuation_normalization(self):
        tsv = '5\t1\t1\t1\t1\t1\t0\t5\t20\t20\t90\t凯尔希"思衡托\n'
        self.assertEqual(_tokens(tsv, 0, 40)[0], '凯尔希"思衡托')
        self.assertEqual(normalized_name('凯尔希 · 思衡托'), normalized_name('凯尔希.思衡托'))

    def test_similar_long_names_are_candidates_not_exact_matches(self):
        catalog = {normalized_name('罗比菈塔'): find_operator('罗比菈塔'), normalized_name('宴'): find_operator('宴')}
        self.assertEqual(match_name('罗比持塔', catalog), (find_operator('罗比菈塔'), False))
        self.assertEqual(match_name('受', catalog), (None, False))
        self.assertEqual(match_name('宴', catalog), (find_operator('宴'), True))


class OperatorServiceTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.app = create_app(temp)
        self.client = self.enterContext(TestClient(self.app))
        self.headers = {"X-Fulcrum-Token": self.client.get('/api/session').json()["token"]}
        response = self.post('/api/runs', {"runId": "operator-test", "squadId": "squad_001", "initialOperators": []})
        self.assertEqual(response.status_code, 201, response.text)
        self.loaded = response.json()
        image = cv2.imencode('.png', np.zeros((32, 32, 3), np.uint8))[1].tobytes()
        self.asset = self.client.post('/api/images', headers=self.headers, files={"file": ("squad.png", image, "image/png")}).json()

    def post(self, path, body):
        return self.client.post(path, headers=self.headers, json=body)

    def job(self):
        with patch('fulcrum.vision_operators.OperatorRecognizer.recognize', return_value=observation("林")):
            job = self.post('/api/runs/operator-test/jobs/recognize-operators',
                            {"expectedRevision": self.loaded["revision"], "assetId": self.asset["assetId"]}).json()
            for _ in range(100):
                job = self.client.get('/api/jobs/' + job["jobId"], headers=self.headers).json()
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(.01)
        self.assertEqual(job["status"], "completed", job)
        return job

    def test_recognition_is_read_only_confirmation_and_stale_rejection(self):
        before = deepcopy(self.loaded)
        job = self.job()
        self.assertEqual(self.app.state.store.load("operator-test"), before)
        body = {"expectedRevision": before["revision"], "jobId": job["jobId"], "choices": [{"slot": "1-1"}]}
        response = self.post('/api/runs/operator-test/confirm-operators', body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"]["resources"], before["state"]["resources"])
        self.assertEqual(self.post('/api/runs/operator-test/confirm-operators', body).status_code, 409)

    def test_foreign_job_and_injected_operator_rejected(self):
        job = self.job()
        self.post('/api/runs', {"runId": "other", "squadId": "squad_001", "initialOperators": []})
        body = {"expectedRevision": 1, "jobId": job["jobId"], "choices": [{"slot": "1-1"}]}
        self.assertEqual(self.post('/api/runs/other/confirm-operators', body).status_code, 422)
        body["choices"][0]["operatorId"] = find_operator("林")["id"]
        self.assertEqual(self.post('/api/runs/operator-test/confirm-operators', body).status_code, 422)


if __name__ == '__main__':
    unittest.main()
