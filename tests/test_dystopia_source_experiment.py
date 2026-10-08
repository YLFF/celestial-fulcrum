import unittest
from unittest.mock import patch

import numpy as np

from fulcrum.map_model import Coord, MapNode
from experiments.benchmark_dystopia_source import source_only


class SourceCoverageExperimentTests(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((64, 64, 3), dtype=np.uint8)
        self.nodes = [MapNode(Coord(x, y), (x, y), (x+10, y+10),
                     category_id="node_type_002" if (x, y) == (0, 0) else "node_type_020")
                     for x in range(-3, 4) for y in range(-3, 4)]
        self.observation = {"active": True, "ideologyId": "dystopia_005"}

    def recognize(self, difficulty, score=.9):
        with patch("experiments.benchmark_dystopia_source.textures", return_value=[("ideal_source", self.image)]), \
             patch("experiments.benchmark_dystopia_source.IconMatcher._score", return_value=score):
            return source_only(self.image, self.nodes, 100, self.observation, difficulty=difficulty)

    def test_low_difficulty_is_center_and_twelve_cells(self):
        for difficulty in (0, 11):
            result = self.recognize(difficulty)
            self.assertEqual(len(result["affectedNodeIds"]), 13)
            self.assertIn("2,0", result["affectedNodeIds"])
            self.assertNotIn("2,1", result["affectedNodeIds"])

    def test_high_difficulty_adds_twelve_cells(self):
        for difficulty in (12, 15):
            result = self.recognize(difficulty)
            self.assertEqual(len(result["affectedNodeIds"]), 25)
            self.assertIn("2,1", result["affectedNodeIds"])
            self.assertNotIn("2,2", result["affectedNodeIds"])

    def test_weak_source_does_not_claim_coverage(self):
        result = self.recognize(15, score=.4)
        self.assertIsNone(result["idealSourceNodeId"])
        self.assertFalse(result["affectedNodeIds"])
        self.assertTrue(all(row["affected"] is None for row in result["nodeEvidence"].values()))

    def test_soil_uses_original_visual_method(self):
        observation = {"active": True, "ideologyId": "dystopia_008"}
        with patch("experiments.benchmark_dystopia_source.recognize_nodes", return_value={"legacy": True}) as original:
            self.assertEqual(source_only(self.image, self.nodes, 100, observation), {"legacy": True})
            original.assert_called_once()

    def test_source_candidates_are_only_emergency_or_hidden_ferocity(self):
        with patch("experiments.benchmark_dystopia_source.textures", return_value=[("ideal_source", self.image)]), \
             patch("experiments.benchmark_dystopia_source.IconMatcher._score", return_value=.9) as score:
            result = source_only(self.image, self.nodes, 100, self.observation)
            self.assertEqual([row["nodeId"] for row in result["idealSourceCandidates"]], ["0,0"])
            self.assertEqual(score.call_count, 1)


if __name__ == "__main__":
    unittest.main()
