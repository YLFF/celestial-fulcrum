import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const source = 'work/app_data/runs/run-mux3hoew-u416e3w/playtime.json';
const original = await readFile(source, 'utf8');
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const value = await response.json();
  assert.ok(response.ok, JSON.stringify(value));
  return value;
}

// Only a unique copy receives checkbox edits; the original run remains read-only.
const runId = `service-smoke-ending-score-${Date.now().toString(36)}`;
const restored = await api('/api/runs/restore', { state: JSON.parse(original), runId });
const catalog = await api('/api/catalog', null, 'GET');
assert.equal(catalog.component.find(row => row.id === 'component_012').initialEstimatedValue, 16);
const out = 'work/ui_ending_scores';
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
async function settled() {
  await page.waitForFunction(() => /\d/.test(document.querySelector('.map-node[data-node-id="1,0"] .node-value')?.textContent || '')
    && !document.querySelector('.sidebar-section input[type="checkbox"]')?.disabled);
}
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  const checkbox = page.getByRole('checkbox', { name: '是否已通过线人节点', exact: true });
  await checkbox.waitFor();
  assert.equal(await checkbox.isChecked(), false);
  await page.getByText('上层或之前已获取怦然信标', { exact: true }).waitFor();
  await settled();
  await checkbox.click();
  await page.waitForFunction(() => [...document.querySelectorAll('.sidebar-section label')]
    .find(row => row.textContent.includes('是否已通过线人节点'))?.querySelector('input')?.checked === true);
  await settled();
  await checkbox.click();
  await page.waitForFunction(() => [...document.querySelectorAll('.sidebar-section label')]
    .find(row => row.textContent.includes('是否已通过线人节点'))?.querySelector('input')?.checked === false);
  await settled();
  await page.reload();
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  await checkbox.waitFor();
  assert.equal(await checkbox.isChecked(), false);
  await settled();
  const saved = await api(`/api/runs/${runId}`, null, 'GET');
  assert.equal(saved.state.goals.progress.ending2_sandbox.status, 'pending');
  assert.deepEqual(saved.state.resources, restored.state.resources);
  assert.deepEqual(saved.state.areas.II.instances, restored.state.areas.II.instances);
  assert.ok(saved.state.globalEncounterPool.find(row => row.id === 'encounter_022').completedCount > 0);

  await page.locator('.map-node[data-node-id="1,0"]').click();
  const dialog = page.getByRole('dialog', { name: '节点编辑 1,0', exact: true });
  const autopsy = dialog.locator('.score-details > details > summary').filter({ has: page.locator('span', { hasText: /^无效验尸$/ }) });
  await autopsy.waitFor();
  assert.ok((await autopsy.innerText()).includes('50.0%'));
  assert.ok((await autopsy.innerText()).includes('156.4'));
  assert.ok((await autopsy.innerText()).includes('='));
  await autopsy.click();
  const autopsyDetails = autopsy.locator('..');
  await autopsyDetails.getByText('藏品', { exact: true }).waitFor();
  assert.ok((await autopsyDetails.innerText()).includes('150'));
  await page.screenshot({ path: `${out}/autopsy-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 900 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  const box = await dialog.boundingBox();
  assert.ok(box.x >= 0 && box.x + box.width <= 391 && box.y + box.height <= 901);
  await page.screenshot({ path: `${out}/autopsy-compact.png`, fullPage: true });
  assert.equal(await readFile(source, 'utf8'), original);
  assert.deepEqual(errors, []);
  console.log('checkbox override persists; autopsy 50% contribution visible; controller appraisal 16; real run unchanged');
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, errors }, null, 2));
  await browser.close();
}
