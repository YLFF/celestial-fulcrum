"""Focused draft effect model checks; live scoring stays independent."""

from copy import deepcopy
import json
import random
import unittest

from fulcrum.relic_effects import (DEFINITIONS_PATH, clause_enabled, deployment_capacity,
                                  evaluate_numeric, load_definitions, management_for,
                                  structural_stage, summarize_numeric, validate_runtime_state)
from fulcrum.relic_scoring import RelicScorer


class RelicEffectModelTests(unittest.TestCase):
    def setUp(self):
        self.definitions = load_definitions(DEFINITIONS_PATH)

    def test_ten_deterministic_unique_samples(self):
        self.assertEqual(len(self.definitions), 10)
        self.assertEqual(set(self.definitions), {"relic_126", "relic_089", "relic_127", "relic_087",
                         "relic_072", "relic_015", "relic_011", "relic_092", "relic_123", "relic_010"})

    def test_cost_add_then_multiply(self):
        self.assertEqual(evaluate_numeric(10, flat_deltas=[2], factors=[0.5]), 6)

    def test_development_multipliers_and_final_floor(self):
        self.assertEqual(evaluate_numeric(10, flat_deltas=[1], factors=[1.3, 1.4]), 20)
        self.assertEqual(evaluate_numeric(1, factors=[1.9, 1.9]), 3)

    def test_base_percentage_is_not_a_flat_value(self):
        self.assertEqual(evaluate_numeric(100, base_ratio_deltas=[1.5, .5], factors=[1.25, 1.25]), 468)

    def test_fixed_terms_are_applied_before_same_zone_percentages(self):
        self.assertEqual(evaluate_numeric(100, flat_deltas=[20], base_ratio_deltas=[.5]), 180)
        self.assertEqual(evaluate_numeric(10, flat_deltas=[-2], base_ratio_deltas=[-.5]), 4)
        self.assertEqual(evaluate_numeric(101, flat_deltas=[2], base_ratio_deltas=[.2, .35], factors=[1.25]), 199)

    def test_domains_targets_and_conditions_are_not_conflated(self):
        first = deepcopy(self.definitions["relic_126"]["effects"][0])
        first.pop("valueRule")
        first.pop("aggregation")
        second = deepcopy(first)
        second["id"] = "test.second"
        second["value"] = .5
        other = deepcopy(second)
        other["domain"] = "outside_battle"
        other["target"]["metric"] = "physical_damage_taken"
        summary = summarize_numeric([first, second, other])
        self.assertEqual(len(summary), 2)
        self.assertEqual(summary[0]["baseRatioDelta"], "2.0")
        self.assertEqual(summary[1]["baseRatioDelta"], "0.5")

    def test_ordinary_bool_and_stacking_bool_rejected(self):
        definition = deepcopy(self.definitions["relic_123"])
        validate_runtime_state(definition, {"value": None})
        with self.assertRaises(ValueError):
            validate_runtime_state(definition, {"value": False})
        definition["management"]["kind"] = "stacking"
        validate_runtime_state(definition, {"value": 3})
        with self.assertRaises(ValueError):
            validate_runtime_state(definition, {"value": True})

    def test_used_enchantment_keeps_granted_effect(self):
        definition = deepcopy(self.definitions["relic_123"])
        definition["management"] = {"kind": "one_shot", "bindOperator": True, "maxRecipients": 2}
        state = {"value": True, "operatorInstanceIds": ["operator-1", "operator-2"]}
        clause = {"lifetime": "granted_operator_buff"}
        self.assertTrue(clause_enabled(definition, clause, state))
        self.assertFalse(clause_enabled(definition, {"lifetime": "one_shot_trigger"}, state))
        with self.assertRaises(ValueError):
            validate_runtime_state(definition, {"value": True, "operatorInstanceIds": ["same", "same"]})

    def test_immediate_resource_score_not_zeroed(self):
        scorer = RelicScorer()
        self.assertGreater(scorer.fixed_score("relic_015"), 0)
        self.assertGreater(scorer.fixed_score("relic_011"), 0)
        self.assertGreater(scorer.fixed_score("relic_010"), 0)

    def test_management_scope_and_lucky_cookie(self):
        self.assertEqual(management_for("relic_188")["maxRecipients"], 2)
        self.assertFalse(management_for("relic_188")["promotionEffect"])
        self.assertTrue(management_for("relic_177")["promotionEffect"])
        self.assertFalse(management_for("relic_177")["autoPromote"])
        self.assertIsNone(management_for("relic_999"))

    def test_stacking_expiry_preserves_counter(self):
        definition = {"management": management_for("relic_034")}
        state = {"value": 3}
        self.assertTrue(clause_enabled(definition, {}, {"value": 2}))
        self.assertFalse(clause_enabled(definition, {}, state))
        self.assertEqual(state["value"], 3)

    def test_confirmed_curves_not_merged_as_constant_bonuses(self):
        for relic_id in ("relic_126", "relic_127"):
            clause = self.definitions[relic_id]["effects"][0]
            summary = summarize_numeric([clause, clause])
            self.assertEqual(len(summary), 2)
            self.assertTrue(all(row["aggregation"] == "separate" for row in summary))
            self.assertNotIn("baseRatioDelta", summary[0])
            self.assertEqual(summary[0]["valueRule"]["interpolation"], "linear")
            self.assertEqual(summary[0]["valueRule"]["startHpRatio"], 1)
            self.assertEqual(summary[0]["valueRule"]["maximumAtHpRatio"], .3)
            self.assertEqual(clause["reviewStatus"], "confirmed")

    def test_all_batches_load_without_duplicate_ids(self):
        definitions = load_definitions()
        self.assertEqual(len(definitions), 239)
        batch = load_definitions(DEFINITIONS_PATH.parent / "calibration_20.json")
        self.assertEqual(len(batch), 20)
        self.assertFalse(set(batch) & set(self.definitions))

    def test_second_batch_is_reproducible_random_sample(self):
        text_path = DEFINITIONS_PATH.parents[1] / "blackflow_relic_texts.json"
        source = json.loads(text_path.read_text(encoding="utf-8"))["relics"]
        excluded = {row["source"]["prtsNumber"] for row in self.definitions.values()}
        remaining = [row for row in source if row["prts_number"] not in excluded]
        expected = random.Random(20261012).sample(remaining, 20)
        actual = load_definitions(DEFINITIONS_PATH.parent / "calibration_20.json")
        self.assertEqual([row["source"]["prtsNumber"] for row in actual.values()],
                         [row["prts_number"] for row in expected])

    def test_recovery_channels_stay_distinct(self):
        natural = deepcopy(load_definitions()["relic_153"]["effects"][0])
        attack = deepcopy(natural)
        attack["target"]["scope"]["skillRecoveryType"] = "attack"
        attack["target"]["metric"] = "sp_recovery_per_attack"
        self.assertEqual(len(summarize_numeric([natural, attack])), 2)
        self.assertEqual(self.definitions["relic_127"]["effects"][0]["target"]["scope"],
                         {"skillRecoveryType": "natural"})

    def test_deployment_capacity_tracks_current_holdings_without_clamp(self):
        coffee = self.definitions["relic_015"]
        voucher = self.definitions["relic_010"]
        self.assertEqual(deployment_capacity(6, 2, [coffee, voucher]), 11)
        self.assertEqual(deployment_capacity(6, 2, [coffee]), 9)
        self.assertEqual(deployment_capacity(12, 2, [coffee, voucher]), 17)

    def test_difficulty_variant_boundaries(self):
        self.assertEqual([structural_stage(n) for n in (0, 2, 3, 5, 6, 8, 9, 15)],
                         ["structured", "structured", "semi_structured", "semi_structured",
                          "unstructured", "unstructured", "chaotic", "chaotic"])
        with self.assertRaises(ValueError):
            structural_stage(True)

    def test_acquisition_slots_and_barrier_rule(self):
        slot = self.definitions["relic_015"]["effects"][0]
        self.assertEqual(slot["category"], "immediate_resource")
        self.assertEqual(slot["maximum"], 13)
        self.assertFalse(slot["revokeOnLoss"])
        barrier = self.definitions["relic_087"]["effects"][0]
        self.assertEqual(barrier["stackingRule"], "sum_actual_granted_values")


if __name__ == "__main__":
    unittest.main()
