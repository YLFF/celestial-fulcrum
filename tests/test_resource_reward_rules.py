"""Slot rewards saturate without imposing a cap on actual deployment slots."""

import unittest

from fulcrum.resource_reward_rules import slot_reward


class SlotRewardTests(unittest.TestCase):
    def test_carry_increase_stops_at_thirteen(self) -> None:
        result = slot_reward("carrySlots", 12, 3)
        self.assertEqual(result["actualIncrease"], 1)
        self.assertEqual(result["newValue"], 13)
        self.assertEqual(result["marginalFactors"], [1, 0, 0])
        self.assertEqual(result["effectiveRewardUnits"], 1)
        self.assertEqual(slot_reward("carrySlots", 13, 1)["effectiveRewardUnits"], 0)

    def test_deployment_crosses_current_carry_threshold(self) -> None:
        result = slot_reward("deploymentSlots", 6, 3, carry_slots=7)
        self.assertEqual(result["marginalFactors"], [1, 0.5, 0.5])
        self.assertEqual(result["effectiveRewardUnits"], 2)
        self.assertEqual(result["newValue"], 9)

    def test_deployment_has_score_limit_but_no_actual_cap(self) -> None:
        result = slot_reward("deploymentSlots", 12, 3, carry_slots=7)
        self.assertEqual(result["marginalFactors"], [0.5, 0, 0])
        self.assertEqual(result["effectiveRewardUnits"], 0.5)
        self.assertEqual(result["actualIncrease"], 3)
        self.assertEqual(result["newValue"], 15)
        self.assertEqual(slot_reward("deploymentSlots", 20, 2, carry_slots=13)["newValue"], 22)

    def test_zero_gain_and_well_equipped_team(self) -> None:
        self.assertEqual(slot_reward("carrySlots", 7, 0)["marginalFactors"], [])
        result = slot_reward("deploymentSlots", 12, 2, carry_slots=13)
        self.assertEqual(result["marginalFactors"], [1, 0])

    def test_invalid_inputs_are_rejected(self) -> None:
        for arguments in (
            ("hope", 7, 1), ("carrySlots", -1, 1), ("carrySlots", 7, -1),
            ("carrySlots", True, 1), ("carrySlots", 7, 1.5), ("deploymentSlots", 6, 1),
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                slot_reward(*arguments)
        for carry_slots in (-1, True, 7.5):
            with self.subTest(carry_slots=carry_slots), self.assertRaises(ValueError):
                slot_reward("deploymentSlots", 6, 1, carry_slots=carry_slots)


if __name__ == "__main__":
    unittest.main()
