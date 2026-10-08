"""A screenshot can populate the confirmed current Playtime snapshot."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "local OCR runtime is required")
class PlaytimeRoundTripTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"PYTHONUTF8": "1"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_screenshot_to_map_position_resources_and_component_box(self) -> None:
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("OpenCV is required")
        with tempfile.TemporaryDirectory(prefix="darkflow-e2e-") as temp:
            root = Path(temp)
            screenshot = ROOT / "samples" / "maps" / "bluestacks_floor_3.png"
            map_json = root / "map.json"
            run_json = root / "check.json"
            commands = [
                [sys.executable, str(ROOT / "scripts" / "new_run.py"), "--run-id", "check", "--output-dir", str(root)],
                [sys.executable, "-m", "fulcrum.cli", str(screenshot), "--resources", "--out", str(map_json)],
                [sys.executable, "-m", "fulcrum.playtime_cli", str(run_json), "import-map", "III", str(map_json)],
                [sys.executable, "-m", "fulcrum.playtime_cli", str(run_json), "add-component", "component_015", "--value", "12"],
            ]
            for command in commands:
                completed = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=90, check=False)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            state = json.loads(run_json.read_text(encoding="utf-8"))
            instance = state["areas"]["III"]["instances"][0]
            self.assertEqual(instance["playerPosition"], "0,0")
            self.assertEqual(instance["actionPoints"], 7)
            self.assertEqual(state["resources"]["hope"], 14)
            self.assertEqual(state["resources"]["originiumIngot"], 16)
            self.assertEqual(
                [item["remainingUses"] for item in state["componentBox"]["items"] if item["componentId"] == "component_015"],
                [3],
            )
            self.assertEqual(sum(item["componentId"] == "component_001" for item in state["componentBox"]["items"]), 2)
            markdown = run_json.with_suffix(".md").read_text(encoding="utf-8")
            self.assertIn("| 玩家位置 / 行动力 | `0,0` / 7 |", markdown)
            self.assertIn("零件箱（当前 3 件，上限 8 件）", markdown)
            self.assertIn("| 希望 | 14 | - |", markdown)

            partial = root / "partial.json"
            recognized = subprocess.run(
                [sys.executable, "-m", "fulcrum.cli", str(ROOT / "samples" / "maps" / "attachment_02.jpg"),
                 "--resources", "--out", str(partial)],
                cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=90, check=False,
            )
            self.assertEqual(recognized.returncode, 2, recognized.stdout + recognized.stderr)
            imported = subprocess.run(
                [sys.executable, "-m", "fulcrum.playtime_cli", str(run_json), "import-resources", str(partial)],
                cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=90, check=False,
            )
            self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
            refreshed = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(refreshed["resources"]["hope"], 2)
            self.assertEqual(refreshed["resources"]["originiumIngot"], 16)
            self.assertEqual(refreshed["areas"]["III"]["instances"][0]["actionPoints"], 3)
            self.assertEqual(refreshed["areas"]["III"]["instances"][0]["playerPosition"], "0,0")


if __name__ == "__main__":
    unittest.main()
