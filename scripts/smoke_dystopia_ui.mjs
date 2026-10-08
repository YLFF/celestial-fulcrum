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
const out = resolve('work/ui_dystopia'); await mkdir(out, { recursive: true });
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json(); assert.ok(response.ok, JSON.stringify(data)); return data;
}
const runId = `ui-dystopia-${Date.now().toString(36)}`;
await api('/api/runs/restore', { state: JSON.parse(original), runId });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
const dialog = () => page.getByRole('dialog');
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  for (const [floor, count, area, sourceNode, ideology, policy] of [[3, 26, 'III', '-1,2', '002', '013'], [1, 13, 'I', '-2,0', '005', '012']]) {
    await page.getByLabel('上传地图截图', { exact: true }).setInputFiles(resolve(`samples/maps/desktop_floor${floor}_dystopia.png`));
    await page.waitForFunction(() => [...document.querySelectorAll('[role="dialog"] button')].some(button => button.textContent.includes('开始识别') && !button.disabled));
    await dialog().getByRole('button', { name: '开始识别', exact: true }).click();
    await dialog().getByRole('button', { name: '确认入局', exact: true }).waitFor({ timeout: 90000 });
    assert.equal(await dialog().locator('.map-node').count(), count);
    assert.equal(await dialog().getByLabel('本层实托邦', { exact: true }).isChecked(), true);
    assert.equal(await dialog().getByLabel('实托邦理念', { exact: true }).inputValue(), `dystopia_${ideology}`);
    assert.equal(await dialog().getByLabel('实托邦方针', { exact: true }).inputValue(), `dystopia_${policy}`);
    assert.equal(await dialog().getByLabel('理想源', { exact: true }).inputValue(), sourceNode);
    assert.equal(await dialog().locator(`[data-node-id="${sourceNode}"] .ideal-source-label`).count(), 1);
    await page.screenshot({ path: `${out}/floor${floor}-preview.png`, fullPage: true });
    if (floor === 1) {
      await dialog().getByLabel('地图更新方式', { exact: true }).selectOption('new');
      await dialog().getByLabel('理想源', { exact: true }).selectOption('');
      assert.equal(await dialog().locator('.ideal-source-label').count(), 0);
    }
    const receipt = page.waitForResponse(response => response.url().endsWith('/confirm-recognition'));
    await dialog().getByRole('button', { name: '确认入局', exact: true }).click();
    const imported = await receipt;
    assert.ok(imported.ok(), await imported.text());
    await dialog().waitFor({ state: 'hidden' });
    const saved = await api(`/api/runs/${runId}`, null, 'GET');
    const slot = saved.state.areas[area], map = slot.instances.find(row => row.instanceId === slot.activeInstanceId);
    assert.equal(map.dystopia.ideologyId, `dystopia_${ideology}`);
    assert.equal(map.dystopia.idealSourceNodeId, floor === 1 ? null : sourceNode);
    assert.equal(map.nodes[sourceNode].resolvedCategoryId, floor === 1 ? null : 'node_type_002');
    assert.equal(map.nodes[map.playerPosition].completion, 'completed');
    if (floor === 1) {
      await page.getByRole('button', { name: '编辑实托邦', exact: true }).click();
      await dialog().getByLabel('理想源', { exact: true }).selectOption(sourceNode);
      await dialog().getByRole('button', { name: '确认更新', exact: true }).click();
      await dialog().waitFor({ state: 'hidden' });
      const edited = await api(`/api/runs/${runId}`, null, 'GET');
      const current = edited.state.areas.I.instances.find(row => row.instanceId === edited.state.areas.I.activeInstanceId);
      assert.equal(current.nodes[sourceNode].resolvedCategoryId, 'node_type_002');
    }
    await page.screenshot({ path: `${out}/floor${floor}-imported.png`, fullPage: true });
    checks.push(`floor${floor}: preview, source review, confirmed snapshot and completed position`);
  }
  await page.getByRole('button', { name: '编辑实托邦', exact: true }).click();
  await dialog().locator('[data-node-id="2,0"]').click();
  await dialog().getByRole('button', { name: '纳入范围', exact: true }).click();
  await dialog().locator('[data-node-id="-1,0"]').click();
  await dialog().getByRole('button', { name: '移出范围', exact: true }).click();
  await dialog().getByRole('button', { name: '确认更新', exact: true }).click();
  await dialog().waitFor({ state: 'hidden' });
  let saved = await api(`/api/runs/${runId}`, null, 'GET');
  let map = saved.state.areas.I.instances.find(row => row.instanceId === saved.state.areas.I.activeInstanceId);
  assert.ok(map.dystopia.affectedNodeIds.includes('2,0'));
  assert.ok(!map.dystopia.affectedNodeIds.includes('-1,0'));
  await page.locator('.main-workspace [data-node-id="2,0"]').click();
  await dialog().getByRole('button', { name: '节点状态', exact: true }).click();
  await dialog().getByLabel('实托邦覆盖', { exact: true }).selectOption('outside');
  await dialog().getByRole('button', { name: '确认更新', exact: true }).click();
  await dialog().waitFor({ state: 'hidden' });
  saved = await api(`/api/runs/${runId}`, null, 'GET');
  map = saved.state.areas.I.instances.find(row => row.instanceId === saved.state.areas.I.activeInstanceId);
  assert.ok(!map.dystopia.affectedNodeIds.includes('2,0'));
  checks.push('main map range editor and per-node override preserve disconnected coverage');
  await page.getByRole('button', { name: '编辑实托邦', exact: true }).click();
  await dialog().getByLabel('实托邦理念', { exact: true }).selectOption('dystopia_008');
  assert.equal(await dialog().getByLabel('理想源', { exact: true }).isDisabled(), true);
  assert.equal(await dialog().getByLabel('理想源', { exact: true }).inputValue(), '');
  await page.screenshot({ path: `${out}/soil-editor-dark.png`, fullPage: true });
  await dialog().getByRole('button', { name: '确认更新', exact: true }).click();
  await dialog().waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: '切换到明亮模式', exact: true }).click();
  await page.screenshot({ path: `${out}/light.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${out}/compact.png`, fullPage: true });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  assert.ok(await page.evaluate(() => {
    const effect = document.querySelector('.main-workspace .dystopia-label').getBoundingClientRect();
    const template = document.querySelector('.main-workspace .map-template').getBoundingClientRect();
    return effect.top >= template.bottom;
  }));
  checks.push('fertile soil removes source; light and narrow layouts do not overflow');
  assert.deepEqual(errors, []);
  assert.equal(await readFile(source, 'utf8'), original);
  if (realBefore != null) assert.equal(await readFile(real, 'utf8'), realBefore);
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, checks, errors }, null, 2));
  await browser.close();
}
console.log(checks.join('\n'));
