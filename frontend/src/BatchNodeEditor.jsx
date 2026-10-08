import React, { useState } from 'react';
import { Modal, SaveButton } from './common';

export default function BatchNodeEditor({ ids, areaKey, catalog, onClose, onSave, busy }) {
  const [category, setCategory] = useState(''), [completion, setCompletion] = useState('');
  const [marks, setMarks] = useState([]), [replaceMarks, setReplaceMarks] = useState(false);
  const validIds = ids.filter(id => id !== '0,0');
  function save() {
    const commands = validIds.map(nodeId => ({ type: 'node', areaKey, nodeId, changes: {
      ...(category ? { categoryId: category } : {}), ...(completion ? { completion } : {}), ...(replaceMarks ? { markIds: marks } : {}),
    } }));
    onSave(commands);
  }
  return <Modal title={`编辑所选节点 · ${validIds.length} 个`} onClose={onClose} footer={<SaveButton busy={busy} disabled={busy || !validIds.length || !(category || completion || replaceMarks)} onClick={save} />}>
    <div className="form-grid"><label className="field"><span>类别</span><select aria-label="所选节点类别" value={category} onChange={e => setCategory(e.target.value)}><option value="">不更新</option>
      {Object.entries(catalog.labels.nodeTypes).filter(([id]) => id !== 'start' && !id.startsWith('unknown_')).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <label className="field"><span>完成状态</span><select value={completion} onChange={e => setCompletion(e.target.value)}><option value="">不更新</option><option value="pending">未完成</option><option value="completed">已完成</option><option value="unknown">待确认</option></select></label></div>
    <label className="checkbox-field"><input type="checkbox" checked={replaceMarks} onChange={e => setReplaceMarks(e.target.checked)} />替换所选节点的标记</label>
    {replaceMarks && <div className="check-list">{Object.entries(catalog.labels.nodeMarks).map(([id, name]) => <label key={id}><input type="checkbox" checked={marks.includes(id)} onChange={e => setMarks(e.target.checked ? [...marks, id] : marks.filter(m => m !== id))} />{name}</label>)}</div>}
  </Modal>;
}
