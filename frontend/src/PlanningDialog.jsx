import React, { useState } from 'react';
import { Route } from 'lucide-react';
import { EntryImage, Modal, NumberField } from './common';
import { searchOptionsError } from './planningOptions';

const BRANCHES = {
  ending2_sandbox: ['取得沙盘α，节点收益0；作为本层软优先目标', '获取高稀有度加工品，按普通收益规划'],
  ending3_beacon: ['取得怦然信标，归队不进阶；作为软优先目标', '普通派遣，计算归队进阶收益'],
  ending3_trade: ['上贡2件自然物，损失仅作参考；作为软优先目标', '按普通失与得交换收益规划'],
  ending3_tribute: ['上贡全部现金，损失仅作参考；作为软优先目标', '按上贡现金的负收益规划，不设置优先目标'],
  ending3_autopsy: ['保留战斗收益，优先获取湮没“光明”', '仅按无效验尸的战斗收益规划'],
};

export default function PlanningDialog({ check, items = [], entries = {}, mode = 'global', topN, budget, onTopNChange, onBudgetChange, busy, onClose, onPlan }) {
  const [selected, setSelected] = useState(check.selectedGoalIds);
  const available = items.filter(item => item.remainingUses > 0);
  const [using, setUsing] = useState(available.filter(item => item.componentId !== 'component_019').map(item => item.instanceId));
  const optionsError = searchOptionsError(topN, budget);
  return <Modal title={check.valid ? '本层前置目标' : '结局进度与地图冲突'} onClose={onClose} footer={check.valid &&
    <button className="primary" disabled={busy || !!optionsError} onClick={() => onPlan(selected, using)}><Route size={16} />开始规划</button>}>
    {check.valid && <b className="planning-mode-label">{mode === 'advice' ? '一步路径建议' : '全局路径规划'}</b>}
    {!check.valid && <div className="form-error" role="alert">{check.conflicts.map((row, index) => <p key={index}>{row.message}</p>)}</div>}
    {check.valid && <div className="planning-target-list">{check.targets.map(row => <div key={row.id}>
      <label className="goal-check"><input type="checkbox" checked={selected.includes(row.id)} onChange={event =>
        setSelected(event.target.checked ? [...selected, row.id] : selected.filter(key => key !== row.id))} /><b>{row.name}</b></label>
      <p>{BRANCHES[row.id]?.[selected.includes(row.id) ? 0 : 1]}</p>
      <small>{row.knownNodeIds.length ? `已定位：${row.knownNodeIds.map(key => `(${key})`).join('、')}` :
        `尚未定位 · ${Object.keys(row.positionProbabilities).length || row.candidateNodeIds?.length || 0} 个候选位置`}</small>
    </div>)}</div>}
    {check.valid && <section className="planning-items"><h3>参与本层规划的加工品（不包括小八戒）</h3>
      {[true, false].map(enabled => <div className="planning-item-row" key={String(enabled)}><b>{enabled ? '本次使用' : '不使用'}</b><div>
        {available.filter(item => using.includes(item.instanceId) === enabled).map(item => <button key={item.instanceId}
          disabled={busy || item.componentId === 'component_019'} aria-label={`${enabled ? '不使用' : '使用'}${entries[item.componentId]?.name || item.componentId}`}
          title={item.componentId === 'component_019' ? (mode === 'advice' ? '一步建议另列随机落点分布' : '小八戒随机移动，不参与确定路线') : entries[item.componentId]?.name}
          onClick={() => setUsing(enabled ? using.filter(id => id !== item.instanceId) : [...using, item.instanceId])}>
          <EntryImage entry={entries[item.componentId]} /><span>{entries[item.componentId]?.name} ×{item.remainingUses}</span>
        </button>)}
        {!available.some(item => using.includes(item.instanceId) === enabled) && <span className="quiet">无</span>}
      </div></div>)}
    </section>}
    {check.valid && <section className="planning-search-options">
      <div className="form-grid">
        <NumberField label={mode === 'advice' ? '显示Top K建议' : '显示Top K路线'} aria-label={mode === 'advice' ? '显示Top K建议' : '显示Top K路线'} value={topN} min={1} max={50} onChange={onTopNChange} disabled={busy} />
        <NumberField label="路径搜索上限" aria-label="路径搜索上限" value={budget} min={1} max={500000} step={1000} onChange={onBudgetChange} disabled={busy} />
      </div>
      {optionsError && <p className="form-error" role="alert">{optionsError}</p>}
    </section>}
  </Modal>;
}
