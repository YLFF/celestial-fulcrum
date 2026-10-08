"""Opaque local image assets; clients never choose a server filesystem path."""

import json
from pathlib import Path
import re
from uuid import uuid4

import cv2
import numpy as np

from .store import atomic_json

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 16_000_000


class AssetStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, asset_id, suffix=".png"):
        if not isinstance(asset_id, str) or not re.fullmatch(r"[a-f0-9]{32}", asset_id):
            raise ValueError("invalid image asset ID")
        path = (self.root / (asset_id + suffix)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("image asset escapes storage")
        return path

    def save(self, payload, *, source=None):
        if not payload or len(payload) > MAX_UPLOAD_BYTES:
            raise ValueError("image must be nonempty and <= 25 MB")
        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("file is not a supported image")
        height, width = image.shape[:2]
        if width * height > MAX_PIXELS:
            raise ValueError("image exceeds 16 million pixels")
        success, encoded = cv2.imencode(".png", image)
        if not success:
            raise ValueError("image encoding failed")
        asset_id = uuid4().hex
        self.path(asset_id).write_bytes(encoded.tobytes())
        info = {"assetId": asset_id, "width": width, "height": height,
                "imageUrl": f"/api/images/{asset_id}", "source": source or {"kind": "upload"}}
        atomic_json(self.path(asset_id, ".json"), info)
        return info

    def load(self, asset_id):
        path = self.path(asset_id)
        if not path.is_file():
            raise FileNotFoundError("image asset not found")
        return json.loads(self.path(asset_id, ".json").read_text(encoding="utf-8"))
