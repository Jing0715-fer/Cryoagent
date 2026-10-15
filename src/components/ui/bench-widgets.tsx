'use client';

/**
 * WARM BENCH 质感组件库 — 参照 pdb-tracker-web-v5 组件模式
 * AnimatedNumber / StatCard / MiniDonut / MiniRing / MiniBar / 
 * MethodBadge / MethodDot / SegmentedTabs / ShimmerBox
 *
 * 设计语言: 赤陶信号色 + 领域方法色 + 淡底徽章 + 滑动药丸 Tab + 计数动画
 */

import React, { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils';

/* ============ AnimatedNumber — rAF 计数动画 (easeOutCubic) ============ */

export function useAnimatedValue(target: number, duration = 800): number {
  const [current, setCurrent] = useState(target);
  const prevRef = useRef(target);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (prevRef.current === target) return;
    const start = prevRef.current;
    const diff = target - start;
    const startTime = performance.now();

    const tick = (now: number) => {
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setCurrent(Math.round(start + diff * eased));
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        prevRef.current = target;
        setCurrent(target);
      }
    };
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [target, duration]);

  useEffect(() => {
    prevRef.current = target;
  }, [target]);

  return current;
}

export function AnimatedNumber({
  value,
  decimals = 0,
  suffix = '',
  className,
}: {
  value: number;
  decimals?: number;
  suffix?: string;
  className?: string;
}) {
  const scaled = Math.round(value * Math.pow(10, decimals));
  const animated = useAnimatedValue(scaled, 800);
  const display = (animated / Math.pow(10, decimals)).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return (
    <span className={cn('num tabular-nums inline-block', className)}>
      {display}
      {suffix}
    </span>
  );
}

/* ============ 领域方法色 — 统一映射 (X-ray 紫罗兰 / Cryo-EM 青绿 / NMR 琥珀 / PRED 石板) ============ */

export type MethodKey = 'xray' | 'cryoem' | 'nmr' | 'pred' | 'other';

export function methodKey(method: string | null | undefined): MethodKey {
  const m = (method || '').toUpperCase();
  if (m.includes('X-RAY') || m.includes('DIFFRACTION')) return 'xray';
  if (m.includes('ELECTRON MICROSCOPY') || m.includes('CRYO')) return 'cryoem';
  if (m.includes('NMR')) return 'nmr';
  if (m.includes('ALPHAFOLD') || m.includes('PREDICT')) return 'pred';
  return 'other';
}

export function methodShort(method: string | null | undefined): string {
  const m = (method || '').toUpperCase();
  if (m.includes('X-RAY')) return 'X-RAY';
  if (m.includes('ELECTRON MICROSCOPY') || m.includes('CRYO')) return 'CRYO-EM';
  if (m.includes('NMR')) return 'NMR';
  if (m.includes('ALPHAFOLD') || m.includes('PREDICT')) return 'PRED';
  return method ? method.slice(0, 8).toUpperCase() : '—';
}

export function methodHex(): Record<MethodKey, string> {
  return {
    xray: 'var(--method-xray)',
    cryoem: 'var(--method-cryoem)',
    nmr: 'var(--method-nmr)',
    pred: 'var(--method-pred)',
    other: 'var(--muted-foreground)',
  };
}

/** 方法徽章 — 淡底 + 领域色 + 同色细边 (质感优于纯 outline) */
export function MethodBadge({ method, className }: { method: string | null | undefined; className?: string }) {
  const key = methodKey(method);
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-[5px] px-1.5 py-px font-mono text-[9px] font-medium tracking-wide',
        key === 'other' ? 'border border-border bg-muted/60 text-muted-foreground' : `method-${key}`,
        className
      )}
    >
      {methodShort(method)}
    </span>
  );
}

/** 方法圆点 — 紧凑列表用 */
export function MethodDot({ method, className }: { method: string | null | undefined; className?: string }) {
  const key = methodKey(method);
  return (
    <span
      className={cn('inline-block h-[7px] w-[7px] shrink-0 rounded-full', className)}
      style={{ background: methodHex()[key] }}
      aria-hidden
    />
  );
}

/* ============ 迷你可视化 — SVG 指示器 (参考 stat-card.tsx) ============ */

export interface DonutSegment {
  label: string;
  value: number;
  color: string;
}

/** 多段甜甜圈 — 方法分布等 */
export function MiniDonut({
  segments,
  size = 30,
  strokeWidth = 3.5,
  className,
}: {
  segments: DonutSegment[];
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const total = segments.reduce((sum, s) => sum + s.value, 0);

  if (total === 0) {
    return (
      <svg width={size} height={size} className={cn('shrink-0', className)} aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--border)" strokeWidth={strokeWidth} />
      </svg>
    );
  }

  const segs: { length: number; offset: number; color: string }[] = [];
  let acc = 0;
  for (const s of segments) {
    const length = (s.value / total) * circumference;
    segs.push({ length, offset: acc, color: s.color });
    acc += length;
  }

  return (
    <svg width={size} height={size} className={cn('-rotate-90 shrink-0', className)} aria-hidden>
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--border)" strokeWidth={strokeWidth} />
      {segs.map((seg, i) => (
        <circle
          key={i}
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={seg.color}
          strokeWidth={strokeWidth}
          strokeDasharray={`${Math.max(seg.length - 1.5, 0)} ${circumference}`}
          strokeDashoffset={-seg.offset}
          style={{ transition: 'stroke-dasharray 0.6s ease-out, stroke-dashoffset 0.6s ease-out' }}
        />
      ))}
    </svg>
  );
}

/** 进度环 — 完成率/覆盖率 */
export function MiniRing({
  value,
  max = 100,
  color,
  size = 28,
  strokeWidth = 3,
  className,
}: {
  value: number;
  max?: number;
  color: string;
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.min(value / max, 1);
  const offset = circumference * (1 - progress);
  return (
    <svg width={size} height={size} className={cn('-rotate-90 shrink-0', className)} aria-hidden>
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--border)" strokeWidth={strokeWidth} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        style={{ transition: 'stroke-dashoffset 0.6s ease-out' }}
      />
    </svg>
  );
}

/** 水平迷你条 — 占比类指标 */
export function MiniBar({
  value,
  max = 100,
  color,
  width = 48,
  height = 5,
  showPct = true,
  className,
}: {
  value: number;
  max?: number;
  color: string;
  width?: number;
  height?: number;
  showPct?: boolean;
  className?: string;
}) {
  const pct = Math.min(value / max, 1);
  return (
    <svg width={width} height={height + (showPct ? 7 : 2)} className={cn('shrink-0', className)} aria-hidden>
      <rect x={0} y={3} width={width} height={height} rx={height / 2} fill="var(--border)" />
      <rect
        x={0}
        y={3}
        width={Math.max(pct * width, height)}
        height={height}
        rx={height / 2}
        fill={color}
        style={{ transition: 'width 0.6s ease-out' }}
      />
      {showPct && (
        <text x={width / 2} y={height + 8} textAnchor="middle" fontSize="7" fontWeight="600" fill="var(--muted-foreground)" fontFamily="var(--font-plex-mono), monospace">
          {Math.round(pct * 100)}%
        </text>
      )}
    </svg>
  );
}

/* ============ StatCard — KPI 指标卡 (参考 StatCard, 领域色渐变图标瓦片) ============ */

export interface StatCardProps {
  title: string;
  value: number | string;
  suffix?: string;
  decimals?: number;
  /** 图标 (ReactNode, 通常 <Icon className="h-3.5 w-3.5 text-white" />) */
  icon: React.ReactNode;
  /** 图标瓦片渐变 — 传 tailwind 渐变类 如 "from-[#c96442] to-[#a04e32]" */
  gradient: string;
  /** 卡片强调色 (顶线/悬停光晕) — CSS 色值 */
  accent: string;
  subtitle?: string;
  loading?: boolean;
  delay?: number;
  /** 右上角迷你指示器 (MiniDonut / MiniRing / MiniBar / Badge) */
  indicator?: React.ReactNode;
  tooltip?: string;
  className?: string;
  onClick?: () => void;
}

export function StatCard({
  title,
  value,
  suffix = '',
  decimals = 0,
  icon,
  gradient,
  accent,
  subtitle,
  loading,
  delay = 0,
  indicator,
  tooltip,
  className,
  onClick,
}: StatCardProps) {
  const isText = typeof value === 'string';
  const style = {
    '--kpi-accent': accent,
    animationDelay: `${delay}ms`,
  } as React.CSSProperties;

  const inner = (
    <>
      {/* 行 1: 图标瓦片 + 标题 + 指示器 */}
      <div className="mb-1.5 flex items-center gap-2">
        <div className={cn('kpi-icon-tile h-7 w-7 min-w-[28px] shrink-0 bg-gradient-to-br', gradient)}>{icon}</div>
        <div className="label-tech min-w-0 flex-1 !tracking-[0.1em] !text-muted-foreground">{title}</div>
        {indicator && <div className="flex shrink-0 items-center justify-center">{indicator}</div>}
      </div>
      {/* 行 2: 大数字 */}
      <div className="text-xl font-bold leading-tight tracking-tight sm:text-2xl">
        {loading ? (
          <span className="shimmer inline-block h-6 w-16 rounded-md" />
        ) : isText ? (
          <span className="num truncate text-lg sm:text-xl" title={value}>{value}</span>
        ) : (
          <AnimatedNumber value={value as number} decimals={decimals} suffix={suffix} />
        )}
      </div>
      {/* 行 3: 副标题 */}
      <div className={cn('label-tech mt-0.5 truncate normal-case !tracking-normal', !subtitle && 'invisible')}>
        {subtitle || '\u00A0'}
      </div>
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        title={tooltip}
        className={cn(
          'kpi-card stagger-list-item flex w-full min-w-0 flex-col border p-3 text-left sm:p-3.5',
          className
        )}
        style={style}
      >
        {inner}
      </button>
    );
  }
  return (
    <div
      title={tooltip}
      className={cn('kpi-card flex min-w-0 flex-col border p-3 sm:p-3.5', className)}
      style={style}
    >
      {inner}
    </div>
  );
}

/* ============ SegmentedTabs — 滑动药丸分段控制 (参考 mode-segmented-control) ============ */

export interface SegmentedTabOption {
  value: string;
  label: React.ReactNode;
}

export function SegmentedTabs({
  options,
  value,
  onChange,
  className,
  size = 'md',
}: {
  options: SegmentedTabOption[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
  size?: 'sm' | 'md';
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState({ left: 0, width: 0, ready: false });

  useEffect(() => {
    const update = () => {
      const container = containerRef.current;
      if (!container) return;
      const active = container.querySelector<HTMLElement>('[data-active="true"]');
      if (active) setPill({ left: active.offsetLeft, width: active.offsetWidth, ready: true });
    };
    update();
    const id = requestAnimationFrame(update);
    window.addEventListener('resize', update);
    return () => {
      cancelAnimationFrame(id);
      window.removeEventListener('resize', update);
    };
  }, [value, options]);

  return (
    <div
      ref={containerRef}
      role="tablist"
      className={cn(
        'seg-tabs relative inline-flex items-center rounded-full p-[3px]',
        size === 'sm' ? 'text-[11px]' : 'text-xs',
        className
      )}
    >
      {pill.ready && (
        <span
          className="seg-pill absolute top-[3px] h-[calc(100%-6px)] rounded-full"
          style={{ left: pill.left, width: pill.width }}
          aria-hidden
        />
      )}
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role="tab"
            aria-selected={active}
            data-active={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              'seg-tab relative z-10 flex items-center justify-center gap-1.5 rounded-full font-medium',
              size === 'sm' ? 'px-3 py-1' : 'px-3.5 py-[5px]',
              active ? 'text-foreground' : 'text-muted-foreground hover:text-foreground/80'
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/* ============ ShimmerBox — 骨架占位 (动画流光) ============ */

export function ShimmerBox({ className }: { className?: string }) {
  return <span className={cn('shimmer block rounded-md', className)} aria-hidden />;
}

/* ============ 等级徽章 — 分档评分 (评估中心/IF 分档) ============ */

export function TierBadge({ tier, label, className }: { tier: 'top' | 'high' | 'mid' | 'low'; label?: string; className?: string }) {
  const texts: Record<string, string> = { top: 'TOP', high: 'HIGH', mid: 'MID', low: 'LOW' };
  return (
    <span className={cn('tier-badge inline-flex items-center rounded-[5px] px-1.5 py-px font-mono text-[9px] font-medium tracking-wide', `tier-${tier}`, className)}>
      {label || texts[tier]}
    </span>
  );
}
