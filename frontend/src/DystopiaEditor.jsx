import React, { useState } from 'react';
import { Layers } from 'lucide-react';
import { Modal, SaveButton } from './common';
import MapView from './MapView';
import { coverageStatus, emptyDystopia, setCoverage } from './dystopia';

export function DystopiaFields({ value, onChange, nodes, catalog, selectedIds = [] }) {
  const entries = catalog.dystopia || [];
  const choices = entries.filter(row => Number(row.id.slice(-3)) <= 10);
  const policies = entries.filter(row => Number(row.id.slice(-3)) > 10);
  return <div className="dystopia-fields">
    <label className="checkbox-field"><input aria-label="本层实托邦" type="checkbox" checked={value.active}
      onChange={e => onChange(e.target.checked ? { ...emptyDystopia(), active: true,
        uncertainNodeIds: Object.keys(nodes) } : emptyDystopia())} /><Layers size={15} />本层实托邦</label>
    {value.active && <><div className="form-grid">
      <label className="field"><span>理念</span><select aria-label="实托邦理念" value={value.ideologyId || ''}
        onChange={e => onChange({ ...value, ideologyId: e.target.value || null,
          ...(e.target.value === 'dystopia_008' ? { idealSourceNodeId: null, policyId: 'dystopia_014' } : {}) })}>
        <option value="">待确认</option>{choices.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      <label className="field"><span>方针</span><select aria-label="实托邦方针" value={value.policyId || ''}
        onChange={e => onChange({ ...value, policyId: e.target.value || null })}>
        <option value="">无 / 待确认</option>{policies.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      <label className="field full"><span>理想源 · 紧急作战</span><select aria-label="理想源" value={value.idealSourceNodeId || ''}
        disabled={value.ideologyId === 'dystopia_008'} onChange={e => { const id = e.target.value || null;
          onChange({ ...(id ? setCoverage(value, [id], 'inside') : value), idealSourceNodeId: id }); }}>
        <option value="">{value.ideologyId === 'dystopia_008' ? '希望的沃土无理想源' : '待确认 / 不设定'}</option>
        {Object.values(nodes).filter(node => ['node_type_002', 'unknown_ferocity'].includes(node.observedCategoryId || node.categoryId)
          || node.id === value.idealSourceNodeId)
          .map(node => <option key={node.id} value={node.id}>({node.id})</option>)}</select></label>
    </div>
    {!!selectedIds.length && <div className="map-review-toolbar"><span>已选 {selectedIds.length} 个节点</span>
      <button onClick={() => onChange(setCoverage(value, selectedIds, 'inside'))}>纳入范围</button>
      <button onClick={() => onChange(setCoverage(value, selectedIds, 'outside'))}>移出范围</button>
      <button onClick={() => onChange(setCoverage(value, selectedIds, 'unknown'))}>待确认</button></div>}
    <details><summary>覆盖节点 · {value.affectedNodeIds.length} 个 · 待确认 {value.uncertainNodeIds.length} 个</summary>
      <div className="dystopia-node-list">{Object.values(nodes).map(node => <label className="field" key={node.id}><span>({node.id})</span>
        <select aria-label={`实托邦范围 ${node.id}`} value={coverageStatus(value, node.id)}
          onChange={e => onChange(setCoverage(value, [node.id], e.target.value))}>
          <option value="inside">范围内</option><option value="outside">范围外</option><option value="unknown">待确认</option></select></label>)}</div>
    </details></>}
  </div>;
}

export function SpecialRegionFields({ areaKey, utopiaId, onUtopiaChange, value, onChange, ...props }) {
  return <div className="special-region-fields">
    {areaKey?.includes('treehole') && <label className="field"><span>本层乌托邦（记录随机生成结果）</span>
      <select aria-label="本层乌托邦" value={utopiaId || ''} onChange={event => {
        const id = event.target.value || null;
        if (id) onChange(emptyDystopia());
        onUtopiaChange(id);
      }}><option value="">无 / 待确认</option>{props.catalog.utopia.map(row =>
        <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>}
    <DystopiaFields {...props} value={value} onChange={next => {
      if (next.active) onUtopiaChange(null);
      onChange(next);
    }} />
  </div>;
}

export default function DystopiaEditor({ instance, catalog, entries, onSave, onClose, busy }) {
  const [value, setValue] = useState(() => structuredClone(instance.dystopia || emptyDystopia()));
  const [utopiaId, setUtopia] = useState(instance.utopiaId || null);
  const [selected, setSelected] = useState([]);
  return <Modal title="本层实托邦 / 乌托邦" wide onClose={onClose} footer={<SaveButton busy={busy}
    onClick={() => onSave([{ type: 'dystopia', areaKey: instance.areaKey, value },
      { type: 'utopia', areaKey: instance.areaKey, value: utopiaId }])}>确认更新</SaveButton>}>
    <MapView preview instance={{ ...instance, dystopia: value, utopiaId }} catalog={catalog} entries={entries}
      busy={busy} selectedIds={selected} onSelectionChange={setSelected} />
    <SpecialRegionFields areaKey={instance.areaKey} utopiaId={utopiaId} onUtopiaChange={setUtopia}
      value={value} onChange={setValue} nodes={instance.nodes} catalog={catalog} selectedIds={selected} />
  </Modal>;
}
