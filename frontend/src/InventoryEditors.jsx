import React, { useState } from 'react';
import { Trash2, UserRoundPlus, Swords, PackagePlus, Footprints, TreeDeciduous } from 'lucide-react';
import { EntryImage, IconButton, Modal, NumberField, SaveButton } from './common';
import { componentCommands, operatorProgressLabel, operatorProgressOptions, PROFESSIONS, uid } from './model';
import CatalogPicker from './CatalogPicker';
import { SOURCE_CHOICES, sourceChoice } from './picker';
import { acquireDraft, appraisalDraft } from './componentAppraisal';

export function RelicEditor({ state, catalog, entries, onSave, onClose, busy, adding = false }) {
  const [items, setItems] = useState(structuredClone(state.relics));
  const change = (index, changes) => setItems(items.map((row, i) => i === index ? { ...row, ...changes } : row));
  return <Modal title={`藏品 · ${items.reduce((a, b) => a + (b.count || 1), 0)} 件`} onClose={onClose} wide footer={<SaveButton busy={busy} onClick={() => onSave([{ type: 'relics', items }])} />}>
    <div className="picker-layout"><CatalogPicker autoFocus={adding} rows={catalog.relic} selectedIds={items.filter(row => row.id !== 'relic_014' && !/^relic_(03[2-7]|24[0-3])$/.test(row.id)).map(row => row.id)} onAdd={({ id }) => setItems(items.some(row => row.id === id) ? items.map(row => row.id === id ? { ...row, count: (row.count || 1) + 1 } : row) : [...items, { id, count: 1, state: null }])} />
    <div className="editor-list">{items.map((row, index) => <div className="relic-edit-row" key={row.id}>
      <EntryImage entry={entries[row.id]} className="inventory-image" /><div className="item-title"><b>{entries[row.id]?.name || row.id}</b><small>{row.id}</small></div>
      <label className="field"><span>层数 / 生效</span><input aria-label={`${entries[row.id]?.name} 层数 / 生效`} placeholder="层数或生效状态" value={row.state ?? ''} onChange={e => change(index, { state: e.target.value === '' ? null : /^\d+$/.test(e.target.value) ? Number(e.target.value) : e.target.value })} /></label>
      <IconButton icon={Trash2} label={`移除 ${entries[row.id]?.name}`} onClick={() => setItems(items.filter((_, i) => i !== index))} />
    </div>)}</div></div>
  </Modal>;
}

export function ComponentEditor({ state, catalog, entries, onSave, onClose, busy, adding = false }) {
  const [box, setBox] = useState(structuredClone(state.componentBox));
  const [error, setError] = useState(''), [confirmTrees, setConfirmTrees] = useState(false);
  const trees = box.items.filter(row => row.componentId === 'component_006').length;
  const change = (index, changes) => setBox({ ...box, items: box.items.map((row, i) => i === index ? { ...row, ...changes } : row) });
  return <Modal title={`零件箱 · ${box.items.length}/${box.capacity}`} onClose={onClose} wide
    footer={<SaveButton busy={busy || confirmTrees} onClick={() => onSave(componentCommands(state.componentBox, box))} />}>
    <div className="box-header"><NumberField label="容量上限" value={box.capacity} onChange={value => setBox({ ...box, capacity: value })} />
      <div className="appraisal-actions">{[
        ['recruit', '招募干员+1', UserRoundPlus, '每件回声玉米估价+3；新增干员不会自动结算'],
        ['battle', '战斗胜利+1', Swords, '按完美胜利：血蕈+2、霜晶树+4；非完美战斗请使用“我树碎了？！”'],
        ['acquire', '获得零件+1', PackagePlus, '每件多生苔藓+1、板藤+4；新增零件已自动结算'],
        ['soilMove', '沃土移动+1', Footprints, '途经希望的沃土增益区域：所有自然物+2'],
      ].map(([event, label, Icon, title]) => <button key={event} title={title} disabled={busy} onClick={() => setBox(appraisalDraft(box, event, catalog))}><Icon size={14} />{label}</button>)}
      <button className="tree-break-button" disabled={busy || !trees} onClick={() => setConfirmTrees(true)}><TreeDeciduous size={14} />我树碎了？！</button></div>
      <span>总估价 {box.items.reduce((sum, row) => sum + (row.estimatedValue || 0), 0)}</span></div>
    {error && <div className="form-error" role="alert">{error}</div>}
    {confirmTrees && <div className="confirmation-overlay"><section className="tree-confirmation" role="alertdialog" aria-modal="true" aria-label="确认移除霜晶树"><h3>移除全部霜晶树？</h3><p>将从零件箱移除 {trees} 件霜晶树。</p><div><button autoFocus onClick={() => setConfirmTrees(false)}>取消</button><button className="primary" onClick={() => { setBox({ ...box, items: box.items.filter(row => row.componentId !== 'component_006') }); setConfirmTrees(false); }}>确认移除</button></div></section></div>}
    <div className="picker-layout component-layout"><CatalogPicker autoFocus={adding} rows={catalog.component} onAdd={entry => {
      try { setBox(acquireDraft(box, entry, catalog)); setError(''); } catch (e) { setError(e.message); }
    }} />
    <div className="component-columns">{['加工品', '自然物', '概念体'].map(kind => <section key={kind}><h3>{kind}</h3>{box.items.map((row, index) => entries[row.componentId]?.kind === kind && <div className="component-edit-row" key={row.instanceId}>
      <EntryImage entry={entries[row.componentId]} className="inventory-image" /><div className="item-title"><b>{entries[row.componentId]?.name || row.componentId}</b><small>{row.instanceId}</small></div>
      <NumberField label="当前估价" value={row.estimatedValue} nullable onChange={value => change(index, { estimatedValue: value })} />
      {row.remainingUses != null ? <><NumberField label="剩余次数" value={row.remainingUses} max={catalog.componentInitialUses[row.componentId]} onChange={value => change(index, { remainingUses: value })} />
        <label className="checkbox-field"><input type="checkbox" checked={row.routeCandidate} onChange={e => change(index, { routeCandidate: e.target.checked })} />参与规划</label></> : <span className="quiet">{kind}</span>}
      <IconButton icon={Trash2} label={`移除 ${entries[row.componentId]?.name}`} onClick={() => setBox({ ...box, items: box.items.filter((_, i) => i !== index) })} />
    </div>)}</section>)}</div></div>
  </Modal>;
}

export function OperatorEditor({ state, catalog, onSave, onClose, busy, adding = false }) {
  const [items, setItems] = useState(() => structuredClone(state.operators).map(row => {
    const entry = catalog.operators.find(entry => entry.name === row.name);
    return entry ? { ...row, operatorId: entry.id, profession: entry.professionEditable ? row.profession : entry.profession, rarity: entry.rarity } : row;
  }));
  const [squad, setSquad] = useState(state.squad || []);
  const [settle, setSettle] = useState(false);
  const change = (id, changes) => setItems(items.map(row => row.instanceId === id ? { ...row, ...changes } : row));
  async function save() {
    const old = new Map(state.operators.map(row => [row.instanceId, row]));
    const live = new Set(items.map(row => row.instanceId)), commands = [];
    for (const row of state.operators) if (!live.has(row.instanceId)) commands.push({ type: 'operatorRemove', instanceId: row.instanceId });
    for (const row of items) {
      const source = row.source || 'normal', support = source === 'assistance' || source === 'emergency';
      const changes = { name: row.name, profession: row.profession || null, rarity: row.rarity ?? null, elite: row.elite,
        source, remainingBattles: support ? (row.remainingBattles || 1) : null, initialRecruitment: !!row.initialRecruitment };
      if (!old.has(row.instanceId)) commands.push({ type: 'operatorAdd', name: row.name, source, elite: row.elite, profession: row.profession || null,
        rarity: row.rarity ?? null, instanceId: row.instanceId, recordOnly: !settle, ...(settle && row.hopeCost != null ? { hopeCost: row.hopeCost } : {}) });
      else {
        if (settle && old.get(row.instanceId).elite === 1 && row.elite === 2 && !support) commands.push({ type: 'operatorPromote', instanceId: row.instanceId,
          ...(row.hopeCost != null ? { hopeCost: row.hopeCost } : {}) });
        commands.push({ type: 'operatorUpdate', instanceId: row.instanceId, changes });
      }
    }
    commands.push({ type: 'squad', operatorIds: squad.filter(id => live.has(id)) });
    await onSave(commands);
  }
  return <Modal title={`干员与编队 · ${items.length} 人`} onClose={onClose} wide footer={<SaveButton busy={busy} onClick={save} />}>
    <div className="editor-toolbar">
      <label className="checkbox-field"><input type="checkbox" checked={settle} onChange={e => setSettle(e.target.checked)} />结算新招募 / 进阶</label>
      <span>编队 {squad.length}/{state.resources.carrySlots}</span></div>
    <div className="picker-layout"><CatalogPicker rows={catalog.operators} operators autoFocus={adding} selectedIds={items.filter(row => !row.remainingBattles && !catalog.operators.find(entry => entry.name === row.name)?.repeatable).map(row => row.operatorId || catalog.operators.find(entry => entry.name === row.name)?.id)} onAdd={entry => setItems([...(entry.repeatable ? items : items.filter(row => row.name !== entry.name || !row.remainingBattles)), { instanceId: uid('op'), operatorId: entry.id, name: entry.name, source: 'normal', profession: entry.profession, elite: entry.rarity >= 3 ? 1 : 0, rarity: entry.rarity, remainingBattles: null }])} />
    <div className="operator-editor">{items.map(row => <section className="operator-edit-row" key={row.instanceId}>
      <label className="checkbox-field"><input type="checkbox" checked={squad.includes(row.instanceId)} onChange={e => setSquad(e.target.checked ? [...squad, row.instanceId] : squad.filter(id => id !== row.instanceId))} />编队</label>
      <label className="field"><span>干员名称</span><input value={row.name} onChange={e => {
        const entry = catalog.operators.find(entry => entry.name === e.target.value);
        change(row.instanceId, { name: e.target.value, operatorId: entry?.id, ...(entry ? { profession: entry.professionEditable ? row.profession : entry.profession, rarity: entry.rarity } : {}) });
      }} /></label>
      <label className="field"><span>职业</span><select aria-label="职业" disabled={catalog.operators.some(entry => entry.name === row.name && !entry.professionEditable)} value={row.profession || ''} onChange={e => change(row.instanceId, { profession: e.target.value || null })}>
        <option value="">待确认</option>{PROFESSIONS.map(text => <option key={text}>{text}</option>)}</select></label>
      <NumberField label="星级" readOnly={catalog.operators.some(entry => entry.name === row.name)} value={row.rarity} min={1} max={6} nullable onChange={value => change(row.instanceId, { rarity: value })} />
      <label className="field"><span>进阶状态</span><select aria-label="进阶状态" value={row.elite ?? ''} onChange={e => change(row.instanceId, { elite: e.target.value === '' ? null : Number(e.target.value) })}>
        <option value="">待确认</option>{operatorProgressOptions(row.rarity, row.elite).map(value => <option key={value} value={value}>{operatorProgressLabel(value)}</option>)}</select></label>
      <label className="field"><span>来源</span><select aria-label="来源" value={sourceChoice(row.source)} onChange={e => change(row.instanceId, { source: e.target.value })}>
        {Object.entries(SOURCE_CHOICES).map(([id, text]) => <option value={id} key={id}>{text}</option>)}</select></label>
      {settle && <NumberField label="希望费用" value={row.hopeCost} nullable onChange={value => change(row.instanceId, { hopeCost: value })} />}
      <IconButton icon={Trash2} label={`移除干员 ${row.name}`} onClick={() => { setItems(items.filter(x => x.instanceId !== row.instanceId)); setSquad(squad.filter(id => id !== row.instanceId)); }} />
    </section>)}</div></div>
  </Modal>;
}
