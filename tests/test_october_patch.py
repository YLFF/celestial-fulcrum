from copy import deepcopy
import unittest
from fulcrum.node_predictor import _catalogs, predict_instance
from fulcrum.playtime_state import merge_map_observation, new_playtime, rebuild_derived, update_node
from fulcrum.resource_capacity import reconcile_carry_slots
from fulcrum.service.updates import apply_commands, validate_application_state
from tests.test_playtime_prediction import treehole_map


class OctoberPatchTests(unittest.TestCase):
    def test_carry_grants_and_level_six(self):
        state = new_playtime("slots")
        apply_commands(state, [{"type": "resources", "values": {"level": 6}},
                               {"type": "relics", "items": [{"id": "relic_016"}]}])
        self.assertEqual(state["resources"]["carrySlots"], 11)
        rebuild_derived(state)
        self.assertEqual(state["resources"]["carrySlots"], 11)
        apply_commands(state, [{"type": "relics", "items": []}])
        self.assertEqual(state["resources"]["carrySlots"], 11)
        apply_commands(state, [{"type": "relics", "items": [{"id": "relic_016"}]}])
        self.assertEqual(state["resources"]["carrySlots"], 12)
        apply_commands(state, [{"type": "resources", "values": {"level": 10}}])
        self.assertEqual(state["resources"]["carrySlots"], 13)

    def test_legacy_capacity_restores_only_minimum(self):
        state = new_playtime("legacy")
        state.pop("resourceRuntime")
        state["resources"].update(level=6, carrySlots=7)
        state["relics"] = [{"id": "relic_016"}]
        reconcile_carry_slots(state)
        self.assertEqual(state["resources"]["carrySlots"], 11)
        state.pop("resourceRuntime")
        state["resources"]["carrySlots"] = 12
        reconcile_carry_slots(state)
        self.assertEqual(state["resources"]["carrySlots"], 12)

    def test_squad_selection_has_no_capacity_rejection(self):
        state = new_playtime("roster")
        state["operators"] = [{"instanceId": str(i), "name": f"temporary-{i}", "elite": 1} for i in range(15)]
        apply_commands(state, [{"type": "squad", "operatorIds": [str(i) for i in range(15)]}])
        validate_application_state(state)
        self.assertEqual(len(state["squad"]), 15)

    def test_blind_zone_replaces_pending_and_preserves_completed(self):
        state = new_playtime("blind-zone")
        observation = treehole_map(3)
        observation["layerObservation"] = {"utopiaId": "utopia_005"}
        instance = merge_map_observation(state, "III-treehole", observation)
        update_node(state, "III-treehole", "1,0", category_id="node_type_006", encounter_id="encounter_009")
        update_node(state, "III-treehole", "2,0", category_id="node_type_011", completion="completed")
        preserved = deepcopy(instance["nodes"]["2,0"])
        observation["nodes"][1]["categoryId"] = "node_type_020"
        observation["nodes"][2]["categoryId"] = "node_type_007"
        merge_map_observation(state, "III-treehole", observation)
        self.assertEqual(instance["utopiaId"], "utopia_005")
        self.assertEqual(instance["nodes"]["1,0"]["observedCategoryId"], "node_type_020")
        self.assertIsNone(instance["nodes"]["1,0"]["encounterId"])
        self.assertNotIn("needsCategoryReview", instance["nodes"]["1,0"])
        self.assertEqual(instance["nodes"]["2,0"], preserved)

    def test_horizontal_fork_has_evidenced_danger_path(self):
        template = _catalogs()[2]["floor-1-horizontal-fork"]
        sx, sy = template["startSlot"]
        key = lambda slot: f"{slot[0]-sx},{sy-slot[1]}"
        instance = {"areaKey": "I", "templateId": template["id"],
                    "nodes": {key(slot): {"slot": slot, "observedCategoryId": "unknown_mystery", "resolvedCategoryId": None}
                              for slot in template["occupiedSlots"]},
                    "edges": [[key(a), key(b)] for a, b in template["edges"]]}
        predicted = predict_instance(instance)["unknownNodes"]
        self.assertTrue(predicted["1,-1"]["categories"]["danger-path"]["isCandidate"])
        self.assertFalse(predicted["1,1"]["categories"]["danger-path"]["isCandidate"])

if __name__ == "__main__":
    unittest.main()
