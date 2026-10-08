import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Check, Crosshair, ZoomIn, ZoomOut, Maximize2, Flag, CircleHelp, Circle, SunDim } from 'lucide-react';
import { EntryImage, IconButton } from './common';
import { nodeCategory, num, pct } from './model';
import { coverageStatus } from './dystopia';
import { POSITION_FILTERS, candidatePositions, routeCurve } from './mapPresentation';
import { MAP_BACKGROUND, MAP_SIDE_BRIGHTNESS_RATIO, MAP_BRIGHTNESS_KEY, savedMapBrightness } from './mapBackgrounds';

const COLORS = { node_type_001: 'combat', node_type_002: 'combat', node_type_003: 'combat',
  unknown_ferocity: 'combat', node_type_004: 'green', node_type_013: 'gold', node_type_015: 'gold',
  node_type_010: 'blue', unknown_mystery: 'blue', start: 'start' };

export default function MapView({ instance, catalog, entries, scores, route, onSelect, onUpload, busy, selectedIds = [], onSelectionChange, preview = false }) {
  const [zoom, setZoom] = useState(1);
  const [brightness, setBrightness] = useState(() => savedMapBrightness());
  function changeBrightness(value) {
    setBrightness(value);
    try { localStorage.setItem(MAP_BRIGHTNESS_KEY, String(value)); } catch { /* Keep the current brightness when storage is unavailable. */ }
  }
  const [hover, setHover] = useState(null);
  const [filter, setFilter] = useState('');
  const markerId = `route-arrow-${useId().replace(/:/g, '')}`;
  useEffect(() => { setFilter(''); }, [instance?.instanceId]);
  const candidates = candidatePositions(instance, filter);
  const [selection, setSelection] = useState(null), scene = useRef(null), selectionStart = useRef(null);
  function localPoint(event) {
    const rect = scene.current.getBoundingClientRect();
    return { x: (event.clientX - rect.left) / zoom, y: (event.clientY - rect.top) / zoom };
  }
  function beginSelection(event) {
    if (!onSelectionChange || busy || event.button !== 0 || event.target.closest('button')) return;
    event.preventDefault(); setHover(null);
    selectionStart.current = localPoint(event); setSelection({ ...selectionStart.current, width: 0, height: 0 });
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function moveSelection(event) {
    const start = selectionStart.current;
    if (!start) return;
    const end = localPoint(event);
    setSelection({ x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), width: Math.abs(end.x - start.x), height: Math.abs(end.y - start.y) });
  }
  function endSelection(event) {
    const start = selectionStart.current;
    if (!start) return;
    const end = localPoint(event);
    const ids = geometry.nodes.filter(n => { const p = geometry.points[n.id]; return p.x >= Math.min(start.x, end.x) && p.x <= Math.max(start.x, end.x) && p.y >= Math.min(start.y, end.y) && p.y <= Math.max(start.y, end.y); }).map(n => n.id);
    onSelectionChange(event.shiftKey ? [...new Set([...selectedIds, ...ids])] : ids);
    selectionStart.current = null; setSelection(null);
  }
  const geometry = useMemo(() => {
    if (!instance) return null;
    const nodes = Object.values(instance.nodes);
    const xs = nodes.map(n => n.coord[0]), ys = nodes.map(n => n.coord[1]);
    const minX = Math.min(...xs), maxY = Math.max(...ys);
    const width = Math.max(620, (Math.max(...xs) - minX) * 108 + 160);
    const height = Math.max(340, (maxY - Math.min(...ys)) * 98 + 140);
    const usedWidth = (Math.max(...xs) - minX) * 108;
    const points = Object.fromEntries(nodes.map(n => [n.id, {
      x: (n.coord[0] - minX) * 108 + (width - usedWidth) / 2,
      y: (maxY - n.coord[1]) * 98 + 65,
    }]));
    return { width, height, points, nodes };
  }, [instance]);
  const visited = new Set(route?.steps?.flatMap(s => [s.entered, s.arrived]) || []);
  const steps = route?.steps || [];
  const posteriorFamilies = Object.values(instance?.prediction?.posteriorBeta?.families || {});
  const posteriorFallbacks = posteriorFamilies.filter(row => row.status === 'fallback');
  const predictionLabel = !instance ? '沉沦者的黑流树海' : !posteriorFamilies.length ? '规则预测' :
    posteriorFallbacks.length === posteriorFamilies.length ? '兼容预测' :
      `节点预测 beta${posteriorFallbacks.length ? ' · 部分回退' : ''}`;
  return <div className="map-frame">
    <div className="map-tools">
      <span className="map-template">{instance?.templateId || '地图待导入'}</span>
      {instance?.dystopia?.active && <span className="dystopia-label">{entries[instance.dystopia.ideologyId]?.name || '实托邦'} · {entries[instance.dystopia.policyId]?.name || '方针待确认'} · {instance.dystopia.affectedNodeIds.length} 节点</span>}
      {instance?.utopiaId && <span className="dystopia-label">乌托邦 · {entries[instance.utopiaId]?.name || instance.utopiaId}</span>}
      <div className="tool-group"><label className="map-brightness" title={`背景亮度 ${brightness}%`}>
          <SunDim size={14} aria-hidden="true" /><input type="range" min="10" max="100" step="5"
            aria-label="背景亮度" aria-valuetext={`${brightness}%`} value={brightness}
            onChange={event => changeBrightness(Number(event.target.value))} />
        </label><IconButton icon={ZoomOut} label="缩小地图" onClick={() => setZoom(Math.max(.55, zoom - .15))} />
        <span>{Math.round(zoom * 100)}%</span><IconButton icon={ZoomIn} label="放大地图" onClick={() => setZoom(Math.min(1.6, zoom + .15))} />
        <IconButton icon={Maximize2} label="重置地图缩放" onClick={() => setZoom(1)} /></div>
    </div>
    <div className="map-canvas has-background" data-background={MAP_BACKGROUND.id}
      style={{ backgroundImage: `url("${MAP_BACKGROUND.url}")`, '--map-background-shade': 1 - brightness / 100,
        '--map-side-shade': 1 - Math.min(1, brightness / 100 * MAP_SIDE_BRIGHTNESS_RATIO) }}>
    {!preview && geometry && <div className="map-guidance-row">
      <aside className="map-concepts"><p>· 节点得分代表该节点可能收益的加权量化指标，括号内是揭示新节点的信息收益。</p>
        <p>· 节点和事件概率为根据规则、统计结果的归一化估算。</p>
        <p>· 分数及规划路线随结局目标和进度、事件池、本层规划策略等因素变化；<strong>移动后应刷新地图并确认已完成节点</strong>。</p></aside>
      <fieldset className="position-filters"><legend>查看节点可能位置</legend>{POSITION_FILTERS.map(([id, name]) => <label key={id}>
        <input type="checkbox" checked={filter === id} onChange={() => setFilter(filter === id ? '' : id)} />{name}
      </label>)}</fieldset>
    </div>}
    <div className="map-viewport" onScroll={() => setHover(null)}>
      {!geometry ? <div className="empty-map"><CircleHelp size={36} /><h2>尚无地图</h2><button onClick={onUpload} disabled={busy}>导入截图</button></div> :
        <div className="map-scale" style={{ width: geometry.width * zoom, height: geometry.height * zoom }}>
          <div className="map-scene" ref={scene} onPointerDown={beginSelection} onPointerMove={moveSelection} onPointerUp={endSelection} onPointerCancel={() => { selectionStart.current = null; setSelection(null); }} style={{ width: geometry.width, height: geometry.height, transform: `scale(${zoom})` }}>
            <svg className="connections" width={geometry.width} height={geometry.height} aria-hidden="true">
              <defs><marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 Z" fill="#e3c872" /></marker></defs>
              {instance.dystopia?.active && geometry.nodes.map(node => {
                const status = coverageStatus(instance.dystopia, node.id), point = geometry.points[node.id];
                return status !== 'outside' && <circle key={`dystopia-${node.id}`} cx={point.x} cy={point.y} r={42}
                  className={`dystopia-zone ${status === 'unknown' ? 'uncertain' : ''}`} />;
              })}
              {instance.edges.map(([a, b]) => <line key={`${a}-${b}`} x1={geometry.points[a].x} y1={geometry.points[a].y}
                x2={geometry.points[b].x} y2={geometry.points[b].y} className="map-edge" />)}
              {steps.map((step, index) => {
                const a = geometry.points[step.from], b = geometry.points[step.entered];
                return a && b && <path key={index} d={routeCurve(a, b, index)} className="route-edge" markerEnd={`url(#${markerId})`} />;
              })}
            </svg>
            {geometry.nodes.map(node => {
              const category = preview && !node.observedCategoryId && !node.resolvedCategoryId ? 'unreadable' : nodeCategory(node), point = geometry.points[node.id];
              const position = instance.playerPosition === node.id;
              const value = scores?.nodeValues?.[node.id];
              const name = catalog.labels.nodeTypes[category] || (category === 'unreadable' ? '待确认' : category);
              const order = steps.findIndex(s => s.entered === node.id);
              return <button key={node.id} className={`map-node ${COLORS[category] || 'blue'} ${candidates.has(node.id) ? 'candidate-position' : ''} ${filter && !candidates.has(node.id) ? 'not-candidate-position' : ''} ${selectedIds.includes(node.id) ? 'selected-node' : ''} ${node.completion === 'completed' ? 'completed' : ''} ${visited.has(node.id) ? 'route-node' : ''} ${position ? 'player-node' : ''}`}
                style={{ left: point.x, top: point.y }} onClick={event => { setHover(null); if (preview || event.shiftKey) onSelectionChange?.(event.shiftKey ? [...new Set([...selectedIds, node.id])] : [node.id]); else onSelect?.(node.id, event.currentTarget.getBoundingClientRect()); }}
                aria-label={`节点 ${node.id} ${name}`} data-node-id={node.id}
                onMouseEnter={event => { const rect = event.currentTarget.getBoundingClientRect(); setHover({ node, rect }); }}
                onMouseLeave={() => setHover(null)} onFocus={event => setHover({ node, rect: event.currentTarget.getBoundingClientRect() })} onBlur={() => setHover(null)}>
                <span className="node-coordinate">{node.id === '0,0' ? '起点' : `(${node.id})`}</span>
                <span className="node-disc">{category === 'start' ? <Crosshair size={27} /> : category === 'node_type_020' ? <Circle size={13} /> :
                  <span className={`node-art ${candidates.has(node.id) ? 'candidate-art' : ''}`}><EntryImage entry={entries[category]} className={`node-icon ${category.startsWith('node_type_') ? 'atlas-icon' : 'unknown-icon'}`} />
                    {candidates.has(node.id) && <EntryImage entry={entries[filter === 'autopsy' ? 'node_type_001' : filter]} className="node-icon atlas-icon candidate-overlay" />}</span>}
                  {node.completion === 'completed' && <Check className="completed-badge" size={13} />}
                  {position && <Crosshair className="player-badge" size={19} />}
                  {order >= 0 && <span className="route-order">{order + 1}</span>}
                </span>
                <span className="node-name">{name}</span>
                {instance.dystopia?.active && instance.dystopia.idealSourceNodeId === node.id && <span className="ideal-source-label">理想源</span>}
                {!preview && <span className="node-value">{value ? num(value.points) : '—'}{value && <small className="reveal-value"> (+{num(value.revealValue || 0)})</small>}<small>分</small></span>}
                <span className="node-marks">{node.confirmedMarkIds.map(id => <EntryImage key={id} entry={entries[id]} className="mark-icon" />)}{node.candidateMarkIds?.map(id => <span key={id} title="标记候选" className="mark-candidate"><EntryImage entry={entries[id]} className="mark-icon" /></span>)}</span>
              </button>;
            })}
            {selection && <div className="map-selection" style={{ left: selection.x, top: selection.y, width: selection.width, height: selection.height }} />}
          </div>
        </div>}
    </div>
    </div>
    {hover && <div className="hover-sheet" style={{ left: Math.max(8, Math.min(window.innerWidth - 264, hover.rect.right + 8)), top: Math.max(8, Math.min(window.innerHeight - 250, hover.rect.top)) }}>
      <b>{catalog.labels.nodeTypes[nodeCategory(hover.node)]} <span>({hover.node.id})</span></b>
      <div className="hover-score">{num(scores?.nodeValues?.[hover.node.id]?.arrivalPoints ?? scores?.nodeValues?.[hover.node.id]?.points)}<small>期望分</small></div>
      <div className="hover-foot">节点 {num(scores?.nodeValues?.[hover.node.id]?.points)} + 揭示 {num(scores?.nodeValues?.[hover.node.id]?.revealValue)}</div>
      {scores?.nodeValues?.[hover.node.id]?.referenceLoss && <div className="reference-loss-inline">上贡损失 {num(scores.nodeValues[hover.node.id].referenceLoss.points)} 分
        （{scores.nodeValues[hover.node.id].referenceLoss.includedInPlanningScore ? '已扣规划分' : scores.nodeValues[hover.node.id].referenceLoss.includedPoints ? '部分已扣规划分' : '仅参考'}）</div>}
      {Object.entries(scores?.nodeValues?.[hover.node.id]?.classification?.probabilities ||
        instance.prediction?.unknownNodes?.[hover.node.id]?.categoryProbabilities || {}).map(([id, probability]) => <div className="probability-row" key={id}>
        <span>{catalog.labels.nodeTypes[id]}</span><span>{pct(probability)}</span>
      </div>)}
      <div className="hover-foot">{hover.node.completion === 'completed' ? '已完成' : '未完成'} · {hover.node.visibility === 'revealed' ? '已探明' : '未探明'}</div>
      {instance.dystopia?.active && <div className="hover-foot">实托邦：{ { inside: '范围内', outside: '范围外', unknown: '待确认' }[coverageStatus(instance.dystopia, hover.node.id)]}
        {instance.dystopia.idealSourceNodeId === hover.node.id ? ' · 理想源（紧急作战）' : ''}</div>}
    </div>}
    <div className="map-status"><span><Crosshair size={13} /> {instance?.playerPosition ? `当前位置 (${instance.playerPosition})` : '位置待确认'}</span>
      <span><Flag size={13} /> {instance ? `${Object.values(instance.nodes).filter(n => n.completion === 'completed').length}/${Object.keys(instance.nodes).length} 已完成` : '—'}</span>
      <span title={posteriorFallbacks.map(row => row.reason).join('；')}>{predictionLabel}{instance?.prediction?.warnings?.length ? ` · ${instance.prediction.warnings.length} 项规则提示` : ''}</span>
    </div>
  </div>;
}
