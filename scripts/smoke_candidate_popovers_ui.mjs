import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8772';
const out = 'work/ui_focused_followup';
await mkdir(out, { recursive: true });
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method,
    headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  assert.ok(response.ok, JSON.stringify(data));
  return data;
}
const runId = `ui-focused-${Date.now().toString(36)}`;
let loaded = await api('/api/runs', { runId, squadId: 'squad_014' });
const templates = await api('/api/map-templates?areaKey=II', null, 'GET');
loaded = await api(`/api/runs/${runId}/manual-map`, {
  expectedRevision: loaded.revision, areaKey: 'II', templateId: templates.templates[0].id, actionPoints: 5,
});
const instance = loaded.state.areas.II.instances[0];
const nodeId = Object.values(instance.nodes).find(node => node.id !== '0,0' && !node.resolvedCategoryId).id;
const unknownId = Object.values(instance.nodes).find(node => node.id !== nodeId && node.id !== '0,0' && !node.resolvedCategoryId).id;
loaded = await api(`/api/runs/${runId}`, { expectedRevision: loaded.revision, commands: [
  { type: 'node', areaKey: 'II', nodeId, changes: { categoryId: 'node_type_006', visibility: 'revealed', completion: 'pending' } },
  { type: 'nodeReset', areaKey: 'II', nodeId: unknownId, categoryId: 'unknown_mystery' },
] }, 'PATCH');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
async function bounds(locator, label, viewport) {
  const rect = await locator.boundingBox();
  assert.ok(rect && rect.x >= -1 && rect.y >= -1 && rect.x + rect.width <= viewport.width + 1 &&
    rect.y + rect.height <= viewport.height + 1, `${label}: ${JSON.stringify(rect)} in ${JSON.stringify(viewport)}`);
  return rect;
}
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id &&
    !document.querySelector('input[aria-label="上传地图截图"]')?.disabled, runId);
  await page.getByRole('button', { name: '添加干员与编队', exact: true }).click();
  const filters = page.getByRole('group', { name: '筛选职业' });
  assert.equal(await filters.getByRole('checkbox').count(), 8);
  assert.equal(await filters.locator('input:checked').count(), 8);
  const rarities = await page.locator('.picker-results small').allTextContents();
  const values = rarities.map(text => Number(text.match(/^(\d)★/)?.[1] || 0));
  assert.deepEqual(values, [...values].sort((a, b) => b - a));
  for (const name of ['先锋', '近卫', '重装', '狙击', '术师', '医疗', '辅助'])
    await filters.getByRole('checkbox', { name, exact: true }).uncheck();
  assert.ok((await page.locator('.picker-results small').allTextContents()).every(text => /特种|待确认/.test(text)));
  await page.screenshot({ path: `${out}/operator-filter.png` });
  checks.push('eight default-checked profession filters, combined filtering, rarity-descending candidates');
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click();
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1024, height: 600 }, { width: 390, height: 740 }]) {
    await page.setViewportSize(viewport);
    await page.locator(`.main-workspace [data-node-id="${nodeId}"]`).click();
    const detail = page.getByRole('dialog', { name: `节点编辑 ${nodeId}`, exact: true });
    await bounds(detail, 'node detail', viewport);
    await detail.locator('.score-details').first().waitFor();
    const body = detail.locator('.node-popover-body');
    await body.evaluate(element => { element.querySelectorAll('details').forEach(row => { row.open = true; }); });
    await bounds(detail.locator('footer'), 'footer after expanding long score details', viewport);
    await body.evaluate(element => { element.scrollTop = element.scrollHeight; });
    await bounds(detail, 'expanded node detail', viewport);
    await page.screenshot({ path: `${out}/node-${viewport.width}.png` });
    await body.evaluate(element => { element.scrollTop = 0; });
    const poolButton = detail.getByRole('button', { name: '藏品池', exact: true }).first();
    await poolButton.click();
    const pool = page.locator('.reward-pool-popover');
    await bounds(pool, 'reward pool', viewport);
    await page.screenshot({ path: `${out}/pool-${viewport.width}.png` });
    await pool.getByRole('button', { name: '关闭藏品池', exact: true }).click();
    await detail.getByRole('button', { name: '关闭节点详情', exact: true }).click();
    checks.push(`long node details and reward pool fit ${viewport.width}x${viewport.height}`);
  }
  await page.setViewportSize({ width: 1024, height: 600 });
  const unknown = page.locator(`.main-workspace [data-node-id="${unknownId}"]`);
  if (await unknown.count()) {
    await unknown.hover();
    const sheet = page.locator('.hover-sheet');
    await sheet.waitFor();
    await page.waitForFunction(() => {
      const rect = document.querySelector('.hover-sheet')?.getBoundingClientRect();
      return rect && rect.bottom <= innerHeight;
    });
    await bounds(sheet, 'hover probabilities', { width: 1024, height: 600 });
    checks.push('hover summary fits short desktop window');
  }
  loaded = await api(`/api/runs/${runId}`, { expectedRevision: loaded.revision, commands: [
    { type: 'node', areaKey: 'II', nodeId, changes: { completion: 'completed' } },
  ] }, 'PATCH');
  await page.reload();
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id &&
    !document.querySelector('input[aria-label="上传地图截图"]')?.disabled, runId);
  await page.locator(`.main-workspace [data-node-id="${nodeId}"]`).click();
  let detail = page.getByRole('dialog', { name: `节点编辑 ${nodeId}`, exact: true });
  await detail.getByRole('button', { name: '节点状态', exact: true }).click();
  await detail.getByRole('checkbox', { name: /流窜/ }).check();
  await detail.getByRole('button', { name: '确认更新', exact: true }).click();
  await detail.waitFor({ state: 'hidden' });
  let saved = await api(`/api/runs/${runId}`, null, 'GET');
  let node = saved.state.areas.II.instances[0].nodes[nodeId];
  assert.ok(node.confirmedMarkIds.includes('node_mark_001'));
  assert.equal(node.residentCleared, false);
  assert.equal(node.completedCategoryId, 'node_type_006');
  await page.locator(`.main-workspace [data-node-id="${nodeId}"]`).click();
  detail = page.getByRole('dialog', { name: `节点编辑 ${nodeId}`, exact: true });
  await detail.getByRole('button', { name: '已完成', exact: true }).click();
  await detail.getByRole('button', { name: '确认更新', exact: true }).click();
  await detail.waitFor({ state: 'hidden' });
  saved = await api(`/api/runs/${runId}`, null, 'GET');
  node = saved.state.areas.II.instances[0].nodes[nodeId];
  assert.ok(!node.confirmedMarkIds.includes('node_mark_001'));
  assert.equal(node.completedCategoryId, 'node_type_006');
  checks.push('manual resident marking on a completed node is not auto-cleared; explicit completion preserves original identity');
  assert.deepEqual(errors, []);
  await writeFile(`${out}/ui-result.json`, JSON.stringify({ runId, checks, errors }, null, 2));
  console.log(JSON.stringify({ runId, checks, errors }, null, 2));
} finally {
  await browser.close();
}
