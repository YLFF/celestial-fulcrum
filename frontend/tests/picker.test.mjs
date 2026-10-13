import test from 'node:test';
import assert from 'node:assert/strict';
import { fuzzyMatch, operatorCandidates, SOURCE_CHOICES, sourceChoice } from '../src/picker.js';

test('operator candidates combine selected professions, rarity sorting and fuzzy matching', () => {
  const rows = [
    { name: '近卫甲', profession: '近卫', rarity: 4 },
    { name: '近卫乙', profession: '近卫', rarity: 6 },
    { name: '特种甲', profession: '特种', rarity: 6 },
    { name: '近卫丙', profession: '近卫', rarity: 6 },
    { name: '新干员临时占位', profession: null },
  ];
  const before = structuredClone(rows);
  assert.deepEqual(operatorCandidates(rows, ['近卫', '特种']).map(row => row.name),
    ['近卫乙', '特种甲', '近卫丙', '近卫甲', '新干员临时占位']);
  assert.deepEqual(operatorCandidates(rows, ['特种'], '甲').map(row => row.name), ['特种甲']);
  assert.deepEqual(operatorCandidates(rows, []).map(row => row.name),
    ['近卫乙', '特种甲', '近卫丙', '近卫甲', '新干员临时占位']);
  assert.deepEqual(operatorCandidates(rows, [], '甲').map(row => row.name), ['特种甲', '近卫甲']);
  assert.deepEqual(rows, before);
});

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
