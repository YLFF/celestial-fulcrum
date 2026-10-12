import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8770';
const out = 'work/one_step_advice_ui';
await mkdir(out, { recursive: true });
const token = (await (await fetch(base + '/api/session')).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const value = await response.json();
  assert.ok(response.ok, JSON.stringify(value));
  return value;
}
async function waitJob(id) {
  for (let i = 0; i < 250; i++) {
    const job = await api('/api/jobs/' + id, null, 'GET');
    if (job.status === 'completed') return job;
    assert.ok(!['failed', 'cancelled'].includes(job.status), JSON.stringify(job));
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error('job timeout');
}

const browser = await chromium.launch({ headless: true });
const errors = [], reports = [];
try {
  for (const [label, source] of [['floor3', 'run-muyxp5qy-a9irnda'], ['floor4', 'run-mux3hoew-u416e3w']]) {
    const path = `work/app_data/runs/${source}/playtime.json`;
    const original = await readFile(path, 'utf8');
    const runId = `service-smoke-advice-${label}-${Date.now().toString(36)}`;
    const initial = await api('/api/runs/restore', { state: JSON.parse(original), runId });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(id => {
      localStorage.setItem('fulcrum-run', id);
      localStorage.setItem('fulcrum-theme', 'dark');
    }, runId);
    await page.goto(base);
    await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
    await page.getByRole('button', { name: '一步路径建议', exact: true }).click();
    await page.getByRole('button', { name: '规划', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '本层前置目标' });
    await dialog.getByRole('spinbutton', { name: '路径搜索上限', exact: true }).fill('10000');
    const request = page.waitForResponse(r => r.url().includes('/jobs/plan') && r.request().method() === 'POST');
    await dialog.getByRole('button', { name: '开始规划', exact: true }).click();
    const response = await request;
    assert.equal(response.request().postDataJSON().mode, 'advice');
    const job = await waitJob((await response.json()).jobId);
    const result = job.result;
    await page.locator('.advice-choice').first().waitFor();
    assert.equal(await page.locator('.advice-row').count(), 5);
    await page.locator('.advice-choice').first().click();
    const drawn = await page.locator('.connections .route-edge').count();
    assert.equal(drawn, 1, 'only the first move is shown on the map');
    await page.locator('.map-frame').screenshot({ path: `${out}/${label}-map.png` });
    await page.locator('.route-section').screenshot({ path: `${out}/${label}-advice.png` });
    await page.locator('.advice-row').first().getByText('后续方向与资源取舍', { exact: true }).click();
    assert.ok(await page.locator('.advice-row').first().locator('.advice-continuation').count() >= 3);
    if (label === 'floor4') {
      const random = page.locator('.advice-row').filter({ hasText: '小八戒随机前往' });
      await random.getByRole('button', { name: /选择建议/ }).click();
      assert.equal(await page.locator('.connections .route-edge').count(), 0);
      await random.getByRole('button', { name: '查看落点分布', exact: true }).click();
      assert.equal(await random.locator('.advice-branches > div').count(), result.metrics.randomLandings);
      await random.screenshot({ path: `${out}/floor4-random.png` });
    }
    if (label === 'floor3') {
      const panel = page.locator('.route-priority-filters');
      const filter = panel.getByRole('checkbox').first();
      await filter.check();
      const selectedId = result.priorityTargets[0].id;
      const expected = result.suggestions.filter(row => row.relatedGoalIds.includes(selectedId)).slice(0, 5);
      await page.waitForFunction(n => document.querySelectorAll('.advice-row').length === n, expected.length);
      await filter.uncheck();
      await page.getByRole('button', { name: '全局路径规划', exact: true }).click();
      await page.getByRole('button', { name: '规划', exact: true }).click();
      const pending = page.waitForResponse(r => r.url().includes('/jobs/plan') && r.request().method() === 'POST');
      await page.getByRole('button', { name: '开始规划', exact: true }).click();
      const globalJob = await waitJob((await (await pending).json()).jobId);
      assert.equal(globalJob.result.mode, 'global');
      await page.locator('.route-choice').first().waitFor();
      await page.getByRole('button', { name: '一步路径建议', exact: true }).click();
      await page.locator('.advice-choice').first().waitFor();
      assert.equal(await page.locator('.advice-row').count(), 5, 'advice cache survives the global comparison');
      await page.getByRole('button', { name: '切换到明亮模式', exact: true }).click();
      await page.locator('.route-section').screenshot({ path: `${out}/floor3-light.png` });
    }
    await page.setViewportSize({ width: 390, height: 900 });
    await page.locator('.route-heading').scrollIntoViewIfNeeded();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: `${out}/${label}-mobile.png` });
    const current = await api(`/api/runs/${runId}`, null, 'GET');
    assert.equal(current.revision, initial.revision, 'planning does not change the save');
    assert.equal(await readFile(path, 'utf8'), original);
    reports.push({ runId, label, metrics: result.metrics, expandedStates: result.expandedStates,
      recommendations: result.suggestions.slice(0, 5).map(row => ({ id: row.id, labels: row.labels,
        firstPoints: row.firstPoints, lookaheadPoints: row.lookaheadPoints })) });
    await page.close();
  }
  assert.deepEqual(errors, []);
  await writeFile(`${out}/results.json`, JSON.stringify({ reports, errors }, null, 2));
  console.log(JSON.stringify({ reports, errors }));
} finally {
  await browser.close();
}
