import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const sourcePath = resolve('runs/true-run-001/playtime.json');
const original = await readFile(sourcePath, 'utf8');
const out = resolve('work/ui_progress'); await mkdir(out, { recursive: true });
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json(); assert.ok(response.ok, JSON.stringify(data)); return data;
}
const seed = JSON.parse(original);
seed.memo = Array.from({ length: 80 }, (_, i) => `测试备忘 ${i + 1}`).join('\n');
const runId = `ui-progress-${Date.now().toString(36)}`;
await api('/api/runs/restore', { state: seed, runId });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const checks = [], errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
const dialog = () => page.getByRole('dialog');
async function check(name, callback) { await callback(); checks.push(name); console.log(name); }
async function aligned() {
  const main = await page.locator('.main-workspace').boundingBox();
  const side = await page.locator('.playtime-sidebar').boundingBox();
  assert.ok(Math.abs(main.y - side.y) < 1);
  assert.ok(Math.abs(main.height - side.height) < 1);
  const route = await page.locator('.route-section').boundingBox();
  assert.ok(Math.abs(route.y - main.y - main.height) < 1);
}
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  await check('sidebar matches map plus inventory and scrolls without pushing routes down', async () => {
    await aligned();
    for (const title of ['节点池', '不期而遇池', '本局备忘']) await page.getByRole('button', { name: `展开${title}`, exact: true }).click();
    await aligned();
    assert.ok(await page.locator('.playtime-sidebar').evaluate(el => el.scrollHeight > el.clientHeight));
    await page.locator('.playtime-sidebar').evaluate(el => { el.scrollTop = 0; });
    await page.screenshot({ path: `${out}/sidebar-dark.png`, fullPage: true });
  });
  await check('roster displays progress labels and preserves stored elite values', async () => {
    const before = (await api(`/api/runs/${runId}`, null, 'GET')).state.operators;
    assert.equal(await page.locator('.operator-strip').getByText(/精[零一二012]/).count(), 0);
    await page.getByRole('button', { name: '编辑干员与编队', exact: true }).click();
    const states = dialog().getByLabel('进阶状态', { exact: true });
    assert.equal(await states.count(), before.length);
    for (let i = 0; i < before.length; i++) {
      assert.equal(await states.nth(i).inputValue(), String(before[i].elite));
      const labels = await states.nth(i).locator('option').allTextContents();
      assert.ok(labels.includes(before[i].elite === 2 ? '已进阶' : '未进阶'));
      assert.equal(labels.some(text => /精[零一二]/.test(text)), false);
    }
    await dialog().getByRole('button', { name: '保存', exact: true }).click();
    await dialog().waitFor({ state: 'hidden' });
    const after = (await api(`/api/runs/${runId}`, null, 'GET')).state.operators;
    assert.deepEqual(after.map(row => [row.instanceId, row.elite]), before.map(row => [row.instanceId, row.elite]));
  });
  await check('new recruitment has unpromoted and promoted states but no E0 choice', async () => {
    await page.getByRole('button', { name: '开始探索', exact: true }).click();
    await dialog().getByLabel('分队', { exact: true }).selectOption('squad_002');
    assert.ok((await dialog().locator('.initial-mechanist').innerText()).includes('未进阶'));
    await dialog().getByLabel('初始有重装招募券').check();
    await dialog().getByLabel('消耗 2 希望进阶机械师').check();
    assert.ok((await dialog().locator('.initial-mechanist').innerText()).includes('已进阶'));
    await dialog().getByLabel('分队', { exact: true }).selectOption('squad_014');
    await dialog().getByLabel('搜索名称', { exact: true }).fill('予愿安洁莉娜');
    await dialog().locator('.picker-results button').first().click();
    const field = dialog().getByLabel('予愿安洁莉娜 初始进阶状态', { exact: true });
    assert.deepEqual(await field.locator('option').allTextContents(), ['未进阶', '已进阶']);
    assert.equal(await field.inputValue(), '1');
    await field.selectOption('2'); assert.equal(await field.inputValue(), '2');
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
  });
  await check('desktop and narrow layouts remain aligned without horizontal overflow', async () => {
    for (const width of [1920, 1024, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      if (width > 800) await aligned();
      await page.locator('.playtime-sidebar').evaluate(el => { el.scrollTop = 0; });
      await page.screenshot({ path: `${out}/dark-${width}.png`, fullPage: true });
    }
    await page.getByRole('button', { name: '切换到明亮模式', exact: true }).click();
    await page.setViewportSize({ width: 1440, height: 1000 }); await aligned();
    await page.locator('.playtime-sidebar').evaluate(el => { el.scrollTop = 0; });
    await page.screenshot({ path: `${out}/sidebar-light.png`, fullPage: true });
  });
  assert.equal(await readFile(sourcePath, 'utf8'), original); assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, checks, errors }, null, 2));
  await browser.close();
}
