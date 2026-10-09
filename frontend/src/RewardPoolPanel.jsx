import React, { useState } from 'react';
import { X, Search, Gem, Package } from 'lucide-react';
import { EntryImage, IconButton } from './common';
import { visiblePoolItems } from './rewardPools';

export function RewardPoolButtons({ pools, label, onOpen }) {
  if (!onOpen) return null;
  return <div className="reward-pool-actions">{[['relic', '藏品池', Gem], ['component', '零件池', Package]].map(([kind, name, Icon]) => {
    const matching = pools.filter(pool => pool.kind === kind);
    return matching.length ? <button key={kind} onClick={event => { event.preventDefault(); event.stopPropagation(); onOpen({ pools: matching, label, kind }); }}><Icon size={13} />{name}</button> : null;
  })}</div>;
}

export default function RewardPoolPanel({ selection, entries, heldRelics, style, onClose }) {
  const [query, setQuery] = useState('');
  const name = selection.kind === 'relic' ? '藏品池' : '零件池';
  return <section className="node-popover reward-pool-popover" role="dialog" aria-label={`${selection.label} ${name}`} style={style}>
    <header><div><small>{selection.label}</small><h3>{name}</h3></div><IconButton icon={X} label={`关闭${name}`} onClick={onClose} /></header>
    <div className="pool-search"><Search size={14} /><input aria-label={`搜索${name}`} placeholder="搜索名称" value={query} onChange={e => setQuery(e.target.value)} /></div>
    <div className="node-popover-body">{selection.pools.map(pool => {
      const items = visiblePoolItems(pool, heldRelics, entries).filter(row => (entries[row.id]?.name || row.id).includes(query.trim()));
      return <section className="reward-pool-group" key={pool.id}><h4>{pool.label}</h4>
        {items.length ? <div className="reward-pool-grid">{items.map(row => <div className="reward-pool-item" key={row.id} title={entries[row.id]?.effect || entries[row.id]?.name}>
          <EntryImage entry={entries[row.id]} className="inventory-image" /><span>{entries[row.id]?.name || row.id}</span>
        </div>)}</div> : <p className="quiet">{query ? '没有匹配项' : selection.kind === 'relic' ? '本池藏品已全部持有' : '暂无可展示物品'}</p>}
      </section>;
    })}</div>
  </section>;
}
