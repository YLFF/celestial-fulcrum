import copy
import unittest

from fulcrum.dystopia import empty_dystopia, set_dystopia, merge_dystopia_observation, validate_dystopia
from fulcrum.playtime_state import new_playtime, merge_map_observation, validate_playtime
from fulcrum.service.updates import apply_commands
from tests.test_playtime_utopia import observation


class DystopiaSnapshotTests(unittest.TestCase):
    def make_map(self):
        state = new_playtime("dystopia-test")
        data = observation()
        data["nodes"][1]["categoryId"] = "unknown_ferocity"
        instance = merge_map_observation(state, "III", data)
        return state, instance, data

    def test_legacy_maps_remain_valid_and_snapshot_is_not_a_log(self):
        state, instance, _ = self.make_map()
        validate_playtime(state)
        value = {**empty_dystopia(), "active": True, "ideologyId": "dystopia_005", "policyId": "dystopia_012",
                 "affectedNodeIds": ["1,0"], "uncertainNodeIds": ["0,0"], "idealSourceNodeId": "1,0"}
        apply_commands(state, [{"type": "dystopia", "areaKey": "III", "value": value}])
        self.assertEqual(instance["dystopia"], value)
        self.assertEqual(instance["nodes"]["1,0"]["resolvedCategoryId"], "node_type_002")
        self.assertEqual(instance["nodes"]["1,0"]["observedCategoryId"], "unknown_ferocity")
        value["affectedNodeIds"].append("0,0")
        self.assertEqual(instance["dystopia"]["affectedNodeIds"], ["1,0"])

    def test_uncertain_refresh_preserves_confirmed_coverage_and_missing_header_does_not_clear(self):
        _, instance, _ = self.make_map()
        set_dystopia(instance, {**empty_dystopia(), "active": True, "ideologyId": "dystopia_005",
                    "affectedNodeIds": ["1,0"], "idealSourceNodeId": "1,0"})
        merge_dystopia_observation(instance, {"active": True, "ideologyId": "dystopia_005",
                    "nodeEvidence": {"0,0": {"affected": False}, "1,0": {"affected": None}}})
        self.assertEqual(instance["dystopia"]["affectedNodeIds"], ["1,0"])
        before = copy.deepcopy(instance["dystopia"])
        merge_dystopia_observation(instance, {"active": None})
        self.assertEqual(instance["dystopia"], before)

    def test_fertile_soil_has_no_source_and_invalid_node_ids_rejected(self):
        _, instance, _ = self.make_map()
        for change in ({"affectedNodeIds": ["no-such-node"]}, {"affectedNodeIds": ["1,0"], "uncertainNodeIds": ["1,0"]},
                       {"ideologyId": "utopia_005"}, {"ideologyId": "dystopia_008", "affectedNodeIds": ["1,0"], "idealSourceNodeId": "1,0"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_dystopia({**empty_dystopia(), "active": True, **change}, instance["nodes"])
        soil = {**empty_dystopia(), "active": True, "ideologyId": "dystopia_008", "policyId": "dystopia_014"}
        set_dystopia(instance, soil)
        set_dystopia(instance, empty_dystopia())
        self.assertFalse(instance["dystopia"]["active"])

    def test_completed_source_refresh_does_not_destroy_original_category(self):
        state, instance, data = self.make_map()
        data["dystopiaObservation"] = {"active": True, "ideologyId": "dystopia_005", "idealSourceNodeId": "1,0",
            "nodeEvidence": {"1,0": {"affected": True}, "0,0": {"affected": False}}}
        merge_map_observation(state, "III", data)
        data["dystopiaObservation"] = {"active": None}
        data["nodes"][1]["categoryId"] = "node_type_020"
        merge_map_observation(state, "III", data)
        self.assertEqual(instance["nodes"]["1,0"]["resolvedCategoryId"], "node_type_002")
        data["dystopiaObservation"] = {"active": True, "ideologyId": "dystopia_005",
                                      "nodeEvidence": {"1,0": {"affected": True}}}
        merge_map_observation(state, "III", data)
        self.assertEqual(instance["dystopia"]["idealSourceNodeId"], "1,0")
        set_dystopia(instance, empty_dystopia())
        validate_playtime(state)

    def test_source_rejects_a_noncombat_node(self):
        _, instance, _ = self.make_map()
        with self.assertRaisesRegex(ValueError, "emergency combat"):
            set_dystopia(instance, {**empty_dystopia(), "active": True, "affectedNodeIds": ["0,0"], "idealSourceNodeId": "0,0"})

    def test_rejecting_source_candidate_restores_hidden_category_without_erasing_history(self):
        _, instance, _ = self.make_map()
        set_dystopia(instance, {**empty_dystopia(), "active": True, "affectedNodeIds": ["1,0"], "idealSourceNodeId": "1,0"})
        set_dystopia(instance, {**empty_dystopia(), "active": True})
        self.assertIsNone(instance["nodes"]["1,0"]["resolvedCategoryId"])
