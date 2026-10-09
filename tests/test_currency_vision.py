import unittest
from pathlib import Path
import json

import cv2
import numpy as np

from fulcrum.vision_currency import ATLAS, recognize_currency
from fulcrum.vision_resources import _box
from fulcrum.vision_geometry import detect_map_viewport, working_image

ROOT = Path(__file__).resolve().parents[1]


class CurrencyVisionTests(unittest.TestCase):
    def test_all_archived_currency_values(self):
        samples = json.loads((ROOT / "samples/maps/resources_expected.json").read_text(encoding="utf-8"))["samples"]
        for sample in [*samples, {"file": "desktop_floor_2_progress.png", "originium_ingot": 23}]:
            with self.subTest(sample=sample["file"]):
                image = cv2.imread(str(ROOT / "samples/maps" / sample["file"]))
                work, scale = working_image(image)
                viewport = tuple(round(value / scale) for value in detect_map_viewport(work))
                ui_scale = .9 if sample["file"].startswith('desktop_') else 1
                x0, y0, x1, y1 = _box(image, viewport, 'originium_ingot', ui_scale)
                result = recognize_currency(image[y0:y1, x0:x1], image.shape[0] / 1152 * ui_scale)
                self.assertEqual(result["value"], sample["originium_ingot"])

    def test_three_digits_are_not_truncated(self):
        with np.load(ATLAS) as atlas:
            mask = np.concatenate([atlas[digit] for digit in '235'], axis=1) * 255
        mask = cv2.copyMakeBorder(mask, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
        result = recognize_currency(cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR), 1)
        self.assertEqual(result['value'], 235)
        self.assertEqual(result['digitCount'], 3)
        self.assertEqual(result['status'], 'recognized')

    def test_blank_image_is_unreadable(self):
        result = recognize_currency(np.zeros((70, 250, 3), dtype=np.uint8), 1)
        self.assertIsNone(result['value'])
        self.assertEqual(result['status'], 'unreadable')
