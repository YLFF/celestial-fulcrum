from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    import cv2
    import numpy as np

    from fulcrum.vision_geometry import working_image
    from fulcrum.vision_layer import recognize_layer
    from fulcrum.vision_pipeline import MapRecognizer
    from fulcrum.vision_player import recognize_player_position
    from fulcrum.map_model import Coord, MapNode
except ImportError:
    cv2 = None


SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "maps"


@unittest.skipUnless(cv2 is not None, "install requirements-vision.txt for CV tests")
class ArchivedMapSamplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.samples = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))["samples"]
        cls.recognizer = MapRecognizer()

    def test_layer_marker_across_archived_screenshots(self) -> None:
        self.assertGreaterEqual(len(self.samples), 11)
        self.assertEqual(len({sample["file"] for sample in self.samples}), len(self.samples))
        for sample in self.samples:
            with self.subTest(sample=sample["file"]):
                image = cv2.imread(str(SAMPLES / sample["file"]))
                self.assertIsNotNone(image)
                layer = recognize_layer(image)
                self.assertEqual(layer.label, sample["layer"])
                self.assertEqual(layer.floor, sample["floor"])
                self.assertIsNotNone(layer.roi)

    def test_fifth_layer_glyph_from_fourth_layer_sample(self) -> None:
        image = cv2.imread(str(SAMPLES / "attachment_04.jpg"))
        cv2.rectangle(image, (965, 54), (973, 79), (40, 30, 60), -1)
        layer = recognize_layer(image)
        self.assertEqual((layer.label, layer.area, layer.floor), ("V", "main", 5))

    def test_three_question_mark_treehole_variant(self) -> None:
        source = cv2.imread(str(SAMPLES / "attachment_01.jpg"))
        image = source.copy()
        cv2.rectangle(image, (1033, 53), (1060, 80), (28, 27, 29), -1)
        for left, right, target in ((1012, 1021, 1036), (1036, 1041, 1049)):
            patch = source[54:76, left:right]
            mask = cv2.inRange(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV), (10, 70, 100), (47, 255, 255))
            cv2.copyTo(patch, mask, image[54:76, target:target + right - left])
        self.assertEqual(recognize_layer(image).label, "treehole")

    def test_auto_map_recognition_and_partial_negative_samples(self) -> None:
        for sample in self.samples:
            with self.subTest(sample=sample["file"]):
                result = self.recognizer.recognize(SAMPLES / sample["file"])
                self.assertEqual(result.area, "treehole" if sample["layer"] == "treehole" else (
                    "source_confluence" if sample["floor"] == 6 else "main"
                ))
                self.assertEqual(result.floor, sample["floor"])
                self.assertEqual(result.success, sample["expectMap"])
                self.assertEqual(result.template_id, sample["templateId"])
                self.assertIsNotNone(result.map_viewport)
                if result.success:
                    self.assertIsNotNone(result.map_roi)
                    x0, y0, x1, y1 = result.map_roi
                    vx0, vy0, vx1, vy1 = result.map_viewport
                    self.assertTrue(vx0 <= x0 < x1 <= vx1)
                    self.assertTrue(vy0 <= y0 < y1 <= vy1)
                    self.assertEqual(len(result.nodes), len({node.coord.key for node in result.nodes}))
                else:
                    self.assertIsNone(result.map_roi)

    def test_special_sixth_floor_nodes_and_real_marks(self) -> None:
        sixth = self.recognizer.recognize(SAMPLES / "attachment_08.jpg")
        categories = {node.category_name for node in sixth.nodes}
        self.assertIn("命运所指", categories)
        self.assertIn("险路恶敌", categories)
        self.assertFalse(any(node.marks for node in sixth.nodes))

        fourth = self.recognizer.recognize(SAMPLES / "attachment_04.jpg")
        self.assertEqual(
            [(node.category_name, mark["id"]) for node in fourth.nodes for mark in node.marks],
            [("失与得", "node_mark_006")],
        )
        treehole = self.recognizer.recognize(SAMPLES / "attachment_01.jpg")
        self.assertFalse(any(node.marks for node in treehole.nodes))

        image, _ = working_image(cv2.imread(str(SAMPLES / "attachment_05.jpg")))
        self.assertEqual(
            self.recognizer.icons.detect_marks(image, (507, 167), 100)[0]["id"],
            "node_mark_001",
        )

    def test_player_position_on_complete_archived_maps(self) -> None:
        expected = {
            "attachment_01.jpg": "3,0", "attachment_03.jpg": "3,0",
            "attachment_04.jpg": "-3,-2", "attachment_06.jpg": "0,0",
            "attachment_07.jpg": "0,0", "attachment_08.jpg": "4,-1",
            "bluestacks_floor_1.png": "0,0", "bluestacks_floor_3.png": "0,0",
            "desktop_floor2_yellow_shop.png": "0,2",
        }
        for filename, position in expected.items():
            with self.subTest(filename=filename):
                result = self.recognizer.recognize(SAMPLES / filename)
                self.assertEqual(result.player_position_observation["status"], "recognized")
                self.assertEqual(result.player_position_observation["nodeId"], position)
                self.assertEqual(result.to_dict()["playerPositionObservation"], result.player_position_observation)

    def test_blank_screenshot_does_not_guess_layer(self) -> None:
        result = self.recognizer.recognize_image(
            np.zeros((720, 1280, 3), dtype=np.uint8), screenshot="blank"
        )
        self.assertFalse(result.success)
        self.assertIsNone(result.area)
        self.assertEqual(result.template_candidates, [])

    def test_zoomed_highlight_and_shadow_nodes(self) -> None:
        result = self.recognizer.recognize(SAMPLES / "desktop_action_4.png")
        nodes = {node.coord.key: node for node in result.nodes}
        self.assertTrue(result.success)
        self.assertEqual(nodes["-1,0"].category_id, "node_type_006")
        self.assertGreater(nodes["-1,0"].category_score, .6)
        self.assertEqual(nodes["1,1"].category_id, "node_type_020")
        self.assertGreater(nodes["1,1"].category_score, .8)
        self.assertEqual(nodes["-1,-1"].category_id, "node_type_020")

    def test_low_contrast_second_floor_map_and_node_categories(self) -> None:
        result = self.recognizer.recognize(SAMPLES / "desktop_floor2_lookout_revealed.png", difficulty=5)
        self.assertTrue(result.success)
        self.assertEqual(result.template_id, "floor-2-04")
        self.assertEqual(len(result.nodes), 19)
        self.assertEqual(result.match_quality["coverage"], 1.0)
        self.assertFalse(result.match_quality["clippedNodeIds"])
        by_coord = {node.coord.key: node for node in result.nodes}
        expected = {
            "-2,3": "node_type_020", "-2,2": "node_type_001", "-2,1": "node_type_006",
            "-2,0": "unknown_mystery", "-1,3": "node_type_007", "-1,2": "node_type_018",
            "-1,1": "node_type_020", "-1,0": "node_type_020", "0,3": "node_type_008",
            "0,2": "node_type_020", "0,1": "node_type_001", "0,0": "start",
            "1,3": "unknown_mystery", "1,2": "node_type_009", "1,1": "node_type_020",
            "2,3": "unknown_mystery", "2,2": "node_type_015", "2,1": "unknown_ferocity",
            "2,0": "unknown_mystery",
        }
        self.assertEqual({key: node.category_id for key, node in by_coord.items()}, expected)
        self.assertEqual(result.player_position_observation["status"], "recognized")
        self.assertEqual(result.player_position_observation["nodeId"], "0,0")
        self.assertTrue(all(not node.marks for node in result.nodes))

    def test_text_first_fourth_floor_with_highlights_and_two_exits(self) -> None:
        result = self.recognizer.recognize(SAMPLES / "desktop_floor4_two_exits.png", difficulty=5)
        self.assertTrue(result.success)
        self.assertEqual(result.template_id, "floor-4-11")
        expected = {
            "-6,1": "unknown_mystery", "-6,0": "node_type_014", "-6,-1": "node_type_005",
            "-5,1": "node_type_015", "-5,0": "node_type_001", "-5,-1": "node_type_018", "-5,-2": "node_type_004",
            "-4,1": "unknown_mystery", "-4,0": "node_type_008", "-4,-1": "node_type_002", "-4,-2": "node_type_015",
            "-3,1": "unknown_mystery", "-3,0": "node_type_020", "-3,-2": "node_type_020", "-3,-3": "unknown_ferocity",
            "-2,0": "node_type_001", "-2,-1": "unknown_mystery", "-2,-2": "node_type_020", "-2,-3": "node_type_019",
            "-1,1": "node_type_011", "-1,0": "node_type_020", "-1,-1": "node_type_020", "-1,-2": "node_type_020", "-1,-3": "unknown_mystery",
            "0,1": "node_type_014", "0,0": "start", "0,-1": "node_type_006", "0,-2": "node_type_013", "0,-3": "node_type_020",
            "1,1": "node_type_020", "1,0": "node_type_017", "1,-1": "node_type_020",
        }
        self.assertEqual({node.coord.key: node.category_id for node in result.nodes}, expected)
        self.assertEqual(result.player_position_observation["nodeId"], "-1,0")
        self.assertGreaterEqual(result.node_text_observation["acceptedCount"], 10)
        self.assertTrue(all(node.completion == "unknown" for node in result.nodes))

    def test_treehole_question_mark_with_merged_dot_and_highlighted_choice(self) -> None:
        result = self.recognizer.recognize(SAMPLES / "desktop_treehole_single_row.png", difficulty=5)
        self.assertTrue(result.success)
        self.assertEqual(result.area, "treehole")
        self.assertIsNone(result.floor)
        self.assertEqual(result.template_id, "treehole-08")
        self.assertEqual({node.coord.key: node.category_id for node in result.nodes}, {
            "0,0": "start", "1,0": "node_type_011", "2,0": "unknown_mystery",
            "3,0": "unknown_mystery", "4,0": "unknown_mystery", "5,0": "node_type_020",
        })
        self.assertEqual(result.player_position_observation["nodeId"], "0,0")
        choice = next(node for node in result.nodes if node.coord.key == "1,0")
        self.assertEqual(choice.category_source, "text_and_icon")

    def test_blank_lattice_does_not_guess_player(self) -> None:
        nodes = [MapNode(Coord(0, 0), (0, 0), (60, 60)), MapNode(Coord(1, 0), (1, 0), (160, 60))]
        observed = recognize_player_position(np.zeros((240, 300, 3), dtype=np.uint8), nodes)
        self.assertEqual(observed["status"], "unreadable")
        self.assertIsNone(observed["nodeId"])

    def test_revealed_exits_shadow_connector_and_current_yellow_shop(self) -> None:
        result = self.recognizer.recognize(SAMPLES / "desktop_floor2_yellow_shop.png")
        self.assertTrue(result.success)
        self.assertEqual(result.template_id, "floor-2-01")
        self.assertEqual(len(result.nodes), 17)
        nodes = {node.coord.key: node for node in result.nodes}
        for key, category in {"2,3": "node_type_015", "4,1": "node_type_015", "1,3": "node_type_020",
                              "0,2": "node_type_013", "3,0": "node_type_018"}.items():
            with self.subTest(node=key):
                self.assertEqual(nodes[key].category_id, category)
                self.assertEqual(nodes[key].visibility, "revealed")
        self.assertFalse(any(node.category_id is None for node in result.nodes))
        self.assertEqual([(node.coord.key, mark["id"]) for node in result.nodes for mark in node.marks], [("0,3", "node_mark_002")])
        player = result.player_position_observation
        self.assertEqual((player["status"], player["nodeId"], player["source"]), ("recognized", "0,2", "player_avatar"))
        self.assertLess(player["anchorPixel"][0], nodes["0,2"].pixel[0])

    def test_repeated_green_shop_overlay_at_multiple_sizes(self) -> None:
        image = cv2.imread(str(SAMPLES / "green_shop_repeat_crop.png"))
        for scale in (.3, .4, .5):
            with self.subTest(scale=scale):
                work = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                chosen, candidates = self.recognizer.icons.classify_node(work, (309 * scale, 270 * scale), 500 * scale, [])
                self.assertIsNotNone(chosen)
                self.assertEqual(chosen.id, "node_type_004")
                self.assertGreater(chosen.score, .75)
                self.assertEqual(candidates[0].id, "node_type_004")

    def test_crosshair_without_avatar_is_not_a_confirmed_position(self) -> None:
        image = np.zeros((300, 450, 3), np.uint8)
        nodes = [MapNode(Coord(0, 0), (0, 0), (150, 150)), MapNode(Coord(1, 0), (1, 0), (350, 150))]
        for dx, dy in ((1, -1), (-1, 1)):
            cv2.line(image, (round(150 + dx * 36), round(150 + dy * 36)),
                     (round(150 + dx * 90), round(150 + dy * 90)), (255, 255, 255), 3)
        result = recognize_player_position(image, nodes)
        self.assertNotEqual(result["status"], "recognized")

    def test_multiple_identical_avatars_need_confirmation(self) -> None:
        template = cv2.imread(str(SAMPLES.parents[1] / "assets" / "vision" / "player_avatar_01.png"), cv2.IMREAD_GRAYSCALE)
        image = np.zeros((220, 400, 3), np.uint8)
        nodes = [MapNode(Coord(0, 0), (0, 0), (150, 100)), MapNode(Coord(1, 0), (1, 0), (251, 100))]
        for x in (114, 215):
            image[76:120, x:x + 22] = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)
        result = recognize_player_position(image, nodes)
        self.assertEqual(result["status"], "needs_review")
        self.assertAlmostEqual(result["margin"], 0)


if __name__ == "__main__":
    unittest.main()
