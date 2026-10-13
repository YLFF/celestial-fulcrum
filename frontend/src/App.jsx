import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Plus, Upload, Download, ImagePlus, ScanLine, Monitor, Undo2, Redo2, RefreshCw, Sun, Moon,
  Heart, Shield, Coins, Zap, Package, Users, ChevronRight, ChevronDown, Route, LoaderCircle, X, Pencil, Layers, Flag, Sparkles, Eye, Check, ArrowRight } from 'lucide-react';
import { api, download, setToken } from './api';
import { applyTheme, savedTheme } from './theme';
import { readPreference } from './preferences.js';
import { boundRecipients, relicGroups } from './relicPresentation';
import { filterRoutes } from './routeFilters';
import { searchOptionsError } from './planningOptions';
import { AREA_NAMES, componentAppraisalTotal, currentInstance, num, operatorProgressLabel, pct, routeNodeName, SOURCES, stepScoreDetails } from './model';
import { EntryImage, IconButton, Modal, NumberField, SaveButton } from './common';
import MapView from './MapView';
import BatchNodeEditor from './BatchNodeEditor';
import NodeEditor from './NodeEditor';
import ScoreDetails from './ScoreDetails';
import QuickResourceEditor from './QuickResourceEditor';
import TeamThresholdPanel from './TeamThresholdPanel';
import DystopiaEditor from './DystopiaEditor';
import PlanningDialog from './PlanningDialog';
import DecisionAdvice from './DecisionAdvice';
import { adviceMapRoute, filterAdvice } from './advicePresentation';
import AreaTabs from './AreaTabs';
import RelicRecognitionDialog from './RelicRecognitionDialog';
import CombatBonusDialog from './CombatBonusDialog';
import { ComponentEditor, OperatorEditor, RelicEditor } from './InventoryEditors';
import { NewRunEditor, ResourceEditor, GoalEditor } from './RunEditors';
import { UploadDialog, CaptureDialog } from './InputDialogs';

const ENDINGS = { normal1: '普通 1', pursuit1: '追猎 1', ending2: '结局 2', normal3: '普通 3', pursuit3: '追猎 3' };

export default function App() {
  const [theme, setTheme] = useState(savedTheme);
  useEffect(() => { applyTheme(theme); }, [theme]);
  const [catalog, setCatalog] = useState(null), [caps, setCaps] = useState({}), [runs, setRuns] = useState([]);
  useEffect(() => { if (catalog?.project?.name) document.title = catalog.project.name; }, [catalog]);
  const [loaded, setLoaded] = useState(null), [area, setArea] = useState('I'), [scores, setScores] = useState(null);
  const [planning, setPlanning] = useState(null), [routeIndex, setRouteIndex] = useState(0), [pursuitChoice, setPursuit] = useState(false);
  const [planMode, setPlanMode] = useState('global'), [advice, setAdvice] = useState(null);
  const endingModeLocked = area === 'V' && ['normal1', 'pursuit1'].includes(loaded?.state.goals?.endingV);
  const pursuit = endingModeLocked ? loaded.state.goals.endingV === 'pursuit1' : pursuitChoice;
  const [topN, setTopN] = useState(5), [budget, setBudget] = useState(50000), [busy, setBusy] = useState(false);
  const [modal, setModal] = useState(null), [node, setNode] = useState(null), [tasks, setTasks] = useState([]);
  const [toast, setToast] = useState(null), [dragging, setDragging] = useState(false);
  const [bootError, setBootError] = useState(''), [poolMode, setPoolMode] = useState('local');
  const [stepDetail, setStepDetail] = useState(null);
  const [routeFilterIds, setRouteFilterIds] = useState([]), [routeFilterMode, setRouteFilterMode] = useState('all');
  const visibleRoutes = useMemo(() => filterRoutes(planning, routeFilterIds, routeFilterMode, topN),
    [planning, routeFilterIds, routeFilterMode, topN]);
  const visibleAdvice = useMemo(() => filterAdvice(advice, routeFilterIds, routeFilterMode, topN),
    [advice, routeFilterIds, routeFilterMode, topN]);
  const activeResult = planMode === 'advice' ? advice : planning;
  useEffect(() => { setRouteIndex(0); setStepDetail(null); }, [routeFilterIds, routeFilterMode, planning, advice, planMode]);
  useEffect(() => { setAdvice(null); }, [loaded?.runId, loaded?.revision, area, pursuit, topN, budget]);
  const [lastAsset, setLastAsset] = useState(null);
  const [relicView, setRelicView] = useState('acquired');
  const [selectedNodes, setSelectedNodes] = useState([]);
  useEffect(() => { setSelectedNodes([]); }, [loaded?.runId, loaded?.revision, area]);
  const loadedRef = useRef(null), fileInput = useRef(null), importInput = useRef(null), taskControllers = useRef(new Map());
  const runRequest = useRef(0);
  const pendingFile = useRef(null), dragDepth = useRef(0);
  const viewRef = useRef({ area, pursuit, topN, budget, planMode }); viewRef.current = { area, pursuit, topN, budget, planMode };
  const entries = useMemo(() => catalog ? Object.fromEntries(Object.values(catalog).filter(Array.isArray).flat().filter(row => row.id).map(row => [row.id, row])) : {}, [catalog]);
  const instance = currentInstance(loaded?.state, area), state = loaded?.state;
  const nodeName = id => routeNodeName(id, instance?.nodes, catalog?.labels.nodeTypes);
  const planReady = instance && instance.actionPoints != null && instance.playerPosition && instance.nodes[instance.playerPosition]?.completion === 'completed';

  function notify(message, error = false) { setToast({ message, error, at: Date.now() }); }
  function failed(error) {
    const text = error.status === 409 ? '对局已更新，请刷新后重新确认这次修改。' : error.message;
    notify(text, true);
  }
  async function listRuns() { const value = await api('/api/runs'); setRuns(value.runs); return value.runs; }
  function applyRun(value, forceArea) {
    loadedRef.current = value; setLoaded(value);
    if (forceArea) setArea(value.state.currentAreaKey || 'I');
    setPlanning(null); setAdvice(null); setScores(null); setNode(null); setStepDetail(null);
    localStorage.setItem('fulcrum-run', value.runId);
  }
  async function openRun(id, forceArea = true) {
    const request = ++runRequest.current;
    const value = await api(`/api/runs/${encodeURIComponent(id)}`);
    if (request === runRequest.current) applyRun(value, forceArea);
    return value;
  }
  async function initialize() {
    setBootError('');
    try {
      const session = await api('/api/session');
      if (session.token) setToken(session.token);
      setCaps(await api('/api/capabilities'));
      const data = await api('/api/catalog'); setCatalog(data);
      const rows = await listRuns(), saved = readPreference('fulcrum-run');
      const chosen = rows.find(row => row.runId === saved && row.valid) || rows.find(row => row.valid && !row.runId.startsWith('service-smoke')) || rows.find(row => row.valid);
      if (chosen) await openRun(chosen.runId);
    } catch (e) { setBootError(e.message); }
  }
  useEffect(() => { initialize(); return () => { for (const controller of taskControllers.current.values()) controller.cancelled = true; }; }, []);
  useEffect(() => { if (!toast) return; const id = setTimeout(() => setToast(null), 6000); return () => clearTimeout(id); }, [toast]);
  useEffect(() => {
    const handler = event => { if (event.key === 'Escape') { setNode(null); setStepDetail(null); } };
    document.addEventListener('keydown', handler); return () => document.removeEventListener('keydown', handler);
  }, []);
  useEffect(() => {
    if (!loaded) return;
    const id = setInterval(async () => {
      try {
        const request = runRequest.current;
        const fresh = await api(`/api/runs/${encodeURIComponent(loaded.runId)}`);
        if (request === runRequest.current && loadedRef.current?.runId === fresh.runId &&
            fresh.revision > loadedRef.current.revision) {
          applyRun(fresh, false); notify('已同步新的对局状态');
        }
      } catch { /* A transient refresh failure does not erase an open form. */ }
    }, 8000);
    return () => clearInterval(id);
  }, [loaded?.runId]);

  async function startJob(kind, options, source = loadedRef.current) {
    const job = await api(`/api/runs/${source.runId}/jobs/${kind}`, { method: 'POST', body: { expectedRevision: source.revision, ...options } });
    const controller = { cancelled: false }; taskControllers.current.set(job.jobId, controller);
    setTasks(old => [...old, job]);
    try {
      let current = job;
      while (['queued', 'running'].includes(current.status)) {
        if (controller.cancelled) throw new Error('已取消');
        await new Promise(resolve => setTimeout(resolve, 250));
        current = await api(`/api/jobs/${job.jobId}`);
        setTasks(old => old.map(row => row.jobId === current.jobId ? current : row));
      }
      if (current.status !== 'completed') throw new Error(current.error || '任务未完成');
      if (current.stale) throw new Error('计算结果已过期，请根据新状态重新计算。');
      return current;
    } finally { taskControllers.current.delete(job.jobId); setTasks(old => old.filter(row => row.jobId !== job.jobId)); }
  }
  useEffect(() => {
    if (!planReady) { setScores(null); return; }
    let active = true;
    startJob('score', { areaKey: area, pursuit }).then(job => {
      if (active && loadedRef.current?.revision === job.sourceRevision && loadedRef.current.runId === job.runId) setScores(job.result);
    }).catch(e => { if (active) failed(e); });
    return () => { active = false; };
  }, [loaded?.runId, loaded?.revision, area, pursuit, !!planReady]);

  async function mutate(commands, sourceRevision = loadedRef.current?.revision) {
    if (!commands.length) { setModal(null); return true; }
    setBusy(true);
    try {
      await api(`/api/runs/${loadedRef.current.runId}`, { method: 'PATCH', body: { expectedRevision: sourceRevision, commands } });
      setModal(null); setNode(null);
      await openRun(loadedRef.current.runId, false); await listRuns(); notify('对局已保存'); return true;
    } catch (e) { failed(e); return false; }
    finally { setBusy(false); }
  }
  function edit(type, extras = {}) { setNode(null); setModal({ type, source: loadedRef.current, ...extras }); }
  function selectFile(file) {
    if (!file) return;
    if (!loadedRef.current) { pendingFile.current = file; edit('new'); return; }
    edit('upload', { file });
  }
  async function createRun(body) {
    setBusy(true);
    try {
      const value = await api('/api/runs', { method: 'POST', body });
      setModal(null);
      await openRun(value.runId); await listRuns(); notify('已创建新对局');
      if (pendingFile.current) { const file = pendingFile.current; pendingFile.current = null; edit('upload', { file }); }
    } catch (e) { failed(e); }
    finally { setBusy(false); }
  }
  async function restore(file) {
    if (!file) return; setBusy(true);
    try {
      const source = JSON.parse(await file.text());
      const value = await api('/api/runs/restore', { method: 'POST', body: { state: source.state || source,
        runId: `${((source.state || source).runId || 'restored').slice(0, 40)}-ui-${Date.now().toString(36)}` } });
      await openRun(value.runId); await listRuns(); notify('已恢复对局副本');
    } catch (e) { failed(e); }
    finally { setBusy(false); }
  }
  async function openExample() {
    setBusy(true);
    try { const value = await api('/api/examples/true-run-001/restore', { method: 'POST', body: {} }); await openRun(value.runId); await listRuns(); notify('已打开实测对局副本'); }
    catch (e) { failed(e); } finally { setBusy(false); }
  }
  async function confirmRecognition(body) {
    setBusy(true);
    try {
      const value = await api(`/api/runs/${modal.source.runId}/confirm-recognition`, { method: 'POST', body });
      setModal(null);
      await openRun(value.runId); await listRuns(); notify('识别结果已确认，预测已更新');
    } catch (e) { failed(e); } finally { setBusy(false); }
  }
  async function confirmRelics(body) {
    setBusy(true);
    try {
      const value = await api(`/api/runs/${modal.source.runId}/confirm-relics`, { method: 'POST', body });
      setModal(null);
      await openRun(value.runId, false); await listRuns(); notify('藏品已追加，原有藏品保留');
    } catch (error) { failed(error); } finally { setBusy(false); }
  }
  async function createManualMap(body) {
    setBusy(true);
    try {
      const value = await api(`/api/runs/${modal.source.runId}/manual-map`, { method: 'POST', body });
      setModal(null);
      await openRun(value.runId); await listRuns(); notify('手动地图已建立，请补充待确认节点');
    } finally { setBusy(false); }
  }
  async function search() {
    try {
      const source = loadedRef.current;
      const check = await api(`/api/runs/${source.runId}/planning-check`, { method: 'POST', body: { expectedRevision: source.revision, areaKey: area } });
      if (loadedRef.current?.runId !== source.runId || loadedRef.current?.revision !== source.revision || viewRef.current.area !== area) return;
      setModal({ type: 'planning', source, areaKey: area, check });
    } catch (e) { failed(e); }
  }
  async function executeSearch(planningGoalIds, source = modal?.source || loadedRef.current, useItemIds = null) {
    const optionsError = searchOptionsError(topN, budget);
    if (optionsError) { notify(optionsError, true); return; }
    setBusy(true);
    try {
      if (loadedRef.current?.runId !== source.runId || loadedRef.current?.revision !== source.revision || viewRef.current.area !== area ||
          (modal?.type === 'planning' && modal.areaKey !== area)) throw new Error('对局或层级已更新，请重新选择本层目标。');
      const old = currentInstance(source.state, area).strategy.planningGoalIds || [];
      if (JSON.stringify(old) !== JSON.stringify(planningGoalIds)) {
        await api(`/api/runs/${source.runId}`, { method: 'PATCH', body: { expectedRevision: source.revision,
          commands: [{ type: 'strategy', areaKey: area, value: { planningGoalIds } }] } });
        source = await openRun(source.runId, false);
      }
      setModal(null);
      const job = await startJob('plan', { areaKey: area, pursuit, topN, maxStates: budget, planningGoalIds, useItemIds, mode: planMode }, source);
      if (loadedRef.current.runId === job.runId && loadedRef.current.revision === job.sourceRevision &&
          viewRef.current.area === job.options.areaKey && viewRef.current.pursuit === job.options.pursuit &&
          viewRef.current.topN === job.options.topN && viewRef.current.budget === job.options.maxStates) {
        if (job.options.mode === 'advice') setAdvice(job.result); else setPlanning(job.result);
        setRouteFilterIds([]); setRouteFilterMode('all'); setRouteIndex(0); setStepDetail(null); notify(`搜索完成 · ${job.result.expandedStates.toLocaleString()} 个状态`);
      }
    } catch (e) { failed(e); }
    finally { setBusy(false); }
  }
  async function travelHistory(direction) {
    setBusy(true);
    try { await api(`/api/runs/${loaded.runId}/${direction}`, { method: 'POST', body: { expectedRevision: loaded.revision } }); await openRun(loaded.runId, true); notify(direction === 'undo' ? '已撤销上次地图更新' : '已重做地图更新'); }
    catch (e) { failed(e); } finally { setBusy(false); }
  }
  async function exportRun() {
    try {
      const state = await api(`/api/runs/${loaded.runId}/export`);
      download(JSON.stringify(state, null, 2), `${loaded.runId}.json`);
    } catch (e) { failed(e); }
  }
  const activePlan = tasks.some(row => row.kind === 'plan'), selectedRoute = planMode === 'advice' ? adviceMapRoute(visibleAdvice[routeIndex]) : visibleRoutes[routeIndex];
  const activeStep = stepDetail && visibleRoutes[stepDetail.route]?.steps[stepDetail.step];
  const eventPool = poolMode === 'local' ? state?.areas[area]?.encounterPool || [] : state?.globalEncounterPool || [];
  const eventWeights = Object.fromEntries((scores?.eventDistribution?.events || scores?.eventDistribution?.rows || []).map(row => [row.eventId, row.probability]));
  const close = () => setModal(null);
  const saveModal = commands => mutate(commands, modal.source.revision);

  if (!catalog) return <main className="loading-page"><div className="brand"><Layers size={25} />天堂支点</div>{bootError ? <><div className="form-error">{bootError}</div><button onClick={initialize}>重新连接</button></> : <LoaderCircle className="spin" size={24} />}</main>;

  return <div className="app" onDragEnter={e => { if (modal?.type === 'relicRecognition') return; if ([...e.dataTransfer.types].includes('Files')) { e.preventDefault(); dragDepth.current++; setDragging(true); } }}
    onDragOver={e => { if ([...e.dataTransfer.types].includes('Files')) e.preventDefault(); }}
    onDragLeave={e => { if ([...e.dataTransfer.types].includes('Files')) { dragDepth.current--; if (dragDepth.current <= 0) setDragging(false); } }}
    onDrop={e => { e.preventDefault(); dragDepth.current = 0; setDragging(false); if (busy) return; const file = e.dataTransfer.files[0]; if (file?.name.toLowerCase().endsWith('.json')) restore(file); else selectFile(file); }}>
    <input className="hidden-input" type="file" disabled={busy} ref={fileInput} accept="image/png,image/jpeg,image/webp,image/bmp" aria-label="上传地图截图" onChange={e => { selectFile(e.target.files[0]); e.target.value = ''; }} />
    <input className="hidden-input" type="file" disabled={busy} ref={importInput} accept=".json,application/json" aria-label="导入 Playtime" onChange={e => { restore(e.target.files[0]); e.target.value = ''; }} />
    <header className="app-header"><div className="brand" title={catalog.project.name}><Layers size={23} /><div><b>{catalog.project.shortName}</b><small>明日方舟集成战略助手</small></div></div>
      <select className="run-select" aria-label="选择对局" value={loaded?.runId || ''} disabled={busy} onChange={e => openRun(e.target.value).catch(failed)}><option value="" disabled>选择对局</option>
        {runs.filter(row => row.valid).map(row => <option value={row.runId} key={row.runId}>{row.runId}</option>)}</select>
      {state && <div className="run-badges"><span>N{state.opening.difficulty}</span><span>{catalog.squads[state.opening.squadId] || '未选分队'}</span></div>}
      <div className="header-actions"><button className="primary start-exploration" onClick={() => edit('new')} disabled={busy}><Plus size={17} aria-hidden="true" />开始探索</button>
        <IconButton icon={theme === 'dark' ? Sun : Moon} label={theme === 'dark' ? '切换到明亮模式' : '切换到黑暗模式'}
          aria-pressed={theme === 'dark'} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} />
        <IconButton icon={Upload} label="恢复 Playtime" onClick={() => importInput.current.click()} disabled={busy} />
        <IconButton icon={Download} label="导出 Playtime" onClick={exportRun} disabled={!loaded} />
        <IconButton icon={Undo2} label="撤销上次地图更新" onClick={() => travelHistory('undo')} disabled={!loaded?.history?.canUndo || busy} />
        <IconButton icon={Redo2} label="重做地图更新" onClick={() => travelHistory('redo')} disabled={!loaded?.history?.canRedo || busy} />
        <IconButton icon={RefreshCw} label="刷新对局" onClick={() => loaded && openRun(loaded.runId, false).catch(failed)} disabled={!loaded || busy} />
      </div></header>
    <div className="resource-strip">{state ? <>
      <Resource icon={Heart} name="生命" value={`${num(state.resources.life.current)}/${num(state.resources.life.max)}`} color="red" onEdit={() => edit('quickResource', { field: 'life' })} disabled={busy} />
      <Resource icon={Shield} name="护盾" value={num(state.resources.shield)} onEdit={() => edit('quickResource', { field: 'shield' })} disabled={busy} />
      <Resource icon={ChevronRight} name="等级 / 经验" value={`Lv.${state.resources.level} · ${state.resources.experience.current}/${state.resources.experience.max ?? '—'}`} onEdit={() => edit('quickResource', { field: 'level' })} disabled={busy} />
      <Resource icon={Sparkles} name="希望" value={num(state.resources.hope)} color="gold-text" onEdit={() => edit('quickResource', { field: 'hope' })} disabled={busy} />
      <Resource icon={Coins} name="源石锭" value={num(state.resources.originiumIngot)} color="green-text" onEdit={() => edit('quickResource', { field: 'originiumIngot' })} disabled={busy} />
      <Resource icon={Package} name="总估价" value={num(state.resources.totalEstimatedValue ?? componentAppraisalTotal(state.componentBox.items))} />
      <Resource icon={Zap} name="行动力" value={num(instance?.actionPoints)} onEdit={instance ? () => edit('quickResource', { field: 'actionPoints' }) : undefined} disabled={busy} />
      <IconButton icon={Pencil} label="编辑实时资源" onClick={() => edit('resources')} disabled={busy} />
    </> : <span className="quiet">未打开对局</span>}</div>
    <div className="workspace"><main className="main-workspace">
      <div className="map-header"><AreaTabs runId={loaded?.runId} area={area} disabled={busy} onChange={value => { setArea(value); setNode(null); setPlanning(null); }} />
        <div className="input-actions"><span className="input-caption">导入地图或更新探索进度：</span><button className="primary" onClick={() => fileInput.current.click()} disabled={busy}><ImagePlus size={16} /><span>导入地图</span></button>
          {caps.windowCapture && <button onClick={() => loaded ? edit('capture') : edit('new')} disabled={busy}><Monitor size={16} /><span>窗口截图</span></button>}
          <IconButton icon={Layers} label="编辑实托邦 / 乌托邦" onClick={() => edit('dystopia')} disabled={!instance || busy} />
        </div></div>
      <MapView instance={instance} catalog={catalog} entries={entries} scores={scores} route={selectedRoute}
        selectedIds={selectedNodes} onSelectionChange={setSelectedNodes}
        onSelect={(id, anchor) => { setNode({ id, anchor, source: loaded, instance }); setStepDetail(null); }} onUpload={() => fileInput.current.click()} busy={busy} />
      {!!selectedNodes.length && <div className="map-review-toolbar"><span>已选 {selectedNodes.length} 个节点</span><button disabled={busy || !selectedNodes.some(id => id !== '0,0')} onClick={() => edit('batchNodes', { ids: selectedNodes })}><Pencil size={14} />编辑所选节点</button><button onClick={() => setSelectedNodes([])}>取消选择</button></div>}
      <div className="inventory-band">
        <InventoryStrip title="藏品" subtitle={state ? `${state.relics.reduce((a, r) => a + (r.count || 1), 0)} 件` : '—'} icon={Sparkles}
          contentClass="relic-inventory"
          onEdit={() => edit('relics')} onAdd={() => edit('relics', { adding: true })} disabled={!state || busy}
          actions={<><div className="segmented relic-view-switch" aria-label="藏品展示方式"><button className={relicView === 'acquired' ? 'active' : ''} onClick={() => setRelicView('acquired')}>获得顺序</button><button className={relicView === 'category' ? 'active' : ''} onClick={() => setRelicView('category')}>分类</button></div><IconButton icon={ScanLine} label="识别藏品" disabled={!state || busy || !caps.relicRecognition} onClick={() => edit('relicRecognition', { assetInfo: lastAsset })} />
            <button className="bonus-button" title="查看全体干员战斗加成" onClick={() => edit('combatBonuses')} disabled={!state || busy || !caps.relicEffectAggregation}><Sparkles size={14} />加成汇总</button></>}>
          {(relicView === 'category' ? relicGroups(state?.relics || [], entries, catalog.relicCategories) : [{ name: '', items: state?.relics || [] }]).map(group => <div className={`relic-display-group ${group.name ? 'classified' : ''}`} key={group.name}>
            {group.name && <small>{group.name}</small>}<div>{group.items.map(row => <button key={row.id} className="inventory-token" title={`${entries[row.id]?.name}${row.enchantment ? ` · 已附魔 ${boundRecipients(row).map(item => item.operatorName).join('、')}` : ''}`} onClick={() => edit('relics')}><EntryImage entry={entries[row.id]} className="inventory-image" />{row.count > 1 && <span>{row.count}</span>}</button>)}</div>
          </div>)}
          {!state?.relics.length && <span className="quiet">暂无藏品</span>}
        </InventoryStrip>
        <InventoryStrip title="零件箱" subtitle={state ? `${state.componentBox.items.length}/${state.componentBox.capacity} · 总估价 ${num(componentAppraisalTotal(state.componentBox.items))}` : '—'} icon={Package}
          warning={state && state.componentBox.items.length > state.componentBox.capacity ? `超限 ${state.componentBox.items.length - state.componentBox.capacity} 件` : ''}
          contentClass="component-inventory" onEdit={() => edit('components')} onAdd={() => edit('components', { adding: true })} disabled={!state || busy}>
          {['加工品', '自然物', '概念体'].map(kind => <div className="component-inventory-row" key={kind}><small>{kind}</small><div>{state?.componentBox.items.filter(row => entries[row.componentId]?.kind === kind).sort((a, b) => a.componentId.localeCompare(b.componentId)).map(row => <button key={row.instanceId} className={`inventory-token ${row.remainingUses != null && !row.routeCandidate ? 'excluded' : ''}`} title={`${entries[row.componentId]?.name} · 估价 ${num(row.estimatedValue)}`} onClick={() => edit('components')}>
            <EntryImage entry={entries[row.componentId]} className="inventory-image" />{row.remainingUses != null && <span>{row.remainingUses}</span>}</button>)}</div></div>)}
        </InventoryStrip>
        <InventoryStrip title="干员与编队" subtitle={state ? `${state.operators.length} 人 · ${state.squad?.length || 0}/${state.resources.carrySlots}` : '—'} icon={Users}
          onEdit={() => edit('operators')} onAdd={() => edit('operators', { adding: true })} disabled={!state || busy}>
          <div className="operator-strip">{state?.operators.map(row => <button key={row.instanceId} title={`${row.name} · ${SOURCES[row.source] || row.source}`} onClick={() => edit('operators')}>
            <span>{row.name}</span><small>{row.rarity || '?'}★ · {operatorProgressLabel(row.elite)}{row.remainingBattles ? ' · 助' : ''}</small></button>)}</div>
        </InventoryStrip>
      </div>
    </main><aside className="playtime-sidebar"><div className="sidebar-heading"><Flag size={16} /><h2>Playtime</h2><IconButton icon={Pencil} label="编辑结局目标" onClick={() => edit('goals')} disabled={!loaded || busy} /></div>
      {loaded ? <>
        <SidebarSection title="结局进度"><div className="ending-chips"><span>V · {ENDINGS[state.goals.endingV] || '未选择'}</span><span>VI · {ENDINGS[state.goals.endingVI] || '未选择'}</span></div>
          {loaded.goalSummary.milestones.map(row => <label className="goal-check" key={row.id}>
            <input type="checkbox" checked={row.status === 'completed'} disabled={busy} onChange={e => mutate([{ type: 'goals', value: { ...state.goals, progress: { ...state.goals.progress, [row.id]: { status: e.target.checked ? 'completed' : 'pending' } } } }])} />
            <span>{row.name}</span></label>)}
          {!loaded.goalSummary.milestones.some(row => row.priority !== 'ignored') && <span className="quiet">结局目标未设定</span>}
        </SidebarSection>
        <SidebarSection title="节点池" defaultOpen={false}><div className="section-heading"><span>已知 / 总量</span></div>
          {Object.values(instance?.nodePool || {}).filter(row => row.categoryId).map(row => <div className="pool-row" key={row.categoryId}><span>{catalog.labels.nodeTypes[row.categoryId]}</span>
            <span className={row.countRuleConflict ? 'negative' : ''}>{row.knownCount} / {row.minimum === row.maximum ? row.maximum : `${row.minimum}–${row.maximum}`}</span></div>)}
        </SidebarSection>
        <SidebarSection title="不期而遇池" defaultOpen={false}><div className="section-heading"><div className="segmented small"><button className={poolMode === 'local' ? 'active' : ''} onClick={() => setPoolMode('local')}>本层</button><button className={poolMode === 'global' ? 'active' : ''} onClick={() => setPoolMode('global')}>全局</button></div></div>
          <div className="encounter-list">{eventPool.map(row => <div className={`encounter-row ${(row.eligibility === 'excluded' || (row.completedCount > 0 || row.completedRun > 0) && row.repeatability === 'once_per_run') ? 'unavailable' : ''}`} key={row.id}>
            <span>{row.name}</span><small>{row.completedHere || row.completedCount ? `${row.completedHere || row.completedCount} 次` : eventWeights[row.id] != null ? pct(eventWeights[row.id]) : row.eligibility === 'conditional' ? '有条件' : '—'}</small></div>)}</div>
        </SidebarSection>
        <SidebarSection title="战力门槛"><TeamThresholdPanel status={loaded.teamThresholds?.[area]} instance={instance} busy={busy}
          onChange={value => mutate([{ type: 'strategy', areaKey: area, value: { scoringOptions: { ...instance.strategy.scoringOptions, teamThresholdOverride: value } } }])} /></SidebarSection>
        <SidebarSection title="本局备忘" defaultOpen={false}><IconButton icon={Pencil} label="编辑备忘" onClick={() => edit('memo')} /><p className="memo-text">{state.memo || state.goals.note || '—'}</p></SidebarSection>
      </> : <div className="no-run-actions"><button className="primary" onClick={() => edit('new')}><Plus size={16} />新建对局</button>{caps.exampleRun && <button onClick={openExample} disabled={busy}>打开一层实测</button>}</div>}
    </aside></div>
    <section className="route-section"><div className="route-heading"><h2><Route size={18} />路径规划</h2><div className="route-controls">
      <div className="segmented planning-mode" aria-label="规划方式">
        <button className={planMode === 'global' ? 'active' : ''} onClick={() => { setPlanMode('global'); setRouteFilterIds([]); }}>全局路径规划</button>
        <button className={planMode === 'advice' ? 'active' : ''} onClick={() => { setPlanMode('advice'); setRouteFilterIds([]); }}>一步路径建议</button>
      </div>
      <ReserveEditor key={`${loaded?.runId}-${loaded?.revision}-${area}`} instance={instance} busy={busy}
        onSave={merchantReserve => { const options = { ...instance.strategy.scoringOptions, merchantReserve };
          delete options.merchantReserveEntries;
          return mutate([{ type: 'strategy', areaKey: area, value: { scoringOptions: options } }]); }} />
      <div className="segmented" title={endingModeLocked ? '本层规划方式由五层结局目标决定' : undefined}><button disabled={endingModeLocked} className={!pursuit ? 'active' : ''} onClick={() => { setPursuit(false); setPlanning(null); }}>不追猎</button><button disabled={endingModeLocked} className={pursuit ? 'active' : ''} onClick={() => { setPursuit(true); setPlanning(null); }}>追猎</button></div>
      <button className="primary" onClick={search} disabled={!planReady || activePlan || busy}>{activePlan ? <LoaderCircle size={16} className="spin" /> : <Route size={16} />}规划</button>
    </div></div>
      {activeResult ? <>{planMode === 'global' && <div className="search-summary"><span>{planning.searchComplete ? '搜索完成' : '预算截断'} · {planning.expandedStates.toLocaleString()} 状态</span>
        <span>{visibleRoutes.length} / {topN} 条路线</span>{planning.randomMovement.excludedItemInstanceIds.length > 0 && <span>随机移动另计</span>}</div>}
        {!!activeResult.priorityTargets?.length && <fieldset className="route-priority-filters"><legend>关联优先项</legend>
          <div className="route-filter-options">{activeResult.priorityTargets.map(target => <label key={target.id}>
            <input type="checkbox" checked={routeFilterIds.includes(target.id)} onChange={event => setRouteFilterIds(old =>
              event.target.checked ? [...old, target.id] : old.filter(id => id !== target.id))} />{target.name}</label>)}</div>
          <div className="segmented small" aria-label="优先项筛选方式"><button className={routeFilterMode === 'all' ? 'active' : ''} onClick={() => setRouteFilterMode('all')}>全部相关</button>
            <button className={routeFilterMode === 'any' ? 'active' : ''} onClick={() => setRouteFilterMode('any')}>任一相关</button></div>
          <IconButton icon={X} label="清除路线筛选" disabled={!routeFilterIds.length} onClick={() => setRouteFilterIds([])} />
        </fieldset>}
        {planMode === 'advice' ? <DecisionAdvice result={advice} rows={visibleAdvice} selectedIndex={routeIndex} onSelect={setRouteIndex}
          instance={instance} catalog={catalog} entries={entries} /> : <>
        {!visibleRoutes.length && <div className="route-empty">{routeFilterIds.length ? '已搜索的可行路线中没有符合当前筛选条件的路线' : '当前未找到可行路线'}</div>}
        <div className="route-list">{visibleRoutes.map((row, index) => <div className={`route-row ${index === routeIndex ? 'selected' : ''}`} key={index}>
          <button className="route-choice" onClick={() => { setRouteIndex(index); setStepDetail(null); }} aria-label={`选择路线 ${index + 1}`}><span>路线 {index + 1}</span><b>{num(row.metrics.weightedValue)}<small>分</small></b></button>
          <div className="route-steps">{row.steps.map((step, i) => <React.Fragment key={i}><button className={`route-step ${stepDetail?.route === index && stepDetail?.step === i ? 'active' : ''}`}
            onClick={() => { setRouteIndex(index); setStepDetail({ route: index, step: i }); }}><small>{i + 1} · {step.componentId ? entries[step.componentId]?.name || step.movement : '徒步'}</small>
            <b title={`(${step.entered})${step.portalTransfer ? ` → (${step.arrived})` : ''}`}>{nodeName(step.entered)}{step.portalTransfer && ` → ${nodeName(step.arrived)}`}</b><span>{num(step.weightedValue)} 分</span>
            {step.referenceLossPoints < 0 && <span className="reference-loss-inline">上贡参考 {num(step.referenceLossPoints)}</span>}</button>{i < row.steps.length - 1 && <ArrowRight size={13} className="step-arrow" />}</React.Fragment>)}</div>
          <div className="route-result"><span title={row.goalType !== 'pursuit' ? `(${row.endNode})` : undefined}>{row.goalType === 'pursuit' ? '追猎' : `终点 ${nodeName(row.endNode)}`}</span><small>行动力 {row.remainingActionPoints}</small>
            {!!row.prerequisites?.length && <small className="route-priority">前置 {row.prerequisiteRanking.plannedKnownCompletions} · 寻找覆盖 {pct(row.prerequisiteRanking.searchCoverage)}</small>}
            {!!row.prerequisites?.length && <details><summary>前置：{row.prerequisites.filter(target => target.plannedCompletion).length} / {row.prerequisites.length} 已定位目标计划完成</summary>
              {row.prerequisites.map(target => <p key={target.id}>{target.name}：{target.plannedCompletion ? '路线经过' : !target.feasibleFromSnapshot ? '当前资源不满足' : target.knownNodeIds.length ? '本路线未完成' : `候选位置探索覆盖 ${pct(target.searchCoverage)}（不保证找到）`}
                {!!target.visitedNodeIds?.length && <span title={target.visitedNodeIds.map(id => `(${id})`).join('、')}> · 前往 {target.visitedNodeIds.map(nodeName).join('、')}</span>}
                {!!target.revealedNodeIds?.length && <span title={target.revealedNodeIds.map(id => `(${id})`).join('、')}> · 可能揭示 {target.revealedNodeIds.map(nodeName).join('、')}</span>}</p>)}</details>}
            {row.referenceLossPoints < 0 && <small className="reference-loss-inline">上贡参考 {num(row.referenceLossPoints)} 分</small>}
            {row.terminalScore && <details className="terminal-score"><summary>离层 / 追猎奖励 {num(row.terminalScore.points)} 分</summary><ScoreDetails value={row.terminalScore} catalog={catalog} compact /></details>}
          </div>
        </div>)}</div>
        {activeStep && <StepBreakdown step={activeStep} nodes={instance?.nodes} nodeValues={planning.scoring?.nodeValues} catalog={catalog} onClose={() => setStepDetail(null)} />}
        </>}
      </> : <div className="route-empty">{planReady ? (planMode === 'advice' ? '一步建议待计算' : '路线待计算') : '地图、玩家位置与完成状态待确认'}</div>}
    </section>
    <footer className="app-footer"><span className="status-dot" /><span>本地服务</span><span>{loaded ? `Playtime v${loaded.revision}` : '无对局'}</span>
      {tasks.map(task => <span className="task-status" key={task.jobId}><LoaderCircle size={12} className="spin" />{({ recognize: '识图', 'recognize-relics': '藏品识别', score: '评分', plan: '搜索' })[task.kind]} {task.progress.expandedStates ? task.progress.expandedStates.toLocaleString() : ''}
        <button title="取消任务" aria-label="取消任务" onClick={() => api(`/api/jobs/${task.jobId}/cancel`, { method: 'POST' }).catch(failed)}><X size={13} /></button></span>)}</footer>
    {dragging && <div className="drop-overlay"><Upload size={38} /><b>导入截图 / Playtime</b></div>}
    {toast && <div className={`toast ${toast.error ? 'error' : ''}`} role={toast.error ? 'alert' : 'status'}>{toast.error ? <X size={16} /> : <Check size={16} />}<span>{toast.message}</span><button aria-label="关闭提示" onClick={() => setToast(null)}><X size={14} /></button></div>}
    {node && <NodeEditor key={`${node.source.revision}-${node.id}`} node={node.instance.nodes[node.id]} instance={node.instance} catalog={catalog} value={scores?.nodeValues[node.id]}
      entries={entries} heldRelics={state?.relics} anchor={node.anchor} busy={busy} onClose={() => setNode(null)} onSave={commands => mutate(commands, node.source.revision)} />}
    {modal?.type === 'new' && <NewRunEditor catalog={catalog} busy={busy} onClose={close} onCreate={createRun} />}
    {modal?.type === 'planning' && <PlanningDialog key={`${modal.source.revision}-${modal.areaKey}`} check={modal.check} items={modal.source.state.componentBox.items}
      entries={entries} mode={planMode} topN={topN} budget={budget} onTopNChange={value => { setTopN(value); setPlanning(null); }}
      onBudgetChange={value => { setBudget(value); setPlanning(null); }} busy={busy} onClose={close} onPlan={(ids, items) => executeSearch(ids, modal.source, items)} />}
    {modal?.type === 'batchNodes' && <BatchNodeEditor ids={modal.ids} areaKey={area} catalog={catalog} onClose={close} onSave={saveModal} busy={busy} />}
    {modal?.type === 'upload' && <UploadDialog key={modal.file?.name || modal.assetInfo?.assetId} {...modal} loaded={modal.source} catalog={catalog} entries={entries} startJob={startJob} onConfirm={confirmRecognition} onManualCreate={createManualMap} onClose={close} busy={busy} notify={notify} onAsset={setLastAsset} />}
    {modal?.type === 'capture' && <CaptureDialog onClose={close} notify={notify} onCaptured={assetInfo => setModal({ type: 'upload', source: modal.source, assetInfo })} />}
    {modal?.type === 'relics' && <RelicEditor adding={modal.adding} state={modal.source.state} catalog={catalog} entries={entries} onSave={saveModal} onClose={close} busy={busy} />}
    {modal?.type === 'relicRecognition' && <RelicRecognitionDialog loaded={modal.source} entries={entries} assetInfo={modal.assetInfo} onAsset={setLastAsset}
      startJob={startJob} onConfirm={confirmRelics} onClose={close} busy={busy} notify={notify} />}
    {modal?.type === 'components' && <ComponentEditor adding={modal.adding} state={modal.source.state} catalog={catalog} entries={entries} onSave={saveModal} onClose={close} busy={busy} />}
    {modal?.type === 'operators' && <OperatorEditor adding={modal.adding} loaded={modal.source} areaKey={area} state={modal.source.state} catalog={catalog} entries={entries} onSave={saveModal} onClose={close} busy={busy} />}
    {modal?.type === 'combatBonuses' && <CombatBonusDialog loaded={modal.source} areaKey={area} entries={entries} onClose={close} />}
    {modal?.type === 'resources' && <ResourceEditor state={modal.source.state} instance={currentInstance(modal.source.state, area)} catalog={catalog} onSave={saveModal} onClose={close} busy={busy} />}
    {modal?.type === 'quickResource' && <QuickResourceEditor field={modal.field} state={modal.source.state} instance={currentInstance(modal.source.state, area)} onSave={saveModal} onClose={close} busy={busy} />}
    {modal?.type === 'goals' && <GoalEditor loaded={modal.source} onSave={saveModal} onClose={close} busy={busy} />}
    {modal?.type === 'dystopia' && <DystopiaEditor instance={currentInstance(modal.source.state, area)} catalog={catalog} entries={entries} onSave={saveModal} onClose={close} busy={busy} />}
    {modal?.type === 'memo' && <MemoEditor value={modal.source.state.memo || ''} onClose={close} onSave={saveModal} busy={busy} />}
  </div>;
}

function Resource({ icon: Icon, name, value, color = '', onEdit, disabled }) { return <div className={`resource ${color} ${onEdit ? 'editable' : ''}`} role={onEdit ? 'button' : undefined} tabIndex={onEdit && !disabled ? 0 : undefined}
  aria-label={onEdit ? `编辑${name}` : undefined} aria-disabled={onEdit ? disabled : undefined} title={onEdit ? `编辑${name}` : undefined}
  onDoubleClick={() => !disabled && onEdit?.()} onKeyDown={event => { if (onEdit && !disabled && ['Enter', ' '].includes(event.key)) { event.preventDefault(); onEdit(); } }}><Icon size={17} /><div><small>{name}</small><b>{value}</b></div></div>; }
function SidebarSection({ title, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return <section className="sidebar-section"><button className="sidebar-toggle" aria-expanded={open} aria-label={`${open ? '收起' : '展开'}${title}`} onClick={() => setOpen(!open)}>
    <h3>{title}</h3>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button>{open && <div className="sidebar-content">{children}</div>}</section>;
}
function ReserveEditor({ instance, busy, onSave }) {
  const saved = instance?.strategy.scoringOptions?.merchantReserve ?? 0;
  const [value, setValue] = useState(String(saved));
  const valid = value.trim() !== '' && Number.isSafeInteger(Number(value)) && Number(value) >= 0;
  return <div className="reserve-editor"><label className="field"><span>路线规划预留源石锭</span><input aria-label="路线规划预留源石锭" type="number" min={0} step={1}
    value={value} disabled={!instance || busy} onChange={event => setValue(event.target.value)} /></label>
    <IconButton icon={Check} label="保存路线规划预留源石锭并重新评分" disabled={!instance || busy || !valid || Number(value) === saved} onClick={() => onSave(Number(value))} /></div>;
}
function InventoryStrip({ title, subtitle, icon: Icon, onEdit, onAdd, actions, disabled, children, contentClass = '', warning = '' }) {
  return <section className={`inventory-section ${warning ? 'over-capacity' : ''}`}><header><h3><Icon size={15} />{title}</h3><span className={warning ? 'capacity-warning' : ''}>{subtitle}{warning && <strong role="status">{warning}</strong>}</span><div className="inventory-actions">{actions}<IconButton icon={Pencil} label={`编辑${title}`} onClick={onEdit} disabled={disabled} /><IconButton icon={Plus} label={`添加${title}`} onClick={onAdd} disabled={disabled} /></div></header><div className={`inventory-content ${contentClass}`}>{children}</div></section>;
}
function MemoEditor({ value, onSave, onClose, busy }) {
  const [text, setText] = useState(value);
  return <Modal title="本局备忘" onClose={onClose} footer={<SaveButton busy={busy} onClick={() => onSave([{ type: 'memo', value: text }])} />}>
    <textarea className="memo-editor" aria-label="本局备忘内容" value={text} onChange={e => setText(e.target.value)} /></Modal>;
}
function StepBreakdown({ step, nodes, nodeValues, catalog, onClose }) {
  const breakdown = step.scoreBreakdown;
  return <section className="step-breakdown"><div className="section-heading"><h3 title={`(${step.entered})`}>{routeNodeName(step.entered, nodes, catalog.labels.nodeTypes)} · {num(step.weightedValue)} 分</h3><IconButton icon={X} label="关闭步骤得分" onClick={onClose} /></div>
    <div className="step-totals"><span>节点 {num(breakdown?.nodeValue)}</span><span>揭示 {num(breakdown?.revealValue)}</span><span>招募 {num(breakdown?.recruitmentValue)}</span>
      {breakdown?.referenceLossPoints < 0 && <span className="reference-loss-inline">上贡参考 {num(breakdown.referenceLossPoints)}</span>}
      <span>预期现金 {num(step.expectedPrefixCashAfter)}</span><span>预期估价 {num(step.expectedPrefixAppraisalAfter)}</span></div>
    {breakdown?.nodeTerms?.map(row => <ScoreDetails key={row.nodeId} value={stepScoreDetails(row, nodeValues)} catalog={catalog} compact />)}
    {!!breakdown?.revealTerms?.length && <details><summary>揭示得分</summary><pre>{JSON.stringify(breakdown.revealTerms, null, 2)}</pre></details>}
  </section>;
}
