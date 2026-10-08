import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8768';
const token = (await (await fetch(base + '/api/session')).json()).token;
async function api(path, body) {
  const response = await fetch(base + path, { method: body ? 'POST' : 'GET',
    headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const value = await response.json();
  assert.ok(response.ok, JSON.stringify(value));
  return value;
}
const source = 'runs/true-run-001/playtime.json';
const original = await readFile(source, 'utf8');
const catalog = await api('/api/catalog');
const categories = [...Object.keys(catalog.labels.nodeTypes).filter(id => id.startsWith('node_type_') && id !== 'node_type_020'),
  'unknown_mystery', 'unknown_ferocity'];
const out = 'work/ui_product_assets';
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const failures = [];
let imageCount = 0;
try {
  const seed = JSON.parse(original), slots = Object.keys(seed.areas.I.instances[0].nodes).filter(id => id !== '0,0');
  for (let offset = 0; offset < categories.length; offset += slots.length) {
    const state = structuredClone(seed), map = state.areas.I.instances[0];
    state.currentAreaKey = 'I';
    state.relics = []; state.componentBox.items = [];
    map.dystopia = { active: false, ideologyId: null, policyId: null,
      affectedNodeIds: [], uncertainNodeIds: [], idealSourceNodeId: null };
    map.prediction = null; map.playerPosition = '0,0';
    for (const [index, id] of slots.entries()) {
      const category = categories[offset + index] || 'node_type_020';
      Object.assign(map.nodes[id], { observedCategoryId: category,
        resolvedCategoryId: category.startsWith('unknown_') ? null : category,
        visibility: category.startsWith('unknown_') ? 'hidden' : 'revealed',
        completion: 'pending', completedCategoryId: null, encounterId: null,
        confirmedMarkIds: [], candidateMarkIds: [] });
    }
    const runId = `product-assets-${Date.now().toString(36)}-${offset}`;
    await api('/api/runs/restore', { runId, state });
    for (const [width, height, theme] of [[1440, 1000, 'light'], [1000, 800, 'dark']]) {
      const page = await browser.newPage({ viewport: { width, height } });
      page.on('pageerror', error => failures.push(error.message));
      await page.addInitScript(({ runId, theme }) => {
        localStorage.setItem('fulcrum-run', runId); localStorage.setItem('fulcrum-theme', theme);
      }, { runId, theme });
      await page.goto(base);
      await page.locator('.map-node').first().waitFor();
      const wanted = Math.min(slots.length, categories.length - offset);
      await page.waitForFunction(count => [...document.querySelectorAll('.node-art img')].filter(img => img.complete && img.naturalWidth).length >= count, wanted);
      assert.equal(await page.title(), catalog.project.name);
      assert.equal(await page.locator('.brand b').innerText(), catalog.project.shortName);
      assert.equal(await page.locator('.node-art svg').count(), 0, 'node image fallback remains');
      const icons = await page.locator('.node-art img').evaluateAll(images => images.map(img => ({
        width: img.naturalWidth, height: img.naturalHeight, clip: getComputedStyle(img).clipPath,
      })));
      assert.ok(icons.every(row => row.width && row.height && row.clip === 'none'));
      imageCount += icons.length;
      await page.screenshot({ path: `${out}/map-${offset}-${width}-${theme}.png`, fullPage: true });
      if (offset + slots.length >= categories.length && width === 1440) {
        const art = page.locator('.node-art').filter({ has: page.locator('img.unknown-icon') });
        for (let i = 0; i < await art.count(); i++) {
          await art.nth(i).screenshot({ path: `${out}/unknown-${i}.png`, scale: 'css' });
        }
      }
      await page.close();
    }
  }
  assert.deepEqual(failures, []);
  assert.equal(await readFile(source, 'utf8'), original);
  const result = { ok: true, categories: categories.length, renderedImageChecks: imageCount, viewports: [1440, 1000], themes: ['light', 'dark'] };
  await writeFile(`${out}/result.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} finally { await browser.close(); }
