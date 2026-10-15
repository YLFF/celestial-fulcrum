import React, { useEffect, useRef, useState } from 'react';
import { Download, RefreshCw, RotateCw, LoaderCircle } from 'lucide-react';
import { api } from './api';
import { Modal } from './common';

const STATUS = { idle: '尚未检查', checking: '正在检查正式发行版', upToDate: '当前已是最新正式版本', available: '发现新版本',
  downloading: '正在下载并校验发行包', ready: '发行包已校验，可安装', installing: '即将关闭并重启更新', error: '更新未完成' };
export default function AppUpdateDialog({ onClose, notify }) {
  const [state, setState] = useState(null), [busy, setBusy] = useState(false), [confirm, setConfirm] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    async function refresh() {
      try { const value = await api('/api/app-updates'); if (alive.current) setState(value); }
      catch (error) { if (alive.current) notify(error.message, true); }
    }
    refresh(); const timer = setInterval(refresh, 1500);
    return () => { alive.current = false; clearInterval(timer); };
  }, []);
  async function action(value) {
    setBusy(true); setConfirm(false);
    try { const next = await api('/api/app-updates', { method: 'POST', body: { action: value } }); if (alive.current) setState(next); }
    catch (error) { notify(error.message, true); }
    finally { if (alive.current) setBusy(false); }
  }
  const locked = busy || ['checking', 'downloading', 'installing'].includes(state?.status);
  return <Modal title="应用更新" onClose={onClose} footer={<>
    <button disabled={locked} onClick={() => action('check')}><RefreshCw size={16} />检查更新</button>
    {state?.status === 'available' && <button className="primary" disabled={locked} onClick={() => action('download')}><Download size={16} />下载更新</button>}
    {state?.status === 'ready' && state.canInstall && <button className="primary" disabled={locked} onClick={() => setConfirm(true)}><RotateCw size={16} />重启并更新</button>}
  </>}>
    {state && <div className="app-update-content">
      <p>当前版本 <b>{state.currentVersion}</b>{state.release && <> · 最新版本 <b>{state.release.version}</b></>}</p>
      <div className="app-update-status" role="status">{locked && <LoaderCircle size={16} className="spin" />}{STATUS[state.status]}</div>
      {state.error && <p className="negative" role="alert">{state.error}</p>}
      {state.status === 'downloading' && <><progress aria-label="更新下载进度" max={state.release?.size || 1} value={state.downloadedBytes || 0} />
        <small>{((state.downloadedBytes || 0) / 1048576).toFixed(1)} / {((state.release?.size || 0) / 1048576).toFixed(1)} MB</small></>}
      {state.release?.notes && <pre className="release-notes">{state.release.notes}</pre>}
      {state.status === 'ready' && !state.canInstall && <p className="quiet">开发页面不替换本地程序，请从发行页手动安装。</p>}
      <a href={state.releasePage} target="_blank" rel="noreferrer">GitHub 发行页</a>
      {confirm && <div className="app-update-confirm"><b>现在关闭程序并安装更新？</b><p>存档保留。新包自检失败将恢复旧版程序；旧程序备份也会保留。</p>
        <button onClick={() => setConfirm(false)}>取消</button><button className="primary" onClick={() => action('install')}>确认重启更新</button></div>}
    </div>}
  </Modal>;
}
