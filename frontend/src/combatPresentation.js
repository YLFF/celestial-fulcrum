export const COMBAT_CATEGORY_ORDER = ['survival', 'damage', 'cost', 'skill_cycle', 'control', 'mechanism', 'support'];
export const ATTRIBUTE_LABELS = { max_hp: '生命', attack: '攻击', attack_speed: '攻速' };

const INDICATOR_SECTIONS = {
  survival: [
    ['生命与敌方输出', ['max_hp', 'current_hp', 'hp_loss', 'attack', 'damage_dealt', 'boss_ability_modifier']],
    ['屏障与减伤', ['barrier', 'damage_blocking_shield', 'damage_block_layers', 'damage_taken', 'physical_damage_taken', 'arts_damage_taken']],
    ['恢复效果', ['healing_received', 'hp_recovery_received', 'hp_recovery_per_second', 'hp_regeneration_per_second', 'hp_recovery']],
    ['防御与抗性', ['defense', 'resistance', 'dodge_probability', 'status_immunity', 'camouflage', 'elemental_buildup_received', 'remove_elemental_self_dot']],
    ['其他生存效果', ['block_count']],
  ],
  damage: [
    ['攻击与攻速', ['attack', 'attack_speed']],
    ['伤害增幅', ['damage_dealt', 'damage_taken', 'vulnerability', 'extra_damage']],
    ['敌方生命与防御', ['max_hp', 'random_enemy_max_hp', 'defense', 'resistance', 'enemy_defense_ignore', 'enemy_resistance_reduction']],
    ['元素与弹药', ['elemental_buildup_received', 'elemental_burst_enhancement', 'ammo_restore']],
  ],
  cost: [['部署与费用', ['deployment_cost', 'deployment_cost_shuffle', 'initial_dp', 'dp_recovery', 'dp_grant']]],
  skill_cycle: [
    ['技力需求与初始技力', ['skill_sp_cost', 'initial_sp']],
    ['技力回复', ['sp_recovery_per_second', 'sp_recovery_per_attack', 'sp_recovery_per_hit', 'direct_sp_grant']],
    ['技能限制', ['skill_activation_forbidden', 'skill_auto_activation']],
  ],
  control: [['异常与控制', ['status_duration', 'stun', 'levitate', 'sluggish', 'weight', 'disable_special_abilities']]],
  mechanism: [
    ['部署与再部署', ['redeployment_time', 'remaining_redeployment_time', 'allowed_deployment_tiles', 'uses_deployment_capacity']],
    ['特殊机制', ['summon', 'boss_ability_modifier', 'additional_enemies']],
  ],
  support: [['支援道具', ['support_item']]],
};

function indicatorOrder(category, metric) {
  const sections = INDICATOR_SECTIONS[category] || [];
  for (let index = 0; index < sections.length; index += 1) {
    const rank = sections[index][1].indexOf(metric);
    if (rank !== -1) return { section: sections[index][0], sectionRank: index, metricRank: rank };
  }
  return { section: '其他效果', sectionRank: sections.length, metricRank: 0 };
}

export function signed(value, suffix = '') {
  const number = Number(value || 0);
  return `${number >= 0 ? '+' : ''}${Number(number.toFixed(4))}${suffix}`;
}

export function attributeValue(cell) {
  if (!cell) return '—';
  if (cell.status === 'partial' && cell.sources?.length === 0) return '待确认';
  const parts = [];
  const flat = Number(cell.flatDelta), percent = Number(cell.relativePercent);
  if (flat || cell.metric === 'attack_speed') parts.push(signed(flat, ' 点'));
  if (percent || !parts.length) parts.push(signed(percent, '%'));
  return parts.join(' / ');
}

export function effectValue(row) {
  if (row.strategy === 'numeric') return attributeValue(row);
  if (['evasion', 'vulnerability'].includes(row.strategy)) return `${Number((Number(row.ratio) * 100).toFixed(4))}%`;
  return row.bucket === 'unresolved' ? '待确认' : '效果说明';
}

export function indicatorGroups(rows) {
  const groups = new Map();
  for (const row of rows) {
    const key = JSON.stringify([row.metric, row.domain, row.side, Object.entries(row.tags || {}).sort(),
      Object.entries(row.displayScope || {}).sort()]);
    if (!groups.has(key)) groups.set(key, { key, metric: row.metric, label: row.metricLabel,
      domain: row.domainLabel, domainId: row.domain, side: row.scopeLabel || row.sideLabel,
      scopeBreadth: row.scopeBreadth || 0, tagText: row.tagText, rows: [],
      ...indicatorOrder(row.category, row.metric) });
    groups.get(key).rows.push(row);
  }
  return [...groups.values()].map(group => {
    const known = group.rows.filter(row => row.bucket === 'constant' ||
      row.strategy === 'numeric' && row.sources.every(source => source.resolvedFrom === 'snapshot_count'));
    const values = [...new Set(known.map(effectValue))];
    const remaining = group.rows.length - known.length;
    return { ...group, preview: values.join('；') || (group.rows.some(row => row.bucket === 'unresolved') ? '待确认' : '条件效果'),
      additionalCount: remaining, sourceCount: new Set(group.rows.flatMap(row => row.sources.map(source => source.id))).size };
  }).sort((a, b) => a.sectionRank - b.sectionRank || a.metricRank - b.metricRank ||
    a.scopeBreadth - b.scopeBreadth || (a.domainId === 'inside_battle') - (b.domainId === 'inside_battle') ||
    String(a.side).localeCompare(String(b.side), 'zh-CN') || String(a.tagText).localeCompare(String(b.tagText), 'zh-CN'));
}
