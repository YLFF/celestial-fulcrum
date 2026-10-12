import test from 'node:test';
import assert from 'node:assert/strict';
import { componentAppraisalTotal, routeNodeName } from '../src/model.js';

const labels = { node_type_001: '作战', node_type_004: '诡意行商', unknown_mystery: '未知的诡秘' };

test('route labels use the confirmed type before the observed type and keep unknowns unknown', () => {
  const nodes = {
    '1,0': { observedCategoryId: 'node_type_001' },
    '2,0': { observedCategoryId: 'unknown_mystery', resolvedCategoryId: 'node_type_004' },
    '3,0': { observedCategoryId: 'unknown_mystery' },
    '0,0': { observedCategoryId: 'start' },
  };
  assert.equal(routeNodeName('1,0', nodes, labels), '作战');
  assert.equal(routeNodeName('2,0', nodes, labels), '诡意行商');
  assert.equal(routeNodeName('3,0', nodes, labels), '未知的诡秘');
  assert.equal(routeNodeName('0,0', nodes, labels), '起点');
});

test('missing categories and positions are not guessed from coordinate IDs', () => {
  assert.equal(routeNodeName('1,0', { '1,0': {} }, labels), '未确认节点');
  assert.equal(routeNodeName('9,9', {}, labels), '未确认节点');
  assert.equal(routeNodeName('0,0'), '未确认节点');
});

test('box appraisal sums every component kind, preserves zero, and does not invent unknown values', () => {
  const rows = [{ estimatedValue: 8 }, { estimatedValue: 3 }, { estimatedValue: 0 }, { estimatedValue: null }, {}];
  const before = structuredClone(rows);
  assert.equal(componentAppraisalTotal(rows), 11);
  assert.deepEqual(rows, before);
  rows[0].estimatedValue = 12;
  assert.equal(componentAppraisalTotal(rows), 15);
  assert.equal(componentAppraisalTotal([]), 0);
});
