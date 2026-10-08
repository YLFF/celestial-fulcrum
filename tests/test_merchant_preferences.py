"""Player shop-entry preferences do not simulate transactions or forbid entry."""

import unittest

from fulcrum.merchant_preferences import merchant_entry_preferences


def preferences(**changes):
    arguments = {"floor": 3, "cash": 20, "estimated_value": 1, "box_capacity": 8,
                 "box_count": 4, "yellow_visited": False, "eligible_event_ids": []}
    return merchant_entry_preferences(**{**arguments, **changes})


class MerchantPreferenceTests(unittest.TestCase):
    def test_yellow_strict_threshold_and_layer_first_visit(self) -> None:
        self.assertTrue(preferences()["yellow"]["stronglyPreferred"])
        self.assertFalse(preferences(estimated_value=0)["yellow"]["stronglyPreferred"])
        self.assertFalse(preferences(yellow_visited=True)["yellow"]["stronglyPreferred"])
        self.assertTrue(preferences(cash=0, estimated_value=21)["yellow"]["stronglyPreferred"])
        self.assertEqual(preferences(cash=0, estimated_value=21)["unreservedCash"], 0)

    def test_yellow_empty_box_urgency_and_before_floor_four(self) -> None:
        self.assertGreater(preferences(box_count=0)["yellow"]["emptyBoxFraction"],
                           preferences(box_count=7)["yellow"]["emptyBoxFraction"])
        self.assertTrue(preferences(floor=3)["yellow"]["developmentPreferenceBeforeFloorIV"])
        self.assertFalse(preferences(floor=4)["yellow"]["developmentPreferenceBeforeFloorIV"])
        self.assertEqual(preferences(box_capacity=0, box_count=0)["yellow"]["emptyBoxFraction"], 0)

    def test_green_team_deficit_can_take_precedence_before_yellow(self) -> None:
        self.assertTrue(preferences()["green"]["considerEntry"])
        self.assertTrue(preferences(yellow_visited=True)["green"]["considerEntry"])
        green = preferences(team_below_threshold=True)["green"]
        self.assertTrue(green["priorityForTeamDeficit"])
        self.assertTrue(green["considerEntry"])
        self.assertIsNone(preferences()["green"]["teamBelowThreshold"])
        self.assertFalse(preferences(cash=0, team_below_threshold=True)["green"]["considerEntry"])

    def test_selected_reserves_add_while_actual_cash_and_economy_remain_separate(self) -> None:
        result = preferences(cash=50, estimated_value=100, yellow_visited=True,
                             eligible_event_ids=["encounter_005", "encounter_016", "encounter_017"],
                             reserve_entries={"partner_meeting": 50, "lake_fairy": 3})
        self.assertEqual(result["cashReserve"], 53)
        self.assertEqual(result["unreservedCash"], 0)
        self.assertTrue(result["green"]["cashLimitedByReserve"])
        self.assertTrue(result["green"]["considerEntry"])
        self.assertFalse(result["transactionModelEnabled"])
        self.assertFalse(result["mutatesPlaytime"])
        self.assertEqual(result["unreservedEconomy"], 97)
        self.assertEqual(preferences(cash=50, eligible_event_ids=["encounter_005", "encounter_017"])["cashReserve"], 20)
        self.assertEqual(preferences(eligible_event_ids=["encounter_017"])["cashReserve"], 20)
        poor = preferences(cash=2, estimated_value=100, eligible_event_ids=["encounter_016"], reserve_override=50)
        self.assertEqual(poor["reserveShortfall"], 48)
        self.assertEqual(poor["unreservedCash"], 0)

    def test_latest_filtered_pool_and_player_reserve_override(self) -> None:
        self.assertEqual(preferences(eligible_event_ids=[])["cashReserve"], 20)
        self.assertEqual(preferences(yellow_visited=True)["cashReserve"], 0)
        self.assertEqual(preferences(yellow_shop_available=False)["cashReserve"], 0)
        self.assertEqual(preferences(floor=6)["cashReserve"], 0)
        overridden = preferences(eligible_event_ids=["encounter_016"], reserve_override=3)
        self.assertEqual(overridden["cashReserve"], 3)
        self.assertEqual(overridden["unreservedCash"], 17)
        self.assertTrue(overridden["reserveIsOverridden"])

    def test_invalid_inputs(self) -> None:
        for changes in ({"cash": -1}, {"cash": True}, {"estimated_value": float("nan")},
                        {"floor": 0}, {"floor": True}, {"box_count": -1}, {"box_capacity": -1},
                        {"yellow_visited": 1}, {"team_below_threshold": "unknown"},
                        {"eligible_event_ids": "encounter_016"}, {"reserve_override": -1},
                        {"yellow_shop_available": 1}, {"reserve_entries": []},
                        {"reserve_entries": {"yellow_shop": -1}},
                        {"reserve_entries": {"yellow_shop": 20}, "reserve_override": 20}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                preferences(**changes)

    def test_over_capacity_box_is_treated_as_full(self) -> None:
        result = preferences(box_count=9, box_capacity=8)
        self.assertEqual(result["yellow"]["freeBoxSlots"], 0)
        self.assertEqual(result["yellow"]["emptyBoxFraction"], 0)


if __name__ == "__main__":
    unittest.main()
