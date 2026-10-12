from copy import deepcopy
import unittest

from fulcrum.component_box import add_component
from fulcrum.node_scoring import SnapshotScorer
from fulcrum.route_planner import RoutePlanner
from tests.test_dystopia_scoring import advance, dystopia
from tests.test_route_planner import make_map, state
from tests.test_snapshot_scoring import context


class RewardOverlayTests(unittest.TestCase):
    def test_fruit_pool_cash_equivalence_overlays_resident_without_changing_inventory_values(self):
        nodes = [{"id": "a", "categoryId": "node_type_007", "confirmedMarkIds": ["node_mark_001", "node_mark_007"]},
                 {"id": "b", "categoryId": "node_type_007", "confirmedMarkIds": ["node_mark_001"]}]
        c = context()
        before = deepcopy(c)
        scorer = SnapshotScorer(nodes, c, state(2))
        fruit = scorer.values["a"]["fruitReward"]
        expected = (14 * 400 + 18 * 192 + 6 * 256) / 38
        self.assertAlmostEqual(fruit["points"], expected)
        self.assertAlmostEqual(scorer.values["a"]["points"] - scorer.values["b"]["points"], expected)
        self.assertEqual(scorer.values["a"]["expectedCashDelta"], scorer.values["b"]["expectedCashDelta"])
        self.assertEqual(scorer.values["a"]["missingTerms"], [])
        self.assertEqual(c, before)

    def test_fruit_bonus_participates_in_route_and_is_once_only(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_020"), (2, 0, "node_type_015")],
                     [("0,0", "1,0"), ("1,0", "2,0")])
        m["nodes"][1]["confirmedMarkIds"] = ["node_mark_007"]
        s = state(3, scoringContext=context("I"), topN=5)
        result = RoutePlanner(m).plan(s)
        self.assertTrue(result["routes"])
        self.assertIn("fruitMarkNatural", result["routes"][0]["steps"][0]["scoreBreakdown"]["nodeTerms"][0]["parts"])
        scorer = SnapshotScorer(m["nodes"], s["scoringContext"], s)
        self.assertEqual(advance(scorer, ["1,0"], done=["1,0"])["nodeValue"], 0)

    def test_remembrance_legality_and_fallback(self):
        for cost in ("action", "processing", "relic", None):
            c = context("IV")
            if cost == "processing":
                add_component(c["componentBox"], "component_014")
                add_component(c["componentBox"], "component_015")
            if cost == "relic":
                c["relics"] = [{"id": "relic_210"}]
            scorer = SnapshotScorer([], c, state(3 if cost == "action" else 1))
            score = scorer.encounter("encounter_012")
            if cost:
                self.assertEqual(score["parts"]["remembrance"], 1000)
                self.assertEqual(score["plannedOption"], "remembrance")
            else:
                self.assertEqual(score["plannedOption"], "actionGain1")
        add_component(c["componentBox"], "component_012")
        scorer = SnapshotScorer([], c, state(1))
        self.assertEqual(scorer.encounter("encounter_012")["actionGainEstimate"], 5)

    def test_healing_heart_chooses_highest_legal_option_not_sum(self):
        c = context("IV")
        add_component(c["componentBox"], "component_012")
        scorer = SnapshotScorer([], c, state(3))
        scorer.action_queue = [1000] * 20
        score = scorer.encounter("encounter_012")
        self.assertEqual(score["points"], scorer.action_value(5))
        self.assertEqual(score["plannedOption"], "actionGain5")
        self.assertEqual(len(score["legalOptions"]), 3)

    def test_treehole_unknown_battle_averages_both_scores_and_cash(self):
        c = context("III-treehole", options={"teamThresholdOverride": "insufficient"})
        scorer = SnapshotScorer([], c, state(2))
        for mode in ("normal", "emergency"):
            combined = scorer.battle(mode)
            rows = [scorer.battle(mode, area=area) for area in ("III", "IV")]
            for key in ("points", "expectedCashDelta", "experienceAward"):
                self.assertAlmostEqual(combined[key], sum(row[key] for row in rows) / 2)
            self.assertEqual(combined["missingTerms"], [])
            self.assertEqual([row["areaKey"] for row in combined["battleOutcomes"]], ["III", "IV"])
        stage = next(name for name, area in scorer.battles.data["stageRegions"].items() if area == "IV")
        self.assertEqual(scorer.battle("normal", stage=stage)["points"], scorer.battle("normal", stage=stage, area="IV")["points"])

    def test_stranger_companion_cash_uses_floor_emergency_with_unverified_provenance(self):
        for area in ("III", "IV", "IV-treehole"):
            scorer = SnapshotScorer([], context(area), state(2))
            score = scorer.encounter("encounter_013")
            expected = scorer.battles.resolve(area_key=area.split("-")[0], mode="emergency")["originiumIngot"]["value"]
            self.assertEqual(score["expectedCashDelta"], expected)
            self.assertEqual(score["cashReference"]["verificationStatus"], "unverified")
            self.assertNotIn("该战斗的随机现金分布尚未量化", score["missingTerms"])

    def test_utopia_city_counts_composite_once_and_updates_prefix_economy(self):
        c = context("III-treehole")
        nodes = [{"id": "a", "categoryId": "node_type_006", "encounterId": "encounter_002"},
                 {"id": "b", "categoryId": "unknown_mystery", "categoryProbabilities": {"node_type_007": 1}}]
        ordinary = SnapshotScorer(nodes, c, state(2))
        scorer = SnapshotScorer(nodes, c, state(2, utopiaId="utopia_007"))
        for key in ("a", "b"):
            self.assertEqual(scorer.values[key]["points"] - ordinary.values[key]["points"], 80)
            self.assertEqual(scorer.values[key]["expectedCashDelta"] - ordinary.values[key]["expectedCashDelta"], 10)
        first = advance(scorer, ["a"], cash=0)
        self.assertEqual(first["merchantTransition"]["cashAfter"], 10)
        self.assertEqual(advance(scorer, ["a"], done=["a"])["nodeValue"], 0)
        main = SnapshotScorer(nodes, context("III"), state(2, utopiaId="utopia_007"))
        self.assertEqual(main.values["a"]["points"], 0)

    def test_utopia_city_does_not_repeat_cash_when_revisiting_shop(self):
        nodes = [{"id": "a", "categoryId": "node_type_004"}]
        scorer = SnapshotScorer(nodes, context("III-treehole"), state(2, utopiaId="utopia_007"))
        first = advance(scorer, ["a"], cash=10)
        again = advance(scorer, ["a"], done=["a"], cash=10)
        self.assertEqual(first["nodeTerms"][0]["parts"]["utopiaCash"], 80)
        self.assertEqual(first["merchantTransition"]["cashAfter"], 10)
        self.assertNotIn("utopiaCash", again["nodeTerms"][0]["parts"])
        self.assertEqual(again["merchantTransition"]["cashAfter"], 0)

    def test_utopia_city_conditional_mark_branch_does_not_duplicate_completion_cash(self):
        c = context("IV-treehole")
        c["prediction"] = {"endingCategoryMarks": {"a": [{"markId": "node_mark_006", "probability": .5}]}}
        nodes = [{"id": "a", "categoryId": "node_type_008"}]
        plain = SnapshotScorer(nodes, c, state(2))
        scorer = SnapshotScorer(nodes, c, state(2, utopiaId="utopia_007"))
        self.assertEqual(scorer.values["a"]["points"] - plain.values["a"]["points"], 80)
        self.assertEqual(scorer.values["a"]["expectedCashDelta"] - plain.values["a"]["expectedCashDelta"], 10)

    def test_utopia_exchange_applies_only_to_loss_gain_branch(self):
        nodes = [{"id": "a", "categoryId": "unknown_mystery",
                  "categoryProbabilities": {"node_type_007": .5, "node_type_008": .5}}]
        plain = SnapshotScorer(nodes, context("IV-treehole"), state(2))
        scorer = SnapshotScorer(nodes, context("IV-treehole"), state(2, utopiaId="utopia_009"))
        self.assertEqual(scorer.values["a"]["points"] - plain.values["a"]["points"], 20)
        self.assertEqual(scorer.values["a"]["expectedCashDelta"] - plain.values["a"]["expectedCashDelta"], 2.5)

    def test_soil_coverage_and_all_battle_categories(self):
        nodes = [{"id": str(index), "categoryId": category} for index, category in enumerate(
            ("node_type_001", "node_type_002", "node_type_003", "node_type_011", "node_type_019", "node_type_021"))]
        c = context()
        plain = SnapshotScorer(nodes, c, state(20))
        d = dystopia("dystopia_014", ideology="dystopia_008", source=None, covered=[row["id"] for row in nodes[:-1]])
        soil = SnapshotScorer(nodes, c, state(20, dystopia=d))
        extra = soil.pool("hopeful_fruits")
        for node in nodes:
            key = node["id"]
            expected = extra + 32 if key in d["affectedNodeIds"] else 0
            self.assertAlmostEqual(soil.values[key]["points"] - plain.values[key]["points"], expected)
        first = advance(soil, ["0"])
        self.assertAlmostEqual(first["nodeValue"], soil.values["0"]["points"])
        self.assertEqual(advance(soil, ["0"], done=["0"])["nodeValue"], 32)

    def test_soil_event_battle_chances_and_unknown_types_are_weighted(self):
        nodes = [{"id": "a", "categoryId": "unknown_ferocity", "categoryProbabilities": {"node_type_001": 2, "node_type_002": 1}},
                 {"id": "b", "categoryId": "node_type_006", "encounterId": "encounter_017"},
                 {"id": "c", "categoryId": "node_type_006", "encounterId": "encounter_018"},
                 {"id": "d", "categoryId": "node_type_006", "encounterId": "encounter_006"},
                 {"id": "e", "categoryId": "node_type_006", "encounterId": "encounter_013"}]
        plain = SnapshotScorer(nodes, context(), state(20))
        d = dystopia("dystopia_014", ideology="dystopia_008", source=None, covered=[row["id"] for row in nodes])
        soil = SnapshotScorer(nodes, context(), state(20, dystopia=d))
        extra = soil.pool("hopeful_fruits")
        for key, chance in (("a", 1), ("b", .8), ("c", .5), ("d", 0), ("e", 1)):
            self.assertAlmostEqual(soil.values[key]["points"] - plain.values[key]["points"], chance * extra + 32)
        ordinary_dystopia = SnapshotScorer(nodes, context(), state(20, dystopia=dystopia("dystopia_014", covered=["a"])))
        self.assertAlmostEqual(ordinary_dystopia.values["a"]["points"] - plain.values["a"]["points"], 32)


if __name__ == "__main__":
    unittest.main()
