"""Reference calibration, nonlinear expectations, and missing-value boundaries."""

from copy import deepcopy
import unittest

from fulcrum.resource_scoring import (
    IncompleteResourceScore, ResourceScorer, UtilityCurve, default_resource_scorer, slot_value_curves,
)
from fulcrum.resource_reward_rules import slot_reward


class ResourceScoringTests(unittest.TestCase):
    def test_confirmed_reference_prices_and_no_mutation(self) -> None:
        before = {"relicCount": 0, "originiumIngot": 20}
        after = {"relicCount": 3, "originiumIngot": 10}
        saved = deepcopy((before, after))
        score = default_resource_scorer().score_change(before, after)
        self.assertEqual(score["gainPoints"], 300)
        self.assertEqual(score["lossPoints"], 80)
        self.assertEqual(score["netPoints"], 220)
        self.assertEqual((before, after), saved)
        self.assertEqual(default_resource_scorer().score_change(
            {"relicCount": 0}, {"relicCount": 1})["netPoints"], 100)
        self.assertEqual(default_resource_scorer().score_change(
            {"originiumIngot": 0}, {"originiumIngot": 1})["netPoints"], 8)

    def test_crossing_bands_integrates_and_round_trip_cannot_create_score(self) -> None:
        scorer = ResourceScorer({"hope": UtilityCurve(((7, 0.3), (20, 0.1), (None, 0.02)))})
        forward = scorer.score_change({"hope": 6}, {"hope": 9})["netPoints"]
        reverse = scorer.score_change({"hope": 9}, {"hope": 6})["netPoints"]
        self.assertAlmostEqual(forward, 50)
        self.assertAlmostEqual(forward + reverse, 0)
        self.assertAlmostEqual(forward, scorer.score_change({"hope": 6}, {"hope": 7})["netPoints"]
                               + scorer.score_change({"hope": 7}, {"hope": 9})["netPoints"])

    def test_expectation_is_not_the_score_of_mean_resources(self) -> None:
        scorer = ResourceScorer({"experience": UtilityCurve(((10, 0.1), (None, 0)))})
        result = scorer.expected_change({"experience": 0}, [
            (0.5, {"experience": 0}), (0.5, {"experience": 20}),
        ])
        self.assertAlmostEqual(result["netPoints"], 50)
        self.assertAlmostEqual(scorer.score_change({"experience": 0}, {"experience": 10})["netPoints"], 100)
        self.assertEqual(scorer.score_change({"experience": 10}, {"experience": 20})["netPoints"], 0)

    def test_normalization_is_global_not_candidate_minmax(self) -> None:
        curves = {"relicCount": UtilityCurve.linear(1), "originiumIngot": UtilityCurve.linear(0.08)}
        scorer = ResourceScorer(curves)
        curves["relicCount"] = UtilityCurve.linear(100)
        before, after = {"relicCount": 0}, {"relicCount": 2}
        self.assertEqual(scorer.score_change(before, after)["netPoints"], 200)
        self.assertEqual(ResourceScorer(scorer.curves, reference_points=1).score_change(before, after)["netPoints"], 2)

    def test_preferences_do_not_discount_costs(self) -> None:
        result = default_resource_scorer().score_change(
            {"relicCount": 0, "originiumIngot": 20},
            {"relicCount": 1, "originiumIngot": 10}, benefit_factor=0.1,
        )
        self.assertEqual(result["netPoints"], 20)
        self.assertEqual(result["adjustedPoints"], -70)
        self.assertEqual(result["lossPoints"], 80)

    def test_missing_resource_is_not_zero_or_implicit_zero_quantity(self) -> None:
        scorer = default_resource_scorer()
        with self.assertRaises(IncompleteResourceScore) as raised:
            scorer.score_change({"hope": 0}, {"hope": 1})
        self.assertEqual(raised.exception.resource_ids, ("hope",))
        self.assertEqual(scorer.score_change({"hope": 6}, {"hope": 6})["netPoints"], 0)
        with self.assertRaises(ValueError):
            scorer.score_change({}, {"relicCount": 1})

    def test_slot_curves_match_existing_rules_across_thresholds(self) -> None:
        for carry in (0, 7, 13, 15):
            scorer = ResourceScorer(slot_value_curves(carry, carry_unit_value=0.4, deployment_unit_value=0.5))
            for current in (0, 6, 12, 13, 20):
                with self.subTest(carry=carry, current=current):
                    result = slot_reward("deploymentSlots", current, 3, carry_slots=carry)
                    points = scorer.score_change({"deploymentSlots": current}, {"deploymentSlots": result["newValue"]})
                    self.assertAlmostEqual(points["netPoints"], result["effectiveRewardUnits"] * 50)
        result = slot_reward("carrySlots", 12, 3)
        points = scorer.score_change({"carrySlots": 12}, {"carrySlots": result["newValue"]})
        self.assertAlmostEqual(points["netPoints"], 40)

    def test_bad_curves_quantities_and_probabilities_are_rejected(self) -> None:
        for bands in ((), ((1, 1),), ((0, 1), (None, 1)), ((2, 1), (1, 1), (None, 1)),
                      ((None, 1), (2, 1)), ((None, -1),), ((float("nan"), 1), (None, 1))):
            with self.subTest(bands=bands), self.assertRaises(ValueError):
                UtilityCurve(bands)
        scorer = default_resource_scorer()
        for quantity in (-1, True, float("nan"), float("inf")):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                scorer.score_change({"relicCount": 0}, {"relicCount": quantity})
        for probabilities in ([], [0.5], [1.1], [-0.1, 1.1], [True]):
            with self.subTest(probabilities=probabilities), self.assertRaises(ValueError):
                scorer.expected_change({"relicCount": 0}, [(p, {"relicCount": 1}) for p in probabilities])
        with self.assertRaises(ValueError):
            ResourceScorer({}, reference_points=0)
        with self.assertRaises(ValueError):
            scorer.score_change({"relicCount": 0}, {"relicCount": 1}, benefit_factor=-1)


if __name__ == "__main__":
    unittest.main()
