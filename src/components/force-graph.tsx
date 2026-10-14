'use client';

/**
 * 自定义 SVG 力导向图 (知识图谱可视化, 替代原 ECharts graph)
 * 简易力模拟: 斥力 + 弹簧引力 + 中心引力, 支持拖拽/缩放/点击
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  weight?: number;
  extra?: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  weight?: number;
  type?: string;
}

const TYPE_COLORS: Record<string, { fill: string; stroke: string; text: string }> = {
  structure: { fill: '#0d9488', stroke: '#14b8a6', text: '#0f766e' },
  literature: { fill: '#d97706', stroke: '#f59e0b', text: '#b45309' },
  uniprot: { fill: '#059669', stroke: '#10b981', text: '#047857' },
  center: { fill: '#0f766e', stroke: '#2dd4bf', text: '#134e4a' },
};

const TYPE_LABELS: Record<string, string> = {
  structure: '结构',
  literature: '文献',
  uniprot: '蛋白质',
  center: '中心',
};

interface SimNode extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

export function ForceGraph({
  nodes,
  edges,
  height = 520,
  onNodeClick,
  centerId,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  height?: number;
  onNodeClick?: (node: GraphNode) => void;
  centerId?: string;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [transform, setTransform] = useState({ k: 1, x: 0, y: 0 });
  const dragRef = useRef<{ nodeId: string | null; lastX: number; lastY: number }>({ nodeId: null, lastX: 0, lastY: 0 });
  const panRef = useRef<{ active: boolean; lastX: number; lastY: number }>({ active: false, lastX: 0, lastY: 0 });
  const width = 900;

  // 初始化位置
  useEffect(() => {
    const init: SimNode[] = nodes.map((n, i) => {
      const angle = (i / Math.max(1, nodes.length)) * Math.PI * 2;
      const radius = n.type === 'center' ? 0 : 120 + (i % 5) * 45;
      return {
        ...n,
        x: width / 2 + Math.cos(angle) * radius + (Math.random() - 0.5) * 30,
        y: height / 2 + Math.sin(angle) * radius + (Math.random() - 0.5) * 30,
        vx: 0,
        vy: 0,
      };
    });
    setSimNodes(init);
  }, [nodes, height]);

  // 力模拟循环
  useEffect(() => {
    if (simNodes.length === 0) return;
    let raf = 0;
    let tick = 0;

    const step = () => {
      tick++;
      const next = simNodes.map((n) => ({ ...n, vx: n.vx * 0.85, vy: n.vy * 0.85 }));
      const map = new Map(next.map((n) => [n.id, n]));

      // 斥力
      for (let i = 0; i < next.length; i++) {
        for (let j = i + 1; j < next.length; j++) {
          const a = next[i];
          const b = next[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const dist = Math.max(20, Math.sqrt(dx * dx + dy * dy));
          const force = 2400 / (dist * dist);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          a.vx += fx;
          a.vy += fy;
          b.vx -= fx;
          b.vy -= fy;
        }
      }
      // 弹簧引力
      for (const e of edges) {
        const a = map.get(e.source);
        const b = map.get(e.target);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const target = 130;
        const force = (dist - target) * 0.012;
        const fx = (dx / (dist || 1)) * force;
        const fy = (dy / (dist || 1)) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }
      // 中心引力 + 积分
      for (const n of next) {
        const isCenter = n.id === centerId || n.type === 'center';
        if (!isCenter) {
          n.vx += (width / 2 - n.x) * 0.002;
          n.vy += (height / 2 - n.y) * 0.002;
        }
        if (dragRef.current.nodeId === n.id) continue;
        n.x += Math.max(-12, Math.min(12, n.vx));
        n.y += Math.max(-12, Math.min(12, n.vy));
        n.x = Math.max(40, Math.min(width - 40, n.x));
        n.y = Math.max(40, Math.min(height - 40, n.y));
      }
      setSimNodes(next);
      if (tick < 160) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
     
  }, [simNodes.length, edges, centerId]);

  const handleNodeMouseDown = useCallback((e: React.MouseEvent, nodeId: string) => {
    e.stopPropagation();
    dragRef.current = { nodeId, lastX: e.clientX, lastY: e.clientY };
    const node = simNodes.find((n) => n.id === nodeId);
    setSelected(nodeId);
    if (node) onNodeClick?.(node);
  }, [simNodes, onNodeClick]);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (dragRef.current.nodeId) {
        const dx = (e.clientX - dragRef.current.lastX) / transform.k;
        const dy = (e.clientY - dragRef.current.lastY) / transform.k;
        dragRef.current.lastX = e.clientX;
        dragRef.current.lastY = e.clientY;
        setSimNodes((prev) =>
          prev.map((n) => (n.id === dragRef.current.nodeId ? { ...n, x: n.x + dx, y: n.y + dy } : n))
        );
      } else if (panRef.current.active) {
        const dx = e.clientX - panRef.current.lastX;
        const dy = e.clientY - panRef.current.lastY;
        panRef.current.lastX = e.clientX;
        panRef.current.lastY = e.clientY;
        setTransform((t) => ({ ...t, x: t.x + dx, y: t.y + dy }));
      }
    },
    [transform.k]
  );

  const handleMouseUp = useCallback(() => {
    dragRef.current.nodeId = null;
    panRef.current.active = false;
  }, []);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    setTransform((t) => {
      const k = Math.max(0.4, Math.min(3, t.k * (e.deltaY < 0 ? 1.12 : 0.89)));
      return { ...t, k };
    });
  }, []);

  const nodeMap = useMemo(() => new Map(simNodes.map((n) => [n.id, n])), [simNodes]);
  const selectedNode = selected ? nodeMap.get(selected) : null;

  const radius = (n: SimNode) => {
    if (n.type === 'center' || n.id === centerId) return 26;
    if (n.type === 'structure') return 18 + Math.min(8, (n.weight || 1) * 1.2);
    if (n.type === 'literature') return 14 + Math.min(8, (n.weight || 1) * 1.4);
    return 13;
  };

  return (
    <div className="relative overflow-hidden rounded-xl border bg-gradient-to-br from-card to-muted/40 dark:from-zinc-900 dark:to-zinc-900/60" style={{ height }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        className="h-full w-full cursor-grab active:cursor-grabbing"
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
        onMouseDown={(e) => {
          panRef.current = { active: true, lastX: e.clientX, lastY: e.clientY };
        }}
      >
        <defs>
          <filter id="glow">
            <feDropShadow dx="0" dy="0" stdDeviation="3" floodOpacity="0.3" />
          </filter>
        </defs>
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k}) translate(${(1 - transform.k) * width / 2},${(1 - transform.k) * height / 2})`}>
          {/* 边 */}
          {edges.map((e, i) => {
            const a = nodeMap.get(e.source);
            const b = nodeMap.get(e.target);
            if (!a || !b) return null;
            const isActive = selected === e.source || selected === e.target || hovered === e.source || hovered === e.target;
            return (
              <g key={`e-${i}`}>
                <line
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={e.type === 'maps_to' ? 'rgba(16,185,129,0.4)' : 'rgba(120,120,120,0.35)'}
                  strokeWidth={isActive ? 2.2 : Math.max(0.8, (e.weight || 1) * 0.55)}
                  strokeDasharray={e.type === 'maps_to' ? '4 3' : undefined}
                />
              </g>
            );
          })}
          {/* 节点 */}
          {simNodes.map((n) => {
            const colors = TYPE_COLORS[n.id === centerId ? 'center' : n.type] || TYPE_COLORS.structure;
            const r = radius(n);
            const isSelected = selected === n.id;
            const isDim = selected && !isSelected && !edges.some(
              (e) => (e.source === selected && e.target === n.id) || (e.target === selected && e.source === n.id)
            );
            return (
              <g
                key={n.id}
                transform={`translate(${n.x},${n.y})`}
                className="cursor-pointer"
                opacity={isDim ? 0.35 : 1}
                onMouseDown={(e) => handleNodeMouseDown(e, n.id)}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
              >
                <circle
                  r={r}
                  fill={colors.fill}
                  stroke={colors.stroke}
                  strokeWidth={isSelected ? 3 : 1.5}
                  filter={isSelected ? 'url(#glow)' : undefined}
                  className="transition-all"
                />
                <text
                  y={r + 14}
                  textAnchor="middle"
                  className="pointer-events-none select-none fill-current text-[11px] font-medium"
                  fill="currentColor"
                  style={{ fontSize: 11 }}
                >
                  {n.label.length > 22 ? `${n.label.slice(0, 21)}…` : n.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* 图例 */}
      <div className="absolute left-3 top-3 flex flex-col gap-1.5 rounded-lg border bg-background/80 px-3 py-2 text-[11px] backdrop-blur">
        {['structure', 'literature', 'uniprot'].map((t) => (
          <div key={t} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: TYPE_COLORS[t].fill }} />
            <span className="text-muted-foreground">{TYPE_LABELS[t]}</span>
          </div>
        ))}
      </div>

      {/* 节点信息 */}
      {selectedNode && (
        <div className="absolute bottom-3 right-3 max-w-[280px] rounded-lg border bg-background/95 p-3 text-xs shadow-lg backdrop-blur">
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="font-mono font-semibold">{selectedNode.label}</span>
            <span className="rounded px-1.5 py-0.5 text-[10px]" style={{ background: `${TYPE_COLORS[selectedNode.type]?.fill}22`, color: TYPE_COLORS[selectedNode.type]?.text }}>
              {TYPE_LABELS[selectedNode.type]}
            </span>
          </div>
          {selectedNode.extra?.title != null && <p className="text-muted-foreground">{String(selectedNode.extra.title).slice(0, 80)}</p>}
          {selectedNode.extra?.method != null && <p className="mt-1 text-muted-foreground">方法: {String(selectedNode.extra.method)}</p>}
          {selectedNode.extra?.year != null && <p className="text-muted-foreground">年份: {String(selectedNode.extra.year)}</p>}
        </div>
      )}

      {/* 缩放控制 */}
      <div className="absolute bottom-3 left-3 flex gap-1">
        <button
          className="rounded border bg-background/80 px-2 py-1 text-xs backdrop-blur hover:bg-accent"
          onClick={() => setTransform({ k: 1, x: 0, y: 0 })}
          type="button"
        >
          重置视图
        </button>
      </div>
    </div>
  );
}
