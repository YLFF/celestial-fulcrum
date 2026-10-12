from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from fulcrum.diagnostics import localize_result, message, public_error
from fulcrum.component_box import catalog as component_catalog
from fulcrum.node_scoring import SnapshotScorer
from fulcrum.scoring_calibration import component_reference_points, green_merchant_base_score, team_threshold
from fulcrum.scoring_profile import PROFILE, PROFILE_PATH, load_profile
from tests.test_snapshot_scoring import context
from tests.test_route_planner import make_map, state
from fulcrum.route_planner import RoutePlanner
from fulcrum.service.app import create_app


class ScoringProfileTests(unittest.TestCase):
    def test_parameter_notes_cover_configuration_without_changing_weights(self):
        notes = PROFILE["parameterNotes"]

        def check(values, explanations, path):
            if isinstance(explanations, str):
                self.assertTrue(any("\u4e00" <= c <= "\u9fff" for c in explanations), path)
                return
            self.assertIsInstance(explanations, dict, path)
            for key, value in values.items():
                self.assertIn(key, explanations, f"{path}.{key}")
                check(value, explanations[key], f"{path}.{key}")

        for section in ("resources", "teamThresholds", "dualSquadThresholdAdditions", "components", "tickets",
                        "events", "merchants", "information", "exits", "overlays", "search", "policies"):
            check(PROFILE[section], notes[section], section)
        self.assertEqual(notes["componentNames"], {key: entry["name"] for key, entry in component_catalog().items()})
        values = json.loads((PROFILE_PATH.parent / "relics.json").read_text(encoding="utf-8"))
        for key in ("defaultPoints", "poolPoints", "contextPoints", "fixedRelicPoints"):
            check(values[key], values["parameterNotes"][key], key)

    def test_forced_insufficient_does_not_invent_hope_deficit_on_floor_one(self):
        scorer = SnapshotScorer([{"id": "a", "categoryId": "node_type_001"}],
                               context("I", options={"teamThresholdOverride": "insufficient"}), state(1))
        self.assertFalse(scorer.threshold["met"])
        self.assertEqual(scorer.threshold["hopeDeficit"], 0)
        self.assertGreater(scorer.values["a"]["experienceAward"], 0)
        self.assertEqual(scorer.values["a"]["parts"]["experience"], 0)

    def test_configuration_inventory_and_single_source(self):
        root = PROFILE_PATH.parents[3]
        catalog = json.loads((root / "data/scoring/catalog.json").read_text(encoding="utf-8"))
        for path in (*catalog["files"].values(), *catalog["relatedReadOnlyData"].values()):
            self.assertTrue((root / path).is_file(), path)
        self.assertFalse((root / "data/blackflow_relic_scoring.json").exists())
        rules = json.loads((root / "data/blackflow_reward_rules.json").read_text(encoding="utf-8"))
        self.assertNotIn("scoring", rules)
        self.assertEqual(load_profile(), PROFILE)
        self.assertEqual(component_reference_points("component_001"), 250)
        self.assertAlmostEqual(green_merchant_base_score(20), 200)

    def test_weight_changes_are_consumed_not_only_documented(self):
        with patch.dict(PROFILE["events"], exchangeOpportunityPoints=333):
            scorer = SnapshotScorer([{"id": "a", "categoryId": "node_type_008"}], context(), state(2))
            self.assertEqual(scorer.values["a"]["points"], 333)
        with patch.dict(PROFILE["dualSquadThresholdAdditions"], {"2": [2, 2, 0]}):
            self.assertEqual(team_threshold(2, "squad_005")["elite2SixStars"], 3)

    def test_invalid_profile_rejected(self):
        changes = [lambda row: row["resources"].update(cashPoints=-1),
                   lambda row: row["search"].update(defaultMaxStates=False),
                   lambda row: row["overlays"]["unconfirmedTreeholeBattle"].update(entryLayerProbability=.8),
                   lambda row: row["components"]["fixedPoints"].update(component_001=float("nan")),
                   lambda row: row.update(teamThresholds=[])]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            for change in changes:
                row = deepcopy(PROFILE)
                change(row)
                path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_profile(path)

    def test_treehole_return_and_final_route_settlement_are_zero(self):
        scorer = SnapshotScorer([{"id": "a", "categoryId": "start"}], context("III-treehole"), state(1))
        returned = scorer.terminal("a", 0, pursuit=True)
        self.assertEqual(returned["points"], 0)
        self.assertEqual(returned["missingTerms"], [])
        self.assertEqual(returned["parts"], {})
        self.assertNotIn("treeholeReturnPoints", PROFILE["exits"])
        m = make_map([(0, 0, "start"), (1, 0, "node_type_003")], [("0,0", "1,0")])
        result = RoutePlanner(m).plan(state(1, scoringContext=context("VI")))
        self.assertTrue(result["routes"])
        self.assertEqual(result["routes"][0]["metrics"]["weightedValue"], 0)
        final = SnapshotScorer([{"id": "a", "categoryId": "node_type_003"}], context("VI"), state(1))
        self.assertEqual(final.battle("boss")["points"], 0)
        self.assertEqual(final.battle("boss")["experienceAward"], 0)

    def test_http_messages_are_chinese(self):
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(directory)) as client:
            responses = [client.get("/api/runs"), client.post("/api/session"), client.get("/api/no-such-route")]
            token = client.get("/api/session").json()["token"]
            client.headers["X-Fulcrum-Token"] = token
            responses.append(client.post("/api/runs", json={"difficulty": -1}))
            for response in responses:
                self.assertGreaterEqual(response.status_code, 400)
                self.assertTrue(any("\u4e00" <= c <= "\u9fff" for c in response.json()["detail"]))

    def test_report_and_dynamic_messages_are_chinese(self):
        scorer = SnapshotScorer([{"id": "a", "categoryId": None}], context(), state(1))
        report = scorer.report()
        for text in (*report["assumptions"], *report["warnings"], *report["missingTermsByNode"]["a"]):
            self.assertTrue(any("\u4e00" <= c <= "\u9fff" for c in text), text)
        self.assertIn("未量化", message("event not priced: encounter_099"))
        self.assertIn("不加入", message("item-1 is random; excluded from guaranteed routes"))
        self.assertIn("上限", message("confirmed combat count 4 exceeds the floor maximum 3; the count cap is not used to exclude further candidates"))
        self.assertIn("不合法", public_error(ValueError("remainingUses must be nonnegative")))
        translated = localize_result({"child": {"missingTerms": ["empty event penalty pending"]}})
        self.assertEqual(translated["child"]["missingTerms"], ["空过事件的惩罚分尚未设置"])
        self.assertEqual(localize_result({"modelLimitations": ["free-visit target consumption not simulated; confirm and replan"]}),
                         {"modelLimitations": []})


if __name__ == "__main__":
    unittest.main()
