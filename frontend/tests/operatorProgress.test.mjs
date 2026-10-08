import test from 'node:test';
import assert from 'node:assert/strict';
import { operatorProgressLabel, operatorProgressOptions } from '../src/model.js';

test('both unpromoted storage values have one visible status', () => {
  assert.equal(operatorProgressLabel(0), '未进阶');
  assert.equal(operatorProgressLabel(1), '未进阶');
  assert.equal(operatorProgressLabel(2), '已进阶');
  assert.equal(operatorProgressLabel(null), '待确认');
});

test('progress choices respect rarity without a separate E0 choice', () => {
  assert.deepEqual(operatorProgressOptions(2, 0), [0]);
  assert.deepEqual(operatorProgressOptions(3, 1), [1]);
  assert.deepEqual(operatorProgressOptions(6, 1), [1, 2]);
  assert.deepEqual(operatorProgressOptions(6, 2), [1, 2]);
  assert.deepEqual(operatorProgressOptions(null, null), [1, 2]);
});

test('existing E0 records remain editable without silently changing storage', () => {
  assert.deepEqual(operatorProgressOptions(6, 0), [0, 2]);
  assert.deepEqual(operatorProgressOptions(3, 2), [1, 2]);
});
