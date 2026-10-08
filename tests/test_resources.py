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
    from fulcrum.vision_resources import HudRecognizer, _parse_field
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
        self.assertEqual(self.recognizer.recognize_image(image)["fields"]["originium_ingot"]["status"], "needs_review")

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
        self.assertEqual(result.resource_observation, {"error": "OCR unavailable"})
        self.assertTrue(any("HUD OCR unavailable" in warning for warning in result.warnings))

    def test_parser_rejects_partial_readings(self) -> None:
        self.assertIsNone(_parse_field("life", "/8"))
        self.assertIsNone(_parse_field("experience", "1198"))
        self.assertIsNone(_parse_field("hope", ""))
        self.assertEqual(_parse_field("experience", "1198/0"), {"current": 1198, "max": 0})


if __name__ == "__main__":
    unittest.main()
