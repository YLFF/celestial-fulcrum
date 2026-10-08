"""Extract a reviewed circular badge from a normalized map screenshot."""

import argparse
from pathlib import Path

import cv2
import numpy as np

from fulcrum.vision_geometry import working_image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--center", nargs=2, type=int, required=True)
    parser.add_argument("--side", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    image = cv2.imread(str(args.source))
    if image is None:
        raise ValueError("source image is unreadable")
    image, _ = working_image(image)
    x, y = args.center
    left, top = x - args.side // 2, y - args.side // 2
    if args.side < 8 or left < 0 or top < 0 or left + args.side > image.shape[1] or top + args.side > image.shape[0]:
        raise ValueError("badge crop must stay inside the normalized source")
    patch = cv2.resize(image[top:top + args.side, left:left + args.side], (57, 57), interpolation=cv2.INTER_LINEAR)
    alpha = np.zeros((57, 57), np.uint8)
    cv2.circle(alpha, (28, 28), 26, 255, -1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.out), np.dstack((patch, alpha))):
        raise ValueError("failed to write badge template")


if __name__ == "__main__":
    main()
