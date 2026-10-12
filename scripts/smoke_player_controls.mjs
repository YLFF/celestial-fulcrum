import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const sourcePath = resolve(process.env.FULCRUM_CONTROLS_SOURCE || 'work/app_data/runs/run-mux3hoew-u416e3w/playtime.json');
const original = await readFile(sourcePath, 'utf8');
const out = resolve('work/ui_controls'); await mkdir(out, { recursive: true });
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json(); assert.ok(response.ok, JSON.stringify(data)); return data;
}
const runId = `ui-controls-${Date.now().toString(36)}`;
await api('/api/runs/restore', { state: JSON.parse(original), runId });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], checks = [], planRequests = [];
page.on('pageerror', error => errors.push(error.message));
page.on('request', request => { if (request.url().endsWith('/jobs/plan')) planRequests.push(request.postDataJSON()); });
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
const dialog = () => page.getByRole('dialog');
const current = () => api(`/api/runs/${runId}`, null, 'GET');
async function check(name, fn) { await fn(); checks.push(name); console.log(name); }
async function save() { await dialog().getByRole('button', { name: '保存', exact: true }).click(); await dialog().waitFor({ state: 'hidden' }); }
async function ready() { await page.waitForFunction(() => document.querySelector('input[aria-label="上传地图截图"]') && !document.querySelector('input[aria-label="上传地图截图"]').disabled && [...document.querySelectorAll('.node-value')].some(el => !el.textContent.includes('\u2014'))); }
try {
  await page.goto(base); await ready();
  await check('resource double click and validation', async () => {
    await page.getByRole('button', { name: '编辑希望', exact: true }).dblclick();
    const before = await current();
    await dialog().getByLabel('希望', { exact: true }).fill('-1');
    await dialog().getByRole('button', { name: '保存', exact: true }).click();
    await dialog().getByRole('alert').waitFor(); assert.equal((await current()).revision, before.revision);
    await dialog().getByLabel('希望', { exact: true }).fill('3.5');
    await dialog().getByRole('button', { name: '保存', exact: true }).click();
    assert.equal((await current()).revision, before.revision);
    await dialog().getByLabel('希望', { exact: true }).fill('8'); await save();
    assert.equal((await current()).state.resources.hope, 8); await ready();
    await page.getByRole('button', { name: '编辑生命', exact: true }).dblclick();
    await dialog().getByLabel('当前生命').fill('999');
    await dialog().getByRole('button', { name: '保存', exact: true }).click();
    await dialog().getByRole('alert').waitFor();
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
    await page.getByRole('button', { name: '编辑等级 / 经验', exact: true }).dblclick();
    await dialog().getByLabel('等级', { exact: true }).fill('11');
    await dialog().getByRole('button', { name: '保存', exact: true }).click(); await dialog().getByRole('alert').waitFor();
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
    assert.equal(await page.getByRole('button', { name: '编辑总估价', exact: true }).count(), 0);
  });
  await check('Top 5 and 10 reach backend and return distinct paths', async () => {
    for (const top of [5, 10]) {
      await page.getByRole('button', { name: '规划', exact: true }).click();
      if (top === 5) assert.equal(await dialog().getByLabel('显示Top K路线', { exact: true }).inputValue(), '5');
      await dialog().getByLabel('显示Top K路线', { exact: true }).fill(String(top));
      assert.equal(await page.locator('.route-row').count(), 0);
      await dialog().getByRole('button', { name: '开始规划', exact: true }).click();
      await page.locator('.route-row').first().waitFor({ timeout: 60000 });
      assert.equal(await page.locator('.route-row').count(), top);
      assert.equal(planRequests.at(-1).topN, top); assert.equal(planRequests.at(-1).maxStates, 50000);
      const paths = await page.locator('.route-steps').evaluateAll(rows => rows.map(row => [...row.querySelectorAll('b')].map(el => el.textContent).join('|')));
      assert.equal(new Set(paths).size, top);
    }
    assert.ok(await page.locator('.terminal-score').count());
    await page.locator('.terminal-score summary').first().click();
    await page.screenshot({ path: `${out}/routes-dark.png`, fullPage: true });
  });
  await check('default score tab, reveal components and aligned sidebar', async () => {
    await page.locator('[data-node-id="1,0"]').click();
    assert.equal(await page.getByRole('button', { name: '概率与得分', exact: true }).getAttribute('class'), 'active');
    assert.ok((await page.locator('.node-popover').innerText()).includes('前往揭示分'));
    await page.screenshot({ path: `${out}/node-score.png`, fullPage: true });
    await page.getByRole('button', { name: '关闭节点详情' }).click();
    for (const name of ['节点池', '不期而遇池', '本局备忘']) {
      const button = page.getByRole('button', { name: `展开${name}`, exact: true });
      assert.equal(await button.getAttribute('aria-expanded'), 'false'); await button.click();
      assert.equal(await page.getByRole('button', { name: `收起${name}`, exact: true }).getAttribute('aria-expanded'), 'true');
    }
    const sidebar = await page.locator('.playtime-sidebar').boundingBox();
    const workspace = await page.locator('.main-workspace').boundingBox();
    assert.ok(Math.abs(sidebar.height - workspace.height) < 1);
    const images = await page.locator('.map-node img').evaluateAll(rows => rows.map(el => ({ loaded: el.complete && el.naturalWidth > 0, width: el.width, height: el.height })));
    assert.ok(images.length > 5 && images.every(el => el.loaded && el.width > 0 && el.height > 0));
  });
  await check('AP4 recognized and current node complete before confirmation', async () => {
    await page.getByLabel('上传地图截图').setInputFiles(resolve('samples/maps/desktop_action_4.png'));
    await dialog().getByRole('button', { name: '开始识别', exact: true }).click();
    await dialog().getByRole('button', { name: '确认入局', exact: true }).waitFor({ timeout: 60000 });
    assert.equal(await dialog().getByLabel('行动力候选', { exact: true }).inputValue(), '4');
    assert.equal(await dialog().getByLabel('当前位置已完成').isChecked(), true);
    await page.screenshot({ path: `${out}/action4-preview.png`, fullPage: true });
    await dialog().getByRole('button', { name: '确认入局', exact: true }).click(); await dialog().waitFor({ state: 'hidden' }); await ready();
    const data = (await current()).state, area = data.areas.I;
    const instance = area.instances.find(row => row.instanceId === area.activeInstanceId);
    assert.equal(instance.actionPoints, 4); assert.equal(instance.nodes[instance.playerPosition].completion, 'completed');
    assert.equal(await page.getByRole('button', { name: '规划', exact: true }).isDisabled(), false);
  });
  await check('Graphics capture default and responsive light/dark layout', async () => {
    await page.getByRole('button', { name: '窗口截图', exact: true }).click();
    assert.equal(await dialog().locator('select').last().inputValue(), 'graphics');
    assert.equal(await dialog().getByRole('button', { name: '授权并截取', exact: true }).isDisabled(), true);
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.screenshot({ path: `${out}/dark-${width}.png`, fullPage: true });
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
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, checks, errors, planRequests }, null, 2));
  await browser.close();
}
