from copy import deepcopy
import random
import unittest

from fulcrum.component_box import INITIAL_USES, add_component
from fulcrum.route_allocation import GeometryCache, TrajectoryPool
from fulcrum.route_frontier import ScoredInventoryFrontier
from fulcrum.route_planner import RoutePlanner
from tests.test_route_planner import make_map, state
from tests.test_snapshot_scoring import context


def with_items(components, *, free=4, options=None):
    c = context(options=options)
    items = []
    for component, uses, appraisal in components:
        item = add_component(c["componentBox"], component, remaining_uses=uses, estimated_value=appraisal)
        items.append({"instanceId": item["instanceId"], "componentId": component,
                      "remainingUses": uses, "estimatedValue": appraisal})
    c["componentBox"]["capacity"] = len(c["componentBox"]["items"]) + free
    return c, items


def best_score(result, field="routes"):
    return max((row["metrics"]["weightedValue"] for row in result[field]), default=None)


class RouteAllocationTests(unittest.TestCase):
    def test_trajectory_pool_shares_paths_without_merging_different_orders(self):
        pool = TrajectoryPool()
        a = pool.extend(0, 1, 1)
        self.assertEqual(a, pool.extend(0, 1, 1))
        b = pool.extend(0, 2, 2)
        self.assertNotEqual(pool.extend(a, 3, 3), pool.extend(b, 3, 3))
        self.assertNotEqual(pool.extend(0, 1, 2), a)
        self.assertEqual(pool.hits, 1)

    def compare(self, game_map, inputs):
        before = deepcopy(inputs)
        reference = RoutePlanner(game_map).plan({**inputs, "searchMode": "reference", "maxStates": 200000})
        target = RoutePlanner(game_map).plan({**inputs, "searchMode": "target", "maxStates": 200000})
        self.assertEqual(inputs, before)
        self.assertTrue(reference["searchComplete"] and target["searchComplete"])
        for field in ("routes", "treeholeBranches"):
            self.assertEqual(best_score(reference, field), best_score(target, field))
        for route in target["routes"] + target["treeholeBranches"]:
            uses = {row["instanceId"]: row["remainingUses"] for row in inputs.get("items", [])}
            for step in route["steps"]:
                if step["itemInstanceId"]:
                    uses[step["itemInstanceId"]] -= 1
                    self.assertGreaterEqual(uses[step["itemInstanceId"]], 0)
                self.assertEqual(step["actionPointsAfter"], step["actionPointsBefore"] - step["actionCost"] + step["actionGain"])
        return reference, target

    def test_frontier_keeps_score_preference_and_ability_tradeoffs(self):
        f = ScoredInventoryFrontier((3, 3))
        self.assertTrue(f.admit(("g",), (2, 1), 0, 100, ((1,),)))
        self.assertFalse(f.admit(("g",), (1, 1), 1, 99, ((0,),)))
        self.assertTrue(f.admit(("g",), (1, 1), 2, 100, ((0,),)))
        self.assertTrue(f.admit(("g",), (0, 3), 3, 100, ((0,),)))
        self.assertTrue(f.admit(("g",), (2, 3), 4, 101, ((2,),)))
        self.assertEqual(f.obsolete, {0, 2, 3})

    def test_shared_geometry_matches_uncached_visibility(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_018"), (2, 0, "unknown_mystery")],
                     [("0,0", "1,0"), ("1,0", "2,0")])
        p = RoutePlanner(m)
        cache = GeometryCache(p.nodes, {}, p._visible_after)
        a = cache.resolve(1, 1, 1)
        b = cache.resolve(1, 1, 1)
        self.assertEqual(a, b)
        self.assertEqual(a[3], p._visible_after(1, 3, 3, 1))
        self.assertEqual(cache.hits, 1)
        self.assertEqual(cache.misses, 1)
        cache.resolve(1, 3, a[3])
        self.assertEqual(cache.misses, 2)

    def test_scored_frontier_guards_tight_box_unknown_appraisal_and_negative_weight(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "node_type_015")],
                     [("0,0", "1,0"), ("1,0", "2,0")])
        for free, value, weight, enabled in ((3, 0, 1, True), (1, 0, 1, False),
                                           (0, 0, 1, False), (3, None, 1, False), (3, 0, -1, False)):
            with self.subTest(free=free, value=value, weight=weight):
                c, items = with_items([("component_015", 2, value)], free=free,
                    options={"nodeWeights": {"1,0": weight}})
                _, result = self.compare(m, state(2, scoringContext=c, items=items, componentBoxFreeSlots=free))
                self.assertEqual(result["searchDiagnostics"]["inventoryDominanceEnabled"], enabled)

    def test_processing_reward_and_consumption_are_not_replaced_by_walking(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_007"), (2, 0, "node_type_015")],
                     [("0,0", "1,0"), ("1,0", "2,0")])
        c, items = with_items([("component_013", 1, 2)])
        add_component(c["componentBox"], "component_029", estimated_value=1)
        _, result = self.compare(m, state(2, scoringContext=c, items=items, componentBoxFreeSlots=3))
        self.assertTrue(result["searchDiagnostics"]["inventoryDominanceEnabled"])
        self.assertEqual(result["routes"][0]["steps"][0]["movement"], "item")

    def test_allocation_keeps_item_needed_later_in_the_same_trajectory(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_001"), (3, 0, "node_type_015")], [])
        c, items = with_items([("component_013", 1, 0), ("component_015", 1, 0)])
        _, result = self.compare(m, state(2, scoringContext=c, items=items, componentBoxFreeSlots=4))
        self.assertEqual([step["componentId"] for step in result["routes"][0]["steps"]],
                         ["component_015", "component_013"])

    def test_same_trajectory_uses_expiring_item_first_when_scores_tie(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "node_type_015")], [])
        c, items = with_items([("component_016", 1, 0), ("component_017", 1, 0)])
        _, result = self.compare(m, state(1, scoringContext=c, items=items, componentBoxFreeSlots=4))
        self.assertEqual(result["routes"][0]["steps"][0]["componentId"], "component_016")

    def test_pursuit_settles_zero_ap_and_only_discards_completed_lower_scores(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_001"), (0, 1, "node_type_001"),
                      (-1, 0, "node_type_001")], [("0,0", "1,0"), ("0,0", "0,1"), ("0,0", "-1,0")])
        c = context(options={"nodeScores": {"1,0": 100, "0,1": 50, "-1,0": 25}})
        reference, target = self.compare(m, state(1, pursuit=True, topN=1, scoringContext=c))
        self.assertEqual(target["routes"][0]["endNode"], "1,0")
        self.assertEqual(target["searchDiagnostics"]["pursuitTerminalsPruned"], 2)
        self.assertEqual(target["searchDiagnostics"]["pursuitTerminalsSettledWithoutQueue"], 1)
        self.assertLess(target["generatedStates"], reference["generatedStates"])

    def test_pursuit_equal_scores_keep_distinct_trajectories(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_001"), (0, 1, "node_type_001")],
                     [("0,0", "1,0"), ("0,0", "0,1")])
        c = context(options={"nodeScores": {"1,0": 100, "0,1": 100}})
        _, target = self.compare(m, state(1, pursuit=True, topN=2, scoringContext=c))
        self.assertEqual(len(target["routes"]), 2)

    def test_whole_trajectory_allocation_honors_tight_box_charge_preference(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_001"), (2, 0, "node_type_015")], [])
        for free, selected in ((0, 0), (4, 1)):
            with self.subTest(free=free):
                c, items = with_items([("component_015", 1, 0), ("component_015", 3, 0)], free=free)
                _, target = self.compare(m, state(2, items=items, scoringContext=c, componentBoxFreeSlots=free))
                self.assertEqual(target["routes"][0]["steps"][0]["itemInstanceId"], items[selected]["instanceId"])

    def test_terminal_cache_is_reset_when_confirmed_snapshot_changes(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_001")], [("0,0", "1,0")])
        c = context(options={"teamThresholdOverride": "insufficient", "hopeDeficit": 20})
        planner = RoutePlanner(m)
        first = planner.plan(state(1, pursuit=True, scoringContext=c))
        c["resources"]["level"] = 10
        c["resources"]["experience"]["current"] = 0
        updated = planner.plan(state(1, pursuit=True, scoringContext=c))
        fresh = RoutePlanner(m).plan(state(1, pursuit=True, scoringContext=c))
        self.assertEqual(best_score(updated), best_score(fresh))
        self.assertGreater(best_score(first), best_score(updated))

    def test_small_snapshots_match_complete_reference(self):
        rng = random.Random(7012)
        coords = [(0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (2, 1)]
        edges = [("0,0", "1,0"), ("0,0", "0,1"), ("1,0", "1,1"), ("0,1", "1,1"),
                 ("1,0", "2,0"), ("1,1", "2,1"), ("2,0", "2,1")]
        pool = ["component_013", "component_015", "component_016", "component_017", "component_020", "component_021", "component_022"]
        for case in range(24):
            with self.subTest(case=case):
                categories = ["start"] + [rng.choice(["node_type_001", "node_type_007", "node_type_013", "node_type_018", "node_type_020"])
                                          for _ in range(4)] + ["node_type_015"]
                m = make_map([(x, y, t) for (x, y), t in zip(coords, categories)], edges)
                components = [(component, rng.randint(1, min(2, INITIAL_USES[component])), rng.randint(0, 2))
                              for component in (rng.choice(pool), rng.choice(pool))]
                c, items = with_items(components, free=1 if case % 4 == 0 else 4)
                if case % 5 == 0:
                    add_component(c["componentBox"], "component_029", estimated_value=1)
                self.compare(m, state(rng.randint(1, 3), pursuit=case % 2 == 0, topN=5,
                             scoringContext=c, items=items, componentBoxFreeSlots=1 if case % 4 == 0 else 3))


if __name__ == "__main__":
    unittest.main()
