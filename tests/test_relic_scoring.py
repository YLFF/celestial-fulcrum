import json
from pathlib import Path
import tempfile
import unittest

from fulcrum.node_rewards import NodeRewardPoolCatalog
from fulcrum.relic_scoring import CONFIG_PATH, RelicScorer
from scripts.calibrate_node_scores import build_report, pool_probe


class RelicScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = NodeRewardPoolCatalog()
        cls.scorer = RelicScorer(catalog=cls.catalog)

    def test_confirmed_prices_are_per_received_relic(self):
        for context, points in (("node_battle_normal", 100), ("node_battle_elite", 125),
                                ("pool_boss", 200), ("node_battle_savage", 150),
                                ("node_wandering_resident_relic", 100),
                                ("node_wandering_resident_convergence_relic", 100),
                                ("node_battle_normal_invalid_autopsy", 150),
                                ("node_incident_lake_fairy", 225), ("node_duel_right", 125),
                                ("node_incident_cave_treasure", 100), ("node_wish_relic", 100),
                                ("node_wish_relic_advanced", 150),
                                ("node_story_curiosity_and_death", 150), ("node_hidden_collectible", 100)):
            self.assertEqual(self.scorer.pool_score(context), points)
        self.assertEqual(self.scorer.pool_score("node_incident_lake_fairy_emergency"), 225)
        self.assertEqual(self.scorer.pool_score("node_incident_lake_fairy_direct"), 225)

    def test_membership_only_hidden_pool_does_not_require_fabricated_probabilities(self):
        context = self.catalog.get("node_hidden_collectible")
        self.assertEqual(len(context["members"]), 26)
        self.assertTrue(all(row["probability"] is None for row in context["members"]))
        probe = pool_probe(self.catalog, context["id"], relic_scorer=self.scorer)
        self.assertEqual(probe["expectedBest"], 100)
        self.assertEqual(probe["assumption"], "configured_per_received_relic_points")
        for event_id in ("encounter_013", "encounter_014", "encounter_015", "encounter_016"):
            self.assertEqual(self.scorer.event_pool(event_id), context["id"])

    def test_wish_cash_boundary_and_refresh_cost_are_applied_once(self):
        for cash in (0, 3, 3.99):
            result = self.scorer.wish_score(cash)
            self.assertEqual(result["points"], 100)
            self.assertEqual(result["cashCost"], 0)
            self.assertEqual(result["cashAfter"], cash)
        for cash in (4, 50):
            result = self.scorer.wish_score(cash)
            self.assertEqual(result["relicPoints"], 150)
            self.assertEqual(result["cashCostPoints"], 32)
            self.assertEqual(result["points"], 118)
            self.assertEqual(result["cashAfter"], cash - 4)
        for cash in (-1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                self.scorer.wish_score(cash)

    def test_pool_proxy_already_contains_two_choice_value(self):
        for context, points in (("pool_boss", 200), ("node_wish_relic_advanced", 150)):
            probe = pool_probe(self.catalog, context, relic_scorer=self.scorer)
            self.assertEqual(probe["expectedBest"], points)
            self.assertEqual(probe["assumption"], "configured_per_received_relic_points")

    def test_report_uses_correct_pools_without_adding_normal_relic_rewards(self):
        report = build_report()
        for row in report["combat"]:
            expected = {"作战": 0, "紧急作战": 125, "险路恶敌": 200}[row["name"]]
            self.assertEqual(row["met"]["parts"]["relics"], expected)
            if row["unmet"]:
                self.assertEqual(row["unmet"]["parts"]["relics"], expected)
        for row in report["specialBattles"]:
            expected = 150 if row["name"] in ("枯枝", "败叶", "无效验尸") else 100
            self.assertEqual(row["met"]["parts"]["relics"], expected)
        self.assertTrue(report["nodes"][6]["score"].startswith("118.00"))
        self.assertTrue(report["nodes"][11]["score"].startswith("假节点150"))
        self.assertTrue(build_report(cash=3)["nodes"][6]["score"].startswith("100.00"))
        self.assertTrue(build_report(painted_perro=1)["nodes"][6]["score"].startswith("218.00"))

    def test_condition_override_and_custom_config_flow_into_calibration(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config["contextPoints"]["node_incident_lake_fairy_direct"] = 300
        config["poolPoints"]["node_hidden_collectible"] = 200
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scores.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            scorer = RelicScorer(path, catalog=self.catalog)
            self.assertEqual(scorer.pool_score("node_incident_lake_fairy_emergency"), 225)
            self.assertEqual(scorer.pool_score("node_incident_lake_fairy_direct"), 300)
            before, after = build_report(), build_report(relic_scores_path=path)
            old = {e["id"]: e for e in before["encounters"]["met"]["events"]}
            new = {e["id"]: e for e in after["encounters"]["met"]["events"]}
            self.assertAlmostEqual(new["encounter_017"]["knownPoints"] - old["encounter_017"]["knownPoints"], 15)
            for event_id in ("encounter_014", "encounter_015"):
                self.assertAlmostEqual(new[event_id]["knownPoints"] - old[event_id]["knownPoints"], 300)

    def test_invalid_configuration_cannot_be_silently_used(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scores.json"
            for points in (-1, True, float("nan"), float("inf")):
                config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                config["poolPoints"]["pool_boss"] = points
                path.write_text(json.dumps(config), encoding="utf-8")
                with self.assertRaises(ValueError):
                    RelicScorer(path, catalog=self.catalog)
            config["poolPoints"] = {"node_duel_left": 100}
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ValueError):
                RelicScorer(path, catalog=self.catalog)


if __name__ == "__main__":
    unittest.main()
