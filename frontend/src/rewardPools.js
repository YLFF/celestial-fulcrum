import { orderedRelics } from './relicPresentation.js';

export function rewardPoolsFor(catalog, scope = {}, areaKey = '') {
  const browser = catalog.rewardBrowser;
  if (!browser) return [];
  let keys;
  if (scope.goalId === 'ending3_autopsy' || scope.stage === '无效验尸') keys = browser.special.ending3_autopsy;
  else if (scope.eventId) keys = browser.events[scope.eventId];
  else keys = browser.nodes[scope.categoryId];
  const area = areaKey === 'IV-remembrance' ? 'f4' : areaKey.includes('treehole')
    ? `f${({ III: 3, IV: 4, V: 5 })[areaKey.split('-')[0]]}-treehole`
    : `f${({ I: 1, II: 2, III: 3, IV: 4, V: 5, VI: 6 })[areaKey]}`;
  const markKeys = (scope.markIds || []).flatMap(id => browser.marks?.[id] || []);
  return [...new Set([...(keys || []), ...markKeys])].map(key => browser.pools[key]).filter(Boolean).filter(pool => {
    if (pool.contextId === 'secret_trader_shelves_f1') return areaKey === 'I';
    if (pool.contextId === 'secret_trader_shelves') return areaKey !== 'I';
    if (scope.categoryId !== 'node_type_004' || scope.eventId) return true;
    const prefix = 'node_battle_shop_merchant__';
    if (!pool.contextId.startsWith(prefix)) return true;
    const suffix = pool.contextId.slice(prefix.length);
    if (suffix === 'collectibles-all') return !areaKey || areaKey === 'VI';
    if (suffix.startsWith('collectibles-f')) return suffix === `collectibles-${area}`;
    if (suffix === 'sand-beta') return ['II', 'III', 'IV', 'IV-remembrance'].includes(areaKey);
    return true;
  });
}

export function visiblePoolItems(pool, heldRelics, entries) {
  const held = new Set(heldRelics.map(row => row.id));
  const items = pool.itemIds.filter(id => pool.kind !== 'relic' || !held.has(id)).map(id => ({ id }));
  return pool.kind === 'relic' ? orderedRelics(items, entries) : items;
}

export function besidePopover(left, top, width, height, viewport) {
  const panelWidth = Math.min(width, viewport.width - 20);
  const candidate = left + width + 8;
  const nextLeft = candidate + panelWidth <= viewport.width - 10 ? candidate
    : left - panelWidth - 8 >= 10 ? left - panelWidth - 8 : Math.max(10, viewport.width - panelWidth - 10);
  return { left: nextLeft, top, width: panelWidth, height: Math.min(height, viewport.height - top - 12) };
}
