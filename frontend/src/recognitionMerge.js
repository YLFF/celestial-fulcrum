const CLEARING = 'node_type_020';
const concrete = id => !!id && !id.startsWith('unknown_') && id !== 'start';

export function recognitionChanges(observation, previous, newInstance = false) {
  if (!observation?.success || newInstance || previous?.templateId !== observation.templateId) return [];
  return observation.nodes.flatMap(row => {
    const old = previous.nodes[row.id];
    if (!old) return [];
    const before = old.resolvedCategoryId || old.observedCategoryId;
    if (old.completion === 'completed') return [];
    if (row.categoryId === CLEARING && before !== CLEARING && before !== 'start')
      return [{ nodeId: row.id, kind: 'completion', before, after: before }];
    if (concrete(row.categoryId) && before !== row.categoryId)
      return [{ nodeId: row.id, kind: concrete(before) ? 'conflict' : 'reveal', before, after: row.categoryId }];
    return [];
  });
}

export function recognitionReview(observation, previous, newInstance = false) {
  if (!observation?.success) return [];
  const compatible = !newInstance && previous?.templateId === observation.templateId;
  return observation.nodes.flatMap(row => {
    const old = compatible ? previous.nodes[row.id] : null;
    if (old?.completion === 'completed') return [];
    const becameClearing = old && row.categoryId === CLEARING &&
      (old.resolvedCategoryId !== CLEARING && old.observedCategoryId !== CLEARING);
    const current = row.id === observation.playerPositionObservation?.nodeId;
    if (current && row.id === '0,0' && row.categoryId === 'start' && !old?.resolvedCategoryId) return [];
    if (!becameClearing && !current) return [];
    const categoryId = old?.resolvedCategoryId || old?.completedCategoryId || (becameClearing ? null : row.categoryId);
    return [{ nodeId: row.id, categoryId: concrete(categoryId) ? categoryId : '',
      encounterId: old?.encounterId || null, reason: becameClearing ? 'clearing' : 'position' }];
  });
}

export function mergedRecognitionPreview(observation, previous, options) {
  if (!observation?.success) return null;
  const { newInstance, position, completePosition, nodeChanges, completions, encounters, markChoices, dystopia, utopiaId } = options;
  const compatible = !newInstance && previous?.templateId === observation.templateId;
  return { templateId: observation.templateId, edges: observation.edges, playerPosition: position, dystopia, utopiaId,
    nodes: Object.fromEntries(observation.nodes.map(row => {
      const old = compatible ? previous.nodes[row.id] : null;
      const override = nodeChanges[row.id];
      const category = override || (concrete(old?.resolvedCategoryId) ? old.resolvedCategoryId : row.categoryId);
      const completed = old?.completion === 'completed' || completions[row.id] || (row.id === position && completePosition);
      return [row.id, { ...old, ...row, observedCategoryId: override || row.categoryId || old?.observedCategoryId || null,
        resolvedCategoryId: concrete(category) ? category : null,
        encounterId: encounters[row.id] || old?.encounterId || null,
        confirmedMarkIds: old?.confirmedMarkIds || [], candidateMarkIds: markChoices[row.id] || [],
        visibility: row.visibility === 'revealed' ? 'revealed' : old?.visibility || row.visibility,
        completion: completed ? 'completed' : old?.completion || 'unknown' }];
    })) };
}
