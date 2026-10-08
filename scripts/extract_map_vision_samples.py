"""Extract reviewed, masked CV templates from an archived screenshot."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from fulcrum.vision_geometry import working_image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--out", type=Path, default=Path("assets/vision"))
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    image, scale = working_image(cv2.imread(result["screenshot"]))
    nodes = {row["id"]: tuple(round(value * scale) for value in row["pixel"]) for row in result["nodes"]}
    args.out.mkdir(parents=True, exist_ok=True)
    # This capture contains a left-side player overlay and two dark exit animations.
    for node_id, filename, radius, mask_radius in (
        ("0,2", "node_type_013_01.png", 32, 25),
        ("2,3", "node_type_015_02.png", 36, 34),
        ("4,1", "node_type_015_03.png", 36, 34),
    ):
        x, y = nodes[node_id]
        patch = image[y - radius:y + radius, x - radius:x + radius]
        alpha = np.zeros(patch.shape[:2], np.uint8)
        cv2.circle(alpha, (radius, radius), mask_radius, 255, -1)
        if node_id == "0,2":
            alpha[:, :radius - 4] = 0
        cv2.imwrite(str(args.out / filename), np.dstack((patch, alpha)))
    x, y = nodes["0,2"]
    sprite = image[y - 24:y + 20, x - 37:x - 15]
    binary = cv2.inRange(cv2.cvtColor(sprite, cv2.COLOR_BGR2HSV), (0, 0, 205), (179, 80, 255))
    cv2.imwrite(str(args.out / "player_avatar_01.png"), binary)


if __name__ == "__main__":
    main()
