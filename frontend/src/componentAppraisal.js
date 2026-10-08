import { uid } from './model.js';

export function appraisalDraft(box, event, catalog) {
  const rules = catalog.componentAppraisalEvents[event];
  if (!rules) throw new Error('不支持的估价更新');
  return { ...box, items: box.items.map(row => ({ ...row,
    estimatedValue: row.estimatedValue == null ? null : row.estimatedValue + (rules[row.componentId] || 0),
  })) };
}

export function acquireDraft(box, entry, catalog) {
  const bundled = entry.id === 'component_007';
  const add = (draft, row, initial) => {
    const grown = appraisalDraft(draft, 'acquire', catalog);
    const uses = catalog.componentInitialUses[row.id] ?? null;
    return { ...grown, items: [...grown.items, { instanceId: uid('part'), componentId: row.id,
      estimatedValue: initial, remainingUses: uses, routeCandidate: uses != null }] };
  };
  let draft = add(box, entry, bundled ? 2 : (entry.initialEstimatedValue ?? null));
  if (bundled) {
    const ball = catalog.component.find(row => row.id === 'component_008');
    for (let i = 0; i < 3; i++) draft = add(draft, ball, ball.initialEstimatedValue);
  }
  return draft;
}
