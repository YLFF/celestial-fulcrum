"""Offline reward lookup, span parsing, and configurable bonus checks."""

import unittest

from fulcrum.battle_rewards import BattleRewardCatalog
from scripts.extract_prts_battle_rewards import PageTables, expanded_rows, money_value, extract_data


class BattleRewardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = BattleRewardCatalog()

    def test_base_and_full_technology_are_separate(self) -> None:
        full = self.catalog.resolve(area_key="III", mode="normal")
        base = self.catalog.resolve(area_key="III", mode="normal", experience_multipliers=[])
        partial = self.catalog.resolve(area_key="III", mode="normal", experience_multipliers=["1.1"])
        self.assertEqual((base["experienceAward"], partial["experienceAward"], full["experienceAward"]), (13, 14, 17))

    def test_round_once_after_all_multipliers(self) -> None:
        result = self.catalog.resolve(area_key="I", mode="normal", experience_multipliers=["1.1", "1.1", "1.1", "1.5"])
        self.assertEqual(result["experienceAward"], 19)
        with self.assertRaises(ValueError):
            self.catalog.resolve(area_key="I", mode="normal", experience_multipliers=["-1"])

    def test_treehole_uses_actual_stage_floor(self) -> None:
        third = self.catalog.resolve(area_key="III-treehole", mode="emergency", stage_name="预算否决")
        fourth = self.catalog.resolve(area_key="III-treehole", mode="emergency", stage_name="选边站")
        self.assertEqual((third["experienceAward"], fourth["experienceAward"]), (33, 39))
        self.assertEqual(fourth["resolvedRegion"], "IV")
        with self.assertRaisesRegex(ValueError, "actual stage"):
            self.catalog.resolve(area_key="III-treehole", mode="normal")

    def test_vi_source_area_zero_has_correct_money(self) -> None:
        result = self.catalog.resolve(area_key="V-treehole", mode="normal", stage_name="命运共享")
        self.assertEqual(result["resolvedRegion"], "VI")
        self.assertEqual(result["originiumIngot"], {"kind": "fixed", "value": 5})
        for mode in ("boss", "bossPursuit"):
            terminal = self.catalog.resolve(area_key="VI", mode=mode)
            self.assertEqual(terminal["experienceAward"], 0)
            self.assertEqual(terminal["originiumIngot"]["value"], 0)
            self.assertEqual(terminal["terminalRewardOverride"]["rewardStatus"], "no_rewards_current_version")

    def test_special_overrides_are_variant_specific(self) -> None:
        normal = self.catalog.resolve(area_key="III-treehole", mode="specialNormal", stage_name="合伙人会议")
        emergency = self.catalog.resolve(area_key="III-treehole", mode="specialEmergency", stage_name="合伙人会议")
        self.assertEqual((normal["experienceAward"], emergency["experienceAward"]), (33, 47))
        self.assertEqual(emergency["originiumIngot"]["value"], 3)

    def test_unknown_and_ranged_money_are_not_invented(self) -> None:
        autopsy = self.catalog.resolve(area_key="V", mode="specialNormal", stage_name="无效验尸")
        homesick = self.catalog.resolve(area_key="I", mode="specialNormal", stage_name="陌生旅伴")
        self.assertEqual(autopsy["originiumIngot"], {"kind": "fixed", "value": 5})
        self.assertEqual(autopsy["experienceAward"], 47)
        self.assertEqual((autopsy["relicCount"], autopsy["componentCount"], autopsy["ticketCount"]), (1, 1, 1))
        self.assertTrue(autopsy["provisional"])
        self.assertEqual(homesick["originiumIngot"], {"kind": "range", "min": 2, "max": 3, "probabilities": None})

    def test_same_stage_name_different_battle_context(self) -> None:
        event = self.catalog.resolve(area_key="IV", mode="specialNormal", stage_name="“闹乐”")
        pursuit = self.catalog.resolve(area_key="IV", mode="pursuit", stage_name="“闹乐”")
        self.assertEqual((event["experienceAward"], event["originiumIngot"]["value"]), (39, 3))
        self.assertEqual((pursuit["experienceAward"], pursuit["originiumIngot"]["value"]), (0, 0))

    def test_wrong_region_and_unavailable_mode_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.catalog.resolve(area_key="I", mode="normal", stage_name="预算否决")
        with self.assertRaises(ValueError):
            self.catalog.resolve(area_key="II", mode="boss")
        with self.assertRaises(ValueError):
            self.catalog.resolve(area_key="V", mode="pursuit")

    def test_full_technology_display_matches_calculation(self) -> None:
        self.assertEqual(len(self.catalog.data["stageRegions"]), 31)
        for region, modes in self.catalog.data["regionRewards"].items():
            for mode, row in modes.items():
                if row:
                    result = self.catalog.resolve(area_key=region, mode=mode)
                    expected = result["terminalRewardOverride"]["experience"] if result.get("terminalRewardOverride") else row["experience"]["fullTechnology"]
                    self.assertEqual(result["experienceAward"], expected)


class TableExtractionTests(unittest.TestCase):
    def test_adjacent_spans_preserve_variants_and_links(self) -> None:
        parser = PageTables()
        parser.feed('<table><tr><td><span class="is6-exp">10</span><span class="is6-exp is-fulltech">13</span>'
                    '<a href="/w/stage" title="ISW-NO 测试">测试</a></td></tr></table>')
        cell = parser.tables[0]["rows"][0][0]
        self.assertEqual(cell["experience"], {"base": 10, "fullTechnology": 13})
        self.assertEqual(cell["text"], "10 13 测试")
        self.assertEqual(cell["links"][0]["title"], "ISW-NO 测试")

    def test_rowspan_and_colspan_keep_inherited_cells(self) -> None:
        parser = PageTables()
        parser.feed('<table><tr><td rowspan="2" colspan="2">A</td><td>B</td></tr><tr><td>C</td></tr></table>')
        rows = expanded_rows(parser.tables[0])
        self.assertEqual([[cell["text"] for cell in row] for row in rows], [["A", "A", "B"], ["A", "A", "C"]])

    def test_invalid_structure_fails_without_guessing(self) -> None:
        with self.assertRaises(ValueError):
            extract_data("<table><tr><td>not a reward table</td></tr></table>")
        with self.assertRaises(ValueError):
            money_value({"text": "unexpected"})


if __name__ == "__main__":
    unittest.main()
