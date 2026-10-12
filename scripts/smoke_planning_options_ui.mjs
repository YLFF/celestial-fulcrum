import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const out = 'work/ui_planning_options';
await mkdir(out, { recursive: true });
const token = (await (await fetch(base + '/api/session')).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  assert.ok(response.ok, JSON.stringify(data));
  return data;
}
const runId = `service-smoke-planning-options-${Date.now().toString(36)}`;
const restored = await api('/api/examples/true-run-001/restore', { runId });
const area = restored.state.currentAreaKey;
const state = () => api(`/api/runs/${runId}`, null, 'GET');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], checks = [], planRequests = [];
page.on('pageerror', error => errors.push(error.message));
page.on('request', request => { if (request.url().endsWith('/jobs/plan')) planRequests.push(request.postDataJSON()); });
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
const dialog = () => page.getByRole('dialog', { name: '本层前置目标', exact: true });
const reserve = () => page.getByLabel('路线规划预留源石锭', { exact: true });
const saveReserve = () => page.getByRole('button', { name: '保存路线规划预留源石锭并重新评分', exact: true });
async function settled() {
  await page.waitForFunction(() => !document.querySelector('.app-footer')?.textContent.includes('评分'));
}
async function check(name, fn) { await fn(); checks.push(name); console.log(name); }
try {
  await page.goto(base);
  await page.locator('.map-node').first().waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll('.node-value')].some(el => !el.textContent.includes('\u2014')));
  await settled();
  await check('reserve is left of pursuit, validates and persists with rescore', async () => {
    assert.equal(await page.locator('.playtime-sidebar .reserve-editor').count(), 0);
    assert.equal(await page.getByLabel('显示Top K路线', { exact: true }).count(), 0);
    assert.equal(await page.getByLabel('路径搜索上限', { exact: true }).count(), 0);
    const amount = await reserve().boundingBox();
    const mode = await page.locator('.route-controls > .segmented').boundingBox();
    assert.ok(amount.x + amount.width < mode.x);
    assert.equal(await reserve().inputValue(), '0');
    for (const invalid of ['-1', '1.5', '']) {
      await reserve().fill(invalid);
      assert.ok(await saveReserve().isDisabled());
    }
    const before = await state();
    const requests = await page.evaluate(() => performance.getEntriesByType('resource').filter(row => row.name.includes('/jobs/score')).length);
    await reserve().fill('30');
    await saveReserve().click();
    await page.waitForFunction(count => performance.getEntriesByType('resource').filter(row => row.name.includes('/jobs/score')).length > count, requests);
    await settled();
    const saved = await state();
    assert.ok(saved.revision > before.revision);
    const current = saved.state.areas[area];
    assert.equal(current.instances.find(row => row.instanceId === current.activeInstanceId).strategy.scoringOptions.merchantReserve, 30);
  });
  await check('search options appear above start with unchanged defaults', async () => {
    await page.getByRole('button', { name: '规划', exact: true }).click();
    assert.equal(await dialog().getByLabel('显示Top K路线', { exact: true }).inputValue(), '5');
    assert.equal(await dialog().getByLabel('路径搜索上限', { exact: true }).inputValue(), '50000');
    const items = await dialog().locator('.planning-items').boundingBox();
    const options = await dialog().locator('.planning-search-options').boundingBox();
    const start = await dialog().getByRole('button', { name: '开始规划', exact: true }).boundingBox();
    assert.ok(items.y + items.height <= options.y && options.y + options.height <= start.y);
  });
  await check('desktop and narrow layouts keep controls visible and inside the viewport', async () => {
    for (const width of [1440, 1024, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      for (const name of ['显示Top K路线', '路径搜索上限']) {
        const input = dialog().getByLabel(name, { exact: true });
        assert.ok(await input.isVisible());
        const box = await input.boundingBox();
        assert.ok(box.x >= 0 && box.x + box.width <= width);
      }
      await page.screenshot({ path: `${out}/dialog-${width}.png`, fullPage: true });
    }
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
    for (const width of [1440, 1024, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.locator('.route-section').scrollIntoViewIfNeeded();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      const box = await reserve().boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= width);
      await page.locator('.route-section').screenshot({ path: `${out}/controls-${width}.png` });
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole('button', { name: '规划', exact: true }).click();
  });
  await check('invalid settings remain editable even after closing and reopening', async () => {
    await dialog().getByLabel('显示Top K路线', { exact: true }).fill('0');
    assert.ok(await dialog().getByRole('button', { name: '开始规划', exact: true }).isDisabled());
    await dialog().getByRole('alert').waitFor();
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
    await page.getByRole('button', { name: '规划', exact: true }).click();
    assert.equal(await dialog().getByLabel('显示Top K路线', { exact: true }).inputValue(), '0');
    await dialog().getByLabel('显示Top K路线', { exact: true }).fill('8');
    await dialog().getByLabel('路径搜索上限', { exact: true }).fill('500001');
    assert.ok(await dialog().getByRole('button', { name: '开始规划', exact: true }).isDisabled());
    await dialog().getByLabel('路径搜索上限', { exact: true }).fill('1000');
    assert.ok(await dialog().getByRole('button', { name: '开始规划', exact: true }).isEnabled());
  });
  await check('edited settings reach the search service and survive reopening', async () => {
    await dialog().getByRole('button', { name: '开始规划', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.search-summary'), null, { timeout: 60000 });
    assert.equal(planRequests.at(-1).topN, 8);
    assert.equal(planRequests.at(-1).maxStates, 1000);
    await page.getByRole('button', { name: '规划', exact: true }).click();
    assert.equal(await dialog().getByLabel('显示Top K路线', { exact: true }).inputValue(), '8');
    assert.equal(await dialog().getByLabel('路径搜索上限', { exact: true }).inputValue(), '1000');
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
  });
  assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, checks, errors, planRequests }, null, 2));
  await browser.close();
}
