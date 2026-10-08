"""User-confirmed rules remain separate from observed pool composition."""

import copy
import unittest

from fulcrum.map_catalog import TemplateCatalog
from fulcrum.node_identity import contextual_mark_id
from fulcrum.node_rewards import NodeRewardPoolCatalog
from fulcrum.playtime_state import merge_map_observation, new_playtime, set_entry_sandboxes, update_node
from tests.test_playtime_prediction import chain_map


def fifth_map():
    observed = chain_map(5)
    observed["templateId"] = TemplateCatalog().candidates("main", 5)[0].id
    for node in observed["nodes"][1:4]:
        node["templateHint"] = "fate-choice"
    return observed


class ConfirmedRewardTests(unittest.TestCase):
    def setUp(self):
        self.catalog = NodeRewardPoolCatalog()

    def test_distinct_resident_groups_and_guaranteed_combat_choices(self):
        resident = self.catalog.rules_for("nodes", "node_type_019")
        groups = resident["componentGroups"]
        self.assertEqual(len(groups), 2)
        self.assertNotEqual(groups[0]["observationContextId"], groups[1]["observationContextId"])
        for group in groups:
            self.assertEqual((group["candidateCount"], group["takeCount"]), (2, 1))
        for node_id in ("node_type_002", "node_type_003"):
            self.assertEqual(self.catalog.rules_for("nodes", node_id)["componentGroups"][0]["candidateCount"], 2)
        boss = self.catalog.rules_for("nodes", "node_type_003")
        self.assertFalse(boss["requiresSixthFloor"])
        self.assertEqual(boss["ingotsPolicy"], "regional_battle_table")

    def test_event_counts_and_controller_are_not_double_counted(self):
        for event, count, cash in (("encounter_015", 3, 0), ("encounter_016", 4, 50)):
            rule = self.catalog.rules_for("events", event)["emergency"]
            self.assertEqual((rule["eventRelicCount"], rule["cashThreshold"]), (count, cash))
            self.assertFalse(rule["addEmergencyBaseRelic"])
        for event in ("encounter_009", "encounter_010", "encounter_012"):
            self.assertFalse(self.catalog.rules_for("events", event)["controllerConsumed"])
        cave = self.catalog.rules_for("events", "encounter_018")
        self.assertEqual([row["terminates"] for row in cave["results"]], [False, False, True, True])
        self.assertEqual([row["probability"] for row in cave["results"]], [0.25] * 4)
        self.assertEqual(cave["probabilityBasis"], "temporary_uniform_assumption")
        self.assertTrue(self.catalog.rules_for("events", "encounter_021")["freeTravelRequiresUncompletedTarget"])

    def test_lake_occurrence_rate_is_not_event_branch_probability(self):
        ordinary = self.catalog.battle_observations("ro6_t_5")[0]
        relic = next(group for group in ordinary["rewardGroups"] if group["items"][0]["name"] == "藏品")
        self.assertEqual(relic["probability"], 5 / 11)
        self.assertEqual((relic["occurrenceCount"], relic["sampleCount"]), (5, 11))
        paid = self.catalog.rules_for("events", "encounter_017")["paidBranch"]
        self.assertEqual(paid["paymentCount"] * paid["cashPerPayment"], 3)
        self.assertEqual([result["probability"] for result in paid["results"]], [0.8, 0.2])
        ordinary["rewardGroups"].clear()
        self.assertTrue(self.catalog.battle_observations("ro6_t_5")[0]["rewardGroups"])

    def test_exchange_and_dispatch_pool_rules(self):
        exchange = self.catalog.rules_for("nodes", "node_type_008")
        self.assertEqual((exchange["exchangeCountMin"], exchange["exchangeCountMax"]), (1, 2))
        self.assertTrue(exchange["reuseNewItem"])
        dispatch = self.catalog.rules_for("nodes", "node_type_009")
        self.assertEqual(dispatch["componentContextId"], "pool_scrap_3")
        self.assertEqual(len(self.catalog.get(dispatch["componentContextId"])["members"]), 12)

    def test_phase_ignores_optional_battle_rewards_and_fate_subtypes_differ(self):
        optional = self.catalog.rules_for("battles", "optional_boxes")
        self.assertFalse(optional["enabledForScoring"])
        self.assertEqual(optional["phasePolicy"], "existing_main_rewards_only")
        fate = self.catalog.rules_for("nodes", "node_type_012")
        self.assertFalse(fate["fakeNode"]["repeatable"])
        self.assertTrue(fate["fakeNode"]["consumedAfterCompletion"])
        self.assertTrue(fate["trueNode"]["repeatable"])
        self.assertEqual(fate["trueNode"]["choices"], ["leave_without_battle", "fight_ending_2_boss"])


class EndingEntryTests(unittest.TestCase):
    def test_confirming_truth_resolves_other_fates_and_consumed_fake_retains_identity(self):
        state = new_playtime("fate-subtypes")
        instance = merge_map_observation(state, "V", fifth_map(), entry_sandbox_relic_ids=["relic_225"])
        update_node(state, "V", "1,0", fate_role="true")
        self.assertEqual([instance["nodes"][f"{x},0"]["fateRole"] for x in (1, 2, 3)], ["true", "fake", "fake"])
        update_node(state, "V", "2,0", completion="completed", category_id="node_type_020")
        node = instance["nodes"]["2,0"]
        self.assertEqual((node["fateRole"], node["resolvedCategoryId"], node["observedCategoryId"]),
                         ("fake", "node_type_012", "node_type_020"))
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            update_node(state, "V", "2,0", fate_role="fake", confirmed_mark_ids=["node_mark_003"])
        self.assertEqual(state, before)

    def test_zero_one_two_entry_sandboxes_and_no_guessed_true_node(self):
        for ids in ([], ["relic_225"], ["relic_225", "relic_226"]):
            with self.subTest(ids=ids):
                state = new_playtime("fifth-entry")
                instance = merge_map_observation(state, "V", fifth_map(), entry_sandbox_relic_ids=ids)
                expected = 3 if ids else 0
                pool = instance["nodePool"]["fate-choice"]
                self.assertEqual((pool["minimum"], pool["maximum"], pool["knownCount"]), (expected, expected, expected))
                self.assertEqual(instance["ending2Entry"]["paidMarkAllowed"], len(ids) == 1)
                self.assertEqual(instance["ending2Entry"]["autoMarkTrueNode"], len(ids) == 2)
                self.assertTrue(all("node_mark_003" not in node["confirmedMarkIds"] for node in instance["nodes"].values()))

    def test_entry_snapshot_survives_later_inventory_and_map_updates(self):
        state = new_playtime("fifth-entry")
        observed = fifth_map()
        instance = merge_map_observation(state, "V", observed, entry_sandbox_relic_ids=["relic_225"])
        state["relics"].clear()
        merge_map_observation(state, "V", observed)
        self.assertEqual(instance["entrySandboxRelicIds"], ["relic_225"])
        set_entry_sandboxes(state, ["relic_225", "relic_226"])
        self.assertTrue(instance["ending2Entry"]["autoMarkTrueNode"])
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            set_entry_sandboxes(state, ["relic_225", "relic_225"])
        self.assertEqual(state, before)

    def test_missing_entry_information_remains_unknown(self):
        state = new_playtime("late-import")
        instance = merge_map_observation(state, "V", fifth_map())
        self.assertEqual(instance["ending2Entry"]["status"], "unknown")
        self.assertNotIn("entrySandboxRelicIds", instance)
        self.assertEqual(instance["nodePool"]["fate-choice"]["maximum"], 3)

    def test_same_icon_maps_to_different_identity_by_main_floor(self):
        self.assertEqual(contextual_mark_id("node_mark_003", "main", 3), "node_mark_002")
        self.assertEqual(contextual_mark_id("node_mark_002", "main", 5), "node_mark_003")
        self.assertIsNone(contextual_mark_id("node_mark_002", "main", 1))
        state = new_playtime("same-icon")
        observed = fifth_map()
        observed["nodes"][2]["marks"] = [{"id": "node_mark_002", "status": "confirmed"}]
        instance = merge_map_observation(state, "V", observed)
        node = instance["nodes"]["2,0"]
        self.assertEqual(node["confirmedMarkIds"], ["node_mark_003"])
        self.assertIsNone(node["encounterId"])
        update_node(state, "V", "3,0", confirmed_mark_ids=["node_mark_003"])
        self.assertEqual(instance["nodes"]["3,0"]["resolvedCategoryId"], "node_type_012")

    def test_manual_informant_mark_is_not_silently_changed_into_truth(self):
        from fulcrum.ending_prediction import planning_check
        state = new_playtime("manual-mark")
        instance = merge_map_observation(state, "V", fifth_map())
        update_node(state, "V", "3,0", confirmed_mark_ids=["node_mark_002"])
        self.assertEqual(instance["nodes"]["3,0"]["confirmedMarkIds"], ["node_mark_002"])
        self.assertIn("mark_floor", {row["code"] for row in planning_check(state, instance)["conflicts"]})


if __name__ == "__main__":
    unittest.main()
