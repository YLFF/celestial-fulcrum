import React from 'react';

const format = value => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 3 });

export default function TeamThresholdPanel({ status, instance, onChange, busy }) {
  if (!status) return null;
  const multipliers = status.multipliers;
  return <div className="team-threshold">
    <div className="threshold-result"><span title="常驻六星已进阶1、未进阶0.7；五星0.5、0.3；其他0.2；助力干员不计入">干员折算人数</span><b>{format(status.weightedOperators)}</b></div>
    <table><thead><tr><th>全体已生效倍率</th><th>局外</th><th>局内</th></tr></thead><tbody>{[
      ['max_hp', '生命'], ['attack', '攻击'],
    ].map(([metric, label]) => <tr key={metric}><th>{label}</th><td>×{format(multipliers[`outside_battle_${metric}`])}</td><td>×{format(multipliers[`inside_battle_${metric}`])}</td></tr>)}</tbody></table>
    <div className="threshold-result"><span>本层战力值 / 目标</span><b className={status.automaticMet ? 'green-text' : 'negative'}>{format(status.power)} / {format(status.required.power)}</b></div>
    <div className="threshold-result"><span>自动判定</span><b className={status.automaticMet ? 'green-text' : 'negative'}>{status.automaticMet ? '达标' : '未达标'}</b></div>
    <div className="segmented threshold-override" role="group" aria-label="战力判定">{[
      ['auto', '自动'], ['enough', '强制够'], ['insufficient', '强制不够'],
    ].map(([value, label]) => <button key={value} className={status.override === value ? 'active' : ''} aria-pressed={status.override === value} disabled={busy || !instance}
      onClick={() => onChange(value)}>{label}</button>)}</div>
    <div className="threshold-result"><span>评分采用</span><b className={status.met ? 'green-text' : 'negative'}>{status.met ? '战力够' : '战力不够'}</b></div>
    {!!status.unknownRarityOperators.length && <small className="quiet">星级待确认：{status.unknownRarityOperators.join('、')}</small>}
    {!!status.pendingAttributeTerms && <small className="quiet">有未确认加成，当前倍率仅含已确认部分</small>}
  </div>;
}
