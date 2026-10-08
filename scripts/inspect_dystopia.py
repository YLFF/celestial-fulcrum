"""Produce normalized CV evidence sheets for reviewed dystopia screenshots."""

import json
from pathlib import Path

import cv2
import numpy as np

from fulcrum.map_catalog import TemplateCatalog
from fulcrum.vision_geometry import detect_circles, detect_map_viewport, match_templates, working_image
from fulcrum.vision_icons import IconMatcher


def main():
    out = Path("work/dystopia-debug")
    out.mkdir(parents=True, exist_ok=True)
    icons = IconMatcher()
    for floor in (1, 3):
        image, scale = working_image(cv2.imread(f"samples/maps/desktop_floor{floor}_dystopia.png"))
        viewport = detect_map_viewport(image)
        circles = detect_circles(image, viewport)
        match = match_templates(circles, TemplateCatalog().candidates("main", floor),
                                (image.shape[1], image.shape[0]), image=image)[0]
        cells, nodes = [], []
        for slot in match.template.occupied_slots:
            pixel = match.pixel_at(slot)
            chosen, candidates = icons.classify_node(image, pixel, match.grid_step, circles)
            key = match.template.coord(slot).key
            nodes.append({"id": key, "pixel": pixel, "chosen": chosen.id if chosen else None,
                          "candidates": [vars(item) for item in candidates]})
            x, y = map(round, pixel)
            patch = image[max(0, y-65):y+66, max(0, x-65):x+66]
            patch = cv2.resize(patch, (150, 150))
            cell = np.zeros((180, 180, 3), np.uint8)
            cell[:150, 15:165] = patch
            cv2.putText(cell, key + ":" + (chosen.id if chosen else "?"), (2, 167),
                        cv2.FONT_HERSHEY_SIMPLEX, .35, (255, 255, 255), 1)
            cells.append(cell)
        while len(cells) % 5:
            cells.append(np.zeros_like(cells[0]))
        cv2.imwrite(str(out / f"floor{floor}-nodes.png"), np.vstack([
            np.hstack(cells[i:i+5]) for i in range(0, len(cells), 5)]))
        cv2.imwrite(str(out / f"floor{floor}-header.png"), image[:85, 500:760])
        cv2.imwrite(str(out / f"floor{floor}-work.png"), image)
        (out / f"floor{floor}.json").write_text(json.dumps(nodes, indent=2), encoding="utf-8")
    images = []
    for i in range(1, 15):
        asset = cv2.imread(f"assets/lubiao/dystopia/dystopia_{i:03}.png", cv2.IMREAD_UNCHANGED)
        cell = np.zeros((150, 150, 3), np.uint8)
        if asset is not None:
            resized = cv2.resize(asset, (110, 110))
            cell[:110, 20:130] = resized[:, :, :3]
        cv2.putText(cell, str(i), (5, 135), cv2.FONT_HERSHEY_SIMPLEX, .7, (255,255,255), 1)
        images.append(cell)
    images.append(np.zeros_like(images[0]))
    cv2.imwrite(str(out / "dystopia-icons.png"), np.vstack([
        np.hstack(images[i:i+5]) for i in range(0, 15, 5)]))


if __name__ == "__main__":
    main()
