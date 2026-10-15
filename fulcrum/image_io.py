"""Decode image files without OpenCV's Windows filename encoding limitation."""

from pathlib import Path

import cv2
import numpy as np


def read_image(path, flags=cv2.IMREAD_COLOR):
    try:
        payload = Path(path).read_bytes()
    except OSError:
        return None
    if not payload:
        return None
    return cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), flags)
