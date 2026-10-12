export function searchOptionsError(topK, maxStates) {
  if (!Number.isInteger(topK) || topK < 1 || topK > 50) return '显示路线数量需为 1-50 的整数。';
  if (!Number.isInteger(maxStates) || maxStates < 1 || maxStates > 500000) return '路径搜索上限需为 1-500000 的整数。';
  return null;
}
