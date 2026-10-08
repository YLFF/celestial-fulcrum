import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const source = 'runs/true-run-001/playtime.json', original = await readFile(source, 'utf8');
const token = (await (await fetch(`${base}/api/session`)).json()).token;
const runId = `ui-ending-${Date.now().toString(36)}`, seed = JSON.parse(original);
seed.goals = { endingV: 'ending2', endingVI: 'normal3', preferences: {}, progress: {}, note: '' };
const response = await fetch(`${base}/api/runs/restore`, { method: 'POST',
  headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' }, body: JSON.stringify({ state: seed, runId }) });
assert.ok(response.ok, await response.text());
const out = 'work/ui_ending'; await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
try {
  await page.goto(base);
  await page.getByText('通过“线人”不期而遇获取沙盘α', { exact: true }).waitFor();
  assert.equal(await page.getByText('五层前取得至少一张沙盘', { exact: true }).count(), 0);
  checks.push('alpha milestone label');
  for (const [label, mode] of [['追猎结局 1', '追猎'], ['普通结局 1', '不追猎']]) {
    await page.getByRole('button', { name: '编辑结局目标', exact: true }).click();
    await page.getByRole('dialog').getByRole('checkbox', { name: label, exact: true }).check();
    await page.getByRole('dialog').getByRole('button', { name: '保存', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    await page.getByLabel('地图区域', { exact: true }).selectOption('V');
    const control = page.locator('.route-controls .segmented');
    assert.equal(await control.getByRole('button', { name: mode, exact: true }).getAttribute('class'), 'active');
    assert.ok(await control.getByRole('button', { name: mode, exact: true }).isDisabled());
    checks.push(`fifth floor follows ${label}`);
    await page.screenshot({ path: `${out}/${mode === '追猎' ? 'pursuit' : 'normal'}.png`, fullPage: true });
  }
  await page.getByLabel('地图区域', { exact: true }).selectOption('I');
  assert.ok(await page.locator('.route-controls .segmented').getByRole('button', { name: '追猎', exact: true }).isEnabled());
  checks.push('other floors retain independent planning choice');
  assert.equal(await readFile(source, 'utf8'), original);
  assert.deepEqual(errors, []);
  console.log(checks.join('\n'));
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, checks, errors }, null, 2));
  await browser.close();
}
