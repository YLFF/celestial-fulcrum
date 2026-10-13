const CLEARING = 'node_type_020';
const concrete = id => !!id && !id.startsWith('unknown_') && id !== 'start';
const RESIDENT = 'node_mark_001';
const terminalCategory = hint => ({ 'danger-end': 'node_type_015', 'danger-enemy': 'node_type_003' })[hint];

export const residentActive = node => !!node?.confirmedMarkIds?.includes(RESIDENT) &&
  !(node.residentCleared ?? node.completion === 'completed');

export function mergedResidentMarks(row, old, selected) {
  const previous = old?.confirmedMarkIds || [];
  const incoming = selected ?? (row.marks || []).filter(mark => mark.status === 'confirmed').map(mark => mark.id);
  const mayBeResident = (row.marks || []).some(mark => mark.id === RESIDENT);
  return [...new Set([...previous.filter(id => id !== RESIDENT || row.categoryId == null || mayBeResident), ...incoming])];
}

export function recognitionChanges(observation, previous, newInstance = false) {
  if (!observation?.success || newInstance || previous?.templateId !== observation.templateId) return [];
  return observation.nodes.flatMap(row => {
    const old = previous.nodes[row.id];
    if (!old) return [];
    const marks = mergedResidentMarks(row, old);
    const residentChanges = marks.includes(RESIDENT) !== (old.confirmedMarkIds || []).includes(RESIDENT)
      ? [{ nodeId: row.id, kind: marks.includes(RESIDENT) ? 'residentArrival' : 'residentDeparture' }] : [];
    const before = old.resolvedCategoryId || old.observedCategoryId;
    if (old.completion === 'completed' || residentActive(old) || marks.includes(RESIDENT)) return residentChanges;
    if (row.categoryId === CLEARING && before !== CLEARING && before !== 'start')
      return [...residentChanges, { nodeId: row.id, kind: 'completion', before, after: before }];
    if (concrete(row.categoryId) && before !== row.categoryId)
      return [...residentChanges, { nodeId: row.id, kind: concrete(before) ? 'conflict' : 'reveal', before, after: row.categoryId }];
    return residentChanges;
  });
}

export function recognitionReview(observation, previous, newInstance = false) {
  if (!observation?.success) return [];
  const compatible = !newInstance && previous?.templateId === observation.templateId;
  return observation.nodes.flatMap(row => {
    const old = compatible ? previous.nodes[row.id] : null;
    const current = row.id === observation.playerPositionObservation?.nodeId;
    if (current && (residentActive(old) || (row.marks || []).some(mark => mark.id === RESIDENT && mark.status === 'confirmed')))
      return [{ nodeId: row.id, categoryId: 'node_type_021', encounterId: null, reason: 'resident' }];
    if (old?.completion === 'completed') return [];
    if (residentActive(old) || (row.marks || []).some(mark => mark.id === RESIDENT && mark.status === 'confirmed')) return [];
    const becameClearing = old && row.categoryId === CLEARING &&
      (old.resolvedCategoryId !== CLEARING && old.observedCategoryId !== CLEARING);
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
  const nodes = Object.fromEntries(observation.nodes.map(row => {
      const old = compatible ? previous.nodes[row.id] : null;
      const override = nodeChanges[row.id];
      const category = override || (concrete(old?.resolvedCategoryId) ? old.resolvedCategoryId :
        terminalCategory(row.templateHint) || row.categoryId);
      const completed = old?.completion === 'completed' || completions[row.id] || (row.id === position && completePosition);
      const clearingResident = (residentActive(old) || mergedResidentMarks(row, old, markChoices[row.id]).includes(RESIDENT)) &&
        (completions[row.id] || row.id === position && completePosition);
      const marks = mergedResidentMarks(row, old, markChoices[row.id]).filter(id => !clearingResident || id !== RESIDENT);
      return [row.id, { ...old, ...row, observedCategoryId: override || row.categoryId || old?.observedCategoryId || null,
        resolvedCategoryId: concrete(category) ? category : null,
        encounterId: encounters[row.id] || old?.encounterId || null,
        confirmedMarkIds: marks, candidateMarkIds: [], residentCleared: !marks.includes(RESIDENT),
        completedCategoryId: old?.completedCategoryId || (completed ? clearingResident ? 'node_type_021' : category : null),
        visibility: row.visibility === 'revealed' ? 'revealed' : old?.visibility || row.visibility,
        completion: completed ? 'completed' : old?.completion || 'unknown' }];
    }));
  const outpostDone = Object.values(nodes).some(node => node.completion === 'completed' && node.completedCategoryId === 'node_type_019');
  if (outpostDone) for (const node of Object.values(nodes)) {
    node.confirmedMarkIds = node.confirmedMarkIds.filter(id => id !== RESIDENT);
    node.residentCleared = true;
  }
  return { templateId: observation.templateId, edges: observation.edges, playerPosition: position, dystopia, utopiaId, nodes };
}
