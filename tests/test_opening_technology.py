"""Technology attributes stay separate from opening resources and other bonuses."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from fulcrum.opening import DEFAULT_TECHNOLOGY_COMBAT_BONUSES, normalize_technology_combat_bonuses
from fulcrum.playtime_state import new_playtime, validate_playtime
from fulcrum.playtime_view import render_basic_section


ROOT = Path(__file__).resolve().parents[1]


class OpeningTechnologyTests(unittest.TestCase):
    def test_lookout_split_defaults_and_validation(self) -> None:
        state = new_playtime("split-default")
        self.assertTrue(state["opening"]["lookoutSplitUnlocked"])
        self.assertIn("| 羽瞰点局外科技：分裂 | 已解锁 |", render_basic_section(state))
        disabled = new_playtime("split-disabled", lookout_split_unlocked=False)
        validate_playtime(disabled)
        self.assertFalse(disabled["opening"]["lookoutSplitUnlocked"])
        self.assertIn("| 羽瞰点局外科技：分裂 | 未解锁 |", render_basic_section(disabled))
        for invalid in (None, 0, "false"):
            with self.assertRaises(ValueError):
                new_playtime("invalid-split", lookout_split_unlocked=invalid)
            state["opening"]["lookoutSplitUnlocked"] = invalid
            with self.assertRaises(ValueError):
                validate_playtime(state)

    def test_default_bonuses_are_persisted_and_rendered(self) -> None:
        state = new_playtime("default-tech")
        validate_playtime(state)
        self.assertEqual(state["opening"]["technologyCombatBonuses"], DEFAULT_TECHNOLOGY_COMBAT_BONUSES)
        reading_view = render_basic_section(state)
        for field, value in (("攻击力", 20), ("防御力", 20), ("生命值", 25)):
            self.assertIn(f"| 局外科技{field}加成 | +{value}% |", reading_view)

    def test_partial_override_does_not_change_resources_or_other_choices(self) -> None:
        kwargs = {"difficulty": 15, "squad_id": "squad_014", "cocoons": {"猫": 2, "天马": 1}}
        original = new_playtime("original-tech", **kwargs)
        customized = new_playtime("custom-tech", **kwargs, technology_combat_bonuses={"attackPercent": 8.5})
        validate_playtime(customized)
        self.assertEqual(customized["opening"]["technologyCombatBonuses"],
                         {"attackPercent": 8.5, "defensePercent": 20, "maxHpPercent": 25})
        for field in ("resources", "componentBox", "operators", "relics"):
            self.assertEqual(customized[field], original[field])
        self.assertIn("三项属性自定义", render_basic_section(customized))
        self.assertIn("+8.5%", render_basic_section(customized))
        self.assertEqual(customized["opening"]["difficulty"], 15)
        self.assertEqual(customized["opening"]["cocoons"], original["opening"]["cocoons"])

    def test_zero_is_kept_and_defaults_are_not_shared(self) -> None:
        bonuses = {"attackPercent": 0, "defensePercent": 0, "maxHpPercent": 0}
        state = new_playtime("no-tech", technology_combat_bonuses=bonuses)
        bonuses["attackPercent"] = 99
        self.assertEqual(state["opening"]["technologyCombatBonuses"]["attackPercent"], 0)
        state["opening"]["technologyCombatBonuses"]["defensePercent"] = 99
        self.assertEqual(new_playtime("default-again")["opening"]["technologyCombatBonuses"]["defensePercent"], 20)

    def test_invalid_overrides_are_rejected(self) -> None:
        for value in (True, "20", -1, float("nan"), float("inf"), 10 ** 1000):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ValueError):
                    normalize_technology_combat_bonuses({"attackPercent": value})
        for bonuses in ([], {"unexpected": 1}):
            with self.assertRaises(ValueError):
                normalize_technology_combat_bonuses(bonuses)

    def test_complete_persisted_schema_is_validated(self) -> None:
        state = new_playtime("validate-tech")
        for invalid in (None, {}, {"attackPercent": 1}, {**DEFAULT_TECHNOLOGY_COMBAT_BONUSES, "other": 2},
                        {**DEFAULT_TECHNOLOGY_COMBAT_BONUSES, "attackPercent": True}):
            state["opening"]["technologyCombatBonuses"] = invalid
            with self.assertRaises(ValueError):
                validate_playtime(state)

    def test_legacy_playtime_is_not_claimed_to_have_confirmed_technology(self) -> None:
        state = new_playtime("legacy-tech")
        del state["opening"]["technologyCombatBonuses"]
        validate_playtime(state)
        self.assertIn("| 局外科技攻击力加成 | 未记录 |", render_basic_section(state))
        self.assertNotIn("+20%", render_basic_section(state))

    def test_cli_writes_custom_values_to_json_and_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/new_run.py"), "--run-id", "custom-tech",
                 "--output-dir", directory, "--difficulty", "15", "--squad", "squad_014",
                 "--cocoon", "天马=1", "--tech-attack-percent", "8", "--tech-defense-percent", "8.5",
                 "--tech-hp-percent", "10"],
                check=True, capture_output=True, text=True,
            )
            state = json.loads((Path(directory) / "custom-tech.json").read_text(encoding="utf-8"))
            reading_view = (Path(directory) / "custom-tech.md").read_text(encoding="utf-8")
            self.assertEqual(state["opening"]["technologyCombatBonuses"],
                             {"attackPercent": 8, "defensePercent": 8.5, "maxHpPercent": 10})
            self.assertIn("| 局外科技防御力加成 | +8.5% |", reading_view)
            validate_playtime(state)

    def test_cli_rejects_nan_without_creating_a_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/new_run.py"), "--run-id", "invalid-tech",
                 "--output-dir", directory, "--tech-attack-percent", "nan"],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid technology combat bonus", result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
