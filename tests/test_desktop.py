import os
import importlib.util
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from fulcrum.desktop import data_directory, desktop_engine, LocalServer, single_instance, check_windows_bundle_trust, startup_message
from fulcrum.playtime_state import new_playtime
from fulcrum.playtime_view import render_standalone
from fulcrum.runtime import node_runtime
from fulcrum.product import PROJECT
from fulcrum.service.catalog import editor_catalog, entries, image_path
from fulcrum.service.store import RunStore
from fulcrum.compat import configured_app_data, default_data_directory


class DesktopTests(unittest.TestCase):
    def test_downloaded_assemblies_explain_unlock_without_changing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dll = root / "pythonnet/runtime/Python.Runtime.dll"
            dll.parent.mkdir(parents=True)
            dll.write_bytes(b"assembly")
            marker = Path(str(dll) + ":Zone.Identifier")
            text = "[ZoneTransfer]\nZoneId=3\nReferrerUrl=https://github.com/test/release.zip\x00"
            marker.write_text(text, encoding="utf-8")
            with patch("fulcrum.desktop.sys.platform", "win32"), patch("fulcrum.desktop.sys.frozen", True, create=True):
                with self.assertRaisesRegex(RuntimeError, "解除锁定"):
                    check_windows_bundle_trust(root)
            self.assertEqual(marker.read_text(encoding="utf-8"), text)
            self.assertEqual(dll.read_bytes(), b"assembly")

    def test_download_check_only_applies_to_frozen_windows_managed_assemblies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dll = root / "pythonnet/runtime/Python.Runtime.dll"
            dll.parent.mkdir(parents=True)
            dll.touch()
            marker = Path(str(dll) + ":Zone.Identifier")
            with patch("fulcrum.desktop.sys.platform", "win32"), patch("fulcrum.desktop.sys.frozen", True, create=True):
                check_windows_bundle_trust(root)
                for text in ("[ZoneTransfer]\nZoneId=2", "[ZoneTransfer]\nZoneId=invalid", "invalid marker"):
                    marker.write_text(text, encoding="utf-8")
                    check_windows_bundle_trust(root)
                marker.write_text("[ZoneTransfer]\nZoneId=4", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "Python.Runtime.dll"):
                    check_windows_bundle_trust(root)
            with patch("fulcrum.desktop.sys.platform", "darwin"), patch("fulcrum.desktop.sys.frozen", True, create=True):
                check_windows_bundle_trust(root)
            with patch("fulcrum.desktop.sys.platform", "win32"), patch("fulcrum.desktop.sys.frozen", False, create=True):
                check_windows_bundle_trust(root)

    def test_startup_messages_do_not_blame_webview_for_unrelated_errors(self):
        directory = Path("test-data")
        message = startup_message(RuntimeError("Failed to resolve Python.Runtime.Loader.Initialize from x"), directory)
        self.assertIn(".NET", message)
        self.assertIn("日志位置", message)
        self.assertNotIn("WebView2", message)
        self.assertNotIn("WebView2", startup_message(RuntimeError("unrelated failure"), directory))
        self.assertIn("Microsoft WebView2 Runtime", startup_message(RuntimeError("WebView2 is missing"), directory))

    def test_release_builder_requires_native_window_success_and_no_stale_report(self):
        from scripts import build_desktop
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "build/desktop-window-test.json"
            report.parent.mkdir(parents=True)
            report.write_text('{"ok": true}', encoding="utf-8")
            def success(args, **kwargs):
                self.assertFalse(report.exists())
                report.write_text(json.dumps({"ok": True, "engine": "edgechromium", "frontendMounted": True}), encoding="utf-8")
            with patch.object(build_desktop, "ROOT", root), patch.object(build_desktop, "run", side_effect=success) as execute:
                build_desktop.verify_window(root / "dist/Fulcrum", "Fulcrum", {})
                self.assertIn("--window-test", execute.call_args.args[0])
                self.assertEqual(execute.call_args.kwargs["timeout"], 120)
            for result in ({"ok": False}, {"ok": True, "engine": "cocoa", "frontendMounted": True},
                           {"ok": True, "engine": "edgechromium", "frontendMounted": False}):
                def failed(args, **kwargs):
                    report.write_text(json.dumps(result), encoding="utf-8")
                with patch.object(build_desktop, "ROOT", root), patch.object(build_desktop, "run", side_effect=failed):
                    with self.assertRaises(RuntimeError):
                        build_desktop.verify_window(root / "dist/Fulcrum", "Fulcrum", {})
            with patch.object(build_desktop, "ROOT", root), patch.object(build_desktop, "run"):
                with self.assertRaises(FileNotFoundError):
                    build_desktop.verify_window(root / "dist/Fulcrum", "Fulcrum", {})

    def test_public_identity_keeps_theme_separate(self):
        self.assertEqual(PROJECT["name"], "天堂支点——明日方舟集成战略助手")
        self.assertEqual(PROJECT["executableName"], "CelestialFulcrum")
        self.assertEqual(PROJECT["englishName"], "Celestial Fulcrum — Arknights Rogue Assistant")
        self.assertEqual(PROJECT["shortName"], "CFARA")
        self.assertEqual(PROJECT["englishShortName"], "CFARA")
        self.assertEqual(PROJECT["dataDirectoryName"], "CFARA")
        self.assertEqual(editor_catalog()["project"], PROJECT)
        self.assertEqual(PROJECT["supportedThemes"], ["沉沦者的黑流树海"])

    @unittest.skipUnless(os.name == "nt" and importlib.util.find_spec("PyInstaller"), "Windows builder dependencies")
    def test_packaging_manifest_contains_every_catalog_image(self):
        root = Path(__file__).resolve().parents[1]
        def analysis(*args, **kwargs):
            return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=kwargs["datas"])
        with patch.dict(os.environ, {"FULCRUM_BUILD_INPUT": str(root / "build/desktop-input")}), \
                patch("PyInstaller.utils.hooks.collect_submodules", return_value=[]):
            spec = runpy.run_path(str(root / "packaging/fulcrum.spec"), init_globals={
                "SPECPATH": str(root / "packaging"), "Analysis": analysis,
                "PYZ": lambda *args: None, "EXE": lambda *args, **kwargs: kwargs,
                "COLLECT": lambda *args, **kwargs: None,
            })
        bundled = {Path(source).resolve() for source, _ in spec["datas"]}
        self.assertIn(root / "chi_sim.traineddata", bundled)
        self.assertIn(root / "scripts/ocr_node_labels.mjs", bundled)
        self.assertIn(root / "packaging/tessdata_fast.LICENSE", bundled)
        for path in (root / "data/scoring").rglob("*.json"):
            self.assertIn((str(path), str(path.relative_to(root).parent)), spec["datas"])
        for entry in entries().values():
            if entry.get("imagePath"):
                self.assertIn(image_path(entry["id"]), bundled, entry["id"])
        for kind in ("unknown_mystery", "unknown_ferocity"):
            self.assertIn(root / "assets/vision" / f"{kind}_01.png", bundled)
        self.assertEqual(spec["exe"]["name"], PROJECT["executableName"])
        self.assertEqual(spec["exe"]["icon"], str(root / "assets/ui/sitting-dog-v1.ico"))
        self.assertIn(PROJECT["name"], str(spec["version_resource"]))

    def test_explicit_and_default_data_directories(self):
        with patch("fulcrum.desktop.sys.platform", "win32"), \
                patch.dict(os.environ, {"LOCALAPPDATA": "C:/app-data", "CFARA_APP_DATA": "", "FULCRUM_APP_DATA": "", "BLACKFLOW_APP_DATA": ""}):
            self.assertEqual(data_directory(), Path("C:/app-data/CFARA"))
        with patch.dict(os.environ, {"CFARA_APP_DATA": "C:/custom-data"}):
            self.assertEqual(data_directory(), Path("C:/custom-data").resolve())
            self.assertEqual(data_directory("C:/override"), Path("C:/override").resolve())

    def test_mac_uses_application_support_and_native_webkit(self):
        with patch("fulcrum.desktop.sys.platform", "darwin"), \
                patch.dict(os.environ, {"CFARA_APP_DATA": "", "FULCRUM_APP_DATA": "", "BLACKFLOW_APP_DATA": ""}), \
                patch("fulcrum.desktop.Path.home", return_value=Path("C:/mac-home")):
            self.assertEqual(data_directory(), Path("C:/mac-home/Library/Application Support/CFARA"))
            self.assertEqual(desktop_engine(), "cocoa")
        with patch("fulcrum.desktop.sys.platform", "win32"):
            self.assertEqual(desktop_engine(), "edgechromium")

    def test_legacy_configuration_is_read_only_and_new_configuration_wins(self):
        self.assertEqual(configured_app_data({"BLACKFLOW_APP_DATA": "old"}), "old")
        self.assertEqual(configured_app_data({"FULCRUM_APP_DATA": "new", "BLACKFLOW_APP_DATA": "old"}), "new")
        self.assertEqual(configured_app_data({"CFARA_APP_DATA": "cfara", "FULCRUM_APP_DATA": "new", "BLACKFLOW_APP_DATA": "old"}), "cfara")
        self.assertEqual(configured_app_data({"CFARA_APP_DATA": "", "FULCRUM_APP_DATA": "new"}), "new")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.assertEqual(default_data_directory(base), base / "CFARA")
            legacy = base / "BlackFlow"
            legacy.mkdir()
            save = legacy / "player-save.json"
            save.write_text("player data", encoding="utf-8")
            self.assertEqual(default_data_directory(base), base / "CFARA")
            self.assertFalse((base / "CFARA").exists())
            (base / "Fulcrum").mkdir()
            self.assertEqual(default_data_directory(base), base / "CFARA")
            self.assertEqual(save.read_text(encoding="utf-8"), "player data")

    @unittest.skipUnless(os.name == "nt", "Windows file locking")
    def test_prevent_two_windows_writing_one_store(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with single_instance(directory):
                with self.assertRaises(RuntimeError):
                    with single_instance(directory):
                        pass
            with single_instance(directory):
                pass

    def test_bundled_node_preferred_without_system_node(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = root / "runtime/node/bin/node.exe"
            node.parent.mkdir(parents=True)
            node.touch()
            with patch("fulcrum.runtime.ROOT", root), patch("fulcrum.runtime.sys.platform", "win32"), \
                    patch("fulcrum.runtime.shutil.which", return_value=None):
                executable, modules = node_runtime()
                self.assertEqual(Path(executable), node)
                self.assertEqual(Path(modules), root / "runtime/node/node_modules")

    def test_mac_bundled_node_preferred_without_system_node(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = root / "runtime/node/bin/node"
            node.parent.mkdir(parents=True)
            node.touch()
            with patch("fulcrum.runtime.ROOT", root), patch("fulcrum.runtime.sys.platform", "darwin"), \
                    patch("fulcrum.runtime.shutil.which", return_value=None):
                executable, modules = node_runtime()
                self.assertEqual(Path(executable), node)
                self.assertEqual(Path(modules), root / "runtime/node/node_modules")

    def test_markdown_without_project_manual(self):
        text = render_standalone(new_playtime("desktop-export"))
        for heading in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## 7."):
            self.assertIn(heading, text)
        with tempfile.TemporaryDirectory() as temporary:
            store = RunStore(Path(temporary) / "runs")
            store.create("desktop-export")
            with patch("fulcrum.service.store.ROOT", Path(temporary)):
                self.assertEqual(store.markdown("desktop-export"), render_standalone(store.load("desktop-export")["state"]))

    def test_loopback_service_starts_and_exits(self):
        with tempfile.TemporaryDirectory() as temporary:
            server = LocalServer(Path(temporary), port=0).start()
            try:
                with urlopen(server.url + "/api/health", timeout=5) as response:
                    self.assertEqual(response.status, 200)
                self.assertEqual(server.socket.getsockname()[0], "127.0.0.1")
            finally:
                server.close()
            self.assertFalse(server.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
