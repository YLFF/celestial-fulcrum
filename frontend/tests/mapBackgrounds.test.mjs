import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MAP_BACKGROUND, MAP_SIDE_BRIGHTNESS_RATIO, MAP_BRIGHTNESS_KEY, DEFAULT_MAP_BRIGHTNESS, savedMapBrightness } from '../src/mapBackgrounds.js';

test('the map uses one centered original-size tree background with slightly brighter sides', () => {
  assert.equal(MAP_BACKGROUND.id, 'flower-tree');
  const png = readFileSync(new URL(`../public${MAP_BACKGROUND.url}`, import.meta.url));
  assert.equal(png.readUInt32BE(16), 1600);
  assert.equal(png.readUInt32BE(20), 900);
  assert.equal(DEFAULT_MAP_BRIGHTNESS * MAP_SIDE_BRIGHTNESS_RATIO, 42);
});

test('background brightness defaults to a dimmed scene and validates saved preferences', () => {
  assert.equal(MAP_BRIGHTNESS_KEY, 'fulcrum-map-brightness');
  assert.equal(DEFAULT_MAP_BRIGHTNESS, 35);
  for (const raw of [null, '', ' ', 'invalid', 'Infinity']) {
    assert.equal(savedMapBrightness({ getItem: () => raw }), 35);
  }
  assert.equal(savedMapBrightness({ getItem: () => '55' }), 55);
  assert.equal(savedMapBrightness({ getItem: () => '200' }), 100);
  assert.equal(savedMapBrightness({ getItem: () => '-20' }), 10);
  assert.equal(savedMapBrightness({ getItem: () => { throw new Error('blocked'); } }), 35);
});
