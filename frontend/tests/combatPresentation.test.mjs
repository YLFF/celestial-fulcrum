import assert from 'node:assert/strict';
import { test } from 'node:test';
import { COMBAT_CATEGORY_ORDER, attributeValue, indicatorGroups } from '../src/combatPresentation.js';

test('six metric formatting keeps fixed points separate from percentages', () => {
  assert.equal(attributeValue({ metric: 'attack', flatDelta: '0', relativePercent: '80' }), '+80%');
  assert.equal(attributeValue({ metric: 'attack_speed', flatDelta: '14', relativePercent: '0' }), '+14 点');
  assert.equal(attributeValue({ metric: 'max_hp', flatDelta: '20', relativePercent: '25' }), '+20 点 / +25%');
  assert.equal(attributeValue({ metric: 'attack', flatDelta: '0', relativePercent: '-10' }), '-10%');
  assert.equal(attributeValue({ metric: 'attack', flatDelta: '0', relativePercent: '0' }), '+0%');
  assert.equal(attributeValue({ status: 'partial', sources: [], flatDelta: '0', relativePercent: '0' }), '待确认');
});

test('different conditions for the same indicator stay nested, not summed', () => {
  const base = { metric: 'attack', metricLabel: '攻击力', domain: 'inside_battle', domainLabel: '局内',
    side: 'operator', sideLabel: '该干员', tags: {}, strategy: 'numeric', flatDelta: '0' };
  const rows = [
    { ...base, bucket: 'constant', relativePercent: '10', sources: [{ id: 'a' }] },
    { ...base, bucket: 'conditional', relativePercent: '150', conditions: [{ description: '开启技能' }], sources: [{ id: 'b' }] },
    { ...base, bucket: 'conditional', relativePercent: '50', conditions: [{ description: '起飞' }], sources: [{ id: 'c' }] },
  ];
  const groups = indicatorGroups(rows);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].preview, '+10%');
  assert.equal(groups[0].additionalCount, 2);
  assert.equal(groups[0].rows.length, 3);
  assert.ok(!groups[0].preview.includes('210'));
  assert.equal(indicatorGroups([...rows, { ...rows[0], side: 'enemy' }]).length, 2);
});

test('known inventory snapshots display current values, unresolved counts are not zeroed', () => {
  const row = { metric: 'attack', metricLabel: '攻击力', tags: {}, strategy: 'numeric', bucket: 'conditional',
    flatDelta: '0', relativePercent: '64', sources: [{ id: 'red', resolvedFrom: 'snapshot_count' }] };
  assert.equal(indicatorGroups([row])[0].preview, '+64%');
  assert.equal(indicatorGroups([{ ...row, strategy: 'describe', bucket: 'unresolved' }])[0].preview, '待确认');
});

test('mechanisms appear before support items', () => {
  assert.ok(COMBAT_CATEGORY_ORDER.indexOf('mechanism') < COMBAT_CATEGORY_ORDER.indexOf('support'));
});

test('overview scopes are separate, sorted broad to narrow within an indicator', () => {
  const base = { category: 'damage', metric: 'attack', metricLabel: '攻击力', domain: 'outside_battle',
    domainLabel: '局外', side: 'friendly_operator', tags: {}, strategy: 'numeric', flatDelta: '0',
    bucket: 'constant', sources: [{ id: 'test' }] };
  const groups = indicatorGroups([
    { ...base, displayScope: { subprofessions: ['炮手'] }, scopeLabel: '炮手', scopeBreadth: 30, relativePercent: '40' },
    { ...base, displayScope: { profession: '近卫' }, scopeLabel: '近卫', scopeBreadth: 20, relativePercent: '20' },
    { ...base, displayScope: { position: 'melee' }, scopeLabel: '近战', scopeBreadth: 10, relativePercent: '60' },
    { ...base, displayScope: {}, scopeLabel: '我方全体干员', scopeBreadth: 1, relativePercent: '30' },
  ]);
  assert.equal(groups.length, 4);
  assert.deepEqual(groups.map(group => group.side), ['我方全体干员', '近战', '近卫', '炮手']);
  assert.deepEqual(groups.map(group => group.preview), ['+30%', '+60%', '+20%', '+40%']);
  assert.ok(groups.every(group => group.section === '攻击与攻速'));
});

test('survival prioritizes HP and enemy output before recovery, defense and resistance', () => {
  const metrics = ['resistance', 'hp_recovery', 'defense', 'barrier', 'attack', 'max_hp'];
  const groups = indicatorGroups(metrics.map(metric => ({ category: 'survival', metric, tags: {},
    side: metric === 'attack' ? 'enemy' : 'friendly_unit', bucket: 'conditional', sources: [{ id: metric }] })));
  assert.deepEqual(groups.map(group => group.metric), ['max_hp', 'attack', 'barrier', 'hp_recovery', 'defense', 'resistance']);
  assert.equal(groups[0].section, '生命与敌方输出');
  assert.equal(groups[3].section, '恢复效果');
  assert.equal(groups[4].section, '防御与抗性');
});
