import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8768';
const source = 'work/app_data/runs/run-mux3hoew-u416e3w/playtime.json';
const original = await readFile(source, 'utf8');
const token = (await (await fetch(base + '/api/session')).json()).token;
const runId = `map-background-${Date.now().toString(36)}`;
const restored = await fetch(base + '/api/runs/restore', { method: 'POST',
  headers: { 'X-Fulcrum-Token': token, 'Content-Type': 'application/json' },
  body: JSON.stringify({ runId, state: JSON.parse(original) }) });
assert.ok(restored.ok, await restored.text());
const out = 'work/ui_map_tree_background';
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const failures = [], checks = [];
try {
  for (const [width, height, name] of [[1440, 1000, 'wide'], [1280, 960, 'standard'],
    [1920, 1080, 'full-hd'], [390, 844, 'mobile']]) {
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
    page.on('pageerror', error => failures.push(error.message));
    await page.addInitScript(id => {
      localStorage.setItem('fulcrum-run', id);
      localStorage.setItem('fulcrum-theme', 'dark');
      localStorage.setItem('fulcrum-map-background', 'stone-ring');
    }, runId);
    await page.goto(base);
    await page.locator('.map-node').first().waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('.node-art img')].every(image => image.complete && image.naturalWidth > 0)
      && document.querySelectorAll('.node-art img').length > 0);
    await page.waitForFunction(() => [...document.querySelectorAll('.node-value')].some(node => /\d/.test(node.textContent)));
    const coordinates = await page.locator('.map-node').evaluateAll(nodes => nodes.map(node => [node.dataset.nodeId, node.style.left, node.style.top]));
    assert.equal(await page.getByRole('group', { name: '地图背景', exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: '开始探索', exact: true }).count(), 1);
    assert.equal(await page.getByRole('group', { name: '查看节点可能位置', exact: true }).count(), 1);
    assert.equal(await page.getByRole('checkbox', { name: '秘境行商', exact: true }).count(), 1);
    assert.equal(await page.getByRole('checkbox', { name: '诡意行商', exact: true }).count(), 1);
    for (const id of ['flower-tree']) {
      await page.waitForFunction(id => document.querySelector('.map-canvas').dataset.background === id, id);
      const style = await page.locator('.map-canvas').evaluate(async canvas => {
        const computed = getComputedStyle(canvas), image = new Image();
        image.src = computed.backgroundImage.slice(5, -2);
        await image.decode();
        return { size: computed.backgroundSize, position: computed.backgroundPosition,
          repeat: computed.backgroundRepeat, transform: computed.transform,
          imageWidth: image.naturalWidth, imageHeight: image.naturalHeight,
          width: canvas.clientWidth, height: canvas.clientHeight };
      });
      assert.equal(style.size, 'auto');
      assert.equal(style.position, '50% 50%');
      assert.equal(style.repeat, 'no-repeat');
      assert.equal(style.transform, 'none');
      assert.equal(style.imageWidth, 1600);
      assert.equal(style.imageHeight, 900);
      const layers = await page.locator('.map-canvas').evaluate(canvas => {
        const shade = getComputedStyle(canvas, '::before');
        const viewport = getComputedStyle(canvas.querySelector('.map-viewport'));
        return { opacity: Number(shade.opacity), background: shade.backgroundImage,
          centerShade: Number(getComputedStyle(canvas).getPropertyValue('--map-background-shade')),
          sideShade: Number(getComputedStyle(canvas).getPropertyValue('--map-side-shade')), pointerEvents: shade.pointerEvents,
          shadeZ: Number(shade.zIndex), viewportZ: Number(viewport.zIndex), viewportFilter: viewport.filter };
      });
      assert.equal(layers.opacity, 1);
      assert.match(layers.background, /linear-gradient/);
      assert.ok(Math.abs(layers.centerShade - .65) < .001);
      assert.ok(Math.abs(layers.sideShade - .58) < .001);
      assert.equal(layers.pointerEvents, 'none');
      assert.ok(layers.viewportZ > layers.shadeZ);
      assert.equal(layers.viewportFilter, 'none');
      assert.deepEqual(await page.locator('.map-node').evaluateAll(nodes => nodes.map(node => [node.dataset.nodeId, node.style.left, node.style.top])), coordinates);
      await page.mouse.move(0, 0);
      await page.locator('.map-frame').screenshot({ path: `${out}/${id}-${name}.png`, scale: 'css' });
      checks.push({ background: id, viewport: [width, height], ...style, ...layers });
    }
    const originalStyle = await page.locator('.map-canvas').evaluate(canvas => getComputedStyle(canvas).backgroundSize);
    await page.getByRole('button', { name: '放大地图', exact: true }).click();
    assert.equal(await page.locator('.map-canvas').evaluate(canvas => getComputedStyle(canvas).backgroundSize), originalStyle);
    assert.equal(await page.locator('.map-canvas').evaluate(canvas => getComputedStyle(canvas).transform), 'none');
    const slider = page.getByRole('slider', { name: '背景亮度' });
    await slider.fill('55');
    assert.equal(await slider.inputValue(), '55');
    assert.ok(Math.abs(await page.locator('.map-canvas').evaluate(canvas => Number(getComputedStyle(canvas).getPropertyValue('--map-background-shade'))) - .45) < .001);
    await page.reload();
    await page.locator('.map-canvas[data-background="flower-tree"]').waitFor();
    assert.equal(await page.getByRole('slider', { name: '背景亮度' }).inputValue(), '55');
    await page.close();
  }
  assert.deepEqual(failures, []);
  assert.equal(await readFile(source, 'utf8'), original);
  await writeFile(`${out}/result.json`, JSON.stringify({ ok: true, runId, sourceUnchanged: true, checks }, null, 2));
  console.log(JSON.stringify({ ok: true, views: checks.length, sourceUnchanged: true, runId }));
} finally { await browser.close(); }
