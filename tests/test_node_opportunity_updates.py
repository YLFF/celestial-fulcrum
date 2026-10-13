from copy import deepcopy
import unittest

from fulcrum.scoring_calibration import (
    emergency_aid_score, green_merchant_base_score, merchant_prefix_score,
    merchant_reference_score, safe_corner_score,
)
from scripts.calibrate_node_scores import build_report


class SafeCornerTests(unittest.TestCase):
    def score(self, **changes):
        return safe_corner_score(**{
            "two_action_points_value": 400, "hope_points": 0,
            "has_elite1_six_star": False, **changes,
        })

    def test_ten_menus_have_exactly_one_fixed_and_two_distinct_random_options(self):
        result = self.score()
        self.assertEqual(len(result["menus"]), 10)
        frequencies = {name: 0 for name in result["options"]}
        for row in result["menus"]:
            self.assertEqual(len(set(row["optionIds"])), 3)
            self.assertIn("rest", row["optionIds"])
            self.assertEqual(row["probability"], 0.1)
            for name in row["optionIds"]:
                frequencies[name] += 1
            self.assertEqual(row["points"], max(result["options"][name] for name in row["optionIds"]))
        self.assertEqual(frequencies.pop("rest"), 10)
        self.assertTrue(all(count == 4 for count in frequencies.values()))

    def test_expectation_and_supply_ticket_condition(self):
        self.assertEqual(self.score()["points"], 205)
        self.assertEqual(self.score(hope_points=150)["points"], 232.5)
        self.assertEqual(self.score(has_elite1_six_star=True)["points"], 225)
        self.assertEqual(self.score(hope_points=150, has_elite1_six_star=True)["points"], 245)
        self.assertEqual(self.score(two_action_points_value=0)["points"], 62.5)

    def test_confirmed_menu_is_not_randomly_averaged_again(self):
        result = self.score(has_elite1_six_star=True,
                            offered_option_ids=["rest", "advanced_supply_ticket", "box_capacity"])
        self.assertEqual(result["points"], 150)
        self.assertEqual(result["model"], "confirmed_menu")
        self.assertFalse(result["mutatesPlaytime"])

    def test_invalid_and_missing_option_values_fail(self):
        for changes in ({"hope_points": None}, {"two_action_points_value": -1},
                        {"has_elite1_six_star": 1}, {"offered_option_ids": "rest"},
                        {"offered_option_ids": ["hope", "box_capacity", "action_points"]},
                        {"offered_option_ids": ["rest", "hope", "hope"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.score(**changes)


class UpdatedMerchantTests(unittest.TestCase):
    def parameters(self, **changes):
        return {"category_id": "node_type_004", "floor": 3, "cash": 100,
                "estimated_value": 0, "box_capacity": 8, "box_count": 3,
                "yellow_visited": False, "eligible_event_ids": [], "below_threshold": False,
                **changes}

    def test_logarithm_hits_both_anchors_and_is_increasing_concave(self):
        self.assertEqual(green_merchant_base_score(0), 0)
        self.assertAlmostEqual(green_merchant_base_score(20), 200)
        self.assertAlmostEqual(green_merchant_base_score(280), 800)
        values = [green_merchant_base_score(x) for x in range(0, 101, 10)]
        self.assertEqual(values, sorted(values))
        increments = [b - a for a, b in zip(values, values[1:])]
        self.assertEqual(increments, sorted(increments, reverse=True))

    def test_yellow_linear_low_economy_and_cap_then_repeat_factor(self):
        for economy, points in ((0, 0), (1, 30), (10, 300), (20, 600), (30, 900), (40, 1000)):
            args = self.parameters(category_id="node_type_013", cash=0, estimated_value=economy)
            first = merchant_reference_score(**args)
            self.assertEqual(first["points"], points)
            self.assertAlmostEqual(merchant_reference_score(**args, first_visit=False)["points"], 0.8 * points)

    def test_additive_reserves_and_conditional_yellow_reserve_release(self):
        entries = {"yellow_shop": 30, "partner_meeting": 50, "lake_fairy": 3}
        original = deepcopy(entries)
        args = self.parameters(reserve_entries=entries)
        before = merchant_reference_score(**args)
        self.assertEqual(before["preferences"]["cashReserve"], 83)
        self.assertEqual(before["economyInput"], 17)
        self.assertAlmostEqual(before["points"], green_merchant_base_score(17) + 100)
        for changes in ({"yellow_visited": True}, {"yellow_shop_available": False}):
            after = merchant_reference_score(**{**args, **changes})
            self.assertEqual(after["preferences"]["cashReserve"], 53)
        self.assertEqual(entries, original)

    def test_default_reserve_and_confirmed_absence(self):
        before = merchant_reference_score(**self.parameters(cash=40))
        self.assertEqual(before["preferences"]["cashReserve"], 0)
        self.assertAlmostEqual(before["points"], green_merchant_base_score(40) + 100)
        for changes in ({"floor": 6}, {"floor": 1, "yellow_shop_available": False}, {"yellow_visited": True}):
            after = merchant_reference_score(**self.parameters(cash=20, **changes))
            self.assertAlmostEqual(after["points"], 300)
        self.assertAlmostEqual(merchant_reference_score(**self.parameters(cash=20))["points"], 300)
        self.assertEqual(merchant_reference_score(**self.parameters(cash=20, reserve_override=20))["points"], 0)
        self.assertGreater(merchant_reference_score(**self.parameters(cash=21))["points"], 0)

    def test_repeat_discounts_shopping_without_awarding_tickets(self):
        args = self.parameters(yellow_visited=True, below_threshold=True, squad_id="squad_005")
        first = merchant_reference_score(**args)
        repeat = merchant_reference_score(**args, first_visit=False)
        self.assertAlmostEqual(repeat["points"], 0.8 * first["parts"]["entry"])
        self.assertEqual(repeat["parts"]["tickets"], 0)
        self.assertFalse(repeat["preferences"]["mutatesPlaytime"])

    def test_per_move_proxy_is_separate_and_does_not_cover_unaffordable_net_costs(self):
        args = self.parameters(category_id="node_type_013", cash=10)
        result = merchant_prefix_score(**args, prefix_cash_outcomes=[(4, 1)], path_steps=3)
        self.assertEqual(result["expectedArrivalCash"], 17)
        self.assertEqual(result["points"], 510)
        self.assertEqual(result["stepCashProxy"], 3)
        self.assertFalse(result["unlocksGuaranteedActions"])
        with self.assertRaises(ValueError):
            merchant_prefix_score(**args, prefix_cash_outcomes=[(-11, 1)], path_steps=10)
        for changes in ({"path_steps": -1}, {"path_steps": True}, {"step_ingot_expectation": -1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                merchant_prefix_score(**args, prefix_cash_outcomes=[(0, 1)], **changes)


class AidAndReportTests(unittest.TestCase):
    def test_aid_is_appraisal_not_actual_cash_or_permanent_team_strength(self):
        for count in (0, 1, 2):
            result = emergency_aid_score(count)
            self.assertEqual(result["points"], 72 * count)
            self.assertEqual(result["estimatedValueIncrease"], 9 * count)
            self.assertEqual(result["actualCashAward"], 0)
        for count in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                emergency_aid_score(count)

    def test_report_uses_new_node_opportunities(self):
        report = build_report(corn_count=2, has_elite1_six_star=True)
        self.assertEqual(report["safeCorner"]["met"]["points"], 225)
        self.assertEqual(report["safeCorner"]["unmet"]["points"], 245)
        self.assertEqual(report["emergencyAid"]["points"], 144)
        self.assertEqual(report["merchantPrefixExamples"]["earnedCash"]["points"], 810)
        self.assertEqual(report["merchantPrefixExamples"]["additiveReserve"]["economyInput"], 17)


if __name__ == "__main__":
    unittest.main()
