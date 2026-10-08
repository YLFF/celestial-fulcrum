const RANK_FIELDS = ['weightedValue', 'newNodes', 'newlyRevealedOtherNodes', 'treeholesReached',
  'survivingProcessingItems', 'remainingItemUses'];

export function relatedGoals(route) {
  return route.relatedGoalIds || (route.prerequisites || []).filter(row =>
    row.related || row.plannedCompletion || row.searchCoverage > 0).map(row => row.id);
}

export function filterRoutes(planning, selectedIds = [], mode = 'all', topN = 5) {
  if (!planning) return [];
  const pool = [...(planning.routes || []), ...(planning.routeGroups || []).flatMap(group => group.routes)];
  const matched = pool.filter(route => {
    const related = new Set(relatedGoals(route));
    return mode === 'any' ? !selectedIds.length || selectedIds.some(id => related.has(id)) :
      selectedIds.every(id => related.has(id));
  }).sort((left, right) => {
    for (const field of RANK_FIELDS) {
      const difference = (right.metrics[field] || 0) - (left.metrics[field] || 0);
      if (difference) return difference;
    }
    return 0;
  });
  const seen = new Set();
  return matched.filter(route => {
    const key = JSON.stringify([route.goalType, route.endNode, route.steps.map(step => [step.entered, step.arrived])]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, topN);
}
