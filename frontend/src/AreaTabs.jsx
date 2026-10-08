import React, { useEffect, useRef, useState } from 'react';
import { Plus, X } from 'lucide-react';
import { AREA_NAMES } from './model';
import { readPreference } from './preferences.js';

export default function AreaTabs({ runId, area, onChange, disabled }) {
  const [hidden, setHidden] = useState([]), [adding, setAdding] = useState(false);
  const tabs = useRef(null);
  const ids = Object.keys(AREA_NAMES), key = `fulcrum-hidden-areas:${runId || 'empty'}`;
  useEffect(() => {
    try { setHidden((JSON.parse(readPreference(key)) || []).filter(id => ids.includes(id) && id !== area)); }
    catch { setHidden([]); }
    setAdding(false);
  }, [key]);
  useEffect(() => {
    setHidden(old => old.includes(area) ? old.filter(id => id !== area) : old);
  }, [area]);
  useEffect(() => {
    const selected = tabs.current?.querySelector('[aria-selected="true"]');
    if (!selected) return;
    const row = selected.parentElement.getBoundingClientRect(), view = tabs.current.getBoundingClientRect();
    if (row.right > view.right) tabs.current.scrollLeft += row.right - view.right;
    else if (row.left < view.left) tabs.current.scrollLeft -= view.left - row.left;
  }, [area, hidden]);
  function save(value) { setHidden(value); try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Tabs remain usable without persistent storage. */ } }
  const visible = ids.filter(id => !hidden.includes(id));
  return <div className="area-tabs-wrap">
    <div className="area-tabs" ref={tabs} role="tablist" aria-label="地图槽位">{visible.map(id => <div className={`area-tab ${area === id ? 'active' : ''}`} key={id}>
      <button role="tab" tabIndex={area === id ? 0 : -1} aria-selected={area === id} aria-label={AREA_NAMES[id]} disabled={disabled} onClick={() => onChange(id)} onKeyDown={event => {
        const moves = { ArrowLeft: -1, ArrowRight: 1, Home: -visible.indexOf(id), End: visible.length - 1 - visible.indexOf(id) };
        if (moves[event.key] == null) return;
        event.preventDefault(); const index = (visible.indexOf(id) + moves[event.key] + visible.length) % visible.length;
        onChange(visible[index]); tabs.current.querySelectorAll('[role="tab"]')[index].focus();
      }}>{AREA_NAMES[id]}</button>
      <button className="area-close" title="关闭页签，不删除地图" aria-label={`关闭${AREA_NAMES[id]}页签`} disabled={disabled || visible.length === 1} onClick={() => {
        save([...hidden, id]); if (area === id) onChange(visible.find(other => other !== id));
      }}><X size={11} /></button>
    </div>)}</div>
    <button className="icon-button" title="恢复地图页签" aria-label="恢复地图页签" aria-expanded={adding} disabled={!hidden.length || disabled} onClick={() => setAdding(!adding)}><Plus size={15} /></button>
    {adding && <div className="area-add-menu">{ids.filter(id => hidden.includes(id)).map(id => <button key={id} onClick={() => {
      save(hidden.filter(other => other !== id)); onChange(id); setAdding(false);
    }}>{AREA_NAMES[id]}</button>)}</div>}
  </div>;
}
