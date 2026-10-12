import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { orderedOperatorRoster } from '../frontend/src/model.js';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const out = 'work/ui_inventory_updates';
await mkdir(out, { recursive: true });
const token = (await (await fetch(base + '/api/session')).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  assert.ok(response.ok, JSON.stringify(data));
  return data;
}
const sourcePath = 'runs/true-run-001/playtime.json';
const original = await readFile(sourcePath, 'utf8');
const seed = JSON.parse(original), runId = `ui-inventory-updates-${Date.now().toString(36)}`;
seed.componentBox = { capacity: 12, items: [
  { instanceId: 'mist-a', componentId: 'component_003', estimatedValue: 2, remainingUses: null, routeCandidate: false },
  { instanceId: 'mist-b', componentId: 'component_003', estimatedValue: 9, remainingUses: null, routeCandidate: false },
  { instanceId: 'corn-a', componentId: 'component_004', estimatedValue: 3, remainingUses: null, routeCandidate: false },
] };
seed.resources.totalEstimatedValue = 14;
const slot = seed.areas[seed.currentAreaKey];
const instance = slot.instances.find(row => row.instanceId === slot.activeInstanceId);
instance.strategy.scoringOptions ??= {};
delete instance.strategy.scoringOptions.merchantReserve;
await api('/api/runs/restore', { state: seed, runId });
const state = () => api(`/api/runs/${runId}`, null, 'GET');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
const dialog = () => page.getByRole('dialog');
const ready = () => page.waitForFunction(id => document.querySelector('.run-select')?.value === id && !document.querySelector('input[aria-label="上传地图截图"]')?.disabled, runId);
async function save() { await dialog().getByRole('button', { name: '保存', exact: true }).click(); await dialog().waitFor({ state: 'hidden' }); await ready(); }
async function check(name, fn) { await fn(); checks.push(name); console.log(name); }
const placeholderRows = () => dialog().locator('.operator-edit-row').filter({ has: page.locator('input[value="新干员临时占位"]') });
try {
  await page.goto(base); await ready();
  await check('reserve defaults to zero and explicit saved amounts survive reload', async () => {
    const reserve = page.getByLabel('路线规划预留源石锭', { exact: true });
    assert.equal(await reserve.inputValue(), '0');
    await reserve.fill('30');
    await page.getByRole('button', { name: '保存路线规划预留源石锭并重新评分', exact: true }).click();
    await ready();
    const saved = (await state()).state.areas[seed.currentAreaKey];
    assert.equal(saved.instances.find(row => row.instanceId === saved.activeInstanceId).strategy.scoringOptions.merchantReserve, 30);
    await page.reload(); await ready();
    assert.equal(await reserve.inputValue(), '30');
  });
  await check('reveal button precedes soil movement and saves one point per mist grass per click', async () => {
    await page.getByRole('button', { name: '编辑零件箱', exact: true }).click();
    const actions = await dialog().locator('.appraisal-actions button').allTextContents();
    assert.equal(actions.indexOf('揭示节点+1') + 1, actions.indexOf('沃土移动+1'));
    await dialog().getByRole('button', { name: '揭示节点+1', exact: true }).click();
    await dialog().getByRole('button', { name: '揭示节点+1', exact: true }).click();
    await page.screenshot({ path: `${out}/appraisal.png`, fullPage: true });
    await save();
    const saved = (await state()).state;
    assert.deepEqual(saved.componentBox.items.map(row => row.estimatedValue), [4, 11, 3]);
    assert.equal(saved.resources.totalEstimatedValue, 18);
  });
  await check('two placeholders save independent rarity and profession and remain editable after reopening', async () => {
    await page.getByRole('button', { name: '添加干员与编队', exact: true }).click();
    await dialog().getByLabel('搜索名称', { exact: true }).fill('临时占');
    const add = dialog().getByRole('button', { name: '选择 新干员临时占位', exact: true });
    await add.click(); await add.click();
    const rows = placeholderRows();
    assert.equal(await rows.count(), 2);
    const values = [[6, '近卫'], [5, '医疗']];
    for (let i = 0; i < 2; i++) {
      assert.ok(await rows.nth(i).getByLabel('星级', { exact: true }).isEditable());
      await rows.nth(i).getByLabel('星级', { exact: true }).fill(String(values[i][0]));
      await rows.nth(i).getByLabel('职业', { exact: true }).selectOption(values[i][1]);
    }
    await save();
    const getPlaceholders = async () => (await state()).state.operators.filter(row => row.name === '新干员临时占位');
    const added = await getPlaceholders();
    assert.deepEqual(added.map(row => [row.rarity, row.profession]), values);
    assert.notEqual(added[0].instanceId, added[1].instanceId);
    await page.getByRole('button', { name: '编辑干员与编队', exact: true }).click();
    for (let i = 0; i < 2; i++) assert.equal(await placeholderRows().nth(i).getByLabel('星级', { exact: true }).inputValue(), String(values[1 - i][0]));
    await page.screenshot({ path: `${out}/placeholders.png`, fullPage: true });
    await placeholderRows().nth(0).getByLabel('星级', { exact: true }).fill('4');
    await placeholderRows().nth(0).getByLabel('职业', { exact: true }).selectOption('先锋');
    await save();
    assert.deepEqual((await getPlaceholders()).map(row => [row.rarity, row.profession]), [[6, '近卫'], [4, '先锋']]);
  });
  await check('squad-first order is applied only on opening and never rewrites acquisition order', async () => {
    const before = (await state()).state;
    const expected = orderedOperatorRoster(before.operators, before.squad);
    await page.getByRole('button', { name: '编辑干员与编队', exact: true }).click();
    const names = () => dialog().locator('.operator-edit-row input:not([type])').evaluateAll(inputs => inputs.map(input => input.value));
    assert.deepEqual(await names(), expected.map(row => row.name));
    const selectedRows = dialog().locator('.operator-edit-row').locator('input[type="checkbox"]');
    for (let i = 0; i < expected.length; i++) assert.equal(await selectedRows.nth(i).isChecked(), before.squad.includes(expected[i].instanceId));
    await selectedRows.nth(expected.length - 1).setChecked(!before.squad.includes(expected.at(-1).instanceId));
    assert.deepEqual(await names(), expected.map(row => row.name));
    await save();
    const saved = (await state()).state;
    assert.deepEqual(saved.operators.map(row => row.instanceId), before.operators.map(row => row.instanceId));
    await page.getByRole('button', { name: '编辑干员与编队', exact: true }).click();
    assert.deepEqual(await names(), orderedOperatorRoster(saved.operators, saved.squad).map(row => row.name));
    await page.screenshot({ path: `${out}/squad-order.png`, fullPage: true });
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
  });
  await check('new PRTS operators can be found by name and code within profession filters', async () => {
    await page.getByRole('button', { name: '添加干员与编队', exact: true }).click();
    for (const [name, code, profession] of [['克莱门莎', 'AE01', '近卫'], ['旅骨', 'II12', '特种'], ['德·托莱多', 'II13', '辅助']]) {
      await dialog().getByLabel('筛选职业', { exact: true }).selectOption(profession);
      for (const query of [name, code]) {
        await dialog().getByLabel('搜索名称', { exact: true }).fill(query);
        assert.ok(await dialog().getByRole('button', { name: `选择 ${name}`, exact: true }).isVisible());
      }
    }
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
  });
  assert.equal(await readFile(sourcePath, 'utf8'), original);
  assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  await writeFile(`${out}/failure.json`, JSON.stringify({ error: error.stack, body: await page.locator('body').innerText() }, null, 2));
  throw error;
} finally {
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, checks, errors }, null, 2));
  await browser.close();
}
