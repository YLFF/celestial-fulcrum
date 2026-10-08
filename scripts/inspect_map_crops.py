"""Save fitted map cells for local recognition diagnostics."""

import argparse
import json
from pathlib import Path

import cv2

from fulcrum.vision_geometry import working_image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    image, scale = working_image(cv2.imread(result["screenshot"]))
    args.out.mkdir(parents=True, exist_ok=True)
    for node in result["nodes"]:
        x, y = (round(value * scale) for value in node["pixel"])
        patch = image[max(0, y - 65):y + 66, max(0, x - 65):x + 66]
        cv2.imwrite(str(args.out / f"{node['id'].replace(',', '_')}.png"), patch)


if __name__ == "__main__":
    main()
