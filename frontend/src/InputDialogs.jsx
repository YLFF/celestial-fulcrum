import React, { useEffect, useState } from 'react';
import { ScanLine, RefreshCw, Monitor, LoaderCircle, Map as MapIcon } from 'lucide-react';
import { api } from './api';
import { readPreference } from './preferences';
import { captureTarget, rememberedCaptureWindow } from './captureTarget';
import { Modal, SaveButton, AssetImage, EntryImage, NumberField } from './common';
import { AREA_NAMES, areaFromObservation } from './model';
import MapView from './MapView';
import { SpecialRegionFields } from './DystopiaEditor';
import { dystopiaFromObservation, emptyDystopia } from './dystopia';
import { recognitionChanges, recognitionReview, mergedRecognitionPreview, mergedResidentMarks, newRecognizedRelics, volatileRecognition } from './recognitionMerge';
import ManualMapDialog from './ManualMapDialog';

const FIELDS = { life: '生命', shield: '护盾', level: '等级', experience: '经验', hope: '希望', originium_ingot: '源石锭', action_points: '行动力' };
const TARGETS = { life: 'life', shield: 'shield', level: 'level', experience: 'experience', hope: 'hope', originium_ingot: 'originiumIngot' };

export function UploadDialog({ file, assetInfo, loaded, catalog, entries, startJob, onConfirm, onManualCreate, onClose, busy, notify, onAsset }) {
  const [asset, setAsset] = useState(assetInfo || null), [area, setArea] = useState(''), [template, setTemplate] = useState('');
  const [working, setWorking] = useState(false), [candidate, setCandidate] = useState(null);
  const [includeRelics, setIncludeRelics] = useState(true), [selectedRelics, setSelectedRelics] = useState({});
  const [manual, setManual] = useState(false);
  const [fields, setFields] = useState({}), [selected, setSelected] = useState({}), [confirmMap, setConfirmMap] = useState(true);
  const [newInstance, setNewInstance] = useState(false), [position, setPosition] = useState(''), [completePosition, setCompletePosition] = useState(false);
  const [nodeChanges, setNodeChanges] = useState({}), [error, setError] = useState('');
  const [markChoices, setMarkChoices] = useState({});
  const [completions, setCompletions] = useState({}), [encounters, setEncounters] = useState({});
  const [resetConfirmed, setResetConfirmed] = useState(false);
  const [dystopia, setDystopia] = useState(emptyDystopia);
  const [utopiaId, setUtopia] = useState(null);
  const [selectedNodes, setSelectedNodes] = useState([]), [batchCategory, setBatchCategory] = useState('');
  useEffect(() => { if (asset) onAsset?.(asset); }, [asset, onAsset]);
  useEffect(() => {
    let live = true;
    if (!file || assetInfo) return () => { live = false; };
    const data = new FormData(); data.append('file', file);
    setWorking(true);
    api('/api/images', { method: 'POST', body: data }).then(value => { if (live) setAsset(value); }).catch(e => { if (live) setError(e.message); }).finally(() => { if (live) setWorking(false); });
    return () => { live = false; };
  }, [file, assetInfo]);
  async function recognize() {
    setWorking(true); setError(''); setCandidate(null); setSelectedRelics({});
    try {
      const job = await startJob('recognize', { assetId: asset.assetId, areaKey: area || null, templateId: template || null, includeResources: true, includeRelics }, loaded);
      const result = job.result, resource = result.resourceObservation?.fields || {};
      setCandidate(job); setFields(structuredClone(resource)); setSelected(Object.fromEntries(Object.entries(resource).map(([id, row]) => [id, ['recognized', 'absent_zero'].includes(row.status)])));
      setSelectedRelics(Object.fromEntries(newRecognizedRelics(result, loaded.state.relics).map(row => [row.id, true])));
      setConfirmMap(result.success); setPosition(result.playerPositionObservation?.nodeId || '');
      setCompletePosition(!!result.playerPositionObservation?.nodeId);
      const chosen = area || areaFromObservation(result), slot = loaded.state.areas[chosen];
      const old = slot?.instances.find(row => row.instanceId === slot.activeInstanceId);
      setNewInstance(false); setResetConfirmed(false);
      setCompletions(Object.fromEntries(recognitionReview(result, old).filter(row => row.reason === 'clearing').map(row => [row.nodeId, true])));
      setEncounters({});
      setDystopia(dystopiaFromObservation(result, old?.templateId === result.templateId ? old.dystopia : null));
      setUtopia(result.layerObservation?.utopiaId || (old?.templateId === result.templateId && !result.dystopiaObservation?.active ? old.utopiaId || null : null));
      setNodeChanges({});
      setMarkChoices(Object.fromEntries(result.nodes.map(row => [row.id, row.marks.map(mark => mark.id)])));
      setSelectedNodes([]);
    } catch (e) { setError(e.message); }
    finally { setWorking(false); }
  }
  async function confirm() {
    const observation = candidate.result, chosen = area || areaFromObservation(observation);
    if (confirmMap && !chosen) { setError('请选择树洞对应的进入层。'); return; }
    if (confirmMap && oldMap && !newInstance && oldMap.templateId !== observation.templateId) { setError('模板与本层记录不同，请核对截图；只有确认换图后才能重新建立本层地图。'); return; }
    if (confirmMap && newInstance && oldMap && !resetConfirmed) { setError('请确认重新建立本层地图。'); return; }
    const values = {}, commands = [];
    for (const [id, row] of Object.entries(fields)) {
      if (!selected[id] || !(TARGETS[id] || id === 'action_points')) continue;
      if ((['life', 'experience'].includes(id) ? [row.current, row.max] : [row.value]).some(value => value == null || !Number.isInteger(value))) { setError('请填写勾选资源的数值，或取消勾选。'); return; }
      if (id === 'action_points') continue;
      values[TARGETS[id]] = ['life', 'experience'].includes(id) ? { current: row.current, max: row.max } : row.value;
    }
    if (Object.keys(values).length) commands.push({ type: 'resources', values });
    if (confirmMap) {
      if (selected.action_points) commands.push({ type: 'actionPoints', areaKey: chosen, value: fields.action_points.value });
      for (const [nodeId, categoryId] of Object.entries(nodeChanges)) if (categoryId) commands.push(categoryId.startsWith('unknown_') ? { type: 'nodeReset', areaKey: chosen, nodeId, categoryId } : { type: 'node', areaKey: chosen, nodeId, changes: { categoryId } });
      for (const row of review) {
        const completed = completions[row.nodeId] || (row.nodeId === position && completePosition);
        if (!completed) continue;
        const categoryId = nodeChanges[row.nodeId] || row.categoryId;
        if (!categoryId || categoryId.startsWith('unknown_')) { setError(`请补充已完成节点 (${row.nodeId}) 的原始类别，不能从空地反推具体事件。`); return; }
        const changes = row.reason === 'resident' ? { completion: 'completed',
          ...(!oldMap?.nodes[row.nodeId]?.completedCategoryId ? { completedCategoryId: 'node_type_021' } : {}) }
          : { categoryId, completion: 'completed' };
        if (categoryId === 'node_type_006' && encounters[row.nodeId]) changes.encounterId = encounters[row.nodeId];
        commands.push({ type: 'node', areaKey: chosen, nodeId: row.nodeId, changes });
      }
      for (const [nodeId, marks] of Object.entries(markChoices)) {
        if (!marks.length || nodeChanges[nodeId]?.startsWith('unknown_')) continue;
        let previous = !newInstance && oldMap?.templateId === observation.templateId ? oldMap.nodes[nodeId] : null;
        if (utopiaId === 'utopia_005' || volatileRecognition(observation, oldMap)) {
          if (previous?.completion === 'completed') continue;
          previous = null;
        }
        const observed = observation.nodes.find(row => row.id === nodeId);
        commands.push({ type: 'node', areaKey: chosen, nodeId, changes: { markIds: mergedResidentMarks(observed, previous, marks) } });
      }
      commands.push({ type: 'dystopia', areaKey: chosen, value: dystopia });
      commands.push({ type: 'utopia', areaKey: chosen, value: utopiaId });
      if (position) commands.push({ type: 'position', areaKey: chosen, value: position });
      if (position && completePosition) commands.push({ type: 'node', areaKey: chosen, nodeId: position, changes: { completion: 'completed' } });
    } else if (selected.action_points && chosen && loaded.state.areas[chosen]?.activeInstanceId) commands.push({ type: 'actionPoints', areaKey: chosen, value: fields.action_points.value });
    const freshI = chosen === 'I' && loaded.state.areas.I.instances.length === 0 && position === '0,0' && !loaded.state.currentAreaKey;
    // Opening AP follows the confirmed opening preset, even if the screenshot is a simulation.
    const filtered = freshI ? commands.filter(row => row.type !== 'actionPoints') : commands;
    await onConfirm({ expectedRevision: candidate.sourceRevision, jobId: candidate.jobId, areaKey: chosen, confirmMap,
      resourceFields: [], newInstance, initialAreaEntry: freshI && confirmMap, commands: filtered,
      relicIds: relicCandidates.filter(row => selectedRelics[row.id]).map(row => row.id) });
  }
  const observation = candidate?.result;
  const relicCandidates = newRecognizedRelics(observation, loaded.state.relics);
  const chosenArea = area || (observation && areaFromObservation(observation));
  const slot = loaded.state.areas[chosenArea], oldMap = slot?.instances.find(row => row.instanceId === slot.activeInstanceId);
  const reviewObservation = observation && { ...observation, layerObservation: { ...observation.layerObservation, utopiaId } };
  const review = recognitionReview(reviewObservation && { ...reviewObservation, playerPositionObservation: { nodeId: position } }, oldMap, newInstance);
  const previewMap = mergedRecognitionPreview(observation, oldMap, { newInstance, position, completePosition,
    nodeChanges, completions, encounters, markChoices, dystopia, utopiaId });
  const changes = recognitionChanges(reviewObservation, oldMap, newInstance);
  if (manual) return <ManualMapDialog loaded={loaded} catalog={catalog} entries={entries}
    initialArea={chosenArea || area} asset={asset} busy={busy} onCreate={onManualCreate} onClose={() => setManual(false)} />;
  return <Modal title={candidate ? '确认识别结果' : '导入截图'} onClose={onClose} dismissOutside={!candidate} wide footer={candidate ?
    <><button onClick={recognize} disabled={working}><RefreshCw size={15} />重新识别</button><SaveButton busy={busy || working} onClick={confirm}>确认入局</SaveButton></> :
    <SaveButton busy={working} onClick={recognize} disabled={working || !asset}><ScanLine size={16} />开始识别</SaveButton>}>
    <div className="upload-config form-grid"><label className="field"><span>识别区域</span><select aria-label="识别区域" disabled={working || busy} value={area} onChange={e => {
      const next = e.target.value;
      setArea(next);
      if (observation?.success && observation.area === 'treehole' && observation.floor == null && next.endsWith('-treehole')) {
        setCompletions({}); setEncounters({}); setNodeChanges({}); setNewInstance(false); setResetConfirmed(false);
        const target = loaded.state.areas[next];
        const old = target?.instances.find(row => row.instanceId === target.activeInstanceId);
        setUtopia(observation.layerObservation?.utopiaId || old?.utopiaId || null);
        setDystopia(dystopiaFromObservation(observation, old?.templateId === observation.templateId ? old.dystopia : null));
      } else setCandidate(null);
    }}>
      <option value="">自动判层</option>{Object.entries(AREA_NAMES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <label className="field"><span>指定模板 ID（可选）</span><input value={template} onChange={e => { setTemplate(e.target.value); setCandidate(null); }} /></label>
      <label className="checkbox-field"><input type="checkbox" checked={includeRelics} disabled={working || busy}
        onChange={e => { setIncludeRelics(e.target.checked); setCandidate(null); }} />同步识别左下角藏品</label></div>
    {error && <div role="alert" className="form-error">{error}</div>}
    {(error || (observation && !observation.success)) && <div className="manual-map-fallback">
      <button onClick={() => setManual(true)} disabled={busy || working}><MapIcon size={16} />选择层数与模板，手动建图</button>
    </div>}
    {asset && (candidate ? <details><summary>原始截图</summary><div className="recognition-preview"><AssetImage assetId={asset.assetId} className="screenshot-preview" /></div></details> : <div className="recognition-preview"><AssetImage assetId={asset.assetId} className="screenshot-preview" /></div>)}
    {working && <div className="pending"><LoaderCircle size={18} className="spin" />识别任务进行中</div>}
    {observation && <>
      <div className="recognition-summary"><b>{observation.success ? observation.templateId : '地图未匹配'}</b><span>{observation.nodes?.length || 0} 个节点</span>
        {observation.matchQuality && <span>匹配 {Math.round(observation.matchQuality.score * 100)}% · 覆盖 {Math.round(observation.matchQuality.coverage * 100)}%</span>}
        <div className="segmented"><button disabled={!observation.success} className={confirmMap ? 'active' : ''} onClick={() => setConfirmMap(true)}>更新地图和资源</button><button className={!confirmMap ? 'active' : ''} onClick={() => setConfirmMap(false)}>只更新资源</button></div>
        {confirmMap && oldMap && <select aria-label="地图更新方式" value={newInstance ? 'new' : 'merge'} onChange={e => {
          const fresh = e.target.value === 'new'; setNewInstance(fresh); setResetConfirmed(false);
          setCompletions(Object.fromEntries(recognitionReview(observation, oldMap, fresh).filter(row => row.reason === 'clearing').map(row => [row.nodeId, true])));
          setEncounters({}); setDystopia(dystopiaFromObservation(observation, fresh ? null : oldMap.dystopia));
          setUtopia(observation.layerObservation?.utopiaId || (fresh || observation.dystopiaObservation?.active ? null : oldMap.utopiaId || null));
        }}>
          <option value="merge">合并本层地图（保留已确认信息）</option><option value="new">重新建立本层地图</option></select>}</div>
      {confirmMap && newInstance && oldMap && <label className="checkbox-field form-error"><input type="checkbox" checked={resetConfirmed} onChange={e => setResetConfirmed(e.target.checked)} />确认换图：本次不沿用旧节点记录，旧实例仍保留</label>}
      {confirmMap && !newInstance && oldMap && oldMap.templateId !== observation.templateId && <div className="form-error">模板与本层记录不同，不能直接合并。请核对截图或明确选择重新建立。</div>}
      {confirmMap && oldMap?.templateId === observation.templateId && !newInstance && <section className="merge-summary">
        <h3>本层合并预览</h3><p>{volatileRecognition(reviewObservation, oldMap) ? '全知者盲区：只保留已完成节点，其余节点以本次截图替换。' : '保留原节点类别、事件与结局标记；流窜居民位置以新截图更新。'}</p>
        {changes.map(row => <div key={`${row.nodeId}-${row.kind}`} className={row.kind === 'conflict' ? 'negative' : ''}>
          ({row.nodeId}) · {row.kind === 'completion' ? `可能已完成：${catalog.labels.nodeTypes[row.before] || '原类别待补充'}` :
            row.kind === 'residentArrival' ? '新出现流窜居民（原节点记录保留）' : row.kind === 'residentDeparture' ? '流窜居民已不在此处（移动或清理）' :
            row.kind === 'reveal' ? `新探明：${catalog.labels.nodeTypes[row.after]}` : `类别冲突：${catalog.labels.nodeTypes[row.before]} / ${catalog.labels.nodeTypes[row.after]}，请修正节点`}</div>)}
        {!changes.length && <span className="quiet">未发现新增类别或完成候选；仍可确认位置与资源更新。</span>}
      </section>}
      {confirmMap && !!review.length && <section className="merge-review"><h3>完成节点确认</h3>{review.map(row => {
        const categoryId = nodeChanges[row.nodeId] || row.categoryId;
        const done = !!completions[row.nodeId] || (row.nodeId === position && completePosition);
        return <div className="merge-review-row" key={row.nodeId}><label className="checkbox-field"><input type="checkbox" aria-label={`确认完成 ${row.nodeId}`} checked={done}
          onChange={e => { setCompletions({ ...completions, [row.nodeId]: e.target.checked }); if (row.nodeId === position) setCompletePosition(e.target.checked); }} />
          完成了 ({row.nodeId}) 的{catalog.labels.nodeTypes[categoryId] || '未知节点'}</label>
          {row.reason === 'clearing' && <small>截图已变为空地，保留原类别</small>}
          {!categoryId && <select aria-label={`补充原类别 ${row.nodeId}`} value={nodeChanges[row.nodeId] || ''} onChange={e => setNodeChanges({ ...nodeChanges, [row.nodeId]: e.target.value })}>
            <option value="">请补充原类别</option>{Object.entries(catalog.labels.nodeTypes).filter(([id]) => id.startsWith('node_type_')).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select>}
          {categoryId === 'node_type_006' && !row.encounterId && <select aria-label={`补充事件 ${row.nodeId}`} value={encounters[row.nodeId] || ''} onChange={e => setEncounters({ ...encounters, [row.nodeId]: e.target.value })}>
            <option value="">请补充事件（也可稍后补充）</option>{catalog.encounters.map(event => <option key={event.id} value={event.id}>{event.name}</option>)}</select>}
        </div>;
      })}</section>}
      {!!relicCandidates.length && <section className="synced-relic-candidates" aria-label="新识别藏品"><h3>新识别藏品</h3>
        <div className="synced-relic-list">{relicCandidates.map(row => <label key={row.id}>
          <input type="checkbox" aria-label={`添加 ${row.name}`} checked={!!selectedRelics[row.id]} disabled={busy || working}
            onChange={e => setSelectedRelics(old => ({ ...old, [row.id]: e.target.checked }))} />
          <EntryImage entry={entries[row.id]} /><span>{row.name}</span>
        </label>)}</div></section>}
      {previewMap && <><MapView preview instance={previewMap} catalog={catalog} entries={entries} busy={busy} selectedIds={selectedNodes} onSelectionChange={setSelectedNodes} />
        <div className="map-review-toolbar"><span>已选 {selectedNodes.length} 个节点</span><select aria-label="批量修正节点类别" value={batchCategory} onChange={e => setBatchCategory(e.target.value)}><option value="">节点类别</option>
          {Object.entries(catalog.labels.nodeTypes).filter(([id]) => id !== 'start' && id !== 'node_type_021').map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select>
          <button disabled={!batchCategory || !selectedNodes.some(id => id !== '0,0')} onClick={() => setNodeChanges({ ...nodeChanges, ...Object.fromEntries(selectedNodes.filter(id => id !== '0,0').map(id => [id, batchCategory])) })}>修正所选节点</button><button onClick={() => setSelectedNodes([])} disabled={!selectedNodes.length}>取消选择</button></div></>}
      {previewMap && confirmMap && <SpecialRegionFields areaKey={chosenArea} utopiaId={utopiaId} onUtopiaChange={value => { setUtopia(value); if (value === 'utopia_005') setCompletions({}); }}
        value={dystopia} onChange={setDystopia} nodes={previewMap.nodes} catalog={catalog} selectedIds={selectedNodes} />}
      <h3>资源候选</h3><div className="resource-candidates">{Object.entries(fields).filter(([id]) => FIELDS[id]).map(([id, row]) => <div key={id}>
        <label className="checkbox-field"><input type="checkbox" checked={!!selected[id]} onChange={e => setSelected({ ...selected, [id]: e.target.checked })} />{FIELDS[id]}</label>
        <span className={`candidate-status ${row.status === 'needs_review' ? 'review' : ''}`}>{['recognized', 'absent_zero'].includes(row.status) ? '识别' : '待确认'}</span>
        {['life', 'experience'].includes(id) ? <div className="paired-numbers"><input aria-label={`${FIELDS[id]}当前候选`} type="number" min={0} value={row.current ?? ''}
          onChange={e => setFields({ ...fields, [id]: { ...row, current: Number(e.target.value) } })} /><span>/</span><input aria-label={`${FIELDS[id]}上限候选`} type="number" min={0} value={row.max ?? ''}
            onChange={e => setFields({ ...fields, [id]: { ...row, max: Number(e.target.value) } })} /></div> : <input aria-label={`${FIELDS[id]}候选`} type="number" min={0} value={row.value ?? ''}
              onChange={e => setFields({ ...fields, [id]: { ...row, value: Number(e.target.value) } })} />}
      </div>)}</div>
      {confirmMap && <><div className="form-grid"><label className="field"><span>玩家位置</span><select aria-label="玩家位置" value={position} onChange={e => { setPosition(e.target.value); setCompletePosition(!!e.target.value); }}><option value="">不更新位置</option>
        {observation.nodes.map(n => <option value={n.id} key={n.id}>({n.id}) · {catalog.labels.nodeTypes[n.categoryId] || '未知'}</option>)}</select></label>
        <label className="checkbox-field"><input type="checkbox" checked={completePosition} onChange={e => setCompletePosition(e.target.checked)} />当前位置已完成</label></div>
        <details><summary>节点候选与修正</summary><div className="node-review-list">{observation.nodes.map(n => <div key={n.id}><b>({n.id})</b>
          <span>{catalog.labels.nodeTypes[n.categoryId] || '待确认'}</span><select aria-label={`修正节点 ${n.id}`} value={nodeChanges[n.id] || ''} onChange={e => setNodeChanges({ ...nodeChanges, [n.id]: e.target.value })}>
            <option value="">保留候选</option>{Object.entries(catalog.labels.nodeTypes).filter(([id]) => id !== 'start' && id !== 'node_type_021').map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></div>)}</div></details>
        {observation.nodes.some(row => row.marks.length) && <details><summary>节点标记候选</summary><div className="mark-review-list">
          {observation.nodes.filter(row => row.marks.length).map(row => <div className="mark-review-row" key={row.id}><b>({row.id})</b>
            {row.marks.map(mark => <label className="checkbox-field" key={mark.id}><input type="checkbox" aria-label={`节点 ${row.id} ${catalog.labels.nodeMarks[mark.id]}`}
              checked={markChoices[row.id]?.includes(mark.id) || false} onChange={e => setMarkChoices({ ...markChoices,
                [row.id]: e.target.checked ? [...new Set([...(markChoices[row.id] || []), mark.id])] : (markChoices[row.id] || []).filter(id => id !== mark.id) })} />
              {catalog.labels.nodeMarks[mark.id]}</label>)}</div>)}
        </div></details>}</>}
      {!!observation.warnings?.length && <details className="score-warnings"><summary>{observation.warnings.length} 项识别提示</summary><ul>{observation.warnings.map((text, i) => <li key={i}>{text}</li>)}</ul></details>}
    </>}
  </Modal>;
}

export function CaptureDialog({ onClose, onCaptured, notify }) {
  const [windows, setWindows] = useState([]), [selected, setSelected] = useState(''), [method, setMethod] = useState('graphics');
  const [consent, setConsent] = useState(() => readPreference('fulcrum-capture-consent') === 'true'), [crop, setCrop] = useState(false), [rect, setRect] = useState([0, 0, 1920, 1080]);
  const [working, setWorking] = useState(false), [error, setError] = useState('');
  async function refresh() {
    try {
      const data = await api('/api/capture/windows');
      const rows = data.windows.sort((a, b) => Number(b.foreground) - Number(a.foreground));
      setWindows(rows);
      let saved;
      try { saved = JSON.parse(readPreference('fulcrum-capture-target')); } catch { saved = null; }
      const target = rows.find(row => row.windowId === selected && !row.minimized) || rememberedCaptureWindow(rows, saved);
      setSelected(target?.windowId || '');
      if (target) setRect([0, 0, target.clientRect.width, target.clientRect.height]);
    }
    catch (e) { setError(e.message); }
  }
  useEffect(() => { refresh(); }, []);
  async function capture() {
    const target = windows.find(w => w.windowId === selected);
    if (!target) return;
    setWorking(true); setError(''); let grant;
    try { localStorage.setItem('fulcrum-capture-target', JSON.stringify(captureTarget(target))); } catch { /* Capture also works without preference storage. */ }
    try {
      grant = await api('/api/capture/authorize', { method: 'POST', body: { pid: target.pid, windowId: target.windowId, consent } });
      const asset = await api('/api/capture', { method: 'POST', body: { pid: target.pid, windowId: target.windowId, authorizationId: grant.authorizationId, method, crop: crop ? rect : null } });
      onCaptured(asset);
    } catch (e) { setError(e.message); }
    finally { if (grant) await api('/api/capture/revoke', { method: 'POST', body: { authorizationId: grant.authorizationId } }).catch(() => {}); setWorking(false); }
  }
  return <Modal title="选择窗口截图" onClose={onClose} footer={<SaveButton busy={working} disabled={working || !selected || !consent} onClick={capture}><Monitor size={15} />授权并截取</SaveButton>}>
    <div className="section-heading"><h3>可见窗口</h3><button onClick={refresh}><RefreshCw size={15} />刷新</button></div>
    <label className="field"><span>目标进程 / 窗口</span><select aria-label="目标进程 / 窗口" value={selected} onChange={e => {
      setSelected(e.target.value); const row = windows.find(w => w.windowId === e.target.value);
      if (row) setRect([0, 0, row.clientRect.width, row.clientRect.height]);
    }}><option value="">选择窗口</option>{windows.map(w => <option key={w.windowId} value={w.windowId} disabled={w.minimized}>
      {w.foreground ? '前台 · ' : ''}{w.process || w.pid} · {w.title}{w.minimized ? '（最小化）' : ''}</option>)}</select></label>
    <label className="field"><span>截取方式</span><select aria-label="截取方式" value={method} onChange={e => setMethod(e.target.value)}>
      <option value="graphics">窗口内容 · Windows Graphics Capture</option><option value="printwindow">窗口内容 · PrintWindow</option><option value="screen">屏幕区域 · 可能包含遮挡</option></select></label>
    <label className="checkbox-field"><input type="checkbox" checked={crop} onChange={e => setCrop(e.target.checked)} />裁剪客户区</label>
    {crop && <div className="form-grid">{['X', 'Y', '宽度', '高度'].map((label, index) => <NumberField key={label} label={label} value={rect[index]} min={index < 2 ? 0 : 1} onChange={value => setRect(rect.map((x, i) => i === index ? value : x))} />)}</div>}
    <label className="checkbox-field consent"><input type="checkbox" checked={consent} onChange={e => {
      setConsent(e.target.checked);
      try { localStorage.setItem('fulcrum-capture-consent', String(e.target.checked)); } catch { /* Keep consent for this dialog if storage is unavailable. */ }
    }} />允许截取所选窗口</label>
    {error && <div role="alert" className="form-error">{error}</div>}
  </Modal>;
}
