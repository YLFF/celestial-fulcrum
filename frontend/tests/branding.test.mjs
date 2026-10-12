import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('product identity uses CFARA while retaining the Celestial Fulcrum executable', () => {
  const project = JSON.parse(readFileSync(new URL('../../data/project_info.json', import.meta.url), 'utf8'));
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.ok(html.includes(`<title>${project.name}</title>`));
  assert.ok(app.includes('catalog.project.shortName'));
  assert.equal(project.shortName, 'CFARA');
  assert.equal(project.englishShortName, 'CFARA');
  assert.equal(project.englishName, 'Celestial Fulcrum — Arknights Rogue Assistant');
  assert.equal(project.dataDirectoryName, 'CFARA');
  assert.equal(project.executableName, 'CelestialFulcrum');
  assert.ok(!app.includes('BLACK FLOW'));
});

test('unknown icons move slightly upward without clipping the illustration', () => {
  const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  const rule = css.match(/\.node-art img\.unknown-icon \{([^}]+)\}/)[1];
  assert.ok(!rule.includes('clip-path'));
  assert.match(rule, /translate\(-50%, -45%\)/);
  assert.match(rule, /width: 150%; height: 150%/);
});
