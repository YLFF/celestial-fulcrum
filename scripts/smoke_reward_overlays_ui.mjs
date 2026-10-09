import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8767';
const out = resolve('work/ui_reward_overlays');
await mkdir(out, { recursive: true });
const token = (await (await fetch(`${base}/api/session`)).json()).token;
const seed = JSON.parse(await readFile(resolve('runs/true-run-001/playtime.json'), 'utf8'));
seed.goals = { endingV: null, endingVI: null, preferences: {}, progress: {}, note: '' };
const map = seed.areas.I.instances[0];
map.actionPoints = 3;
map.dystopia = { active: false, ideologyId: null, policyId: null, affectedNodeIds: [], uncertainNodeIds: [], idealSourceNodeId: null };
for (const node of Object.values(map.nodes)) {
  Object.assign(node, { observedCategoryId: 'node_type_001', resolvedCategoryId: 'node_type_001',
    completion: 'pending', completedCategoryId: null, visibility: 'revealed',
    confirmedMarkIds: [], candidateMarkIds: [], encounterId: null });
}
Object.assign(map.nodes['0,0'], { observedCategoryId: 'start', resolvedCategoryId: 'start', completion: 'completed' });
for (const id of ['0,1', '0,-1']) Object.assign(map.nodes[id], {
  observedCategoryId: 'unknown_mystery', resolvedCategoryId: null, visibility: 'hidden',
});
Object.assign(map.nodes['1,0'], { observedCategoryId: 'node_type_020', resolvedCategoryId: 'node_type_020', confirmedMarkIds: ['node_mark_007'] });
const runId = `ui-overlays-${Date.now().toString(36)}`;
const response = await fetch(`${base}/api/runs/restore`, { method: 'POST', headers: {
  'X-Fulcrum-Token': token, 'Content-Type': 'application/json',
}, body: JSON.stringify({ state: seed, runId }) });
assert.ok(response.ok, await response.text());

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => {
  localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark');
}, runId);
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  await page.waitForFunction(() => [...document.querySelectorAll('[data-node-id="1,0"] .node-value')]
    .some(row => row.textContent.includes('278.7')));
  await page.getByRole('checkbox', { name: '小八戒', exact: true }).check();
  const marked = await page.locator('.main-workspace .candidate-position').evaluateAll(nodes => nodes.map(row => row.dataset.nodeId).sort());
  assert.deepEqual(marked, ['0,-1', '0,1']);
  assert.equal(await page.locator('.main-workspace .candidate-overlay').count(), 0);
  assert.equal(await page.locator('.main-workspace .candidate-art').count(), 0);
  await page.screenshot({ path: resolve(out, 'desktop-filter.png'), fullPage: true });
  await page.getByRole('checkbox', { name: '小八戒', exact: true }).uncheck();
  await page.locator('.main-workspace [data-node-id="1,0"]').click();
  const dialog = page.getByRole('dialog');
  await dialog.getByText('藏果地自然物期望', { exact: true }).waitFor();
  await dialog.getByText('藏果地自然物的期望收益', { exact: true }).click();
  const details = await dialog.innerText();
  for (const name of ['板藤', '恋家果', '光彩松露']) assert.ok(details.includes(name));
  await page.screenshot({ path: resolve(out, 'fruit-details.png'), fullPage: true });
  await dialog.getByRole('button', { name: '关闭节点详情', exact: true }).click();
  await page.setViewportSize({ width: 980, height: 700 });
  await page.getByRole('checkbox', { name: '小八戒', exact: true }).check();
  await page.screenshot({ path: resolve(out, 'compact-filter.png'), fullPage: true });
  assert.deepEqual(errors, []);
  await writeFile(resolve(out, 'result.json'), JSON.stringify({ runId, marked, errors, fruitPoints: 278.7,
    checks: ['little eight candidates', 'no icon switching', 'localized fruit outcomes', 'desktop and compact viewports'] }, null, 2));
  console.log(JSON.stringify({ success: true, out, marked, errors }));
} finally {
  await browser.close();
}
