import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8768';
const source = 'work/app_data/runs/run-mux3hoew-u416e3w/playtime.json';
const original = await readFile(source, 'utf8');
const token = (await (await fetch(base + '/api/session')).json()).token;
async function api(path, body, method = 'POST') {
  const response = await fetch(base + path, { method,
    headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const value = await response.json();
  assert.ok(response.ok, JSON.stringify(value));
  return value;
}
const runId = `conditional-markers-${Date.now().toString(36)}`;
const run = await api('/api/runs/restore', { runId, state: JSON.parse(original) });
const map = run.state.areas.III.instances.find(row => row.instanceId === run.state.areas.III.activeInstanceId);
const probabilities = map.prediction.unknownNodes['-4,0'].categoryProbabilities;
assert.ok(Math.abs(probabilities.node_type_013 - .2707157252046357) < 1e-10);
assert.ok(Math.abs(probabilities.node_type_011 - .5112444424573863) < 1e-10);
assert.equal(map.prediction.posteriorBeta.families.unknown_mystery.status, 'ok');
const jobId = (await api(`/api/runs/${runId}/jobs/score`, { expectedRevision: run.revision })).jobId;
let score;
for (let attempt = 0; attempt < 200; attempt++) {
  const job = await api(`/api/jobs/${jobId}`, null, 'GET');
  assert.ok(!['failed', 'cancelled'].includes(job.status), JSON.stringify(job));
  if (job.status === 'completed') { score = job.result; break; }
  await new Promise(resolve => setTimeout(resolve, 100));
}
assert.ok(score, 'score job timed out');
assert.deepEqual(score.nodeValues['-4,0'].classification.probabilities, probabilities);
const out = 'work/ui_conditional_markers';
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
  await page.addInitScript(id => {
    localStorage.setItem('fulcrum-run', id);
    localStorage.setItem('fulcrum-theme', 'dark');
  }, runId);
  await page.goto(base);
  await page.locator('[data-node-id="-4,0"]').first().waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll('.node-value')].some(el => /\d/.test(el.textContent)));
  await page.locator('[data-node-id="-4,0"]').first().click();
  const dialog = page.getByRole('dialog', { name: '节点编辑 -4,0', exact: true });
  await dialog.waitFor();
  const rows = await dialog.locator('.score-details > .classification-table > .probability-row').allTextContents();
  assert.ok(rows.some(row => row.includes('秘境行商') && row.includes('27.1%')), rows.join('\n'));
  assert.ok(rows.some(row => row.includes('狭路相逢') && row.includes('51.1%')), rows.join('\n'));
  const raw = dialog.locator('details.classification-table');
  assert.equal(await raw.getAttribute('open'), null);
  assert.ok((await raw.textContent()).includes('非当前分类概率'));
  assert.ok(!(await dialog.textContent()).includes('均分必出前置'));
  await page.screenshot({ path: `${out}/node-minus4-zero.png`, fullPage: true });
  assert.deepEqual(errors, []);
  assert.equal(await readFile(source, 'utf8'), original);
  const result = { ok: true, runId, probabilities, score: score.nodeValues['-4,0'].points, sourceUnchanged: true };
  await writeFile(`${out}/result.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} finally {
  await browser.close();
}
