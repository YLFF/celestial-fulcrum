"""Normalize a reviewed shop crop while masking its left-side player overlay."""

import argparse
from pathlib import Path

import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("screenshot", type=Path)
    parser.add_argument("--center", nargs=2, type=int, required=True)
    parser.add_argument("--side", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    image = cv2.imread(str(args.screenshot))
    x, y = args.center
    radius = args.side // 2
    if image is None or min(x - radius, y - radius) < 0 or y + radius > image.shape[0] or x + radius > image.shape[1]:
        raise ValueError("shop crop must lie inside the source image")
    patch = cv2.resize(image[y - radius:y + radius, x - radius:x + radius], (72, 72), interpolation=cv2.INTER_AREA)
    alpha = np.zeros((72, 72), np.uint8)
    cv2.circle(alpha, (36, 36), 31, 255, -1)
    alpha[:, :29] = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.out), np.dstack((patch, alpha)))


if __name__ == "__main__":
    main()
