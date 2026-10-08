import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdir } from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const protectedPaths = ['work/app_data/runs/run-mux3hoew-u416e3w/playtime.json', 'runs/true-run-001/playtime.json'];
const originals = await Promise.all(protectedPaths.map(path => readFile(path, 'utf8')));
const token = (await (await fetch(base + '/api/session')).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const value = await response.json();
  assert.ok(response.ok, JSON.stringify(value));
  return value;
}
const runId = `service-smoke-relics-${Date.now().toString(36)}`;
const seed = JSON.parse(originals[1]);
seed.relics = [{ id: 'relic_139', count: 1, state: 2, note: 'preserved' }, { id: 'relic_001', count: 1 }];
await api('/api/runs/restore', { state: seed, runId });
await mkdir('work/ui_relic_recognition', { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base);
  await page.getByLabel('选择对局', { exact: true }).selectOption(runId);
  await page.getByRole('button', { name: '识别藏品', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '识别藏品', exact: true });
  await dialog.getByLabel('藏品截图', { exact: true }).setInputFiles('samples/relics/visible_row.jpg');
  await dialog.getByRole('button', { name: '识别', exact: true }).click();
  await dialog.locator('[data-relic-slot="7"]').waitFor({ timeout: 30000 });
  assert.match(await dialog.locator('[data-relic-slot="2"]').innerText(), /黄金平原/);
  assert.match(await dialog.locator('[data-relic-slot="6"]').innerText(), /锈刃-新典训/);
  assert.match(await dialog.locator('[data-relic-slot="7"]').innerText(), /蓝色丝巾/);
  assert.equal(await dialog.getByLabel('第2件藏品', { exact: true }).inputValue(), '');
  assert.equal(await dialog.getByLabel('第6件藏品', { exact: true }).inputValue(), '');
  assert.equal(await dialog.getByLabel('第7件藏品', { exact: true }).inputValue(), '');
  await dialog.getByRole('img', { name: '检测到的收藏品栏' }).waitFor();
  await page.screenshot({ path: 'work/ui_relic_recognition/desktop.png', fullPage: false });
  await dialog.getByLabel('第6件藏品', { exact: true }).selectOption('relic_180');
  await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });
  await page.screenshot({ path: 'work/ui_relic_recognition/dark.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await dialog.locator('[data-relic-slot="7"]').scrollIntoViewIfNeeded();
  assert.equal(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth+1), true);
  const rect = await dialog.boundingBox();
  assert.ok(rect.y >= 0 && rect.y+rect.height <= 844);
  await page.screenshot({ path: 'work/ui_relic_recognition/mobile.png' });
  await dialog.getByRole('button', { name: /添加 5 件藏品/ }).click();
  await dialog.waitFor({ state: 'hidden' });
  const after = await api(`/api/runs/${runId}`, null, 'GET');
  const rows = after.state.relics;
  assert.equal(rows.length, 7);
  assert.deepEqual(rows[0], seed.relics[0]);
  assert.equal(rows.filter(row => row.id === 'relic_139').length, 1);
  assert.ok(rows.some(row => row.id === 'relic_180'));
  assert.ok(!rows.some(row => row.id === 'relic_016'));
  assert.deepEqual(errors, []);
  for (let i=0; i<originals.length; i++) assert.equal(await readFile(protectedPaths[i], 'utf8'), originals[i]);
  console.log(JSON.stringify({ runId, relics: rows.map(row => row.id), originalRunsUnchanged: true }));
} finally {
  await browser.close();
}
