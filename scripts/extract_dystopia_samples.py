"""Archive reviewed distorted node textures, keeping labels/badges outside masks."""

from pathlib import Path

import cv2
import numpy as np

from fulcrum.vision_geometry import working_image


def crop(image, center, side, path, inner=0, outer=.48, grid_step=100):
    x, y = map(round, center)
    half = side // 2
    patch = image[y-half:y-half+side, x-half:x-half+side]
    assert patch.shape[:2] == (side, side)
    yy, xx = np.indices((side, side))
    radius = np.hypot(xx-half, yy-half)
    alpha = ((radius <= side*outer) & (radius >= side*inner)).astype(np.uint8)*255
    patch = np.dstack((patch, alpha))
    patch = cv2.resize(patch, None, fx=100/grid_step, fy=100/grid_step, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), patch)


def main():
    out = Path("assets/vision/dystopia")
    out.mkdir(parents=True, exist_ok=True)
    (out / "clean").mkdir(exist_ok=True)
    one, _ = working_image(cv2.imread("samples/maps/desktop_floor1_dystopia.png"))
    three, _ = working_image(cv2.imread("samples/maps/desktop_floor3_dystopia.png"))
    # Coordinates are reviewed in the 1280-wide working image, not original pixels.
    for kind, center, side in [
        ("node_type_001", (637, 184), 60), ("unknown_mystery", (470, 184), 62),
        ("unknown_ferocity", (807, 359), 60), ("node_type_020", (467, 360), 34),
    ]:
        crop(one, center, side, out / f"{kind}_01.png", grid_step=174)
    for kind, center, side in [
        ("node_type_017", (337, 345), 46), ("node_type_018", (435, 345), 46),
        ("node_type_003", (535, 345), 72), ("node_type_004", (535, 444), 46),
        ("node_type_002", (636, 344), 48), ("node_type_006", (636, 544), 45),
        ("node_type_009", (436, 544), 48), ("node_type_020", (536, 547), 22),
        ("unknown_mystery", (637, 146), 50),
    ]:
        crop(three, center, side, out / f"{kind}_02.png")
    crop(three, (837, 245), 50, out / "node_type_002_03.png")
    crop(three, (532, 147), 24, out / "node_type_020_03.png")
    crop(three, (736, 147), 24, out / "node_type_020_04.png")
    crop(three, (635, 446), 24, out / "node_type_020_05.png")
    crop(three, (337, 444), 46, out / "clean/node_type_005_01.png")
    crop(three, (941, 544), 45, out / "clean/node_type_006_02.png")
    crop(one, (300, 359), 152, out / "ideal_source_01.png", inner=.25, outer=.48, grid_step=174)
    crop(three, (636, 344), 108, out / "ideal_source_02.png", inner=.24, outer=.48)


if __name__ == "__main__":
    main()
