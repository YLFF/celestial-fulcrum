import test from 'node:test';
import assert from 'node:assert/strict';
import { candidateIconSwitch, candidatePositions, POSITION_FILTERS, routeCurve } from '../src/mapPresentation.js';
import { mergedRecognitionPreview, recognitionChanges, recognitionReview, residentActive, newRecognizedRelics } from '../src/recognitionMerge.js';
import { AREA_NAMES } from '../src/model.js';

test('ten fixed area names and candidate filter order', () => {
  assert.equal(Object.keys(AREA_NAMES).length, 10);
  assert.equal(AREA_NAMES.I, 'I · 玻利瓦尔肤层');
  assert.ok(AREA_NAMES.V.includes('卡德霍之颅'));
  assert.deepEqual(POSITION_FILTERS.map(row => row[1]), ['秘境行商', '诡意行商', '误入奇境', '狭路相逢', '不期而遇', '先行一步', '无效验尸', '险路小径', '小八戒']);
  const instance = { nodes: { a: {}, b: { completion: 'completed' }, c: { resolvedCategoryId: 'node_type_013' } },
    prediction: { unknownNodes: { a: { candidates: [{ categoryId: 'node_type_013' }], endingOccupancy: [{ goalId: 'ending3_autopsy', probability: .5 }] },
      b: { candidates: [{ categoryId: 'node_type_013' }] }, c: { candidates: [{ categoryId: 'node_type_013' }] } } } };
  assert.deepEqual([...candidatePositions(instance, 'node_type_013')], ['a']);
  assert.deepEqual([...candidatePositions(instance, 'autopsy')], ['a']);
  assert.equal(candidatePositions(instance, '').size, 0);
});

test('little eight highlights unknown mystery, then unvisited noncombat, then all noncombat without icon switching', () => {
  const instance = { nodes: {
    a: { observedCategoryId: 'unknown_mystery', completion: 'pending' },
    b: { resolvedCategoryId: 'node_type_007', completion: 'pending' },
    c: { resolvedCategoryId: 'node_type_004', completion: 'completed' },
    d: { resolvedCategoryId: 'node_type_001', observedCategoryId: 'node_type_020', completion: 'completed' },
    e: { observedCategoryId: 'unknown_ferocity', completion: 'pending' },
    f: { resolvedCategoryId: 'node_type_007', confirmedMarkIds: ['node_mark_001'], completion: 'pending' },
    g: { resolvedCategoryId: 'node_type_021', confirmedMarkIds: ['node_mark_001'], completion: 'completed' },
  } };
  assert.deepEqual([...candidatePositions(instance, 'little-eight')], ['a']);
  instance.nodes.a.resolvedCategoryId = 'node_type_001';
  assert.deepEqual([...candidatePositions(instance, 'little-eight')], ['b']);
  instance.nodes.b.completion = 'completed';
  assert.deepEqual([...candidatePositions(instance, 'little-eight')], ['b', 'c', 'd', 'g']);
  assert.equal(candidateIconSwitch('little-eight'), false);
  assert.equal(candidateIconSwitch('node_type_013'), true);
  assert.equal(candidateIconSwitch(''), false);
});

test('straight and jump moves become directional curves, not map edges', () => {
  assert.match(routeCurve({ x: 0, y: 0 }, { x: 200, y: 0 }, 0), /^M .* Q /);
  assert.match(routeCurve({ x: 0, y: 0 }, { x: 0, y: 200 }, 0), /^M .* Q /);
  assert.equal(routeCurve({ x: 1, y: 1 }, { x: 1, y: 1 }, 0), null);
  assert.notEqual(routeCurve({ x: 0, y: 0 }, { x: 200, y: 0 }, 0), routeCurve({ x: 200, y: 0 }, { x: 0, y: 0 }, 1));
  for (const end of [{ x: 216, y: 0 }, { x: 0, y: 196 }]) {
    const numbers = routeCurve({ x: 0, y: 0 }, end).match(/-?\d+(?:\.\d+)?/g).map(Number);
    const [, , cx, cy, ex, ey] = numbers;
    let nearest = Infinity;
    for (let t = 0; t <= 1; t += .001) {
      const x = 2 * (1 - t) * t * cx + t * t * ex, y = 2 * (1 - t) * t * cy + t * t * ey;
      nearest = Math.min(nearest, Math.hypot(x - end.x / 2, y - end.y / 2));
    }
    assert.ok(nearest > 27, `jump curve intersects intermediate disc: ${nearest}`);
  }
});

const old = { templateId: 't', nodes: {
  a: { id: 'a', resolvedCategoryId: 'node_type_011', observedCategoryId: 'node_type_011', completion: 'pending', confirmedMarkIds: [] },
  b: { id: 'b', resolvedCategoryId: 'node_type_006', observedCategoryId: 'node_type_006', completion: 'pending', confirmedMarkIds: [], encounterId: null },
  c: { id: 'c', resolvedCategoryId: 'node_type_006', observedCategoryId: 'node_type_020', completion: 'completed', confirmedMarkIds: [], encounterId: 'event-1' },
  d: { id: 'd', resolvedCategoryId: null, observedCategoryId: 'unknown_mystery', completion: 'pending', confirmedMarkIds: [] },
} };
const observation = { success: true, templateId: 't', edges: [], nodes: ['a', 'b', 'c', 'd'].map(id => ({ id, categoryId: 'node_type_020', marks: [] })) };

test('map relic sync lists only accepted, new, unique complete icons without changing source data', () => {
  const source = { success: true, relicObservation: { success: true,
    acceptedRelicIds: ['held', 'new', 'partial'], slots: [
      { id: 'held', status: 'accepted' }, { id: 'new', name: '新藏品', status: 'accepted' },
      { id: 'new', status: 'accepted' }, { id: 'uncertain', status: 'needs_review' },
      { id: 'partial', status: 'accepted', partial: true },
    ] } };
  const held = [{ id: 'held', state: 4, note: 'keep' }];
  const before = structuredClone({ source, held });
  assert.deepEqual(newRecognizedRelics(source, held).map(row => row.id), ['new']);
  assert.deepEqual(newRecognizedRelics({ ...source, success: false }, held), []);
  assert.deepEqual(newRecognizedRelics({ success: true }, held), []);
  assert.deepEqual(newRecognizedRelics(null, held), []);
  assert.deepEqual({ source, held }, before);
});

test('merge change summary distinguishes revelations, completion suggestions and conflicts', () => {
  assert.deepEqual(recognitionChanges(observation, old).map(row => [row.nodeId, row.kind]),
    [['a', 'completion'], ['b', 'completion'], ['d', 'completion']]);
  const changed = { ...observation, nodes: [{ id: 'a', categoryId: 'node_type_001' },
    { id: 'd', categoryId: 'node_type_013' }, { id: 'c', categoryId: 'node_type_020' }] };
  assert.deepEqual(recognitionChanges(changed, old).map(row => [row.nodeId, row.kind]), [['a', 'conflict'], ['d', 'reveal']]);
  assert.deepEqual(recognitionChanges(changed, old, true), []);
});
test('merge preview preserves original types/events and exposes unknown traversed type', () => {
  const before = structuredClone(old);
  const review = recognitionReview(observation, old);
  assert.deepEqual(review.map(row => [row.nodeId, row.categoryId]), [['a', 'node_type_011'], ['b', 'node_type_006'], ['d', '']]);
  const preview = mergedRecognitionPreview(observation, old, { newInstance: false, completions: { a: true, b: true },
    nodeChanges: {}, encounters: { b: 'event-2' }, markChoices: {}, position: '', completePosition: false });
  assert.equal(preview.nodes.a.resolvedCategoryId, 'node_type_011');
  assert.equal(preview.nodes.a.completion, 'completed');
  assert.equal(preview.nodes.b.encounterId, 'event-2');
  assert.equal(preview.nodes.c.encounterId, 'event-1');
  assert.equal(preview.nodes.c.completion, 'completed');
  assert.deepEqual(old, before);
  assert.deepEqual(recognitionReview(observation, old, true), []);
  assert.deepEqual(recognitionReview({ ...observation, templateId: 'different' }, old), []);
  const missing = { ...observation, nodes: [{ id: 'c', categoryId: null, visibility: 'unknown', marks: [] }] };
  const retained = mergedRecognitionPreview(missing, old, { newInstance: false, nodeChanges: {}, completions: {}, encounters: {}, markChoices: {} });
  assert.equal(retained.nodes.c.resolvedCategoryId, 'node_type_006');
  assert.equal(retained.nodes.c.observedCategoryId, 'node_type_020');
  assert.equal(retained.nodes.c.encounterId, 'event-1');
});

test('resident merge refreshes overlays on completed nodes without erasing original event history', () => {
  const previous = { templateId: 't', nodes: {
    a: { ...old.nodes.c, id: 'a', completedCategoryId: 'node_type_006', confirmedMarkIds: ['node_mark_001', 'node_mark_007'], residentCleared: false },
    b: { ...old.nodes.c, id: 'b', completedCategoryId: 'node_type_006', confirmedMarkIds: [], residentCleared: true },
  } };
  const incoming = { success: true, templateId: 't', edges: [], nodes: [
    { id: 'a', categoryId: 'node_type_020', marks: [] },
    { id: 'b', categoryId: 'node_type_020', marks: [{ id: 'node_mark_001', status: 'confirmed' }] },
  ] };
  assert.deepEqual(recognitionChanges(incoming, previous).map(row => [row.nodeId, row.kind]),
    [['a', 'residentDeparture'], ['b', 'residentArrival']]);
  const options = { newInstance: false, nodeChanges: {}, completions: {}, encounters: {}, markChoices: {} };
  const preview = mergedRecognitionPreview(incoming, previous, options);
  assert.deepEqual(preview.nodes.a.confirmedMarkIds, ['node_mark_007']);
  assert.equal(residentActive(preview.nodes.b), true);
  assert.equal(preview.nodes.b.encounterId, 'event-1');
  assert.equal(preview.nodes.b.completedCategoryId, 'node_type_006');
  const atResident = { ...incoming, playerPositionObservation: { nodeId: 'b' } };
  assert.deepEqual(recognitionReview(atResident, previous).map(row => [row.nodeId, row.reason]), [['b', 'resident']]);
  const cleared = mergedRecognitionPreview(atResident, previous, { ...options, position: 'b', completePosition: true });
  assert.equal(residentActive(cleared.nodes.b), false);
  assert.equal(cleared.nodes.b.completedCategoryId, 'node_type_006');
});

test('completion preview clears all residents when completing the outpost, never other marks', () => {
  const previous = { templateId: 't', nodes: {
    a: { ...old.nodes.a, resolvedCategoryId: 'node_type_019' },
    b: { ...old.nodes.c, confirmedMarkIds: ['node_mark_001', 'node_mark_007'], residentCleared: false },
  } };
  const preview = mergedRecognitionPreview(observation, previous, { newInstance: false,
    completions: { a: true }, nodeChanges: {}, encounters: {}, markChoices: {} });
  assert.deepEqual(preview.nodes.b.confirmedMarkIds, ['node_mark_007']);
  assert.equal(residentActive(preview.nodes.b), false);
});

test('an incoming resident on an unread unknown node does not suggest completion of the original node', () => {
  const incoming = { success: true, templateId: 't', nodes: [
    { id: 'd', categoryId: 'node_type_020', marks: [{ id: 'node_mark_001', status: 'confirmed' }] },
  ] };
  assert.deepEqual(recognitionChanges(incoming, old).map(row => row.kind), ['residentArrival']);
  assert.deepEqual(recognitionReview(incoming, old), []);
});

test('unrevealed fixed exits appear in merge preview without being mistaken for shortcuts', () => {
  const incoming = { success: true, templateId: 't', edges: [], nodes: [
    { id: 'a', categoryId: 'unknown_mystery', templateHint: 'danger-end', marks: [] },
    { id: 'b', categoryId: null, templateHint: 'danger-end', marks: [] },
    { id: 'c', categoryId: 'node_type_016', templateHint: null, marks: [] },
  ] };
  const preview = mergedRecognitionPreview(incoming, null, { newInstance: true,
    completions: {}, nodeChanges: {}, encounters: {}, markChoices: {} });
  assert.equal(preview.nodes.a.resolvedCategoryId, 'node_type_015');
  assert.equal(preview.nodes.b.resolvedCategoryId, 'node_type_015');
  assert.equal(preview.nodes.c.resolvedCategoryId, 'node_type_016');
});
