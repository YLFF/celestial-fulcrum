import React, { useState } from 'react';
import { Trash2, ChevronsUp, UserRoundPlus, Swords, PackagePlus, Eye, Footprints, TreeDeciduous, WandSparkles, ChartNoAxesCombined } from 'lucide-react';
import { EntryImage, IconButton, Modal, NumberField, SaveButton } from './common';
import { componentAppraisalTotal, componentCommands, num, orderedOperatorRoster, operatorProgressLabel, operatorProgressOptions, PROFESSIONS, uid } from './model';
import CatalogPicker from './CatalogPicker';
import { SOURCE_CHOICES, sourceChoice } from './picker';
import { acquireDraft, appraisalDraft } from './componentAppraisal';
import { boundRecipients, canEnchant, enchantCommands, manualTrainingPromotion, newestRelics, recipientIds, relicActive, relicManagement, relicStatus, toggleRecipient } from './relicPresentation';
import CombatBonusDialog from './CombatBonusDialog';

export function RelicEditor({ state, catalog, entries, onSave, onClose, busy, adding = false }) {
  const [items, setItems] = useState(structuredClone(state.relics));
  const [assignments, setAssignments] = useState({});
  function assign(id, operatorId, slot = 0) { setAssignments(current => {
    const next = { ...current }, ids = [...(next[id] || [])]; ids[slot] = operatorId;
    next[id] = ids; return next;
  }); }
  const change = (index, changes) => setItems(items.map((row, i) => i === index ? { ...row, ...changes } : row));
  return <Modal title={`藏品 · ${items.reduce((a, b) => a + (b.count || 1), 0)} 件`} onClose={onClose} wide footer={<SaveButton busy={busy} onClick={() => onSave([{ type: 'relics', items }, ...enchantCommands(assignments)])} />}>
    <div className="picker-layout"><CatalogPicker autoFocus={adding} rows={catalog.relic} selectedIds={items.filter(row => row.id !== 'relic_014' && !/^relic_(03[2-7]|24[0-3])$/.test(row.id)).map(row => row.id)} onAdd={({ id }) => setItems(items.some(row => row.id === id) ? items.map(row => row.id === id ? { ...row, count: (row.count || 1) + 1 } : row) : [...items, { id, count: 1, state: null }])} />
    <div className="editor-list">{newestRelics(items).map(({ row, index }) => {
      const entry = entries[row.id], management = relicManagement(entry), status = relicStatus(row, entry, state);
      return <div className="relic-edit-row" key={row.id}>
      <EntryImage entry={entries[row.id]} className="inventory-image" /><div className="item-title"><b>{entries[row.id]?.name || row.id}</b><small>{row.id}</small></div>
      {management.bindOperator ? <div className="enchantment-controls">
        {relicActive(row) ? <span className="enchantment-applied">已生效 · {boundRecipients(row).map(item => item.operatorName).join('、') || '受益干员未记录'}</span>
          : Array.from({ length: management.maxRecipients || 1 }, (_, slot) => <label className="field" key={slot}>
            <span>{recipientIds(assignments[row.id]).some(Boolean) ? '待保存附魔' : `附魔${management.profession ? ` · ${management.profession}` : ''}`}{management.promotionEffect && ' · 自动进阶'}</span>
            <select aria-label={`${entry.name} 受益干员${slot ? ` ${slot + 1}` : ''}`} value={assignments[row.id]?.[slot] || ''} onChange={e => assign(row.id, e.target.value, slot)}>
            <option value="">未生效 / 选择干员</option>{state.operators.filter(operator => canEnchant(row, operator, entries)).map(operator => <option key={operator.instanceId} value={operator.instanceId}
              disabled={(assignments[row.id] || []).some((id, index) => index !== slot && id === operator.instanceId)}>{operator.name}</option>)}</select></label>)}
      </div> : status.readOnly ? <span className="relic-runtime-status">{status.label}</span>
        : status.kind === 'stacking' ? <NumberField label="层数" aria-label={`${entry.name} 层数`} value={row.state} nullable
          max={management.maximum} min={management.minimum || 0} onChange={value => change(index, { state: value })} />
        : <label className="field"><span>生效状态</span><select aria-label={`${entry.name} 生效状态`} value={relicActive(row) ? 'active' : 'inactive'}
          onChange={e => change(index, { state: e.target.value })}><option value="inactive">未生效</option><option value="active">已生效</option></select></label>}
      <IconButton icon={Trash2} label={`移除 ${entries[row.id]?.name}`} onClick={() => { setItems(items.filter((_, i) => i !== index)); setAssignments(current => { const next = { ...current }; delete next[row.id]; return next; }); }} />
    </div>; })}</div></div>
  </Modal>;
}

export function ComponentEditor({ state, catalog, entries, onSave, onClose, busy, adding = false }) {
  const [box, setBox] = useState(structuredClone(state.componentBox));
  const [error, setError] = useState(''), [confirmTrees, setConfirmTrees] = useState(false);
  const trees = box.items.filter(row => row.componentId === 'component_006').length;
  const unknownAppraisals = box.items.filter(row => row.estimatedValue == null).length;
  const change = (index, changes) => setBox({ ...box, items: box.items.map((row, i) => i === index ? { ...row, ...changes } : row) });
  return <Modal title={`零件箱 · ${box.items.length}/${box.capacity}`} onClose={onClose} wide
    footer={<SaveButton busy={busy || confirmTrees} onClick={() => onSave(componentCommands(state.componentBox, box))} />}>
    <div className="box-header"><div className="box-summary"><NumberField label="容量上限" value={box.capacity} onChange={value => setBox({ ...box, capacity: value })} />
      <div className="box-appraisal" role="status" aria-label="零件箱总估价"><span>总估价</span><b>{num(componentAppraisalTotal(box.items))}</b>
        {unknownAppraisals > 0 && <small>{unknownAppraisals} 件未估价</small>}</div></div>
      <div className="appraisal-actions">{[
        ['recruit', '招募干员+1', UserRoundPlus, '每件回声玉米估价+3；新增干员不会自动结算'],
        ['battle', '战斗胜利+1', Swords, '按完美胜利：血蕈+2、霜晶树+4；非完美战斗请使用“我树碎了？！”'],
        ['acquire', '获得零件+1', PackagePlus, '每件多生苔藓+1、板藤+4；新增零件已自动结算'],
        ['reveal', '揭示节点+1', Eye, '每件雾滚草估价+1'],
        ['soilMove', '沃土移动+1', Footprints, '途经希望的沃土增益区域：所有自然物+2'],
      ].map(([event, label, Icon, title]) => <button key={event} title={title} disabled={busy} onClick={() => setBox(appraisalDraft(box, event, catalog))}><Icon size={14} />{label}</button>)}
      <button className="tree-break-button" disabled={busy || !trees} onClick={() => setConfirmTrees(true)}><TreeDeciduous size={14} />我树碎了？！</button></div>
    </div>
    {error && <div className="form-error" role="alert">{error}</div>}
    {confirmTrees && <div className="confirmation-overlay"><section className="tree-confirmation" role="alertdialog" aria-modal="true" aria-label="确认移除霜晶树"><h3>移除全部霜晶树？</h3><p>将从零件箱移除 {trees} 件霜晶树。</p><div><button autoFocus onClick={() => setConfirmTrees(false)}>取消</button><button className="primary" onClick={() => { setBox({ ...box, items: box.items.filter(row => row.componentId !== 'component_006') }); setConfirmTrees(false); }}>确认移除</button></div></section></div>}
    <div className="picker-layout component-layout"><CatalogPicker components autoFocus={adding} rows={catalog.component} onAdd={entry => {
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

export function OperatorEditor({ state, catalog, entries, onSave, onClose, busy, adding = false, loaded, areaKey }) {
  const [items, setItems] = useState(() => orderedOperatorRoster(structuredClone(state.operators), state.squad).map(row => {
    const entry = catalog.operators.find(entry => entry.name === row.name);
    return { ...row, ...(entry ? { operatorId: entry.id, profession: entry.professionEditable ? row.profession : entry.profession, rarity: entry.rarityEditable ? row.rarity : entry.rarity } : {}),
      elite: row.elite ?? ((entry?.rarity ?? row.rarity) >= 3 ? 1 : 0) };
  }));
  const [squad, setSquad] = useState(state.squad || []);
  const [settle, setSettle] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [bonusOperator, setBonusOperator] = useState(null);
  const [enchantOperator, setEnchantOperator] = useState(null), [assignments, setAssignments] = useState({});
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
        const trainingPromotion = manualTrainingPromotion(old.get(row.instanceId), row, state.relics, assignments, entries);
        if ((settle || trainingPromotion) && old.get(row.instanceId).elite === 1 && row.elite === 2 && !support) commands.push({ type: 'operatorPromote', instanceId: row.instanceId,
          ...(trainingPromotion ? { hopeCost: 0 } : row.hopeCost != null ? { hopeCost: row.hopeCost } : {}) });
        commands.push({ type: 'operatorUpdate', instanceId: row.instanceId, changes });
      }
    }
    commands.push({ type: 'squad', operatorIds: squad.filter(id => live.has(id)) });
    commands.push(...enchantCommands(Object.fromEntries(Object.entries(assignments).map(([id, value]) => [id, recipientIds(value).filter(recipient => live.has(recipient))]))));
    await onSave(commands);
  }
  if (bonusOperator) return <CombatBonusDialog loaded={loaded} areaKey={areaKey} entries={entries}
    operatorInstanceId={bonusOperator} onClose={() => setBonusOperator(null)} />;
  return <Modal title={`干员与编队 · ${items.length} 人`} onClose={onClose} wide footer={<SaveButton busy={busy || !!pendingDelete} onClick={save} />}>
    {pendingDelete && <div className="confirmation-overlay"><section className="tree-confirmation" role="alertdialog" aria-modal="true" aria-label="确认移除干员">
      <h3>移除 {pendingDelete.name}？</h3><p>该干员也将从当前编队移除，保存后生效。</p><div><button autoFocus onClick={() => setPendingDelete(null)}>取消</button>
      <button className="primary" onClick={() => { setItems(items.filter(row => row.instanceId !== pendingDelete.instanceId)); setSquad(squad.filter(id => id !== pendingDelete.instanceId)); setPendingDelete(null); }}>确认移除</button></div>
    </section></div>}
    <div className="editor-toolbar">
      <label className="checkbox-field"><input type="checkbox" checked={settle} onChange={e => setSettle(e.target.checked)} />结算新招募 / 进阶</label>
      <span>编队 {squad.length}/{state.resources.carrySlots}</span></div>
    <div className="picker-layout"><CatalogPicker rows={catalog.operators} operators autoFocus={adding} selectedIds={items.filter(row => !row.remainingBattles && !catalog.operators.find(entry => entry.name === row.name)?.repeatable).map(row => row.operatorId || catalog.operators.find(entry => entry.name === row.name)?.id)} onAdd={entry => setItems([...(entry.repeatable ? items : items.filter(row => row.name !== entry.name || !row.remainingBattles)), { instanceId: uid('op'), operatorId: entry.id, name: entry.name, source: 'normal', profession: entry.profession, elite: entry.rarity >= 3 ? 1 : 0, rarity: entry.rarity, remainingBattles: null }])} />
    <div className="operator-editor">{items.map(row => <section className="operator-edit-row" key={row.instanceId}>
      <label className="checkbox-field"><input type="checkbox" checked={squad.includes(row.instanceId)} onChange={e => setSquad(e.target.checked ? [...squad, row.instanceId] : squad.filter(id => id !== row.instanceId))} />编队</label>
      <label className="field"><span>干员名称</span><input value={row.name} onChange={e => {
        const entry = catalog.operators.find(entry => entry.name === e.target.value);
        change(row.instanceId, { name: e.target.value, operatorId: entry?.id, ...(entry ? { profession: entry.professionEditable ? row.profession : entry.profession, rarity: entry.rarityEditable ? row.rarity : entry.rarity } : {}) });
      }} /></label>
      <label className="field"><span>职业</span><select aria-label="职业" disabled={catalog.operators.some(entry => entry.name === row.name && !entry.professionEditable)} value={row.profession || ''} onChange={e => change(row.instanceId, { profession: e.target.value || null })}>
        <option value="" disabled>选择职业</option>{PROFESSIONS.map(text => <option key={text}>{text}</option>)}</select></label>
      <NumberField label="星级" readOnly={catalog.operators.some(entry => entry.name === row.name && !entry.rarityEditable)} value={row.rarity} min={1} max={6} nullable onChange={value => change(row.instanceId, { rarity: value })} />
      <label className="field"><span>进阶状态</span><select aria-label="进阶状态" value={row.elite} onChange={e => change(row.instanceId, { elite: Number(e.target.value) })}>
        {operatorProgressOptions(row.rarity, row.elite).map(value => <option key={value} value={value}>{operatorProgressLabel(value)}</option>)}</select></label>
      <label className="field"><span>来源</span><select aria-label="来源" value={sourceChoice(row.source)} onChange={e => change(row.instanceId, { source: e.target.value })}>
        {Object.entries(SOURCE_CHOICES).map(([id, text]) => <option value={id} key={id}>{text}</option>)}</select></label>
      {settle && <NumberField label="希望费用" value={row.hopeCost} nullable onChange={value => change(row.instanceId, { hopeCost: value })} />}
      <div className="operator-row-actions operator-bonus-actions"><IconButton icon={ChartNoAxesCombined} label={`查看 ${row.name} 加成（已保存状态）`}
        disabled={busy || !loaded || !state.operators.some(item => item.instanceId === row.instanceId)} onClick={() => setBonusOperator(row.instanceId)} />
        <IconButton icon={WandSparkles} label={`附魔 ${row.name}`} disabled={busy} onClick={() => setEnchantOperator(enchantOperator === row.instanceId ? null : row.instanceId)} />
        <IconButton icon={ChevronsUp} label={`进阶 ${row.name}`} disabled={busy || row.elite === 2 || !operatorProgressOptions(row.rarity, row.elite).includes(2)} onClick={() => change(row.instanceId, { elite: 2 })} />
        <IconButton icon={Trash2} label={`移除干员 ${row.name}`} disabled={busy} onClick={() => setPendingDelete(row)} /></div>
      {(enchantOperator === row.instanceId || Object.values(assignments).some(value => recipientIds(value).includes(row.instanceId)) || state.relics.some(relic => boundRecipients(relic).some(item => item.operatorInstanceId === row.instanceId))) &&
        <div className="operator-enchantments">{state.relics.filter(relic => boundRecipients(relic).some(item => item.operatorInstanceId === row.instanceId)).map(relic => <span key={relic.id}>{entries[relic.id]?.name} · 已生效</span>)}
          {!state.relics.some(relic => canEnchant(relic, row, entries)) && <span className="quiet">无可用的附魔藏品</span>}
          {state.relics.filter(relic => canEnchant(relic, row, entries) && (enchantOperator === row.instanceId || recipientIds(assignments[relic.id]).includes(row.instanceId))).map(relic => <label className="checkbox-field" key={relic.id}>
            <input type="checkbox" aria-label={`将${entries[relic.id]?.name}附魔至${row.name}`} checked={recipientIds(assignments[relic.id]).includes(row.instanceId)}
              disabled={!recipientIds(assignments[relic.id]).includes(row.instanceId) && recipientIds(assignments[relic.id]).length >= (relicManagement(entries[relic.id]).maxRecipients || 1)}
              onChange={e => setAssignments(current => toggleRecipient(current, relic.id, row.instanceId, e.target.checked))} />
            <EntryImage entry={entries[relic.id]} className="inventory-image" />{entries[relic.id]?.name}{recipientIds(assignments[relic.id]).includes(row.instanceId) ? ' · 待保存' : ''}{relicManagement(entries[relic.id]).promotionEffect && ' · 自动进阶'}</label>)}
        </div>}
    </section>)}</div></div>
  </Modal>;
}
