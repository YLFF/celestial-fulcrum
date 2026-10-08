import test from 'node:test';
import assert from 'node:assert/strict';
import { areaFromObservation, componentCommands, currentInstance, nodeCategory, stepScoreDetails, TERM_NAMES, scoreNote, typeScoreRows } from '../src/model.js';

test('autopsy is a separate global-probability score branch, not labeled ordinary combat', () => {
  const value = { types: [
    { categoryId: 'node_type_001', probability: .75, score: { points: 234, branches: [
      { name: '结局前置', probability: 2 / 3, score: { points: 312, stage: '无效验尸', goalId: 'ending3_autopsy' } },
      { name: '普通节点', probability: 1 / 3, score: { points: 78 } },
    ] } },
    { categoryId: 'node_type_002', probability: .25, score: { points: 390 } },
  ] };
  const before = structuredClone(value);
  const rows = typeScoreRows(value, { node_type_001: '作战', node_type_002: '紧急作战' });
  assert.deepEqual(rows.map(row => [row.name, row.probability, row.probability * row.score.points]),
    [['无效验尸', .5, 156], ['作战', .25, 19.5], ['紧急作战', .25, 97.5]]);
  assert.equal(rows.reduce((sum, row) => sum + row.probability * row.score.points, 0), 273);
  assert.deepEqual(value, before);
  assert.deepEqual(typeScoreRows({}), []);
});

test('route details use arrival shop scores and never restore a repeated node reward', () => {
  const frozen = { n: { points: 120, arrivalPoints: 999, classification: { probabilities: { node_type_013: 1 } },
    types: [{ categoryId: 'node_type_013', probability: 1, score: { points: 120 } }] } };
  const before = structuredClone(frozen);
  const row = { frozenBreakdownNodeId: 'n', points: 300, parts: { typeExpectation: 120, merchantPrefixAdjustment: 180 },
    merchantTypes: [{ categoryId: 'node_type_013', merchant: { points: 300, parts: { entry: 300 } } }] };
  const details = stepScoreDetails(row, frozen);
  assert.equal(details.points, 300);
  assert.equal(details.types[0].score.points, 300);
  assert.equal(details.arrivalPoints, undefined);
  assert.deepEqual(stepScoreDetails({ points: 0, frozenBreakdownNodeId: null }, frozen), { points: 0, frozenBreakdownNodeId: null });
  assert.deepEqual(frozen, before);
});

test('event scoring labels and tribute limitations are localized', () => {
  for (const key of ['combat80Percent', 'directRelic20Percent', 'conditionalRounds', 'actionOpportunity', 'hopefulSoil']) {
    assert.ok(/[\u4e00-\u9fff]/.test(TERM_NAMES[key]));
  }
  assert.ok(scoreNote('tribute appraisal uses confirmed values only').includes('估价'));
});

test('treehole parent is never guessed from screenshot', () => {
  assert.equal(areaFromObservation({area: 'treehole', floor: 3}), null);
  assert.equal(areaFromObservation({area: 'main', floor: 4}), 'IV');
});
test('active instance and original category survive completion', () => {
  assert.equal(currentInstance({areas: {I: {activeInstanceId: 'a', instances: [{instanceId: 'a'}]}}}, 'I').instanceId, 'a');
  assert.equal(currentInstance(null, 'I'), null);
  assert.equal(nodeCategory({resolvedCategoryId: 'node_type_005', observedCategoryId: 'empty'}), 'node_type_005');
});
test('inventory batch grows before adding and shrinks after removal', () => {
  const a = {instanceId: 'a', componentId: 'component_001', estimatedValue: 5};
  const b = {instanceId: 'b', componentId: 'component_001', estimatedValue: 5};
  assert.deepEqual(componentCommands({capacity: 1, items: [a]}, {capacity: 2, items: [a,b]}).map(x => x.type), ['componentCapacity','componentAdd']);
  assert.deepEqual(componentCommands({capacity: 2, items: [a,b]}, {capacity: 1, items: [a]}).map(x => x.type), ['componentRemove','componentCapacity']);
});
test('unchanged components do not emit mutations', () => {
  const before = {capacity: 8, items: [{instanceId: 'a', componentId: 'component_023', remainingUses: 2, estimatedValue: 10, routeCandidate: true}]};
  assert.deepEqual(componentCommands(before, structuredClone(before)), []);
  const draft = structuredClone(before); draft.items[0].routeCandidate = false;
  assert.deepEqual(componentCommands(before, draft), [{type: 'componentUpdate', instanceId: 'a', changes: {routeCandidate: false}}]);
});
