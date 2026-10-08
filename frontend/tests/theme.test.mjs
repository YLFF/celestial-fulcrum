import test from 'node:test';
import assert from 'node:assert/strict';
import { savedTheme, applyTheme, THEME_KEY } from '../src/theme.js';

test('light remains the default; only supported saved modes are restored', () => {
  for (const value of [null, '', 'system', 'light']) assert.equal(savedTheme({getItem: () => value}), 'light');
  assert.equal(savedTheme({getItem: key => key === THEME_KEY ? 'dark' : null}), 'dark');
});
test('switch applies to the whole document and persists', () => {
  const root = {dataset: {}}, entries = new Map();
  const storage = {setItem: (key, value) => entries.set(key, value), getItem: key => entries.get(key)};
  applyTheme('dark', root, storage);
  assert.equal(root.dataset.theme, 'dark'); assert.equal(savedTheme(storage), 'dark');
  applyTheme('light', root, storage);
  assert.equal(root.dataset.theme, 'light'); assert.equal(savedTheme(storage), 'light');
});
test('blocked storage does not prevent switching', () => {
  const storage = {getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); }};
  assert.equal(savedTheme(storage), 'light');
  const root = {dataset: {}}; applyTheme('dark', root, storage);
  assert.equal(root.dataset.theme, 'dark');
});
