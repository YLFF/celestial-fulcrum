"""Archive the supplied HUD row and its text anchor, not item identities."""

from pathlib import Path
import argparse
import shutil

import cv2

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=ROOT / "samples/relics/visible_row.jpg")
    source = parser.parse_args().source.resolve()
    archive = ROOT / "samples/relics/visible_row.jpg"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if source != archive.resolve():
        shutil.copyfile(source, archive)
    image = cv2.imread(str(archive))
    if image is None or image.shape[:2] != (582, 1280):
        raise ValueError("this extraction recipe expects the archived 1280x582 sample")
    assets = ROOT / "assets/vision/relics"
    assets.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(assets / "inventory_label.png"), image[554:572, 172:225])
    cv2.imwrite(str(assets / "appraisal_label.png"), image[529:544, 616:663])
    cv2.imwrite(str(ROOT / "work/relic_row.png"), cv2.resize(image[516:577, 160:580], None, fx=3, fy=3))


if __name__ == "__main__":
    main()
