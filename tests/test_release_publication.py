from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ReleasePublicationTests(unittest.TestCase):
    def test_application_and_runtime_versions_are_consistent(self):
        versions = [json.loads((ROOT / name).read_text(encoding="utf-8"))["version"]
                    for name in ("data/project_info.json", "package.json", "frontend/package.json")]
        self.assertEqual(len(set(versions)), 1)

    def test_data_allowlist_excludes_nested_local_caches(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import export_release_source as release
            import export_macos_source as macos
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ("data/catalog.json", "data/scoring/blackflow/default.json", "data/relic_effects/numeric_rules.json", "data/arkrog_auth/local.json"):
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("{}", encoding="utf-8")
                with patch.object(release, "FILES", ()), patch.object(release, "EXTRA_FILES", ()), patch.object(release, "TREES", {}):
                    names = {path.relative_to(root).as_posix() for path in release.publication_files(root)}
                self.assertEqual(names, {"data/catalog.json", "data/scoring/blackflow/default.json", "data/relic_effects/numeric_rules.json"})
                with patch.object(macos, "FILES", ()), patch.object(macos, "FOLDERS", ()):
                    mac_names = {path.relative_to(root).as_posix() for path in macos.source_files(root)}
                self.assertEqual(mac_names, names)
        finally:
            sys.path.remove(str(ROOT / "scripts"))

    def test_allowlist_excludes_unfinished_documents_and_player_data(self):
        scripts = ROOT / "scripts"
        import sys
        sys.path.insert(0, str(scripts))
        try:
            from export_release_source import publication_files
            names = {path.relative_to(ROOT).as_posix() for path in publication_files()}
        finally:
            sys.path.remove(str(scripts))
        self.assertNotIn("README.md", names)
        self.assertNotIn("BLACKFLOW_REFERENCE.md", names)
        self.assertNotIn("ROADMAP.md", names)
        self.assertNotIn("tests/test_decision_advisor.py", names)
        self.assertNotIn("tests/test_rolling_route_probe.py", names)
        self.assertIn("docs/ROADMAP.md", names)
        self.assertEqual({name for name in names if name.startswith("docs/")}, {"docs/ROADMAP.md"})
        self.assertFalse(any(name.startswith(("runs/", "samples/", "work/", ".git/")) for name in names))
        self.assertIn(".github/workflows/desktop-release.yml", names)
        self.assertIn("fulcrum/lookout_rules.py", names)
        self.assertIn("data/scoring/blackflow/default.json", names)
        self.assertIn("data/scoring/blackflow/relics.json", names)
        self.assertIn("tests/fixtures/arkrog_30.json", names)
        self.assertIn("tests/fixtures/n15_floor2_combat.json", names)
        for path in (ROOT / "data/relic_effects").rglob("*.json"):
            self.assertIn(path.relative_to(ROOT).as_posix(), names)
        self.assertIn("packaging/fulcrum.spec", names)
        self.assertIn("packaging/fulcrum-macos.spec", names)
        self.assertIn("tests/test_release_publication.py", names)
        self.assertIn("LICENSE", names)
        self.assertIn("NOTICE", names)
        self.assertFalse(any(name.endswith(".prompt.txt") for name in names))

    def test_refresh_removes_only_unchanged_managed_files(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from export_release_source import remove_obsolete_files
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                old = root / "obsolete.json"
                old.write_text("old", encoding="utf-8")
                unmanaged = root / "README.md"
                unmanaged.write_text("keep", encoding="utf-8")
                (root / "publication-manifest.json").write_text(json.dumps({"fileSHA256": {
                    "obsolete.json": hashlib.sha256(b"old").hexdigest()}}), encoding="utf-8")
                old.write_text("changed", encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    remove_obsolete_files(root, [])
                self.assertTrue(old.exists())
                old.write_text("old", encoding="utf-8")
                remove_obsolete_files(root, [])
                self.assertFalse(old.exists())
                self.assertEqual(unmanaged.read_text(encoding="utf-8"), "keep")
                (root / "publication-manifest.json").write_text(json.dumps({"fileSHA256": {"../outside.json": "x"}}), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    remove_obsolete_files(root, [])
        finally:
            sys.path.remove(str(ROOT / "scripts"))


class ProjectLicensingTests(unittest.TestCase):
    def test_license_and_notices_are_complete(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Version 3, 29 June 2007", license_text)
        self.assertIn("END OF TERMS AND CONDITIONS", license_text)
        self.assertIn("How to Apply These Terms to Your New Programs", license_text)
        self.assertGreater(len(license_text), 35000)
        notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("GPL-3.0-only", notice)
        self.assertIn("does not relicense third-party", notice)
        self.assertIn("corresponding source", notice)

    def test_package_metadata_uses_the_same_license(self):
        for filename in ("package.json", "frontend/package.json", "data/project_info.json"):
            with self.subTest(filename=filename):
                metadata = json.loads((ROOT / filename).read_text(encoding="utf-8"))
                self.assertEqual(metadata["license"], "GPL-3.0-only")

    def test_mac_source_export_includes_project_license(self):
        from scripts.export_macos_source import source_files
        names = {path.relative_to(ROOT).as_posix() for path in source_files()}
        self.assertTrue({"LICENSE", "NOTICE"}.issubset(names))

    def test_shared_desktop_license_collector_copies_project_files(self):
        from io import BytesIO
        from scripts import build_desktop
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(build_desktop.metadata, "distributions", return_value=[]), \
                patch.object(build_desktop, "urlopen", return_value=BytesIO(b"Node license")):
            destination = Path(directory)
            build_desktop.collect_licenses(destination, "v24.0.0")
            for filename in ("LICENSE", "NOTICE"):
                self.assertEqual((destination / filename).read_bytes(), (ROOT / filename).read_bytes())
            self.assertEqual((destination / "licenses/Node-LICENSE.txt").read_bytes(), b"Node license")

    def test_mac_build_uses_shared_license_collector(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import build_macos
            import build_desktop
            self.assertIs(build_macos.collect_licenses, build_desktop.collect_licenses)
        finally:
            sys.path.remove(str(ROOT / "scripts"))


if __name__ == "__main__":
    unittest.main()
