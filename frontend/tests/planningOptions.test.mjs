import assert from 'node:assert/strict';
import test from 'node:test';
import { searchOptionsError } from '../src/planningOptions.js';

test('planning defaults and boundary values remain valid', () => {
  for (const [topK, maxStates] of [[5, 50000], [1, 1], [50, 500000], [8, 10000]]) {
    assert.equal(searchOptionsError(topK, maxStates), null);
  }
});

test('invalid route counts cannot start a search', () => {
  for (const value of [0, -1, 51, 1.5, NaN, Infinity, null, '5']) {
    assert.match(searchOptionsError(value, 50000), /显示路线数量/);
  }
});

test('invalid state budgets cannot start a search', () => {
  for (const value of [0, -1, 500001, 1000.5, NaN, Infinity, null, '50000']) {
    assert.match(searchOptionsError(5, value), /路径搜索上限/);
  }
});
