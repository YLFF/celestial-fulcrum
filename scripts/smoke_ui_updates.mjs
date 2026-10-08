import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = 'http://127.0.0.1:8766', out = resolve('work/ui_updates');
await mkdir(out, { recursive: true });
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const res = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await res.json(); assert.ok(res.ok, JSON.stringify(data)); return data;
}
const id = `ui-updates-${Date.now().toString(36)}`;
await api('/api/runs', { runId: id, squadId: 'squad_014' });
const catalog = await api('/api/catalog', null, 'GET');
const original = await readFile('runs/true-run-001/playtime.json', 'utf8');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
const errors = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, id);
const dialog = () => page.getByRole('dialog');
async function check(name, callback) { await callback(); checks.push(name); console.log(name); }
async function waitPreview() { await page.locator('.opening-summary').waitFor(); await page.waitForTimeout(200); }
async function current() { return (await api(`/api/runs/${id}`, null, 'GET')).state; }
async function save() { await dialog().getByRole('button', { name: '保存', exact: true }).click(); await dialog().waitFor({ state: 'hidden' }); }
async function newForm() { await page.locator('.app-header').getByRole('button', { name: '开始探索', exact: true }).click(); await waitPreview(); }
try {
  await page.goto(base); await page.getByRole('button', { name: '添加零件箱' }).waitFor();
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, id);
  await check('opening costs, search, goals and supports', async () => {
    await newForm();
    assert.equal(await dialog().getByLabel('分队').locator('option[value=""]').count(), 0);
    assert.equal(await dialog().getByText('投资余额', { exact: true }).count(), 0);
    await dialog().getByLabel('筛选职业').selectOption(catalog.operators.find(row => row.name === '予愿安洁莉娜').profession);
    await dialog().getByLabel('搜索名称').fill('予愿安');
    await dialog().getByRole('button', { name: '选择 予愿安洁莉娜', exact: true }).click(); await waitPreview();
    assert.ok((await page.locator('.opening-summary').innerText()).includes('剩余希望 0'));
    assert.equal(await dialog().getByLabel('予愿安洁莉娜 初始进阶状态').inputValue(), '1');
    assert.equal(await dialog().getByLabel('希望消耗', { exact: true }).count(), 0);
    await dialog().getByLabel('襁褓中的狗', { exact: true }).check();
    await dialog().getByLabel('襁褓中的狗数量').fill('2'); await waitPreview();
    assert.ok((await page.locator('.opening-summary').innerText()).includes('剩余希望 2'));
    assert.equal(await dialog().getByText('襁褓羽蛇', { exact: true }).count(), 0);
    assert.equal(await dialog().getByText('襁褓三头犬', { exact: true }).count(), 0);
    await dialog().getByLabel('普通结局 1', { exact: true }).check();
    await dialog().getByLabel('结局 2', { exact: true }).check();
    assert.equal(await dialog().getByLabel('普通结局 1', { exact: true }).isChecked(), false);
    await dialog().getByLabel('普通结局 3', { exact: true }).check();
    await dialog().getByLabel('无效验尸', { exact: true }).check();
    await dialog().getByLabel('获得8源石锭', { exact: true }).check(); await waitPreview();
    await page.screenshot({ path: `${out}/new-run-dark.png`, fullPage: true });
    await dialog().getByLabel('分队').selectOption('squad_007'); await waitPreview();
    assert.equal(await page.locator('.opening-operator').count(), 0);
    await dialog().getByLabel('筛选职业').selectOption('辅助');
    await dialog().getByLabel('搜索名称').fill('安洁莉娜');
    await dialog().getByRole('button', { name: '选择 安洁莉娜', exact: true }).click(); await waitPreview();
    assert.equal(await dialog().getByLabel('安洁莉娜 初始进阶状态').inputValue(), '1');
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
  });
  await check('special squad initial Mechanist promotion', async () => {
    await newForm(); await dialog().getByLabel('分队').selectOption('squad_002'); await waitPreview();
    await dialog().getByLabel('初始有重装招募券').check();
    await dialog().getByLabel('消耗 2 希望进阶机械师').check(); await waitPreview();
    assert.ok((await page.locator('.opening-summary').innerText()).includes('剩余希望 4'));
    await dialog().getByLabel('对局 ID').fill(`${id}-special`); await waitPreview();
    await dialog().getByRole('button', { name: '进入树海', exact: true }).click(); await dialog().waitFor({ state: 'hidden' });
    const state = (await api(`/api/runs/${id}-special`, null, 'GET')).state;
    assert.equal(state.operators.find(row => row.name === '机械师').elite, 2);
    assert.equal(state.resources.hope, 4);
    assert.ok(state.componentBox.items.some(row => row.componentId === 'component_023'));
    await page.getByLabel('选择对局').selectOption(id);
    await page.waitForFunction(id => document.querySelector('.run-select')?.value === id && document.querySelector('.run-badges')?.textContent.includes('多边贸易'), id);
  });
  await check('three-category component editor with initial appraisal', async () => {
    await page.getByRole('button', { name: '添加零件箱', exact: true }).click();
    assert.equal(await page.locator('.component-columns > section').count(), 3);
    await dialog().getByLabel('搜索名称').fill('结构原理');
    await dialog().getByRole('button', { name: '选择 结构性原理', exact: true }).click();
    const row = page.locator('.component-edit-row').filter({ hasText: '结构性原理' });
    assert.equal(await row.getByLabel('当前估价').inputValue(), '1');
    assert.equal(await row.getByLabel('剩余次数').inputValue(), '3');
    assert.ok((await row.locator('..').innerText()).startsWith('加工品'));
    await page.screenshot({ path: `${out}/components-dark.png`, fullPage: true }); await save();
    assert.equal((await current()).componentBox.items.find(row => row.componentId === 'component_023').estimatedValue, 1);
  });
  await check('relic stacks and fixed bonus action', async () => {
    assert.ok(await page.locator('.inventory-section').first().locator('header .bonus-button').count());
    await page.getByRole('button', { name: '添加藏品', exact: true }).click();
    const relic = catalog.relic[0];
    await dialog().getByLabel('搜索名称').fill(relic.name);
    await dialog().getByRole('button', { name: `选择 ${relic.name}`, exact: true }).click();
    assert.equal(await dialog().getByLabel('数量', { exact: true }).count(), 0);
    await dialog().getByLabel(`${relic.name} 层数 / 生效`, { exact: true }).fill('3'); await save();
    assert.equal((await current()).relics[0].state, 3);
  });
  await check('operator picker and three sources', async () => {
    await page.getByRole('button', { name: '添加干员与编队', exact: true }).click();
    const fixed = page.locator('.operator-edit-row').first();
    assert.equal(await fixed.getByLabel('职业', { exact: true }).inputValue(), '重装');
    assert.equal(await fixed.getByLabel('星级', { exact: true }).inputValue(), '6');
    assert.equal(await fixed.getByLabel('进阶状态', { exact: true }).inputValue(), '2');
    assert.equal(await fixed.getByLabel('来源', { exact: true }).locator('option').count(), 3);
    await dialog().getByLabel('筛选职业').selectOption('先锋'); await dialog().getByLabel('搜索名称').fill('FANG');
    await dialog().getByRole('button', { name: '选择 芬', exact: true }).click(); await save();
    assert.equal((await current()).operators.find(row => row.name === '芬').profession, '先锋');
    assert.ok((await page.locator('.operator-strip').innerText()).includes('6★ · 已进阶 · 助'));
  });
  await check('native screenshot preview and resources before commit', async () => {
    await page.locator('input[aria-label="上传地图截图"]').setInputFiles(resolve('samples/maps/desktop_native_3840.png'));
    await dialog().getByRole('button', { name: '开始识别', exact: true }).click();
    await dialog().getByRole('button', { name: '确认入局', exact: true }).waitFor({ timeout: 60000 });
    assert.equal(await dialog().locator('.map-node').count(), 13);
    for (const [name, value] of [['等级', '1'], ['护盾', '2'], ['行动力', '6'], ['希望', '1'], ['源石锭', '25']]) assert.equal(await dialog().getByLabel(`${name}候选`, { exact: true }).inputValue(), value);
    assert.equal(await dialog().getByLabel('生命当前候选').inputValue(), '4');
    assert.equal(await dialog().getByLabel('经验当前候选').inputValue(), '0');
    assert.equal((await current()).areas.I.instances.length, 0);
    await dialog().locator('[data-node-id="1,1"]').click();
    await dialog().getByLabel('批量修正节点类别').selectOption('node_type_006');
    await dialog().getByRole('button', { name: '修正所选节点', exact: true }).click();
    assert.ok((await dialog().locator('[data-node-id="1,1"]').innerText()).includes('不期而遇'));
    await page.screenshot({ path: `${out}/recognition-preview.png`, fullPage: true });
    await dialog().getByRole('button', { name: '确认入局', exact: true }).click(); await dialog().waitFor({ state: 'hidden' });
    const state = await current(); assert.equal(state.resources.level, 1); assert.equal(state.resources.shield, 2); assert.equal(state.resources.hope, 1);
    assert.equal(state.areas.I.instances[0].nodes['1,1'].resolvedCategoryId, 'node_type_006');
    for (const nodeId of ['-1,1', '2,0', '2,1']) assert.equal(state.areas.I.instances[0].nodes[nodeId].resolvedCategoryId, null);
  });
  await check('map rectangle selection and editable batch', async () => {
    await page.waitForFunction(() => !document.querySelector('input[aria-label="上传地图截图"]').disabled);
    const scene = await page.locator('.main-workspace .map-scene').boundingBox();
    await page.mouse.move(scene.x + 10, scene.y + 10); await page.mouse.down(); await page.mouse.move(scene.x + scene.width - 10, scene.y + scene.height - 10, { steps: 8 }); await page.mouse.up();
    assert.equal(await page.locator('.main-workspace .selected-node').count(), 13);
    await page.getByRole('button', { name: '编辑所选节点', exact: true }).click();
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
    await page.getByRole('button', { name: '取消选择', exact: true }).click();
    await page.screenshot({ path: `${out}/desktop-dark.png`, fullPage: true });
  });
  await check('responsive dark and light layouts', async () => {
    await page.getByRole('button', { name: '切换到明亮模式' }).click(); await page.screenshot({ path: `${out}/desktop-light.png`, fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.getByRole('button', { name: '添加零件箱', exact: true }).click();
    assert.equal(await dialog().evaluate(el => el.scrollWidth <= el.clientWidth), true);
    await page.screenshot({ path: `${out}/mobile-components.png`, fullPage: true });
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
    await newForm(); assert.equal(await dialog().evaluate(el => el.scrollWidth <= el.clientWidth), true);
    await page.screenshot({ path: `${out}/mobile-new.png`, fullPage: true });
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
  });
  assert.deepEqual(errors, []);
  assert.equal(await readFile('runs/true-run-001/playtime.json', 'utf8'), original);
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(`${out}/report.json`, JSON.stringify({ checks, errors, runId: id }, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ runId: id, checks: checks.length, errors }));
