from copy import deepcopy
import unittest

from fulcrum.route_planner import RoutePlanner
from scripts.audit_snapshot_similarity import future_key, near_trajectory_clusters, pareto_labels, summarize


def record(label, parent=None, *, uses=(2,), score=0, terminal=None, step=None):
    return {"labelId": label, "parentLabelId": parent, "position": "b" if parent is not None else "a",
            "actionPoints": 1, "doneMask": 3, "visibleMask": 3, "informationMask": 0,
            "rewardNodeMask": 2, "canonicalUses": uses, "score": score,
            "prefixCash": 20, "prefixAppraisal": 10, "movements": int(parent is not None),
            "terminalScore": terminal, "step": step}


def sample_map():
    return {"success": True, "nodes": [
            {"id": "a", "coord": [0, 0], "categoryId": "start", "visibility": "revealed"},
            {"id": "b", "coord": [1, 0], "categoryId": "node_type_001", "visibility": "revealed"},
            {"id": "c", "coord": [2, 0], "categoryId": "node_type_015", "visibility": "revealed"},
        ], "edges": [["a", "b"], ["b", "c"]]}


class RouteSimilarityTests(unittest.TestCase):
    def test_generation_trace_does_not_change_result_or_inputs(self):
        game_map = sample_map()
        state = {"position": "a", "actionPoints": 2, "completedNodes": ["a"]}
        before = deepcopy(state)
        expected = RoutePlanner(game_map).plan(state)
        rows = []
        actual = RoutePlanner(game_map).plan(state, on_generate=rows.append)
        self.assertEqual(actual, expected)
        self.assertEqual(state, before)
        self.assertEqual(len(rows), actual["generatedStates"])
        self.assertEqual([row["labelId"] for row in rows], list(range(len(rows))))
        self.assertTrue(all(row["parentLabelId"] < row["labelId"] for row in rows[1:]))
        self.assertTrue(any(row["terminalScore"] is not None for row in rows))
        self.assertTrue(any(row["score"] > 0 for row in rows))

    def test_zero_ap_nonterminal_pruning_preserves_best_exit(self):
        state = {"position": "a", "actionPoints": 2, "completedNodes": ["a"]}
        target = RoutePlanner(sample_map()).plan(state)
        reference = RoutePlanner(sample_map()).plan({**state, "searchMode": "reference"})
        self.assertEqual(target["routes"], reference["routes"])
        self.assertLess(target["generatedStates"], reference["generatedStates"])
        self.assertGreater(target["searchDiagnostics"]["zeroAPNonterminalActionsPruned"], 0)
        self.assertEqual(reference["searchDiagnostics"]["zeroAPNonterminalActionsPruned"], 0)

    def test_zero_ap_pursuit_and_single_step_remain_valid(self):
        state = {"position": "a", "actionPoints": 1, "completedNodes": ["a"]}
        for options in ({"pursuit": True}, {"utopiaId": "utopia_005"}):
            with self.subTest(options=options):
                target = RoutePlanner(sample_map()).plan({**state, **options})
                reference = RoutePlanner(sample_map()).plan({**state, **options, "searchMode": "reference"})
                self.assertEqual(target["routes"], reference["routes"])
                self.assertTrue(target["routes"])
                self.assertEqual(target["searchDiagnostics"]["zeroAPNonterminalActionsPruned"], 0)

    def test_known_ap_return_is_applied_before_dead_end_pruning(self):
        for component in ("component_016", "component_024"):
            with self.subTest(component=component):
                state = {"position": "a", "actionPoints": 1, "completedNodes": ["a"],
                         "items": [{"instanceId": "part", "componentId": component, "remainingUses": 1}]}
                target = RoutePlanner(sample_map()).plan(state)
                reference = RoutePlanner(sample_map()).plan({**state, "searchMode": "reference"})
                self.assertTrue(target["routes"])
                self.assertEqual(target["routes"][0]["metrics"], reference["routes"][0]["metrics"])

    def test_pareto_preserves_incomparable_abilities_and_score_tradeoff(self):
        rows = [record(0, uses=(2, 0), score=100), record(1, uses=(1, 0), score=95),
                record(2, uses=(0, 2), score=110), record(3, uses=(1, 0), score=120)]
        self.assertEqual({row["labelId"] for row in pareto_labels(rows)}, {0, 2, 3})

    def test_same_delta_trajectory_keeps_distinct_inventory_labels(self):
        step = {"from": "a", "entered": "b", "arrived": "b", "itemInstanceId": "one"}
        rows = [record(0), record(1, 0, uses=(2,), score=100, terminal=100, step=step),
                record(2, 0, uses=(1,), score=100, terminal=100,
                       step={**step, "itemInstanceId": "two"})]
        report = summarize(rows, {"searchDiagnostics": {}, "searchComplete": True},
                           {"a": (0, 0), "b": (1, 0)})
        self.assertEqual(report["exactGeometricTrajectories"], 2)
        self.assertEqual(report["sameTrajectoryExcessLabels"], 1)
        self.assertEqual(report["nearBestTerminalLabels"], 2)
        self.assertEqual(report["nearBestDistinctTrajectories"], 1)
        self.assertEqual(report["hypotheticalDominatedLabels"], 1)

    def test_future_key_keeps_economy_and_step_count(self):
        row = record(0)
        for field in ("prefixCash", "prefixAppraisal", "movements", "visibleMask", "actionPoints"):
            other = {**row, field: row[field] + 1}
            self.assertNotEqual(future_key(row, inventory=False), future_key(other, inventory=False))
        other = {**row, "canonicalUses": (1,)}
        self.assertEqual(future_key(row, inventory=False), future_key(other, inventory=False))
        self.assertNotEqual(future_key(row), future_key(other))

    def test_one_edit_neighborhood_preserves_goal_and_non_neighbors(self):
        a, b, c, d = ((i, 0, 0, 0) for i in range(4))
        paths = [("end", (a, b)), ("end", (a, c)), ("end", (a,)),
                 ("other", (a, b)), ("end", (d, d, d))]
        self.assertEqual(near_trajectory_clusters(paths), [3, 1, 1])


if __name__ == "__main__":
    unittest.main()
