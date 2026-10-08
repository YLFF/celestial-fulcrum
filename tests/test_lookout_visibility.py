from copy import deepcopy
import unittest

from fulcrum.lookout_rules import lookout_radii
from fulcrum.playtime_route import route_inputs
from fulcrum.playtime_state import new_playtime, merge_map_observation
from fulcrum.route_planner import RoutePlanner
from tests.test_route_planner import make_map, state
from tests.test_snapshot_scoring import context
from fulcrum.map_catalog import TemplateCatalog


class LookoutVisibilityTests(unittest.TestCase):
    def test_difficulty_three_and_technology_are_both_required(self):
        for difficulty, split, expected in ((0, True, (1, 2)), (2, True, (1, 2)),
                (3, True, (2, 3)), (15, True, (2, 3)), (15, False, (1, 2))):
            with self.subTest(difficulty=difficulty, split=split):
                self.assertEqual(lookout_radii(difficulty, split), expected)
        for difficulty, split in ((True, True), (-1, True), (3, 1), (3, "false")):
            with self.assertRaises(ValueError):
                lookout_radii(difficulty, split)

    def test_spawn_and_arrival_use_diamond_not_square_or_graph(self):
        game_map = make_map([(x, y, "node_type_018" if (x, y) == (0, 0) else "unknown_mystery")
                             for x in range(-3, 4) for y in range(-3, 4)], [])
        for difficulty, split, spawn_count, arrival_count in ((2, True, 5, 13),
                (3, True, 13, 25), (15, False, 5, 13)):
            with self.subTest(difficulty=difficulty, split=split):
                planner = RoutePlanner(game_map)
                planner._configure_lookout_visibility({"difficulty": difficulty, "lookoutSplitUnlocked": split})
                index = planner.index["0,0"]
                baseline = planner._initial_visibility(index, 0, 0)
                after = planner._visible_after(index, 1 << index, baseline, index)
                self.assertEqual(baseline.bit_count(), spawn_count)
                self.assertEqual(after.bit_count(), arrival_count)
                self.assertFalse(after & (1 << planner.index["2,2"]))
                self.assertEqual(planner._initial_visibility(index, 1 << index, 0), after)

    def test_preview_search_and_first_reveal_scoring_agree(self):
        game_map = make_map([(-1, 0, "start"), (0, 0, "node_type_018"),
                (1, 1, "unknown_mystery"), (2, 1, "unknown_ferocity"), (2, 2, "unknown_mystery")],
                [("-1,0", "0,0")], hidden={"1,1", "2,1", "2,2"})
        for difficulty, split, expected_id, expected_score in ((2, True, "1,1", 20),
                (3, True, "2,1", 40), (15, False, "1,1", 20)):
            for mode in ("target", "reference"):
                with self.subTest(difficulty=difficulty, split=split, mode=mode):
                    c = context("I", options={"nodeScores": {"1,1": 100, "2,1": 200, "2,2": 300}})
                    c["opening"].update(difficulty=difficulty, lookoutSplitUnlocked=split)
                    route_state = state(1, position="-1,0", completedNodes=["-1,0"],
                                        pursuit=True, scoringContext=c, searchMode=mode)
                    before_map, before_state = deepcopy(game_map), deepcopy(route_state)
                    planner = RoutePlanner(game_map)
                    preview = planner.score_snapshot(route_state)["nodeValues"]["0,0"]
                    self.assertAlmostEqual(preview["revealValue"], expected_score)
                    self.assertEqual([row["nodeId"] for row in preview["arrivalRevealTerms"]], [expected_id])
                    route = planner.plan(route_state)["routes"][0]
                    first = route["steps"][0]
                    self.assertEqual(first["arrived"], "0,0")
                    self.assertEqual(first["actionGain"], 1)
                    self.assertEqual(first["actionPointsAfter"], 1)
                    self.assertAlmostEqual(first["revealValue"], expected_score)
                    self.assertEqual(first["newlyRevealedOtherNodes"], [expected_id])
                    self.assertAlmostEqual(sum(step["revealValue"] for step in route["steps"]), expected_score)
                    self.assertEqual(game_map, before_map)
                    self.assertEqual(route_state, before_state)

    def test_completed_lookout_does_not_reaward_sight_or_action(self):
        game_map = make_map([(-1, 0, "start"), (0, 0, "node_type_018"), (2, 1, "unknown_mystery")],
                            [("-1,0", "0,0")], hidden={"2,1"})
        route_state = state(1, position="-1,0", completedNodes=["-1,0", "0,0"], pursuit=True,
                            scoringContext=context("I", options={"nodeScores": {"2,1": 200}}))
        planner = RoutePlanner(game_map)
        self.assertEqual(planner.score_snapshot(route_state)["nodeValues"]["0,0"]["revealValue"], 0)
        for route in planner.plan(route_state)["routes"]:
            self.assertTrue(all(step["actionGain"] == 0 and step["revealValue"] == 0 for step in route["steps"]))

    def test_resident_preserves_lookout_effect(self):
        game_map = make_map([(-1, 0, "start"), (0, 0, "node_type_018"), (2, 1, "unknown_mystery")],
                            [("-1,0", "0,0")], hidden={"2,1"})
        game_map["nodes"][1]["confirmedMarkIds"] = ["node_mark_001"]
        route_state = state(1, position="-1,0", completedNodes=["-1,0"], pursuit=True,
                            scoringContext=context("I", options={"nodeScores": {"2,1": 200}}))
        first = RoutePlanner(game_map).plan(route_state)["routes"][0]["steps"][0]
        self.assertEqual(first["actionGain"], 1)
        self.assertAlmostEqual(first["revealValue"], 40)

    def test_playtime_adapter_propagates_technology_and_legacy_defaults(self):
        template = TemplateCatalog().candidates("main", 1)[0]
        observation = {"success": True, "area": "main", "floor": 1, "templateId": template.id,
            "nodes": [{"id": template.coord(slot).key, "coord": [template.coord(slot).x, template.coord(slot).y],
                       "slot": list(slot), "categoryId": "start" if slot == template.start_slot else "unknown_mystery",
                       "visibility": "hidden", "marks": []} for slot in template.occupied_slots],
            "edges": [[template.coord(a).key, template.coord(b).key] for a, b in template.edges]}
        run = new_playtime("lookout-adapter", difficulty=2, lookout_split_unlocked=False)
        instance = merge_map_observation(run, "I", observation, player_position="0,0")
        instance["actionPoints"] = 6
        _, route_state = route_inputs(run)
        self.assertEqual((route_state["difficulty"], route_state["lookoutSplitUnlocked"]), (2, False))
        del run["opening"]["lookoutSplitUnlocked"]
        self.assertTrue(route_inputs(run)[1]["lookoutSplitUnlocked"])


if __name__ == "__main__":
    unittest.main()
