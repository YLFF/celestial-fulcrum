from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path

try:
    import cv2
    import numpy as np

    from fulcrum.map_catalog import TemplateCatalog
    from fulcrum.vision_geometry import Circle, match_templates
    from fulcrum.vision_icons import IconMatcher
    from fulcrum.vision_pipeline import MapRecognizer, render_overlay
except ImportError:
    cv2 = None


SCREENSHOTS = Path(r"C:\Users\Lean\Pictures\BlueStacks")


@unittest.skipUnless(cv2 is not None, "install requirements-vision.txt for CV tests")
class MapVisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = TemplateCatalog()
        cls.recognizer = MapRecognizer(cls.catalog)

    def test_template_match_from_noisy_grid_points(self) -> None:
        template = next(item for item in self.catalog.templates if item.id == "floor-3-01")
        circles = [Circle(340 + col * 100, 145 + row * 100, 24) for col, row in template.occupied_slots]
        circles.extend((Circle(90, 200, 8), Circle(1150, 500, 20)))
        matches = match_templates(circles, self.catalog.candidates("main", 3), (1280, 720))
        self.assertEqual(matches[0].template.id, "floor-3-01")
        self.assertEqual(matches[0].coverage, 1.0)

    def test_identical_mark_templates_use_floor_before_score_margin(self) -> None:
        matcher = IconMatcher.__new__(IconMatcher)
        icon = np.zeros((5, 5, 3), dtype=np.uint8)
        matcher.mark_templates = [("node_mark_002", icon), ("node_mark_003", icon)]
        matcher.mark_labels = {"node_mark_002": "线人与线索", "node_mark_003": "谜题与谜底"}
        with patch.object(matcher, "_score", return_value=0.95):
            self.assertEqual(matcher.detect_marks(icon, (0, 0), 60), [])
            for floor, mark in ((3, "node_mark_002"), (5, "node_mark_003")):
                result = matcher.detect_marks(icon, (0, 0), 60, area="main", floor=floor)
                self.assertEqual(result[0]["id"], mark)
                self.assertEqual(result[0]["status"], "candidate")

    def test_treehole_same_occupancy_is_disambiguated_by_edges(self) -> None:
        templates = self.catalog.candidates("treehole", 3)
        for template_id in ("treehole-03", "treehole-09"):
            with self.subTest(template_id=template_id):
                template = next(item for item in templates if item.id == template_id)
                image = np.full((720, 1280, 3), 20, dtype=np.uint8)
                circles = [Circle(320 + col * 110, 180 + row * 110, 20) for col, row in template.occupied_slots]
                for a, b in template.edges:
                    cv2.line(
                        image,
                        (320 + a[0] * 110, 180 + a[1] * 110),
                        (320 + b[0] * 110, 180 + b[1] * 110),
                        (190, 190, 190),
                        8,
                    )
                for col, row in template.occupied_slots:
                    cv2.circle(image, (320 + col * 110, 180 + row * 110), 12, (230, 230, 230), 3)
                matches = match_templates(circles, templates, (1280, 720), image=image)
                self.assertEqual(matches[0].template.id, template_id)
                result = self.recognizer.recognize_image(
                    image, screenshot="synthetic_treehole", area="treehole", floor=4
                )
                self.assertTrue(result.success)
                self.assertEqual(result.template_id, template_id)
                self.assertEqual(result.region_id, "treehole_floor_4")
                self.assertEqual(result.template_source_region_id, template.region_id)

    def test_sixth_floor_fixed_template_from_synthetic_image(self) -> None:
        template = self.catalog.candidates("source_confluence", 6)[0]
        image = np.full((720, 1280, 3), 18, dtype=np.uint8)
        for a, b in template.edges:
            cv2.line(
                image,
                (270 + a[0] * 130, 130 + a[1] * 110),
                (270 + b[0] * 130, 130 + b[1] * 110),
                (100, 100, 100),
                7,
            )
        for col, row in template.occupied_slots:
            cv2.circle(image, (270 + col * 130, 130 + row * 110), 12, (230, 230, 230), 3)
        result = self.recognizer.recognize_image(
            image, screenshot="synthetic_vi", area="source_confluence", floor=6
        )
        self.assertTrue(result.success)
        self.assertEqual(result.template_id, "floor-6-01")
        self.assertEqual(len(result.nodes), len(template.occupied_slots))

    def test_one_row_treeholes_do_not_match_as_shorter_subset(self) -> None:
        templates = self.catalog.candidates("treehole", 4)
        for template_id in ("treehole-01", "treehole-08"):
            with self.subTest(template_id=template_id):
                template = next(item for item in templates if item.id == template_id)
                image = np.full((720, 1280, 3), 20, dtype=np.uint8)
                for a, b in template.edges:
                    cv2.line(
                        image,
                        (270 + a[0] * 120, 330 + a[1] * 120),
                        (270 + b[0] * 120, 330 + b[1] * 120),
                        (120, 120, 120),
                        8,
                    )
                for col, row in template.occupied_slots:
                    cv2.circle(image, (270 + col * 120, 330 + row * 120), 12, (230, 230, 230), 3)
                result = self.recognizer.recognize_image(
                    image, screenshot="synthetic_row", area="treehole", floor=4
                )
                self.assertTrue(result.success)
                self.assertEqual(result.template_id, template_id)

    def test_larger_treeholes_do_not_match_as_three_by_three_subset(self) -> None:
        templates = self.catalog.candidates("treehole", 4)
        for template_id in ("treehole-05", "treehole-06"):
            with self.subTest(template_id=template_id):
                template = next(item for item in templates if item.id == template_id)
                image = np.full((720, 1280, 3), 20, dtype=np.uint8)
                for a, b in template.edges:
                    cv2.line(
                        image,
                        (270 + a[0] * 120, 130 + a[1] * 100),
                        (270 + b[0] * 120, 130 + b[1] * 100),
                        (190, 190, 190),
                        8,
                    )
                for col, row in template.occupied_slots:
                    cv2.circle(image, (270 + col * 120, 130 + row * 100), 12, (230, 230, 230), 3)
                result = self.recognizer.recognize_image(
                    image, screenshot="synthetic_large_treehole", area="treehole", floor=4
                )
                self.assertTrue(result.success)
                self.assertEqual(result.template_id, template_id)

    def test_blank_image_fails_closed(self) -> None:
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        result = self.recognizer.recognize_image(image, screenshot="blank", area="main", floor=3)
        self.assertFalse(result.success)
        self.assertIsNone(result.template_id)
        self.assertEqual(result.nodes, [])

    def test_mark_candidate_can_be_detected_near_node(self) -> None:
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        mark = cv2.resize(cv2.imread("assets/lubiao/node_mark/node_mark_005.png"), (52, 52))
        image[325 - 26:325 + 26, 530 - 26:530 + 26] = mark
        detected = IconMatcher().detect_marks(image, (500, 350), 100)
        self.assertEqual([item["id"] for item in detected], ["node_mark_005"])

    def test_all_mark_badges_at_relative_position_and_multiple_grid_scales(self) -> None:
        matcher = IconMatcher()
        for number in range(1, 8):
            mark_id = f"node_mark_{number:03}"
            for step in (80, 140, 220):
                with self.subTest(mark=mark_id, step=step):
                    image = np.full((520, 600, 3), 20, np.uint8)
                    side = round(.34 * step)
                    template = cv2.imread(f"assets/lubiao/node_mark/{mark_id}.png")
                    badge = cv2.resize(template, (side, side))
                    x, y = round(260 + .20 * step), round(270 - .18 * step)
                    image[y - side // 2:y - side // 2 + side, x - side // 2:x - side // 2 + side] = badge
                    floor = 5 if mark_id == "node_mark_003" else 3
                    detected = matcher.detect_marks(image, (260, 270), step, area="main", floor=floor)
                    self.assertEqual([row["id"] for row in detected], [mark_id])

    def test_badge_outside_the_relative_corner_is_not_attached_to_a_node(self) -> None:
        image = np.full((400, 600, 3), 20, np.uint8)
        badge = cv2.resize(cv2.imread("assets/lubiao/node_mark/node_mark_002.png"), (34, 34))
        image[233:267, 163:197] = badge
        detected = IconMatcher().detect_marks(image, (230, 200), 100, area="main", floor=3)
        self.assertEqual(detected, [])

    @unittest.skipUnless((SCREENSHOTS / "Screenshot_2026.08.14_00.27.48.746.png").exists(), "local floor-I screenshot unavailable")
    def test_floor_one_screenshot(self) -> None:
        path = SCREENSHOTS / "Screenshot_2026.08.14_00.27.48.746.png"
        result = self.recognizer.recognize(path, area="main", floor=1)
        self.assertTrue(result.success)
        self.assertEqual(result.template_id, "floor-1-single-exit")
        self.assertEqual(len(result.nodes), 11)
        by_coord = {node.coord.key: node for node in result.nodes}
        self.assertEqual(by_coord["-1,0"].category_name, "作战")
        self.assertEqual(by_coord["2,0"].category_name, "未知的诡秘")
        self.assertEqual(by_coord["2,0"].visibility, "hidden")
        self.assertEqual(by_coord["3,0"].category_name, "险路尽头")
        self.assertTrue(all(node.completion == "unknown" for node in result.nodes))

    @unittest.skipUnless((SCREENSHOTS / "Screenshot_2026.08.14_00.39.27.286.png").exists(), "local floor-III screenshot unavailable")
    def test_floor_three_screenshot_and_overlay(self) -> None:
        path = SCREENSHOTS / "Screenshot_2026.08.14_00.39.27.286.png"
        result = self.recognizer.recognize(path, area="main", floor=3)
        self.assertTrue(result.success)
        self.assertEqual(result.template_id, "floor-3-01")
        self.assertEqual(len(result.nodes), 27)
        by_coord = {node.coord.key: node for node in result.nodes}
        self.assertEqual(by_coord["1,0"].category_name, "不期而遇")
        self.assertEqual(by_coord["5,0"].category_name, "险路恶敌")
        self.assertEqual(by_coord["2,1"].category_name, "未知的诡秘")
        self.assertEqual(by_coord["2,2"].category_name, "林间空地")
        self.assertEqual(by_coord["4,-1"].category_name, "紧急作战")
        image = cv2.imread(str(path))
        overlay = render_overlay(image, result)
        self.assertEqual(overlay.shape, image.shape)
        self.assertGreater(int(np.count_nonzero(overlay != image)), 500)

    @unittest.skipUnless((SCREENSHOTS / "Screenshot_2026.08.14_00.39.27.286.png").exists(), "local floor-III screenshot unavailable")
    def test_template_survives_one_changed_node(self) -> None:
        path = SCREENSHOTS / "Screenshot_2026.08.14_00.39.27.286.png"
        image = cv2.imread(str(path))
        x, y = 437 * 3, 345 * 3
        cv2.rectangle(image, (x - 130, y - 130), (x + 130, y + 130), (15, 15, 15), -1)
        result = self.recognizer.recognize_image(
            image, screenshot="changed_node", area="main", floor=3
        )
        self.assertTrue(result.success)
        self.assertEqual(result.template_id, "floor-3-01")
        self.assertTrue(any(node.category_id is None for node in result.nodes))


if __name__ == "__main__":
    unittest.main()
