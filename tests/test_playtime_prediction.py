"""Snapshot updates and local node prediction remain consistent over a run."""

from __future__ import annotations

import copy
import json
import unittest

from fulcrum.playtime_state import active_instance, merge_map_observation, new_playtime, update_node, validate_playtime
from fulcrum.node_predictor import PREDICTION_DATA_PATH, _area_frequency, _catalogs, predict_instance
from fulcrum.map_catalog import TemplateCatalog
from fulcrum.playtime_view import render_map_sections


DATA = json.loads(PREDICTION_DATA_PATH.read_text(encoding="utf-8"))


def chain_map(floor: int, *, length: int = 6) -> dict:
    return {
        "success": True, "area": "main", "floor": floor,
        "templateId": "floor-3-01" if floor == 3 else "floor-4-11",
        "templateSourceRegionId": f"floor_{floor}", "screenshot": "test.png",
        "nodes": [
            {
                "id": f"{x},0", "coord": [x, 0], "slot": [x, 0],
                "categoryId": "start" if x == 0 else "unknown_mystery",
                "visibility": "revealed" if x == 0 else "hidden", "marks": [],
                "templateHint": None,
            }
            for x in range(length)
        ],
        "edges": [[f"{x},0", f"{x + 1},0"] for x in range(length - 1)],
    }


def types(state: dict, area: str, node_id: str) -> set[str]:
    prediction = active_instance(state, area)["prediction"]
    return {row["nodeType"] for row in prediction["unknownNodes"][node_id]["candidates"]}


def event_candidates(instance: dict) -> set[str]:
    return {row["id"] for row in instance["prediction"]["encounterPool"]["candidates"]}


def treehole_map(floor: int) -> dict:
    template = TemplateCatalog().candidates("treehole", floor)[0]
    return {**chain_map(floor), "area": "treehole", "templateId": template.id}


class PlaytimePredictionTests(unittest.TestCase):
    def test_multi_move_merge_keeps_identity_and_requires_completion_confirmation(self):
        state = new_playtime("merge-review")
        instance = merge_map_observation(state, "III", chain_map(3))
        update_node(state, "III", "2,0", category_id="node_type_011", completion="pending")
        update_node(state, "III", "3,0", category_id="node_type_006", encounter_id="encounter_009", completion="pending")
        observed = chain_map(3)
        for index in (2, 3):
            observed["nodes"][index]["categoryId"] = "node_type_020"
        merge_map_observation(state, "III", observed)
        self.assertEqual(instance["nodes"]["2,0"]["resolvedCategoryId"], "node_type_011")
        self.assertEqual(instance["nodes"]["3,0"]["encounterId"], "encounter_009")
        self.assertEqual(instance["nodes"]["3,0"]["completion"], "pending")
        for node_id in ("2,0", "3,0"):
            update_node(state, "III", node_id, completion="completed")
        merge_map_observation(state, "III", observed)
        self.assertEqual(instance["nodes"]["3,0"]["completedCategoryId"], "node_type_006")
        self.assertNotIn("encounter_009", event_candidates(instance))
        self.assertEqual(len(state["areas"]["III"]["instances"]), 1)

    def test_multiple_exits_are_fixed_but_shop_candidates_remain_uncertain(self) -> None:
        state = new_playtime("hint-candidates")
        observed = chain_map(3)
        for index, hint in ((1, "rogue-trader"), (2, "rogue-trader"), (3, "danger-end"), (4, "danger-end")):
            observed["nodes"][index]["templateHint"] = hint
        observed["nodes"][3]["categoryId"] = "node_type_015"
        instance = merge_map_observation(state, "III", observed)
        self.assertEqual(instance["nodes"]["3,0"]["resolvedCategoryId"], "node_type_015")
        self.assertEqual(instance["nodes"]["4,0"]["resolvedCategoryId"], "node_type_015")
        for node_id in ("1,0", "2,0"):
            self.assertIsNone(instance["nodes"][node_id]["resolvedCategoryId"])
            self.assertEqual(instance["nodes"][node_id]["observedCategoryId"], "unknown_mystery")
        merge_map_observation(state, "III", observed)
        self.assertIsNone(instance["nodes"]["2,0"]["resolvedCategoryId"])

    def test_unique_exit_hint_can_resolve_an_unrevealed_terminal(self) -> None:
        state = new_playtime("unique-exit-hint")
        observed = chain_map(3)
        observed["nodes"][-1]["templateHint"] = "danger-end"
        instance = merge_map_observation(state, "III", observed)
        self.assertEqual(instance["nodes"]["5,0"]["resolvedCategoryId"], "node_type_015")

    def test_manual_node_editor_corrects_category_and_multiple_marks_without_log(self) -> None:
        state = new_playtime("manual-map")
        instance = merge_map_observation(state, "III", chain_map(3))
        node = update_node(state, "III", "2,0", category_id="node_type_007",
                           confirmed_mark_ids=["node_mark_001", "node_mark_007"], visibility="revealed")
        self.assertEqual(node["resolvedCategoryId"], "node_type_007")
        self.assertEqual(node["confirmedMarkIds"], ["node_mark_001", "node_mark_007"])
        update_node(state, "III", "2,0", category_id="node_type_018", confirmed_mark_ids=["node_mark_007"])
        self.assertEqual(node["resolvedCategoryId"], "node_type_018")
        self.assertEqual(node["confirmedMarkIds"], ["node_mark_007"])
        before = copy.deepcopy(state)
        with self.assertRaisesRegex(ValueError, "visibility"):
            update_node(state, "III", "2,0", category_id="node_type_006", visibility="invalid")
        self.assertEqual(state, before)
        update_node(state, "III", "2,0", confirmed_mark_ids=[])
        self.assertEqual(node["confirmedMarkIds"], [])
        self.assertIs(instance["nodes"]["2,0"], node)
        self.assertEqual(len(state["areas"]["III"]["instances"]), 1)

    def test_ten_area_slots_include_remembrance_and_treeholes(self) -> None:
        state = new_playtime("run-1")
        self.assertEqual(len(state["areas"]), 10)
        self.assertEqual(state["areas"]["IV-remembrance"]["floor"], 4)
        self.assertEqual(
            {row["id"] for row in state["areas"]["III-treehole"]["encounterPool"]},
            {row["id"] for row in state["areas"]["III"]["encounterPool"]},
        )
        self.assertEqual(len(state["globalEncounterPool"]), 23)

    def test_distance_frequency_is_not_renormalized_and_count_cap_updates(self) -> None:
        state = new_playtime("run-2")
        instance = merge_map_observation(state, "III", chain_map(3), player_position="0,0")
        self.assertIn("narrow-meet", types(state, "III", "3,0"))
        self.assertNotIn("wrong-turn", types(state, "III", "3,0"))
        self.assertIn("wrong-turn", types(state, "III", "5,0"))
        candidates = instance["prediction"]["unknownNodes"]["3,0"]["candidates"]
        narrow = next(row for row in candidates if row["nodeType"] == "narrow-meet")
        counts = DATA["distanceSamples"]["narrow-meet"]["2"]
        self.assertEqual(narrow["distanceSampleCount"], counts["3"])
        self.assertEqual(narrow["typeSampleCount"], sum(counts.values()))
        self.assertAlmostEqual(narrow["distanceFrequency"], counts["3"] / sum(counts.values()))
        self.assertNotAlmostEqual(sum(row["distanceFrequency"] or 0 for row in candidates), 1)
        at_two = instance["prediction"]["unknownNodes"]["2,0"]["categories"]
        self.assertFalse(at_two["encounter"]["isCandidate"])
        self.assertEqual(at_two["encounter"]["distanceFrequency"], 0)
        self.assertFalse(at_two["wrong-turn"]["isCandidate"])
        self.assertEqual(at_two["wrong-turn"]["distanceFrequency"], 0)
        zero_state = new_playtime("run-2-zero")
        distant = merge_map_observation(zero_state, "III", chain_map(3, length=17))
        sampled = distant["prediction"]["unknownNodes"]["12,0"]["categories"]["emergency-aid"]
        self.assertTrue(sampled["isCandidate"])
        self.assertEqual(sampled["distanceSampleCount"], DATA["distanceSamples"]["emergency-aid"]["2"]["12"])
        beyond_range = distant["prediction"]["unknownNodes"]["16,0"]["categories"]["emergency-aid"]
        self.assertFalse(beyond_range["isCandidate"])
        self.assertEqual(beyond_range["distanceFrequency"], 0)

        update_node(state, "III", "2,0", category_id="node_type_011", completion="completed")
        self.assertNotIn("narrow-meet", types(state, "III", "3,0"))
        self.assertIn("encounter", types(state, "III", "3,0"))
        self.assertEqual(instance["nodePool"]["narrow-meet"]["completedCount"], 1)
        self.assertEqual(instance["nodePool"]["narrow-meet"]["maximumRemaining"], 0)

    def test_reimport_preserves_original_type_and_completion(self) -> None:
        state = new_playtime("run-3")
        observed = chain_map(3)
        instance = merge_map_observation(state, "III", observed)
        update_node(state, "III", "2,0", category_id="node_type_011", completion="completed")
        next_image = copy.deepcopy(observed)
        next_image["nodes"][2]["categoryId"] = "node_type_020"
        next_image["nodes"][2]["visibility"] = "revealed"
        merge_map_observation(state, "III", next_image)
        node = instance["nodes"]["2,0"]
        self.assertEqual(node["observedCategoryId"], "node_type_020")
        self.assertEqual(node["resolvedCategoryId"], "node_type_011")
        self.assertEqual(node["completion"], "completed")
        self.assertEqual(len(state["areas"]["III"]["instances"]), 1)
        self.assertNotIn("narrow-meet", types(state, "III", "3,0"))

    def test_confirmed_map_import_updates_position_and_readable_hud_only(self) -> None:
        state = new_playtime("run-hud")
        observed = chain_map(3)
        observed["playerPositionObservation"] = {"status": "recognized", "nodeId": "2,0"}
        observed["resourceObservation"] = {"fields": {
            "hope": {"value": 9, "status": "recognized"},
            "life": {"current": 3, "max": 8, "status": "recognized"},
            "shield": {"value": 0, "status": "absent_zero"},
            "originium_ingot": {"value": 99, "status": "needs_review"},
            "action_points": {"value": 5, "status": "recognized"},
        }}
        instance = merge_map_observation(state, "III", observed)
        self.assertEqual(instance["playerPosition"], "2,0")
        self.assertEqual(instance["actionPoints"], 5)
        self.assertEqual(state["resources"]["hope"], 9)
        self.assertEqual(state["resources"]["life"], {"current": 3, "max": 8})
        self.assertEqual(state["resources"]["shield"], 0)
        self.assertEqual(state["resources"]["originiumIngot"], 20)

        next_image = copy.deepcopy(observed)
        next_image["playerPositionObservation"] = {"status": "needs_review", "nodeId": "3,0"}
        next_image["resourceObservation"]["fields"]["action_points"] = {"value": None, "status": "unreadable"}
        merge_map_observation(state, "III", next_image)
        self.assertEqual(instance["playerPosition"], "2,0")
        self.assertEqual(instance["playerPositionCandidate"], "3,0")
        self.assertEqual(instance["actionPoints"], 5)
        merge_map_observation(state, "III", next_image, player_position="1,0")
        self.assertEqual(instance["playerPosition"], "1,0")
        self.assertIsNone(instance["playerPositionCandidate"])

    def test_same_node_confirmation_does_not_double_count_encounter(self) -> None:
        state = new_playtime("run-4")
        merge_map_observation(state, "III", chain_map(3))
        for _ in range(2):
            update_node(state, "III", "2,0", category_id="node_type_006", encounter_id="encounter_009", completion="completed")
        event = next(row for row in state["globalEncounterPool"] if row["id"] == "encounter_009")
        self.assertEqual(event["completedCount"], 1)
        self.assertEqual(event["completedAt"], ["III-1:2,0"])
        self.assertEqual(active_instance(state, "III")["nodePool"]["encounter"]["knownCount"], 1)

    def test_completed_once_event_is_removed_from_predictions_and_correction_restores_it(self) -> None:
        state = new_playtime("event-exclusion")
        third = merge_map_observation(state, "III", chain_map(3))
        fourth = merge_map_observation(state, "IV", chain_map(4))
        remembered = merge_map_observation(state, "IV-remembrance", chain_map(4))
        hole = merge_map_observation(state, "IV-treehole", treehole_map(4))
        before = copy.deepcopy(fourth["prediction"]["unknownNodes"])
        update_node(state, "III", "2,0", encounter_id="encounter_009", completion="pending")
        for instance in (third, fourth, remembered, hole):
            self.assertIn("encounter_009", event_candidates(instance))
        update_node(state, "III", "2,0", completion="completed")
        for instance in (third, fourth, remembered, hole):
            self.assertNotIn("encounter_009", event_candidates(instance))
            excluded = next(row for row in instance["prediction"]["encounterPool"]["excluded"]
                            if row["id"] == "encounter_009")
            self.assertEqual(excluded["eligibility"], "entered")
            self.assertEqual(excluded["completedRun"], 1)
        self.assertEqual(fourth["prediction"]["unknownNodes"], before)
        self.assertNotIn("encounter_009", fourth["prediction"]["encounterNodes"]["4,0"]["eventCandidateIds"])
        self.assertEqual(next(row for row in state["globalEncounterPool"]
                              if row["id"] == "encounter_009")["completedAt"], ["III-1:2,0"])
        cleared = chain_map(3)
        cleared["nodes"][2]["categoryId"] = "node_type_020"
        merge_map_observation(state, "III", cleared)
        self.assertNotIn("encounter_009", event_candidates(fourth))
        update_node(state, "III", "2,0", completion="pending")
        for instance in (third, fourth, remembered, hole):
            self.assertIn("encounter_009", event_candidates(instance))
        self.assertEqual(third["nodes"]["2,0"]["encounterId"], "encounter_009")

    def test_three_repeatable_events_remain_candidates_after_actual_experience(self) -> None:
        for event_id in ("encounter_002", "encounter_003", "encounter_005"):
            with self.subTest(event=event_id):
                state = new_playtime("repeatable")
                second = merge_map_observation(state, "II", {
                    **chain_map(2), "templateId": "floor-2-02",
                })
                for node_id in ("2,0", "3,0"):
                    update_node(state, "II", node_id, encounter_id=event_id, completion="completed")
                self.assertIn(event_id, event_candidates(second))
                row = next(row for row in second["prediction"]["encounterPool"]["candidates"]
                           if row["id"] == event_id)
                self.assertEqual(row["completedRun"], 2)

    def test_tree_treasure_has_one_main_and_one_treehole_opportunity_not_one_per_floor(self) -> None:
        for first_area in ("III", "III-treehole"):
            with self.subTest(first_area=first_area):
                state = new_playtime("tree-treasure")
                instances = {
                    "III": merge_map_observation(state, "III", chain_map(3)),
                    "IV": merge_map_observation(state, "IV", chain_map(4)),
                    "IV-remembrance": merge_map_observation(state, "IV-remembrance", chain_map(4)),
                    "III-treehole": merge_map_observation(state, "III-treehole", treehole_map(3)),
                    "IV-treehole": merge_map_observation(state, "IV-treehole", treehole_map(4)),
                }
                update_node(state, first_area, "2,0", encounter_id="encounter_018", completion="completed")
                for area, instance in instances.items():
                    same_kind = ("treehole" in area) == ("treehole" in first_area)
                    self.assertEqual("encounter_018" in event_candidates(instance), not same_kind)
                    if same_kind:
                        row = next(row for row in instance["prediction"]["encounterPool"]["excluded"]
                                   if row["id"] == "encounter_018")
                        self.assertEqual(row["eligibility"], "entered_in_this_area_kind")
                other_area = "III" if "treehole" in first_area else "III-treehole"
                update_node(state, other_area, "2,0", encounter_id="encounter_018", completion="completed")
                for instance in instances.values():
                    self.assertNotIn("encounter_018", event_candidates(instance))
                self.assertEqual(next(row for row in state["globalEncounterPool"]
                                      if row["id"] == "encounter_018")["completedCount"], 2)

    def test_event_prediction_separates_fixed_identity_and_resident_override(self) -> None:
        state = new_playtime("event-identities")
        instance = merge_map_observation(state, "III", chain_map(3))
        self.assertNotIn("encounter_022", event_candidates(instance))
        self.assertNotIn("encounter_023", event_candidates(instance))
        update_node(state, "III", "2,0", confirmed_mark_ids=["node_mark_002"])
        update_node(state, "III", "3,0", category_id="node_type_006")
        predicted = instance["prediction"]["encounterNodes"]
        self.assertEqual(predicted["2,0"], {
            "basis": "confirmed_identity", "eventCandidateIds": ["encounter_022"],
        })
        self.assertEqual(set(predicted["3,0"]["eventCandidateIds"]), event_candidates(instance))
        update_node(state, "III", "3,0", confirmed_mark_ids=["node_mark_001"])
        self.assertNotIn("3,0", instance["prediction"]["encounterNodes"])
        update_node(state, "III", "2,0", completion="completed")
        self.assertNotIn("2,0", instance["prediction"]["encounterNodes"])
        marked = next(row for row in instance["prediction"]["encounterPool"]["markedEvents"]
                      if row["id"] == "encounter_022")
        self.assertEqual(marked["eligibility"], "entered")

    def test_event_requirements_use_each_map_instance_not_only_the_active_map(self) -> None:
        state = new_playtime("event-map-conditions")
        observed = chain_map(4, length=3)
        old = merge_map_observation(state, "IV", observed)
        update_node(state, "IV", "1,0", category_id="node_type_019")
        update_node(state, "IV", "2,0", category_id="node_type_001")
        new = merge_map_observation(state, "IV", observed, new_instance=True)
        update_node(state, "IV", "1,0", category_id="node_type_001")
        update_node(state, "IV", "2,0", category_id="node_type_001")
        self.assertIn("encounter_020", event_candidates(old))
        self.assertNotIn("encounter_020", event_candidates(new))

    def test_confirmed_special_mark_resolves_encounter_without_completion(self) -> None:
        state = new_playtime("run-5")
        instance = merge_map_observation(state, "III", chain_map(3))
        update_node(state, "III", "2,0", confirmed_mark_ids=["node_mark_002"])
        node = instance["nodes"]["2,0"]
        self.assertEqual(node["resolvedCategoryId"], "node_type_006")
        self.assertEqual(node["encounterId"], "encounter_022")
        self.assertEqual(node["completion"], "unknown")
        self.assertEqual(next(row for row in state["globalEncounterPool"] if row["id"] == "encounter_022")["completedCount"], 0)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            update_node(state, "III", "2,0", encounter_id="encounter_009")
        with self.assertRaisesRegex(ValueError, "identifying mark"):
            update_node(state, "III", "2,0", clear_encounter=True)
        update_node(state, "III", "2,0", confirmed_mark_ids=[], category_id="node_type_011", clear_encounter=True)
        self.assertIsNone(node["encounterId"])
        self.assertEqual(node["resolvedCategoryId"], "node_type_011")

    def test_resident_on_identified_event_does_not_complete_the_overridden_event(self) -> None:
        for mark, event_id in (("node_mark_002", "encounter_022"), ("node_mark_005", "encounter_023")):
            with self.subTest(mark=mark):
                state = new_playtime("resident-event")
                observed = chain_map(3)
                instance = merge_map_observation(state, "III", observed)
                node = update_node(state, "III", "2,0", confirmed_mark_ids=["node_mark_001", mark],
                                   completion="completed")
                self.assertEqual(node["encounterId"], event_id)
                self.assertEqual(node["resolvedCategoryId"], "node_type_006")
                self.assertEqual(node["completedCategoryId"], "node_type_021")
                def event() -> dict:
                    return next(row for row in state["globalEncounterPool"] if row["id"] == event_id)
                self.assertEqual(event()["completedCount"], 0)
                reading_view = render_map_sections(state)
                self.assertIn("实际完成类别", reading_view)
                self.assertIn("completed | node_type_021", reading_view)
                update_node(state, "III", "2,0", confirmed_mark_ids=[mark], completion="completed")
                observed["nodes"][2]["categoryId"] = "node_type_020"
                observed["nodes"][2]["visibility"] = "revealed"
                merge_map_observation(state, "III", observed)
                self.assertEqual(instance["nodes"]["2,0"]["completedCategoryId"], "node_type_021")
                self.assertEqual(event()["completedCount"], 0)
                self.assertEqual(event()["outcomes"], {})
                self.assertEqual(instance["nodePool"]["encounter"]["knownCount"], 1)
                update_node(state, "III", "2,0", completed_category_id="node_type_006")
                self.assertEqual(event()["completedCount"], 1)
                update_node(state, "III", "2,0", completion="pending")
                self.assertIsNone(node["completedCategoryId"])
                self.assertEqual(event()["completedCount"], 0)

    def test_completed_category_correction_is_validated_before_mutation(self) -> None:
        state = new_playtime("completion-category")
        merge_map_observation(state, "III", chain_map(3))
        before = copy.deepcopy(state)
        for kwargs in ({"completed_category_id": "node_type_021"},
                       {"completion": "completed", "completed_category_id": "unknown_mystery"},
                       {"completion": "completed", "completed_category_id": "invalid"}):
            with self.assertRaises(ValueError):
                update_node(state, "III", "2,0", **kwargs)
            self.assertEqual(state, before)
        node = update_node(state, "III", "2,0", category_id="node_type_006", encounter_id="encounter_009",
                           completion="completed", completed_category_id="node_type_021")
        invalid = copy.deepcopy(state)
        invalid["areas"]["III"]["instances"][0]["nodes"]["2,0"]["completion"] = "pending"
        with self.assertRaises(ValueError):
            validate_playtime(invalid)
        self.assertEqual(node["completedCategoryId"], "node_type_021")

    def test_legacy_completed_resident_does_not_become_an_event_after_clearing_mark(self) -> None:
        state = new_playtime("legacy-resident")
        merge_map_observation(state, "III", chain_map(3))
        node = update_node(state, "III", "2,0", confirmed_mark_ids=["node_mark_001", "node_mark_005"],
                           completion="completed")
        del node["completedCategoryId"]
        validate_playtime(state)
        update_node(state, "III", "2,0", confirmed_mark_ids=["node_mark_005"])
        self.assertEqual(node["completedCategoryId"], "node_type_021")
        self.assertEqual(next(row for row in state["globalEncounterPool"] if row["id"] == "encounter_023")["completedCount"], 0)

    def test_remembrance_uses_separate_distance_rule_and_snapshot(self) -> None:
        state = new_playtime("run-6")
        observed = chain_map(4, length=10)
        normal = merge_map_observation(state, "IV", observed)
        remembered = merge_map_observation(state, "IV-remembrance", observed)
        self.assertNotIn("wrong-turn", types(state, "IV", "9,0"))
        self.assertIn("wrong-turn", types(state, "IV-remembrance", "9,0"))
        self.assertEqual(remembered["predictionDistanceMode"], "remembrance")
        self.assertEqual(remembered["prediction"]["sampleVersion"], DATA["statisticsUpdatedAt"][:10])
        rem_counts = DATA["distanceSamples"]["wrong-turn"]["remembrance"]
        self.assertAlmostEqual(remembered["prediction"]["unknownNodes"]["9,0"]["categories"]["wrong-turn"]["distanceFrequency"], rem_counts.get("9", 0) / sum(rem_counts.values()))
        self.assertIsNot(normal, remembered)
        update_node(state, "IV-remembrance", "2,0", category_id="node_type_011")
        self.assertIsNone(normal["nodes"]["2,0"]["resolvedCategoryId"])

    def test_template_change_requires_explicit_new_instance(self) -> None:
        state = new_playtime("run-7")
        observed = chain_map(3)
        merge_map_observation(state, "III", observed)
        changed = copy.deepcopy(observed)
        changed["templateId"] = "floor-3-02"
        with self.assertRaisesRegex(ValueError, "template changed"):
            merge_map_observation(state, "III", changed)
        merge_map_observation(state, "III", changed, new_instance=True)
        self.assertEqual(len(state["areas"]["III"]["instances"]), 2)

    def test_event_pool_uses_distinct_node_requirements_and_keeps_cleared_settlement(self) -> None:
        state = new_playtime("run-8")
        observed = chain_map(4, length=3)
        merge_map_observation(state, "IV", observed)
        update_node(state, "IV", "1,0", category_id="node_type_001")
        update_node(state, "IV", "2,0", category_id="node_type_005")
        row = next(event for event in state["areas"]["IV"]["encounterPool"] if event["id"] == "encounter_020")
        self.assertEqual(row["requirements"], ["settlement_in_area"])
        self.assertEqual(row["conditionStatus"], "not_met")
        self.assertEqual(row["eligibility"], "condition_not_met")
        update_node(state, "IV", "2,0", category_id="node_type_017")
        row = next(event for event in state["areas"]["IV"]["encounterPool"] if event["id"] == "encounter_020")
        self.assertEqual(row["conditionStatus"], "not_met")
        self.assertEqual(row["eligibility"], "condition_not_met")
        alone = next(event for event in state["areas"]["IV"]["encounterPool"] if event["id"] == "encounter_021")
        self.assertEqual(alone["requirements"], ["emergency_aid_in_area"])
        self.assertEqual(alone["conditionStatus"], "confirmed")
        self.assertEqual(alone["eligibility"], "possible")
        update_node(state, "IV", "1,0", category_id="node_type_019")
        row = next(event for event in state["areas"]["IV"]["encounterPool"] if event["id"] == "encounter_020")
        self.assertEqual(row["conditionStatus"], "confirmed")
        self.assertEqual(row["eligibility"], "possible")
        update_node(state, "IV", "1,0", completion="completed")
        update_node(state, "IV", "1,0", category_id="node_type_020")
        row = next(event for event in state["areas"]["IV"]["encounterPool"] if event["id"] == "encounter_020")
        self.assertEqual(row["conditionStatus"], "confirmed")
        self.assertEqual(row["eligibility"], "possible")

    def test_predictor_reads_single_prediction_dataset(self) -> None:
        rules, stats, templates = _catalogs()
        self.assertIs(rules, stats)
        self.assertEqual(rules["ruleVersion"], DATA["ruleVersion"])
        self.assertEqual(templates["floor-2-02"]["dangerPathEvidenceSlots"], [[3, 0], [4, 0]])

    def test_danger_path_uses_template_slots_after_stats_cleanup(self) -> None:
        template = _catalogs()[2]["floor-2-02"]
        start_x, start_y = template["startSlot"]
        key = lambda slot: f"{slot[0] - start_x},{start_y - slot[1]}"
        instance = {
            "areaKey": "II", "templateId": template["id"],
            "nodes": {
                key(slot): {
                    "slot": slot,
                    "observedCategoryId": "start" if slot == template["startSlot"] else "unknown_mystery",
                    "resolvedCategoryId": None,
                }
                for slot in template["occupiedSlots"]
            },
            "edges": [[key(left), key(right)] for left, right in template["edges"]],
        }
        predicted = predict_instance(instance)["unknownNodes"]
        self.assertTrue(any(
            predicted[key(slot)]["categories"]["danger-path"]["isCandidate"]
            for slot in template["dangerPathEvidenceSlots"]
        ))

    def test_current_remembrance_sample_matches_visible_page_frequency(self) -> None:
        stats = DATA
        rem_counts = stats["distanceSamples"]["encounter"]["remembrance"]
        self.assertAlmostEqual(_area_frequency(stats, "IV-remembrance", "encounter", 3, 11)["distanceFrequency"], rem_counts.get("11", 0) / sum(rem_counts.values()))
        self.assertNotEqual(
            _area_frequency(stats, "IV-remembrance", "encounter", 3, 11)["distanceFrequency"],
            _area_frequency(stats, "IV", "encounter", 3, 11)["distanceFrequency"],
        )

    def test_current_october_count_rules_include_remembrance_column(self) -> None:
        state = new_playtime("run-9")
        first = merge_map_observation(state, "I", {
            **chain_map(3), "floor": 1, "templateId": "floor-1-single-exit",
        })
        third = merge_map_observation(state, "III", chain_map(3))
        remembered = merge_map_observation(state, "IV-remembrance", chain_map(4))
        self.assertEqual(first["nodePool"]["wish"]["maximum"], 2)
        self.assertEqual(third["nodePool"]["combat"]["maximum"], 6)
        self.assertEqual(remembered["nodePool"]["encounter"]["maximum"], 3)

        observed = chain_map(4)
        for node in observed["nodes"][1:4]:
            node["categoryId"] = "node_type_006"
        normal_state = new_playtime("run-9-normal")
        remembered_state = new_playtime("run-9-remembered")
        merge_map_observation(normal_state, "IV", observed)
        merge_map_observation(remembered_state, "IV-remembrance", observed)
        self.assertIn("encounter", types(normal_state, "IV", "4,0"))
        self.assertNotIn("encounter", types(remembered_state, "IV-remembrance", "4,0"))

    def test_danger_end_shortcut_and_settlement_clearing_rule(self) -> None:
        state = new_playtime("run-10")
        shortcut = chain_map(4, length=3)
        shortcut["nodes"][1]["categoryId"] = "node_type_015"
        instance = merge_map_observation(state, "IV", shortcut)
        self.assertEqual(instance["prediction"]["unknownNodes"]["2,0"]["distanceFromStart"], 1)

        second = new_playtime("run-11")
        observed = chain_map(4, length=6)
        observed["nodes"][2]["categoryId"] = "node_type_020"
        observed["nodes"][4]["categoryId"] = "unknown_ferocity"
        merge_map_observation(second, "IV", observed)
        merge_map_observation(second, "IV-remembrance", observed)
        self.assertNotIn("settlement", types(second, "IV", "4,0"))
        self.assertIn("settlement", types(second, "IV-remembrance", "4,0"))


if __name__ == "__main__":
    unittest.main()
