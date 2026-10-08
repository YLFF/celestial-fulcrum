from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from fulcrum.map_catalog import TemplateCatalog
from fulcrum.map_model import Coord


class MapCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = TemplateCatalog()

    def test_treehole_candidates_are_shared_across_entry_floors(self) -> None:
        expected = {item.id for item in self.catalog.candidates("treehole", 3)}
        self.assertEqual(len(expected), 9)
        self.assertEqual(expected, {item.id for item in self.catalog.candidates("treehole", 4)})
        self.assertEqual(expected, {item.id for item in self.catalog.candidates("treehole", 5)})

    def test_sixth_floor_uses_fixed_template(self) -> None:
        templates = self.catalog.candidates("source_confluence", 6)
        self.assertEqual([item.id for item in templates], ["floor-6-01"])

    def test_start_relative_coordinate_and_edges(self) -> None:
        template = next(item for item in self.catalog.templates if item.id == "floor-3-01")
        self.assertEqual(template.coord(template.start_slot), Coord(0, 0))
        self.assertEqual(template.coord((1, 2)), Coord(1, 0))
        self.assertEqual(template.coord((2, 1)), Coord(2, 1))
        occupied = set(template.occupied_slots)
        self.assertTrue(all(a in occupied and b in occupied for a, b in template.edges))

    def test_visual_labels_match_reference_headings(self) -> None:
        root = Path(__file__).resolve().parents[1]
        reference = (root / "BLACKSTREAM_REFERENCE.md").read_text(encoding="utf-8")
        labels = json.loads((root / "data" / "vision_labels.json").read_text(encoding="utf-8"))
        for section, pattern in (
            ("nodeTypes", r"^### (node_type_\d{3}) (.+)$"),
            ("nodeMarks", r"^### (node_mark_\d{3}) (.+)$"),
        ):
            expected = dict(re.findall(pattern, reference, flags=re.MULTILINE))
            if section == "nodeTypes":
                # Pursuit is triggered outside the map when action points run out.
                expected.pop("node_type_022", None)
                self.assertNotIn("node_type_022", labels[section])
            actual = {key: value for key, value in labels[section].items() if key in expected}
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
