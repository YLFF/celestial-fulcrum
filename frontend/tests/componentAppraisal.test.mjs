import test from 'node:test';
import assert from 'node:assert/strict';
import { acquireDraft, appraisalDraft } from '../src/componentAppraisal.js';
import { componentCommands } from '../src/model.js';

const catalog = { componentInitialUses: { component_015: 3 }, component: [{ id: 'component_008', initialEstimatedValue: 2 }],
  componentAppraisalEvents: {
    acquire: { component_007: 1, component_009: 4 }, recruit: { component_004: 3 },
    battle: { component_002: 2, component_006: 4 }, reveal: { component_003: 1 }, soilMove: { component_007: 2, component_009: 2 },
  } };
const before = () => ({ capacity: 8, items: [
  { instanceId: 'moss', componentId: 'component_007', estimatedValue: 5, remainingUses: null, routeCandidate: false },
  { instanceId: 'board', componentId: 'component_009', estimatedValue: 4, remainingUses: null, routeCandidate: false },
] });

test('moss brings three balls and grows existing components once per acquired item', () => {
  const box = before(), original = structuredClone(box);
  const draft = acquireDraft(box, { id: 'component_007', initialEstimatedValue: 5 }, catalog);
  assert.deepEqual(box, original);
  assert.equal(draft.items.length, 6);
  assert.equal(draft.items[0].estimatedValue, 9);
  assert.equal(draft.items[1].estimatedValue, 20);
  assert.equal(draft.items[2].estimatedValue, 5);
  assert.equal(draft.items.filter(row => row.componentId === 'component_008').length, 3);
  assert.equal(new Set(draft.items.map(row => row.instanceId)).size, 6);
  const commands = componentCommands(box, draft);
  assert.equal(commands.filter(row => row.type === 'componentAdd').length, 4);
  assert.ok(commands.filter(row => row.type === 'componentAdd').every(row => row.recordOnly));
});

test('full box permits the bundle and still grows moss and board', () => {
  const box = { ...before(), capacity: 5 }, old = structuredClone(box);
  const draft = acquireDraft(box, { id: 'component_007', initialEstimatedValue: 5 }, catalog);
  assert.equal(draft.capacity, 5);
  assert.equal(draft.items.length, 6);
  assert.equal(draft.items[0].estimatedValue, 9);
  assert.equal(draft.items[1].estimatedValue, 20);
  assert.deepEqual(box, old);
});

test('recruit button adds three per corn and board starts at eight', () => {
  const box = before();
  box.items.push({ instanceId: 'corn', componentId: 'component_004', estimatedValue: 4 });
  assert.equal(appraisalDraft(box, 'recruit', catalog).items[2].estimatedValue, 7);
  const draft = acquireDraft(box, { id: 'component_009', initialEstimatedValue: 8 }, catalog);
  assert.equal(draft.items.at(-1).estimatedValue, 8);
  assert.equal(draft.items[1].estimatedValue, 8);
});

test('ordinary processing item grows moss and board, but does not bundle balls', () => {
  const draft = acquireDraft(before(), { id: 'component_015', initialEstimatedValue: 1 }, catalog);
  assert.equal(draft.items.length, 3);
  assert.equal(draft.items[0].estimatedValue, 6);
  assert.equal(draft.items[1].estimatedValue, 8);
  assert.equal(draft.items[2].remainingUses, 3);
});

test('buttons use shared rules without filling unknown appraisal', () => {
  const box = before(); box.items[0].estimatedValue = null;
  const draft = appraisalDraft(box, 'soilMove', catalog);
  assert.equal(draft.items[0].estimatedValue, null);
  assert.equal(draft.items[1].estimatedValue, 6);
  assert.equal(box.items[1].estimatedValue, 4);
});

test('revealing a node grows all mist grass only and keeps unknown appraisal untouched', () => {
  const box = before();
  box.items.push(...[2, 9, null].map((value, index) => ({ instanceId: `mist-${index}`, componentId: 'component_003', estimatedValue: value })));
  const original = structuredClone(box);
  const draft = appraisalDraft(box, 'reveal', catalog);
  assert.deepEqual(draft.items.map(row => row.estimatedValue), [5, 4, 3, 10, null]);
  assert.deepEqual(box, original);
  const commands = componentCommands(box, draft);
  assert.equal(commands.length, 2);
  assert.ok(commands.every(row => row.type === 'componentUpdate' && row.instanceId.startsWith('mist-')));
});
