'use client';

/**
 * CryoAgent Pro — 序列理化分析 (BENCH 设计系统)
 * 蛋白质: 分子量/等电点/GRAVY/稳定性/氨基酸组成/二级结构倾向/疏水性剖面/消光系数
 * 核酸: GC 含量/Tm/碱基组成/GC 滑动窗口/ORF/翻译/密码子使用
 */

import { useMemo, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import {
  ArrowRight, ChevronDown, Copy, Download, Loader2, Play, TriangleAlert,
} from 'lucide-react';

// ============ 类型定义 (API 契约) ============

interface AminoAcidCount {
  code: string;
  name: string;
  count: number;
  percent: number;
  mw: number;
  hydropathy: number;
  volume: number;
}

interface ProteinResult {
  length: number;
  molecularWeight: number;
  molecularWeightKDa: number;
  theoreticalPi: number;
  gravy: number;
  instabilityIndex: number;
  stabilityClass: string;
  aromaticity: number;
  chargedResidues: { positive: number; negative: number; net: number };
  ssTendency: { helix: number; sheet: number; turn: number };
  aminoAcids: AminoAcidCount[];
  compositionChart: { code: string; count: number; percent: number }[];
  hydropathyPlot: { position: number; value: number }[];
  hydropathyBins: { range: string; count: number }[];
  extinctionCoefficient: { reduced: number; oxidized: number };
  nTerm: string;
  cTerm: string;
  validProtein: boolean;
  warnings: string[];
}

interface NucleicResult {
  length: number;
  gcContent: number;
  atContent: number;
  baseCounts: { base: string; count: number; percent: number }[];
  isRna: boolean;
  meltingTemp: number;
  molecularWeight: number;
  baseDistribution: { position: number; gcWindow: number }[];
  orfs: { start: number; end: number; length: number; strand: string; proteinLength: number }[];
  proteinTranslation: string;
  codonStats: { codon: string; aminoAcid: string; count: number }[];
  warnings: string[];
}

interface AnalyzeResponse {
  type: 'protein' | 'nucleic';
  sourceLabel: string;
  seqName: string;
  sequenceLength: number;
  result: ProteinResult | NucleicResult;
}

// ============ 示例序列 ============

const EXAMPLE_PROTEIN = 'MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHFDLSHGSAQVKGHGKKVADALTNAVAHVDDMPNALSALSDLHAHKLRVDPVNFKLLSHCLLVTLAAHLPAEFTPAVHASLDKFLASVSTVLTSKYR';
const EXAMPLE_NUCLEIC = 'ACGTTCAATGGCTGCTGCTGCTGCTGCTGCTGCTGCTGCTGCTTAACCGGATGGCGAAATTCTAAACGTTTAGCATGCATGGTAA';

// BENCH 图表轴 / 提示框样式 (与标杆视图一致)
const AXIS = { fontSize: 9, fontFamily: 'var(--font-plex-mono), monospace', fill: 'currentColor', opacity: 0.55 };
/** 深色玻璃 tooltip — recharts 内联样式不跟随主题 class 切换, 用固定 rgba (深浅两主题通用) */
const TOOLTIP_STYLE = {
  fontSize: 11,
  fontFamily: 'var(--font-plex-mono), monospace',
  borderRadius: 8,
  border: '1px solid color-mix(in srgb, var(--primary) 32%, transparent)',
  background: 'rgba(36, 34, 32, 0.95)',
  color: '#faf8f5',
  padding: '4px 10px',
  boxShadow: '0 4px 12px rgba(0, 0, 0, 0.18)',
};

/** 碱基分类编码 — chart 色彩体系 */
const BASE_COLORS: Record<string, string> = {
  A: 'var(--chart-1)',
  T: 'var(--chart-2)',
  U: 'var(--chart-2)',
  G: 'var(--chart-5)',
  C: 'var(--chart-4)',
  N: 'var(--muted-foreground)',
};

/** 长序列降采样, 保证图表渲染流畅 */
function downsample<T>(data: T[], maxPoints = 600): T[] {
  if (data.length <= maxPoints) return data;
  const step = Math.ceil(data.length / maxPoints);
  const out: T[] = [];
  for (let i = 0; i < data.length; i += step) out.push(data[i]);
  if (out[out.length - 1] !== data[data.length - 1]) out.push(data[data.length - 1]);
  return out;
}

// ============ BENCH 面板基元 ============

function SectionCard({
  title, hint, action, children, className,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn('rounded-lg border bg-card', className)}>
      <div className="flex items-center gap-3 border-b px-4 py-2.5">
        <span className="label-tech !text-[10px] text-foreground/75">{title}</span>
        {hint && <span className="label-tech ml-auto !text-[9px]">{hint}</span>}
        {action}
      </div>
      <div className="p-3 md:p-4">{children}</div>
    </section>
  );
}

/** 精确空态 — mono 指引而非占位插画 */
function Empty({ text }: { text: string }) {
  return (
    <div className="label-tech flex h-full min-h-[88px] items-center justify-center px-4 py-8 text-center !text-[10px] normal-case !tracking-[0.06em]">
      {text}
    </div>
  );
}

/** 指标格 — hairline 网格单元 */
function MetricCell({
  label, value, unit, hint, tone,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  tone?: 'teal' | 'emerald' | 'amber' | 'rose';
}) {
  const toneClass =
    tone === 'emerald' ? 'text-chart-1'
      : tone === 'amber' ? 'text-chart-2'
        : tone === 'rose' ? 'text-chart-4'
          : 'text-primary';
  return (
    <div className="min-w-0 bg-card px-4 py-3">
      <div className="label-tech !text-[9px]">{label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className={cn('num text-[20px] font-medium leading-none tracking-tight', tone && toneClass)}>{value}</span>
        {unit && <span className="label-tech !text-[9px]">{unit}</span>}
      </div>
      {hint && <div className="label-tech mt-1.5 !text-[9px] normal-case !tracking-normal text-muted-foreground/70">{hint}</div>}
    </div>
  );
}

/** 分类比例条 — 仪器式细条 */
function BarRow({ label, value, max, tone }: { label: string; value: number; max: number; tone: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[11px]">
        <span className="font-medium">{label}</span>
        <span className="num text-muted-foreground">{value.toFixed(1)}%</span>
      </div>
      <div className="h-[6px] overflow-hidden rounded-[2px] bg-muted">
        <div className={cn('h-full rounded-[2px] transition-all', tone)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ============ 蛋白质结果 ============

function ProteinResults({ resp }: { resp: AnalyzeResponse & { type: 'protein'; result: ProteinResult } }) {
  const r = resp.result;

  const compData = useMemo(() => r.compositionChart.slice(0, 20), [r]);
  const hydData = useMemo(
    () =>
      downsample(r.hydropathyPlot).map((p) => ({
        position: p.position,
        value: p.value,
        hydro: p.value > 1.6 ? p.value : null,
      })),
    [r]
  );
  const maxSS = Math.max(r.ssTendency.helix, r.ssTendency.sheet, r.ssTendency.turn, 1);

  return (
    <div className="space-y-4">
      {/* 关键指标 — hairline 网格 */}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border md:grid-cols-3 xl:grid-cols-6">
        <MetricCell label="分子量" value={r.molecularWeightKDa.toFixed(2)} unit="kDa" hint={`${r.molecularWeight.toLocaleString()} Da`} />
        <MetricCell label="等电点 pI" value={r.theoreticalPi.toFixed(2)} hint={r.theoreticalPi > 7 ? '碱性蛋白' : '酸性蛋白'} tone="teal" />
        <MetricCell
          label="GRAVY 疏水性"
          value={r.gravy.toFixed(3)}
          hint={r.gravy > 0 ? '整体偏疏水' : '整体偏亲水'}
          tone={r.gravy > 0 ? 'amber' : 'emerald'}
        />
        <MetricCell
          label="稳定性"
          value={r.instabilityIndex.toFixed(1)}
          hint={`不稳定指数 · ${r.stabilityClass}`}
          tone={r.stabilityClass === '稳定' ? 'emerald' : 'rose'}
        />
        <MetricCell label="芳香度" value={r.aromaticity.toFixed(2)} unit="%" hint="W / Y / F 占比" />
        <MetricCell
          label="净电荷 (pH7)"
          value={r.chargedResidues.net > 0 ? `+${r.chargedResidues.net}` : String(r.chargedResidues.net)}
          hint={`正 ${r.chargedResidues.positive} / 负 ${r.chargedResidues.negative}`}
          tone={r.chargedResidues.net >= 0 ? 'teal' : 'rose'}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 氨基酸组成 */}
        <SectionCard title="氨基酸组成 · COMPOSITION" hint={`前 ${compData.length} 种 · 共 ${r.length} AA`}>
          <div className="h-[300px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={compData} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 4 }}>
                <CartesianGrid strokeDasharray="2 5" stroke="currentColor" horizontal={false} opacity={0.08} />
                <XAxis type="number" unit="%" tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={{ opacity: 0.2 }} />
                <YAxis type="category" dataKey="code" width={32} tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={false} />
                <Tooltip
                  formatter={(value, _name, item) => [`${Number(value).toFixed(2)}% (${item?.payload?.count ?? 0} 个)`, '占比']}
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: 'var(--accent)', opacity: 0.5 }}
                />
                <Bar dataKey="percent" radius={[0, 3, 3, 0]} fill="var(--chart-1)" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-3 max-h-56 overflow-y-auto custom-scrollbar rounded-md border">
            <table className="bench">
              <thead>
                <tr>
                  <th>残基</th>
                  <th>名称</th>
                  <th className="!text-right">数量</th>
                  <th className="!text-right">占比</th>
                  <th className="!text-right">疏水性</th>
                </tr>
              </thead>
              <tbody>
                {r.aminoAcids.filter((a) => a.count > 0).map((a) => (
                  <tr key={a.code}>
                    <td className="font-mono font-semibold text-primary">{a.code}</td>
                    <td className="text-muted-foreground">{a.name}</td>
                    <td className="num text-right">{a.count}</td>
                    <td className="num text-right">{a.percent.toFixed(2)}%</td>
                    <td className={cn('num text-right', a.hydropathy > 0 ? 'text-chart-2' : 'text-chart-1')}>
                      {a.hydropathy.toFixed(1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <div className="space-y-4">
          {/* 二级结构倾向 */}
          <SectionCard title="二级结构倾向 · SS TENDENCY" hint="Chou-Fasman 参数">
            <div className="space-y-3.5">
              <BarRow label="α-螺旋 Helix" value={r.ssTendency.helix} max={maxSS} tone="bg-chart-1" />
              <BarRow label="β-折叠 Sheet" value={r.ssTendency.sheet} max={maxSS} tone="bg-chart-3" />
              <BarRow label="β-转角 Turn" value={r.ssTendency.turn} max={maxSS} tone="bg-chart-2" />
            </div>
            <p className="mt-3 text-[11px] text-muted-foreground">
              三类倾向归一化为相对比例, 数值越高表示该类二级结构元件出现可能性越大。
            </p>
          </SectionCard>

          {/* 消光系数 + 末端 */}
          <SectionCard title="消光系数与末端序列 · ε280" hint="Gill-Von Hippel">
            <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border bg-border">
              <div className="bg-card px-4 py-3">
                <div className="label-tech !text-[9px]">还原态 ε280</div>
                <div className="num mt-1 text-[18px] font-medium leading-none text-chart-1">
                  {r.extinctionCoefficient.reduced.toLocaleString()}
                </div>
                <div className="label-tech mt-1.5 !text-[9px] normal-case !tracking-normal text-muted-foreground/70">M⁻¹·cm⁻¹ · 所有 Cys 还原</div>
              </div>
              <div className="bg-card px-4 py-3">
                <div className="label-tech !text-[9px]">氧化态 ε280</div>
                <div className="num mt-1 text-[18px] font-medium leading-none text-chart-1">
                  {r.extinctionCoefficient.oxidized.toLocaleString()}
                </div>
                <div className="label-tech mt-1.5 !text-[9px] normal-case !tracking-normal text-muted-foreground/70">M⁻¹·cm⁻¹ · 二硫键形成</div>
              </div>
              <div className="bg-card px-4 py-3">
                <div className="label-tech !text-[9px]">N 端 · 前 10 AA</div>
                <div className="seq-mono mt-1.5 text-xs font-semibold leading-relaxed">{r.nTerm}</div>
              </div>
              <div className="bg-card px-4 py-3">
                <div className="label-tech !text-[9px]">C 端 · 末 10 AA</div>
                <div className="seq-mono mt-1.5 text-xs font-semibold leading-relaxed">{r.cTerm}</div>
              </div>
            </div>
          </SectionCard>
        </div>
      </div>

      {/* 疏水性剖面 */}
      <SectionCard title="疏水性剖面 · HYDROPATHY" hint="Kyte-Doolittle · 窗口 9">
        <div className="h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={hydData} margin={{ top: 12, right: 24, bottom: 4, left: 0 }}>
              <CartesianGrid strokeDasharray="2 5" stroke="currentColor" vertical={false} opacity={0.08} />
              <XAxis dataKey="position" type="number" domain={['dataMin', 'dataMax']} tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={{ opacity: 0.2 }} />
              <YAxis domain={[-4.5, 4.5]} tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={false} width={32} />
              <Tooltip
                formatter={(value) => [Number(value).toFixed(2), '疏水性']}
                labelFormatter={(label) => `残基位置 ${label}`}
                contentStyle={TOOLTIP_STYLE}
              />
              <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeDasharray="3 4" opacity={0.4} />
              <ReferenceLine
                y={1.6}
                stroke="var(--chart-2)"
                strokeDasharray="5 3"
                label={{ value: '疏水阈值 1.6', position: 'insideTopRight', fontSize: 9, fill: 'var(--chart-2)', fontFamily: 'var(--font-plex-mono), monospace' }}
              />
              <Line type="monotone" dataKey="value" stroke="var(--chart-5)" strokeWidth={1.5} dot={false} name="疏水性" />
              <Line type="monotone" dataKey="hydro" stroke="var(--chart-1)" strokeWidth={2.25} dot={false} connectNulls={false} name="疏水区 (>1.6)" />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {r.hydropathyBins.map((b) => (
            <span key={b.range} className="rounded-[3px] border px-1.5 py-px font-mono text-[9px] text-muted-foreground">
              {b.range}: {b.count} 位点
            </span>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          加粗 teal 区段为高于 1.6 阈值的潜在跨膜 / 疏水核心区域。
        </p>
      </SectionCard>
    </div>
  );
}

// ============ 核酸结果 ============

function NucleicResults({ resp }: { resp: AnalyzeResponse & { type: 'nucleic'; result: NucleicResult } }) {
  const r = resp.result;
  const navigate = useAppStore((s) => s.navigate);
  const [translationOpen, setTranslationOpen] = useState(false);

  const gcData = useMemo(() => downsample(r.baseDistribution), [r]);
  const maxCodon = Math.max(...r.codonStats.map((c) => c.count), 1);

  const copyTranslation = async () => {
    try {
      await navigator.clipboard.writeText(r.proteinTranslation);
      toast.success('翻译序列已复制');
    } catch {
      toast.error('复制失败');
    }
  };

  return (
    <div className="space-y-4">
      {/* 关键指标 — hairline 网格 */}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border md:grid-cols-3 xl:grid-cols-6">
        <MetricCell label="序列长度" value={r.length.toLocaleString()} unit="nt" />
        <MetricCell label="GC 含量" value={r.gcContent.toFixed(1)} unit="%" tone="teal" hint={`${r.baseCounts.find((b) => b.base === 'G')?.count ?? 0} G + ${r.baseCounts.find((b) => b.base === 'C')?.count ?? 0} C`} />
        <MetricCell label="AT 含量" value={r.atContent.toFixed(1)} unit="%" tone="amber" />
        <MetricCell label="解链温度 Tm" value={r.meltingTemp.toFixed(1)} unit="℃" hint="Wallace / GC 经验公式" />
        <MetricCell label="分子量" value={r.molecularWeight.toLocaleString()} unit="Da" />
        <MetricCell label="核酸类型" value={r.isRna ? 'RNA' : 'DNA'} hint={r.isRna ? '含 U 无 T' : '含 T'} tone="emerald" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 碱基组成 */}
        <SectionCard title="碱基组成 · BASE COMPOSITION" hint="四碱基占比">
          <div className="flex flex-col items-center gap-4 sm:flex-row">
            <div className="h-[200px] w-[220px] shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={r.baseCounts}
                    dataKey="count"
                    nameKey="base"
                    cx="50%"
                    cy="50%"
                    innerRadius={48}
                    outerRadius={78}
                    paddingAngle={2}
                    stroke="var(--card)"
                    strokeWidth={1}
                  >
                    {r.baseCounts.map((b) => (
                      <Cell key={b.base} fill={BASE_COLORS[b.base] ?? 'var(--muted-foreground)'} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value, name) => [`${value} 个`, `碱基 ${name}`]}
                    contentStyle={TOOLTIP_STYLE}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="w-full space-y-2">
              {r.baseCounts.map((b) => (
                <div key={b.base} className="flex items-center gap-2.5">
                  <span className="h-2.5 w-2.5 shrink-0 rounded-[2px]" style={{ background: BASE_COLORS[b.base] ?? 'var(--muted-foreground)' }} />
                  <span className="num w-6 font-mono text-xs font-bold">{b.base}</span>
                  <div className="h-[6px] flex-1 overflow-hidden rounded-[2px] bg-muted">
                    <div className="h-full rounded-[2px]" style={{ width: `${b.percent}%`, background: BASE_COLORS[b.base] ?? 'var(--muted-foreground)' }} />
                  </div>
                  <span className="num w-24 text-right text-[11px] text-muted-foreground">
                    {b.count} · {b.percent.toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </SectionCard>

        {/* GC 滑动窗口 */}
        <SectionCard title="GC 滑动窗口 · GC WINDOW" hint="窗口 30 nt">
          <div className="h-[260px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={gcData} margin={{ top: 12, right: 24, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="2 5" stroke="currentColor" vertical={false} opacity={0.08} />
                <XAxis dataKey="position" type="number" domain={['dataMin', 'dataMax']} tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={{ opacity: 0.2 }} />
                <YAxis unit="%" domain={[0, 100]} tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={false} width={32} />
                <Tooltip
                  formatter={(value) => [`${Number(value).toFixed(1)}%`, '窗口 GC']}
                  labelFormatter={(label) => `位置 ${label}`}
                  contentStyle={TOOLTIP_STYLE}
                />
                <ReferenceLine y={50} stroke="var(--chart-2)" strokeDasharray="5 3" label={{ value: '50%', position: 'insideTopRight', fontSize: 9, fill: 'var(--chart-2)', fontFamily: 'var(--font-plex-mono), monospace' }} />
                <Line type="monotone" dataKey="gcWindow" stroke="var(--chart-1)" strokeWidth={1.75} dot={false} name="GC%" />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            GC 含量显著偏离 50% 的区段可能影响退火温度与二级结构稳定性。
          </p>
        </SectionCard>
      </div>

      {/* ORF 表 */}
      <SectionCard title="开放阅读框 · ORF" hint={`${r.orfs.length} 个 ≥30 nt · 正链 3 框`}>
        {r.orfs.length > 0 ? (
          <div className="max-h-64 overflow-y-auto custom-scrollbar rounded-md border">
            <table className="bench">
              <thead>
                <tr>
                  <th>阅读框</th>
                  <th className="!text-right">起始 (nt)</th>
                  <th className="!text-right">终止 (nt)</th>
                  <th className="!text-right">长度 (nt)</th>
                  <th className="!text-right">蛋白长度 (aa)</th>
                </tr>
              </thead>
              <tbody>
                {r.orfs.map((o, i) => (
                  <tr key={`${o.start}-${i}`}>
                    <td className="font-mono">{o.strand}</td>
                    <td className="num text-right">{o.start}</td>
                    <td className="num text-right">{o.end}</td>
                    <td className="num text-right">{o.length}</td>
                    <td className="num text-right font-semibold text-primary">{o.proteinLength}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty text="NO ORF — 未发现 ≥30 nt 的完整阅读框 (含起始密码子与终止密码子)" />
        )}
      </SectionCard>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 翻译蛋白序列 */}
        <SectionCard
          title="翻译蛋白序列 · TRANSLATION"
          hint={r.proteinTranslation ? `${r.proteinTranslation.length} AA · 最长 ORF` : undefined}
        >
          {r.proteinTranslation ? (
            <Collapsible open={translationOpen} onOpenChange={setTranslationOpen}>
              <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 rounded-md border bg-muted/30 px-3 py-2 text-left transition-colors hover:bg-muted/60">
                <span className="seq-mono truncate text-xs">{r.proteinTranslation.slice(0, 60)}…</span>
                <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform', translationOpen && 'rotate-180')} />
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="seq-mono mt-2 max-h-56 overflow-y-auto custom-scrollbar rounded-md border bg-muted/30 p-3 text-xs leading-relaxed">
                  {r.proteinTranslation}
                </div>
              </CollapsibleContent>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" onClick={copyTranslation}>
                  <Copy className="h-3 w-3" strokeWidth={1.75} />复制序列
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-1.5 text-xs"
                  onClick={() => navigate('alignment', { seq: r.proteinTranslation })}
                >
                  <ArrowRight className="h-3 w-3" strokeWidth={1.75} />发送到序列比对
                </Button>
              </div>
            </Collapsible>
          ) : (
            <Empty text="NO ORF — 无可翻译的开放阅读框" />
          )}
        </SectionCard>

        {/* 密码子使用 */}
        <SectionCard title="密码子使用偏好 · CODON USAGE" hint="翻译区前 12 位">
          {r.codonStats.length > 0 ? (
            <div className="max-h-[280px] space-y-2 overflow-y-auto custom-scrollbar pr-1">
              {r.codonStats.slice(0, 12).map((c) => (
                <div key={c.codon} className="flex items-center gap-2.5">
                  <span className="num w-12 font-mono text-xs font-bold">{c.codon}</span>
                  <span className="w-6 shrink-0 rounded-[3px] border px-1 py-px text-center font-mono text-[9px] text-muted-foreground">{c.aminoAcid}</span>
                  <div className="h-[6px] flex-1 overflow-hidden rounded-[2px] bg-muted">
                    <div className="h-full rounded-[2px] bg-chart-1" style={{ width: `${(c.count / maxCodon) * 100}%` }} />
                  </div>
                  <span className="num w-8 text-right text-[11px] text-muted-foreground">{c.count}</span>
                </div>
              ))}
            </div>
          ) : (
            <Empty text="NO DATA — 无密码子统计数据" />
          )}
        </SectionCard>
      </div>
    </div>
  );
}

// ============ 主组件 ============

export function SequenceAnalyzerView() {
  const viewParams = useAppStore((s) => s.viewParams);
  const [sequence, setSequence] = useState(() => viewParams.seq ?? '');
  const [source, setSource] = useState<'raw' | 'pdb' | 'uniprot'>('raw');
  const [sourceId, setSourceId] = useState('');
  const [type, setType] = useState<string>('auto');
  const [analyzing, setAnalyzing] = useState(false);
  const [response, setResponse] = useState<AnalyzeResponse | null>(null);
  const [error, setError] = useState('');

  const prefilled = Boolean(viewParams.seq);

  const runAnalysis = async () => {
    const seq = sequence.replace(/\s/g, '');
    if (source === 'raw' && !seq) { toast.error('请输入序列'); return; }
    if (source !== 'raw' && !sourceId.trim()) { toast.error(source === 'pdb' ? '请输入 PDB ID' : '请输入 UniProt ID'); return; }

    setAnalyzing(true);
    setError('');
    setResponse(null);
    try {
      const body = source === 'raw' ? { sequence: seq, type } : { source, sourceId: sourceId.trim(), type };
      const d = await api<AnalyzeResponse>('/api/sequence/analyze', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setResponse(d);
      toast.success(d.type === 'protein' ? `蛋白质分析完成 · ${d.result.length} aa` : `核酸分析完成 · ${d.result.length} nt`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '分析失败';
      setError(msg);
      toast.error(msg);
    } finally {
      setAnalyzing(false);
    }
  };

  const exportJson = () => {
    if (!response) return;
    try {
      const blob = new Blob([JSON.stringify(response, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `cryoagent-sequence-analysis-${Date.now()}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success('分析结果已导出为 JSON');
    } catch {
      toast.error('导出失败');
    }
  };

  const warnings = response?.result.warnings ?? [];

  const sourceOptions: { value: 'raw' | 'pdb' | 'uniprot'; label: string }[] = [
    { value: 'raw', label: '直接输入' },
    { value: 'pdb', label: 'PDB' },
    { value: 'uniprot', label: 'UniProt' },
  ];

  return (
    <div className="animate-fade-in-up">
      {/* ===== Masthead — 坐标纸 + 模块代号 ===== */}
      <div className="grid-bg relative border-b">
        <div className="flex flex-wrap items-end justify-between gap-4 px-4 py-6 md:px-6">
          <div>
            <div className="label-tech !text-[10px]">Protein Profile · 序列理化分析</div>
            <h1 className="font-display mt-1.5 text-[26px] font-semibold leading-none tracking-tight md:text-[30px]">
              序列理化分析
              <span className="title-accent">Sequence Profiling</span>
            </h1>
            <p className="mt-2.5 max-w-lg text-xs leading-relaxed text-muted-foreground">
              蛋白质 / 核酸序列理化性质计算 — 分子量 · 等电点 · GRAVY 疏水性 · 二级结构倾向 · ORF 与密码子偏好, 类型自动检测
            </p>
          </div>
          <div className="label-tech space-y-1.5 text-right !text-[10px]">
            <div className="flex items-center justify-end gap-2">
              <span className="status-dot" aria-hidden /> AUTO TYPE DETECT
            </div>
            <div className="text-muted-foreground/60">PROTEIN / NUCLEIC</div>
            <div className="text-muted-foreground/60">RCSB · UNIPROT HOOK</div>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-4 md:p-6">
        {prefilled && (
          <div className="flex items-center gap-2.5 rounded-lg border border-primary/30 bg-accent/40 px-4 py-2.5">
            <span className="status-dot" aria-hidden />
            <p className="text-xs text-accent-foreground">已从结构详情预填序列 — 点击「开始分析」即可计算理化性质。</p>
          </div>
        )}

        {/* ===== 序列输入 ===== */}
        <section className="rounded-lg border bg-card">
          <div className="flex items-center gap-3 border-b px-4 py-2.5">
            <span className="label-tech !text-[10px] text-foreground/75">序列输入 · INPUT</span>
            <span className="label-tech ml-auto !text-[9px]">单字母编码 · 自动忽略空白</span>
          </div>
          <div className="flex flex-col gap-4 p-4 lg:flex-row">
            <div className="min-w-0 flex-1 space-y-3">
              <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="序列来源">
                {sourceOptions.map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    role="radio"
                    aria-checked={source === o.value}
                    onClick={() => setSource(o.value)}
                    className={cn(
                      'flex h-11 items-center rounded-[5px] border px-3 text-xs transition-colors sm:h-8',
                      source === o.value
                        ? 'border-primary/50 bg-accent font-medium text-accent-foreground'
                        : 'border-input bg-card text-muted-foreground hover:border-foreground/25 hover:text-foreground'
                    )}
                  >
                    {o.label}
                  </button>
                ))}
              </div>

              {source === 'raw' ? (
                <>
                  <div className="flex items-center justify-between">
                    <label className="label-tech !text-[9px] normal-case !tracking-[0.06em]" htmlFor="analyzer-seq">
                      序列 · 单字母编码
                    </label>
                    <span className="num text-[10px] text-muted-foreground">
                      {sequence.replace(/\s/g, '').length} 字符
                    </span>
                  </div>
                  <Textarea
                    id="analyzer-seq"
                    value={sequence}
                    onChange={(e) => setSequence(e.target.value)}
                    placeholder="粘贴氨基酸序列 (如 MKT…) 或核酸序列 (如 ATGGCT…)…"
                    className="min-h-[110px] resize-y font-mono text-xs leading-relaxed"
                    spellCheck={false}
                    aria-label="序列输入"
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline" size="sm" className="h-11 gap-1.5 text-xs sm:h-8"
                      onClick={() => { setSource('raw'); setSequence(EXAMPLE_PROTEIN); }}
                    >
                      示例 · 血红蛋白 α ({EXAMPLE_PROTEIN.length} AA)
                    </Button>
                    <Button
                      variant="outline" size="sm" className="h-11 gap-1.5 text-xs sm:h-8"
                      onClick={() => { setSource('raw'); setSequence(EXAMPLE_NUCLEIC); }}
                    >
                      示例 · DNA 片段 ({EXAMPLE_NUCLEIC.length} NT)
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <label className="label-tech !text-[9px] normal-case !tracking-[0.06em]" htmlFor="analyzer-source-id">
                    {source === 'pdb' ? 'PDB ID' : 'UniProt Accession'}
                  </label>
                  <Input
                    id="analyzer-source-id"
                    value={sourceId}
                    onChange={(e) => { setSource(source); setSourceId(e.target.value.toUpperCase()); }}
                    placeholder={source === 'pdb' ? '例如 6M0J' : '例如 P69905'}
                    className="h-9 font-mono text-xs"
                    aria-label={source === 'pdb' ? 'PDB ID 输入' : 'UniProt Accession 输入'}
                  />
                  <p className="text-[11px] text-muted-foreground">
                    {source === 'pdb' ? '从 RCSB 结构提取首个实体序列 · 服务端缓存' : '从 UniProt 条目获取参考序列'}
                  </p>
                </>
              )}
            </div>

            <div className="w-full shrink-0 space-y-3 lg:w-[200px]">
              <div className="space-y-1.5">
                <label className="label-tech !text-[9px] normal-case !tracking-[0.06em]" htmlFor="analyzer-type">
                  序列类型
                </label>
                <Select value={type} onValueChange={setType}>
                  <SelectTrigger id="analyzer-type" aria-label="序列类型" className="h-9 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">自动检测</SelectItem>
                    <SelectItem value="protein">蛋白质</SelectItem>
                    <SelectItem value="nucleic">核酸</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button onClick={runAnalysis} disabled={analyzing} className="w-full gap-2">
                {analyzing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" strokeWidth={1.75} />}
                {analyzing ? '分析中…' : '开始分析'}
              </Button>
            </div>
          </div>
        </section>

        {/* 错误 */}
        {error && !analyzing && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4" role="alert">
            <div className="label-tech !text-[10px] !text-destructive">ANALYSIS FAILED</div>
            <p className="mt-1 text-sm text-destructive">{error}</p>
          </div>
        )}

        {/* 加载骨架 */}
        {analyzing && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
              {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="shimmer h-[88px] rounded-lg" />)}
            </div>
            <Skeleton className="shimmer h-[300px] w-full rounded-lg" />
          </div>
        )}

        {/* 结果 */}
        {response && !analyzing && (
          <div className="space-y-4">
            {/* 来源信息 + 导出 */}
            <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-card px-4 py-2.5">
              <span
                className={cn(
                  'shrink-0 rounded-[3px] border px-1.5 py-px font-mono text-[9px] font-medium',
                  response.type === 'protein' ? 'border-chart-1/50 text-chart-1' : 'border-chart-3/50 text-chart-3'
                )}
              >
                {response.type === 'protein' ? 'PROTEIN' : 'NUCLEIC'}
              </span>
              <span className="num min-w-0 truncate text-xs text-muted-foreground">
                来源 {response.sourceLabel}
                {response.seqName ? ` · ${response.seqName}` : ''} · {response.sequenceLength} {response.type === 'protein' ? 'AA' : 'NT'}
              </span>
              <button
                type="button"
                onClick={exportJson}
                className="label-tech ml-auto flex shrink-0 items-center gap-1 !text-[9px] !text-primary transition-opacity hover:opacity-70"
              >
                导出 JSON <Download className="h-3 w-3" strokeWidth={1.75} />
              </button>
            </div>

            {/* 警告 */}
            {warnings.length > 0 && (
              <div className="flex gap-3 rounded-lg border border-chart-2/40 bg-chart-2/5 p-4" role="alert">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-chart-2" strokeWidth={1.75} />
                <div className="space-y-1 text-xs text-foreground/80">
                  {warnings.map((w, i) => <p key={i}>· {w}</p>)}
                </div>
              </div>
            )}

            {response.type === 'protein' ? (
              <ProteinResults resp={response as AnalyzeResponse & { type: 'protein'; result: ProteinResult }} />
            ) : (
              <NucleicResults resp={response as AnalyzeResponse & { type: 'nucleic'; result: NucleicResult }} />
            )}
          </div>
        )}

        {!response && !analyzing && !error && (
          <section className="rounded-lg border bg-card">
            <Empty text="NO RESULT — 粘贴序列或指定 PDB / UniProt ID 后开始分析, 将计算分子量 · 等电点 · 疏水性 · 二级结构倾向 等指标" />
          </section>
        )}
      </div>
    </div>
  );
}
