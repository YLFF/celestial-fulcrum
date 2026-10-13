import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8773';
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method,
    headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  assert.ok(response.ok, JSON.stringify(data));
  return data;
}
function gate() {
  let release;
  const promise = new Promise(resolve => { release = resolve; });
  return { promise, release };
}
async function bounded(promise) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('Expected request did not arrive')), 15000);
    })]);
  } finally { clearTimeout(timer); }
}

const suffix = Date.now().toString(36);
const ids = ['a', 'b', 'c'].map(name => `review-${name}-${suffix}`);
const original = await api('/api/runs', { runId: ids[0], squadId: 'squad_001' });
await api('/api/runs', { runId: ids[1], squadId: 'squad_001' });
const source = structuredClone(original.state);
source._serviceHistory = { past: [structuredClone(source)], future: [structuredClone(source)] };
source.resources.hope = 8;
source._serviceHistory.past[0].resources.hope = 6;
source._serviceHistory.future[0].resources.hope = 10;
await api('/api/runs/restore', { state: source, runId: ids[2] });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(id => localStorage.setItem('fulcrum-run', id), ids[0]);
const select = page.getByRole('combobox', { name: '选择对局', exact: true });
async function opened(id) {
  await page.waitForFunction(value => document.querySelector('.run-select')?.value === value &&
    localStorage.getItem('fulcrum-run') === value, id);
}

try {
  await page.goto(base);
  await opened(ids[0]);
  const slow = gate(), started = gate();
  await page.route(`${base}/api/runs/${ids[1]}`, async route => {
    const response = await route.fetch();
    started.release();
    await slow.promise;
    await route.fulfill({ response });
  });
  await select.selectOption(ids[1]);
  await bounded(started.promise);
  await select.selectOption(ids[2]);
  await opened(ids[2]);
  const oldResponse = page.waitForResponse(`${base}/api/runs/${ids[1]}`);
  slow.release();
  await oldResponse;
  await delay(100);
  assert.equal(await select.inputValue(), ids[2]);
  console.log('Out-of-order run selection cannot replace the current run');

  const polling = gate(), pollingStarted = gate();
  let delayed = false;
  await page.route(`${base}/api/runs/${ids[2]}`, async route => {
    const response = await route.fetch();
    if (!delayed) {
      delayed = true;
      const json = await response.json();
      json.revision += 1;
      pollingStarted.release();
      await polling.promise;
      await route.fulfill({ response, json });
    } else await route.fulfill({ response });
  });
  await bounded(pollingStarted.promise);
  await select.selectOption(ids[0]);
  await opened(ids[0]);
  const oldPoll = page.waitForResponse(`${base}/api/runs/${ids[2]}`);
  polling.release();
  await oldPoll;
  await delay(100);
  assert.equal(await select.inputValue(), ids[0]);
  console.log('An old background refresh cannot reopen a different run');

  await select.selectOption(ids[2]);
  await opened(ids[2]);
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出 Playtime', exact: true }).click();
  const download = await downloadEvent;
  const buffer = await readFile(await download.path());
  const exported = JSON.parse(buffer.toString('utf8'));
  assert.equal(exported._serviceHistory.past.length, 1);
  assert.equal(exported._serviceHistory.future.length, 1);
  await page.getByLabel('导入 Playtime', { exact: true }).setInputFiles({ name: 'review.json', mimeType: 'application/json', buffer });
  await page.waitForFunction(prefix => document.querySelector('.run-select')?.value.startsWith(prefix), `${ids[2]}-ui-`);
  const importedId = await select.inputValue();
  for (const [direction, hope] of [['重做', 10], ['撤销', 8], ['撤销', 6]]) {
    const updated = page.waitForResponse(response => response.url() === `${base}/api/runs/${importedId}` && response.ok());
    await page.getByRole('button', { name: direction === '重做' ? '重做地图更新' : '撤销上次地图更新', exact: true }).click();
    await updated;
    await page.waitForFunction(() => !document.querySelector('.run-select').disabled);
    assert.equal((await api(`/api/runs/${importedId}`, null, 'GET')).state.resources.hope, hope);
  }
  assert.equal((await api(`/api/runs/${ids[2]}`, null, 'GET')).state.resources.hope, 8);
  console.log('UI export/import preserves undo and redo without changing the source');
  assert.deepEqual(errors, []);
} finally { await browser.close(); }
