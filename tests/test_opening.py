"""Opening modifiers and the first-floor screenshot share one confirmed state."""

from __future__ import annotations

from pathlib import Path
import unittest

from fulcrum.opening import SQUAD_NAMES, opening_action_points
from fulcrum.playtime_route import route_inputs
from fulcrum.playtime_state import merge_map_observation, new_playtime, validate_playtime
from fulcrum.route_planner import RoutePlanner
from fulcrum.vision_pipeline import MapRecognizer


SCREENSHOT = Path(__file__).resolve().parents[1] / "samples" / "maps" / "opening_shop_cats_pegasus.png"


class OpeningTests(unittest.TestCase):
    def test_every_squad_has_the_expected_opening_delta(self) -> None:
        self.assertEqual(len(SQUAD_NAMES), 15)
        for squad_id in SQUAD_NAMES:
            with self.subTest(squad=squad_id):
                state = new_playtime(squad_id, squad_id=squad_id)
                validate_playtime(state)
                resources = state["resources"]
                box = state["componentBox"]
                self.assertEqual(resources["level"], 1)
                self.assertEqual(resources["shield"], 2)
                self.assertEqual(resources["hope"], 8 if squad_id == "squad_003" else 6)
                self.assertEqual(resources["originiumIngot"], 40 if squad_id == "squad_003" else 20)
                self.assertEqual(resources["life"], {
                    "current": 6 if squad_id == "squad_001" else (1 if squad_id == "squad_004" else 4),
                    "max": 6 if squad_id == "squad_001" else 4,
                })
                self.assertEqual(resources["carrySlots"], 9 if squad_id == "squad_002" else 7)
                self.assertEqual(resources["deploymentSlots"], 8 if squad_id == "squad_002" else 6)
                self.assertEqual(box["capacity"], 12 if squad_id == "squad_014" else (10 if squad_id == "squad_002" else 8))
                self.assertEqual(len(box["items"]), 6 if squad_id == "squad_003" else 2)
                self.assertEqual(len(state["operators"]), 6 if squad_id == "squad_002" else 1)
                expected_relic = {"squad_011": "relic_134", "squad_015": "relic_211"}.get(squad_id)
                self.assertEqual([row["id"] for row in state["relics"]], [expected_relic] if expected_relic else [])
                self.assertEqual(len(state["pendingOpeningRewards"]), 2 if squad_id == "squad_013" else 0)

    def test_cats_and_pegasus_opening_and_screenshot_override(self) -> None:
        observed = MapRecognizer().recognize(SCREENSHOT, include_resources=True).to_dict()
        self.assertTrue(observed["success"])
        self.assertEqual(observed["floor"], 1)
        self.assertEqual(observed["templateId"], "floor-1-single-exit")
        self.assertEqual((len(observed["nodes"]), len(observed["edges"])), (11, 11))
        self.assertEqual(observed["resourceObservation"]["fields"]["action_points"]["value"], 6)

        without_pegasus = new_playtime("shop-cats", squad_id="squad_014", cocoons={"猫": 2})
        self.assertEqual(opening_action_points(without_pegasus["opening"], "I"), 6)
        normal_instance = merge_map_observation(
            without_pegasus, "I", observed, player_position="0,0", initial_area_entry=True,
        )
        self.assertEqual(normal_instance["actionPoints"], 6)
        state = new_playtime("shop-pegasus", squad_id="squad_014", cocoons={"猫": 2, "天马": 1})
        instance = merge_map_observation(state, "I", observed, player_position="0,0", initial_area_entry=True)
        self.assertEqual(instance["openingObservedActionPoints"], 6)
        self.assertEqual(instance["actionPoints"], 7)
        self.assertEqual(state["resources"]["originiumIngot"], 30)
        self.assertEqual(state["resources"]["hope"], 6)
        self.assertEqual(state["componentBox"]["capacity"], 12)
        self.assertEqual([item["componentId"] for item in state["componentBox"]["items"]], ["component_001"] * 2)
        self.assertEqual([relic["id"] for relic in state["relics"]], ["relic_032"])
        self.assertEqual(instance["nodes"]["2,0"]["resolvedCategoryId"], "node_type_004")
        self.assertEqual(instance["nodePool"]["forest-clearing"]["knownCount"], 2)
        self.assertEqual(instance["nodePool"]["total-nodes"]["knownCount"], 11)
        self.assertTrue(instance["nodePool"]["combat"]["countRuleConflict"])
        self.assertIsNone(instance["nodePool"]["combat"]["maximumRemaining"])
        self.assertEqual(instance["prediction"]["status"], "needs_review")
        self.assertIn("combat", {candidate["nodeType"] for candidate in instance["prediction"]["unknownNodes"]["2,1"]["candidates"]})
        self.assertEqual(set(instance["prediction"]["unknownNodes"]), {"1,1", "2,1"})

        route_map, route_state = route_inputs(state, top_n=5)
        self.assertEqual(route_state["actionPoints"], 7)
        self.assertEqual(route_state["position"], "0,0")
        self.assertEqual(route_state["items"], [])
        planned = RoutePlanner(route_map).plan(route_state)
        self.assertTrue(planned["routes"])
        self.assertTrue(planned["searchComplete"])

    def test_opening_override_is_not_available_on_later_refreshes(self) -> None:
        observed = MapRecognizer().recognize(SCREENSHOT, include_resources=True).to_dict()
        state = new_playtime("shop-refresh", squad_id="squad_014", cocoons={"天马": 1})
        instance = merge_map_observation(state, "I", observed, player_position="0,0", initial_area_entry=True)
        self.assertEqual(instance["actionPoints"], 7)
        with self.assertRaisesRegex(ValueError, "fresh first-floor"):
            merge_map_observation(state, "I", observed, player_position="0,0", initial_area_entry=True)
        merge_map_observation(state, "I", observed, player_position="0,0")
        self.assertEqual(instance["actionPoints"], 6)


if __name__ == "__main__":
    unittest.main()
