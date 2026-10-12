import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { routeNodeName } from '../frontend/src/model.js';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8768';
const out = 'work/ui_route_presentation';
await mkdir(out, { recursive: true });
const sourcePath = 'runs/true-run-001/playtime.json';
const original = await readFile(sourcePath, 'utf8');
const seed = JSON.parse(original), runId = 'ui-route-presentation-fixture';
seed.runId = runId;
seed.goals = { endingV: null, endingVI: null, progress: {}, note: '' };
const slot = seed.areas[seed.currentAreaKey];
const instance = slot.instances.find(row => row.instanceId === slot.activeInstanceId);
instance.strategy.planningGoalIds = [];
seed.componentBox = { capacity: 12, items: [
  { instanceId: 'mist-a', componentId: 'component_003', estimatedValue: 2, remainingUses: null, routeCandidate: false },
  { instanceId: 'mist-b', componentId: 'component_003', estimatedValue: 9, remainingUses: null, routeCandidate: false },
  { instanceId: 'corn-a', componentId: 'component_004', estimatedValue: 3, remainingUses: null, routeCandidate: false },
  { instanceId: 'unknown-a', componentId: 'component_008', estimatedValue: null, remainingUses: null, routeCandidate: false },
] };
seed.resources.totalEstimatedValue = 14;
const loaded = { runId, revision: 1, state: seed, goalSummary: { milestones: [] }, teamThresholds: {}, history: {} };
const steps = [
  { from: '0,0', entered: '0,1', arrived: '0,1', movement: 'walk', weightedValue: 100 },
  { from: '0,1', entered: '-1,1', arrived: '-1,1', movement: 'walk', weightedValue: 200 },
  { from: '-1,1', entered: '-2,0', arrived: '-2,-1', portalTransfer: true, movement: 'walk', weightedValue: 50 },
].map(step => ({ ...step, expectedPrefixCashAfter: 20, expectedPrefixAppraisalAfter: 14,
  scoreBreakdown: { nodeValue: step.weightedValue, revealValue: 0, recruitmentValue: 0, nodeTerms: [], revealTerms: [] } }));
const planning = { searchComplete: true, expandedStates: 3, randomMovement: { excludedItemInstanceIds: [] },
  scoring: { nodeValues: {} }, routes: [{ metrics: { weightedValue: 350 }, steps,
    goalType: 'exit', endNode: '-2,-1', remainingActionPoints: 0 }] };
const { token } = await (await fetch(base + '/api/session')).json();
const catalogResponse = await fetch(base + '/api/catalog', { headers: { 'X-Fulcrum-Token': token } });
assert.ok(catalogResponse.ok);
const catalog = await catalogResponse.json();
const nodeName = id => routeNodeName(id, instance.nodes, catalog.labels.nodeTypes);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => {
  localStorage.setItem('fulcrum-run', id);
  localStorage.setItem('fulcrum-theme', 'dark');
}, runId);
// Mock only the test run's state and jobs; never create or mutate a stored Playtime.
await page.route(/\/api\/runs(?:\/|$)/, async route => {
  const request = route.request(), path = new URL(request.url()).pathname;
  let data;
  if (path === '/api/runs') data = { runs: [{ runId, valid: true }] };
  else if (path === `/api/runs/${runId}`) data = loaded;
  else if (path.endsWith('/planning-check')) data = { valid: true, conflicts: [], selectedGoalIds: [], targets: [] };
  else if (path.includes('/jobs/')) {
    const kind = path.split('/').at(-1), options = request.postDataJSON();
    data = { jobId: `fixture-${kind}`, kind, status: 'completed', sourceRevision: 1, runId, options,
      progress: {}, stale: false, result: kind === 'plan' ? planning : { nodeValues: {} } };
  } else return route.fallback();
  await route.fulfill({ json: data });
});
const dialog = () => page.getByRole('dialog');
async function check(name, fn) { await fn(); checks.push(name); console.log(name); }
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id &&
    !document.querySelector('input[aria-label="上传地图截图"]')?.disabled, runId);
  await check('route types, portal names and coordinate tooltips', async () => {
    await page.getByRole('button', { name: '规划', exact: true }).click();
    await dialog().getByRole('button', { name: '开始规划', exact: true }).click();
    const labels = page.locator('.route-step b');
    await labels.first().waitFor();
    assert.deepEqual(await labels.allTextContents(), [nodeName('0,1'), nodeName('-1,1'),
      `${nodeName('-2,0')} → ${nodeName('-2,-1')}`]);
    assert.equal(await labels.first().getAttribute('title'), '(0,1)');
    assert.equal(await labels.nth(2).getAttribute('title'), '(-2,0) → (-2,-1)');
    assert.equal(await page.locator('.route-result > span').textContent(), `终点 ${nodeName('-2,-1')}`);
    await page.locator('.route-step').first().click();
    assert.equal(await page.locator('.step-breakdown h3').textContent(), `${nodeName('0,1')} · 100 分`);
    await page.locator('.route-section').screenshot({ path: `${out}/routes-desktop.png` });
  });
  await check('appraisal is prominent and responds to draft edits and appraisal actions', async () => {
    await page.getByRole('button', { name: '编辑零件箱', exact: true }).click();
    const total = dialog().getByRole('status', { name: '零件箱总估价' });
    assert.equal(await total.locator('b').textContent(), '14');
    assert.equal(await total.locator('small').textContent(), '1 件未估价');
    await dialog().getByRole('button', { name: '揭示节点+1', exact: true }).click();
    assert.equal(await total.locator('b').textContent(), '16');
    await dialog().getByLabel('当前估价', { exact: true }).nth(2).fill('8');
    assert.equal(await total.locator('b').textContent(), '21');
    const summary = await dialog().locator('.box-summary').boundingBox();
    const actions = await dialog().locator('.appraisal-actions').boundingBox();
    assert.ok(summary.y + summary.height <= actions.y + 1);
    await dialog().screenshot({ path: `${out}/box-desktop.png` });
    await page.setViewportSize({ width: 480, height: 900 });
    await dialog().screenshot({ path: `${out}/box-mobile.png` });
    const bounds = await total.boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 480);
    await dialog().getByRole('button', { name: '关闭', exact: true }).click();
  });
  await check('route names stay readable at narrow widths and in light mode', async () => {
    await page.locator('.route-section').screenshot({ path: `${out}/routes-mobile.png` });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole('button', { name: '切换到明亮模式', exact: true }).click();
    await page.locator('.route-section').screenshot({ path: `${out}/routes-light.png` });
    for (const label of await page.locator('.route-step b').all()) {
      assert.ok(await label.evaluate(el => el.scrollWidth <= el.clientWidth + 1));
    }
  });
  assert.deepEqual(errors, []);
  assert.equal(await readFile(sourcePath, 'utf8'), original);
  await writeFile(`${out}/report.json`, JSON.stringify({ checks, errors, sourceUnchanged: true }, null, 2));
  console.log(JSON.stringify({ checks, errors, sourceUnchanged: true }, null, 2));
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  console.error(JSON.stringify({ errors, text: await page.locator('body').innerText() }, null, 2));
  throw error;
} finally { await browser.close(); }
