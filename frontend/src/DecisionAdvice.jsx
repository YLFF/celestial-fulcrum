import React, { useState } from 'react';
import { ArrowRight, Footprints, Shuffle, Navigation, ChevronDown } from 'lucide-react';
import { num, pct, routeNodeName } from './model';
import { EXIT_STATUS, policyName } from './advicePresentation';
import ScoreDetails from './ScoreDetails';

export default function DecisionAdvice({ result, rows, selectedIndex, onSelect, instance, catalog, entries }) {
  const name = id => routeNodeName(id, instance?.nodes, catalog.labels.nodeTypes);
  const movement = step => step.componentId ? entries[step.componentId]?.name || '加工品' : '徒步';
  return <div className="decision-advice">
    <div className="search-summary"><span>一步建议 · {result.expandedStates.toLocaleString()} 次推演 · {num(result.metrics.seconds)} 秒</span>
      <span>{result.metrics.firstActions} 种第一步 · {rows.length} 条建议{result.metrics.randomLandings > 0 && ` · ${result.metrics.randomLandings} 个随机落点`}</span>
      <span>{result.searchComplete ? '本次预算内完成' : '推演达到预算上限'}{result.metrics.beamDiscarded > 0 && ' · 保留多策略候选'}</span></div>
    {!rows.length && <div className="route-empty">没有符合当前筛选条件的一步建议</div>}
    <div className="advice-list">{rows.map((row, index) => <section className={`advice-row ${index === selectedIndex ? 'selected' : ''}`} key={row.id}>
      <div className="advice-heading"><button className="advice-choice" aria-label={`选择建议 ${index + 1}`} onClick={() => onSelect(index)}>
        {row.random ? <Shuffle size={18} /> : row.firstStep.componentId ? <Navigation size={18} /> : <Footprints size={18} />}
        <span><b>{row.random ? '小八戒随机前往' : name(row.firstStep.entered)}</b>
          <small>{row.random ? `${row.branches.length} 个候选落点` : `(${row.firstStep.entered}) · ${movement(row.firstStep)} · 剩余行动力 ${row.remainingActionPoints}`}</small></span>
      </button><div className="advice-scores"><b>{num(row.firstPoints)}<small>本步收益</small></b>
        <span>{num(row.lookaheadPoints)}<small>含后续推演</small></span>
        {!row.random && <span>+{num(row.revealPoints)}<small>揭示参考</small></span>}</div></div>
      <div className="advice-tags">{row.labels.map(label => <span key={label}>{label}</span>)}
        <span className={!row.random && row.exitCheck.status !== 'reachable' ? 'advice-risk' : ''}>
          {row.random ? `已知离层走法覆盖 ${pct(row.exitCoverage)}` : EXIT_STATUS[row.exitCheck.status]}</span></div>
      {row.random ? <RandomBranches row={row} name={name} movement={movement} /> : <>
        <ul className="advice-reasons">{row.reasons.map((text, i) => <li key={i}>{text}</li>)}</ul>
        {!!row.goals.length && <div className="advice-goals">{row.goals.map(goal => <span key={goal.id}>{goal.name}：
          {goal.plannedCompletion ? '本步经过已定位目标' : goal.related ? `本步探索覆盖 ${pct(goal.searchCoverage)}` : '本步未推进'}</span>)}</div>}
        <details className="advice-details"><summary><ChevronDown size={13} />本步评分构成</summary>
          {row.firstStep.scoreDetails.nodeTerms.map(term => <ScoreDetails key={term.nodeId} value={term} catalog={catalog} compact />)}
          {row.firstStep.terminalScore && <ScoreDetails value={row.firstStep.terminalScore} catalog={catalog} compact />}
        </details>
        {!!row.information.length && <details className="advice-details"><summary><ChevronDown size={13} />本步新揭示</summary>
          {row.information.map(info => <p key={info.nodeId}><b title={`(${info.nodeId})`}>{name(info.nodeId)}</b> · {info.reachableNext ? '下一步可达' : '下一步不能直接前往'}
            · 收益范围 {num(info.scoreRange[0])}～{num(info.scoreRange[1])} 分</p>)}</details>}
        <details className="advice-details"><summary><ChevronDown size={13} />后续方向与资源取舍</summary>
          {row.continuations.map(option => <div className="advice-continuation" key={option.policy}>
            <b>{policyName(option.policy, result.priorityTargets)} · {num(option.points)} 分</b>
            <div className="advice-direction">{option.steps.slice(1).map((step, i) => <React.Fragment key={i}>
              {i > 0 && <ArrowRight size={12} />}<span title={`(${step.entered})`}>{name(step.entered)}<small>{movement(step)}</small></span>
            </React.Fragment>)}{option.steps.length === 1 && <span>完成本步后重新判断</span>}</div>
            <small>剩余行动力 {option.remainingActionPoints} · 消耗全图加工品 {option.flexibleUsesSpent} 次
              {` · ${option.exitStatus ? EXIT_STATUS[option.exitStatus] : '该后续离层状态未检查'}`}</small>
            <p>{option.remainingItems.map(item => `${entries[item.componentId]?.name || item.componentId} ×${item.remainingUses}`).join('、') || '无剩余加工品'}</p>
          </div>)}
        </details>
        {!!row.exitCheck.steps.length && <details className="advice-details"><summary><ChevronDown size={13} />已知离层走法（不作为固定后续）</summary>
          <p>{row.exitCheck.steps.map(step => `${name(step.entered)}（${movement(step)}）`).join(' → ')}</p></details>}
      </>}
    </section>)}</div>
    <details className="advice-limitations"><summary>本次推演的边界</summary>{result.limitations.map(text => <p key={text}>{text}</p>)}</details>
  </div>;
}

function RandomBranches({ row, name, movement }) {
  const [expanded, setExpanded] = useState(false);
  return <div className="advice-random"><p>按候选落点等概率分别推演；落地后可重新选择方向，不预先承诺一条共同路线。</p>
    <button className="text-action" onClick={() => setExpanded(!expanded)}><ChevronDown size={14} />{expanded ? '收起落点' : '查看落点分布'}</button>
    {expanded && <div className="advice-branches">{row.branches.map(branch => <div key={branch.id}>
      <b>{name(branch.firstStep.entered)} ({branch.firstStep.entered}) · {pct(branch.probability)}</b>
      <span>本步 {num(branch.firstPoints)} · 含后续 {num(branch.lookaheadPoints)} 分</span>
      <small>{EXIT_STATUS[branch.exitCheck.status]}</small>
      <p>{branch.continuations.find(option => option.policy === 'income').steps.slice(1).map(step => `${name(step.entered)}（${movement(step)}）`).join(' → ') || '落地后重新判断'}</p>
    </div>)}</div>}
  </div>;
}
