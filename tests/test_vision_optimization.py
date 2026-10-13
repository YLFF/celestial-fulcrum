import unittest

import cv2
import numpy as np

from fulcrum.vision_geometry import _edge_contrast
from fulcrum.vision_icons import IconMatcher
from fulcrum.vision_node_text import label_crop


def scalar_edge_contrast(gray, first, second):
    start, end = np.array(first, np.float32), np.array(second, np.float32)
    direction = end - start
    length = float(np.linalg.norm(direction))
    if length < 35 or min(*start, *end) < 20 or max(start[0], end[0]) >= gray.shape[1] - 20 or max(start[1], end[1]) >= gray.shape[0] - 20:
        return 0.0
    normal = np.array([-direction[1], direction[0]], np.float32) / length
    center, flank = [], []
    for t in np.linspace(.29, .71, 9):
        point = start + direction * t
        cross_section = [point + normal * offset for offset in range(-8, 9, 2)]
        center.append(float(np.percentile([gray[round(p[1]), round(p[0])] for p in cross_section], 80)))
        for offset in (-17., 17.):
            p = point + normal * offset
            flank.append(float(gray[round(p[1]), round(p[0])]))
    return float(np.median(center) - np.median(flank))


def whole_patch_score(image, pixel, step, icon, scales):
    radius = min(115, max(55, round(step * .59)))
    x, y = round(pixel[0]), round(pixel[1])
    x0, y0 = max(0, x - radius), max(0, y - radius)
    patch = image[y0:min(image.shape[0], y + radius), x0:min(image.shape[1], x + radius)]
    best = -1.
    for scale in scales:
        template = cv2.resize(icon, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
        th, tw = template.shape[:2]
        if patch.shape[0] < th or patch.shape[1] < tw:
            continue
        if template.ndim == 3 and template.shape[2] == 4:
            scores = cv2.matchTemplate(patch, template[:, :, :3], cv2.TM_CCOEFF_NORMED, mask=template[:, :, 3])
        else:
            scores = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
        cx, cy = x - x0 - tw / 2, y - y0 - th / 2
        slack = max(9, step * .12)
        left, right = max(0, int(cx - slack)), min(scores.shape[1], int(cx + slack) + 1)
        top, bottom = max(0, int(cy - slack)), min(scores.shape[0], int(cy + slack) + 1)
        if left < right and top < bottom:
            finite = scores[top:bottom, left:right]
            finite = finite[np.isfinite(finite)]
            if finite.size:
                best = max(best, min(1., float(finite.max())))
    return best


class VisionOptimizationTests(unittest.TestCase):
    def test_batched_edge_samples_preserve_scalar_calculation(self):
        rng = np.random.default_rng(621)
        gray = rng.integers(0, 256, (280, 360), dtype=np.uint8)
        pairs = [((50, 50), (200, 50)), ((100, 50), (100, 200)), ((3, 50), (200, 50)), ((50, 50), (60, 60))]
        pairs.extend((tuple(rng.uniform(30, 250, 2)), tuple(rng.uniform(30, 250, 2))) for _ in range(100))
        for first, second in pairs:
            self.assertEqual(_edge_contrast(gray, first, second), scalar_edge_contrast(gray, first, second))

    def test_local_correlation_preserves_scores_and_border_behavior(self):
        rng = np.random.default_rng(483)
        for channels in (1, 3, 4):
            image = rng.integers(0, 256, (260, 340) if channels == 1 else (260, 340, 3), dtype=np.uint8)
            icon = rng.integers(0, 256, (28, 32) if channels == 1 else (28, 32, channels), dtype=np.uint8)
            if channels == 4:
                icon[:, :, 3] = rng.integers(0, 2, (28, 32), dtype=np.uint8) * 255
            for position in ((130, 130), (5, 5), (335, 250)):
                for step in (60, 140, 240):
                    scales = (.55, .85, 1., 1.45, 2.)
                    self.assertAlmostEqual(IconMatcher._score(image, position, step, icon, scales),
                                           whole_patch_score(image, position, step, icon, scales), places=5)

    def test_binary_label_variant_reuses_identical_grayscale_crop(self):
        image = np.full((260, 350, 3), 20, np.uint8)
        cv2.putText(image, 'ABCD', (130, 150), cv2.FONT_HERSHEY_SIMPLEX, .6, (240, 240, 240), 2)
        gray = label_crop(image, (170, 110), 120, (0, 0, 350, 260))
        self.assertIsNotNone(gray)
        binary = label_crop(image, (170, 110), 120, (0, 0, 350, 260), binarize=True)
        self.assertEqual(gray[1], binary[1])
        np.testing.assert_array_equal(cv2.threshold(gray[0], 64, 255, cv2.THRESH_BINARY)[1], binary[0])
