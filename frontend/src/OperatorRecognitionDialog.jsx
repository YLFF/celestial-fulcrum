import React, { useRef, useState } from 'react';
import { ImagePlus, Monitor, ScanLine, LoaderCircle } from 'lucide-react';
import { api, imageURL } from './api';
import { Modal, SaveButton } from './common';
import { CaptureDialog } from './InputDialogs';

export const CHANGE_LABELS = { add: '新增', promote: '更新为已进阶', update: '补齐未进阶状态', unchanged: '状态一致', downgrade: '进阶状态冲突，请手动核对', ambiguous: '选择已有记录' };

async function cardPreviews(asset, slots) {
  const img = new Image(); img.src = await imageURL(`/api/images/${asset.assetId}`); await img.decode();
  return Object.fromEntries(slots.map(slot => {
    const [x0, y0, x1, y1] = slot.box, canvas = document.createElement('canvas');
    canvas.width = x1 - x0; canvas.height = y1 - y0;
    canvas.getContext('2d').drawImage(img, x0, y0, canvas.width, canvas.height, 0, 0, canvas.width, canvas.height);
    return [slot.slot, canvas.toDataURL()];
  }));
}

export default function OperatorRecognitionDialog({ loaded, startJob, onConfirm, onClose, busy, notify, captureAvailable, onAsset }) {
  const [asset, setAsset] = useState(null), [working, setWorking] = useState(false), [capture, setCapture] = useState(false);
  const [job, setJob] = useState(null), [previews, setPreviews] = useState({}), [selected, setSelected] = useState({}), [targets, setTargets] = useState({});
  const input = useRef(null), generation = useRef(0);
  const locked = busy || working;
  const changes = job?.result?.changes || [];
  const chosen = changes.filter(row => selected[row.slot] && row.change !== 'downgrade' && row.change !== 'unchanged'
    && (row.change !== 'ambiguous' || targets[row.slot])).map(row => ({ slot: row.slot, instanceId: targets[row.slot] || row.instanceId || null }));
  async function upload(file) {
    if (!file || locked) return;
    const version = ++generation.current;
    setWorking(true); setJob(null); setSelected({}); setPreviews({});
    try {
      const form = new FormData(); form.append('file', file);
      const info = await api('/api/images', { method: 'POST', body: form });
      if (version === generation.current) { setAsset(info); onAsset(info); }
    } catch (error) { notify(error.message, true); }
    finally { if (version === generation.current) setWorking(false); }
  }
  async function recognize(info = asset) {
    if (!info) return;
    setWorking(true); setJob(null); setSelected({}); setTargets({}); setPreviews({});
    try {
      const value = await startJob('recognize-operators', { assetId: info.assetId }, loaded);
      setJob(value);
      if (value.result.success) {
        setSelected(Object.fromEntries(value.result.changes.map(row => [row.slot, row.selected])));
        setPreviews(await cardPreviews(info, value.result.slots));
      }
    } catch (error) { notify(error.message, true); }
    finally { setWorking(false); }
  }
  if (capture) return <CaptureDialog notify={notify} onClose={() => setCapture(false)} onCaptured={info => {
    setCapture(false); setAsset(info); onAsset(info); recognize(info);
  }} />;
  return <Modal title="识别编队页面干员" wide onClose={onClose} footer={<SaveButton busy={busy} disabled={locked || !chosen.length}
    onClick={() => onConfirm({ expectedRevision: loaded.revision, jobId: job.jobId, choices: chosen })}>确认更新 {chosen.length} 名干员</SaveButton>}>
    <div className="relic-scan-surface" onDragOver={event => { event.preventDefault(); event.stopPropagation(); }}
      onDrop={event => { event.preventDefault(); event.stopPropagation(); upload(event.dataTransfer.files[0]); }}>
      <div className="relic-scan-toolbar">
        <input ref={input} type="file" accept="image/*" aria-label="编队截图" hidden onChange={event => { upload(event.target.files[0]); event.target.value = ''; }} />
        <button disabled={locked} onClick={() => input.current.click()}><ImagePlus size={16} />选择 / 拖入截图</button>
        <span>{asset ? `${asset.width} × ${asset.height}` : '未选择截图'}</span>
      </div>
      <div className="relic-scan-actions">
        <button className="primary" disabled={locked || !captureAvailable} onClick={() => setCapture(true)}><Monitor size={16} />识别编队页面干员</button>
        <button disabled={locked || !asset} onClick={() => recognize()}>{working ? <LoaderCircle size={16} className="spin" /> : <ScanLine size={16} />}识别所选截图</button>
      </div>
      {job?.result && !job.result.success && <p className="negative" role="alert">{job.result.reason}</p>}
      {job?.result.success && <>
        <div className="operator-scan-summary" role="status">{changes.length} 名干员匹配 · {job.result.slots.length - changes.length} 名未匹配 · {job.elapsedSeconds} 秒</div>
        <div className="operator-scan-results">{job.result.slots.map(slot => {
          const row = changes.find(row => row.slot === slot.slot), actionable = row && !['unchanged', 'downgrade'].includes(row.change);
          return <div className={`operator-scan-row ${slot.status === 'needs_review' ? 'review' : ''}`} key={slot.slot}>
            {previews[slot.slot] && <img src={previews[slot.slot]} alt={`第${slot.column}列第${slot.row}行干员`} />}
            <div><b>{slot.name || slot.text || '未识别名字'}</b><small>{row ? `${slot.elite === 2 ? '已进阶' : '未进阶'} · ${CHANGE_LABELS[row.change]}` : '未匹配干员库，忽略'}
              {slot.status === 'needs_review' && ' · 识别待核对'}</small>
              {row?.change === 'ambiguous' && <select aria-label={`${slot.name}已有记录`} value={targets[slot.slot] || ''} disabled={locked}
                onChange={event => setTargets(old => ({ ...old, [slot.slot]: event.target.value }))}>
                <option value="">选择记录</option>{row.targets.map(target => <option key={target.instanceId} value={target.instanceId}>{target.instanceId} · {target.source}</option>)}
              </select>}
            </div>
            <label className="checkbox-field"><input type="checkbox" aria-label={`确认${slot.name || slot.text}`} disabled={locked || !actionable}
              checked={!!selected[slot.slot] && !!actionable} onChange={event => setSelected(old => ({ ...old, [slot.slot]: event.target.checked }))} />更新</label>
          </div>;
        })}</div>
      </>}
    </div>
  </Modal>;
}
