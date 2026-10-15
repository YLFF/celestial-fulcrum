from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from fulcrum.vision_node_text import NodeLabelRecognizer, corroborated_label_candidate, decode_label_sheet, label_crop, normalize_label, repeated_complete_label
from fulcrum.vision_pipeline import MapRecognizer
from fulcrum.vision_icons import IconMatch


ROOT = Path(__file__).resolve().parents[1]
LABELS = json.loads((ROOT / "data/vision_labels.json").read_text(encoding="utf-8"))["nodeTypes"]


def tsv_word(text, confidence=95, y=20, x=10):
    return f"5\t1\t1\t1\t1\t1\t{x}\t{y}\t100\t20\t{confidence}\t{text}\n"


class NodeTextTests(unittest.TestCase):
    def test_weak_last_character_needs_multiple_methods_and_only_proposes_a_category(self):
        observation = {"status": "unconfirmed", "categoryId": None, "variants": [
            {"text": "狭路相着", "confidence": 68, "method": "gray"},
            {"text": "狭路相才", "confidence": 68, "method": "binary"},
            {"text": "狭路相逢", "confidence": 39, "method": "gray|line", "lexicalCategoryId": "node_type_011"}]}
        self.assertEqual(corroborated_label_candidate(observation, LABELS), "node_type_011")
        self.assertIsNone(observation["categoryId"])
        self.assertIsNone(corroborated_label_candidate({**observation, "variants": observation["variants"][:1]}, LABELS))
        self.assertIsNone(corroborated_label_candidate({**observation, "status": "conflict"}, LABELS))
        other = {"text": "不期而遇", "confidence": 90, "method": "gray|line", "lexicalCategoryId": "node_type_006"}
        self.assertIsNone(corroborated_label_candidate({**observation, "variants": [*observation["variants"], other]}, LABELS))

    def test_corroboration_does_not_relax_unknown_nodes_short_words_or_ambiguous_prefixes(self):
        for first, second in (("未知的凶庞", "未知的凶戾"), ("未知的诡密", "未知的诡秘"),
                              ("失与诵", "失与得"), ("狭路相", "狭路相"), ("狭路相着", "狭路相才")):
            observation = {"variants": [{"text": first, "confidence": 59, "method": "gray"},
                                         {"text": second, "confidence": 59, "method": "binary"}]}
            self.assertIsNone(corroborated_label_candidate(observation, LABELS))
        ambiguous = {"a": "相同前缀甲", "b": "相同前缀乙"}
        observation = {"variants": [{"text": "相同前缀丙", "confidence": 90, "method": "gray"},
                                     {"text": "相同前缀丁", "confidence": 90, "method": "binary"}]}
        self.assertIsNone(corroborated_label_candidate(observation, ambiguous))

    def test_complete_distinctive_names_have_a_lower_threshold_but_similar_families_do_not(self):
        rows = {"a": {"top": 0, "bottom": 80, "box": [0, 0, 100, 20]}}
        for name, confidence, expected in (("狭路相逢", 55, "node_type_011"), ("狭路相逢", 54.9, None),
                                           ("失与得", 55, "node_type_008"), ("曲折密道", 55, "node_type_014"),
                                           ("诡意行商", 64.9, None), ("秘境行商", 64.9, None),
                                           ("诡意行商", 65, "node_type_004"), ("秘境行商", 65, "node_type_013"),
                                           ("未知的诡秘", 74.9, None), ("未知的凶戾", 74.9, None),
                                           ("紧急作战", 64.9, None), ("作战", 74.9, None)):
            with self.subTest(name=name, confidence=confidence):
                self.assertEqual(decode_label_sheet(tsv_word(name, confidence), rows, LABELS)["a"]["categoryId"], expected)

    def test_similar_shops_cannot_use_weak_prefix_corroboration(self):
        for name in ("诡意行商", "秘境行商", "未知的诡秘", "未知的凶戾", "紧急作战"):
            observation = {"variants": [{"text": name, "confidence": 39, "method": "gray"},
                                         {"text": name, "confidence": 42, "method": "gray|line"}]}
            self.assertIsNone(corroborated_label_candidate(observation, LABELS))

    def test_repeated_complete_names_are_distinct_from_partial_agreement(self):
        observation = {"variants": [{"text": "狭路相逢", "confidence": 31.11, "method": "gray"},
                                     {"text": "狭路相逢", "confidence": 41.84, "method": "gray|line"},
                                     {"text": "狭路相庆", "confidence": 68.33, "method": "binary"}]}
        self.assertEqual(corroborated_label_candidate(observation, LABELS), "node_type_011")
        self.assertTrue(repeated_complete_label(observation, LABELS["node_type_011"]))
        observation["variants"][1]["text"] = "狭路相才"
        self.assertFalse(repeated_complete_label(observation, LABELS["node_type_011"]))

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

    def test_corroborated_text_still_needs_icon_and_cannot_replace_strong_visual_evidence(self):
        recognizer = MapRecognizer()
        template = recognizer.catalog.candidates("source_confluence", 6)[0]
        target = next(slot for slot in template.occupied_slots if slot != template.start_slot)
        image = np.full((720, 1280, 3), 18, dtype=np.uint8)
        for a, b in template.edges:
            cv2.line(image, (270 + a[0] * 130, 130 + a[1] * 110),
                     (270 + b[0] * 130, 130 + b[1] * 110), (100, 100, 100), 7)
        for col, row in template.occupied_slots:
            cv2.circle(image, (270 + col * 130, 130 + row * 110), 12, (230, 230, 230), 3)
        observations = {template.coord(slot).key: {"categoryId": "node_type_002", "text": "紧急作战",
                                                  "confidence": 95, "status": "recognized"}
                        for slot in template.occupied_slots if slot != template.start_slot}
        observations[template.coord(target).key] = {"status": "unconfirmed", "variants": [
            {"text": "狭路相着", "confidence": 68, "method": "gray"},
            {"text": "狭路相才", "confidence": 68, "method": "binary"}]}
        for icon_score, current_score, complete, expected in ((.64, None, False, "node_type_011"), (.59, None, False, None),
                                                            (.64, .80, False, "node_type_006"), (.64, .62, False, "node_type_006"),
                                                            (.64, .58, False, "node_type_011"), (.64, .62, True, "node_type_011"),
                                                            (.64, .66, True, "node_type_006"), (.61, .62, True, "node_type_006")):
            with self.subTest(icon_score=icon_score, current_score=current_score, complete=complete):
                current = IconMatch("node_type_006", "不期而遇", current_score, .1) if current_score else None
                def confirm(_image, _pixel, _step, category, *, minimum=.60, **_):
                    self.assertEqual(category, "node_type_011")
                    return IconMatch(category, "狭路相逢", icon_score, 0) if icon_score >= minimum else None
                candidate_observations = deepcopy(observations)
                if complete:
                    candidate_observations[template.coord(target).key]["variants"] = [
                        {"text": "狭路相逢", "confidence": 31, "method": "gray"},
                        {"text": "狭路相逢", "confidence": 42, "method": "gray|line"}]
                with patch.object(recognizer.node_text, "recognize", return_value={"observations": candidate_observations}), \
                     patch.object(recognizer.icons, "classify_node", return_value=(current, [current] if current else [])), \
                     patch.object(recognizer.icons, "confirm_text_candidate", side_effect=confirm), \
                     patch.object(recognizer.icons, "refine_node", return_value=None):
                    result = recognizer.recognize_image(image, screenshot="test", area="source_confluence", floor=6)
                node = next(node for node in result.nodes if node.slot == target)
                if expected is None:
                    self.assertNotEqual(node.category_id, "node_type_011")
                else:
                    self.assertEqual(node.category_id, expected)

    def test_offline_model_matches_recorded_provenance(self):
        metadata = json.loads((ROOT / "data/vision_ocr_models.json").read_text(encoding="utf-8"))["models"][0]
        self.assertEqual(hashlib.sha256((ROOT / metadata["file"]).read_bytes()).hexdigest(), metadata["sha256"])


if __name__ == "__main__":
    unittest.main()
