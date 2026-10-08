import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('product title and package identity use Celestial Fulcrum', () => {
  const project = JSON.parse(readFileSync(new URL('../../data/project_info.json', import.meta.url), 'utf8'));
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.ok(html.includes(`<title>${project.name}</title>`));
  assert.ok(app.includes('catalog.project.shortName'));
  assert.ok(!app.includes('BLACK FLOW'));
});

test('unknown icons keep the full round illustration, with no bottom strip clipping', () => {
  const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  const rule = css.match(/\.node-art img\.unknown-icon \{([^}]+)\}/)[1];
  assert.ok(!rule.includes('clip-path'));
  assert.match(rule, /translate\(-50%, -40%\)/);
});
