import React from 'react';
import { num, pct, TERM_NAMES, scoreNote, typeScoreRows } from './model';
import { rewardPoolsFor } from './rewardPools';
import { RewardPoolButtons } from './RewardPoolPanel';

export default function ScoreDetails({ value, catalog, compact = false, rewardScope = {}, areaKey = '', onOpenPool, hidePoolButtons = false }) {
  if (!value) return <div className="empty-inline">暂无评分</div>;
  const eventNames = Object.fromEntries(catalog.encounters.map(row => [row.id, row.name]));
  const types = typeScoreRows(value, catalog.labels.nodeTypes);
  const scope = { ...rewardScope, ...(value.eventId ? { eventId: value.eventId } : {}),
    ...(value.goalId ? { goalId: value.goalId } : {}), ...(value.stage ? { stage: value.stage } : {}) };
  const label = eventNames[scope.eventId] || catalog.labels.nodeTypes[scope.categoryId] || '节点奖励';
  const splitTypes = value.types?.some(row => row.score.branches?.some(branch => branch.probability > 0));
  const conditionalMarks = [...(value.classification?.endingOccupancy || []),
    ...(value.classification?.conditionalEndingPlacements || [])];
  return <div className={`score-details ${compact ? 'compact' : ''}`}>
    {!hidePoolButtons && !types.length && !value.events?.length && !value.branches?.length && <RewardPoolButtons
      pools={rewardPoolsFor(catalog, scope, areaKey)} label={label} onOpen={onOpenPool} />}
    {value.points != null && <div className="score-total"><span>期望得分</span><b>{num(value.arrivalPoints ?? value.points)}</b></div>}
    {value.arrivalPoints != null && <><div className="score-part"><span>节点基础分</span><strong>{num(value.points)}</strong></div>
      <div className="score-part"><span>前往揭示分</span><strong>{num(value.revealValue)}</strong></div>
      {!!value.arrivalRevealTerms?.length && <details><summary>新揭示节点</summary>{value.arrivalRevealTerms.map(row =>
        <div className="score-part" key={row.nodeId}><span>({row.nodeId})</span><strong>{num(row.points)}</strong></div>)}</details>}</>}
    {Object.entries(value.parts || {}).map(([key, number]) => <div className="score-part" key={key}>
      <span>{TERM_NAMES[key] || key}</span><strong className={number < 0 ? 'negative' : ''}>{num(number)}</strong></div>)}
    {!!value.scoringBasis?.length && <div className="score-basis">{value.scoringBasis.map((row, index) =>
      <div className="score-part" key={index}><span>{row.label}</span><strong>{num(row.points)} 分</strong></div>)}</div>}
    {value.rewardModifiers && <details><summary>战斗奖励加成</summary>{Object.entries(value.rewardModifiers).map(([metric, terms]) =>
      !!terms.length && <div key={metric}><b>{metric === 'battle_cash_reward' ? '源石锭' : '指挥经验'}</b>
        {terms.map(term => <div className="score-part" key={term.clauseId}><span>{term.name}</span><strong>
          {term.operation === 'factor' ? `×${num(term.value)}` : term.operation === 'base_ratio_delta'
            ? `${term.value >= 0 ? '+' : ''}${pct(term.value)}` : `${term.value >= 0 ? '+' : ''}${num(term.value)}`}</strong></div>)}</div>)}
      <small>固定增减先结算；经验藏品增幅相加、源石锭藏品倍率相乘，科技倍率独立，最后向下取整一次。</small></details>}
    {value.actionGainEstimate != null && <div className="score-part"><span>获得 {value.actionGainEstimate} 行动力（期望收益，不预加搜索行动力）</span></div>}
    {value.fruitReward && <details><summary>藏果地自然物的期望收益</summary>
      {value.fruitReward.fruitOutcomes?.map(row => <div className="score-part" key={row.itemId}>
        <span>{catalog.component?.find(entry => entry.id === row.itemId)?.name || row.itemId} · {pct(row.probability)} × {num(row.cashEquivalent)} 源石锭等价 × {num(value.fruitReward.cashUnitPoints ?? 8)}</span>
        <strong>{num(row.probability * row.points)}</strong></div>)}
    </details>}
    {!!value.eligibleCosts?.length && <div className="score-basis">{value.eligibleCosts.map(cost => <div key={cost}>{cost}可取得追忆；仅选择一种。</div>)}</div>}
    {value.policyAdjustment && <div className="policy-summary">
      <div className="score-part"><span>{value.policyAdjustment.policyId === 'dystopia_011'
        ? `经过扣现金 ${num(value.policyAdjustment.cashLost)} × ${num(value.policyAdjustment.unitPoints ?? 8)}`
        : `${num(value.policyAdjustment.naturalCount)} 件自然物 × 2 估价 × ${num(value.policyAdjustment.unitPoints ?? 8)}`}</span>
        <strong>{num(value.policyAdjustment.points)} 分</strong></div>
      {value.policyAdjustment.policyId === 'dystopia_011' && <small>入点预测现金 {num(value.policyAdjustment.cashBefore)}，不足2时扣至0</small>}
      {value.policyAdjustment.sourceDestroyedAfter && <small>本节点结算后击破理想源，后续方针失效</small>}
    </div>}
    {value.referenceLoss && <div className="reference-loss-summary">
      <div className="score-part"><span>上贡损失（{value.referenceLoss.includedInPlanningScore ? '已扣规划分' : value.referenceLoss.includedPoints ? '部分已扣规划分' : '参考，不扣规划分'}）</span><strong className="negative">{num(value.referenceLoss.points)}</strong></div>
      {value.referenceLoss.includedPoints != null && value.referenceLoss.includedPoints !== 0 && !value.referenceLoss.includedInPlanningScore &&
        <div className="score-part"><span>其中已扣规划分</span><strong>{num(value.referenceLoss.includedPoints)}</strong></div>}
      {value.referenceLoss.expectedCashLost != null && <div className="score-part"><span>上贡源石锭 −{num(value.referenceLoss.expectedCashLost)} × {num(value.referenceLoss.cashUnitPoints ?? 8)}</span><strong>{num(value.referenceLoss.points)} 分</strong></div>}
      {value.referenceLoss.expectedNaturalCountLost != null && <div className="score-part"><span>随机 {num(value.referenceLoss.expectedNaturalCountLost)} 件自然物 × 平均 {num(value.referenceLoss.componentUnitPoints)} 效用分</span><strong>{num(value.referenceLoss.points)} 分</strong></div>}
      {value.referenceLoss.expectedAppraisalLost != null && <div className="score-part"><span>预计损失估价</span><strong>{num(value.referenceLoss.expectedAppraisalLost)}</strong></div>}
      {value.referenceLoss.cashEquivalentPoints != null && <div className="score-part"><span>估价折算 −{num(value.referenceLoss.expectedAppraisalLost)} × 8</span><strong>{num(value.referenceLoss.cashEquivalentPoints)} 分</strong></div>}
      {value.referenceLoss.expectedNaturalCountLost != null && <small>按当前零件箱随机上贡2件的期望；效用分与估价折算分是两种参考，不相加</small>}
    </div>}
    {value.classification && <div className="classification-table"><h4>{splitTypes ? '收益分支概率' : '分类估分权重'}</h4>
      {(splitTypes ? types : Object.entries(value.classification.probabilities || {}).map(([id, probability]) =>
        ({ key: id, name: catalog.labels.nodeTypes[id] || id, probability }))).map(row => <div className="probability-row" key={row.key}>
        <span>{row.name}</span><span>{pct(row.probability)}</span></div>)}
      {!!conditionalMarks.length && <details><summary>该位置的结局标记概率</summary>
        {conditionalMarks.map(row => <div className="probability-row" key={row.goalId}>
          <span>{row.name}</span><span>{pct(row.probability)}</span></div>)}
        <small>先按普通规则预测类别，再在该类别内分配结局标记；不提高类别概率。</small>
      </details>}
    </div>}
    {types.map(row => <details key={row.key}>
      <summary><span>{row.name}</span><span>{pct(row.probability)} × {num(row.score.points)} = {num(row.probability * row.score.points)}</span>
        <RewardPoolButtons pools={rewardPoolsFor(catalog, { categoryId: row.categoryId, eventId: row.score.eventId, goalId: row.score.goalId, stage: row.score.stage }, areaKey)} label={row.name} onOpen={onOpenPool} /></summary>
      <ScoreDetails value={row.score} catalog={catalog} compact hidePoolButtons rewardScope={{ categoryId: row.categoryId }} areaKey={areaKey} onOpenPool={onOpenPool} />
    </details>)}
    {value.events?.map(row => <details key={row.eventId}>
      <summary><span>{eventNames[row.eventId] || row.eventId}</span><span>{pct(row.probability)} × {num(row.score.points)}</span>
        <RewardPoolButtons pools={rewardPoolsFor(catalog, { eventId: row.eventId }, areaKey)} label={eventNames[row.eventId] || row.eventId} onOpen={onOpenPool} /></summary>
      <ScoreDetails value={row.score} catalog={catalog} compact hidePoolButtons rewardScope={{ eventId: row.eventId }} areaKey={areaKey} onOpenPool={onOpenPool} />
    </details>)}
    {value.branches?.filter(row => row.probability > 0).map(row => <details key={row.name}>
      <summary><span>{row.name}</span><span>{pct(row.probability)} × {num(row.score.points)}</span></summary>
      <ScoreDetails value={row.score} catalog={catalog} compact rewardScope={scope} areaKey={areaKey} onOpenPool={onOpenPool} />
    </details>)}
    {value.merchant && <div className="merchant-summary">
      <div className="score-part"><span>入店经济</span><b>{num(value.merchant.economyInput)}</b></div>
      <div className="score-part"><span>剩余货柜</span><b>{pct(value.merchant.remainingShelfFraction)}</b></div>
      <div className="score-part"><span>预计取钱</span><b>{num(value.merchant.withdrawal?.cash)}</b></div>
    </div>}
    {!!value.missingTerms?.length && <details className="score-warnings"><summary>{value.missingTerms.length} 项未量化内容</summary>
      <ul>{value.missingTerms.map(text => <li key={text}>{scoreNote(text)}</li>)}</ul></details>}
    {!!value.modelLimitations?.length && <details className="score-warnings"><summary>过程估算注意</summary>
      <ul>{value.modelLimitations.map(text => <li key={text}>{scoreNote(text)}</li>)}</ul></details>}
  </div>;
}
