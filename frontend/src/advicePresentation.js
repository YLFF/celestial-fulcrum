export function filterAdvice(result, ids = [], match = 'all', limit = 5) {
  return (result?.suggestions || []).filter(row => {
    const related = new Set(row.relatedGoalIds || []);
    return match === 'any' ? !ids.length || ids.some(id => related.has(id)) : ids.every(id => related.has(id));
  }).slice(0, limit);
}

export function adviceMapRoute(row) {
  return row && !row.random ? { steps: [row.firstStep] } : null;
}

export const EXIT_STATUS = {
  reachable: '保留已知离层走法',
  undetermined: '离层检查达到上限，尚未确定',
  no_known_exit: '现有库存下未找到已知离层走法',
  transfer_boundary: '树洞入口，进入后重新规划',
};

export function policyName(policy, goals) {
  return ({ income: '发育方向', mobility: '保留传送方向', information: '探索方向' })[policy]
    || goals.find(goal => policy === `goal:${goal.id}`)?.name || '后续方向';
}
