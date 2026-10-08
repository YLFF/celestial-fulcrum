import React from 'react';

export default function TeamThresholdPanel({ status, instance, onChange, busy }) {
  if (!status) return null;
  const counts = status.actualCounts;
  return <div className="team-threshold">
    <table><thead><tr><th>常驻阵容</th><th>本层门槛</th><th>实际</th></tr></thead><tbody>{[
      ['elite2SixStars', '已进阶六星'], ['sixStars', '六星总数'], ['totalOperators', '全队人数'],
    ].map(([key, label]) => <tr key={key}><th title={key === 'sixStars' ? '包含未进阶和已进阶六星；助力干员不计入常驻阵容' : undefined}>{label}</th><td>{status.required[key]}</td><td className={counts[key] < status.required[key] ? 'negative' : 'green-text'}>{counts[key]}</td></tr>)}</tbody></table>
    <div className="threshold-result"><span>自动判定</span><b className={status.automaticMet ? 'green-text' : 'negative'}>{status.automaticMet ? '达标' : '未达标'}</b></div>
    <div className="segmented threshold-override" role="group" aria-label="战力判定">{[
      ['auto', '自动'], ['enough', '强制够'], ['insufficient', '强制不够'],
    ].map(([value, label]) => <button key={value} className={status.override === value ? 'active' : ''} aria-pressed={status.override === value} disabled={busy || !instance}
      onClick={() => onChange(value)}>{label}</button>)}</div>
    <div className="threshold-result"><span>评分采用</span><b className={status.met ? 'green-text' : 'negative'}>{status.met ? '战力够' : '战力不够'}</b></div>
    {!!status.unknownRarityOperators.length && <small className="quiet">星级待确认：{status.unknownRarityOperators.join('、')}</small>}
  </div>;
}
