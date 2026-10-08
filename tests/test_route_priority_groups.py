import unittest

from fulcrum.route_planner import RoutePlanner
from tests.test_route_planner import make_map, state
from tests.test_snapshot_scoring import context


class PriorityRouteGroupsTests(unittest.TestCase):
    def test_lower_score_priority_route_is_kept_outside_overall_top_one(self):
        geometry = make_map([(0, 0, 'start'), (-1, 0, 'node_type_009'), (1, 0, 'node_type_007')],
                            [('0,0', '-1,0'), ('0,0', '1,0')])
        c = context()
        c['options']['nodeScores'] = {'-1,0': 0, '1,0': 2000}
        target = {'id': 'ending3_beacon', 'name': '怦然信标', 'knownNodeIds': ['-1,0'], 'positionProbabilities': {}}
        result = RoutePlanner(geometry).plan(state(1, pursuit=True, topN=1, scoringContext=c,
                                                  planningTargets=[target], groupByPriority=True))
        self.assertTrue(result['searchComplete'])
        self.assertEqual(result['routes'][0]['steps'][0]['entered'], '1,0')
        groups = {tuple(group['relatedGoalIds']): group['routes'] for group in result['routeGroups']}
        self.assertIn((), groups)
        self.assertIn(('ending3_beacon',), groups)
        related = groups[('ending3_beacon',)][0]
        self.assertEqual(related['prerequisites'][0]['visitedNodeIds'], ['-1,0'])
        self.assertEqual(related['relatedGoalIds'], ['ending3_beacon'])
        self.assertLess(related['metrics']['weightedValue'], result['routes'][0]['metrics']['weightedValue'])

    def test_revelation_is_related_but_is_not_fake_completion(self):
        geometry = make_map([(0, 0, 'start'), (1, 0, 'node_type_001'), (2, 0, 'unknown_ferocity'), (-1, 0, 'node_type_007')],
                            [('0,0', '1,0'), ('1,0', '2,0'), ('0,0', '-1,0')], hidden={'2,0'})
        c = context()
        c['options']['nodeScores'] = {'-1,0': 10000}
        target = {'id': 'ending3_autopsy', 'name': '无效验尸', 'knownNodeIds': [], 'positionProbabilities': {'2,0': .5}}
        result = RoutePlanner(geometry).plan(state(1, pursuit=True, topN=1, scoringContext=c,
                                                  planningTargets=[target], groupByPriority=True))
        route = next(group for group in result['routeGroups'] if group['relatedGoalIds'])['routes'][0]
        info = route['prerequisites'][0]
        self.assertTrue(info['related'])
        self.assertEqual(info['revealedNodeIds'], ['2,0'])
        self.assertFalse(info['plannedCompletion'])
        self.assertEqual(info['visitedNodeIds'], [])
        self.assertEqual(info['searchCoverage'], .5)

    def test_multiple_related_targets_share_one_group_and_remain_score_sorted(self):
        geometry = make_map([(0, 0, 'start'), (1, 0, 'node_type_009'), (2, 0, 'unknown_ferocity'), (-1, 0, 'node_type_007')],
                            [('0,0', '1,0'), ('1,0', '2,0'), ('0,0', '-1,0')], hidden={'2,0'})
        targets = [
            {'id': 'ending3_beacon', 'name': '怦然信标', 'knownNodeIds': ['1,0'], 'positionProbabilities': {}},
            {'id': 'ending3_autopsy', 'name': '无效验尸', 'knownNodeIds': [], 'positionProbabilities': {'2,0': 1}},
        ]
        result = RoutePlanner(geometry).plan(state(1, pursuit=True, scoringContext=context(),
                                                  planningTargets=targets, groupByPriority=True))
        group = next(group for group in result['routeGroups'] if len(group['relatedGoalIds']) == 2)
        self.assertEqual(set(group['relatedGoalIds']), {target['id'] for target in targets})
        for collection in [result['routes'], *(group['routes'] for group in result['routeGroups'])]:
            scores = [route['metrics']['weightedValue'] for route in collection]
            self.assertEqual(scores, sorted(scores, reverse=True))
