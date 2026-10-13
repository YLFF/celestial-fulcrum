from copy import deepcopy
import unittest

from fulcrum.combat_bonuses import summarize_combat_bonuses
from fulcrum.node_scoring import SnapshotScorer
from fulcrum.team_status import team_status, threshold_floor
from fulcrum.playtime_route import route_inputs
from fulcrum.playtime_state import merge_map_observation, new_playtime
from tests.test_playtime_prediction import chain_map, treehole_map
from tests.test_route_planner import state
from tests.test_snapshot_scoring import context


def operator(index, rarity=6, elite=2, source="normal"):
    return {"instanceId": str(index), "name": f"干员{index}", "source": source,
            "rarity": rarity, "elite": elite, "remainingBattles": None}


def snapshot(operators, relics=(), components=0, technology=True):
    return {"opening": {"difficulty": 15, "technologyCombatBonuses": {
        "attackPercent": 20 if technology else 0, "defensePercent": 20 if technology else 0,
        "maxHpPercent": 25 if technology else 0}}, "operators": operators, "relics": list(relics),
        "componentBox": {"items": [{}] * components}}


class TeamPowerTests(unittest.TestCase):
    def test_star_and_promotion_weights_and_emergency_exclusion(self):
        ops = [operator(1), operator(2, elite=1), operator(3, rarity=5), operator(4, rarity=5, elite=1),
               operator(5, rarity=4), operator(6, rarity=3, elite=0), operator(7, source="assistance")]
        result = team_status(ops, 2, combat_state=snapshot(ops, technology=False))
        self.assertEqual([row["weight"] for row in result["operatorContributions"]], [1, .7, .5, .3, .2, .2])
        self.assertEqual(result["weightedOperators"], 2.9)
        self.assertEqual(result["power"], 2.9)
        self.assertFalse(result["met"])

    def test_product_of_four_current_global_attributes(self):
        ops = [operator(1), operator(2, elite=1)]
        s = snapshot(ops, relics=[{"id": "relic_199"}], components=8)
        before = deepcopy(s)
        result = team_status(ops, "II", combat_state=s)
        self.assertEqual(result["multipliers"], {"outside_battle_max_hp": 1.25, "inside_battle_max_hp": 1.64,
                                                "outside_battle_attack": 1.2, "inside_battle_attack": 1.64})
        self.assertAlmostEqual(result["power"], 1.7 * 1.25 * 1.64 * 1.2 * 1.64)
        self.assertTrue(result["met"])
        self.assertEqual(s, before)

    def test_thresholds_only_depend_on_main_floor(self):
        for area, floor in (("I", 1), ("II", 2), ("III-treehole", 3), ("IV-remembrance", 4),
                            ("IV-treehole", 4), ("V-treehole", 5), ("VI", 6)):
            self.assertEqual(threshold_floor(area), floor)
            for squad in (None, "squad_005", "squad_012"):
                result = team_status([], area, squad)
                self.assertEqual(result["required"]["power"], [0, 5, 6, 8, 10, 13][floor - 1])
        for invalid in (True, 0, 7, "VII", "treehole"):
            with self.assertRaises(ValueError):
                threshold_floor(invalid)

    def test_exact_boundary_and_manual_override_do_not_change_facts(self):
        ops = [operator(i) for i in range(5)]
        s = snapshot(ops, technology=False)
        auto = team_status(ops, 2, combat_state=s)
        forced = team_status(ops, 2, options={"teamThresholdOverride": "insufficient"}, combat_state=s)
        self.assertTrue(auto["automaticMet"])
        self.assertTrue(forced["automaticMet"])
        self.assertFalse(forced["met"])
        self.assertEqual(forced["power"], auto["power"])
        self.assertEqual(forced["deficits"], auto["deficits"])

    def test_scoped_skill_peak_and_environment_do_not_raise_global_threshold(self):
        ops = [operator(1)]
        s = snapshot(ops, relics=[{"id": "relic_052"}, {"id": "relic_051"}, {"id": "relic_126"}])
        s["operators"][0].update(position="melee", profession="狙击", subprofession="炮手")
        before = team_status(ops, 2, combat_state=s)
        self.assertEqual(before["attributeFactor"], 1.5)
        s["areas"] = {"II": {"dystopia": {"active": True, "ideologyId": "dystopia_001"}}}
        self.assertEqual(team_status(ops, 2, combat_state=s)["power"], before["power"])

    def test_missing_stack_is_partial_not_a_guessed_peak(self):
        ops = [operator(1)]
        s = snapshot(ops, relics=[{"id": "relic_035"}])
        result = team_status(ops, 2, combat_state=s)
        self.assertGreater(result["pendingAttributeTerms"], 0)

    def test_api_and_scorer_share_formula_and_hope_gap(self):
        c = context("II")
        c["operators"] = [operator(1)]
        c["resources"]["hope"] = 0
        scorer = SnapshotScorer([], c, state(2))
        report = summarize_combat_bonuses(c, include_operator_views=False)
        status = team_status(c["operators"], "II", attribute_summary=report["global"]["attributeSummary"])
        self.assertEqual(status["power"], scorer.threshold["power"])
        self.assertAlmostEqual(scorer.hope_deficit, (5 / 1.5 - 1) * 10)
        self.assertGreater(scorer.battle("normal")["parts"]["experience"], 0)
        c["resources"]["hope"] = 100
        self.assertEqual(SnapshotScorer([], c, state(2)).hope_deficit, 0)

    def test_route_adapter_preserves_automatic_relic_counter_context(self):
        s = new_playtime("automatic-layer-power")
        s["operators"] = [operator(i) for i in range(3)]
        s["relics"] = [{"id": relic_id} for relic_id in ("relic_033", "relic_034", "relic_035")]
        for area, observed in (("III", chain_map(3)), ("III-treehole", treehole_map(3)),
                               ("IV-treehole", treehole_map(4)), ("IV-remembrance", chain_map(4))):
            with self.subTest(area=area):
                instance = merge_map_observation(s, area, observed, player_position="0,0")
                instance["actionPoints"] = 3
                before = deepcopy(s)
                map_result, inputs = route_inputs(s)
                scorer = SnapshotScorer(map_result["nodes"], inputs["scoringContext"], inputs)
                actual = team_status(s["operators"], area, combat_state=s)
                self.assertEqual({key: scorer.threshold[key] for key in actual}, actual)
                self.assertEqual(actual["pendingAttributeTerms"], 0)
                self.assertEqual(s, before)
                self.assertTrue(all(set(slot) == {"activeInstanceId"}
                                    for slot in inputs["scoringContext"]["areas"].values()))


if __name__ == "__main__":
    unittest.main()
