from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleasePublicationTests(unittest.TestCase):
    def test_allowlist_excludes_documents_and_player_data(self):
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
        self.assertFalse(any(name.startswith(("runs/", "samples/", "work/", ".git/", "docs/")) for name in names))
        self.assertIn(".github/workflows/desktop-release.yml", names)
        self.assertIn("fulcrum/lookout_rules.py", names)
        self.assertIn("packaging/fulcrum.spec", names)
        self.assertIn("packaging/fulcrum-macos.spec", names)
        self.assertIn("tests/test_release_publication.py", names)
        self.assertFalse(any(name.endswith(".prompt.txt") for name in names))


if __name__ == "__main__":
    unittest.main()
