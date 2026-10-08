import unittest

from experiments.node_prediction_beta import FamilyModel, Slot, max_entropy


class PredictionBetaTests(unittest.TestCase):
    def test_mean_above_one_and_endpoint_priors(self):
        prior = max_entropy(0, 5, 2.7)
        self.assertAlmostEqual(sum(prior.values()), 1)
        self.assertAlmostEqual(sum(n * p for n, p in prior.items()), 2.7)
        self.assertAlmostEqual(max_entropy(0, 1, .95)[0], .05)
        self.assertAlmostEqual(max_entropy(0, 1, .95)[1], .95)
        self.assertEqual(max_entropy(1, 1, 1), {1: 1})
        with self.assertRaises(ValueError):
            max_entropy(0, 1, 2)

    def test_count_prior_is_not_multiplied_by_layout_count(self):
        slots = [Slot(str(i), {"shop": 1, "event": 1}) for i in range(3)]
        # P(one shop)=.8. Three placements must not turn this into .923.
        model = FamilyModel(slots, {"shop": {0: .2, 1: .8}, "event": {2: .5, 3: .5}})
        result = model.predict({})
        self.assertAlmostEqual(result["posteriorRemainingMeans"]["shop"], .8)
        self.assertAlmostEqual(result["probabilities"]["0"]["shop"], .8 / 3)
        found = model.predict({"0": "shop"})
        self.assertEqual(found["probabilities"]["1"]["shop"], 0)

    def test_exact_dp_agrees_with_brute_and_revelations(self):
        model = FamilyModel([Slot("a", {"shop": .7, "event": .3}),
                             Slot("b", {"shop": .2, "event": .8}), Slot("c", {"event": 1})],
                            {"shop": max_entropy(0, 1, .9), "event": max_entropy(2, 3, 2.1)})
        for known in ({}, {"b": "event"}, {"a": "shop"}):
            dp, brute = model.predict(known), model.brute_force(known)
            self.assertEqual(dp["legalCompletions"], brute["legalCompletions"])
            for id, rows in dp["probabilities"].items():
                self.assertAlmostEqual(sum(rows.values()), 1)
                for name, value in rows.items():
                    self.assertAlmostEqual(value, brute["probabilities"][id][name])
        with self.assertRaises(ValueError):
            model.predict({"a": "shop", "b": "shop"})

    def test_state_limit_does_not_publish_approximate_output(self):
        with self.assertRaises(RuntimeError):
            FamilyModel([Slot(str(i), {"a": 1, "b": 1}) for i in range(10)],
                        {"a": max_entropy(0, 10, 5), "b": max_entropy(0, 10, 5)}, state_limit=3)

    def test_conditional_marker_preserves_zero_generation_and_at_most_one_mark(self):
        model = FamilyModel([Slot("a", {"exchange": 1, "event": 1}), Slot("b", {"exchange": 1, "event": 1})],
                            {"exchange": {0: .2, 1: .5, 2: .3}, "event": {0: 1 / 3, 1: 1 / 3, 2: 1 / 3}})
        plain = model.predict({})
        marked = model.predict({}, marker_type="exchange")
        self.assertEqual(plain["probabilities"], marked["probabilities"])
        self.assertAlmostEqual(sum(marked["conditionalMarkerProbabilities"].values()), .8)
        self.assertAlmostEqual(marked["conditionalMarkerProbabilities"]["a"], .4)
        self.assertAlmostEqual(marked["probabilities"]["a"]["exchange"], .55)
        known = model.predict({"a": "exchange", "b": "exchange"}, marker_type="exchange")
        self.assertEqual(known["conditionalMarkerProbabilities"], {"a": .5, "b": .5})
        excluded = model.predict({"a": "exchange", "b": "exchange"}, marker_type="exchange", excluded_marker_ids=["a"])
        self.assertEqual(excluded["conditionalMarkerProbabilities"], {"b": 1})
