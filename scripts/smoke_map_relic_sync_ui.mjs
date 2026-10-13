import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8773';
const out = 'work/map-relic-sync';
await mkdir(out, { recursive: true });
const token = (await (await fetch(base + '/api/session')).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method,
    headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const result = await response.json();
  assert.ok(response.ok, JSON.stringify(result));
  return result;
}
const runId = `map-relic-sync-${Date.now().toString(36)}`;
await api('/api/runs', { runId, squadId: 'squad_001' });
const state = () => api(`/api/runs/${runId}`, null, 'GET');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => {
  localStorage.setItem('fulcrum-run', id);
  localStorage.setItem('fulcrum-theme', 'dark');
}, runId);
const dialog = page.getByRole('dialog');
const candidates = dialog.locator('.synced-relic-candidates');
async function ready() {
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id &&
    !document.querySelector('input[aria-label="上传地图截图"]')?.disabled, runId);
}
async function upload() {
  await page.getByLabel('上传地图截图', { exact: true }).setInputFiles('samples/maps/desktop_floor2_lookout_revealed.png');
  await dialog.waitFor({ state: 'visible' });
  await dialog.getByRole('button', { name: '开始识别', exact: true }).click();
  await dialog.getByRole('button', { name: '确认入局', exact: true }).waitFor({ timeout: 60000 });
}
async function confirm() {
  await dialog.getByRole('button', { name: '确认入局', exact: true }).click();
  await dialog.waitFor({ state: 'hidden' });
  await ready();
}
try {
  await page.goto(base);
  await ready();
  const before = await state();
  await upload();
  assert.equal(await dialog.getByLabel('同步识别左下角藏品', { exact: true }).isChecked(), true);
  assert.equal(await candidates.locator('input[type="checkbox"]').count(), 2);
  for (const name of ['沙盘β', '失落之钥']) {
    assert.equal(await candidates.getByLabel(`添加 ${name}`, { exact: true }).isChecked(), true);
  }
  await page.waitForFunction(() => [...document.querySelectorAll('.synced-relic-list img')]
    .filter(image => image.complete && image.naturalWidth > 0).length === 2);
  assert.equal(await dialog.evaluate(element => {
    const review = element.querySelector('.merge-review');
    const relics = element.querySelector('.synced-relic-candidates');
    const map = element.querySelector('.map-frame');
    return !!map && (!review || (review.compareDocumentPosition(relics) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0) &&
      (relics.compareDocumentPosition(map) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
  }), true);
  assert.deepEqual((await state()).state.relics, before.state.relics);
  assert.equal((await state()).revision, before.revision);
  console.log('Matched map exposes only confident new relics, checked by default, without changing the run');

  await candidates.scrollIntoViewIfNeeded();
  assert.ok((await candidates.boundingBox()).height < 110);
  await page.screenshot({ path: `${out}/desktop.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  await candidates.scrollIntoViewIfNeeded();
  assert.equal(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1), true);
  const bounds = await candidates.boundingBox();
  assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390 && bounds.height < 130);
  await page.screenshot({ path: `${out}/mobile.png` });
  console.log('Compact candidate images render without horizontal overflow on desktop and mobile');

  await page.setViewportSize({ width: 1440, height: 1000 });
  await candidates.getByLabel('添加 沙盘β', { exact: true }).uncheck();
  await confirm();
  const updated = await state();
  assert.deepEqual(updated.state.relics.map(row => row.id), ['relic_027']);
  assert.equal(updated.history.undoCount, 1);
  assert.ok(updated.state.areas.II.activeInstanceId);
  const undone = await api(`/api/runs/${runId}/undo`, { expectedRevision: updated.revision });
  assert.deepEqual(undone.state.relics, before.state.relics);
  assert.equal(undone.state.areas.II.activeInstanceId, null);
  const redone = await api(`/api/runs/${runId}/redo`, { expectedRevision: undone.revision });
  assert.deepEqual(redone.state.relics, updated.state.relics);
  assert.equal(redone.state.areas.II.activeInstanceId, updated.state.areas.II.activeInstanceId);
  console.log('Only checked relics are added; one map checkpoint restores both map and inventory');

  await page.reload();
  await ready();
  await upload();
  assert.equal(await candidates.locator('input[type="checkbox"]').count(), 1);
  assert.equal(await candidates.getByLabel('添加 失落之钥', { exact: true }).count(), 0);
  await candidates.getByLabel('添加 沙盘β', { exact: true }).uncheck();
  await confirm();
  assert.deepEqual((await state()).state.relics, updated.state.relics);
  console.log('Held relics are filtered; deselecting all candidates leaves the inventory unchanged');

  await page.getByLabel('上传地图截图', { exact: true }).setInputFiles('samples/maps/desktop_floor2_lookout_revealed.png');
  await dialog.getByLabel('同步识别左下角藏品', { exact: true }).uncheck();
  await dialog.getByRole('button', { name: '开始识别', exact: true }).click();
  await dialog.getByRole('button', { name: '确认入局', exact: true }).waitFor({ timeout: 60000 });
  assert.equal(await candidates.count(), 0);
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  console.log('Optional sync can be disabled without changing map recognition');
  assert.deepEqual(errors, []);
} finally { await browser.close(); }
