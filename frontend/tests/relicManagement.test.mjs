import test from 'node:test';
import assert from 'node:assert/strict';
import { boundRecipients, canEnchant, enchantCommands, newestRelics, relicStatus, toggleRecipient } from '../src/relicPresentation.js';

const entries = {
  training: { management: { kind: 'one_shot', bindOperator: true, maxRecipients: 1, profession: '重装', promotionEffect: true } },
  cookie: { management: { kind: 'one_shot', bindOperator: true, maxRecipients: 2 } },
  aroma: { management: { kind: 'one_shot', bindOperator: true, maxRecipients: 1 } },
};
const operator = { instanceId: 'a', profession: '重装', rarity: 6, elite: 2 };

test('all confirmed bound relics allow already-promoted operators and multiple different buffs', () => {
  assert.equal(canEnchant({ id: 'training', state: 'active' }, operator, entries), false);
  assert.equal(canEnchant({ id: 'cookie' }, operator, entries), true);
  assert.equal(canEnchant({ id: 'aroma' }, operator, entries), true);
  assert.equal(canEnchant({ id: 'aroma' }, { ...operator, rarity: 3, elite: 1 }, entries), true);
  assert.equal(canEnchant({ id: 'training' }, { ...operator, remainingBattles: 1 }, entries), false);
  assert.equal(canEnchant({ id: 'training' }, { ...operator, profession: '辅助' }, entries), false);
});

test('training candidates resolve missing legacy identity from the operator catalog', () => {
  const catalog = [{ id: 'known', name: '旧存档干员', profession: '重装', rarity: 6 },
    { id: 'placeholder', name: '新干员临时占位', profession: null, rarity: 3, professionEditable: true, rarityEditable: true }];
  const legacy = { instanceId: 'legacy', name: '旧存档干员', profession: null, rarity: null, elite: 1 };
  assert.equal(canEnchant({ id: 'training' }, legacy, entries, catalog), true);
  assert.equal(canEnchant({ id: 'training' }, { ...legacy, name: '别名', operatorId: 'known' }, entries, catalog), true);
  assert.equal(canEnchant({ id: 'training' }, { ...legacy, profession: '辅助' }, entries, catalog), false);
  assert.equal(canEnchant({ id: 'training' }, { ...legacy, remainingBattles: 1 }, entries, catalog), false);
  assert.equal(canEnchant({ id: 'training' }, { ...legacy, name: '未知干员' }, entries, catalog), false);
  assert.equal(canEnchant({ id: 'training' }, { ...legacy, name: '新干员临时占位', profession: '重装' }, entries, catalog), false);
  assert.equal(canEnchant({ id: 'training' }, { ...legacy, name: '新干员临时占位', profession: '重装', rarity: 5 }, entries, catalog), true);
  assert.equal(legacy.profession, null);
  assert.equal(legacy.rarity, null);
});

test('cookie assignments produce one atomic two-recipient command without empty slots', () => {
  let values = toggleRecipient({}, 'cookie', 'a', true);
  values = toggleRecipient(values, 'cookie', 'b', true);
  assert.deepEqual(enchantCommands(values), [{ type: 'relicEnchant', relicId: 'cookie', operatorInstanceIds: ['a', 'b'] }]);
  assert.deepEqual(enchantCommands({ cookie: ['', 'b'], training: [] }), [{ type: 'relicEnchant', relicId: 'cookie', operatorInstanceId: 'b' }]);
  assert.deepEqual(toggleRecipient(values, 'cookie', 'a', false), { cookie: ['b'] });
  assert.deepEqual(boundRecipients({ enchantment: { recipients: [{ operatorInstanceId: 'a' }, { operatorInstanceId: 'b' }] } }).map(row => row.operatorInstanceId), ['a', 'b']);
});

test('editor reverses acquisition display without changing saved order or edit indexes', () => {
  const rows = [{ id: 'old' }, { id: 'middle' }, { id: 'new' }];
  assert.deepEqual(newestRelics(rows).map(({ row, index }) => [row.id, index]), [['new', 2], ['middle', 1], ['old', 0]]);
  assert.equal(rows[0].id, 'old');
});

test('ordinary, bound and computable counters do not expose manual fields', () => {
  const state = { currentAreaKey: 'II', resources: { originiumIngot: 24 }, componentBox: { items: [{}, {}, {}] }, areas: {} };
  assert.deepEqual(relicStatus({ id: 'plain' }, { management: { kind: 'ordinary' } }, state), { readOnly: true, kind: 'ordinary', label: '' });
  assert.deepEqual(relicStatus({ id: 'cookie' }, entries.cookie, state), { readOnly: true, label: '未生效' });
  assert.equal(relicStatus({ id: 'red', state: 99 }, { automaticCounter: 'snapshot', snapshotCounter: { field: 'componentCount' } }, state).label, '3 层');
  assert.equal(relicStatus({ id: 'gin', state: 99 }, { automaticCounter: 'snapshot', snapshotCounter: { field: 'cash', unitSize: 5 } }, state).label, '4 层');
  const dragon = { automaticCounter: 'entered_map_layers', management: { kind: 'stacking', ineffectiveAt: 3 } };
  assert.equal(relicStatus({ id: 'dragon', state: 99 }, dragon, state).label, '2 层');
  assert.equal(relicStatus({ id: 'dragon' }, dragon, { ...state, currentAreaKey: 'III' }).label, '3 层 · 已失效');
  assert.equal(relicStatus({ id: 'dragon' }, dragon, { ...state, currentAreaKey: null }).label, '待确认 层');
  assert.equal(relicStatus({ id: 'altar', state: 4 }, { management: { kind: 'stacking' } }, state).readOnly, false);
});
