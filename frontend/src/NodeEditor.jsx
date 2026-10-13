import React, { useEffect, useRef, useState } from 'react';
import { X, Crosshair, Check } from 'lucide-react';
import { IconButton, NumberField, SaveButton } from './common';
import { nodeCategory, pct } from './model';
import ScoreDetails from './ScoreDetails';
import { coverageStatus, setCoverage } from './dystopia';
import RewardPoolPanel, { RewardPoolButtons } from './RewardPoolPanel';
import { besidePopover, rewardPoolsFor } from './rewardPools';
import { residentActive } from './recognitionMerge';

export default function NodeEditor({ node, instance, catalog, value, anchor, onClose, onSave, busy, entries, heldRelics = [] }) {
  const [tab, setTab] = useState('score');
  const [pool, setPool] = useState(null), [panelHeight, setPanelHeight] = useState(540);
  const panelRef = useRef(null);
  useEffect(() => {
    const observer = new ResizeObserver(() => setPanelHeight(panelRef.current.getBoundingClientRect().height));
    observer.observe(panelRef.current);
    return () => observer.disconnect();
  }, []);
  const [viewport, setViewport] = useState({ width: window.innerWidth, height: window.innerHeight });
  useEffect(() => {
    const resize = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);
  const originalCategory = node.resolvedCategoryId || node.observedCategoryId || '';
  const [category, setCategory] = useState(originalCategory);
  const [completion, setCompletion] = useState(node.completion);
  const [confirmCompletion, setConfirmCompletion] = useState(false);
  const [visibility, setVisibility] = useState(node.visibility);
  const [marks, setMarks] = useState(node.confirmedMarkIds);
  const [encounter, setEncounter] = useState(node.encounterId || '');
  const [outcome, setOutcome] = useState(node.encounterOutcome || '');
  const [role, setRole] = useState(node.fateRole || 'unknown');
  const [position, setPosition] = useState(instance.playerPosition === node.id);
  const [coverage, setNodeCoverage] = useState(coverageStatus(instance.dystopia, node.id));
  const [isSource, setIsSource] = useState(instance.dystopia?.idealSourceNodeId === node.id);
  const [weight, setWeight] = useState(instance.strategy.nodeWeights[node.id] ?? 1);
  const [shelves, setShelves] = useState(node.merchantViewedShelves ?? (completion === 'completed' ? 1 : 0));
  const isUnknown = id => id === 'unknown_mystery' || id === 'unknown_ferocity';
  async function save() {
    if (!category) return;
    const commands = [], changed = category !== originalCategory;
    const reset = changed && (isUnknown(category) || category === 'node_type_020');
    if (reset) commands.push({ type: 'nodeReset', areaKey: instance.areaKey, nodeId: node.id, categoryId: category });
    const changes = { visibility, markIds: isUnknown(category) ? [] : marks };
    if (completion !== 'completed' || completion !== node.completion || !marks.includes('node_mark_001') || confirmCompletion)
      changes.completion = completion;
    if (!isUnknown(category)) changes.categoryId = category;
    if (category === 'node_type_006') {
      if (encounter) changes.encounterId = encounter;
      else if (node.encounterId) changes.clearEncounter = true;
      if (outcome !== (node.encounterOutcome || '')) changes.encounterOutcome = outcome;
    } else if (node.encounterId && !reset) changes.clearEncounter = true;
    if (category === 'node_type_012') changes.fateRole = role;
    if (category !== 'node_type_012' && node.fateRole !== 'unknown') changes.fateRole = 'unknown';
    if (completion === 'completed' && !isUnknown(category) &&
        (changed || !node.completedCategoryId && marks.includes('node_mark_001') !== node.confirmedMarkIds.includes('node_mark_001'))) {
      changes.completedCategoryId = marks.includes('node_mark_001') ? 'node_type_021' : category;
    }
    commands.push({ type: 'node', areaKey: instance.areaKey, nodeId: node.id, changes });
    if (instance.dystopia?.active) {
      const value = setCoverage(instance.dystopia, [node.id], isSource ? 'inside' : coverage);
      if (isSource) value.idealSourceNodeId = node.id;
      else if (instance.dystopia.idealSourceNodeId === node.id) value.idealSourceNodeId = null;
      commands.push({ type: 'dystopia', areaKey: instance.areaKey, value });
    }
    if (position) commands.push({ type: 'position', areaKey: instance.areaKey, value: node.id });
    commands.push({ type: 'strategy', areaKey: instance.areaKey, value: { nodeWeights: { ...instance.strategy.nodeWeights, [node.id]: weight } } });
    if (['node_type_004', 'node_type_013'].includes(category)) commands.push({ type: 'shopShelves', areaKey: instance.areaKey, nodeId: node.id, viewed: shelves });
    await onSave(commands);
  }
  const left = Math.max(10, Math.min(viewport.width - (pool && viewport.width >= 812 ? 792 : 396), anchor.right + 8));
  const top = Math.max(70, Math.min(viewport.height - 570, anchor.top - 36));
  return <><section ref={panelRef} role="dialog" aria-label={`节点编辑 ${node.id}`} className="node-popover" style={{ left, top,
    maxHeight: viewport.width > 800 ? Math.max(120, viewport.height - top - 12) : undefined }}>
    <header><div><small>节点 ({node.id})</small><h3>{catalog.labels.nodeTypes[originalCategory] || '待确认节点'}</h3></div>
      <IconButton icon={X} label="关闭节点详情" onClick={onClose} /></header>
    <div className="tabs"><button className={tab === 'node' ? 'active' : ''} onClick={() => { setTab('node'); setPool(null); }}>节点状态</button>
      <button className={tab === 'score' ? 'active' : ''} onClick={() => setTab('score')}>概率与得分</button></div>
    <div className="node-popover-body">{tab === 'score' ? <>
      {marks.includes('node_mark_007') && <div><small>藏果地</small><RewardPoolButtons
        pools={rewardPoolsFor(catalog, { markIds: ['node_mark_007'] }, instance.areaKey)} label="藏果地" onOpen={setPool} /></div>}
      <ScoreDetails value={value} catalog={catalog} rewardScope={{ categoryId: marks.includes('node_mark_001') ? 'node_type_021' : nodeCategory(node), eventId: node.encounterId }}
        areaKey={instance.areaKey} onOpenPool={setPool} />
      {!!instance.prediction?.unknownNodes?.[node.id]?.candidates?.length && <details className="classification-table"><summary>路标原始距离频次（非当前分类概率）</summary>
        {instance.prediction.unknownNodes[node.id].candidates.map(row => <div className="probability-row" key={row.categoryId}>
          <span>{catalog.labels.nodeTypes[row.categoryId]}</span><span>{pct(row.distanceFrequency)}</span></div>)}
      </details>}
    </> : <div className="form-grid">
      <label className="field full"><span>节点类别</span><select aria-label="节点类别" value={category} onChange={e => {
        setCategory(e.target.value); setEncounter(''); setOutcome(''); setMarks([]);
        if (!['node_type_002', 'unknown_ferocity'].includes(e.target.value)) setIsSource(false);
        setVisibility(isUnknown(e.target.value) ? 'hidden' : 'revealed');
        if (isUnknown(e.target.value)) setCompletion('pending');
      }}>
        <option value="" disabled>请选择节点类别</option>{Object.entries(catalog.labels.nodeTypes).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      {residentActive(node) && <small className="full">流窜居民：未清理</small>}
      <label className="field"><span>完成状态</span><select aria-label="完成状态" value={completion} onChange={e => {
        setCompletion(e.target.value); setConfirmCompletion(e.target.value === 'completed');
      }}>
        <option value="unknown">待确认</option><option value="pending">未完成</option><option value="completed">已完成</option></select></label>
      <label className="field"><span>探明状态</span><select aria-label="探明状态" value={visibility} onChange={e => setVisibility(e.target.value)}>
        <option value="unknown">待确认</option><option value="hidden">未探明</option><option value="revealed">已探明</option></select></label>
      {category === 'node_type_006' && <><label className="field full"><span>不期而遇事件</span><select aria-label="不期而遇事件" value={encounter} onChange={e => { setEncounter(e.target.value); setOutcome(''); }}>
        <option value="">未确认具体事件</option>{catalog.encounters.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        <label className="field full"><span>实际选项 / 结果</span><input value={outcome} onChange={e => setOutcome(e.target.value)} /></label></>}
      {category === 'node_type_012' && <label className="field full"><span>命运所指身份</span><select aria-label="命运所指身份" value={role} onChange={e => setRole(e.target.value)}>
        <option value="unknown">未确认</option><option value="true">真结局</option><option value="fake">假结局</option></select></label>}
      <fieldset className="full"><legend>节点标记</legend><div className="check-list">{Object.entries(catalog.labels.nodeMarks).map(([id, name]) =>
        <label key={id}><input type="checkbox" checked={marks.includes(id)} disabled={isUnknown(category)}
          onChange={e => setMarks(e.target.checked ? [...marks, id] : marks.filter(x => x !== id))} />{name}</label>)}</div></fieldset>
      <NumberField label="节点权重倍率" value={weight} onChange={setWeight} step={.1} min={-100} />
      {instance.dystopia?.active && <label className="field"><span>实托邦覆盖</span><select aria-label="实托邦覆盖" value={coverage} onChange={e => {
        setNodeCoverage(e.target.value); if (e.target.value !== 'inside') setIsSource(false);
      }}>
        <option value="inside">范围内</option><option value="outside">范围外</option><option value="unknown">待确认</option></select></label>}
      {instance.dystopia?.active && <label className="checkbox-field"><input aria-label="节点为理想源" type="checkbox" checked={isSource}
        disabled={instance.dystopia.ideologyId === 'dystopia_008' || !['node_type_002', 'unknown_ferocity'].includes(category)}
        onChange={e => { setIsSource(e.target.checked); if (e.target.checked) setNodeCoverage('inside'); }} />理想源</label>}
      {['node_type_004', 'node_type_013'].includes(category) && <NumberField label="已查看货柜面数" value={shelves} onChange={setShelves} max={5} />}
      <label className="checkbox-field full"><input type="checkbox" checked={position} onChange={e => setPosition(e.target.checked)} /><Crosshair size={15} />玩家当前位置</label>
    </div>}</div>
    <footer><button onClick={() => { setCompletion('completed'); setConfirmCompletion(true); setVisibility('revealed'); }} disabled={busy}><Check size={15} />已完成</button>
      <SaveButton busy={busy} disabled={busy || !category} onClick={save}>确认更新</SaveButton></footer>
  </section>{pool && <RewardPoolPanel key={`${pool.label}-${pool.kind}`} selection={pool} entries={entries} heldRelics={heldRelics}
    style={besidePopover(left, top, 386, panelHeight, viewport)} onClose={() => setPool(null)} />}</>;
}
