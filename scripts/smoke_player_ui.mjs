import { createRequire } from 'node:module';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const out = resolve('work/ui_smoke');
await mkdir(out, {recursive: true});
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(`${base}${path}`, {method, headers: {'X-Fulcrum-Token': token, 'Content-Type': 'application/json'}, ...(body ? {body: JSON.stringify(body)} : {})});
  const value = await response.json(); assert.ok(response.ok, JSON.stringify(value)); return value;
}
const sourcePath = resolve('runs/true-run-001/playtime.json');
const original = await readFile(sourcePath, 'utf8');
const runId = `ui-smoke-${Date.now().toString(36)}`;
const restored = await api('/api/examples/true-run-001/restore', {runId});
const catalog = await api('/api/catalog', null, 'GET');
const browser = await chromium.launch({headless: true});
const page = await browser.newPage({viewport: {width: 1440, height: 1000}, deviceScaleFactor: 1});
const errors = [], checks = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
await page.addInitScript(id => localStorage.setItem('fulcrum-run', id), runId);
async function check(name, fn) { await fn(); checks.push(name); console.log(name); }
async function loadedRevision() { return (await api(`/api/runs/${runId}`, null, 'GET')).revision; }
async function saveAndWait(before) {
  await page.getByRole('button', {name: '保存', exact: true}).click();
  await page.waitForFunction(() => !document.querySelector('.modal'), null, {timeout: 15000});
  assert.equal(await loadedRevision(), before + 1);
}
try {
  await page.goto(base);
  await page.locator('.map-node').first().waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll('.node-value')].some(el => !el.textContent.includes('—')));
  await check('map and assets', async () => {
    assert.equal(await page.locator('.map-node').count(), 13);
    await page.waitForFunction(() => document.querySelectorAll('.map-node img').length >= 10);
    assert.equal(await page.locator('.connections .map-edge').count() > 0, true);
    assert.equal(await page.getByRole('button', {name: '手机接入'}).count(), 0);
    await page.screenshot({path: `${out}/desktop.png`, fullPage: true});
  });
  await check('normal route and step breakdown', async () => {
    await page.getByRole('button', {name: '规划', exact: true}).click();
    await page.locator('.route-row').first().waitFor({timeout: 60000});
    assert.equal(await page.locator('.route-row').count(), 3);
    await page.locator('.route-step').first().click();
    await page.locator('.step-breakdown').waitFor();
    await page.screenshot({path: `${out}/desktop-route.png`, fullPage: true});
  });
  await check('pursuit route', async () => {
    await page.getByRole('button', {name: '追猎', exact: true}).click();
    await page.getByRole('button', {name: '规划', exact: true}).click();
    await page.locator('.route-row').first().waitFor({timeout: 60000});
    assert.equal(await page.locator('.route-row').count(), 5);
    assert.ok((await page.locator('.route-choice').first().innerText()).includes('分'));
    await page.getByRole('button', {name: '不追猎', exact: true}).click();
  });
  await check('node detail and score', async () => {
    await page.locator('[data-node-id="1,0"]').click();
    await page.getByRole('button', {name: '概率与得分', exact: true}).click();
    assert.ok((await page.locator('.node-popover').innerText()).includes('分类估分权重'));
    await page.screenshot({path: `${out}/node-detail.png`, fullPage: true});
    await page.getByRole('button', {name: '关闭节点详情'}).click();
  });
  await check('resources and tickets', async () => {
    const before = await loadedRevision();
    await page.getByRole('button', {name: '编辑实时资源'}).click();
    await page.getByLabel('希望', {exact: true}).fill('9');
    await page.getByLabel('招募券类别').selectOption({label: '重装招募券'});
    await page.getByRole('button', {name: '添加', exact: true}).click();
    await saveAndWait(before);
    const state = (await api(`/api/runs/${runId}`, null, 'GET')).state;
    assert.equal(state.resources.hope, 9); assert.deepEqual(state.recruitmentTickets, ['重装招募券']);
  });
  await check('component inventory and route candidates', async () => {
    const before = await loadedRevision();
    await page.getByRole('button', {name: '编辑零件箱'}).click();
    await page.getByLabel('搜索名称', {exact: true}).fill('结构原理');
    await page.getByRole('button', {name: '选择 结构性原理', exact: true}).click();
    await page.getByLabel('剩余次数').fill('2');
    await page.getByLabel('参与规划').uncheck();
    await saveAndWait(before);
    const state = (await api(`/api/runs/${runId}`, null, 'GET')).state;
    const part = state.componentBox.items.find(x => x.componentId === 'component_023');
    assert.equal(part.remainingUses, 2); assert.equal(part.routeCandidate, false);
  });
  await check('relic list', async () => {
    const before = await loadedRevision();
    await page.getByRole('button', {name: '编辑藏品'}).click();
    const name = catalog.relic.find(row => row.id === 'relic_001').name;
    await page.getByLabel('搜索名称', {exact: true}).fill(name);
    await page.getByRole('button', {name: `选择 ${name}`, exact: true}).click();
    await saveAndWait(before);
    assert.ok((await api(`/api/runs/${runId}`, null, 'GET')).state.relics.some(x => x.id === 'relic_001'));
  });
  await check('roster and squad editing', async () => {
    const before = await loadedRevision();
    await page.getByRole('button', {name: '编辑干员与编队'}).click();
    await page.getByLabel('搜索名称', {exact: true}).fill('芬');
    await page.getByRole('button', {name: '选择 芬', exact: true}).click();
    const row = page.locator('.operator-edit-row').last();
    await row.getByRole('checkbox', {name: '编队', exact: true}).check();
    await saveAndWait(before);
    const state = (await api(`/api/runs/${runId}`, null, 'GET')).state;
    const op = state.operators.find(x => x.name === '芬');
    assert.ok(op); assert.ok(state.squad.includes(op.instanceId)); assert.equal(state.resources.hope, 9);
  });
  await check('ending record and layer strategy', async () => {
    let before = await loadedRevision();
    await page.getByRole('button', {name: '编辑结局目标'}).click();
    await page.getByRole('checkbox', {name: '结局 2', exact: true}).check();
    await page.getByRole('checkbox', {name: '普通结局 3', exact: true}).check();
    await saveAndWait(before);
    assert.equal((await api(`/api/runs/${runId}`, null, 'GET')).state.goals.endingV, 'ending2');
    before = await loadedRevision();
    await page.getByRole('button', {name: '本层策略', exact: true}).click();
    await page.getByRole('checkbox', {name: '自定义留钱总额', exact: true}).check();
    await page.getByLabel('现金留钱总额', {exact: true}).fill('83');
    await saveAndWait(before);
    const state = (await api(`/api/runs/${runId}`, null, 'GET')).state;
    assert.equal(state.areas.I.instances[0].strategy.scoringOptions.merchantReserve, 83);
  });
  await check('memo and undo', async () => {
    const before = await loadedRevision();
    await page.getByRole('button', {name: '展开本局备忘', exact: true}).click();
    await page.getByRole('button', {name: '编辑备忘'}).click();
    await page.getByLabel('本局备忘内容').fill('UI smoke memo');
    await saveAndWait(before);
    await page.getByRole('button', {name: '撤销上一版'}).click();
    await page.waitForFunction(() => !document.querySelector('.memo-text')?.textContent.includes('UI smoke memo'));
    assert.equal(await loadedRevision(), before + 2);
  });
  await check('node confirmation, history preservation and position', async () => {
    await page.locator('[data-node-id="1,0"]').click();
    await page.getByRole('button', {name: '节点状态', exact: true}).click();
    await page.getByLabel('节点类别', {exact: true}).selectOption('node_type_006');
    await page.getByLabel('不期而遇事件', {exact: true}).selectOption('encounter_001');
    await page.getByLabel('玩家当前位置', {exact: true}).check();
    await page.getByRole('button', {name: '已完成', exact: true}).click();
    await page.getByRole('button', {name: '确认更新', exact: true}).click();
    await page.waitForFunction(() => !document.querySelector('.node-popover'));
    const current = (await api(`/api/runs/${runId}`, null, 'GET')).state.areas.I;
    const instance = current.instances.find(x => x.instanceId === current.activeInstanceId);
    assert.equal(instance.playerPosition, '1,0');
    assert.equal(instance.nodes['1,0'].completion, 'completed');
    assert.equal(instance.nodes['1,0'].encounterId, 'encounter_001');
  });
  await check('image upload, real recognition, confirmation', async () => {
    await page.waitForFunction(() => !document.querySelector('input[aria-label="上传地图截图"]').disabled);
    await page.getByLabel('上传地图截图').setInputFiles(resolve('samples/true_run_map/run1_floor1_state0.jpg'));
    await page.getByRole('button', {name: '开始识别', exact: true}).waitFor();
    await page.getByRole('button', {name: '开始识别', exact: true}).click();
    await page.getByRole('button', {name: '确认入局', exact: true}).waitFor({timeout: 60000});
    await page.getByLabel('玩家位置', {exact: true}).selectOption('0,0');
    await page.getByLabel('当前位置已完成', {exact: true}).check();
    await page.getByLabel('希望候选', {exact: true}).fill('0');
    await page.getByRole('checkbox', {name: '希望', exact: true}).check();
    await page.screenshot({path: `${out}/recognition.png`, fullPage: true});
    await page.getByRole('button', {name: '确认入局', exact: true}).click();
    await page.waitForFunction(() => !document.querySelector('.modal'), null, {timeout: 20000});
    const data = (await api(`/api/runs/${runId}`, null, 'GET')).state;
    const instance = data.areas.I.instances.find(x => x.instanceId === data.areas.I.activeInstanceId);
    assert.equal(instance.playerPosition, '0,0');
    assert.equal(instance.nodes['1,0'].encounterId, 'encounter_001');
    assert.equal(data.resources.hope, 0);
  });
  await check('responsive layouts', async () => {
    await page.waitForFunction(() => !document.querySelector('input[aria-label="上传地图截图"]').disabled &&
      [...document.querySelectorAll('.node-value')].some(el => !el.textContent.includes('—')) && !document.querySelector('.toast'));
    for (const width of [1024, 390]) {
      await page.setViewportSize({width, height: 844});
      await page.screenshot({path: `${out}/layout-${width}.png`, fullPage: true});
      const sizes = await page.evaluate(() => ({width: innerWidth, scroll: document.documentElement.scrollWidth}));
      assert.ok(sizes.scroll <= sizes.width + 1, JSON.stringify(sizes));
    }
    await page.getByRole('button', {name: '编辑实时资源'}).click();
    await page.screenshot({path: `${out}/mobile-resources.png`, fullPage: true});
    const box = await page.locator('.modal').boundingBox(); assert.ok(box.x >= 0 && box.x + box.width <= 391);
    await page.getByRole('button', {name: '关闭', exact: true}).click();
  });
  await check('explicit unknown and empty corrections', async () => {
    await page.setViewportSize({width: 1440, height: 1000});
    await page.locator('[data-node-id="1,0"]').click();
    await page.getByRole('button', {name: '节点状态', exact: true}).click();
    await page.getByLabel('节点类别', {exact: true}).selectOption('unknown_mystery');
    await page.getByRole('button', {name: '确认更新', exact: true}).click();
    await page.waitForFunction(() => !document.querySelector('.node-popover') && !document.querySelector('input[aria-label="上传地图截图"]').disabled);
    let state = (await api(`/api/runs/${runId}`, null, 'GET')).state;
    let node = state.areas.I.instances[0].nodes['1,0'];
    assert.equal(node.encounterId, null); assert.equal(node.completion, 'pending'); assert.equal(node.visibility, 'hidden');
    await page.locator('[data-node-id="1,0"]').click();
    await page.getByRole('button', {name: '节点状态', exact: true}).click();
    await page.getByLabel('节点类别', {exact: true}).selectOption('node_type_020');
    await page.getByRole('button', {name: '确认更新', exact: true}).click();
    await page.waitForFunction(() => !document.querySelector('.node-popover') && !document.querySelector('input[aria-label="上传地图截图"]').disabled);
    state = (await api(`/api/runs/${runId}`, null, 'GET')).state;
    node = state.areas.I.instances[0].nodes['1,0'];
    assert.equal(node.resolvedCategoryId, 'node_type_020'); assert.equal(node.visibility, 'revealed');
  });
  await check('capture requires selection and explicit consent', async () => {
    await page.setViewportSize({width: 1440, height: 1000});
    await page.getByRole('button', {name: '窗口截图', exact: true}).click();
    await page.locator('select[aria-label="目标进程 / 窗口"] option').nth(1).waitFor({state: 'attached'});
    assert.ok(await page.getByRole('button', {name: '授权并截取', exact: true}).isDisabled());
    const option = await page.locator('select[aria-label="目标进程 / 窗口"] option').evaluateAll(rows => rows.find(r => !r.disabled && r.value)?.value);
    await page.getByLabel('目标进程 / 窗口', {exact: true}).selectOption(option);
    assert.ok(await page.getByRole('button', {name: '授权并截取', exact: true}).isDisabled());
    // Inspect the dialog only: no arbitrary window is captured.
    await page.screenshot({path: `${out}/capture-dialog.png`, fullPage: true});
    await page.getByRole('button', {name: '关闭', exact: true}).click();
  });
  await check('JSON export and restore copy', async () => {
    const downloadEvent = page.waitForEvent('download');
    await page.getByRole('button', {name: '导出 Playtime', exact: true}).click();
    const download = await downloadEvent;
    const exported = `${out}/exported.json`; await download.saveAs(exported);
    const state = JSON.parse(await readFile(exported, 'utf8')); assert.equal(state.runId, runId);
    await page.getByLabel('导入 Playtime', {exact: true}).setInputFiles(exported);
    await page.waitForFunction(id => document.querySelector('select[aria-label="选择对局"]').value !== id, runId);
    assert.equal(await page.locator('.map-node').count(), 13);
  });
  await check('new run initialization', async () => {
    await page.getByRole('button', {name: '开始探索', exact: true}).click();
    const id = `ui-new-${Date.now().toString(36)}`;
    await page.getByLabel('对局 ID', {exact: true}).fill(id);
    await page.getByLabel('难度', {exact: true}).fill('15');
    await page.getByLabel('分队', {exact: true}).selectOption('squad_014');
    await page.getByRole('button', {name: '进入树海', exact: true}).click();
    await page.waitForFunction(id => document.querySelector('select[aria-label="选择对局"]').value === id, id);
    const state = (await api(`/api/runs/${id}`, null, 'GET')).state;
    assert.equal(state.opening.difficulty, 15); assert.equal(state.componentBox.items.length, 2);
    assert.equal(state.componentBox.capacity, 12); assert.equal(state.resources.investmentBalance, 99);
  });
  assert.equal(await readFile(sourcePath, 'utf8'), original, 'original fixture must not change');
  assert.deepEqual(errors, []);
  await writeFile(`${out}/result.json`, JSON.stringify({runId, sourceRevision: restored.revision, checks, errors}, null, 2));
} catch (error) {
  await page.screenshot({path: `${out}/failure.png`, fullPage: true});
  await writeFile(`${out}/failure.json`, JSON.stringify({runId, checks, errors, error: error.stack, body: await page.locator('body').innerText()}, null, 2));
  throw error;
} finally { await browser.close(); }
