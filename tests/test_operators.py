"""Shared recruitment and one-battle support, including full-mastery Mechanist."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from fulcrum.operators import add_operator, complete_operator_battle, promote_operator, remove_operator
from fulcrum.playtime_state import new_playtime, rebuild_derived, validate_playtime
from fulcrum.playtime_view import render_operator_section


ROOT = Path(__file__).resolve().parents[1]


class OperatorTests(unittest.TestCase):
    def test_default_support_uses_shared_roster_without_recruitment_rewards(self) -> None:
        state = new_playtime("support")
        validate_playtime(state)
        self.assertEqual(len(state["operators"]), 1)
        support = state["operators"][0]
        self.assertEqual((support["name"], support["source"], support["remainingBattles"]),
                         ("机械师", "assistance", 1))
        self.assertEqual(state["resources"]["hope"], 6)
        self.assertEqual(state["componentBox"]["capacity"], 8)
        self.assertEqual(len(state["componentBox"]["items"]), 2)
        view = render_operator_section(state)
        self.assertIn("临时助力", view)
        self.assertIn("可出战 1 场", view)

    def test_initial_normal_recruit_deducts_two_and_does_not_add_support(self) -> None:
        state = new_playtime("initial-normal", initial_operators=[{"name": "机械师"}])
        validate_playtime(state)
        self.assertEqual(len(state["operators"]), 1)
        operator = state["operators"][0]
        self.assertTrue(operator["initialRecruitment"])
        self.assertEqual(operator["source"], "normal")
        self.assertIsNone(operator["remainingBattles"])
        self.assertEqual(state["resources"]["hope"], 4)
        self.assertEqual(state["componentBox"]["capacity"], 10)
        self.assertFalse(any(item["componentId"] == "component_023" for item in state["componentBox"]["items"]))

    def test_initial_temporary_recruit_is_free_and_gets_capacity_only(self) -> None:
        state = new_playtime("initial-temporary", initial_operators=[{"name": "机械师", "source": "temporary"}])
        self.assertEqual((len(state["operators"]), state["resources"]["hope"], state["componentBox"]["capacity"]),
                         (1, 6, 10))
        self.assertEqual(len(state["componentBox"]["items"]), 2)

    def test_special_squad_has_one_temporary_mechanist_not_additional_support(self) -> None:
        state = new_playtime("special", squad_id="squad_002")
        self.assertEqual(len(state["operators"]), 6)
        mechanists = [row for row in state["operators"] if row["name"] == "机械师"]
        self.assertEqual(len(mechanists), 1)
        self.assertEqual(mechanists[0]["source"], "temporary")
        self.assertEqual(state["componentBox"]["capacity"], 10)
        self.assertEqual(state["resources"]["hope"], 6)

    def test_explicit_special_squad_initial_roster_does_not_duplicate_default(self) -> None:
        for operator in ({"name": "机械师"}, {"name": "机械师", "source": "temporary", "instanceId": "confirmed"}):
            with self.subTest(operator=operator):
                state = new_playtime("special-confirmed", squad_id="squad_002", initial_operators=[operator])
                self.assertEqual(len(state["operators"]), 6)
                self.assertEqual(state["componentBox"]["capacity"], 10)
                self.assertEqual(state["resources"]["hope"], 6)
                self.assertEqual(state["operators"][-1]["source"], "temporary")
                validate_playtime(state)

    def test_later_normal_recruit_replaces_support_and_promotion_is_once(self) -> None:
        state = new_playtime("later")
        operator = add_operator(state, "机械师", instance_id="mechanist")
        self.assertEqual(state["resources"]["hope"], 3)
        self.assertEqual(len(state["operators"]), 1)
        self.assertFalse(operator["initialRecruitment"])
        self.assertEqual(state["componentBox"]["capacity"], 10)
        promote_operator(state, "mechanist")
        self.assertEqual(state["resources"]["hope"], 2)
        item = state["componentBox"]["items"][-1]
        self.assertEqual((item["componentId"], item["remainingUses"]), ("component_023", 3))
        self.assertEqual(item["estimatedValue"], 1)
        before = deepcopy(state)
        promote_operator(state, "mechanist")
        rebuild_derived(state)
        self.assertEqual(state, before)
        validate_playtime(state)

    def test_emergency_support_is_shared_one_battle_record_and_has_no_bonus(self) -> None:
        state = new_playtime("emergency")
        remove_operator(state, state["operators"][0]["instanceId"])
        operator = add_operator(state, "机械师", source="emergency", ingot_cost=5)
        self.assertEqual(state["resources"]["originiumIngot"], 15)
        self.assertEqual(state["resources"]["hope"], 6)
        self.assertEqual(state["componentBox"]["capacity"], 8)
        self.assertEqual(operator["remainingBattles"], 1)
        self.assertEqual(complete_operator_battle(state, [operator["instanceId"]]), [operator["instanceId"]])
        self.assertEqual(state["operators"], [])

    def test_only_actually_deployed_supports_leave_and_no_automatic_replenishment(self) -> None:
        state = new_playtime("deployed")
        support_id = state["operators"][0]["instanceId"]
        ordinary = add_operator(state, "示例干员", hope_cost=1)
        hired = add_operator(state, "示例雇员", source="emergency", ingot_cost=4)
        removed = complete_operator_battle(state, [ordinary["instanceId"], hired["instanceId"]])
        self.assertEqual(removed, [hired["instanceId"]])
        self.assertIn(support_id, [row["instanceId"] for row in state["operators"]])
        complete_operator_battle(state, [support_id])
        rebuild_derived(state)
        self.assertEqual([row["name"] for row in state["operators"]], ["示例干员"])
        self.assertEqual(state["componentBox"]["capacity"], 8)

    def test_support_cannot_be_promoted(self) -> None:
        state = new_playtime("no-support-promotion")
        before = deepcopy(state)
        with self.assertRaisesRegex(ValueError, "support cannot be promoted"):
            promote_operator(state, state["operators"][0]["instanceId"])
        self.assertEqual(state, before)

    def test_generic_permanent_recruit_also_replaces_same_name_support(self) -> None:
        state = new_playtime("shared")
        add_operator(state, "示例干员", source="assistance")
        operator = add_operator(state, "示例干员", source="temporary")
        self.assertEqual([row for row in state["operators"] if row["name"] == "示例干员"], [operator])
        self.assertIsNone(operator["remainingBattles"])

    def test_record_only_updates_roster_without_replaying_observed_resources(self) -> None:
        state = new_playtime("observed")
        state["resources"]["hope"] = 3
        state["componentBox"]["capacity"] = 10
        resources, box = deepcopy(state["resources"]), deepcopy(state["componentBox"])
        operator = add_operator(state, "机械师", record_only=True)
        self.assertEqual(state["resources"], resources)
        self.assertEqual(state["componentBox"], box)
        promote_operator(state, operator["instanceId"], record_only=True)
        self.assertEqual(state["resources"], resources)
        self.assertEqual(state["componentBox"], box)
        self.assertEqual(state["operators"][0]["elite"], 2)
        self.assertEqual(len(state["operators"]), 1)
        before = deepcopy(state)
        with self.assertRaises(ValueError):
            add_operator(state, "示例干员", record_only=True, hope_cost=1)
        with self.assertRaises(ValueError):
            promote_operator(state, operator["instanceId"], record_only=True, hope_cost=1)
        self.assertEqual(state, before)

    def test_confirmed_initial_roster_accepts_other_operators_and_stays_isolated(self) -> None:
        initial = [{"name": "示例干员", "instanceId": "initial", "hopeCost": 1}]
        state = new_playtime("initial-input", initial_operators=initial)
        initial[0]["name"] = "changed"
        self.assertEqual(state["operators"][0]["name"], "示例干员")
        self.assertEqual(state["resources"]["hope"], 5)
        self.assertEqual(state["operators"][-1]["name"], "机械师")
        for invalid in ({}, [None], [{}], [{"name": "示例干员", "unexpected": True}]):
            with self.assertRaises(ValueError):
                new_playtime("bad-initial", initial_operators=invalid)

    def test_duplicate_recruitment_and_failed_costs_do_not_mutate_state(self) -> None:
        state = new_playtime("rollback")
        before = deepcopy(state)
        for kwargs in ({"hope_cost": 99}, {"hope_cost": 1, "ingot_cost": 99}, {"elite": True},
                       {"source": []}, {"instance_id": []}, {"hope_cost": True}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    add_operator(state, "机械师", **kwargs)
                self.assertEqual(state, before)
        add_operator(state, "机械师", instance_id="mechanist")
        before = deepcopy(state)
        with self.assertRaises(ValueError):
            add_operator(state, "机械师", instance_id="mechanist")
        with self.assertRaises(ValueError):
            add_operator(state, "机械师")
        self.assertEqual(state, before)

    def test_full_box_allows_promotion_and_temporary_overflow(self) -> None:
        state = new_playtime("full-box", initial_operators=[{"name": "机械师"}])
        state["componentBox"]["capacity"] = 2
        hope = state["resources"]["hope"]
        promote_operator(state, state["operators"][0]["instanceId"])
        self.assertEqual(state["operators"][0]["elite"], 2)
        self.assertEqual(state["resources"]["hope"], hope - 1)
        self.assertEqual(len(state["componentBox"]["items"]), 3)
        self.assertEqual(state["componentBox"]["items"][-1]["componentId"], "component_023")

    def test_cost_override_and_rarity_based_non_n15_price(self) -> None:
        state = new_playtime("confirmed", difficulty=10)
        operator = add_operator(state, "机械师")
        promote_operator(state, operator["instanceId"], hope_cost=0)
        self.assertEqual(state["resources"]["hope"], 4)
        self.assertEqual(state["componentBox"]["items"][-1]["componentId"], "component_023")

    def test_old_roster_without_lifetime_fields_is_valid_and_not_backfilled(self) -> None:
        state = new_playtime("old")
        del state["opening"]["mechanistMasteryPreset"]
        state["operators"] = [{"instanceId": "old-mechanist", "name": "机械师", "elite": 1,
                               "source": "squad_002-temporary"}]
        before = deepcopy(state)
        rebuild_derived(state)
        self.assertEqual(state, before)
        promote_operator(state, "old-mechanist")
        self.assertEqual(state["componentBox"]["capacity"], 8)
        self.assertEqual(state["componentBox"]["items"][-1]["componentId"], "component_023")

    def test_invalid_roster_and_invalid_deployed_ids_are_rejected(self) -> None:
        state = new_playtime("bad-roster")
        for deployed in (["unknown"], [state["operators"][0]["instanceId"]] * 2, [None]):
            before = deepcopy(state)
            with self.assertRaises(ValueError):
                complete_operator_battle(state, deployed)
            self.assertEqual(state, before)
        for changes in ({"remainingBattles": 0}, {"remainingBattles": None}, {"elite": True}, {"initialRecruitment": 1}):
            invalid = deepcopy(state)
            invalid["operators"][0].update(changes)
            with self.assertRaises(ValueError):
                validate_playtime(invalid)

    def test_cli_opening_and_shared_roster_updates_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/new_run.py"), "--run-id", "cli-operators",
                 "--output-dir", directory, "--initial-mechanist", "normal"],
                check=True, capture_output=True, text=True,
            )
            self.assertIn("cli-operators.json", result.stdout)
            path = Path(directory) / "cli-operators.json"
            state = json.loads(path.read_text(encoding="utf-8"))
            operator_id = state["operators"][0]["instanceId"]
            for command in (
                ["promote-operator", operator_id],
                ["add-operator", "示例雇员", "--source", "emergency", "--instance-id", "hired", "--ingot-cost", "5"],
                ["operator-battle", "--deployed", "hired"],
            ):
                subprocess.run([sys.executable, "-m", "fulcrum.playtime_cli", str(path), *command],
                               check=True, capture_output=True, text=True, cwd=ROOT)
            state = json.loads(path.read_text(encoding="utf-8"))
            validate_playtime(state)
            self.assertEqual((state["resources"]["hope"], state["resources"]["originiumIngot"]), (3, 15))
            self.assertEqual(len(state["operators"]), 1)
            self.assertEqual(state["operators"][0]["elite"], 2)
            reading_view = path.with_suffix(".md").read_text(encoding="utf-8")
            self.assertIn("普通招募", reading_view)
            self.assertIn("精2", reading_view)
            self.assertNotIn("示例雇员", reading_view)
            self.assertIn("结构性原理", reading_view)
            before = path.read_bytes()
            result = subprocess.run(
                [sys.executable, "-m", "fulcrum.playtime_cli", str(path), "add-operator", "机械师"],
                capture_output=True, text=True, cwd=ROOT,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
