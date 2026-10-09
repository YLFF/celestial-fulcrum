from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import cv2
    import numpy as np

    from fulcrum.vision_pipeline import MapRecognizer
    from fulcrum.vision_geometry import detect_map_viewport, working_image
    from fulcrum.vision_resources import HudRecognizer, _box, _hope_digits, _hope_zero_score, _parse_field
except ImportError:
    cv2 = None


SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "maps"


@unittest.skipUnless(cv2 is not None and shutil.which("node"), "OpenCV and local Node.js OCR are required")
class ResourceVisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.expected = json.loads((SAMPLES / "resources_expected.json").read_text(encoding="utf-8"))["samples"]
        cls.recognizer = HudRecognizer()

    def test_hud_fields_across_archived_screenshots(self) -> None:
        self.assertEqual(len(self.expected), 10)
        for sample in self.expected:
            with self.subTest(sample=sample["file"]):
                image = cv2.imread(str(SAMPLES / sample["file"]))
                result = self.recognizer.recognize_image(image)
                self.assertEqual(result["backend"], "local_tesseract_js")
                fields = result["fields"]
                self.assertEqual(set(fields), set(sample) - {"file"})
                for name, expected in sample.items():
                    if name == "file":
                        continue
                    observed = fields[name]
                    actual = [observed["current"], observed["max"]] if isinstance(expected, list) else observed["value"]
                    self.assertEqual(actual, expected, name)
                    self.assertIn(observed["status"], {"recognized", "absent_zero", "needs_review", "unreadable"})
                    if expected is not None:
                        self.assertNotEqual(observed["status"], "unreadable")
                    x0, y0, x1, y1 = observed["roi"]
                    self.assertTrue(0 <= x0 < x1 <= image.shape[1])
                    self.assertTrue(0 <= y0 < y1 <= image.shape[0])
                if sample["shield"] == 0:
                    self.assertEqual(fields["shield"]["status"], "absent_zero")
        image = cv2.imread(str(SAMPLES / "attachment_02.jpg"))
        currency = self.recognizer.recognize_image(image)["fields"]["originium_ingot"]
        self.assertEqual(currency["status"], "recognized")
        self.assertEqual(currency["method"], "cv_currency_atlas")

    def test_blank_image_does_not_become_zero_shield(self) -> None:
        image = np.zeros((931, 2048, 3), dtype=np.uint8)
        fields = self.recognizer.recognize_image(image)["fields"]
        self.assertIsNone(fields["shield"]["value"])
        self.assertEqual(fields["shield"]["status"], "unreadable")
        self.assertIsNone(fields["hope"]["value"])
        self.assertIsNone(fields["action_points"]["value"])

    def test_map_pipeline_can_include_resources_on_partial_map(self) -> None:
        path = SAMPLES / "attachment_02.jpg"
        result = MapRecognizer().recognize(path, include_resources=True)
        self.assertFalse(result.success)
        self.assertEqual(result.resource_observation["fields"]["hope"]["value"], 2)
        self.assertEqual(result.to_dict()["resourceObservation"], result.resource_observation)

    def test_ocr_failure_does_not_discard_map(self) -> None:
        with patch.object(HudRecognizer, "recognize_image", side_effect=RuntimeError("OCR unavailable")):
            result = MapRecognizer().recognize(SAMPLES / "attachment_04.jpg", include_resources=True)
        self.assertTrue(result.success)
        self.assertEqual(result.template_id, "floor-4-11")
        self.assertEqual(result.resource_observation["diagnosticDetail"], "OCR unavailable")
        self.assertIn("操作未完成", result.resource_observation["error"])
        self.assertTrue(any("资源文字识别不可用" in warning for warning in result.warnings))

    def test_parser_rejects_partial_readings(self) -> None:
        self.assertIsNone(_parse_field("life", "/8"))
        self.assertIsNone(_parse_field("experience", "1198"))
        self.assertIsNone(_parse_field("hope", ""))
        self.assertEqual(_parse_field("experience", "1198/0"), {"current": 1198, "max": 0})


@unittest.skipUnless(cv2 is not None, "OpenCV is required")
class HopeZeroTests(unittest.TestCase):
    def test_slashed_zero_at_different_sizes_and_anchor_scales(self):
        source = cv2.imread(str(SAMPLES.parent / "hud" / "hope_zero_currency.png"))
        for factor in (0.4, 0.6, 1.0, 1.5):
            image = cv2.resize(source, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
            for scale in (1.0, 1.6875):
                with self.subTest(factor=factor, scale=scale):
                    digits = _hope_digits(image, scale * factor)
                    self.assertIsNotNone(digits)
                    self.assertIsNotNone(_hope_zero_score(digits))

    def test_nonzero_archived_hope_is_not_overridden(self):
        expected = json.loads((SAMPLES / "resources_expected.json").read_text(encoding="utf-8"))["samples"]
        for sample in [*expected, {"file": "desktop_native_3840.png"}]:
            with self.subTest(sample=sample["file"]):
                image = cv2.imread(str(SAMPLES / sample["file"]))
                work, scale = working_image(image)
                viewport = tuple(round(value / scale) for value in detect_map_viewport(work))
                ui_scale = 0.9 if sample["file"].startswith("desktop_") else 1.0
                x0, y0, x1, y1 = _box(image, viewport, "hope", ui_scale)
                digits = _hope_digits(image[y0:y1, x0:x1], image.shape[0] / 1152 * ui_scale)
                self.assertIsNotNone(digits)
                self.assertIsNone(_hope_zero_score(digits))

    def test_blank_and_solid_shapes_are_not_zero(self):
        blank = np.zeros((100, 100), dtype=np.uint8)
        self.assertIsNone(_hope_zero_score(blank))
        blank[10:80, 25:70] = 255
        self.assertIsNone(_hope_zero_score(blank))

    @unittest.skipUnless(shutil.which("node"), "Node required for local OCR")
    def test_zero_glyph_fallback_in_full_hud(self):
        # Insert the labelled crop into a full HUD to exercise the OCR fallback.
        image = cv2.imread(str(SAMPLES / "desktop_native_3840.png"))
        source = cv2.imread(str(SAMPLES.parent / "hud" / "hope_zero_currency.png"))
        x0, y0, x1, y1 = _box(image, (0, 0, image.shape[1], image.shape[0]), "hope", 0.9)
        image[y0:y1, x0:x1] = source[35:35 + y1-y0, :x1-x0]
        hope = HudRecognizer().recognize_image(image)["fields"]["hope"]
        self.assertEqual(hope["value"], 0)
        self.assertEqual(hope["status"], "recognized")
        self.assertEqual(hope["method"], "cv_slashed_zero")
        self.assertGreaterEqual(hope["matchScore"], 0.91)


if __name__ == "__main__":
    unittest.main()
