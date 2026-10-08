"""Build the tiny action-point glyph atlas from archived, labelled HUD crops."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.vision_action import ATLAS, action_glyphs
from fulcrum.vision_geometry import detect_map_viewport, working_image
from fulcrum.vision_resources import _box


SOURCES = {"1": "attachment_01.jpg", "2": "attachment_08.jpg", "3": "attachment_02.jpg",
           "4": "desktop_action_4.png", "5": "desktop_action_5.png",
           "6": "attachment_06.jpg", "7": "bluestacks_floor_3.png", "8": "attachment_05.jpg"}


def main() -> None:
    masks = {}
    for digit, filename in SOURCES.items():
        image = cv2.imread(str(ROOT / "samples" / "maps" / filename))
        if image is None:
            raise ValueError(f"missing source screenshot {filename}")
        work, scale = working_image(image)
        viewport = tuple(round(value / scale) for value in detect_map_viewport(work))
        ui_scale = 0.9 if filename.startswith("desktop_") else 1.0
        x0, y0, x1, y1 = _box(image, viewport, "action_points", ui_scale)
        glyphs = action_glyphs(image[y0:y1, x0:x1], image.shape[0] / 1152 * ui_scale)
        if len(glyphs) != 1:
            raise ValueError(f"could not isolate action digit in {filename}")
        masks[digit] = glyphs[0]
    ATLAS.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(ATLAS, **masks)
    print(json.dumps({"atlas": str(ATLAS), "digits": sorted(masks)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
