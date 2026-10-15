from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from fulcrum.image_io import read_image


class ImagePathTests(unittest.TestCase):
    def test_unicode_paths_preserve_decoding_and_alpha(self):
        pixels = np.arange(12 * 16 * 4, dtype=np.uint8).reshape((12, 16, 4))
        ok, encoded = cv2.imencode('.png', pixels)
        self.assertTrue(ok)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ascii_path = root / 'image.png'
            unicode_path = root / '\u5929\u5802\u652f\u70b9' / '\u8282\u70b9.png'
            unicode_path.parent.mkdir()
            for path in (ascii_path, unicode_path):
                path.write_bytes(encoded.tobytes())
            for mode in (cv2.IMREAD_COLOR, cv2.IMREAD_GRAYSCALE, cv2.IMREAD_UNCHANGED):
                expected = cv2.imread(str(ascii_path), mode)
                np.testing.assert_array_equal(read_image(unicode_path, mode), expected)

    def test_unreadable_and_invalid_files_return_none(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.png'
            self.assertIsNone(read_image(path))
            path.write_bytes(b'')
            self.assertIsNone(read_image(path))
            path.write_bytes(b'not an image')
            self.assertIsNone(read_image(path))
