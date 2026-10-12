import React, { useEffect, useState } from 'react';
import { ChevronDown, Heart, Swords, Gauge, Layers, RefreshCw, LoaderCircle, Shield, Coins, Zap, Snowflake, Settings2, Package } from 'lucide-react';
import { api } from './api';
import { EntryImage, Modal } from './common';
import { ATTRIBUTE_LABELS, COMBAT_CATEGORY_ORDER, attributeValue, effectValue, indicatorGroups } from './combatPresentation';
import './combatBonuses.css';

const CATEGORY_ICONS = { survival: Shield, damage: Swords, cost: Coins, skill_cycle: Zap,
  control: Snowflake, mechanism: Settings2, support: Package };
const ATTRIBUTE_ICONS = { max_hp: Heart, attack: Swords, attack_speed: Gauge };

function AttributeSummary({ cells }) {
  return <div className="combat-attributes" role="table" aria-label="六项属性加成">
    <div className="combat-attribute-heading" role="row"><span role="columnheader">属性</span><span role="columnheader">局外</span><span role="columnheader">局内</span></div>
    {Object.entries(ATTRIBUTE_LABELS).map(([metric, label]) => {
      const Icon = ATTRIBUTE_ICONS[metric];
      return <div className="combat-attribute-row" role="row" key={metric}><span role="rowheader"><Icon size={17} />{label}</span>
        {['outside_battle', 'inside_battle'].map(domain => {
          const cell = cells.find(item => item.metric === metric && item.domain === domain);
          return <b role="cell" data-combat-metric={`${metric}-${domain}`} key={domain}
            className={Number(cell?.relativePercent) < 0 || Number(cell?.flatDelta) < 0 ? 'negative' : ''}>{attributeValue(cell)}</b>;
        })}</div>;
    })}
  </div>;
}

function LayerEnvironment({ environment, entries }) {
  return <section className="combat-environment" aria-label="本层环境"><header><Layers size={16} /><b>本层实托邦 / 乌托邦</b><small>单列影响 · 不计入加成合计</small></header>
    {environment ? <><div className="combat-environment-name"><EntryImage entry={entries[environment.id]} className="combat-environment-icon" /><b>{environment.name}</b><span>{environment.kind}{environment.tierLabel && ` · ${environment.tierLabel}`} · {environment.scope}</span></div>
      <p>{environment.effect}</p>{environment.policy && <p><b>{environment.policy.name}：</b>{environment.policy.effect}</p>}</>
      : <p className="combat-muted">本层无已记录的实托邦 / 乌托邦</p>}
  </section>;
}

function EffectSources({ row, entries }) {
  return <div className="combat-effect-details">
    <div className="combat-effect-result"><b>{row.strategy === 'describe' ? row.valueText : effectValue(row)}</b>
      <span>{row.bucket === 'constant' ? '已生效' : row.bucket === 'unresolved' ? '待确认' : row.bucket === 'related' ? '相关对象效果' : '条件生效'}</span></div>
    {row.conditionText !== '无额外条件' && <p className="combat-condition">{row.conditionText}</p>}
    {row.strategy === 'numeric' && Number(row.flatDelta) && Number(row.relativeFactor) !== 1 ? <p className="combat-condition">{row.valueText}</p> : null}
    {!!row.multiplicationZones?.length && <div className="combat-zone-list">{row.multiplicationZones.map((zone, index) => <span key={zone.id}>
      乘区 {index + 1}：{zone.flatDelta !== '0' ? `固定增量 ${zone.flatDelta}；` : ''}×{Number(((1 + Number(zone.baseRatioDelta)) * Number(zone.factor)).toFixed(4))}
    </span>)}</div>}
    <ul className="combat-source-list">{row.sources.map((source, index) => <li key={`${source.clauseId}-${source.acquisitionId || index}`}>
      {source.type === 'relic' ? <EntryImage entry={entries[source.id]} className="combat-source-icon" /> : <Layers className="combat-source-icon" />}
      <div><div className="combat-source-heading"><b>{source.name}</b>{source.valueText && <span>{source.valueText}</span>}</div>
        {source.resolvedCount != null && <small>{source.resolvedFrom === 'snapshot_count' ? '当前计数' : '当前层数 / 计数'} {source.resolvedCount}</small>}
        {source.scopeText && <small>{source.scopeText}</small>}
        {!!source.operatorInstanceIds?.length && <small>已绑定当前受益干员</small>}
        {source.originalText && <p>{source.originalText}</p>}</div>
    </li>)}</ul>
  </div>;
}

function BonusCategory({ category, entries }) {
  const Icon = CATEGORY_ICONS[category.id];
  const groups = indicatorGroups(category.rows);
  return <details className="combat-category" data-combat-category={category.id}>
    <summary><Icon size={18} /><b>{category.name}</b><span>{groups.length ? `${groups.length} 项指标` : '无相关效果'}</span><ChevronDown size={16} className="combat-chevron" /></summary>
    {groups.length ? <div className="combat-indicators">{groups.map(group => <details className="combat-indicator" key={group.key}>
      <summary><div className="combat-indicator-heading"><b>{group.label}</b><small>{group.side} · {group.domain}{group.tagText && ` · ${group.tagText}`}</small></div>
        <div className="combat-indicator-value"><b>{group.preview}</b>{group.additionalCount > 0 && <small>{group.additionalCount} 组条件 / 描述</small>}</div><ChevronDown size={15} className="combat-chevron" /></summary>
      {group.rows.map((row, index) => <EffectSources key={index} row={row} entries={entries} />)}
    </details>)}</div> : <p className="combat-empty">无相关效果</p>}
  </details>;
}

export default function CombatBonusDialog({ loaded, areaKey, entries, operatorInstanceId, onClose }) {
  const [result, setResult] = useState(null), [error, setError] = useState(''), [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true); setError(''); setResult(null);
    async function calculate() {
      // On retry, read the authoritative revision rather than reusing stale inputs.
      const current = attempt ? await api(`/api/runs/${loaded.runId}`) : loaded;
      return api(`/api/runs/${loaded.runId}/combat-bonuses`, { method: 'POST', body: {
        expectedRevision: current.revision, areaKey, operatorInstanceId: operatorInstanceId || null,
      } });
    }
    calculate().then(value => { if (live) setResult(value); }).catch(reason => {
      if (live) setError(reason.status === 409 ? '对局已更新，请刷新计算。' : reason.message || '加成计算失败，请重试。');
    }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [loaded, areaKey, operatorInstanceId, attempt]);
  const report = result?.report;
  const view = operatorInstanceId ? report?.operators.find(item => item.operator.instanceId === operatorInstanceId) : report?.global;
  const name = loaded.state.operators.find(item => item.instanceId === operatorInstanceId)?.name;
  return <Modal title={`${operatorInstanceId ? name || '干员' : '全体干员'} · 战斗加成`} onClose={onClose} wide>
    <div className="combat-bonuses">
      {loading ? <div className="combat-loading" role="status"><LoaderCircle size={22} className="spin" />计算中</div> : error ? <div className="combat-error" role="alert"><p>{error}</p><button onClick={() => setAttempt(value => value + 1)}><RefreshCw size={16} />刷新计算</button></div> : view && <>
        <div className="combat-context"><span>N{report.difficulty} · 已保存对局 v{result.revision}</span><span>藏品 / 局外科技 / 难度</span></div>
        <AttributeSummary cells={view.attributeSummary} />
        {view.attributeSummary.some(cell => cell.pendingCount > 0) && <p className="combat-condition">部分属性数值待确认；上方仅显示已确认部分，详见分类。</p>}
        <LayerEnvironment environment={report.environment} entries={entries} />
        <div className="combat-category-list">{COMBAT_CATEGORY_ORDER.map(id => (view.detailCategories || view.categories).find(category => category.id === id)).filter(Boolean)
          .map(category => <BonusCategory key={category.id} category={category} entries={entries} />)}</div>
        {!!report.notices.length && <details className="combat-notices"><summary>计算提示 · {report.notices.length}</summary><ul>{report.notices.map((text, index) => <li key={index}>{text}</li>)}</ul></details>}
        <p className="combat-footnote">不含干员技能、天赋、模组；条件效果不等于常驻效果，不据此自动判定战力。</p>
      </>}
    </div>
  </Modal>;
}
