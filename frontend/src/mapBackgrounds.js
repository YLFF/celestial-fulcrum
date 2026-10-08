import { readPreference } from './preferences.js';

export const MAP_BRIGHTNESS_KEY = 'fulcrum-map-brightness';
export const DEFAULT_MAP_BRIGHTNESS = 35;
export const MAP_BACKGROUND = { id: 'flower-tree', url: '/ui-assets/map-backgrounds/flower-tree.png' };
export const MAP_SIDE_BRIGHTNESS_RATIO = 42 / 35;

export function savedMapBrightness(storage) {
  const raw = readPreference(MAP_BRIGHTNESS_KEY, storage);
  const value = raw == null || raw.trim() === '' ? NaN : Number(raw);
  return Number.isFinite(value) ? Math.max(10, Math.min(100, value)) : DEFAULT_MAP_BRIGHTNESS;
}
