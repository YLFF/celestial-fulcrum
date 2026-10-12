export const relicActive = row => row.state === true || ['active', '已生效'].includes(row.state) || !!row.enchantment;

export const boundRecipients = row => row.enchantment?.recipients
  || (row.enchantment?.operatorInstanceId ? [row.enchantment] : []);
export const recipientIds = value => (Array.isArray(value) ? value : value ? [value] : []).filter(Boolean);
export const relicManagement = entry => entry?.management || (entry?.enchantmentProfession
  ? { kind: 'one_shot', bindOperator: true, maxRecipients: 1, profession: entry.enchantmentProfession, promotionEffect: true }
  : { kind: 'ordinary' });

export function toggleRecipient(assignments, relicId, operatorId, checked) {
  const next = { ...assignments }, ids = recipientIds(next[relicId]).filter(id => id !== operatorId);
  if (checked) ids.push(operatorId);
  if (ids.length) next[relicId] = ids; else delete next[relicId];
  return next;
}

export function newestRelics(rows) {
  return rows.map((row, index) => ({ row, index })).reverse();
}

export function relicStatus(row, entry, state) {
  const management = relicManagement(entry);
  if (management.bindOperator) return { readOnly: true, label: relicActive(row) ? '已生效' : '未生效' };
  if (entry?.automaticCounter) {
    let value = state.relicRuntime?.[row.id]?.value;
    if (entry.automaticCounter === 'snapshot') {
      const count = entry.snapshotCounter.field === 'cash' ? state.resources?.originiumIngot : state.componentBox?.items.length;
      value = count == null ? null : Math.floor(count / (entry.snapshotCounter.unitSize || 1));
    } else if (value == null && state.currentAreaKey) {
      const floors = { I: 1, II: 2, III: 3, IV: 4, V: 5, VI: 6 }, current = state.currentAreaKey;
      const floor = floors[current.split('-')[0]], visited = Object.entries(state.areas || {})
        .filter(([key, slot]) => slot.activeInstanceId && floors[key.split('-')[0]] <= floor).map(([key]) => key);
      if (!visited.includes(current)) visited.push(current);
      const caves = visited.filter(key => key.endsWith('-treehole')).length;
      value = floor + (entry.automaticCounter === 'entered_regions' ? Math.min(1, caves) : caves + Number(visited.includes('IV-remembrance')));
    }
    return { readOnly: true, label: `${value ?? '待确认'} 层${management.ineffectiveAt != null && value >= management.ineffectiveAt ? ' · 已失效' : ''}` };
  }
  return { readOnly: management.kind === 'ordinary', kind: management.kind, label: '' };
}

export function canEnchant(row, operator, entries) {
  const management = relicManagement(entries[row.id]);
  return !!management.bindOperator && !relicActive(row)
    && (!management.profession || operator.profession === management.profession)
    && (!management.promotionEffect || ([1, 2].includes(operator.elite) && operator.rarity >= 4 && operator.remainingBattles == null));
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
  return Object.entries(assignments).filter(([, value]) => recipientIds(value).length)
    .map(([relicId, value]) => recipientIds(value).length === 1
      ? { type: 'relicEnchant', relicId, operatorInstanceId: recipientIds(value)[0] }
      : { type: 'relicEnchant', relicId, operatorInstanceIds: recipientIds(value) });
}

export function manualTrainingPromotion(previous, next, relics, assignments, entries) {
  return previous?.elite === 1 && next.elite === 2 && relics.some(relic =>
    entries[relic.id]?.enchantmentProfession === next.profession
    && [...recipientIds(assignments[relic.id]), ...boundRecipients(relic).map(item => item.operatorInstanceId)].includes(next.instanceId));
}
