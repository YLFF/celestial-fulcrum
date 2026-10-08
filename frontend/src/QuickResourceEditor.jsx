import React, { useState } from 'react';
import { Modal, SaveButton } from './common';

const LABELS = { life: '生命', shield: '护盾', level: '等级 / 经验', hope: '希望', originiumIngot: '源石锭', actionPoints: '行动力' };

export default function QuickResourceEditor({ field, state, instance, onSave, onClose, busy }) {
  const definitions = field === 'life' ? [['current', '当前生命', state.resources.life.current], ['max', '生命上限', state.resources.life.max]]
    : field === 'level' ? [['level', '等级', state.resources.level], ['current', '当前经验', state.resources.experience.current], ['max', '升级所需经验', state.resources.experience.max]]
    : [[field, LABELS[field], field === 'actionPoints' ? instance?.actionPoints : state.resources[field]]];
  const [values, setValues] = useState(() => Object.fromEntries(definitions.map(([id, , value]) => [id, value == null ? '' : String(value)])));
  const [error, setError] = useState('');
  async function save(event) {
    event.preventDefault();
    const parsed = {};
    for (const [id, label] of definitions) {
      if (!/^\d+$/.test(values[id]) || !Number.isSafeInteger(Number(values[id]))) { setError(`${label}需要填写非负整数`); return; }
      parsed[id] = Number(values[id]);
    }
    if (field === 'level' && (parsed.level < 1 || parsed.level > 10)) { setError('等级范围为 1–10'); return; }
    if ((field === 'life' || field === 'level' && parsed.max > 0) && parsed.current > parsed.max) { setError('当前值不能超过上限'); return; }
    setError('');
    const command = field === 'actionPoints' ? { type: 'actionPoints', areaKey: instance.areaKey, value: parsed.actionPoints }
      : { type: 'resources', values: field === 'life' ? { life: parsed } : field === 'level' ? { level: parsed.level, experience: { current: parsed.current, max: parsed.max } } : parsed };
    await onSave([command]);
  }
  return <Modal title={`编辑${LABELS[field]}`} onClose={onClose} footer={<SaveButton form="quick-resource-form" type="submit" busy={busy} />}>
    <form id="quick-resource-form" onSubmit={save} noValidate className="form-grid">
      {definitions.map(([id, label], index) => <label key={id} className="field"><span>{label}</span>
        <input autoFocus={index === 0} aria-label={label} type="number" min={id === 'level' ? 1 : 0} max={id === 'level' ? 10 : undefined} step={1}
          value={values[id]} onChange={event => { setValues({ ...values, [id]: event.target.value }); setError(''); }} /></label>)}
      {error && <div role="alert" className="form-error">{error}</div>}
    </form>
  </Modal>;
}
