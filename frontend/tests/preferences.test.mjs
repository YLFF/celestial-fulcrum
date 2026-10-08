import test from 'node:test';
import assert from 'node:assert/strict';
import { readPreference } from '../src/preferences.js';

test('legacy theme, run and hidden tabs migrate without deleting original values', () => {
  for (const suffix of ['theme', 'run', 'hidden-areas:my-run', 'token']) {
    const entries = new Map([[`blackflow-${suffix}`, 'saved-value']]);
    const storage = { getItem: key => entries.get(key) ?? null, setItem: (key, value) => entries.set(key, value) };
    assert.equal(readPreference(`fulcrum-${suffix}`, storage), 'saved-value');
    assert.equal(entries.get(`fulcrum-${suffix}`), 'saved-value');
    assert.equal(entries.get(`blackflow-${suffix}`), 'saved-value');
    entries.set(`fulcrum-${suffix}`, 'new-value');
    assert.equal(readPreference(`fulcrum-${suffix}`, storage), 'new-value');
  }
});

test('read-only or unavailable storage does not prevent reading legacy preferences', () => {
  assert.equal(readPreference('fulcrum-theme', { getItem: key => key === 'blackflow-theme' ? 'dark' : null,
    setItem: () => { throw new Error('read-only'); } }), 'dark');
  assert.equal(readPreference('fulcrum-theme', { getItem: () => { throw new Error('blocked'); } }), null);
});
