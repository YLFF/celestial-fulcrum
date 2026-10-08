import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8768';
const out = 'work/ui_lookout';
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
  await page.goto(base);
  await page.getByRole('button', { name: '开始探索', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '新建对局', exact: true });
  const split = dialog.getByRole('checkbox', { name: '生命游戏 · 分裂（羽瞰点）', exact: true });
  assert.equal(await split.isChecked(), true);
  await page.screenshot({ path: `${out}/desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await split.scrollIntoViewIfNeeded();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await page.screenshot({ path: `${out}/mobile.png`, fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const runId = `lookout-ui-${Date.now().toString(36)}`;
  await dialog.getByLabel('对局 ID', { exact: true }).fill(runId);
  const preview = page.waitForResponse(response => response.url().endsWith('/api/opening/preview')
    && response.request().postDataJSON().lookoutSplitUnlocked === false);
  await split.uncheck();
  assert.equal((await preview).ok(), true);
  const creation = page.waitForResponse(response => response.url().endsWith('/api/runs') && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: '进入树海', exact: true }).click();
  const response = await creation;
  assert.equal(response.status(), 201);
  const created = await response.json();
  assert.equal(created.state.runId, runId);
  assert.equal(created.state.opening.lookoutSplitUnlocked, false);
  assert.equal(created.state.opening.difficulty, 15);
  await dialog.waitFor({ state: 'hidden' });
  assert.deepEqual(errors, []);
  console.log('lookout checkbox: default enabled, narrow viewport, preview and persisted opt-out passed');
} finally {
  await browser.close();
}
