import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const source = 'https://www.lubiao.wiki/nodes/rogue_6';
const out = resolve('work/lubiao_node_icons');
const labels = JSON.parse(await readFile('data/vision_labels.json', 'utf8')).nodeTypes;
const normalize = text => text.replace(/[\s“”"「」]/g, '');
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto(source, { waitUntil: 'networkidle', timeout: 30000 });
  const sprites = await page.locator('.compact-node-entry .directory-base-icon').evaluateAll(elements => elements.map(element => {
    const clip = element.querySelector('.asset-sprite-clip'), image = clip.querySelector('image');
    return { name: element.closest('a').innerText.trim(), url: image.getAttribute('href'),
      box: [-Number(image.getAttribute('x')), -Number(image.getAttribute('y')), Number(clip.getAttribute('width')), Number(clip.getAttribute('height'))] };
  }));
  const rows = sprites.map(row => ({ ...row, id: Object.keys(labels).find(id => normalize(labels[id]) === normalize(row.name)) }));
  if (rows.some(row => !row.id) || new Set(rows.map(row => row.id)).size !== rows.length) throw new Error('unmatched or duplicate node icon');
  const urls = [...new Set(rows.map(row => row.url))];
  await mkdir(out, { recursive: true });
  const atlases = [];
  const atlasBytes = new Map();
  for (const [index, url] of urls.entries()) {
    if (new URL(url).hostname !== 'assets.lubiao.wiki') throw new Error('unexpected asset host');
    const response = await page.request.get(url);
    if (!response.ok()) throw new Error(`asset download failed: ${response.status()}`);
    const file = `atlas-${index}.avif`;
    const bytes = await response.body();
    await writeFile(resolve(out, file), bytes);
    atlasBytes.set(url, bytes.toString('base64'));
    atlases.push({ url, file });
  }
  for (const row of rows) {
    const png = await page.evaluate(async ({ base64, box }) => {
      const image = new Image(); image.src = `data:image/avif;base64,${base64}`; await image.decode();
      const [x, y, width, height] = box;
      if (x < 0 || y < 0 || x + width > image.width || y + height > image.height) throw new Error('invalid atlas rectangle');
      const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
      canvas.getContext('2d').drawImage(image, x, y, width, height, 0, 0, width, height);
      return canvas.toDataURL('image/png').split(',')[1];
    }, { base64: atlasBytes.get(row.url), box: row.box });
    await writeFile(resolve(out, `${row.id}.png`), Buffer.from(png, 'base64'));
  }
  await writeFile(resolve(out, 'source.json'), JSON.stringify({ source, fetchedAt: new Date().toISOString(), atlases, icons: rows }, null, 2) + '\n');
  console.log(JSON.stringify({ icons: rows.length, atlases: atlases.length, out }));
} finally { await browser.close(); }
