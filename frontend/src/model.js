export const AREA_NAMES = { I: 'I · 玻利瓦尔肤层', II: 'II · 甜美的伤口', III: 'III · 血色空脉',
  'III-treehole': 'III · 未萌生摇篮', IV: 'IV · 受害者腐殖', 'IV-remembrance': 'IV · 追忆',
  'IV-treehole': 'IV · 未萌生摇篮', V: 'V · 卡德霍之颅', 'V-treehole': 'V · 未萌生摇篮', VI: 'VI · 源流交汇处' };
export const SOURCES = { normal: '普通招募', temporary: '临时招募', assistance: '应急助力', emergency: '应急助力', 'squad_002-temporary': '临时招募', squad_002: '普通招募' };
export const PROFESSIONS = ['先锋', '近卫', '重装', '狙击', '术师', '医疗', '辅助', '特种'];
export const TERM_NAMES = { experience: '经验', cash: '源石锭', tickets: '招募券', components: '零件', relics: '藏品',
  paintedBonus: '涂装加成', typeExpectation: '节点类别期望', encounterExpectation: '事件期望', eventExtra: '事件附加',
  cashCost: '现金支出', naturalTributeCost: '上贡自然物', entry: '商店机会', withdrawalCash: '投资取钱', chosenOption: '事件选项', controller: '笼控器',
  recruitment: '招募', treehole: '树洞', actionPoints: '行动力', terminal: '离层', hope: '希望' };
Object.assign(TERM_NAMES, { sandboxAlpha: '沙盘α（结局前置）', promotion: '归队进阶',
  exchangeOpportunity: '交换机会', dystopiaCashCost: '改良：现金损失', dystopiaNaturalAppraisal: '增益：自然物估价',
  combat80Percent: '80%概率触发湖中魇战斗', directRelic20Percent: '20%概率直接获得藏品', conditionalRounds: '逐轮扣血与奖励期望',
  actionOpportunity: '获得行动力的机会收益', hopefulSoil: '下层希望的沃土', seedCost: '消耗1种子',
  remembrance: '取得追忆', utopiaCash: '乌托邦：完成节点的额外源石锭', fruitMarkNatural: '藏果地自然物期望',
  hopefulSoilComponent: '希望的沃土：额外零件', treeholeCombatExpectation: '树洞战斗：本层与下层奖励期望',
  freeVisit: '免费前往目标的收益', component: '零件收益', temporarySixStar: '随机临时招募六星',
  lifeShieldExcluded: '生命与护盾（暂不计分）', nextLayerCombat: '下层普通战斗期望',
  delayedProcessing: '延迟获得加工品', delayedHope: '延迟获得希望', treeholeActionProxy: '树洞行动力机会',
  bestMenuExpectation: '随机选项中的最佳收益期望', duelReward: '狭路相逢奖励',
  fakeFateRelic: '假命运所指藏品', heldRecruitmentTickets: '留存招募券使用', cornAppraisal: '玉米估价增加',
  strategyAdjustment: '本层权重调整', merchantPrefixAdjustment: '到店预测经济调整', tributePrefixAdjustment: '到达上贡时现金损失调整',
  endingPlacementExpectation: '结局前置与普通节点的混合期望', exitProcessing: '离层零件', remainingHope: '剩余行动力转希望',
  nextLayerAP: '携带下层行动力', pursuitTicket: '追猎招募券' });
Object.assign(TERM_NAMES, { finalBattle: '终战结算（当前无奖励）', treeholeReturn: '树洞返回（无额外奖励）', emptyEventPenalty: '空过事件惩罚', conditionalMarkExpectation: '结局标记条件期望' });

const SCORE_NOTES = {
  'empty event penalty pending': '空过事件的惩罚分尚未设置',
  'no seed/controller: empty event penalty pending': '没有种子或笼控器，红苔无法获得沃土；空过惩罚分尚未设置',
  'planned tribute needs two held natural components': '自然物不足2件，无法上贡',
  'random tribute assumes uniform selection of two held natural-component instances': '随机上贡按当前自然物实例等概率选2件估计',
  'tribute item identities remain frozen during search; confirm inventory and replan': '上贡物品按当前库存估算，实际结果确认后重新规划',
  'tribute appraisal uses confirmed values only': '部分自然物估价未填写，损失参考仅含已知估价',
  'variable combat cash distribution unpriced': '该战斗的随机现金分布尚未量化',
  'eligible events missing weight': '部分合资格事件缺少统计权重', 'empty sampled encounter pool': '没有可用的不期而遇统计样本',
  'no nonzero category evidence; no invented posterior': '候选节点没有非零样本，无法估分',
  'unclassified node; confirm its category before interpreting its utility': '节点类型尚未确认',
};
export const scoreNote = text => SCORE_NOTES[text] || text;

const PREREQUISITE_NAMES = { ending3_autopsy: '无效验尸', ending3_trade: '失与得上贡',
  ending3_tribute: '泪之聚落上贡', ending2_sandbox: '线人（沙盘α）', ending3_beacon: '先行一步（怦然信标）' };

export function typeScoreRows(value, nodeTypes = {}) {
  return (value.types || []).flatMap(type => {
    const name = nodeTypes[type.categoryId] || type.categoryId;
    const branches = type.score.branches?.filter(row => row.probability > 0);
    if (!branches?.length) return [{ ...type, key: type.categoryId, name }];
    return branches.map((branch, index) => ({ categoryId: type.categoryId, key: `${type.categoryId}-${index}`,
      name: branch.score.stage || PREREQUISITE_NAMES[branch.score.goalId]
        || (branch.name === '普通节点' ? name : `${name} · ${branch.name}`),
      probability: type.probability * branch.probability, score: branch.score }));
  });
}

export function stepScoreDetails(row, nodeValues = {}) {
  const frozen = nodeValues[row.frozenBreakdownNodeId];
  if (!frozen) return row;
  const details = Object.fromEntries(['classification', 'types', 'events', 'branches', 'actionGainEstimate']
    .filter(key => frozen[key] != null).map(key => [key, frozen[key]]));
  if (details.types && row.merchantTypes?.length) {
    const shops = new Map(row.merchantTypes.map(type => [type.categoryId, type.merchant]));
    details.types = details.types.map(type => shops.has(type.categoryId) ? { ...type,
      score: { points: shops.get(type.categoryId).points, parts: shops.get(type.categoryId).parts, merchant: shops.get(type.categoryId) } } : type);
  }
  return { ...details, ...row };
}

export const num = value => value == null ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(value);
export const pct = value => `${((value || 0) * 100).toFixed(1)}%`;
export const uid = prefix => `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;

export const operatorProgressLabel = elite => elite == null ? '待确认' : elite === 2 ? '已进阶' : '未进阶';

export function operatorProgressOptions(rarity, elite) {
  const unpromoted = elite === 0 || rarity != null && rarity < 3 ? 0 : 1;
  return rarity == null || rarity >= 4 || elite === 2 ? [unpromoted, 2] : [unpromoted];
}

export function currentInstance(state, areaKey) {
  const slot = state?.areas?.[areaKey];
  return slot?.instances?.find(row => row.instanceId === slot.activeInstanceId) || null;
}

export function nodeCategory(node) { return node.resolvedCategoryId || node.observedCategoryId || 'unknown_mystery'; }

export function componentCommands(before, draft) {
  const commands = [];
  if (draft.capacity > before.capacity) commands.push({ type: 'componentCapacity', value: draft.capacity });
  const old = new Map(before.items.map(row => [row.instanceId, row]));
  const live = new Set(draft.items.map(row => row.instanceId));
  for (const row of before.items) if (!live.has(row.instanceId)) commands.push({ type: 'componentRemove', instanceId: row.instanceId });
  for (const row of draft.items) {
    // The draft already includes acquisition growth and moss's bundled balls.
    if (!old.has(row.instanceId)) commands.push({ type: 'componentAdd', ...row, recordOnly: true });
    else {
      const changes = Object.fromEntries(['remainingUses', 'estimatedValue', 'routeCandidate']
        .filter(key => row[key] !== old.get(row.instanceId)[key]).map(key => [key, row[key]]));
      if (Object.keys(changes).length) commands.push({ type: 'componentUpdate', instanceId: row.instanceId, changes });
    }
  }
  if (draft.capacity < before.capacity) commands.push({ type: 'componentCapacity', value: draft.capacity });
  return commands;
}

export function areaFromObservation(observation) {
  return observation.area === 'treehole' ? null : ['I', 'II', 'III', 'IV', 'V', 'VI'][observation.floor - 1] || null;
}
