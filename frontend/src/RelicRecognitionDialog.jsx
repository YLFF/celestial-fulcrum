import React, { useRef, useState } from 'react';
import { ImagePlus, ScanLine, LoaderCircle, Check, AlertTriangle } from 'lucide-react';
import { api, imageURL } from './api';
import { EntryImage, Modal, SaveButton } from './common';

async function crops(asset, result) {
  const img = new Image();
  img.src = await imageURL(`/api/images/${asset.assetId}`);
  await img.decode();
  function crop(box) {
    const [x0, y0, x1, y1] = box;
    const canvas = document.createElement('canvas');
    canvas.width = x1-x0; canvas.height = y1-y0;
    canvas.getContext('2d').drawImage(img, x0, y0, x1-x0, y1-y0, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL();
  }
  return { row: crop(result.rowBox), items: result.slots.map(slot => crop(slot.box)) };
}

export default function RelicRecognitionDialog({ loaded, entries, startJob, onConfirm, onClose, busy, notify, assetInfo, onAsset }) {
  const [asset, setAsset] = useState(assetInfo || null), [working, setWorking] = useState(false);
  const [job, setJob] = useState(null), [preview, setPreview] = useState(null), [selected, setSelected] = useState({});
  const input = useRef(null), generation = useRef(0);
  const held = new Set(loaded.state.relics.map(row => row.id));
  const chosen = [...new Set(Object.values(selected).filter(id => id && !held.has(id)))];
  const locked = working || busy;
  async function upload(file) {
    if (!file || locked) return;
    const version = ++generation.current;
    setWorking(true); setJob(null); setPreview(null); setSelected({});
    try {
      const form = new FormData(); form.append('file', file);
      const info = await api('/api/images', { method: 'POST', body: form });
      if (version === generation.current) { setAsset(info); onAsset(info); }
    } catch (error) { notify(error.message, true); }
    finally { if (version === generation.current) setWorking(false); }
  }
  async function recognize() {
    setWorking(true); setJob(null); setPreview(null); setSelected({});
    try {
      const value = await startJob('recognize-relics', { assetId: asset.assetId }, loaded);
      setJob(value);
      if (value.result.success) {
        setPreview(await crops(asset, value.result));
        setSelected(Object.fromEntries(value.result.slots.map(row => [row.slot, row.status === 'accepted' && !held.has(row.id) ? row.id : ''])));
      }
    } catch (error) { notify(error.message, true); }
    finally { setWorking(false); }
  }
  return <Modal title="识别藏品" wide onClose={onClose} footer={<SaveButton busy={busy} disabled={locked || !job || !chosen.length}
    onClick={() => onConfirm({ expectedRevision: loaded.revision, jobId: job.jobId, relicIds: chosen })}>添加 {chosen.length} 件藏品</SaveButton>}>
    <div className="relic-scan-surface" onDragOver={event => { event.preventDefault(); event.stopPropagation(); }}
      onDrop={event => { event.preventDefault(); event.stopPropagation(); upload(event.dataTransfer.files[0]); }}>
    <div className="relic-scan-toolbar">
      <input ref={input} type="file" accept="image/*" aria-label="藏品截图" hidden onChange={event => { upload(event.target.files[0]); event.target.value = ''; }} />
      <button disabled={locked} onClick={() => input.current.click()}><ImagePlus size={16} />选择 / 拖入截图</button>
      <span>{asset ? `${asset.width} × ${asset.height}` : '未选择截图'}</span>
    </div>
    <div className="relic-scan-actions"><button className="primary" disabled={!asset || locked} onClick={recognize}>{working ? <LoaderCircle size={16} className="spin" /> : <ScanLine size={16} />}识别最新截图藏品栏</button>
      <small className="quiet">默认使用最近导入或截取的图片；也可选择、拖入新的截图。</small></div>
    {job?.result && !job.result.success && <p className="negative" role="alert">{job.result.reason}</p>}
    {preview && <figure className="relic-row-preview"><img src={preview.row} alt="检测到的收藏品栏" /><figcaption>可见 {job.result.slots.length} 件 · {job.elapsedSeconds} 秒</figcaption></figure>}
    {job?.result.success && <div className="relic-scan-results">{job.result.slots.map((slot, index) => {
      const duplicate = held.has(slot.id);
      return <div className={`relic-scan-result ${slot.status === 'needs_review' ? 'review' : ''}`} key={slot.slot} data-relic-slot={slot.slot}>
        <b className="relic-slot-number">{slot.slot}</b>
        {preview && <img className="relic-detected-icon" src={preview.items[index]} alt={`截图藏品 ${slot.slot}`} />}
        <EntryImage entry={entries[slot.id]} className="relic-matched-icon" />
        <div className="relic-match-info"><b>{slot.name}</b><small>相似度 {(slot.score*100).toFixed(1)}% · 候选差 {(slot.margin*100).toFixed(1)}%</small>
          <span>{duplicate ? <><Check size={12} />已持有，不重复添加</> : slot.status === 'accepted' ? <><Check size={12} />匹配通过</> : <><AlertTriangle size={12} />{slot.partial ? '图标不完整，待确认' : '相似候选，待确认'}</>}</span></div>
        <label className="relic-match-choice"><select aria-label={`第${slot.slot}件藏品`} value={selected[slot.slot] || ''} disabled={locked}
          onChange={event => setSelected(old => ({ ...old, [slot.slot]: event.target.value }))}>
          <option value="">不添加</option>{slot.candidates.map(candidate => <option key={candidate.id} value={candidate.id} disabled={held.has(candidate.id)}>
            {candidate.name} · {(candidate.score*100).toFixed(1)}%{held.has(candidate.id) ? ' · 已持有' : ''}</option>)}
        </select></label>
      </div>;
    })}</div>}
    </div>
  </Modal>;
}
