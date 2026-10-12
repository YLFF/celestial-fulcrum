from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import unittest

from fulcrum.combat_bonuses import fresh_relic_state, summarize_combat_bonuses


class ArkrogComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = json.loads((Path(__file__).parent / "fixtures/arkrog_30.json").read_text(encoding="utf-8"))
        cls.state = {"opening": {"difficulty": cls.sample["difficulty"], "technologyCombatBonuses": cls.sample["technology"]},
            "relics": [fresh_relic_state(row[0]) for row in cls.sample["relics"]],
            "operators": [{"instanceId": "melee", "name": "银灰", "position": "melee", "profession": "近卫"},
                          {"instanceId": "ranged", "name": "寒芒克洛丝", "position": "ranged", "profession": "狙击"}]}
        cls.report = summarize_combat_bonuses(cls.state, context={"enemyRegionCount": 1})

    @staticmethod
    def rows(view):
        return [row for category in view["categories"] for row in category["rows"]]

    def value(self, view, metric, field, *, side="operator", damage_type=None):
        matches = [row for row in self.rows(view) if row["metric"] == metric and row["side"] == side
                   and row["bucket"] == "constant" and row["tags"].get("damageType") == damage_type]
        self.assertEqual(len(matches), 1, (metric, side, damage_type))
        return matches[0][field]

    def test_all_30_source_terms_match_web_text(self):
        self.assertEqual(len(self.sample["relics"]), 30)
        sources = [(row["metric"], source) for row in self.rows(self.report["operators"][0]) for source in row["sources"]]
        for relic_id, name, checks in self.sample["relics"]:
            with self.subTest(relic=name):
                for metric, operation, expected in checks:
                    candidates = [source for key, source in sources if key == metric and source["id"] == relic_id]
                    self.assertTrue(candidates, metric)
                    for source in candidates:
                        self.assertEqual(source["operation"], operation)
                        if operation == "mechanism":
                            self.assertEqual(source["value"], expected)
                        else:
                            self.assertEqual(Decimal(str(source["value"])), Decimal(expected))

    def test_combined_melee_and_ranged_values_match_observed_web_results(self):
        expected = self.sample["webResults"]
        for index, attack_key in ((0, "meleeAttackFactor"), (1, "rangedAttackFactor")):
            view = self.report["operators"][index]
            for metric, field, key in (("attack", "relativeFactor", attack_key),
                ("defense", "relativeFactor", "defenseFactor"), ("max_hp", "relativeFactor", "hpFactor"),
                ("attack_speed", "flatDelta", "attackSpeedDelta"), ("sp_recovery_per_second", "flatDelta", "naturalSpDelta")):
                self.assertEqual(self.value(view, metric, field), expected[key])
            for damage, key in (("physical", "physicalDamageFactor"), ("arts", "artsDamageFactor"), ("true", "trueDamageFactor")):
                self.assertEqual(self.value(view, "damage_taken", "relativeFactor", side="enemy", damage_type=damage), expected[key])
            for damage, key in (("physical", "displayedPhysicalDodgePercent"), ("arts", "displayedArtsDodgePercent")):
                ratio = Decimal(self.value(view, "dodge_probability", "ratio", damage_type=damage))
                self.assertEqual(ratio, Decimal("0.235"))
                self.assertEqual(int((ratio * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)), expected[key])
        for metric, key in (("attack", "enemyAttackFactor"), ("max_hp", "enemyHpFactor")):
            self.assertEqual(self.value(self.report["global"], metric, "relativeFactor", side="enemy"), expected[key])

    def test_global_does_not_inherit_melee_only_relics(self):
        self.assertEqual(self.value(self.report["global"], "attack", "relativeFactor", side="friendly_unit"), "1.49")


if __name__ == "__main__":
    unittest.main()
