export const relicActive = row => ['active', '已生效'].includes(row.state) || !!row.enchantment;

export function canEnchant(row, operator, entries) {
  const profession = entries[row.id]?.enchantmentProfession;
  return !!profession && !relicActive(row) && operator.profession === profession
    && [1, 2].includes(operator.elite) && operator.rarity >= 4;
}

export function orderedRelics(rows, entries) {
  return [...rows].sort((a, b) => (entries[a.id]?.displayOrder ?? 0) - (entries[b.id]?.displayOrder ?? 0)
    || a.id.localeCompare(b.id, 'en', { numeric: true }));
}

export function relicGroups(rows, entries, categories) {
  const groups = new Map();
  for (const row of orderedRelics(rows, entries)) {
    const name = entries[row.id]?.displayCategory || '未分类';
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(row);
  }
  return [...new Set([...categories, ...groups.keys()])].filter(name => groups.has(name))
    .map(name => ({ name, items: groups.get(name) }));
}

export function enchantCommands(assignments) {
  return Object.entries(assignments).map(([relicId, operatorInstanceId]) => ({ type: 'relicEnchant', relicId, operatorInstanceId }));
}

export function manualTrainingPromotion(previous, next, relics, assignments, entries) {
  return previous?.elite === 1 && next.elite === 2 && relics.some(relic =>
    entries[relic.id]?.enchantmentProfession === next.profession
    && (assignments[relic.id] || relic.enchantment?.operatorInstanceId) === next.instanceId);
}
