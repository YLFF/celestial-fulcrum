import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8775';
const sample = process.argv[2];
assert.ok(sample, 'Pass an operator squad screenshot path');
const out = process.env.FULCRUM_UI_OUTPUT || 'work/ui_operator_recognition';
await mkdir(out, { recursive: true });
const token = (await (await fetch(base + '/api/session')).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const value = await response.json();
  assert.ok(response.ok, JSON.stringify(value)); return value;
}
const runId = `operator-smoke-${Date.now().toString(36)}`;
const before = await api('/api/runs', { runId, squadId: 'squad_001', initialOperators: [] });
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base);
  await page.getByLabel('选择对局', { exact: true }).selectOption(runId);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  await page.getByRole('button', { name: '识别编队页面干员', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '识别编队页面干员', exact: true });
  await dialog.getByRole('button', { name: '识别编队页面干员', exact: true }).click();
  const capture = page.getByRole('dialog', { name: '选择窗口截图', exact: true });
  await capture.waitFor();
  await capture.getByRole('button', { name: '关闭', exact: true }).click();
  await dialog.getByLabel('编队截图', { exact: true }).setInputFiles(sample);
  await dialog.getByRole('button', { name: '识别所选截图', exact: true }).click();
  await dialog.locator('.operator-scan-row').first().waitFor({ timeout: 40000 });
  await page.screenshot({ path: `${out}/desktop.png` });
  assert.equal(await dialog.locator('.operator-scan-row').count(), 9);
  assert.equal(await dialog.getByLabel('确认机械师', { exact: true }).isDisabled(), true);
  assert.deepEqual((await api(`/api/runs/${runId}`, null, 'GET')).state, before.state);
  const reviewChoice = dialog.getByLabel('确认宴', { exact: true });
  if (await reviewChoice.count()) {
    assert.equal(await reviewChoice.isChecked(), false);
    await reviewChoice.check();
    assert.equal(await reviewChoice.isChecked(), true);
    await reviewChoice.uncheck();
  }
  const changed = await dialog.locator('input[type=checkbox]:checked').count();
  assert.ok(changed >= 1);
  await page.setViewportSize({ width: 390, height: 844 });
  await dialog.locator('.operator-scan-row').last().scrollIntoViewIfNeeded();
  assert.ok(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1));
  const box = await dialog.boundingBox();
  assert.ok(box.y >= 0 && box.y + box.height <= 844);
  await page.screenshot({ path: `${out}/mobile.png` });
  await dialog.getByRole('button', { name: `确认更新 ${changed} 名干员`, exact: true }).click();
  await dialog.waitFor({ state: 'hidden' });
  const after = await api(`/api/runs/${runId}`, null, 'GET');
  assert.equal(after.state.operators.length, before.state.operators.length + changed);
  assert.deepEqual(after.state.resources, before.state.resources);
  assert.deepEqual(after.state.componentBox, before.state.componentBox);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: '检查应用更新', exact: true }).click();
  const update = page.getByRole('dialog', { name: '应用更新', exact: true });
  await update.getByText('尚未检查', { exact: true }).waitFor();
  await page.screenshot({ path: `${out}/updates.png` });
  assert.equal(await update.getByRole('button', { name: '重启并更新', exact: true }).count(), 0);
  const fake = { currentVersion: '0.1.0', status: 'idle', canInstall: true, releasePage: 'https://github.com/YLFF/celestial-fulcrum/releases',
    release: { version: '0.2.0', size: 123456789, notes: '测试发行说明' } }, updateActions = [];
  await page.route('**/api/app-updates', async route => {
    if (route.request().method() === 'POST') {
      const action = route.request().postDataJSON().action;
      updateActions.push(action);
      fake.status = { check: 'available', download: 'ready', install: 'installing' }[action];
    }
    await route.fulfill({ json: fake });
  });
  await update.getByRole('button', { name: '检查更新', exact: true }).click();
  await update.getByRole('button', { name: '下载更新', exact: true }).click();
  await update.getByRole('button', { name: '重启并更新', exact: true }).click();
  await update.getByText('现在关闭程序并安装更新？', { exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await update.evaluate(element => element.scrollWidth <= element.clientWidth + 1));
  await page.screenshot({ path: `${out}/updates-confirm-mobile.png` });
  await update.getByRole('button', { name: '确认重启更新', exact: true }).click();
  await update.getByText('即将关闭并重启更新', { exact: true }).waitFor();
  assert.deepEqual(updateActions, ['check', 'download', 'install']);
  assert.deepEqual(errors, []);
  await writeFile(`${out}/summary.json`, JSON.stringify({ runId, cards: 9, selectedChanges: changed, beforeRevision: before.revision,
    afterRevision: after.revision, resourcesUnchanged: true, desktopMobileOverflow: false, captureDialog: true,
    updateButtonsWithFakeRelease: updateActions, pageErrors: errors }, null, 2));
  console.log(JSON.stringify({ runId, cards: 9, selectedChanges: changed, resourcesUnchanged: true, pageErrors: errors }));
} finally { await browser.close(); }
