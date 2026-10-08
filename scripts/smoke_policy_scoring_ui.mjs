import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const source = resolve('runs/true-run-001/playtime.json'), original = await readFile(source, 'utf8');
const real = resolve('work/app_data/runs/run-mux3hoew-u416e3w/playtime.json');
const realBefore = await readFile(real, 'utf8').catch(() => null);
const out = resolve('work/ui_policy_scoring'); await mkdir(out, { recursive: true });
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json(); assert.ok(response.ok, JSON.stringify(data)); return data;
}
const seed = JSON.parse(original), map = seed.areas.I.instances[0];
seed.goals = { endingV: 'ending2', endingVI: null, preferences: { ending3_trade: 'required' }, progress: {}, note: '' };
map.actionPoints = 5;
for (const row of Object.values(map.nodes)) {
  if (row.id === '0,0' || row.resolvedCategoryId === 'node_type_015') continue;
  Object.assign(row, { observedCategoryId: 'node_type_020', resolvedCategoryId: 'node_type_020', completion: 'pending',
    completedCategoryId: null, visibility: 'revealed', confirmedMarkIds: [], encounterId: null });
}
Object.assign(map.nodes['0,1'], { observedCategoryId: 'node_type_002', resolvedCategoryId: 'node_type_002' });
Object.assign(map.nodes['0,-1'], { observedCategoryId: 'node_type_008', resolvedCategoryId: 'node_type_008', confirmedMarkIds: ['node_mark_006'] });
Object.assign(map.nodes['1,-1'], { observedCategoryId: 'node_type_006', resolvedCategoryId: 'node_type_006', confirmedMarkIds: ['node_mark_005'], encounterId: 'encounter_023' });
Object.assign(map.nodes['-1,0'], { observedCategoryId: 'node_type_006', resolvedCategoryId: 'node_type_006', confirmedMarkIds: ['node_mark_002'], encounterId: 'encounter_022' });
Object.assign(map.nodes['1,0'], { observedCategoryId: 'unknown_mystery', resolvedCategoryId: null, visibility: 'hidden' });
map.dystopia = { active: true, ideologyId: 'dystopia_001', policyId: 'dystopia_011',
  affectedNodeIds: Object.keys(map.nodes), uncertainNodeIds: [], idealSourceNodeId: '0,1' };
const runId = `ui-policy-${Date.now().toString(36)}`;
await api('/api/runs/restore', { state: seed, runId });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 700 } });
const errors = [], checks = [], writes = [];
let externalRunChangedDuringTest = false;
page.on('pageerror', error => errors.push(error.message));
page.on('request', request => {
  const path = new URL(request.url()).pathname;
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method()) && path.startsWith('/api/runs/')) writes.push(path);
});
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
const dialog = () => page.getByRole('dialog');
async function settled() {
  await page.waitForFunction(() => !document.querySelector('.app-footer')?.textContent.includes('评分'));
}
async function open(id) {
  await page.locator(`.main-workspace [data-node-id="${id}"]`).click();
  await dialog().locator('.score-total').first().waitFor();
}
async function close() { await dialog().getByRole('button', { name: '关闭节点详情', exact: true }).click(); }
async function bounds() {
  await page.waitForFunction(() => {
    const rect = document.querySelector('.node-popover')?.getBoundingClientRect();
    return rect && rect.top >= 0 && rect.bottom <= innerHeight;
  });
  const result = await dialog().evaluate(element => {
    const rect = element.getBoundingClientRect(), footer = element.querySelector('footer').getBoundingClientRect();
    const body = element.querySelector('.node-popover-body');
    return { top: rect.top, bottom: rect.bottom, footerBottom: footer.bottom, height: innerHeight,
      scroll: body.scrollHeight, visible: body.clientHeight };
  });
  assert.ok(result.top >= 0 && result.bottom <= result.height && result.footerBottom <= result.height, JSON.stringify(result));
  return result;
}
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  await settled();
  await open('0,1');
  assert.ok((await dialog().locator('.policy-summary').innerText()).includes('经过扣现金 2 × 8'));
  assert.ok((await dialog().locator('.policy-summary').innerText()).includes('结算后击破理想源'));
  await bounds();
  await page.screenshot({ path: `${out}/source-dark.png`, fullPage: true });
  await close();
  checks.push('improvement and source cutoff have explicit score formulas');
  await open('0,-1');
  const natural = await dialog().locator('.reference-loss-summary').innerText();
  assert.ok(natural.includes('随机 2 件自然物 × 平均 250 效用分'));
  assert.ok(natural.includes('估价折算 −4 × 8'));
  assert.ok((await dialog().locator('.score-basis').innerText()).includes('不计普通两次交换的200分'));
  await page.screenshot({ path: `${out}/tribute-dark.png`, fullPage: true });
  await close();
  await open('-1,0');
  assert.ok((await dialog().locator('.score-basis').innerText()).includes('计划取得沙盘α'));
  await close();
  checks.push('ending options explain zero-point branches and separate utility/appraisal tribute losses');
  await open('1,0');
  await dialog().evaluate(element => element.querySelectorAll('details').forEach(row => { row.open = true; }));
  const long = await bounds();
  assert.ok(long.scroll > long.visible, JSON.stringify(long));
  await dialog().locator('.node-popover-body').evaluate(element => { element.scrollTop = element.scrollHeight; });
  await page.screenshot({ path: `${out}/long-dark.png`, fullPage: true });
  await page.setViewportSize({ width: 1440, height: 540 });
  await bounds();
  await page.screenshot({ path: `${out}/long-short-window.png`, fullPage: true });
  await close();
  checks.push('long probability detail scrolls inside the viewport, including after window resize');
  await page.getByRole('button', { name: '编辑实托邦', exact: true }).click();
  await dialog().getByLabel('实托邦理念', { exact: true }).selectOption('dystopia_008');
  await dialog().getByRole('button', { name: '确认更新', exact: true }).click();
  await dialog().waitFor({ state: 'hidden' });
  await settled();
  await open('2,0');
  assert.ok((await dialog().locator('.policy-summary').innerText()).includes('2 件自然物 × 2 估价 × 8'));
  await bounds();
  await page.screenshot({ path: `${out}/soil-dark.png`, fullPage: true });
  await close();
  await page.getByRole('button', { name: '切换到明亮模式', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await open('0,-1');
  await bounds();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await page.screenshot({ path: `${out}/tribute-light-compact.png`, fullPage: true });
  await close();
  checks.push('fertile soil keeps benefit and narrow/light detail remains bounded');
  const saved = await api(`/api/runs/${runId}`, null, 'GET');
  assert.equal(saved.state.resources.originiumIngot, seed.resources.originiumIngot);
  assert.deepEqual(saved.state.componentBox, seed.componentBox);
  assert.equal(await readFile(source, 'utf8'), original);
  // The player can edit their own run concurrently; audit our requests, not their file bytes.
  assert.ok(writes.every(path => path === `/api/runs/${runId}` || path.startsWith(`/api/runs/${runId}/`)), JSON.stringify(writes));
  if (realBefore != null) externalRunChangedDuringTest = await readFile(real, 'utf8') !== realBefore;
  assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, checks, errors, writes, externalRunChangedDuringTest }, null, 2));
  await browser.close();
}
console.log(checks.join('\n'));
