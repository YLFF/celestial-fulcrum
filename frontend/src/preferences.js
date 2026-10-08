export function readPreference(key, storage) {
  try {
    const target = storage ?? globalThis.localStorage;
    const current = target.getItem(key);
    if (current != null) return current;
    const legacy = target.getItem(key.replace(/^fulcrum-/, 'blackflow-'));
    if (legacy != null) {
      try { target.setItem(key, legacy); } catch { /* Read-only storage still restores the preference. */ }
    }
    return legacy ?? null;
  } catch {
    return null;
  }
}
