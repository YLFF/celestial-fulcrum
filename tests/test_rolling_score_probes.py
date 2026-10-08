from copy import deepcopy
import unittest

from fulcrum.scoring_calibration import (
    REVEAL_VALUE_COEFFICIENT, green_merchant_base_score, merchant_prefix_score, merchant_reference_score,
    reveal_information_score,
)


class RevealScoreTests(unittest.TestCase):
    def test_default_values_both_unknown_families_in_the_same_score_unit(self):
        result = reveal_information_score(
            {"mystery": 500, "ferocity": 300}, newly_revealed_ids=["mystery", "ferocity"],
        )
        self.assertEqual(REVEAL_VALUE_COEFFICIENT, 0.2)
        self.assertEqual(result["points"], 160)
        self.assertEqual(sum(row["points"] for row in result["terms"]), result["points"])

    def test_first_revelation_only_and_no_extra_information_for_the_entered_node(self):
        values = {"a": 500, "b": 1000, "c": 300}
        result = reveal_information_score(
            values, newly_revealed_ids=["a", "a", "b", "c"],
            already_revealed_ids=["b"], entered_node_id="c",
        )
        self.assertEqual(result["countedNodeIds"], ["a"])
        self.assertEqual(result["points"], 100)
        self.assertFalse(result["mutatesPlaytime"])
        self.assertEqual(values, {"a": 500, "b": 1000, "c": 300})

    def test_coefficient_override_and_empty_information(self):
        self.assertEqual(reveal_information_score({"a": 500}, newly_revealed_ids=["a"], coefficient=0.1)["points"], 50)
        self.assertEqual(reveal_information_score({}, newly_revealed_ids=[])["points"], 0)
        self.assertEqual(reveal_information_score({}, newly_revealed_ids=["a"], already_revealed_ids=["a"])["points"], 0)

    def test_unknown_values_and_invalid_inputs_are_not_silently_zero(self):
        for kwargs in (
            {"node_opportunity_points": {}, "newly_revealed_ids": ["a"]},
            {"node_opportunity_points": {"a": None}, "newly_revealed_ids": ["a"]},
            {"node_opportunity_points": {"a": -1}, "newly_revealed_ids": ["a"]},
            {"node_opportunity_points": {"a": float("nan")}, "newly_revealed_ids": ["a"]},
            {"node_opportunity_points": {}, "newly_revealed_ids": "a"},
            {"node_opportunity_points": {}, "newly_revealed_ids": [], "coefficient": True},
            {"node_opportunity_points": {}, "newly_revealed_ids": [], "coefficient": -1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                reveal_information_score(**kwargs)


class MerchantPrefixTests(unittest.TestCase):
    def parameters(self, **changes):
        return {
            "category_id": "node_type_013", "floor": 3, "cash": 10,
            "estimated_value": 0, "box_capacity": 8, "box_count": 3,
            "yellow_visited": False, "eligible_event_ids": [], "below_threshold": False,
            **changes,
        }

    def test_deterministic_prefix_changes_shop_priority_without_changing_actual_resources(self):
        parameters = self.parameters()
        before = deepcopy(parameters)
        self.assertEqual(merchant_reference_score(**parameters)["points"], 300)
        result = merchant_prefix_score(**parameters, prefix_cash_outcomes=[(4 + 4 + 5, 1)], path_steps=4)
        self.assertEqual(result["expectedArrivalCash"], 27)
        self.assertEqual(result["stepCashProxy"], 4)
        self.assertEqual(result["qualifiedProbability"], 1)
        self.assertEqual(result["points"], 810)
        self.assertEqual(parameters, before)
        self.assertFalse(result["mutatesPlaytime"])
        self.assertFalse(result["unlocksGuaranteedActions"])

    def test_nonlinear_condition_is_evaluated_per_branch_not_on_average_cash(self):
        parameters = self.parameters(category_id="node_type_004", cash=15)
        result = merchant_prefix_score(**parameters, prefix_cash_outcomes=[(0, 0.5), (12, 0.5)])
        self.assertEqual(result["expectedArrivalCash"], 21)
        self.assertAlmostEqual(result["points"], 0.5 * (green_merchant_base_score(7) + 100))
        self.assertEqual(result["qualifiedProbability"], 0.5)
        averaged = merchant_reference_score(**{**parameters, "cash": result["expectedArrivalCash"]})
        self.assertAlmostEqual(averaged["points"], green_merchant_base_score(1) + 100)
        self.assertNotAlmostEqual(averaged["points"], result["points"])

    def test_costs_are_net_and_event_cash_reserve_is_still_applied(self):
        parameters = self.parameters(category_id="node_type_004", cash=12,
                                     yellow_visited=True, eligible_event_ids=["encounter_005"],
                                     reserve_entries={"knock_lever": 10})
        self.assertEqual(merchant_prefix_score(**parameters, prefix_cash_outcomes=[(-2, 1)])["points"], 0)
        self.assertAlmostEqual(merchant_prefix_score(**parameters, prefix_cash_outcomes=[(2, 1)])["points"], green_merchant_base_score(4) + 100)
        self.assertAlmostEqual(merchant_prefix_score(**{**parameters, "reserve_entries": None}, prefix_cash_outcomes=[(2, 1)], reserve_override=0)["points"], green_merchant_base_score(14) + 100)

    def test_appraisal_counts_for_shop_score_but_does_not_award_actual_cash(self):
        parameters = self.parameters(cash=0, estimated_value=21)
        self.assertEqual(merchant_prefix_score(**parameters, prefix_cash_outcomes=[(0, 1)])["points"], 630)
        parameters.update(category_id="node_type_004", yellow_visited=True)
        result = merchant_prefix_score(**parameters, prefix_cash_outcomes=[(0, 1)])
        self.assertAlmostEqual(result["points"], green_merchant_base_score(21) + 100)
        self.assertEqual(result["expectedArrivalCash"], 0)
        self.assertFalse(result["unlocksGuaranteedActions"])

    def test_coupon_mix_and_repeat_discount_are_preserved(self):
        parameters = self.parameters(category_id="node_type_004", cash=50, yellow_visited=True,
                                     squad_id="squad_005", below_threshold=True)
        first = merchant_prefix_score(**parameters, prefix_cash_outcomes=[(0, 1)])["points"]
        self.assertAlmostEqual(first, green_merchant_base_score(50) + 164.0625)
        result = merchant_prefix_score(**parameters, prefix_cash_outcomes=[(0, 1)], first_visit=False)
        self.assertAlmostEqual(result["points"], 0.8 * green_merchant_base_score(50))
        self.assertEqual(result["branches"][0]["score"]["parts"]["tickets"], 0)
        self.assertEqual(result["branches"][0]["score"]["repeatFactor"], 0.8)

    def test_invalid_outcomes_do_not_create_an_affordable_arrival(self):
        for outcomes in ([], [(1, 0.5)], [(1, -1), (1, 2)], [(-11, 1)],
                         [(float("nan"), 1)], [(True, 1)], [(1, True)]):
            with self.subTest(outcomes=outcomes), self.assertRaises(ValueError):
                merchant_prefix_score(**self.parameters(), prefix_cash_outcomes=outcomes)


if __name__ == "__main__":
    unittest.main()
