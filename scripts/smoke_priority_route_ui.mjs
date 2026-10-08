import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { filterRoutes } from '../frontend/src/routeFilters.js';
import { num } from '../frontend/src/model.js';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const source = 'work/app_data/runs/run-muyxp5qy-a9irnda/playtime.json';
const original = await readFile(source, 'utf8');
const token = (await (await fetch(base + '/api/session')).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const value = await response.json();
  assert.ok(response.ok, JSON.stringify(value));
  return value;
}
async function waitJob(id) {
  for (let i = 0; i < 450; i++) {
    const job = await api('/api/jobs/' + id, null, 'GET');
    if (job.status === 'completed') return job.result;
    assert.ok(!['failed', 'cancelled'].includes(job.status), JSON.stringify(job));
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error('job timeout');
}
const runId = `service-smoke-priority-${Date.now().toString(36)}`;
await api('/api/runs/restore', { runId, state: JSON.parse(original) });
const out = 'work/ui_priority_routes';
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  await page.getByRole('button', { name: '规划', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '本层前置目标' });
  const requested = page.waitForResponse(response => response.url().includes('/jobs/plan') && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: '开始规划', exact: true }).click();
  const result = await waitJob((await (await requested).json()).jobId);
  await page.locator('.route-choice').first().waitFor();
  const panel = page.locator('.route-priority-filters');
  assert.equal(await panel.getByRole('checkbox').count(), result.priorityTargets.length);
  async function assertRoutes(ids, mode = 'all') {
    const expected = filterRoutes(result, ids, mode, 5);
    await page.waitForFunction(count => document.querySelectorAll('.route-choice').length === count, expected.length);
    const actual = await page.locator('.route-choice b').allTextContents();
    assert.deepEqual(actual.map(text => Number(text.replace(/[^\d.-]/g, ''))), expected.map(route =>
      Number(num(route.metrics.weightedValue).replace(/,/g, ''))));
    if (expected.length) {
      await page.getByRole('button', { name: '选择路线 1', exact: true }).click();
      const drawn = await page.locator('.map-node.route-node').evaluateAll(nodes => nodes.map(node => node.dataset.nodeId));
      for (const step of expected[0].steps) assert.ok(drawn.includes(step.entered));
    }
    return expected;
  }
  await assertRoutes([]);
  const label = id => result.priorityTargets.find(target => target.id === id).name;
  await panel.getByRole('checkbox', { name: label('ending2_sandbox'), exact: true }).check();
  await assertRoutes(['ending2_sandbox']);
  await panel.getByRole('checkbox', { name: label('ending3_autopsy'), exact: true }).check();
  const combined = await assertRoutes(['ending2_sandbox', 'ending3_autopsy']);
  assert.ok(combined.length > 0 && combined[0].metrics.weightedValue < result.routes[0].metrics.weightedValue);
  await page.screenshot({ path: `${out}/combined-dark.png`, fullPage: true });
  await panel.getByRole('button', { name: '任一相关', exact: true }).click();
  await assertRoutes(['ending2_sandbox', 'ending3_autopsy'], 'any');
  await panel.getByRole('button', { name: '清除路线筛选', exact: true }).click();
  await panel.getByRole('checkbox', { name: label('ending3_tribute'), exact: true }).check();
  await assertRoutes(['ending3_tribute'], 'any');
  assert.ok(await page.getByText('已搜索的可行路线中没有符合当前筛选条件的路线', { exact: true }).isVisible());
  await panel.getByRole('button', { name: '清除路线筛选', exact: true }).click();
  await assertRoutes([]);
  await page.getByRole('button', { name: '切换到明亮模式', exact: true }).click();
  await page.screenshot({ path: `${out}/all-light.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 900 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await page.screenshot({ path: `${out}/compact.png`, fullPage: true });
  assert.deepEqual(errors, []);
  assert.equal(await readFile(source, 'utf8'), original);
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, searchComplete: result.searchComplete,
    expandedStates: result.expandedStates, groupCount: result.routeGroups.length, errors }, null, 2));
  console.log(JSON.stringify({ runId, groups: result.routeGroups.length, realRunUnchanged: true }));
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await browser.close();
}
