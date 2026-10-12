from pathlib import Path
import shutil
import unittest

import cv2

from fulcrum.vision_pipeline import MapRecognizer, match_quality
from fulcrum.vision_resources import HudRecognizer
from fulcrum.map_catalog import TemplateCatalog
from fulcrum.map_model import TemplateMatch

ROOT = Path(__file__).resolve().parents[1]


class NativeHudTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required for local OCR")
    def test_compact_native_hud_all_resources(self):
        fields = HudRecognizer().recognize_image(cv2.imread(str(ROOT / "samples/maps/desktop_native_3840.png")))["fields"]
        self.assertEqual((fields["life"]["current"], fields["life"]["max"]), (4, 4))
        self.assertEqual((fields["experience"]["current"], fields["experience"]["max"]), (0, 10))
        for key, expected in {"level": 1, "shield": 2, "hope": 1, "originium_ingot": 25, "action_points": 6}.items():
            self.assertEqual(fields[key]["value"], expected, key)
        self.assertTrue(all(row["status"] == "recognized" for row in fields.values()))

    def test_map_quality_is_not_a_posterior_probability(self):
        template = TemplateCatalog().candidates("main", 1)[0]
        good = TemplateMatch(template, 200, 180, 100, 100, .85, .85, 10, 0, .8)
        self.assertTrue(match_quality(good, (0, 70, 1280, 640))["accepted"])
        sparse = TemplateMatch(template, 200, 180, 100, 100, .7, .7, 8, 0, .8)
        self.assertFalse(match_quality(sparse, (0, 70, 1280, 640))["accepted"])
        self.assertFalse(match_quality(good, (0, 70, 450, 640))["accepted"])

    def test_second_floor_progress_map_and_currency(self):
        result = MapRecognizer().recognize(ROOT / "samples/maps/desktop_floor_2_progress.png", include_resources=True)
        self.assertTrue(result.success)
        self.assertEqual(result.template_id, "floor-2-09")
        self.assertEqual(len(result.nodes), 19)
        self.assertEqual(result.player_position_observation["nodeId"], "0,0")
        self.assertEqual(result.resource_observation["fields"]["originium_ingot"]["value"], 23)
        self.assertEqual(result.resource_observation["fields"]["originium_ingot"]["status"], "recognized")
        for node in result.nodes:
            if node.category_id is None:
                self.assertTrue(any(f"({node.coord.key})" in warning and "类型未识别" in warning for warning in result.warnings))

    @unittest.skipUnless(shutil.which("node"), "Node required for local OCR")
    def test_low_contrast_screenshot_keeps_uncertain_currency_for_review(self):
        image = cv2.imread(str(ROOT / "samples/maps/desktop_floor2_lookout_revealed.png"))
        fields = HudRecognizer().recognize_image(image)["fields"]
        self.assertEqual((fields["life"]["current"], fields["life"]["max"]), (6, 6))
        self.assertEqual((fields["experience"]["current"], fields["experience"]["max"]), (3, 24))
        for key, expected in {"level": 2, "shield": 2, "hope": 4, "action_points": 6}.items():
            self.assertEqual(fields[key]["value"], expected, key)
            self.assertEqual(fields[key]["status"], "recognized", key)
        self.assertEqual(fields["originium_ingot"]["value"], 9)
        self.assertEqual(fields["originium_ingot"]["status"], "needs_review")

    def test_full_native_map(self):
        result = MapRecognizer().recognize(ROOT / "samples/maps/desktop_native_3840.png")
        self.assertTrue(result.success)
        self.assertEqual(result.template_id, "floor-1-vertical-fork")
        self.assertEqual(len(result.nodes), 13)
        self.assertTrue(any("单张截图不能确认" in warning for warning in result.warnings))
        self.assertTrue(all(any("\u4e00" <= char <= "\u9fff" for char in warning) for warning in result.warnings))

    def test_missing_map_regions_fail_even_with_manual_template(self):
        image = cv2.imread(str(ROOT / "samples/maps/desktop_native_3840.png"))
        for bounds in [(0, 1300, 3840, 1950), (0, 220, 1560, 1950), (2150, 220, 3840, 1950)]:
            with self.subTest(bounds=bounds):
                partial = image.copy()
                x0, y0, x1, y1 = bounds
                partial[y0:y1, x0:x1] = 0
                for template in (None, "floor-1-vertical-fork"):
                    result = MapRecognizer().recognize_image(partial, screenshot="partial", area="main", floor=1, template_override=template)
                    self.assertFalse(result.success)
                    self.assertFalse(result.match_quality["accepted"])
                    self.assertEqual(result.nodes, [])


if __name__ == "__main__":
    unittest.main()
