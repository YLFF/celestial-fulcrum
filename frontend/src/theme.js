import { readPreference } from './preferences.js';

export const THEME_KEY = 'fulcrum-theme';

export function savedTheme(storage) {
  try {
    return readPreference(THEME_KEY, storage) === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

export function applyTheme(theme, root = globalThis.document.documentElement, storage) {
  const value = theme === 'dark' ? 'dark' : 'light';
  root.dataset.theme = value;
  try {
    (storage ?? globalThis.localStorage).setItem(THEME_KEY, value);
  } catch {
    // Theme switching still works when browser storage is unavailable.
  }
}
