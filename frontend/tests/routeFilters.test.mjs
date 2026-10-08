import assert from 'node:assert/strict';
import test from 'node:test';
import { filterRoutes, relatedGoals } from '../src/routeFilters.js';

function route(score, ids, path) {
  return { goalType: 'exit', endNode: 'end', metrics: { weightedValue: score }, relatedGoalIds: ids,
    steps: path.map(entered => ({ entered, arrived: entered })) };
}

test('priority filters include independent group results and sort by score', () => {
  const a = route(10, ['A'], ['x']), b = route(100, ['B'], ['y']), both = route(50, ['A', 'B'], ['z']);
  const plan = { routes: [b], routeGroups: [{ routes: [a, both, b] }] };
  assert.deepEqual(filterRoutes(plan, [], 'all', 5), [b, both, a]);
  assert.deepEqual(filterRoutes(plan, ['A'], 'all', 5), [both, a]);
  assert.deepEqual(filterRoutes(plan, ['A', 'B'], 'all', 5), [both]);
  assert.deepEqual(filterRoutes(plan, ['A', 'B'], 'any', 2), [b, both]);
  assert.deepEqual(filterRoutes(plan, ['absent']), []);
});

test('matching trajectories deduplicate item allocations, not related destinations', () => {
  const a = route(10, ['A'], ['x']), duplicate = { ...a, allocation: 'other' };
  assert.equal(filterRoutes({ routes: [a], routeGroups: [{ routes: [duplicate] }] }).length, 1);
  assert.deepEqual(relatedGoals({ prerequisites: [{ id: 'A', searchCoverage: .5 }, { id: 'B', plannedCompletion: true }] }), ['A', 'B']);
  assert.deepEqual(filterRoutes(null), []);
});
