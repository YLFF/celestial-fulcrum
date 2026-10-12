import React, { useEffect, useState } from 'react';
import { Map as MapIcon, ArrowLeft, RefreshCw, ChevronLeft, ChevronRight } from 'lucide-react';
import { api } from './api';
import { IconButton, Modal, NumberField, SaveButton } from './common';
import { AREA_NAMES } from './model';
import MapView from './MapView';

export default function ManualMapDialog({ loaded, catalog, entries, initialArea, asset, busy, onCreate, onClose }) {
  const [area, setArea] = useState(initialArea || loaded.state.currentAreaKey || 'I');
  const [templates, setTemplates] = useState([]), [templateId, setTemplateId] = useState('');
  const [working, setWorking] = useState(false), [error, setError] = useState('');
  const [replacement, setReplacement] = useState(false), [actionPoints, setActionPoints] = useState(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true;
    setWorking(true); setError(''); setTemplates([]); setTemplateId(''); setReplacement(false);
    api(`/api/map-templates?areaKey=${encodeURIComponent(area)}`).then(value => {
      if (live) { setTemplates(value.templates); setTemplateId(value.templates[0]?.id || ''); }
    }).catch(e => { if (live) setError(e.message); }).finally(() => { if (live) setWorking(false); });
    return () => { live = false; };
  }, [area, retry]);
  const selected = templates.find(row => row.id === templateId);
  const templateIndex = templates.findIndex(row => row.id === templateId);
  const oldMap = loaded.state.areas[area]?.activeInstanceId;
  const validPoints = actionPoints == null || (Number.isSafeInteger(actionPoints) && actionPoints >= 0);
  async function create() {
    if (!selected || !validPoints || (oldMap && !replacement)) return;
    try {
      await onCreate({ expectedRevision: loaded.revision, areaKey: area, templateId,
        replaceExisting: !!oldMap && replacement, actionPoints, assetId: asset?.assetId || null });
    } catch (e) { setError(e.message); }
  }
  return <Modal title="按模板手动建图" wide onClose={onClose} footer={<>
    <button onClick={onClose} disabled={busy}><ArrowLeft size={15} />返回识别结果</button>
    <SaveButton busy={busy || working} disabled={busy || working || !selected || !validPoints || (!!oldMap && !replacement)} onClick={create}>
      <MapIcon size={16} />创建可编辑地图
    </SaveButton>
  </>}>
    <div className="form-grid">
      <label className="field"><span>地图层数</span><select aria-label="手动建图层数" value={area} disabled={busy}
        onChange={e => { setArea(e.target.value); setActionPoints(null); }}>
        {Object.entries(AREA_NAMES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select></label>
      <div className="field"><span>地图模板</span><div className="template-navigation">
        <IconButton icon={ChevronLeft} label="上一个地图模板" disabled={busy || working || templateIndex <= 0} onClick={() => setTemplateId(templates[templateIndex - 1].id)} />
        <select aria-label="手动建图模板" value={templateId} disabled={busy || working}
        onChange={e => setTemplateId(e.target.value)}>
        {!templates.length && <option value="">{working ? '正在读取模板' : '暂无模板'}</option>}
        {templates.map(row => <option key={row.id} value={row.id}>模板 {row.number} · {row.gridShape.join(' × ')} · {row.nodeCount} 节点 · {row.terminalCount} 出口</option>)}
      </select><IconButton icon={ChevronRight} label="下一个地图模板" disabled={busy || working || templateIndex < 0 || templateIndex >= templates.length - 1} onClick={() => setTemplateId(templates[templateIndex + 1].id)} />
      </div></div>
      <NumberField label="本层行动力（可稍后补充）" aria-label="手动建图行动力" nullable value={actionPoints}
        onChange={setActionPoints} disabled={busy} />
    </div>
    {error && <div role="alert" className="form-error">{error}<button onClick={() => setRetry(retry + 1)} disabled={busy || working}><RefreshCw size={15} />重新读取模板</button></div>}
    {!validPoints && <p className="form-error" role="alert">行动力须为不小于0的整数。</p>}
    {oldMap && <label className="checkbox-field consent"><input type="checkbox" checked={replacement} disabled={busy}
      onChange={e => setReplacement(e.target.checked)} />确认重新建立本层地图，旧实例保留</label>}
    {selected && <MapView preview instance={selected.preview} catalog={catalog} entries={entries} busy={busy} />}
  </Modal>;
}
