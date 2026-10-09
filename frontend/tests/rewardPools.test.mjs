import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { rewardPoolsFor, visiblePoolItems, besidePopover } from '../src/rewardPools.js';
import { canEnchant, relicActive, relicGroups, enchantCommands, manualTrainingPromotion } from '../src/relicPresentation.js';

const entries = {
  relic_174: { name: '钝爪-新典训', enchantmentProfession: '先锋', displayOrder: 0, displayCategory: '专业工具' },
  relic_002: { displayOrder: 0, displayCategory: '斗争之物' },
  relic_003: { displayOrder: 0, displayCategory: '斗争之物' },
};
const pools = Object.fromEntries(['normal', 'advanced', 'autopsy', 'event', 'collectibles-f3', 'collectibles-f4', 'collectibles-all', 'new-training']
  .map(id => [id, { id, contextId: ['normal', 'advanced', 'autopsy', 'event'].includes(id) ? id : `node_battle_shop_merchant__${id}`, kind: 'relic', itemIds: ['relic_003', 'relic_002'] }]));
const catalog = { rewardBrowser: { pools, nodes: { node_type_007: ['normal', 'advanced'], node_type_004: ['collectibles-f3', 'collectibles-f4', 'collectibles-all', 'new-training'] },
  events: { encounter_009: ['event'] }, special: { ending3_autopsy: ['autopsy'] } } };

test('wish options stay separate, event and autopsy override ordinary category', () => {
  assert.deepEqual(rewardPoolsFor(catalog, { categoryId: 'node_type_007' }).map(row => row.id), ['normal', 'advanced']);
  assert.deepEqual(rewardPoolsFor(catalog, { categoryId: 'node_type_001', stage: '无效验尸' }).map(row => row.id), ['autopsy']);
  assert.deepEqual(rewardPoolsFor(catalog, { eventId: 'encounter_009' }).map(row => row.id), ['event']);
});
test('merchant pools use current layer, while new training remains visible', () => {
  assert.deepEqual(rewardPoolsFor(catalog, { categoryId: 'node_type_004' }, 'III').map(row => row.id), ['collectibles-f3', 'new-training']);
  assert.deepEqual(rewardPoolsFor(catalog, { categoryId: 'node_type_004' }, 'IV-remembrance').map(row => row.id), ['collectibles-f4', 'new-training']);
  assert.deepEqual(rewardPoolsFor(catalog, { categoryId: 'node_type_004' }, 'VI').map(row => row.id), ['collectibles-all', 'new-training']);
});
test('secret trader has one merged shelf pool per layer, never relics or cultivation results', () => {
  const local = { rewardBrowser: { pools: {
    regular: { id: 'regular', contextId: 'secret_trader_shelves', kind: 'component' },
    first: { id: 'first', contextId: 'secret_trader_shelves_f1', kind: 'component' },
  }, nodes: { node_type_013: ['regular', 'first'] } } };
  for (const [area, expected] of [['I', 'first'], ['II', 'regular'], ['IV-remembrance', 'regular'], ['III-treehole', 'regular'], ['', 'regular']]) {
    const result = rewardPoolsFor(local, { categoryId: 'node_type_013' }, area);
    assert.deepEqual(result.map(row => row.id), [expected]);
    assert.equal(result[0].kind, 'component');
  }
});
test('fruit mark pool can be queried separately or combined with its host without duplicates', () => {
  const local = structuredClone(catalog);
  local.rewardBrowser.marks = { node_mark_007: ['event'] };
  assert.deepEqual(rewardPoolsFor(local, { markIds: ['node_mark_007'] }).map(row => row.id), ['event']);
  assert.deepEqual(rewardPoolsFor(local, { categoryId: 'node_type_007', markIds: ['node_mark_007'] }).map(row => row.id), ['normal', 'advanced', 'event']);
  assert.deepEqual(rewardPoolsFor(local, { eventId: 'encounter_009', markIds: ['node_mark_007'] }).map(row => row.id), ['event']);
});
test('held relics excluded; components not excluded; input and probability not mutated', () => {
  const before = structuredClone(pools.normal);
  assert.deepEqual(visiblePoolItems(pools.normal, [{ id: 'relic_003' }], entries), [{ id: 'relic_002' }]);
  assert.deepEqual(pools.normal, before);
  assert.equal(visiblePoolItems({ ...pools.normal, kind: 'component' }, [{ id: 'relic_003' }], entries).length, 2);
});
test('enchantments require matching profession, unapplied relic, eligible operator', () => {
  const operator = { profession: '先锋', elite: 1, rarity: 6 };
  assert.equal(canEnchant({ id: 'relic_174' }, operator, entries), true);
  assert.equal(canEnchant({ id: 'relic_174', state: 'active' }, operator, entries), false);
  assert.equal(canEnchant({ id: 'relic_174' }, { ...operator, profession: '术师' }, entries), false);
  assert.equal(canEnchant({ id: 'relic_174' }, { ...operator, rarity: 3 }, entries), false);
  assert.equal(relicActive({ enchantment: { operatorInstanceId: 'x' } }), true);
  assert.deepEqual(enchantCommands({ relic_174: 'op1' }), [{ type: 'relicEnchant', relicId: 'relic_174', operatorInstanceId: 'op1' }]);
});
test('category order is configured and within category sorted by id; acquisition input unchanged', () => {
  const input = [{ id: 'relic_003' }, { id: 'relic_174' }, { id: 'relic_002' }];
  assert.deepEqual(relicGroups(input, entries, ['专业工具', '斗争之物']), [
    { name: '专业工具', items: [{ id: 'relic_174' }] }, { name: '斗争之物', items: [{ id: 'relic_002' }, { id: 'relic_003' }] },
  ]);
  assert.equal(input[0].id, 'relic_003');
});
test('training promotion is only detected after explicit operator stage change', () => {
  const previous = { instanceId: 'op1', elite: 1, profession: '先锋' };
  const relics = [{ id: 'relic_174', state: 'inactive' }];
  assert.equal(manualTrainingPromotion(previous, previous, relics, { relic_174: 'op1' }, entries), false);
  const next = { ...previous, elite: 2 };
  assert.equal(manualTrainingPromotion(previous, next, relics, { relic_174: 'op1' }, entries), true);
  assert.equal(manualTrainingPromotion(previous, next, relics, { relic_174: 'op2' }, entries), false);
  assert.equal(manualTrainingPromotion(next, next, relics, { relic_174: 'op1' }, entries), false);
  assert.equal(manualTrainingPromotion(previous, next, [{ ...relics[0], enchantment: { operatorInstanceId: 'op1' } }], {}, entries), true);
});
test('side panels use right when possible, then left, and stay within viewport', () => {
  assert.equal(besidePopover(100, 70, 386, 500, { width: 1200, height: 800 }).left, 494);
  assert.equal(besidePopover(800, 70, 386, 500, { width: 1200, height: 800 }).left, 406);
  const small = besidePopover(10, 70, 386, 500, { width: 360, height: 600 });
  assert.equal(small.width, 340);
  assert.ok(small.top + small.height <= 588);
});
test('completion review uses title green in both themes', () => {
  const css = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  assert.match(css, /merge-review-row[^\n]+color: #184e3d/);
  assert.match(css, /data-theme="dark"[^\n]+merge-review-row[^\n]+color: #ace1c8/);
});
