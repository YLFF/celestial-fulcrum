export const emptyDystopia = () => ({ active: false, ideologyId: null, policyId: null,
  affectedNodeIds: [], uncertainNodeIds: [], idealSourceNodeId: null });

export function coverageStatus(value, id) {
  return value?.affectedNodeIds?.includes(id) ? 'inside' : value?.uncertainNodeIds?.includes(id) ? 'unknown' : 'outside';
}

export function setCoverage(value, ids, status) {
  const selected = new Set(ids);
  const result = { ...value, affectedNodeIds: value.affectedNodeIds.filter(id => !selected.has(id)),
    uncertainNodeIds: value.uncertainNodeIds.filter(id => !selected.has(id)) };
  if (status === 'inside') result.affectedNodeIds.push(...ids);
  if (status === 'unknown') result.uncertainNodeIds.push(...ids);
  if (selected.has(value.idealSourceNodeId) && status !== 'inside') result.idealSourceNodeId = null;
  return result;
}

export function dystopiaFromObservation(observation, previous) {
  const candidate = observation?.dystopiaObservation;
  if (!candidate?.active) return structuredClone(previous || emptyDystopia());
  const same = previous?.active && previous.ideologyId === candidate.ideologyId;
  let value = { ...emptyDystopia(), active: true, ideologyId: candidate.ideologyId,
    policyId: candidate.policyId || (same ? previous.policyId : null), idealSourceNodeId: null };
  for (const node of observation.nodes) {
    const status = candidate.nodeEvidence?.[node.id]?.affected;
    value = setCoverage(value, [node.id], status === true ? 'inside' : status === false ? 'outside' :
      same ? coverageStatus(previous, node.id) : 'unknown');
  }
  const previousSource = same && observation.nodes.some(node => node.id === previous.idealSourceNodeId) ? previous.idealSourceNodeId : null;
  value.idealSourceNodeId = candidate.ideologyId === 'dystopia_008' ? null : candidate.idealSourceNodeId || previousSource;
  if (value.idealSourceNodeId) value = { ...setCoverage(value, [value.idealSourceNodeId], 'inside'), idealSourceNodeId: value.idealSourceNodeId };
  return value;
}
