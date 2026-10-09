"""Build the slashed-zero reference from a labelled currency HUD crop."""

from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.vision_resources import HOPE_ZERO_TEMPLATE, _hope_digits, _hope_zero_glyph


def main() -> None:
    source = ROOT / "samples" / "hud" / "hope_zero_currency.png"
    image = cv2.imread(str(source))
    if image is None:
        raise ValueError(f"missing source screenshot: {source}")
    digits = _hope_digits(image, 1.6875)
    glyph = _hope_zero_glyph(digits) if digits is not None else None
    if glyph is None:
        raise ValueError("could not isolate the labelled hope zero")
    HOPE_ZERO_TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(HOPE_ZERO_TEMPLATE, **{"0": glyph})
    print(HOPE_ZERO_TEMPLATE)


if __name__ == "__main__":
    main()
