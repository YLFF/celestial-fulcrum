import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.FULCRUM_PLAYWRIGHT || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.FULCRUM_URL || 'http://127.0.0.1:8766';
const runId = process.env.FULCRUM_THEME_RUN || 'true-run-001-ui';
const out = resolve('work/ui_theme'); await mkdir(out, {recursive: true});
const token = (await (await fetch(`${base}/api/session`)).json()).token;
async function snapshot() {
  const response = await fetch(`${base}/api/runs/${runId}`, {headers: {'X-Fulcrum-Token': token}});
  assert.ok(response.ok); return response.json();
}
const before = await snapshot();
const browser = await chromium.launch({headless: true});
const page = await browser.newPage({viewport: {width: 1440, height: 1000}, colorScheme: 'light'});
const errors = [], checks = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
await page.addInitScript(id => localStorage.setItem('fulcrum-run', id), runId);
async function ready() { await page.locator('.map-node').first().waitFor(); }
async function screenshot(name) { await page.screenshot({path: `${out}/${name}.png`, fullPage: true}); }
async function check(name, fn) { await fn(); checks.push(name); console.log(name); }
async function background(selector) { return page.locator(selector).evaluate(el => getComputedStyle(el).backgroundColor); }
try {
  await page.goto(base); await ready();
  const mapBackground = await background('.map-frame');
  await check('default light and explicit dark switch', async () => {
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'light');
    await page.getByRole('button', {name: '切换到黑暗模式', exact: true}).click();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'dark');
    assert.equal(await page.getByRole('button', {name: '切换到明亮模式', exact: true}).getAttribute('aria-pressed'), 'true');
    assert.equal(await background('.app-header'), 'rgb(32, 35, 33)');
    assert.equal(await background('.map-frame'), mapBackground);
    await page.waitForFunction(() => [...document.querySelectorAll('.node-value')].some(el => !el.textContent.includes('—')));
    await screenshot('dark-desktop');
  });
  await check('node popover and hover use dark surfaces', async () => {
    await page.locator('[data-node-id="1,0"]').hover();
    assert.equal(await background('.hover-sheet'), 'rgb(32, 35, 33)');
    await page.locator('[data-node-id="1,0"]').click();
    await page.getByRole('button', {name: '概率与得分', exact: true}).click();
    assert.equal(await background('.node-popover'), 'rgb(32, 35, 33)');
    await screenshot('dark-node');
    await page.getByRole('button', {name: '关闭节点详情'}).click();
  });
  await check('resource form uses dark inputs and panels', async () => {
    await page.getByRole('button', {name: '编辑实时资源'}).click();
    assert.equal(await background('.modal'), 'rgb(32, 35, 33)');
    assert.equal(await background('.modal input[type="number"] >> nth=0'), 'rgb(25, 28, 26)');
    await screenshot('dark-resources');
    await page.getByRole('button', {name: '关闭', exact: true}).click();
  });
  await check('route comparison retains its values in dark mode', async () => {
    await page.getByRole('button', {name: '规划', exact: true}).click();
    await page.locator('.route-row').first().waitFor({timeout: 60000});
    assert.ok((await page.locator('.route-choice').first().innerText()).includes('1,215.1'));
    await page.locator('.route-step').first().click();
    await page.locator('.step-breakdown').waitFor();
    await screenshot('dark-route');
  });
  await check('theme persists across reload', async () => {
    await page.reload(); await ready();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'dark');
    assert.equal(await page.evaluate(() => localStorage.getItem('fulcrum-theme')), 'dark');
  });
  await check('narrow layouts fit with the additional control', async () => {
    for (const width of [1024, 390]) {
      await page.setViewportSize({width, height: 844});
      await screenshot(`dark-${width}`);
      const dimensions = await page.evaluate(() => ({width: innerWidth, scroll: document.documentElement.scrollWidth}));
      assert.ok(dimensions.scroll <= width + 1, JSON.stringify(dimensions));
      const boxes = await page.locator('.header-actions button').evaluateAll(els => els.map(el => {
        const r = el.getBoundingClientRect(); return {left: r.left, right: r.right, top: r.top, bottom: r.bottom};
      }));
      for (let i = 1; i < boxes.length; i++) assert.ok(boxes[i].left >= boxes[i-1].right || boxes[i].top >= boxes[i-1].bottom);
    }
    await page.getByRole('button', {name: '编辑实时资源'}).click();
    await screenshot('dark-mobile-resources');
    await page.getByRole('button', {name: '关闭', exact: true}).click();
  });
  await check('light mode restores and persists without state changes', async () => {
    await page.getByRole('button', {name: '切换到明亮模式', exact: true}).click();
    assert.equal(await background('.app-header'), 'rgb(255, 255, 255)');
    await page.reload(); await ready();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'light');
    assert.deepEqual(await snapshot(), before);
  });
  assert.deepEqual(errors, []);
  await writeFile(`${out}/result.json`, JSON.stringify({runId, checks, errors, playtimeUnchanged: true}, null, 2));
} catch (error) {
  await screenshot('failure');
  await writeFile(`${out}/failure.json`, JSON.stringify({checks, errors, error: error.stack}, null, 2));
  throw error;
} finally { await browser.close(); }
