import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const source = 'work/app_data/runs/run-mux3hoew-u416e3w/playtime.json';
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
    if (job.status === 'completed') return job;
    assert.ok(!['failed', 'cancelled'].includes(job.status), JSON.stringify(job));
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error('job timeout');
}
const runId = `service-smoke-map-beta-${Date.now().toString(36)}`;
const bootstrapId = runId + '-raw';
let loaded = await api('/api/runs', { runId: bootstrapId, squadId: 'squad_001' });
const upload = new FormData();
upload.append('file', new Blob([await readFile('samples/maps/bluestacks_floor_3.png')], { type: 'image/png' }), 'floor3.png');
const assetResponse = await fetch(base + '/api/images', { method: 'POST', headers: { 'X-Fulcrum-Token': token }, body: upload });
const asset = await assetResponse.json();
assert.ok(assetResponse.ok);
const job = await waitJob((await api(`/api/runs/${bootstrapId}/jobs/recognize`, { expectedRevision: loaded.revision, assetId: asset.assetId, includeResources: false })).jobId);
assert.ok(job.result.success);
loaded = await api(`/api/runs/${bootstrapId}/confirm-recognition`, { expectedRevision: loaded.revision, jobId: job.jobId, areaKey: 'III', resourceFields: [] });
const seed = structuredClone(loaded.state), map = seed.areas.III.instances[0];
const clearingIds = job.result.nodes.filter(row => row.categoryId === 'node_type_020' && row.id !== '0,0' && row.id !== map.playerPosition).map(row => row.id);
assert.ok(clearingIds.length >= 3);
const [a, b, c] = clearingIds;
for (const [id, category, event, completed] of [[a, 'node_type_011', null, false], [b, 'node_type_006', null, false], [c, 'node_type_006', 'encounter_009', true]]) {
  Object.assign(map.nodes[id], { observedCategoryId: category, resolvedCategoryId: category, visibility: 'revealed',
    completion: completed ? 'completed' : 'pending', completedCategoryId: completed ? category : null,
    confirmedMarkIds: [], encounterId: event });
}
map.actionPoints = 2;
map.strategy.planningGoalIds = [];
map.dystopia = { active: true, ideologyId: 'dystopia_001', policyId: 'dystopia_011',
  affectedNodeIds: [a, b], uncertainNodeIds: [c], idealSourceNodeId: null };
seed.componentBox.items = [
  { instanceId: 'engine-test', componentId: 'component_015', remainingUses: 3, estimatedValue: 1, routeCandidate: false },
  { instanceId: 'wheel-test', componentId: 'component_016', remainingUses: 1, estimatedValue: 1, routeCandidate: true },
  { instanceId: 'pig-test', componentId: 'component_019', remainingUses: 1, estimatedValue: 1, routeCandidate: true },
];
seed.goals.progress = {};
seed.relics = [];
await api('/api/runs/restore', { runId, state: seed });
const catalog = await api('/api/catalog', null, 'GET');
const entries = Object.fromEntries(Object.values(catalog).filter(Array.isArray).flat().filter(row => row.id).map(row => [row.id, row]));
const out = 'work/ui_map_beta';
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const checks = [], errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
async function check(name, fn) { await fn(); checks.push(name); console.log(name); }
async function settled() { await page.waitForFunction(() => !document.querySelector('.app-footer')?.textContent.includes('评分')); }
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  await settled();
  await check('ten tabs close/reopen without deleting maps', async () => {
    const tabs = page.getByRole('tablist', { name: '地图槽位' });
    assert.equal(await tabs.getByRole('tab').count(), 10);
    await page.getByRole('button', { name: '关闭IV · 追忆页签', exact: true }).click();
    assert.equal(await tabs.getByRole('tab').count(), 9);
    await page.getByRole('button', { name: '恢复地图页签', exact: true }).click();
    await page.locator('.area-add-menu').getByRole('button', { name: 'IV · 追忆', exact: true }).click();
    assert.equal(await tabs.getByRole('tab').count(), 10);
    await tabs.getByRole('tab', { name: 'III · 血色空脉', exact: true }).click();
    await settled();
  });
  await check('single candidate filter, crossfade assets, centered borderless coverage', async () => {
    await page.getByRole('checkbox', { name: '秘境行商', exact: true }).check();
    assert.ok(await page.locator('.candidate-position').count() > 0);
    await page.locator('.candidate-overlay').first().waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('img.candidate-overlay')].every(img => img.complete && img.naturalWidth > 0));
    await page.getByRole('checkbox', { name: '诡意行商', exact: true }).check();
    assert.equal(await page.getByRole('checkbox', { name: '秘境行商', exact: true }).isChecked(), false);
    await page.getByRole('checkbox', { name: '诡意行商', exact: true }).uncheck();
    const alignment = await page.evaluate(id => {
      const disc = document.querySelector(`[data-node-id="${id}"] .node-disc`).getBoundingClientRect();
      const zone = document.querySelector('.dystopia-zone').getBoundingClientRect();
      return { x: Math.abs(disc.x + disc.width / 2 - zone.x - zone.width / 2), y: Math.abs(disc.y + disc.height / 2 - zone.y - zone.height / 2),
        stroke: getComputedStyle(document.querySelector('.dystopia-zone')).stroke };
    }, a);
    assert.ok(alignment.x < 1 && alignment.y < 1, JSON.stringify(alignment));
    assert.equal(alignment.stroke, 'none');
    await page.screenshot({ path: `${out}/desktop-map.png`, fullPage: true });
  });
  await check('map overlays remain fixed while zooming, reserve edits rescore', async () => {
    assert.ok(await page.getByText('导入地图或更新探索进度：', { exact: true }).isVisible());
    assert.equal(await page.getByRole('button', { name: '本层策略', exact: true }).count(), 0);
    assert.equal(await page.locator('.map-concepts strong').textContent(), '移动后应刷新地图并确认已完成节点');
    const overlay = await page.locator('.map-guidance-row').boundingBox();
    await page.getByRole('button', { name: '放大地图', exact: true }).click();
    const zoomed = await page.locator('.map-guidance-row').boundingBox();
    assert.deepEqual(zoomed, overlay);
    await page.getByRole('button', { name: '重置地图缩放', exact: true }).click();
    const input = page.getByLabel('路线规划预留源石锭', { exact: true });
    const save = page.getByRole('button', { name: '保存路线规划预留源石锭并重新评分', exact: true });
    assert.equal(await input.inputValue(), '0');
    await input.fill('-1');
    assert.ok(await save.isDisabled());
    await input.fill('1.5');
    assert.ok(await save.isDisabled());
    const before = await api(`/api/runs/${runId}`, null, 'GET');
    const requests = await page.evaluate(() => performance.getEntriesByType('resource').filter(row => row.name.includes('/jobs/score')).length);
    await input.fill('30');
    await save.click();
    await page.waitForFunction(count => performance.getEntriesByType('resource').filter(row => row.name.includes('/jobs/score')).length > count, requests);
    await settled();
    const saved = await api(`/api/runs/${runId}`, null, 'GET');
    assert.ok(saved.revision > before.revision);
    assert.equal(saved.state.areas.III.instances[0].strategy.scoringOptions.merchantReserve, 30);
    await page.getByRole('button', { name: '编辑实托邦 / 乌托邦', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '本层实托邦 / 乌托邦', exact: true });
    assert.equal(await dialog.getByLabel('本层乌托邦', { exact: true }).count(), 0);
    await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  });
  await check('per-search inventory toggles and solid curved arrows', async () => {
    await page.locator('.route-controls .segmented').getByRole('button', { name: '追猎', exact: true }).click();
    await settled();
    await page.getByRole('button', { name: '规划', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '本层前置目标' });
    const engineName = entries.component_015.name, pigName = entries.component_019.name;
    await dialog.getByRole('button', { name: '不使用' + engineName, exact: true }).click();
    assert.ok(await dialog.getByRole('button', { name: '使用' + engineName, exact: true }).isVisible());
    assert.ok(await dialog.getByRole('button', { name: '使用' + pigName, exact: true }).isDisabled());
    await page.screenshot({ path: `${out}/planning-items.png`, fullPage: true });
    await dialog.getByRole('button', { name: '开始规划', exact: true }).click();
    await page.locator('.route-row').first().waitFor({ timeout: 90000 });
    const paths = page.locator('path.route-edge');
    assert.ok(await paths.count() > 0);
    assert.match(await paths.first().getAttribute('d'), / Q /);
    assert.ok((await paths.first().getAttribute('marker-end')).startsWith('url(#'));
    assert.equal(await paths.first().evaluate(el => getComputedStyle(el).strokeDasharray), 'none');
    const planRequests = await page.evaluate(() => performance.getEntriesByType('resource').filter(row => row.name.includes('/jobs/plan')).length);
    assert.ok(planRequests > 0);
    const saved = await api(`/api/runs/${runId}`, null, 'GET');
    assert.deepEqual(saved.state.componentBox.items, seed.componentBox.items);
  });
  await check('recognize then review/merge two moves, event metadata survives', async () => {
    await page.getByLabel('上传地图截图').setInputFiles('samples/maps/bluestacks_floor_3.png');
    await page.getByRole('button', { name: '开始识别', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '确认识别结果', exact: true });
    await dialog.getByRole('heading', { name: '完成节点确认', exact: true }).waitFor({ timeout: 90000 });
    assert.ok(await dialog.getByRole('heading', { name: '本层合并预览', exact: true }).isVisible());
    assert.equal(await dialog.getByLabel('地图更新方式').inputValue(), 'merge');
    assert.ok(await dialog.getByRole('checkbox', { name: '确认完成 ' + a, exact: true }).isChecked());
    await dialog.getByLabel('补充事件 ' + b, { exact: true }).selectOption('encounter_010');
    assert.ok((await dialog.locator(`[data-node-id="${a}"]`).getAttribute('aria-label')).includes('狭路相逢'));
    await page.screenshot({ path: `${out}/merge-preview.png`, fullPage: true });
    const before = await api(`/api/runs/${runId}`, null, 'GET');
    assert.equal(before.state.areas.III.instances[0].nodes[b].completion, 'pending');
    await dialog.getByRole('button', { name: '确认入局', exact: true }).click();
    await dialog.waitFor({ state: 'hidden', timeout: 30000 });
    const saved = await api(`/api/runs/${runId}`, null, 'GET');
    const current = saved.state.areas.III.instances[0];
    assert.equal(saved.state.areas.III.instances.length, 1);
    assert.equal(current.nodes[a].resolvedCategoryId, 'node_type_011');
    assert.equal(current.nodes[a].completion, 'completed');
    assert.equal(current.nodes[b].encounterId, 'encounter_010');
    assert.equal(current.nodes[b].completion, 'completed');
    assert.equal(current.nodes[c].encounterId, 'encounter_009');
    assert.equal(current.nodes[c].completion, 'completed');
    assert.equal(await page.locator(`[data-node-id="${a}"] .completed-badge`).count(), 1);
  });
  await check('compact viewport no page overflow', async () => {
    await page.setViewportSize({ width: 390, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: `${out}/compact-map.png`, fullPage: true });
  });
  assert.deepEqual(errors, []);
  assert.equal(await readFile(source, 'utf8'), original);
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, checks, errors }, null, 2));
  await browser.close();
}
