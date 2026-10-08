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
const runId = `service-smoke-prerequisite-${Date.now().toString(36)}`;
const seed = JSON.parse(original);
seed.goals = { endingV: null, endingVI: null, preferences: {}, note: '', progress: {
  ending2_sandbox: { status: 'completed' }, ending3_beacon: { status: 'completed' },
  ending3_autopsy: { status: 'completed' }, ending3_tribute: { status: 'completed' },
} };
seed.relics = [];
seed.currentAreaKey = 'III';
const instance = seed.areas.III.instances.find(row => row.instanceId === seed.areas.III.activeInstanceId);
instance.actionPoints = 2;
instance.playerPosition = '0,0';
instance.strategy = { nodeWeights: {}, planningGoalIds: [], scoringOptions: { nodeScores: { '0,1': 10000 } } };
delete instance.dystopia;
for (const node of Object.values(instance.nodes)) {
  Object.assign(node, { resolvedCategoryId: 'node_type_020', observedCategoryId: 'node_type_020', templateHint: null,
    confirmedMarkIds: [], encounterId: null, completion: 'pending', completedCategoryId: null, visibility: 'revealed', fateRole: 'unknown' });
  delete node.merchantViewedShelves;
}
Object.assign(instance.nodes['0,0'], { completion: 'completed', completedCategoryId: 'node_type_020' });
Object.assign(instance.nodes['-1,0'], { resolvedCategoryId: 'node_type_008', observedCategoryId: 'node_type_008', confirmedMarkIds: ['node_mark_006'] });
Object.assign(instance.nodes['0,1'], { resolvedCategoryId: 'node_type_007', observedCategoryId: 'node_type_007' });
// Other floors are deliberately absent from this isolated map fixture.
for (const [key, area] of Object.entries(seed.areas)) if (key !== 'III') { area.instances = []; area.activeInstanceId = null; }
seed.componentBox = { capacity: 8, items: [
  { instanceId: 'seed-a', componentId: 'component_001', estimatedValue: 8, remainingUses: null, routeCandidate: false },
  { instanceId: 'seed-b', componentId: 'component_001', estimatedValue: 8, remainingUses: null, routeCandidate: false },
] };
const restored = await api('/api/runs/restore', { state: seed, runId });
const out = 'work/ui_prerequisites';
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const checks = [], errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
async function checked(name, run) { await run(); checks.push(name); console.log(name); }
async function settled() { await page.waitForFunction(() => !document.querySelector('.app-footer')?.textContent.includes('评分')); }
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  await page.getByText('是否已通过线人节点', { exact: true }).waitFor();
  await settled();
  await page.locator('.route-controls .segmented').getByRole('button', { name: '追猎', exact: true }).click();
  await settled();
  await checked('per-floor selection dialog; no targets enabled implicitly', async () => {
    await page.getByRole('button', { name: '规划', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '本层前置目标', exact: true });
    const target = dialog.getByRole('checkbox', { name: '失与得上贡', exact: true });
    assert.equal(await target.isChecked(), false);
    await target.check();
    await dialog.getByText('上贡2件自然物，损失仅作参考；作为软优先目标', { exact: true }).waitFor();
    await page.screenshot({ path: `${out}/selection-desktop.png`, fullPage: true });
    await page.setViewportSize({ width: 390, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    const box = await dialog.boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= 391 && box.y + box.height <= 901);
    await page.screenshot({ path: `${out}/selection-compact.png`, fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await dialog.getByRole('button', { name: '开始规划', exact: true }).click();
    await dialog.waitFor({ state: 'hidden' });
    await page.locator('.route-row').first().waitFor({ timeout: 90000 });
  });
  await checked('search ranks selected target and preserves actual resources', async () => {
    const row = page.locator('.route-row').first();
    assert.ok((await row.innerText()).includes('前置：1 / 1'));
    await row.locator('.route-step').filter({ has: page.locator('b', { hasText: '(-1,0)' }) }).click();
    await page.locator('.step-breakdown').getByText('上贡损失（参考，不扣规划分）', { exact: true }).waitFor();
    await page.screenshot({ path: `${out}/route-desktop.png`, fullPage: true });
    const saved = await api(`/api/runs/${runId}`, null, 'GET');
    assert.deepEqual(saved.state.resources, restored.state.resources);
    assert.deepEqual(saved.state.componentBox, restored.state.componentBox);
    assert.deepEqual(saved.state.goals.progress, restored.state.goals.progress);
    const active = saved.state.areas.III.instances[0];
    assert.deepEqual(active.strategy.planningGoalIds, ['ending3_trade']);
    assert.equal(active.nodes['-1,0'].completion, 'pending');
    assert.equal(active.playerPosition, '0,0');
    assert.equal(active.actionPoints, 2);
  });
  await checked('completed milestone with pending marker blocks planning and gives correction', async () => {
    const loaded = await api(`/api/runs/${runId}`, null, 'GET');
    await api(`/api/runs/${runId}`, { expectedRevision: loaded.revision, commands: [
      { type: 'goals', value: { progress: { ending3_trade: { status: 'completed' } } } },
    ] }, 'PATCH');
    await page.reload();
    await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
    await settled();
    await page.getByRole('button', { name: '规划', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '结局进度与地图冲突', exact: true });
    await dialog.getByRole('alert').waitFor();
    assert.ok((await dialog.innerText()).includes('(-1,0)'));
    assert.equal(await dialog.getByRole('button', { name: '开始规划', exact: true }).count(), 0);
    await page.screenshot({ path: `${out}/conflict-desktop.png`, fullPage: true });
  });
  assert.equal(await readFile(source, 'utf8'), original);
  assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, checks, errors }, null, 2));
  await browser.close();
}
