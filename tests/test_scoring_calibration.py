from itertools import permutations
import unittest

from fulcrum.scoring_calibration import (
    SEED_POINTS, action_opportunity_score, component_reference_points, evaluate_team_threshold,
    dispatch_reference_score, expected_best_score, experience_reward_score, green_merchant_base_score,
    merchant_reference_score,
    painted_component_relic_bonus, team_threshold, ticket_reference_points,
)
from scripts.calibrate_node_scores import build_report, markdown


class TeamThresholdTests(unittest.TestCase):
    def test_normal_thresholds(self) -> None:
        expected = ((0, 0, 0), (1, 2, 5), (2, 4, 6), (3, 6, 8), (5, 8, 10), (7, 9, 13))
        for floor, (e2, six, total) in enumerate(expected, 1):
            self.assertEqual(team_threshold(floor), {
                "elite2SixStars": e2, "sixStars": six, "totalOperators": total})

    def test_dual_squad_adjustments_only_affect_floors_two_and_three(self) -> None:
        for squad in ("squad_005", "squad_006", "squad_007", "squad_008"):
            self.assertEqual(team_threshold(2, squad), {"elite2SixStars": 2, "sixStars": 3, "totalOperators": 5})
            self.assertEqual(team_threshold(3, squad), {"elite2SixStars": 3, "sixStars": 6, "totalOperators": 6})
            for floor in (1, 4, 5, 6):
                self.assertEqual(team_threshold(floor, squad), team_threshold(floor))
        for squad in ("squad_009", "squad_010", "squad_011"):
            self.assertEqual(team_threshold(3, squad), team_threshold(3))

    def test_extra_e2_substitutes_for_e1(self) -> None:
        self.assertTrue(evaluate_team_threshold(floor=2, total_operators=5, six_star_operators=2,
                                              elite2_six_star_operators=2)["met"])
        self.assertTrue(evaluate_team_threshold(floor=3, total_operators=6, six_star_operators=4,
                                              elite2_six_star_operators=4)["met"])

    def test_all_three_counts_are_required(self) -> None:
        for total, six, e2 in ((5, 4, 2), (6, 3, 2), (6, 4, 1)):
            self.assertFalse(evaluate_team_threshold(floor=3, total_operators=total,
                                                   six_star_operators=six, elite2_six_star_operators=e2)["met"])
        self.assertTrue(evaluate_team_threshold(floor=1, total_operators=0, six_star_operators=0,
                                              elite2_six_star_operators=0)["met"])

    def test_invalid_counts_do_not_silently_become_a_threshold_state(self) -> None:
        for total, six, e2 in ((4, 5, 2), (5, 2, 3), (5, None, 1), (True, 0, 0)):
            with self.assertRaises(ValueError):
                evaluate_team_threshold(floor=2, total_operators=total, six_star_operators=six,
                                        elite2_six_star_operators=e2)
        for floor in (0, 7, True):
            with self.assertRaises(ValueError):
                team_threshold(floor)


class CalibrationMathTests(unittest.TestCase):
    def xp(self, **changes) -> dict:
        return experience_reward_score(**{
            "level": 1, "experience": 0, "reward": 13, "below_threshold": True,
            "hope_deficit": 20, **changes})

    def test_experience_crosses_levels_and_preserves_real_fraction_distinction(self) -> None:
        result = self.xp()
        self.assertEqual((result["levelAfter"], result["experienceAfter"], result["actualHopeAward"]), (2, 3, 4))
        self.assertEqual(result["progressHopeEquivalent"], 4.5)
        self.assertEqual(result["points"], 281.25)

    def test_partial_value_uses_full_interval_not_remaining_interval(self) -> None:
        result = self.xp(experience=9, reward=1)
        self.assertEqual(result["actualHopeAward"], 4)
        self.assertEqual(result["progressHopeEquivalent"], 0.4)
        self.assertEqual(result["points"], 25)

    def test_caps_and_condition_multiplier(self) -> None:
        self.assertEqual(self.xp(hope_deficit=1)["points"], 62.5)
        self.assertEqual(self.xp(reference_six_star_cost=5)["points"], 562.5)
        self.assertEqual(self.xp(below_threshold=False)["points"], 0)
        self.assertEqual(self.xp(hope_deficit=0)["points"], 0)
        self.assertEqual(self.xp(level=10)["points"], 0)
        self.assertEqual(self.xp(reward=490, hope_deficit=100)["actualHopeAward"], 50)
        self.assertEqual(self.xp(level=9, experience=94, reward=100)["levelAfter"], 10)

    def test_invalid_experience_inputs(self) -> None:
        for changes in ({"level": 11}, {"experience": 10}, {"reward": -1},
                        {"hope_deficit": float("nan")}, {"reference_six_star_cost": 0},
                        {"below_threshold": 1}):
            with self.assertRaises(ValueError):
                self.xp(**changes)

    def test_seed_override_does_not_recalculate_statistical_derivation(self) -> None:
        self.assertEqual(SEED_POINTS, 250)
        self.assertEqual(component_reference_points("component_001"), 250)
        self.assertEqual(component_reference_points("component_001", action_unit=0), 250)

    def test_all_components_and_remaining_uses(self) -> None:
        for index in range(1, 31):
            self.assertGreater(component_reference_points(f"component_{index:03}"), 0)
        self.assertEqual(component_reference_points("component_023"), 300)
        self.assertEqual(component_reference_points("component_015", remaining_uses=1), 10)
        self.assertEqual(component_reference_points("component_024"), 810)
        self.assertEqual(component_reference_points("component_019"), 220)
        self.assertEqual(component_reference_points("component_004", existing_same=2), 550)
        self.assertEqual(component_reference_points("component_007"), 200)
        with self.assertRaises(ValueError):
            component_reference_points("component_015", remaining_uses=4)

    def test_direct_promotion_doubles_corresponding_ticket_before_same_conditions(self) -> None:
        for group, squad in (("突击", "squad_005"), ("堡垒", "squad_006"),
                             ("远程", "squad_007"), ("破坏", "squad_008")):
            for chosen_squad in (None, squad, "squad_009"):
                for below in (False, True):
                    normal = ticket_reference_points(f"{group}协议招募券", squad_id=chosen_squad, below_threshold=below)
                    elite = ticket_reference_points(f"精英{group}招募券", squad_id=chosen_squad, below_threshold=below)
                    self.assertEqual(elite, 2 * normal)
        self.assertEqual(ticket_reference_points("精英突击招募券"), 150)
        self.assertEqual(ticket_reference_points("精英突击招募券", squad_id="squad_005", below_threshold=True), 281.25)
        self.assertEqual(ticket_reference_points("前线统合资深招募券"), 125)

    def test_distinct_candidates_match_weighted_ordered_pairs(self) -> None:
        outcomes = [(10, 0.2), (100, 0.3), (200, 0.5)]
        brute_force = sum(max(first[0], second[0]) * first[1] * second[1] / (1 - first[1])
                          for first, second in permutations(outcomes, 2))
        result = expected_best_score(outcomes, candidate_count=2)
        self.assertAlmostEqual(result["expectedBest"], brute_force)
        self.assertEqual(result["model"], "weighted_without_replacement")
        self.assertLessEqual(result["lowerBound"], result["expectedBest"])
        self.assertGreaterEqual(result["upperBound"], result["expectedBest"])
        self.assertEqual(expected_best_score([(10, .99), (100, .01)], candidate_count=2)["expectedBest"], 100)
        self.assertEqual(expected_best_score([(100, .5), (100, .5)], candidate_count=2)["expectedBest"], 100)
        self.assertEqual(expected_best_score(outcomes)["expectedBest"], 132)
        with self.assertRaises(ValueError):
            expected_best_score([(100, 1)], candidate_count=2)

    def test_invalid_distributions(self) -> None:
        for outcomes in ([], [(100, 0.5)], [(100, -1), (10, 2)], [(float("nan"), 1)]):
            with self.assertRaises(ValueError):
                expected_best_score(outcomes)


class NodeScoreReportTests(unittest.TestCase):
    def test_report_covers_node_types_without_converting_missing_values_to_zero(self) -> None:
        report = build_report()
        self.assertEqual([row["id"] for row in report["nodes"]], [f"node_type_{i:03}" for i in range(1, 23)])
        self.assertEqual(report["parameters"]["seedPoints"], 250)
        self.assertAlmostEqual(report["merchants"]["greenMet"]["points"], green_merchant_base_score(50) + 100)
        self.assertEqual(report["encounters"]["met"]["points"], report["encounters"]["met"]["knownContribution"])
        self.assertEqual(report["encounters"]["met"]["missingTerms"], [])
        self.assertIn("同池的不同物品", markdown(report))
        self.assertNotIn("nan", markdown(report))
        for row in report["combat"]:
            self.assertAlmostEqual(sum(row["met"]["parts"].values()), row["met"]["total"])
            if row["floor"] == 1:
                self.assertIsNone(row["unmet"])

    def test_max_level_turns_experience_value_off_but_keeps_ticket_deficit_weight(self) -> None:
        report = build_report(level=10)
        for row in report["combat"]:
            if row["unmet"]:
                self.assertEqual(row["unmet"]["parts"]["experience"], 0)
                self.assertAlmostEqual(row["unmet"]["parts"]["tickets"], 1.25 * row["met"]["parts"]["tickets"])

    def test_painted_arrival_adds_actual_relics_not_inventory_value(self) -> None:
        report = build_report(painted_agor=1, painted_perro=2)
        self.assertEqual(report["paintedBonuses"]["wish"]["points"], 200)
        self.assertEqual(report["paintedBonuses"]["exchange"]["points"], 200)
        walking = build_report(painted_agor=1, painted_perro=2, arrives_by_processing=False)
        self.assertEqual(walking["paintedBonuses"]["wish"]["points"], 0)
        self.assertEqual(walking["paintedBonuses"]["exchange"]["points"], 0)

    def test_treehole_uses_frozen_map_marginals_when_supplied(self) -> None:
        report = build_report(opportunity_scores=[1000, 600, 400, 300, 100, 50, 20, 10], action_points=6)
        self.assertEqual(report["treehole"]["points"], 80)
        self.assertFalse(report["treehole"]["deductSacrificedComponentUtility"])
        self.assertEqual(build_report(opportunity_scores=[])["treehole"]["points"], 0)
        self.assertEqual(build_report(processed_count=0)["treehole"]["points"], 0)
        self.assertEqual(build_report()["treehole"]["points"], 600)

    def test_encounter_probabilities_preserve_missing_values_and_exclude_only_ineligible(self) -> None:
        report = build_report()
        before = report["encounters"]["met"]
        self.assertAlmostEqual(sum(row["probability"] for row in before["events"]), 1)
        self.assertEqual(len(before["events"]), 13)
        self.assertEqual({row["id"] for row in before["excluded"]}, {"encounter_010", "encounter_021"})
        self.assertAlmostEqual(before["knownContribution"], sum(row["contribution"] for row in before["events"]))
        agency = next(row for row in before["events"] if row["id"] == "encounter_019")
        self.assertEqual(agency["knownPoints"], 100)
        self.assertGreater(agency["probability"], 0)
        after = build_report(completed_events=("encounter_018", "encounter_005", "encounter_003"))["encounters"]["met"]
        after_ids = {row["id"] for row in after["events"]}
        self.assertNotIn("encounter_018", after_ids)
        self.assertTrue({"encounter_005", "encounter_003"} <= after_ids)
        self.assertAlmostEqual(sum(row["probability"] for row in after["events"]), 1)
        self.assertGreater(next(row for row in after["events"] if row["id"] == agency["id"])["probability"], agency["probability"])

    def test_agency_and_lake_provisional_values_close_the_default_event_formula(self) -> None:
        report = build_report()
        for key, agency_points in (("met", 100), ("unmet", 125)):
            events = {row["id"]: row for row in report["encounters"][key]["events"]}
            self.assertEqual(events["encounter_019"]["knownPoints"], agency_points)
            self.assertEqual(events["encounter_017"]["missingTerms"], [])
            self.assertIsNotNone(report["encounters"][key]["points"])
        pool = next(row for row in report["pools"] if row["contextId"] == "node_battle_elite_scrap")
        lake = next(row for row in report["encounters"]["met"]["events"] if row["id"] == "encounter_017")
        self.assertAlmostEqual(lake["knownPoints"], 292.2 + 0.8 * pool["expectedBest"])

    def test_exchange_proxy_is_not_the_painted_bonus_or_an_actual_resource_grant(self) -> None:
        report = build_report(painted_agor=1)
        self.assertEqual(report["exchangeOpportunityPoints"], 200)
        self.assertTrue(report["nodes"][7]["score"].startswith("400.00"))
        self.assertTrue(build_report()["nodes"][7]["score"].startswith("200.00"))

    def test_dispatch_keeps_promotion_reference_in_met_state_and_excludes_it_from_ending3(self) -> None:
        report = build_report()
        for key in ("met", "unmet"):
            ordinary = report["dispatch"][key]["ordinary"]
            ending = report["dispatch"][key]["ending3"]
            self.assertEqual(ordinary["parts"]["promotion"], 93.75)
            self.assertEqual(ending["parts"]["promotion"], 0)
            self.assertAlmostEqual(ordinary["points"] - ending["points"], 93.75)
        self.assertEqual(report["dispatch"]["met"]["ordinary"]["parts"]["delayedHope"], 0)
        self.assertEqual(report["dispatch"]["unmet"]["ordinary"]["parts"]["delayedHope"], 70)

    def test_boss_lower_met_score_is_a_pool_effect_not_a_missing_relic(self) -> None:
        report = build_report()
        boss = next(row for row in report["combat"] if row["floor"] == 3 and row["name"] == "险路恶敌")
        elite = next(row for row in report["combat"] if row["floor"] == 3 and row["name"] == "紧急作战")
        self.assertEqual(boss["met"]["parts"]["relics"], 200)
        self.assertEqual(elite["met"]["parts"]["relics"], 125)
        self.assertLess(boss["met"]["parts"]["components"], elite["met"]["parts"]["components"])
        self.assertLess(boss["met"]["total"], elite["met"]["total"])
        self.assertGreater(boss["unmet"]["total"], elite["unmet"]["total"])


class OpportunityCalibrationTests(unittest.TestCase):
    def test_dispatch_discount_applies_only_to_delayed_processing_and_hope(self) -> None:
        result = dispatch_reference_score(processed_points=100, hope_points=100, grants_promotion=True)
        self.assertEqual(result["parts"], {"delayedProcessing": 70, "delayedHope": 70, "promotion": 93.75})
        self.assertEqual(result["points"], 233.75)
        self.assertEqual(dispatch_reference_score(processed_points=100, hope_points=100, grants_promotion=False)["points"], 140)
        for changes in ({"processed_points": -1}, {"hope_points": float("nan")}, {"grants_promotion": 1}):
            with self.assertRaises(ValueError):
                dispatch_reference_score(**{"processed_points": 100, "hope_points": 100, "grants_promotion": True, **changes})

    def test_action_reward_is_the_next_values_not_first_value_times_gain(self) -> None:
        values = [0, -1, 50, 600, 1000, 400, 10]
        score = action_opportunity_score(values, action_points=2, gain=3)
        self.assertEqual(score["marginals"], [600, 400, 50])
        self.assertEqual(score["points"], 1050)
        self.assertEqual(action_opportunity_score(values, action_points=2, gain=3, pursuit=True)["points"], 460)
        self.assertEqual(action_opportunity_score([], action_points=0, gain=2)["points"], 0)
        self.assertEqual(action_opportunity_score(values, action_points=20, gain=3)["unusedGain"], 3)
        for changes in ({"action_points": True}, {"gain": -1}, {"pursuit": 1}, {"node_scores": [float("nan")]}):
            kwargs = {"node_scores": values, "action_points": 2, "gain": 3, **changes}
            with self.assertRaises(ValueError):
                action_opportunity_score(**kwargs)

    def test_painted_rewards_require_the_matching_node_and_first_processed_arrival(self) -> None:
        for category, count in (("node_type_007", 2), ("node_type_008", 6), ("node_type_020", 0)):
            kwargs = {"category_id": category, "painted_agor": 3, "painted_perro": 2, "arrives_by_processing": True}
            self.assertEqual(painted_component_relic_bonus(**kwargs)["extraRelics"], count)
            self.assertEqual(painted_component_relic_bonus(**{**kwargs, "arrives_by_processing": False})["points"], 0)
            self.assertEqual(painted_component_relic_bonus(**{**kwargs, "first_reward": False})["points"], 0)

    def shop(self, **changes) -> dict:
        return merchant_reference_score(**{
            "category_id": "node_type_004", "floor": 3, "cash": 50, "estimated_value": 0,
            "box_capacity": 8, "box_count": 3, "yellow_visited": True,
            "eligible_event_ids": ["encounter_005"], "below_threshold": False, **changes})

    def test_merchant_prices_and_coupon_mix(self) -> None:
        base = green_merchant_base_score(50)
        self.assertAlmostEqual(self.shop()["points"], base + 100)
        self.assertAlmostEqual(self.shop(below_threshold=True)["points"], base + 125)
        for squad in ("squad_005", "squad_006", "squad_007", "squad_008"):
            row = self.shop(squad_id=squad)
            self.assertAlmostEqual(row["points"], base + 131.25)
            self.assertEqual(row["secondTicket"], 75)
            self.assertEqual(row["ticketMix"], "random_single_plus_home_single")
            self.assertAlmostEqual(self.shop(squad_id=squad, below_threshold=True)["points"], base + 164.0625)
        self.assertEqual(self.shop(category_id="node_type_013", yellow_visited=False)["points"], 1000)

    def test_merchant_conditions_and_repeat_do_not_grant_tickets(self) -> None:
        self.assertAlmostEqual(self.shop(yellow_visited=False)["points"], green_merchant_base_score(50) + 100)
        self.assertAlmostEqual(self.shop(yellow_visited=False, below_threshold=True)["points"], green_merchant_base_score(50) + 125)
        self.assertAlmostEqual(self.shop(yellow_visited=False, reserve_override=20)["points"], green_merchant_base_score(30) + 100)
        self.assertAlmostEqual(self.shop(eligible_event_ids=["encounter_016"])["points"], green_merchant_base_score(50) + 100)
        self.assertEqual(self.shop(cash=0)["points"], 0)
        self.assertEqual(self.shop(category_id="node_type_013", yellow_visited=False, cash=20)["points"], 600)
        self.assertEqual(self.shop(category_id="node_type_013", yellow_visited=False, cash=0, estimated_value=21)["points"], 630)
        self.assertAlmostEqual(self.shop(first_visit=False)["points"], 0.8 * self.shop()["parts"]["entry"])
        self.assertEqual(self.shop(first_visit=False)["parts"]["tickets"], 0)
        self.assertFalse(self.shop()["preferences"]["mutatesPlaytime"])


if __name__ == "__main__":
    unittest.main()
