import test from 'node:test';
import assert from 'node:assert/strict';
import { adviceMapRoute, filterAdvice, policyName } from '../src/advicePresentation.js';

const suggestions = [
  { id: 'a', firstStep: { from: '0,0', entered: '1,0' }, relatedGoalIds: ['a'], lookaheadPoints: 4 },
  { id: 'b', random: true, relatedGoalIds: ['a', 'b'], branches: [{ firstStep: { entered: '2,0' } }] },
  { id: 'c', firstStep: { entered: '3,0' }, relatedGoalIds: ['b'], lookaheadPoints: 100 },
];
test('preserves policy representatives rather than re-sorting by raw income', () => {
  assert.deepEqual(filterAdvice({ suggestions }, [], 'all', 2).map(row => row.id), ['a', 'b']);
});
test('all/any priority filters include random and alternative suggestions', () => {
  assert.deepEqual(filterAdvice({ suggestions }, ['a', 'b']).map(row => row.id), ['b']);
  assert.equal(filterAdvice({ suggestions }, ['a', 'b'], 'any').length, 3);
  assert.equal(filterAdvice(null).length, 0);
});
test('only the first step is drawn, never a fictitious random landing', () => {
  assert.deepEqual(adviceMapRoute(suggestions[0]), { steps: [suggestions[0].firstStep] });
  assert.equal(adviceMapRoute(suggestions[1]), null);
  assert.equal(adviceMapRoute(null), null);
});
test('goal continuation labels come from selected goals', () => {
  assert.equal(policyName('goal:a', [{ id: 'a', name: '线人' }]), '线人');
  assert.equal(policyName('income', []), '发育方向');
});
