from copy import deepcopy
from pathlib import Path
import unittest

import cv2
import numpy as np

from fulcrum.playtime_state import new_playtime, set_player_position
from fulcrum.route_planner import RoutePlanner
from fulcrum.node_scoring import SnapshotScorer
from fulcrum.service.updates import validate_application_state
from fulcrum.vision_action import recognize_action
from fulcrum.vision_resources import _box
from fulcrum.vision_geometry import working_image, detect_map_viewport
from fulcrum.window_capture import _crop_client_frame, CaptureUnavailable
from tests.test_route_planner import make_map, state
from tests.test_snapshot_scoring import context

ROOT = Path(__file__).resolve().parents[1]


class PlayerUpdateTests(unittest.TestCase):
    def test_position_is_completed_and_preserves_original_category(self):
        instance = {"nodes": {"a": {"completion": "unknown", "resolvedCategoryId": "node_type_001", "completedCategoryId": None}}}
        set_player_position(instance, "a")
        self.assertEqual(instance["nodes"]["a"]["completion"], "completed")
        self.assertEqual(instance["nodes"]["a"]["completedCategoryId"], "node_type_001")
        instance["nodes"]["a"]["resolvedCategoryId"] = "node_type_020"
        set_player_position(instance, "a")
        self.assertEqual(instance["nodes"]["a"]["completedCategoryId"], "node_type_001")

    def test_resource_bounds_and_nonintegral_values(self):
        for field, value in (("hope", -1), ("hope", 2.5), ("shield", True), ("level", 11),
                             ("life", {"current": 5, "max": 4}), ("experience", {"current": 11, "max": 10})):
            with self.subTest(field=field, value=value):
                run = new_playtime("invalid-resource")
                run["resources"][field] = value
                with self.assertRaises(ValueError):
                    validate_application_state(run)
        run = new_playtime("max-level")
        run["resources"].update(level=10, experience={"current": 100, "max": 0})
        validate_application_state(run)

    def test_repeat_shop_keeps_withdrawal_and_removes_tickets(self):
        scorer = SnapshotScorer([{"id": "s", "categoryId": "start"},
            {"id": "g", "categoryId": "node_type_004"}], context("I"), state(3))
        first = scorer.shop("node_type_004", 50, 0, done={"s"}, repeated=False, node_id="g", viewed_shelves=0)
        again = scorer.shop("node_type_004", 50, 0, done={"s", "g"}, repeated=True, node_id="g", viewed_shelves=1)
        self.assertGreater(first["parts"]["tickets"], 0)
        self.assertEqual(again["parts"]["tickets"], 0)
        self.assertEqual(again["withdrawalPoints"], 80)

    def test_arrival_reveal_preview_matches_first_step(self):
        game_map = make_map([(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "unknown_ferocity")],
                            [("0,0", "1,0"), ("1,0", "2,0")], hidden={"2,0"})
        c = context("I", options={"nodeScores": {"2,0": 100}})
        route_state = state(1, pursuit=True, scoringContext=c)
        before = deepcopy(route_state)
        planner = RoutePlanner(game_map)
        preview = planner.score_snapshot(route_state)["nodeValues"]["1,0"]
        self.assertAlmostEqual(preview["revealValue"], 20)
        result = planner.plan(route_state)
        step = result["routes"][0]["steps"][0]
        self.assertAlmostEqual(preview["revealValue"], step["revealValue"])
        self.assertAlmostEqual(preview["arrivalPoints"], preview["points"] + step["revealValue"])
        self.assertEqual(route_state, before)
        for route in result["routes"]:
            self.assertAlmostEqual(route["metrics"]["weightedValue"],
                sum(step["weightedValue"] for step in route["steps"]) + route["terminalScore"]["points"], places=1)

    def test_top_above_three_returns_distinct_trajectories(self):
        nodes = [(x, y, "start" if (x, y) == (0, 0) else "node_type_015" if (x, y) == (2, 2) else "node_type_001")
                 for x in range(3) for y in range(3)]
        edges = [(f"{x},{y}", f"{x+dx},{y+dy}") for x in range(3) for y in range(3)
                 for dx, dy in ((1, 0), (0, 1)) if x + dx < 3 and y + dy < 3]
        planner = RoutePlanner(make_map(nodes, edges))
        result = planner.plan(state(6, topN=7, scoringContext=context("I")))
        self.assertEqual(len(result["routes"]), 7)
        paths = [tuple((s["entered"], s["arrived"]) for s in r["steps"]) for r in result["routes"]]
        self.assertEqual(len(set(paths)), 7)

    def test_client_crop_does_not_resize_or_include_window_chrome(self):
        image = np.arange(8 * 10 * 3, dtype=np.uint8).reshape(8, 10, 3)
        client = {"x": 102, "y": 204, "width": 6, "height": 3}
        crop = _crop_client_frame(image, client, [(100, 200, 110, 208)])
        np.testing.assert_array_equal(crop, image[4:7, 2:8])
        with self.assertRaises(CaptureUnavailable):
            _crop_client_frame(image, client, [(0, 0, 11, 9)])

    def test_action_four_and_five_at_native_and_downscaled_sizes(self):
        for expected in (4, 5):
            source = cv2.imread(str(ROOT / f"samples/maps/desktop_action_{expected}.png"))
            for size in (None, (2048, 1152)):
                image = source if size is None else cv2.resize(source, size)
                work, scale = working_image(image)
                viewport = tuple(round(v / scale) for v in detect_map_viewport(work))
                x0, y0, x1, y1 = _box(image, viewport, "action_points", 0.9)
                result = recognize_action(image[y0:y1, x0:x1], image.shape[0] / 1152 * 0.9)
                self.assertEqual(result["value"], expected)
                self.assertEqual(result["status"], "recognized")


if __name__ == "__main__":
    unittest.main()
