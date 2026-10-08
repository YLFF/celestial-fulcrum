import React, { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Modal, NumberField, SaveButton, IconButton } from './common';
import { AREA_NAMES, operatorProgressLabel, operatorProgressOptions, PROFESSIONS, uid } from './model';
import CatalogPicker from './CatalogPicker';
import { api } from './api';

function EndingFields({ goals, onChange }) {
  return <div className="form-grid ending-options">{[
    ['endingV', '五层', { normal1: '普通结局 1', pursuit1: '追猎结局 1', ending2: '结局 2' }],
    ['endingVI', '六层', { normal3: '普通结局 3', pursuit3: '追猎结局 3' }],
  ].map(([field, title, choices]) => <fieldset key={field}><legend>{title}</legend>{Object.entries(choices).map(([id, name]) => <label className="checkbox-field" key={id}>
    <input type="checkbox" checked={goals[field] === id} onChange={e => onChange({ ...goals, [field]: e.target.checked ? id : null })} />{name}</label>)}</fieldset>)}</div>;
}

export function NewRunEditor({ catalog, busy, onClose, onCreate }) {
  const [runId, setRunId] = useState(uid('run')), [difficulty, setDifficulty] = useState(15), [squad, setSquad] = useState('squad_014');
  const [cocoons, setCocoons] = useState({}), [technology, setTechnology] = useState({ attackPercent: 20, defensePercent: 20, maxHpPercent: 25 });
  const [lookoutSplit, setLookoutSplit] = useState(true);
  const [investment, setInvestment] = useState(99), [goals, setGoals] = useState({ endingV: null, endingVI: null, preferences: { ending3_autopsy: 'ignored', ending3_trade: 'ignored', ending3_tribute: 'ignored' } });
  const [operators, setOperators] = useState([]);
  const [supports, setSupports] = useState([]), [defenderTicket, setDefenderTicket] = useState(false), [promoteMechanist, setPromoteMechanist] = useState(false);
  const [preview, setPreview] = useState(null), [error, setError] = useState('');
  const body = { runId, difficulty, squadId: squad, cocoons: Object.fromEntries(Object.entries(cocoons).filter(([, n]) => n > 0)),
    technologyCombatBonuses: technology, lookoutSplitUnlocked: lookoutSplit, investmentBalance: investment, initialOperators: operators,
    initialSupports: supports, initialTickets: defenderTicket ? ['重装招募券'] : [], promoteInitialMechanist: promoteMechanist, goals };
  const serialized = JSON.stringify(body);
  useEffect(() => {
    let live = true; setPreview(null); setError('');
    const timer = setTimeout(() => api('/api/opening/preview', { method: 'POST', body: JSON.parse(serialized) }).then(value => { if (live) setPreview(value); }).catch(e => { if (live) setError(e.message); }), 120);
    return () => { live = false; clearTimeout(timer); };
  }, [serialized]);
  const changeOperator = (index, changes) => setOperators(operators.map((row, i) => i === index ? { ...row, ...changes } : row));
  const setCocoon = (id, count) => setCocoons({ ...cocoons, [id]: count });
  return <Modal title="新建对局" onClose={onClose} wide footer={<SaveButton busy={busy} disabled={busy || !preview?.affordable || !squad || !runId.trim()} onClick={() => onCreate(body)}>进入树海</SaveButton>}>
    <div className="form-grid"><label className="field"><span>对局 ID</span><input value={runId} onChange={e => setRunId(e.target.value)} /></label>
      <NumberField label="难度" value={difficulty} max={20} onChange={setDifficulty} />
      <label className="field"><span>分队</span><select aria-label="分队" value={squad} required onChange={e => { setSquad(e.target.value); setOperators([]); setDefenderTicket(false); setPromoteMechanist(false); }}>
        {Object.entries(catalog.squads).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <NumberField label="本局取钱预算" value={investment} onChange={setInvestment} /></div>
    <h3>结局选择</h3><EndingFields goals={goals} onChange={setGoals} />
    <div className="support-grid">{Object.entries({ ending3_autopsy: '无效验尸', ending3_trade: '失与得上贡自然物', ending3_tribute: '不期而遇上贡源石锭' }).map(([id, name]) => <label className="checkbox-field" key={id}>
      <input type="checkbox" checked={goals.preferences?.[id] === 'required'} onChange={e => setGoals({ ...goals, preferences: { ...goals.preferences, [id]: e.target.checked ? 'required' : 'ignored' } })} />{name}</label>)}</div>
    <h3>局外科技</h3><div className="form-grid thirds">{Object.entries({ attackPercent: '攻击力加成 %', defensePercent: '防御力加成 %', maxHpPercent: '生命值加成 %' }).map(([id, label]) =>
      <NumberField key={id} label={label} value={technology[id]} onChange={value => setTechnology({ ...technology, [id]: value })} />)}</div>
    <label className="checkbox-field"><input type="checkbox" checked={lookoutSplit} onChange={e => setLookoutSplit(e.target.checked)} />生命游戏 · 分裂（羽瞰点）</label>
    <h3>初始支援</h3><div className="support-grid">
      {['relic_240', 'relic_241'].map(id => <div className="support-count" key={id}><label className="checkbox-field"><input type="checkbox" checked={!!cocoons[id]} onChange={e => setCocoon(id, e.target.checked ? 1 : 0)} />{catalog.cocoons[id]}</label>
        {!!cocoons[id] && <input aria-label={`${catalog.cocoons[id]}数量`} type="number" min={1} value={cocoons[id]} onChange={e => setCocoon(id, Math.max(1, Number(e.target.value)))} />}</div>)}
      {Object.entries(catalog.initialSupports || {}).map(([id, name]) => <label className="checkbox-field" key={id}><input type="checkbox" checked={supports.includes(id)} onChange={e => setSupports(e.target.checked ? [...supports, id] : supports.filter(key => key !== id))} />{name}</label>)}
      {['relic_032', 'relic_033', 'relic_034', 'relic_035', 'relic_036', 'relic_037'].map(id => <label className="checkbox-field" key={id}><input type="checkbox" checked={!!cocoons[id]} onChange={e => setCocoon(id, e.target.checked ? 1 : 0)} />{catalog.cocoons[id]}</label>)}
    </div>
    <h3>初始招募</h3>
    {preview && <div className={`opening-summary ${preview.affordable ? '' : 'negative'}`}><span>初始希望 {preview.initialHope}</span><span>招募 / 进阶 −{preview.hopeCost}</span><b>剩余希望 {preview.remainingHope}</b><span>源石锭 {preview.resources.originiumIngot}</span><span>零件箱 {preview.capacity}</span></div>}
    {error && <div className="form-error" role="alert">{error}</div>}
    {squad === 'squad_002' && <div className="initial-mechanist"><b>机械师 · 6★ · 重装 · {promoteMechanist ? '已进阶' : '未进阶'}</b>
      <label className="checkbox-field"><input type="checkbox" checked={defenderTicket} onChange={e => { setDefenderTicket(e.target.checked); if (!e.target.checked) setPromoteMechanist(false); }} />初始有重装招募券</label>
      <label className="checkbox-field"><input type="checkbox" disabled={!defenderTicket} checked={promoteMechanist} onChange={e => setPromoteMechanist(e.target.checked)} />消耗 2 希望进阶机械师</label></div>}
    <div className="picker-layout"><CatalogPicker rows={catalog.operators?.filter(row => squad !== 'squad_002' || row.name !== '机械师')} operators selectedIds={operators.length >= (promoteMechanist ? 2 : 3) ? catalog.operators.map(row => row.id) : operators.filter(row => !catalog.operators.find(entry => entry.id === row.operatorId)?.repeatable).map(row => row.operatorId)} onAdd={entry => setOperators([...operators, { selectionId: uid('initial-op'), operatorId: entry.id, name: entry.name, profession: entry.profession, elite: entry.rarity >= 3 ? 1 : 0, source: 'normal' }])} />
      <div className="initial-roster">{!operators.length && <span className="quiet">待选初始干员</span>}{operators.map((row, index) => { const entry = catalog.operators.find(x => x.id === row.operatorId); return <div className="opening-operator" key={row.selectionId || index}>
        <div className="item-title"><b>{entry.name}</b><small>{entry.rarity}★ · {row.profession || entry.profession || '待确认'}</small></div>
        {entry.professionEditable && <label className="field"><span>职业</span><select aria-label={`${entry.name} 初始职业`} value={row.profession || ''} onChange={e => changeOperator(index, { profession: e.target.value || null })}><option value="">待确认</option>{PROFESSIONS.map(text => <option key={text}>{text}</option>)}</select></label>}
        <label className="field"><span>进阶状态</span><select aria-label={`${entry.name} 初始进阶状态`} value={row.elite} onChange={e => changeOperator(index, { elite: Number(e.target.value) })}>{operatorProgressOptions(entry.rarity, row.elite).map(value => <option key={value} value={value}>{operatorProgressLabel(value)}</option>)}</select></label>
        <label className="field"><span>来源</span><select aria-label={`${entry.name} 初始来源`} value={row.source} onChange={e => changeOperator(index, { source: e.target.value })}><option value="normal">普通招募</option><option value="temporary">临时招募</option></select></label>
        <span className="hope-cost">{preview?.operators[index]?.hopeCost ?? '…'} 希望</span><IconButton icon={Trash2} label={`移除初始干员 ${entry.name}`} onClick={() => setOperators(operators.filter((_, i) => i !== index))} /></div>; })}</div>
    </div>
  </Modal>;
}

export function ResourceEditor({ state, instance, catalog, onClose, onSave, busy }) {
  const [resources, setResources] = useState(structuredClone(state.resources));
  const [action, setAction] = useState(instance?.actionPoints ?? 6);
  const [tickets, setTickets] = useState([...state.recruitmentTickets]);
  const [ticket, setTicket] = useState('重装招募券');
  const set = (id, value) => setResources({ ...resources, [id]: value });
  async function save() {
    const keys = ['life', 'experience', 'shield', 'level', 'hope', 'originiumIngot', 'totalEstimatedValue', 'investmentBalance', 'carrySlots', 'deploymentSlots', 'recruitmentTicketCapacity'];
    const values = Object.fromEntries(keys.filter(id => resources[id] !== undefined).map(id => [id, resources[id]]));
    const commands = [{ type: 'resources', values }, { type: 'tickets', items: tickets }];
    if (instance) commands.push({ type: 'actionPoints', areaKey: instance.areaKey, value: action });
    await onSave(commands);
  }
  return <Modal title="资源与招募券" onClose={onClose} wide footer={<SaveButton busy={busy} onClick={save} />}>
    <div className="form-grid thirds">
      {Object.entries({ level: '指挥等级', hope: '希望', originiumIngot: '源石锭', shield: '护盾', investmentBalance: '投资余额', totalEstimatedValue: '总估价', carrySlots: '携带位', deploymentSlots: '部署位', recruitmentTicketCapacity: '招募券上限' }).map(([id, label]) =>
        <NumberField key={id} label={label} value={resources[id]} min={id === 'level' ? 1 : 0} max={id === 'level' ? 10 : undefined} nullable={id === 'totalEstimatedValue'} onChange={value => set(id, value)} />)}
      {['life', 'experience'].flatMap(id => ['current', 'max'].map(part => <NumberField key={id + part} label={`${id === 'life' ? '生命' : '经验'}${part === 'current' ? '当前' : '上限'}`}
        value={resources[id][part]} nullable onChange={value => set(id, { ...resources[id], [part]: value })} />))}
      {instance && <NumberField label="本层行动力" value={action} onChange={setAction} />}
    </div><h3>留存招募券 · {tickets.length} 张</h3><div className="item-picker"><select aria-label="招募券类别" value={ticket} onChange={e => setTicket(e.target.value)}>
      {catalog.ticketNames.map(name => <option key={name}>{name}</option>)}</select><button onClick={() => setTickets([...tickets, ticket])}><Plus size={15} />添加</button></div>
    <div className="ticket-list">{tickets.map((name, index) => <div key={`${name}-${index}`}><span>{name}</span><IconButton icon={Trash2} label={`移除招募券 ${name}`} onClick={() => setTickets(tickets.filter((_, i) => i !== index))} /></div>)}</div>
  </Modal>;
}

export function GoalEditor({ loaded, onSave, onClose, busy }) {
  const [goals, setGoals] = useState({ preferences: {}, progress: {}, note: '', ...structuredClone(loaded.state.goals) });
  return <Modal title="结局目标与进度" onClose={onClose} footer={<SaveButton busy={busy} onClick={() => onSave([{ type: 'goals', value: goals }])} />}>
    <EndingFields goals={goals} onChange={setGoals} />
    <div className="goal-edit-list">{loaded.goalSummary.milestones.map(row => <div key={row.id}><b>{row.name}</b><div className="form-grid">
      <label className="field"><span>优先级</span><select value={goals.preferences[row.id] || row.priority} onChange={e => setGoals({ ...goals, preferences: { ...goals.preferences, [row.id]: e.target.value } })}>
        <option value="required">必要</option><option value="preferred">偏好</option><option value="ignored">不需要</option></select></label>
      <label className="field"><span>进度</span><select value={goals.progress[row.id]?.status || row.status} onChange={e => setGoals({ ...goals, progress: { ...goals.progress, [row.id]: { ...goals.progress[row.id], status: e.target.value } } })}>
        <option value="unknown">待确认</option><option value="pending">未完成</option><option value="completed">已完成</option><option value="unavailable">不可完成</option></select></label>
    </div></div>)}</div><label className="field"><span>策略备忘</span><textarea value={goals.note || ''} onChange={e => setGoals({ ...goals, note: e.target.value })} /></label>
  </Modal>;
}
