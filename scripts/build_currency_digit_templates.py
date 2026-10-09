"""Build the currency-font atlas from confirmed screenshot HUD values."""

from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fulcrum.vision_currency import ATLAS, currency_glyphs
from fulcrum.vision_geometry import working_image, detect_map_viewport
from fulcrum.vision_resources import _box

SOURCES = {
    "0": ("attachment_04.jpg", "originium_ingot", "80", 1),
    "1": ("attachment_01.jpg", "originium_ingot", "11", 0),
    "2": ("attachment_07.jpg", "originium_ingot", "22", 0),
    "3": ("desktop_floor_2_progress.png", "originium_ingot", "23", 1),
    "4": ("attachment_08.jpg", "originium_ingot", "425", 0),
    "5": ("attachment_08.jpg", "originium_ingot", "425", 2),
    "6": ("bluestacks_floor_3.png", "originium_ingot", "16", 1),
    "7": ("attachment_02.jpg", "originium_ingot", "7", 0),
    "8": ("attachment_04.jpg", "originium_ingot", "80", 0),
    "9": ("attachment_01.jpg", "hope", "29", 1),
}


def main():
    masks = {}
    for digit, (filename, field, expected, index) in SOURCES.items():
        image = cv2.imread(str(ROOT / "samples/maps" / filename))
        work, scale = working_image(image)
        viewport = tuple(round(value / scale) for value in detect_map_viewport(work))
        ui_scale = .9 if filename.startswith('desktop_') else 1
        x0, y0, x1, y1 = _box(image, viewport, field, ui_scale)
        glyphs = currency_glyphs(image[y0:y1, x0:x1], image.shape[0] / 1152 * ui_scale)
        if len(glyphs) != len(expected):
            raise ValueError(f"{filename}: expected {expected}, found {len(glyphs)} digits")
        masks[digit] = glyphs[index]
    np.savez_compressed(ATLAS, **masks)
    print(f"Currency atlas: {ATLAS}; digits {''.join(sorted(masks))}")


if __name__ == '__main__':
    main()
