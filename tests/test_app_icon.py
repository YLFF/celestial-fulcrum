from pathlib import Path
import json
import struct
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class AppIconTests(unittest.TestCase):
    def test_windows_icon_has_small_and_high_resolution_frames(self):
        data = (ROOT / "assets/ui/sitting-dog-v1.ico").read_bytes()
        reserved, kind, count = struct.unpack_from("<HHH", data)
        self.assertEqual((reserved, kind), (0, 1))
        sizes = set()
        for index in range(count):
            width, height, _, _, _, _, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + index * 16)
            size = width or 256
            self.assertEqual(size, height or 256)
            sizes.add(size)
            frame = data[offset:offset + length]
            self.assertEqual(len(frame), length)
            self.assertEqual(frame[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack_from(">II", frame, 16), (size, size))
            self.assertEqual(frame[25], 6)
        self.assertEqual(sizes, {16, 24, 32, 48, 64, 128, 256})

    def test_mac_icon_has_retina_frame_and_valid_container(self):
        data = (ROOT / "assets/ui/sitting-dog-v1.icns").read_bytes()
        self.assertEqual(data[:4], b"icns")
        self.assertEqual(struct.unpack_from(">I", data, 4)[0], len(data))
        chunks = {}
        offset = 8
        while offset < len(data):
            kind, length = struct.unpack_from(">4sI", data, offset)
            self.assertGreaterEqual(length, 8)
            self.assertLessEqual(offset + length, len(data))
            chunks[kind] = data[offset + 8:offset + length]
            offset += length
        self.assertEqual(offset, len(data))
        self.assertEqual(struct.unpack_from(">II", chunks[b"ic10"], 16), (1024, 1024))
        self.assertEqual(chunks[b"ic10"][25], 6)

    def test_source_export_contains_both_native_icons(self):
        from scripts.export_macos_source import source_files
        with patch.object(sys, "path", [str(ROOT / "scripts"), *sys.path]):
            from scripts.export_release_source import publication_files
        for paths in (source_files(), publication_files()):
            names = {path.relative_to(ROOT).as_posix() for path in paths}
            self.assertTrue({"assets/ui/sitting-dog-v1.png", "assets/ui/sitting-dog-v1.ico", "assets/ui/sitting-dog-v1.icns"} <= names)

    def test_stable_tag_is_default_and_not_unconditionally_prerelease(self):
        workflow = (ROOT / ".github/workflows/desktop-release.yml").read_text(encoding="utf-8")
        version = json.loads((ROOT / "data/project_info.json").read_text(encoding="utf-8"))["version"]
        self.assertIn(f"default: v{version}\n", workflow)
        self.assertIn('if [[ "$RELEASE_TAG" == *-* ]]', workflow)
        self.assertIn("release_flags+=(--prerelease)", workflow)
        self.assertIn("release_flags+=(--latest)", workflow)
        self.assertNotIn('--target "$SOURCE_REVISION" --prerelease', workflow)


if __name__ == "__main__":
    unittest.main()
