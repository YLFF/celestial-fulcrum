import importlib.util
import os
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.export_macos_source import source_files
from fulcrum.product import PROJECT
from fulcrum.service.catalog import entries, image_path

ROOT = Path(__file__).resolve().parents[1]


class MacBuildMaterialsTests(unittest.TestCase):
    def test_source_snapshot_has_assets_but_no_player_data_or_root_readme(self):
        paths = set(source_files())
        names = {path.relative_to(ROOT).as_posix() for path in paths}
        self.assertNotIn("README.md", names)
        self.assertTrue(all(not name.startswith(("work/", "runs/", ".git/", ".venv/", "node_modules/")) for name in names))
        self.assertIn("frontend/pnpm-workspace.yaml", names)
        self.assertIn("eng.traineddata", names)
        self.assertIn("chi_sim.traineddata", names)
        self.assertIn("scripts/ocr_node_labels.mjs", names)
        self.assertIn("packaging/tessdata_fast.LICENSE", names)
        self.assertIn("packaging/MACOS_TEST.md", names)
        self.assertIn("data/scoring/blackflow/default.json", names)
        self.assertIn("data/scoring/blackflow/relics.json", names)
        for path in (ROOT / "data/relic_effects").rglob("*.json"):
            self.assertIn(path.relative_to(ROOT).as_posix(), names)
        for entry in entries().values():
            if entry.get("imagePath"):
                self.assertIn(image_path(entry["id"]), paths, entry["id"])
        self.assertIn(ROOT / "frontend/public/ui-assets/map-backgrounds/flower-tree.png", paths)

    @unittest.skipUnless(importlib.util.find_spec("PyInstaller"), "builder dependencies")
    def test_mac_manifest_contains_all_icons_and_native_node_binary(self):
        def analysis(*args, **kwargs):
            return SimpleNamespace(pure=[], scripts=[], binaries=kwargs["binaries"], datas=kwargs["datas"])
        with patch.dict(os.environ, {"FULCRUM_BUILD_INPUT": str(ROOT / "build/macos-input")}), \
                patch("PyInstaller.utils.hooks.collect_submodules", return_value=[]):
            spec = runpy.run_path(str(ROOT / "packaging/fulcrum-macos.spec"), init_globals={
                "SPECPATH": str(ROOT / "packaging"), "Analysis": analysis,
                "PYZ": lambda *args: None, "EXE": lambda *args, **kwargs: kwargs,
                "COLLECT": lambda *args, **kwargs: None, "BUNDLE": lambda *args, **kwargs: kwargs,
            })
        bundled = {Path(source).resolve() for source, _ in spec["datas"]}
        self.assertIn(ROOT / "chi_sim.traineddata", bundled)
        self.assertIn(ROOT / "scripts/ocr_node_labels.mjs", bundled)
        self.assertIn(ROOT / "packaging/tessdata_fast.LICENSE", bundled)
        for path in (ROOT / "data/scoring").rglob("*.json"):
            self.assertIn((str(path), str(path.relative_to(ROOT).parent)), spec["datas"])
        for path in (ROOT / "data/relic_effects").rglob("*.json"):
            self.assertIn((str(path), str(path.relative_to(ROOT).parent)), spec["datas"])
        for entry in entries().values():
            if entry.get("imagePath"):
                self.assertIn(image_path(entry["id"]), bundled, entry["id"])
        self.assertEqual(spec["exe"]["target_arch"], "arm64")
        self.assertEqual(spec["app"]["name"], PROJECT["executableName"] + ".app")
        self.assertIn((str(ROOT / "build/macos-input/runtime/node/bin/node"), "runtime/node/bin"), spec["a"].binaries)
        self.assertIn((str(ROOT / "frontend/dist"), "frontend/dist"), spec["datas"])


if __name__ == "__main__":
    unittest.main()
