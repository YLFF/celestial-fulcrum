import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const sourcePath = resolve('runs/true-run-001/playtime.json');
const original = await readFile(sourcePath, 'utf8');
const out = resolve('work/ui_tribute'); await mkdir(out, { recursive: true });
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json(); assert.ok(response.ok, JSON.stringify(data)); return data;
}
const seed = JSON.parse(original);
seed.resources.originiumIngot = 20;
seed.goals = { endingV: null, endingVI: null, preferences: { ending3_trade: 'required' }, progress: {}, note: '' };
const map = seed.areas.I.instances[0];
map.actionPoints = 5;
for (const row of Object.values(map.nodes)) {
  if (row.id === '0,0' || row.resolvedCategoryId === 'node_type_015') continue;
  Object.assign(row, { observedCategoryId: 'node_type_020', resolvedCategoryId: 'node_type_020',
    visibility: 'revealed', confirmedMarkIds: [], encounterId: null });
}
Object.assign(map.nodes['0,-1'], { observedCategoryId: 'node_type_008', resolvedCategoryId: 'node_type_008', confirmedMarkIds: ['node_mark_006'] });
Object.assign(map.nodes['1,-1'], { observedCategoryId: 'node_type_006', resolvedCategoryId: 'node_type_006', confirmedMarkIds: ['node_mark_005'], encounterId: 'encounter_023' });
const runId = `ui-tribute-${Date.now().toString(36)}`;
await api('/api/runs/restore', { state: seed, runId });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const checks = [], errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
async function check(name, callback) { await callback(); checks.push(name); console.log(name); }
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  await page.waitForFunction(() => !document.querySelector('.app-footer')?.textContent.includes('评分'));
  await check('node detail distinguishes planning score and natural tribute reference loss', async () => {
    await page.locator('[data-node-id="0,-1"]').click();
    const detail = page.getByRole('dialog', { name: '节点编辑 0,-1', exact: true });
    await detail.getByText('上贡损失（参考，不扣规划分）', { exact: true }).waitFor();
    assert.ok((await detail.locator('.reference-loss-summary').innerText()).includes('-500'));
    assert.ok((await detail.locator('.reference-loss-summary').innerText()).includes('2 件'));
    await page.screenshot({ path: `${out}/node-dark.png`, fullPage: true });
    await detail.getByRole('button', { name: '关闭节点详情', exact: true }).click();
  });
  await page.getByRole('button', { name: '规划', exact: true }).click();
  await page.locator('.route-row').first().waitFor({ timeout: 90000 });
  await check('route summary and step details expose reference-only cash and natural losses', async () => {
    const row = page.locator('.route-row').filter({ has: page.locator('.route-step b', { hasText: '(0,-1)' }) }).first();
    await row.waitFor();
    assert.ok((await row.locator('.route-result').innerText()).includes('上贡参考'));
    await row.locator('.route-step').filter({ has: page.locator('b', { hasText: '(0,-1)' }) }).click();
    await page.locator('.step-breakdown .reference-loss-summary').waitFor();
    assert.ok((await page.locator('.step-breakdown').innerText()).includes('-500'));
    await page.screenshot({ path: `${out}/route-dark.png`, fullPage: true });
    await row.locator('.route-step').filter({ has: page.locator('b', { hasText: '(1,-1)' }) }).click();
    await page.locator('.step-breakdown .reference-loss-summary').getByText(/^上贡源石锭/).waitFor();
    assert.ok((await page.locator('.step-breakdown').innerText()).includes('-176'));
    await page.screenshot({ path: `${out}/cash-dark.png`, fullPage: true });
  });
  await check('light theme and compact viewport keep reference fields visible without overflow', async () => {
    await page.getByRole('button', { name: '切换到明亮模式', exact: true }).click();
    await page.screenshot({ path: `${out}/cash-light.png`, fullPage: true });
    await page.setViewportSize({ width: 390, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    assert.ok((await page.locator('.step-breakdown').innerText()).includes('上贡源石锭'));
    await page.screenshot({ path: `${out}/cash-compact.png`, fullPage: true });
  });
  const saved = await api(`/api/runs/${runId}`, null, 'GET');
  assert.equal(saved.state.resources.originiumIngot, 20);
  assert.equal(saved.state.componentBox.items.length, seed.componentBox.items.length);
  assert.equal(await readFile(sourcePath, 'utf8'), original);
  assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, checks, errors }, null, 2));
  await browser.close();
}
