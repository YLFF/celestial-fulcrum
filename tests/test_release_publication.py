from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ReleasePublicationTests(unittest.TestCase):
    def test_data_allowlist_excludes_nested_local_caches(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import export_release_source as release
            import export_macos_source as macos
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ("data/catalog.json", "data/scoring/blackstream/default.json", "data/arkrog_auth/local.json"):
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("{}", encoding="utf-8")
                with patch.object(release, "FILES", ()), patch.object(release, "EXTRA_FILES", ()), patch.object(release, "TREES", {}):
                    names = {path.relative_to(root).as_posix() for path in release.publication_files(root)}
                self.assertEqual(names, {"data/catalog.json", "data/scoring/blackstream/default.json"})
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
        self.assertNotIn("BLACKSTREAM_REFERENCE.md", names)
        self.assertIn("ROADMAP.md", names)
        self.assertFalse(any(name.startswith(("runs/", "samples/", "work/", ".git/", "docs/")) for name in names))
        self.assertIn(".github/workflows/desktop-release.yml", names)
        self.assertIn("fulcrum/lookout_rules.py", names)
        self.assertIn("data/scoring/blackstream/default.json", names)
        self.assertIn("data/scoring/blackstream/relics.json", names)
        self.assertIn("packaging/fulcrum.spec", names)
        self.assertIn("packaging/fulcrum-macos.spec", names)
        self.assertIn("tests/test_release_publication.py", names)
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


if __name__ == "__main__":
    unittest.main()
