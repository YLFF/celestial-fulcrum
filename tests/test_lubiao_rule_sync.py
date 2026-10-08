"""The prediction dataset is a validated, replaceable local input."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.sync_lubiao_prediction_data import (
    HEADERS, NAME_TO_TYPE, OUTPUT, REQUIRED_SAMPLE_TYPES, build_data, build_rules, extract_samples, main,
)


DATA = json.loads(OUTPUT.read_text(encoding="utf-8"))
TYPE_TO_NAME = {node_type: label for label, node_type in NAME_TO_TYPE.items()}
CHUNK = (
    'Dr={updatedAt:"2026-10-01T05:31:38+00:00"},fs={'
    'combat:{0:{1:2},remembrance:{1:1}},'
    'encounter:{0:{2:3},remembrance:{2:1}},'
    '"wrong-turn":{0:{5:1},remembrance:{5:2}},'
    + ','.join(
        f'"{node_type}":{{0:{{1:1}},remembrance:{{1:1}}}}'
        for node_type in sorted(REQUIRED_SAMPLE_TYPES - {"combat", "encounter", "wrong-turn"})
    )
    + '};'
)


def sample_snapshot() -> dict:
    return {
        "source": DATA["source"],
        "ruleVersion": DATA["ruleVersion"],
        "sampleCount": DATA["sampleCount"],
        "sampleUpdatedAt": DATA["sampleUpdatedAt"],
        "distance": [HEADERS, *[
            [TYPE_TO_NAME[node_type], *values]
            for node_type, values in DATA["distanceRanges"].items()
        ]],
        "count": [HEADERS, *[
            [TYPE_TO_NAME[node_type], *values]
            for node_type, values in DATA["countRanges"].items()
        ]],
        "types": {
            floor: [TYPE_TO_NAME[node_type] for node_type in DATA["allowedTypes"][floor]]
            for floor in ("I", "II", "III", "IV", "V")
        },
    }


class LubiaoDataSyncTests(unittest.TestCase):
    def test_rendered_tables_rebuild_installed_rules(self) -> None:
        rebuilt = build_rules(sample_snapshot())
        for key, value in rebuilt.items():
            if key != "schemaVersion":
                self.assertEqual(value, DATA[key])
        self.assertEqual(rebuilt["allowedTypes"]["IV追忆"], rebuilt["allowedTypes"]["IV"])

    def test_table_shape_and_unknown_type_fail_closed(self) -> None:
        shortened = sample_snapshot()
        shortened["distance"][7].pop()
        with self.assertRaisesRegex(ValueError, "columns"):
            build_rules(shortened)
        renamed = sample_snapshot()
        renamed["count"][1][0] = "new event node"
        with self.assertRaisesRegex(ValueError, "new or renamed"):
            build_rules(renamed)

    def test_sample_parser_and_bad_source_fail_closed(self) -> None:
        updated_at, samples = extract_samples(CHUNK)
        self.assertEqual(updated_at, "2026-10-01T05:31:38+00:00")
        self.assertEqual(samples["encounter"]["remembrance"]["2"], 1)
        with self.assertRaisesRegex(ValueError, "dated distance samples"):
            extract_samples('fs={combat:{0:{1:2}}}')
        incomplete = CHUNK.replace('"narrow-meet":{0:{1:1},remembrance:{1:1}},', '')
        with self.assertRaisesRegex(ValueError, "missing node types"):
            extract_samples(incomplete)
        with self.assertRaisesRegex(ValueError, "URL"):
            build_data(sample_snapshot(), CHUNK, "https://example.com/_nuxt/route.js")

    def test_check_apply_idempotence_and_no_downgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            snapshot = directory / "snapshot.json"
            chunk = directory / "route.js"
            output = directory / "prediction.json"
            snapshot.write_text(json.dumps(sample_snapshot(), ensure_ascii=False), encoding="utf-8")
            chunk.write_text(CHUNK, encoding="utf-8")
            args = ["--snapshot", str(snapshot), "--chunk", str(chunk), "--output", str(output)]
            self.assertEqual(main(args), 1)
            self.assertFalse(output.exists())
            self.assertEqual(main([*args, "--apply"]), 0)
            applied = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(applied, build_data(sample_snapshot(), CHUNK, "https://www.lubiao.wiki/_nuxt/route.js"))
            self.assertEqual(main(args), 0)
            chunk.write_text(CHUNK.replace("2026-10-01", "2025-10-01"), encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                main([*args, "--apply"])
            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), applied)


if __name__ == "__main__":
    unittest.main()
