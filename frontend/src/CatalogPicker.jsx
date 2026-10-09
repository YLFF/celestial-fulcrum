import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, Plus, Search } from 'lucide-react';
import { EntryImage } from './common';
import { PROFESSIONS } from './model';
import { fuzzyMatch } from './picker';

export default function CatalogPicker({ rows = [], onAdd, operators = false, components = false, selectedIds = [], autoFocus = false }) {
  const [query, setQuery] = useState(''), [profession, setProfession] = useState('');
  const [limit, setLimit] = useState(100);
  useEffect(() => { setLimit(100); }, [query, profession]);
  const matches = useMemo(() => rows.filter(row => (!profession || row.profession === profession) && fuzzyMatch(row, query)), [rows, query, profession]);
  return <aside className="catalog-picker">
    <label className="picker-search"><Search size={15} /><input aria-label="搜索名称" placeholder={operators ? '中文名 / 代号 / 英文名' : '搜索名称'} autoFocus={autoFocus} value={query} onChange={e => setQuery(e.target.value)} /></label>
    {operators && <select aria-label="筛选职业" value={profession} onChange={e => setProfession(e.target.value)}><option value="">全部职业</option>{PROFESSIONS.map(p => <option key={p}>{p}</option>)}</select>}
    <small className="quiet">{matches.length} 项</small>
    {components ? <div className="component-picker-results">{['加工品', '自然物', '概念体'].map(kind => <section key={kind}>
      <h3>{kind}</h3><div className="component-picker-grid">{matches.filter(row => row.kind === kind).map(row => <button key={row.id} title={row.name}
        disabled={selectedIds.includes(row.id)} onClick={() => onAdd(row)} aria-label={`选择 ${row.name}`}>
        <EntryImage entry={row} className="inventory-image" /><span>{row.name}</span>
      </button>)}</div></section>)}</div> : <div className="picker-results">{matches.slice(0, limit).map(row => <button key={row.id} disabled={selectedIds.includes(row.id)} onClick={() => onAdd(row)} aria-label={`选择 ${row.name}`}>
      {!operators && <EntryImage entry={row} className="inventory-image" />}<span><b>{row.name}</b><small>{operators ? `${row.rarity}★ · ${row.profession || '待确认'}${row.code ? ` · ${row.code}` : ''}` : row.kind || row.id}</small></span><Plus size={14} />
    </button>)}{matches.length > limit && <button aria-label="显示更多条目" title="显示更多条目" onClick={() => setLimit(limit + 100)}><ChevronDown size={16} /></button>}</div>}
  </aside>;
}
