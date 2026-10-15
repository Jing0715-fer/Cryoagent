'use client';

/**
 * 自定义 SVG 力导向图 (知识图谱可视化, 替代原 ECharts graph)
 * 简易力模拟: 斥力 + 弹簧引力 + 中心引力, 支持拖拽/缩放/点击
 * BENCH 设计系统: 节点分类编码走 --chart-1..3, 选中/悬停走 --primary,
 * 背景/文字跟随主题令牌, 配色全部读取 CSS 变量 (硬编码色已移除)
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

/** 节点分类 → 设计令牌 (chart 色系仅用于分类编码) */
const TYPE_TOKENS: Record<string, string> = {
  structure: 'var(--chart-1)',
  literature: 'var(--chart-2)',
  uniprot: 'var(--chart-3)',
  center: 'var(--chart-1)',
};

const TYPE_LABELS: Record<string, string> = {
  structure: '结构',
  literature: '文献',
  uniprot: '蛋白质',
  center: '中心',
};

const MONO_FONT = 'var(--font-plex-mono), ui-monospace, monospace';

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
    <div
      className="relative overflow-hidden rounded-md border bg-background"
      style={{
        height,
        backgroundImage:
          'linear-gradient(to right, color-mix(in oklch, var(--foreground) 4%, transparent) 1px, transparent 1px), linear-gradient(to bottom, color-mix(in oklch, var(--foreground) 4%, transparent) 1px, transparent 1px)',
        backgroundSize: '28px 28px',
      }}
    >
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`知识图谱力导向图 · ${simNodes.length} 节点 ${edges.length} 边 · 支持拖拽平移与滚轮缩放`}
        className="h-full w-full cursor-grab active:cursor-grabbing"
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
        onMouseDown={(e) => {
          panRef.current = { active: true, lastX: e.clientX, lastY: e.clientY };
        }}
      >
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k}) translate(${(1 - transform.k) * width / 2},${(1 - transform.k) * height / 2})`}>
          {/* 边 — 数据重量映射: opacity 随 weight 增强, mentions 高权重加粗; maps_to 虚线保持 */}
          {edges.map((e, i) => {
            const a = nodeMap.get(e.source);
            const b = nodeMap.get(e.target);
            if (!a || !b) return null;
            const isActive = selected === e.source || selected === e.target || hovered === e.source || hovered === e.target;
            const w = e.weight || 1;
            const opacity = 0.25 + (Math.min(w, 8) / 8) * 0.5;
            const stroke = isActive
              ? 'var(--primary)'
              : e.type === 'maps_to'
                ? 'var(--chart-3)'
                : 'var(--foreground)';
            const strokeWidth = isActive
              ? 2
              : e.type === 'mentions' && w >= 3
                ? 1.5
                : 1;
            return (
              <g key={`e-${i}`}>
                <line
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  style={{ stroke, opacity: isActive ? 1 : opacity }}
                  strokeWidth={strokeWidth}
                  strokeDasharray={e.type === 'maps_to' ? '4 3' : undefined}
                />
              </g>
            );
          })}
          {/* 节点 — 分类编码 chart-1..3; 常规描边 background 分离, 悬停/选中 halo 环, 中心双环 */}
          {simNodes.map((n) => {
            const token = TYPE_TOKENS[n.id === centerId ? 'center' : n.type] || TYPE_TOKENS.structure;
            const r = radius(n);
            const isSelected = selected === n.id;
            const isHovered = hovered === n.id;
            const isCenter = n.id === centerId || n.type === 'center';
            const isDim = selected && !isSelected && !edges.some(
              (e) => (e.source === selected && e.target === n.id) || (e.target === selected && e.source === n.id)
            );
            const stroke = isSelected || isHovered || isCenter ? 'var(--primary)' : 'var(--background)';
            return (
              <g
                key={n.id}
                transform={`translate(${n.x},${n.y})`}
                className="cursor-pointer"
                opacity={isDim ? 0.3 : 1}
                onMouseDown={(e) => handleNodeMouseDown(e, n.id)}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
              >
                {/* 中心节点 — 外环双环标记 */}
                {isCenter && (
                  <circle
                    r={r + 5}
                    fill="none"
                    stroke="var(--primary)"
                    strokeOpacity={0.4}
                    strokeWidth={1.25}
                    className="pointer-events-none"
                  />
                )}
                {/* 悬停/选中 — halo 环 (选中走 primary) */}
                {(isSelected || isHovered) && (
                  <circle
                    r={r + 4}
                    fill="none"
                    stroke={isSelected ? 'var(--primary)' : token}
                    strokeOpacity={0.35}
                    strokeWidth={1}
                    className="pointer-events-none"
                  />
                )}
                <circle
                  r={r}
                  style={{ fill: token, stroke }}
                  strokeWidth={isSelected ? 2.5 : isHovered || isCenter ? 1.8 : 1.5}
                  className="transition-all"
                />
                <text
                  y={r + 13}
                  textAnchor="middle"
                  className="pointer-events-none select-none"
                  style={{
                    fill: isSelected ? 'var(--foreground)' : 'var(--muted-foreground)',
                    fontFamily: MONO_FONT,
                    fontSize: 10,
                    paintOrder: 'stroke',
                    stroke: 'var(--background)',
                    strokeWidth: 3,
                    strokeLinejoin: 'round',
                  }}
                >
                  {n.label.length > 22 ? `${n.label.slice(0, 21)}…` : n.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* 图例 — 仪器面板角标 */}
      <div className="absolute left-2.5 top-2.5 rounded-[5px] border bg-card/95 px-2.5 py-2">
        <div className="label-tech mb-1.5 border-b pb-1.5 !text-[9px]">Legend</div>
        <div className="space-y-1">
          {(['structure', 'literature', 'uniprot'] as const).map((t) => (
            <div key={t} className="flex items-center gap-2">
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: TYPE_TOKENS[t] }} aria-hidden />
              <span className="label-tech !text-[9px] normal-case !tracking-[0.06em]">{TYPE_LABELS[t]}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 节点信息 — mono 键值铭牌 */}
      {selectedNode && (
        <div className="absolute bottom-2.5 right-2.5 w-[240px] max-w-[calc(100%-20px)] rounded-md border bg-card p-2.5 shadow-sm">
          <div className="flex items-center justify-between gap-2 border-b pb-1.5">
            <span className="num truncate text-[11px] font-semibold">{selectedNode.label}</span>
            <span className="shrink-0 rounded-[3px] border border-border px-1 py-px font-mono text-[9px] text-muted-foreground">
              {TYPE_LABELS[selectedNode.type] ?? selectedNode.type.toUpperCase()}
            </span>
          </div>
          {selectedNode.extra?.title != null && (
            <p className="mt-1.5 text-[10px] leading-relaxed text-muted-foreground">{String(selectedNode.extra.title).slice(0, 80)}</p>
          )}
          {selectedNode.extra?.method != null && (
            <p className="label-tech mt-1.5 !text-[9px] normal-case !tracking-normal">方法 · {String(selectedNode.extra.method)}</p>
          )}
          {selectedNode.extra?.year != null && (
            <p className="label-tech mt-1 !text-[9px] normal-case !tracking-normal">年份 · {String(selectedNode.extra.year)}</p>
          )}
        </div>
      )}

      {/* 视图控制 */}
      <div className="absolute bottom-2.5 left-2.5">
        <button
          className="label-tech h-8 rounded-[5px] border bg-card px-2.5 transition-colors hover:bg-accent !text-[9px]"
          onClick={() => setTransform({ k: 1, x: 0, y: 0 })}
          type="button"
          aria-label="重置视图缩放与平移"
        >
          RESET VIEW
        </button>
      </div>
    </div>
  );
}
