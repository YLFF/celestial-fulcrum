import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const sourcePath = resolve('runs/true-run-001/playtime.json');
const original = await readFile(sourcePath, 'utf8');
const out = resolve('work/ui_vision_shops'); await mkdir(out, { recursive: true });
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method, headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json(); assert.ok(response.ok, JSON.stringify(data)); return data;
}
const runId = `ui-vision-shops-${Date.now().toString(36)}`;
await api('/api/runs/restore', { state: JSON.parse(original), runId });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const checks = [], errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => { localStorage.setItem('fulcrum-run', id); localStorage.setItem('fulcrum-theme', 'dark'); }, runId);
const dialog = () => page.getByRole('dialog');
async function check(name, callback) { await callback(); checks.push(name); console.log(name); }
try {
  await page.goto(base);
  await page.waitForFunction(id => document.querySelector('.run-select')?.value === id, runId);
  await page.getByLabel('上传地图截图', { exact: true }).setInputFiles(resolve('samples/maps/desktop_floor2_yellow_shop.png'));
  const recognize = dialog().getByRole('button', { name: '开始识别', exact: true });
  await recognize.waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll('[role="dialog"] button')].some(button => button.textContent.includes('开始识别') && !button.disabled));
  await recognize.click();
  await dialog().getByRole('button', { name: '确认入局', exact: true }).waitFor({ timeout: 90000 });
  await check('preview shows both revealed exits, the shaded connector and current yellow shop', async () => {
    assert.equal(await dialog().locator('.map-node').count(), 17);
    for (const [key, name] of [['2,3', '险路尽头'], ['4,1', '险路尽头'], ['1,3', '林间空地'], ['0,2', '秘境行商']]) {
      assert.ok((await dialog().locator(`[data-node-id="${key}"]`).getAttribute('aria-label')).includes(name));
    }
    assert.equal(await dialog().getByLabel('玩家位置', { exact: true }).inputValue(), '0,2');
    assert.equal(await dialog().getByLabel('当前位置已完成', { exact: true }).isChecked(), true);
    await dialog().getByText('节点标记候选', { exact: true }).click();
    const mark = dialog().getByLabel('节点 0,3 线人与线索', { exact: true });
    assert.equal(await mark.isChecked(), true);
    await mark.uncheck();
    assert.equal(await dialog().locator('[data-node-id="0,3"] .mark-candidate').count(), 0);
    await mark.check();
    assert.equal(await dialog().locator('[data-node-id="0,3"] .mark-candidate').count(), 1);
    const before = await api(`/api/runs/${runId}`, null, 'GET');
    assert.equal(before.state.areas.II.instances.length, 0);
    await page.screenshot({ path: `${out}/preview.png`, fullPage: true });
  });
  await dialog().getByRole('button', { name: '确认入局', exact: true }).click();
  await dialog().waitFor({ state: 'hidden' });
  await page.waitForFunction(() => document.querySelector('[aria-label="地图区域"]')?.value === 'II');
  await check('confirmation imports the second-floor map and selects the completed player node', async () => {
    const saved = await api(`/api/runs/${runId}`, null, 'GET');
    const slot = saved.state.areas.II;
    const map = slot.instances.find(row => row.instanceId === slot.activeInstanceId);
    assert.equal(saved.state.currentAreaKey, 'II');
    assert.equal(map.templateId, 'floor-2-01');
    assert.equal(map.playerPosition, '0,2');
    assert.equal(map.nodes['0,2'].completion, 'completed');
    assert.deepEqual(map.nodes['0,3'].confirmedMarkIds, ['node_mark_002']);
    assert.equal(map.nodes['0,3'].encounterId, 'encounter_022');
    for (const [key, category] of [['2,3', 'node_type_015'], ['4,1', 'node_type_015'], ['1,3', 'node_type_020'], ['0,2', 'node_type_013']]) {
      assert.equal(map.nodes[key].observedCategoryId, category);
      if (category !== 'node_type_020') assert.equal(map.nodes[key].resolvedCategoryId, category);
    }
    assert.equal(await page.locator('.main-workspace .map-node.player-node').getAttribute('data-node-id'), '0,2');
    await page.screenshot({ path: `${out}/imported.png`, fullPage: true });
  });
  assert.equal(await readFile(sourcePath, 'utf8'), original);
  assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(`${out}/result.json`, JSON.stringify({ runId, checks, errors }, null, 2));
  await browser.close();
}
