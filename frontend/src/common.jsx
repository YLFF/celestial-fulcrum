import React, { useEffect, useState } from 'react';
import { X, CircleHelp, LoaderCircle } from 'lucide-react';
import { imageURL } from './api';

export function IconButton({ icon: Icon, label, onClick, disabled, className = '', ...props }) {
  return <button type="button" className={`icon-button ${className}`} title={label} aria-label={label}
    onClick={onClick} disabled={disabled} {...props}><Icon size={18} strokeWidth={1.8} /></button>;
}

export function EntryImage({ entry, className = '', alt }) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    let live = true; setUrl(null);
    if (entry?.imageUrl) imageURL(entry.imageUrl).then(value => { if (live) setUrl(value); }).catch(() => {});
    return () => { live = false; };
  }, [entry?.imageUrl]);
  return url ? <img className={className} src={url} alt={alt || entry?.name || ''} /> : <CircleHelp className={className} aria-hidden="true" />;
}

export function AssetImage({ assetId, ...props }) {
  return <EntryImage entry={{ imageUrl: `/api/images/${assetId}`, name: '截图候选' }} {...props} />;
}

export function Modal({ title, children, onClose, footer, wide = false, dismissOutside = true }) {
  useEffect(() => {
    const handler = event => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    const old = document.body.style.overflow; document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', handler); document.body.style.overflow = old; };
  }, [onClose]);
  return <div className="modal-backdrop" onClick={event => { if (dismissOutside && event.target === event.currentTarget) onClose(); }}>
    <section className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
      <header><h2>{title}</h2><IconButton icon={X} label="关闭" onClick={onClose} /></header>
      <div className="modal-body">{children}</div>{footer && <footer>{footer}</footer>}
    </section>
  </div>;
}

export function NumberField({ label, value, onChange, min = 0, max, nullable = false, step = 1, ...inputProps }) {
  return <label className="field"><span>{label}</span><input type="number" min={min} max={max} step={step}
    value={value ?? ''} onChange={event => onChange(event.target.value === '' && nullable ? null : Number(event.target.value))} {...inputProps} /></label>;
}

export function SaveButton({ busy, children = '保存', ...props }) {
  return <button className="primary" type="button" disabled={busy} {...props}>{busy && <LoaderCircle size={15} className="spin" />}{children}</button>;
}
