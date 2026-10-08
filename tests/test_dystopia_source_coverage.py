import unittest
from unittest.mock import patch

import numpy as np

from fulcrum.map_model import Coord, MapNode
from fulcrum.vision_dystopia import recognize_nodes


class SourceCoverageTests(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((64, 64, 3), dtype=np.uint8)
        self.nodes = [MapNode(Coord(x, y), (x, y), (x+10, y+10),
                     category_id="node_type_002" if (x, y) == (0, 0) else "node_type_020")
                     for x in range(-3, 4) for y in range(-3, 4)]
        self.observation = {"active": True, "ideologyId": "dystopia_005"}

    def recognize(self, difficulty, score=.9):
        with patch("fulcrum.vision_dystopia.textures", return_value=[("ideal_source", self.image)]), \
             patch("fulcrum.vision_dystopia.IconMatcher._score", return_value=score):
            return recognize_nodes(self.image, self.nodes, 100, self.observation, difficulty=difficulty)

    def test_radius_changes_at_n12(self):
        for difficulty, count in ((0, 13), (11, 13), (12, 25), (15, 25)):
            result = self.recognize(difficulty)
            self.assertEqual(len(result["affectedNodeIds"]), count)
            self.assertEqual(result["idealSourceNodeId"], "0,0")
            self.assertEqual(result["nodeEvidence"]["2,1"]["affected"], difficulty >= 12)
            self.assertFalse(result["nodeEvidence"]["2,2"]["affected"])

    def test_missing_source_leaves_coverage_unresolved(self):
        result = self.recognize(15, score=.4)
        self.assertIsNone(result["idealSourceNodeId"])
        self.assertFalse(result["affectedNodeIds"])
        self.assertTrue(all(row["affected"] is None for row in result["nodeEvidence"].values()))

    def test_soil_uses_visual_method_no_source_radius(self):
        observation = {"active": True, "ideologyId": "dystopia_008"}
        with patch("fulcrum.vision_dystopia.recognize_visual_nodes", return_value={"visual": True}) as original:
            self.assertEqual(recognize_nodes(self.image, self.nodes, 100, observation), {"visual": True})
            original.assert_called_once()


if __name__ == "__main__":
    unittest.main()
