export const POSITION_FILTERS = [
  ['node_type_013', '秘境行商'], ['node_type_004', '诡意行商'], ['node_type_010', '误入奇境'],
  ['node_type_011', '狭路相逢'], ['node_type_006', '不期而遇'], ['node_type_009', '先行一步'],
  ['autopsy', '无效验尸'], ['node_type_016', '险路小径'],
];

export function candidatePositions(instance, type) {
  if (!type) return new Set();
  return new Set(Object.entries(instance?.prediction?.unknownNodes || {}).filter(([id, row]) => {
    if (instance.nodes[id]?.resolvedCategoryId || instance.nodes[id]?.completion === 'completed') return false;
    return type === 'autopsy' ? row.endingOccupancy?.some(value => value.goalId === 'ending3_autopsy' && value.probability > 0)
      : row.candidates?.some(value => value.categoryId === type);
  }).map(([id]) => id));
}

export function routeCurve(a, b, index = 0) {
  const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy);
  if (!length) return null;
  const bend = Math.min(80, Math.max(56, length * .3)) * (index % 2 ? -1 : 1);
  const mx = (a.x + b.x) / 2 - dy / length * bend;
  const my = (a.y + b.y) / 2 + dx / length * bend;
  // Stop at the target disc, keeping the directional arrow visible.
  const tail = Math.hypot(b.x - mx, b.y - my);
  const end = { x: b.x - (b.x - mx) / tail * 27, y: b.y - (b.y - my) / tail * 27 };
  return `M ${a.x} ${a.y} Q ${mx} ${my} ${end.x} ${end.y}`;
}
