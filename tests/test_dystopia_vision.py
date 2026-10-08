from functools import lru_cache
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2

from fulcrum.vision_pipeline import MapRecognizer
from fulcrum.vision_dystopia import recognize_header, recognize_nodes
from fulcrum.vision_geometry import working_image
from fulcrum.vision_resources import HudRecognizer

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=2)
def sample(floor):
    return MapRecognizer().recognize(ROOT / f"samples/maps/desktop_floor{floor}_dystopia.png")


class DystopiaVisionTests(unittest.TestCase):
    def test_full_maps_and_distorted_node_classes(self):
        for floor, count, source, ideology, policy in ((1, 13, "-2,0", "005", "012"), (3, 26, "-1,2", "002", "013")):
            with self.subTest(floor=floor):
                result = sample(floor)
                self.assertTrue(result.success)
                self.assertEqual(len(result.nodes), count)
                self.assertFalse(any(node.category_id is None for node in result.nodes))
                overlay = result.dystopia_observation
                self.assertEqual(overlay["ideologyId"], "dystopia_"+ideology)
                self.assertEqual(overlay["policyId"], "dystopia_"+policy)
                self.assertEqual(overlay["idealSourceNodeId"], source)
                self.assertIn(source, overlay["affectedNodeIds"])
                self.assertEqual(result.player_position_observation["status"], "recognized")
        one = {node.coord.key: node for node in sample(1).nodes}
        self.assertEqual(one["1,1"].category_id, "node_type_020")
        self.assertEqual(one["-1,0"].category_id, "node_type_020")
        three = {node.coord.key: node for node in sample(3).nodes}
        for key, kind in {"-1,1": "node_type_020", "1,3": "node_type_002", "-4,2": "node_type_017",
                          "-3,2": "node_type_018", "-1,0": "node_type_006", "-2,4": "node_type_020"}.items():
            self.assertEqual(three[key].category_id, kind, key)

    def test_range_does_not_fill_gaps_or_force_unresolved_nodes(self):
        one = sample(1).dystopia_observation
        self.assertIn("0,0", one["affectedNodeIds"])
        self.assertNotIn("1,1", one["affectedNodeIds"])
        self.assertNotIn("2,1", one["affectedNodeIds"])
        self.assertNotIn("2,0", one["affectedNodeIds"])
        three = sample(3).dystopia_observation
        self.assertNotIn("2,1", three["affectedNodeIds"])
        self.assertNotIn("2,0", three["affectedNodeIds"])

    def test_partial_map_is_still_rejected_despite_dystopia_header(self):
        image = cv2.imread(str(ROOT / "samples/maps/desktop_floor3_dystopia.png"))
        image[round(image.shape[0]*.18):round(image.shape[0]*.86), :round(image.shape[1]*.46)] = 0
        result = MapRecognizer().recognize_image(image, screenshot="partial-dystopia")
        self.assertFalse(result.success)

    def test_hud_at_smaller_input_and_fertile_soil_without_source(self):
        image = cv2.imread(str(ROOT / "samples/maps/desktop_floor1_dystopia.png"))
        image = cv2.resize(image, (960, 540))
        self.assertEqual(recognize_header(image)["ideologyId"], "dystopia_005")
        result = recognize_nodes(image, [], 100, {"active": True, "ideologyId": "dystopia_008",
                                              "sourceStatus": "not_applicable", "idealSourceNodeId": None})
        self.assertIsNone(result["idealSourceNodeId"])
        self.assertEqual(result["sourceStatus"], "not_applicable")

    def test_impossible_resource_pair_does_not_auto_import(self):
        image = cv2.imread(str(ROOT / "samples/maps/desktop_floor3_dystopia.png"))
        with patch("fulcrum.vision_resources._run_ocr", return_value={"life": {"text": "48/8", "confidence": 95},
                  "experience": {"text": "20/10", "confidence": 95}}):
            fields = HudRecognizer()._recognize_fit(image, (0, 216, 3839, 1934), 1)["fields"]
        self.assertEqual(fields["life"]["status"], "needs_review")
        self.assertEqual(fields["experience"]["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
