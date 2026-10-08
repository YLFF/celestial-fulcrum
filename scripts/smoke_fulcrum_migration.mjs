import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8768';
const session = await (await fetch(base + '/api/session')).json();
assert.equal(session.header, 'X-Fulcrum-Token');
const source = 'runs/true-run-001/playtime.json';
const original = await readFile(source, 'utf8');
const runId = `namespace-ui-${Date.now().toString(36)}`;
const restored = await fetch(base + '/api/runs/restore', { method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-Fulcrum-Token': session.token },
  body: JSON.stringify({ runId, state: JSON.parse(original) }) });
assert.ok(restored.ok, await restored.text());
const legacy = await fetch(base + '/api/runs', { headers: { 'X-Blackflow-Token': session.token } });
assert.ok(legacy.ok);
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [], authenticated = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.url().includes('/api/') && request.headers()['x-fulcrum-token']) authenticated.push(request.url());
  });
  await page.addInitScript(id => {
    localStorage.setItem('blackflow-run', id);
    localStorage.setItem('blackflow-theme', 'dark');
    localStorage.setItem(`blackflow-hidden-areas:${id}`, JSON.stringify(['VI']));
  }, runId);
  await page.goto(base);
  await page.locator('.map-node').first().waitFor();
  await page.waitForFunction(id => localStorage.getItem('fulcrum-run') === id, runId);
  const preferences = await page.evaluate(id => ({
    theme: document.documentElement.dataset.theme,
    newTheme: localStorage.getItem('fulcrum-theme'), oldTheme: localStorage.getItem('blackflow-theme'),
    hidden: localStorage.getItem(`fulcrum-hidden-areas:${id}`),
  }), runId);
  assert.deepEqual(preferences, { theme: 'dark', newTheme: 'dark', oldTheme: 'dark', hidden: '["VI"]' });
  assert.equal(await page.getByRole('tab', { name: /^VI ·/ }).count(), 0);
  assert.ok(authenticated.length);
  assert.deepEqual(errors, []);
  assert.equal(await readFile(source, 'utf8'), original);
  console.log(JSON.stringify({ ok: true, legacyPreferencesRestored: true, legacyApiAccepted: true,
    newApiRequests: authenticated.length, sourceUnchanged: true }));
} finally { await browser.close(); }
