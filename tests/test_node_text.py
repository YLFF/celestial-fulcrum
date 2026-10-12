from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from fulcrum.vision_node_text import NodeLabelRecognizer, decode_label_sheet, label_crop, normalize_label
from fulcrum.vision_pipeline import MapRecognizer


ROOT = Path(__file__).resolve().parents[1]
LABELS = json.loads((ROOT / "data/vision_labels.json").read_text(encoding="utf-8"))["nodeTypes"]


def tsv_word(text, confidence=95, y=20, x=10):
    return f"5\t1\t1\t1\t1\t1\t{x}\t{y}\t100\t20\t{confidence}\t{text}\n"


class NodeTextTests(unittest.TestCase):
    def test_exact_dictionary_and_low_confidence_fail_closed(self):
        rows = {"0,1": {"top": 0, "bottom": 80, "box": [0, 0, 100, 20]}}
        for text, confidence, expected in (("紧 急 作 战", 95, "node_type_002"),
                                           ("作战", 74.9, None), ("紧急作", 99, None),
                                           ("路标作战", 99, None), ("ABC作战", 99, None)):
            with self.subTest(text=text):
                result = decode_label_sheet(tsv_word(text, confidence), rows, LABELS)["0,1"]
                self.assertEqual(result["categoryId"], expected)

    def test_headerless_tsv_groups_words_only_with_their_own_label(self):
        rows = {"a": {"top": 0, "bottom": 80, "box": [0, 0, 100, 20]},
                "b": {"top": 100, "bottom": 180, "box": [100, 0, 200, 20]}}
        tsv = tsv_word("未知的", x=10) + tsv_word("诡秘", x=50) + tsv_word("作战", y=120)
        result = decode_label_sheet(tsv, rows, LABELS)
        self.assertEqual(result["a"]["categoryId"], "unknown_mystery")
        self.assertEqual(result["b"]["categoryId"], "node_type_001")

    def test_clipped_emergency_prefix_cannot_be_read_as_ordinary_combat(self):
        rows = {"a": {"top": 0, "bottom": 80, "box": [0, 0, 100, 20], "glyphAspect": 4}}
        result = decode_label_sheet(tsv_word("作战"), rows, LABELS)["a"]
        self.assertIsNone(result["categoryId"])
        self.assertIsNone(result["candidateCategoryId"])

    def test_one_unreadable_character_cannot_be_hidden_by_the_average(self):
        rows = {"a": {"top": 0, "bottom": 80, "box": [0, 0, 100, 20]}}
        text = tsv_word("未知的", 99) + tsv_word("诡秘", 0, x=120)
        result = decode_label_sheet(text, rows, LABELS)["a"]
        self.assertIsNone(result["categoryId"])
        self.assertIsNone(result["candidateCategoryId"])

    def test_conflicting_accepted_variants_fall_back_to_icons(self):
        image = np.zeros((200, 300, 3), np.uint8)
        crop = np.full((60, 100), 255, np.uint8), (0, 0, 100, 20)
        data = {"tsv": tsv_word("作战", y=30) + tsv_word("紧急作战", y=118)}
        with patch("fulcrum.vision_node_text.label_crop", return_value=crop), \
                patch("fulcrum.vision_node_text.run_label_ocr", return_value=data):
            result = NodeLabelRecognizer(LABELS).recognize(image, {"a": (150, 100)}, 100, (0, 0, 300, 200))
        self.assertEqual(result["observations"]["a"]["status"], "conflict")
        self.assertIsNone(result["observations"]["a"]["categoryId"])

    def test_resident_quotes_normalize_but_arbitrary_letters_do_not(self):
        self.assertEqual(normalize_label(' “居民” 据点 '), "居民据点")
        self.assertEqual(normalize_label("CNN作战"), "CNN作战")

    def test_absent_text_does_not_start_an_ocr_process(self):
        image = np.full((200, 300, 3), 20, np.uint8)
        with patch("fulcrum.vision_node_text.run_label_ocr") as run:
            result = NodeLabelRecognizer(LABELS).recognize(image, {"0,1": (150, 100)}, 100, (0, 0, 300, 200))
        self.assertEqual(result["status"], "no_text")
        run.assert_not_called()

    def test_missing_model_and_failed_worker_fall_back_without_throwing(self):
        image = np.full((200, 300, 3), 20, np.uint8)
        reader = NodeLabelRecognizer(LABELS)
        with patch("fulcrum.vision_node_text.MODEL", ROOT / "missing-test-model"):
            self.assertEqual(reader.recognize(image, {}, 100, (0, 0, 300, 200))["status"], "unavailable")
        crop = np.full((60, 100), 255, np.uint8), (0, 0, 100, 20)
        with patch("fulcrum.vision_node_text.label_crop", return_value=crop), \
                patch("fulcrum.vision_node_text.run_label_ocr", side_effect=OSError("test failure")):
            self.assertEqual(reader.recognize(image, {"0,1": (150, 100)}, 100, (0, 0, 300, 200))["status"], "unavailable")

    def test_label_touching_crop_side_is_rejected(self):
        image = np.full((200, 300, 3), 20, np.uint8)
        cv2.rectangle(image, (96, 120), (112, 132), (255, 255, 255), -1)
        cv2.rectangle(image, (118, 120), (130, 132), (255, 255, 255), -1)
        self.assertIsNone(label_crop(image, (150, 100), 100, (0, 0, 300, 200)))

    def test_recognized_text_bypasses_icon_matching_and_keeps_completion_unknown(self):
        recognizer = MapRecognizer()
        template = recognizer.catalog.candidates("source_confluence", 6)[0]
        image = np.full((720, 1280, 3), 18, dtype=np.uint8)
        for a, b in template.edges:
            cv2.line(image, (270 + a[0] * 130, 130 + a[1] * 110),
                     (270 + b[0] * 130, 130 + b[1] * 110), (100, 100, 100), 7)
        for col, row in template.occupied_slots:
            cv2.circle(image, (270 + col * 130, 130 + row * 110), 12, (230, 230, 230), 3)
        observations = {template.coord(slot).key: {"categoryId": "node_type_002", "text": "紧急作战",
                                                  "confidence": 95, "status": "recognized"}
                        for slot in template.occupied_slots if slot != template.start_slot}
        with patch.object(recognizer.node_text, "recognize", return_value={"status": "completed", "observations": observations}), \
                patch.object(recognizer.icons, "classify_node", wraps=recognizer.icons.classify_node) as icons:
            result = recognizer.recognize_image(image, screenshot="test", area="source_confluence", floor=6)
        self.assertTrue(result.success)
        icons.assert_not_called()
        self.assertTrue(all(node.category_id == "node_type_002" and node.category_source == "text"
                            and node.completion == "unknown" for node in result.nodes if node.category_id != "start"))
        serialized = result.to_dict()
        self.assertIn("nodeTextObservation", serialized)
        self.assertTrue(any(node["textObservation"] for node in serialized["nodes"]))

    def test_offline_model_matches_recorded_provenance(self):
        metadata = json.loads((ROOT / "data/vision_ocr_models.json").read_text(encoding="utf-8"))["models"][0]
        self.assertEqual(hashlib.sha256((ROOT / metadata["file"]).read_bytes()).hexdigest(), metadata["sha256"])


if __name__ == "__main__":
    unittest.main()
