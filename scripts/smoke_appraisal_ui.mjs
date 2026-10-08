import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const sourcePath = resolve('runs/true-run-001/playtime.json'), original = await readFile(sourcePath, 'utf8');
const out = resolve('work/ui_appraisal'); await mkdir(out, { recursive: true });
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json(); assert.ok(response.ok, JSON.stringify(data)); return data;
}
const runId = `ui-appraisal-${Date.now().toString(36)}`;
const seed = JSON.parse(original);
seed.componentBox = { capacity: 31, items: Array.from({ length: 30 }, (_, i) => ({ instanceId: `sample-${i + 1}`, componentId: `component_${String(i + 1).padStart(3, '0')}`, estimatedValue: 10,
  remainingUses: i >= 12 && i <= 23 ? 1 : null, routeCandidate: i >= 12 && i <= 23 })) };
seed.resources.totalEstimatedValue = 300;
seed.relics = Array.from({ length: 15 }, (_, i) => ({ id: `relic_${String(i + 1).padStart(3, '0')}`, count: 1 }));
const catalog = await api('/api/catalog', null, 'GET');
const extraOps = catalog.operators.filter(row => !seed.operators.some(op => op.name === row.name)).slice(0, 9);
seed.operators.push(...extraOps.map((row, i) => ({ instanceId: `preview-op-${i}`, name: row.name, profession: row.profession, rarity: row.rarity, elite: 1, source: 'normal', remainingBattles: null })));
await api('/api/runs/restore', { state: seed, runId });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
const errors = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
const current = () => api(`/api/runs/${runId}`, null, 'GET');
const dialog = () => page.getByRole('dialog');
const save = async () => { await dialog().getByRole('button', { name: '保存', exact: true }).click(); await dialog().waitFor({ state: 'hidden' }); };
const ready = () => page.waitForFunction(id => document.querySelector('.run-select')?.value === id && !document.querySelector('input[aria-label="上传地图截图"]')?.disabled, runId);
async function check(name, callback) { await callback(); checks.push(name); console.log(name); }
const value = (state, id) => state.componentBox.items.find(row => row.componentId === id).estimatedValue;
try {
  await page.goto(base); await ready();
  await check('three inventory rows preserve every item and center unknown icons', async () => {
    assert.equal(await page.locator('.inventory-section').nth(0).locator('.inventory-token').count(), 15);
    assert.equal(await page.locator('.component-inventory-row').count(), 3);
    assert.equal(await page.locator('.component-inventory-row .inventory-token').count(), 30);
    assert.equal(await page.locator('.operator-strip button').count(), seed.operators.length);
    for (const box of await page.locator('.inventory-content').all()) assert.ok((await box.boundingBox()).height >= 130);
    const relics = await page.locator('.relic-inventory .inventory-token').all();
    const first = await relics[0].boundingBox(), second = await relics[1].boundingBox();
    assert.equal(first.y, second.y); assert.ok(second.x > first.x);
    await page.waitForFunction(() => [...document.querySelectorAll('.unknown-icon')].every(el => el.complete && el.naturalWidth));
    const aligned = await page.locator('.unknown-icon').evaluateAll(rows => rows.every(el => {
      const image = el.getBoundingClientRect(), disc = el.parentElement.getBoundingClientRect();
      return Math.abs(image.y + image.height / 2 - disc.y - disc.height / 2) < 1;
    }));
    assert.ok(aligned);
    await page.screenshot({ path: `${out}/inventory-dark.png`, fullPage: true });
  });
  await check('threshold panel sits between event pool and memo; judgement saves without roster mutation', async () => {
    const headings = await page.locator('.sidebar-toggle h3').allTextContents();
    assert.ok(headings.indexOf('不期而遇池') < headings.indexOf('战力门槛') && headings.indexOf('战力门槛') < headings.indexOf('本局备忘'));
    for (const [label, override, met] of [['强制不够', 'insufficient', false], ['强制够', 'enough', true], ['自动', 'auto', true]]) {
      await page.getByRole('button', { name: label, exact: true }).click();
      await page.waitForFunction(label => document.querySelector(`[aria-label="战力判定"] button[aria-pressed="true"]`)?.textContent === label, label);
      const loaded = await current(); assert.equal(loaded.teamThresholds.I.override, override); assert.equal(loaded.teamThresholds.I.met, met);
      assert.deepEqual(loaded.state.operators, seed.operators);
    }
  });
  await check('moss bundle updates draft and save exactly once', async () => {
    const before = (await current()).state;
    await page.getByRole('button', { name: '添加零件箱', exact: true }).click();
    await dialog().getByLabel('搜索名称', { exact: true }).fill('多生苔藓');
    await dialog().getByRole('button', { name: '选择 多生苔藓', exact: true }).click();
    assert.equal(await dialog().locator('.component-edit-row').count(), before.componentBox.items.length + 4);
    await save(); await ready(); const after = (await current()).state;
    assert.equal(after.componentBox.items.length, before.componentBox.items.length + 4);
    assert.equal(value(after, 'component_007'), value(before, 'component_007') + 4);
    assert.equal(value(after, 'component_009'), value(before, 'component_009') + 16);
    const newMoss = after.componentBox.items.find(row => row.componentId === 'component_007' && row.instanceId !== 'sample-7');
    assert.equal(newMoss.estimatedValue, 5);
    assert.equal(after.componentBox.items.filter(row => row.componentId === 'component_008').length, 4);
    await page.locator('.capacity-warning').waitFor();
    assert.match(await page.locator('.capacity-warning').innerText(), /超限 3 件/);
    assert.equal(await page.locator('.capacity-warning').evaluate(el => getComputedStyle(el).color), 'rgb(239, 170, 164)');
    await page.screenshot({ path: `${out}/overflow-dark.png`, fullPage: true });
  });
  await check('four appraisal buttons target correct items and can be cancelled', async () => {
    const before = await current();
    await page.getByRole('button', { name: '编辑零件箱', exact: true }).click();
    for (const name of ['招募干员+1', '战斗胜利+1', '获得零件+1', '沃土移动+1']) await dialog().getByRole('button', { name, exact: true }).click();
    await page.screenshot({ path: `${out}/appraisal-buttons-dark.png`, fullPage: true });
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
    assert.equal((await current()).revision, before.revision);
    await page.getByRole('button', { name: '编辑零件箱', exact: true }).click();
    for (const name of ['招募干员+1', '战斗胜利+1', '获得零件+1', '沃土移动+1']) await dialog().getByRole('button', { name, exact: true }).click();
    await save(); await ready(); const after = (await current()).state;
    const deltas = { component_004: 5, component_002: 4, component_006: 6, component_007: 3, component_009: 6, component_015: 0, component_025: 0 };
    for (const [id, delta] of Object.entries(deltas)) assert.equal(value(after, id) - value(before.state, id), delta);
  });
  await check('tree removal requires confirmation and leaves other parts intact', async () => {
    const before = (await current()).state;
    await page.getByRole('button', { name: '编辑零件箱', exact: true }).click();
    await dialog().getByRole('button', { name: '我树碎了？！', exact: true }).click();
    await page.getByRole('alertdialog').getByRole('button', { name: '取消', exact: true }).click();
    assert.equal(await dialog().locator('.component-edit-row').count(), before.componentBox.items.length);
    await dialog().getByRole('button', { name: '我树碎了？！', exact: true }).click();
    await page.screenshot({ path: `${out}/tree-confirm-dark.png`, fullPage: true });
    await page.getByRole('alertdialog').getByRole('button', { name: '确认移除', exact: true }).click();
    await save(); await ready(); const after = (await current()).state;
    assert.deepEqual(after.componentBox.items, before.componentBox.items.filter(row => row.componentId !== 'component_006'));
  });
  await check('new roster entry and edits leave corn unchanged', async () => {
    const before = (await current()).state;
    const entry = catalog.operators.find(row => !before.operators.some(op => op.name === row.name));
    await page.getByRole('button', { name: '添加干员与编队', exact: true }).click();
    await dialog().getByLabel('搜索名称', { exact: true }).fill(entry.name);
    await dialog().getByRole('button', { name: `选择 ${entry.name}`, exact: true }).click();
    await save(); await ready(); const after = (await current()).state;
    assert.equal(value(after, 'component_004'), value(before, 'component_004'));
    await page.getByRole('button', { name: '编辑干员与编队', exact: true }).click(); await save(); await ready();
    assert.equal(value((await current()).state, 'component_004'), value(after, 'component_004'));
  });
  await check('repeatable Rhodes operators save and reopen independent professions', async () => {
    await page.getByRole('button', { name: '添加干员与编队', exact: true }).click();
    for (const name of ['罗德岛预备干员', '罗德岛精英干员']) {
      await dialog().getByLabel('搜索名称', { exact: true }).fill(name);
      for (let i = 0; i < 2; i++) await dialog().getByRole('button', { name: `选择 ${name}`, exact: true }).click();
    }
    const rows = dialog().locator('.operator-edit-row').filter({ has: page.locator('input[value="罗德岛预备干员"], input[value="罗德岛精英干员"]') });
    const professions = ['近卫', '狙击', '医疗', '重装'];
    for (let i = 0; i < 4; i++) await rows.nth(i).getByLabel('职业', { exact: true }).selectOption(professions[i]);
    await save(); await ready();
    const generic = (await current()).state.operators.filter(row => row.name.startsWith('罗德岛'));
    assert.deepEqual(generic.map(row => row.profession), professions);
    assert.deepEqual(generic.map(row => row.rarity), [3, 3, 5, 5]);
    assert.equal(new Set(generic.map(row => row.instanceId)).size, 4);
    await page.getByRole('button', { name: '编辑干员与编队', exact: true }).click();
    await save(); await ready();
    assert.deepEqual((await current()).state.operators.filter(row => row.name.startsWith('罗德岛')), generic);
  });
  await check('desktop and narrow viewports remain bounded in both themes', async () => {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 1440 ? 1050 : 844 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.getByRole('button', { name: '编辑零件箱', exact: true }).click();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.screenshot({ path: `${out}/editor-dark-${width}.png`, fullPage: true });
      await dialog().getByRole('button', { name: '关闭', exact: true }).click();
    }
    await page.getByRole('button', { name: '切换到明亮模式', exact: true }).click();
    await page.screenshot({ path: `${out}/light-390.png`, fullPage: true });
  });
  assert.equal(await readFile(sourcePath, 'utf8'), original); assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  await writeFile(`${out}/failure.json`, JSON.stringify({ error: error.stack, body: await page.locator('body').innerText() }, null, 2));
  throw error;
} finally {
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, checks, errors }, null, 2));
  await browser.close();
}
