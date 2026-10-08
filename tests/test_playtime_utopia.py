from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fulcrum.playtime_cli import main
from fulcrum.playtime_state import active_instance, merge_map_observation, new_playtime, validate_playtime
from fulcrum.playtime_view import render_map_sections
from fulcrum.map_catalog import TemplateCatalog


def observation(*, treehole=False) -> dict:
    return {
        "success": True, "area": "treehole" if treehole else "main", "floor": 3,
        "templateId": TemplateCatalog().candidates("treehole", 3)[0].id if treehole else "floor-3-01",
        "nodes": [
            {"id": "0,0", "coord": [0, 0], "slot": [0, 0], "categoryId": "start",
             "visibility": "revealed", "marks": []},
            {"id": "1,0", "coord": [1, 0], "slot": [1, 0], "categoryId": "node_type_001",
             "visibility": "revealed", "marks": []},
        ],
        "edges": [["0,0", "1,0"]],
    }


class PlaytimeUtopiaTests(unittest.TestCase):
    def test_cli_rejects_utopia_on_main_floor_without_saving(self):
        state = new_playtime("main-floor-utopia")
        observed = {**observation(), "area": "main", "templateId": "floor-3-01"}
        merge_map_observation(state, "III", observed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playtime.json"
            original = json.dumps(state)
            path.write_text(original, encoding="utf-8")
            with patch("sys.argv", ["playtime_cli", str(path), "set-utopia", "III", "utopia_005"]):
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    main()
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_utopia_survives_snapshot_refresh_and_old_state_without_field_is_valid(self) -> None:
        state = new_playtime("utopia")
        instance = merge_map_observation(state, "III-treehole", observation(treehole=True))
        instance["utopiaId"] = "utopia_005"
        merge_map_observation(state, "III-treehole", observation(treehole=True))
        self.assertEqual(active_instance(state, "III-treehole")["utopiaId"], "utopia_005")
        self.assertIn("| 当前乌托邦 | utopia_005 |", render_map_sections(state))
        del instance["utopiaId"]
        validate_playtime(state)
        instance["utopiaId"] = []
        with self.assertRaisesRegex(ValueError, "invalid utopia"):
            validate_playtime(state)

    def test_cli_sets_and_clears_utopia_without_overwriting_action_points(self) -> None:
        state = new_playtime("utopia-cli")
        merge_map_observation(state, "III-treehole", observation(treehole=True))["actionPoints"] = 8
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playtime.json"
            path.write_text(json.dumps(state), encoding="utf-8")
            for value, expected in (("utopia_005", "utopia_005"), ("none", None)):
                with patch("sys.argv", ["playtime_cli", str(path), "set-utopia", "III-treehole", value]):
                    with redirect_stdout(StringIO()):
                        main()
                updated = json.loads(path.read_text(encoding="utf-8"))
                instance = active_instance(updated, "III-treehole")
                self.assertEqual(instance["utopiaId"], expected)
                self.assertEqual(instance["actionPoints"], 8)
                self.assertEqual(updated["currentAreaKey"], "III-treehole")
                validate_playtime(updated)
