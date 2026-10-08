import test from 'node:test';
import assert from 'node:assert/strict';
import { fuzzyMatch, SOURCE_CHOICES, sourceChoice } from '../src/picker.js';

test('Chinese subsequence search and normalized English codes', () => {
  assert.equal(fuzzyMatch({ name: '结构性原理' }, '结构原理'), true);
  assert.equal(fuzzyMatch({ name: '予愿安洁莉娜' }, '予愿安'), true);
  assert.equal(fuzzyMatch({ englishName: "Wiš'adel" }, 'WIS ADEL'), true);
  assert.equal(fuzzyMatch({ code: 'RE21' }, 're2'), true);
  assert.equal(fuzzyMatch({ name: '机械师' }, '芬'), false);
});
test('only three editable sources while legacy sources remain readable', () => {
  assert.equal(Object.keys(SOURCE_CHOICES).length, 3);
  assert.equal(sourceChoice('emergency'), 'assistance');
  assert.equal(sourceChoice('squad_002-temporary'), 'temporary');
});
