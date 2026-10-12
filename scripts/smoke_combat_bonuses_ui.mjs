import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8769';
const out = resolve('work/ui_combat_bonuses');
await mkdir(out, { recursive: true });
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  assert.ok(response.ok, JSON.stringify(data));
  return data;
}
const catalog = await api('/api/catalog', null, 'GET');
const seed = JSON.parse(await readFile(resolve('runs/true-run-001/playtime.json'), 'utf8'));
const sample = JSON.parse(await readFile(resolve('samples/combat_bonuses/n15_floor2.json'), 'utf8'));
const runId = `ui-combat-${Date.now().toString(36)}`;
seed.operators = sample.state.operators.map(row => {
  const entry = catalog.operators.find(item => item.id === row.operatorId);
  return { ...row, profession: entry.profession, rarity: entry.rarity, elite: 1, initialRecruitment: true, remainingBattles: null };
});
seed.squad = ['mechanist', 'angelina'];
seed.resources.originiumIngot = 14;
seed.componentBox.items = Array.from({ length: 8 }, (_, index) => ({ instanceId: `sample-${index}`, componentId: 'component_001',
  estimatedValue: 2, remainingUses: null, routeCandidate: false }));
seed.relics = ['199', '052', '051', '192', '130', '077', '060', '220'].map(id => ({ id: `relic_${id}`, count: 1, state: null }));
seed.relics.push({ id: 'relic_180', count: 1, state: 'active', enchantment: {
  operatorInstanceId: 'angelina', operatorName: '予愿安洁莉娜', profession: seed.operators.find(row => row.instanceId === 'angelina').profession,
} });
const instance = seed.areas.I.instances.find(item => item.instanceId === seed.areas.I.activeInstanceId);
instance.dystopia = { active: true, ideologyId: 'dystopia_001', policyId: 'dystopia_014',
  affectedNodeIds: Object.keys(instance.nodes), uncertainNodeIds: [], idealSourceNodeId: null };
await api('/api/runs/restore', { runId, state: seed });
const before = await api(`/api/runs/${runId}`, null, 'GET');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
const dialog = () => page.getByRole('dialog');
async function cell(metric, domain, expected) {
  assert.equal(await dialog().locator(`[data-combat-metric="${metric}-${domain}"]`).innerText(), expected);
}
async function verifyLayout() {
  const result = await dialog().evaluate(element => {
    const body = element.querySelector('.modal-body');
    const close = element.querySelector('header button').getBoundingClientRect();
    return { overflow: body.scrollWidth - body.clientWidth, closeBottom: close.bottom, height: innerHeight,
      metricCount: element.querySelectorAll('[data-combat-metric]').length };
  });
  assert.ok(result.overflow <= 1, JSON.stringify(result));
  assert.ok(result.closeBottom <= result.height);
  assert.equal(result.metricCount, 6);
}
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  await page.getByRole('button', { name: '加成汇总', exact: true }).click();
  await dialog().locator('.combat-attributes').waitFor();
  await cell('max_hp', 'outside_battle', '+25%');
  await cell('max_hp', 'inside_battle', '+64%');
  await cell('attack', 'outside_battle', '+20%');
  await cell('attack', 'inside_battle', '+64%');
  await cell('attack_speed', 'outside_battle', '+14 点');
  await cell('attack_speed', 'inside_battle', '+0 点');
  assert.ok((await dialog().locator('.combat-environment').innerText()).includes('+30%'));
  assert.equal(await dialog().locator('.combat-category[open]').count(), 0);
  const order = await dialog().locator('.combat-category').evaluateAll(elements => elements.map(element => element.dataset.combatCategory));
  assert.deepEqual(order, ['survival', 'damage', 'cost', 'skill_cycle', 'control', 'mechanism', 'support']);
  await verifyLayout();
  await page.screenshot({ path: resolve(out, 'global-desktop.png') });
  checks.push('global six values and separate N15 environment');
  await dialog().locator('[data-combat-category="damage"] > summary').click();
  assert.equal(await dialog().locator('.combat-source-list:visible').count(), 0);
  const indicator = dialog().locator('[data-combat-category="damage"] .combat-indicator').filter({ hasText: '攻击力' }).filter({ hasText: '我方全体单位 · 局外' });
  await indicator.locator(':scope > summary').click();
  await indicator.getByText('局外科技', { exact: true }).waitFor();
  const compact = await indicator.locator('.combat-indicator-heading').evaluate(element => {
    const metric = element.querySelector('b').getBoundingClientRect();
    const scope = element.querySelector('small').getBoundingClientRect();
    return scope.top < metric.bottom && scope.bottom > metric.top;
  });
  assert.ok(compact, 'desktop metric and scope should share one line');
  await page.screenshot({ path: resolve(out, 'global-details.png') });
  checks.push('category then indicator expands sources');
  const melee = dialog().locator('[data-combat-category="damage"] .combat-indicator')
    .filter({ hasText: '攻击力' }).filter({ hasText: '部署位：近战 · 局外' });
  assert.equal(await melee.locator('.combat-indicator-value > b').innerText(), '+60%');
  await melee.locator(':scope > summary').click();
  await melee.getByText('老近卫军之锋', { exact: true }).waitFor();
  await melee.getByText('贵族刺剑', { exact: true }).waitFor();
  await cell('attack', 'outside_battle', '+20%');
  await page.screenshot({ path: resolve(out, 'global-scoped-details.png') });
  checks.push('compact row, scoped relics visible, universal header unchanged');
  await dialog().getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '编辑干员与编队', exact: true }).click();
  const firstName = dialog().locator('input[value="机械师"]');
  await firstName.fill('机械师（草稿）');
  await dialog().getByRole('button', { name: '查看 机械师（草稿） 加成（已保存状态）', exact: true }).click();
  await dialog().locator('.combat-attributes').waitFor();
  await cell('attack', 'outside_battle', '+80%');
  await cell('attack', 'inside_battle', '+64%');
  await page.screenshot({ path: resolve(out, 'operator-desktop.png') });
  await page.keyboard.press('Escape');
  assert.equal(await dialog().locator('input[value="机械师（草稿）"]').count(), 1);
  await dialog().getByRole('button', { name: '查看 予愿安洁莉娜 加成（已保存状态）', exact: true }).click();
  await dialog().locator('.combat-attributes').waitFor();
  await cell('attack', 'outside_battle', '+80%');
  await dialog().locator('[data-combat-category="mechanism"] > summary').click();
  await dialog().locator('[data-combat-category="mechanism"] .combat-indicator').filter({ hasText: '再部署时间' }).locator(':scope > summary').click();
  await dialog().getByText('锈刃-新典训', { exact: true }).waitFor();
  await page.screenshot({ path: resolve(out, 'operator-enchantment.png') });
  checks.push('operator entry, scoped 80%, enchantment, draft preservation and Escape');
  await page.keyboard.press('Escape');
  await dialog().getByRole('button', { name: '关闭', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '加成汇总', exact: true }).click();
  await dialog().locator('.combat-attributes').waitFor();
  await verifyLayout();
  await page.screenshot({ path: resolve(out, 'global-mobile-dark.png') });
  await dialog().locator('[data-combat-category="damage"] > summary').click();
  await dialog().locator('[data-combat-category="damage"] .combat-indicator').first().locator(':scope > summary').click();
  await verifyLayout();
  await page.screenshot({ path: resolve(out, 'details-mobile-dark.png') });
  await dialog().getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '切换到明亮模式', exact: true }).click();
  await page.getByRole('button', { name: '加成汇总', exact: true }).click();
  await dialog().locator('.combat-attributes').waitFor();
  await verifyLayout();
  await page.screenshot({ path: resolve(out, 'global-mobile-light.png') });
  checks.push('desktop/mobile, light/dark, no horizontal overflow');
  await dialog().getByRole('button', { name: '关闭', exact: true }).click();
  let firstRequest = true;
  await page.route('**/api/runs/*/combat-bonuses', async route => {
    if (firstRequest) {
      firstRequest = false;
      await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '修订已更新' }) });
    } else await route.continue();
  });
  await page.getByRole('button', { name: '加成汇总', exact: true }).click();
  await dialog().getByRole('alert').waitFor();
  assert.equal(await dialog().locator('[data-combat-metric]').count(), 0);
  await dialog().getByRole('button', { name: '刷新计算', exact: true }).click();
  await dialog().locator('.combat-attributes').waitFor();
  await cell('attack', 'outside_battle', '+20%');
  checks.push('stale revision hides numeric results and supports retry');
  const after = await api(`/api/runs/${runId}`, null, 'GET');
  assert.deepEqual(after, before);
  assert.deepEqual(errors, []);
  checks.push('read-only revision and state unchanged');
  await writeFile(resolve(out, 'result.json'), JSON.stringify({ runId, checks, errors, base }, null, 2));
  console.log(JSON.stringify({ success: true, runId, checks, out }));
} finally {
  await browser.close();
}
