'use client';

/**
 * CryoAgent Pro — 序列理化分析 (新增功能)
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
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import {
  Activity, ArrowRight, Beaker, ChevronDown, Copy, Dna, Download, FlaskConical, Loader2,
  Play, Ruler, Sparkles, Thermometer, TriangleAlert, Waves,
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

const BASE_COLORS: Record<string, string> = {
  A: '#0d9488',
  T: '#f59e0b',
  U: '#f59e0b',
  G: '#10b981',
  C: '#f43f5e',
  N: '#a3a3a3',
};

const CHART_TEAL = '#0d9488';
const CHART_EMERALD = '#059669';

/** 长序列降采样, 保证图表渲染流畅 */
function downsample<T>(data: T[], maxPoints = 600): T[] {
  if (data.length <= maxPoints) return data;
  const step = Math.ceil(data.length / maxPoints);
  const out: T[] = [];
  for (let i = 0; i < data.length; i += step) out.push(data[i]);
  if (out[out.length - 1] !== data[data.length - 1]) out.push(data[data.length - 1]);
  return out;
}

// ============ 通用指标卡片 ============

function MetricCard({
  label, value, unit, hint, tone,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  tone?: 'teal' | 'emerald' | 'amber' | 'rose';
}) {
  const toneClass =
    tone === 'emerald' ? 'text-emerald-600 dark:text-emerald-400'
      : tone === 'amber' ? 'text-amber-600 dark:text-amber-400'
        : tone === 'rose' ? 'text-rose-600 dark:text-rose-400'
          : 'text-teal-600 dark:text-teal-400';
  return (
    <Card className="p-3 transition-colors hover:border-teal-500/40 md:p-4">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 flex items-baseline gap-1">
        <span className="text-lg font-bold tabular-nums md:text-xl">{value}</span>
        {unit && <span className="text-[11px] text-muted-foreground">{unit}</span>}
      </div>
      {hint && <div className={cn('mt-0.5 text-[10px]', tone ? toneClass : 'text-muted-foreground/70')}>{hint}</div>}
    </Card>
  );
}

function SectionCard({
  icon: Icon, title, subtitle, action, children, className,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn('p-4 md:p-6', className)}>
      <CardHeader className="mb-4 flex-row items-center justify-between space-y-0 p-0">
        <div className="flex items-center gap-2">
          <Icon className="h-4.5 w-4.5 text-teal-600 dark:text-teal-400" />
          <CardTitle className="text-sm">{title}</CardTitle>
          {subtitle && <span className="text-[11px] font-normal text-muted-foreground">{subtitle}</span>}
        </div>
        {action}
      </CardHeader>
      <CardContent className="p-0">{children}</CardContent>
    </Card>
  );
}

function BarRow({ label, value, max, tone }: { label: string; value: number; max: number; tone: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[11px]">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-muted-foreground">{value.toFixed(1)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div className={cn('h-full rounded-full transition-all', tone)} style={{ width: `${pct}%` }} />
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
    <div className="space-y-4 md:space-y-6">
      {/* 关键指标 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MetricCard label="分子量" value={r.molecularWeightKDa.toFixed(2)} unit="kDa" hint={`${r.molecularWeight.toLocaleString()} Da`} />
        <MetricCard label="等电点 pI" value={r.theoreticalPi.toFixed(2)} hint={r.theoreticalPi > 7 ? '碱性蛋白' : '酸性蛋白'} tone="teal" />
        <MetricCard
          label="GRAVY 疏水性"
          value={r.gravy.toFixed(3)}
          hint={r.gravy > 0 ? '整体偏疏水' : '整体偏亲水'}
          tone={r.gravy > 0 ? 'amber' : 'emerald'}
        />
        <MetricCard
          label="稳定性"
          value={r.instabilityIndex.toFixed(1)}
          hint={`不稳定指数 · ${r.stabilityClass}`}
          tone={r.stabilityClass === '稳定' ? 'emerald' : 'rose'}
        />
        <MetricCard label="芳香度" value={r.aromaticity.toFixed(2)} unit="%" hint="W/Y/F 占比" />
        <MetricCard
          label="净电荷 (pH7)"
          value={r.chargedResidues.net > 0 ? `+${r.chargedResidues.net}` : String(r.chargedResidues.net)}
          hint={`正 ${r.chargedResidues.positive} / 负 ${r.chargedResidues.negative}`}
          tone={r.chargedResidues.net >= 0 ? 'teal' : 'rose'}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2 md:gap-6">
        {/* 氨基酸组成 */}
        <SectionCard icon={Beaker} title="氨基酸组成" subtitle={`前 ${compData.length} 种 (共 ${r.length} aa)`}>
          <div className="h-[300px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={compData} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 4 }}>
                <XAxis type="number" unit="%" fontSize={11} stroke="#a1a1aa" />
                <YAxis type="category" dataKey="code" width={32} fontSize={11} stroke="#a1a1aa" />
                <Tooltip
                  formatter={(value, _name, item) => [`${Number(value).toFixed(2)}% (${item?.payload?.count ?? 0} 个)`, '占比']}
                  contentStyle={{ fontSize: 12, borderRadius: 8 }}
                />
                <Bar dataKey="percent" radius={[0, 4, 4, 0]} fill={CHART_TEAL} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-3 max-h-56 overflow-y-auto custom-scrollbar rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="h-8 text-[11px]">残基</TableHead>
                  <TableHead className="h-8 text-[11px]">名称</TableHead>
                  <TableHead className="h-8 text-right text-[11px]">数量</TableHead>
                  <TableHead className="h-8 text-right text-[11px]">占比</TableHead>
                  <TableHead className="h-8 text-right text-[11px]">疏水性</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {r.aminoAcids.filter((a) => a.count > 0).map((a) => (
                  <TableRow key={a.code}>
                    <TableCell className="py-1.5 font-mono text-xs font-bold text-teal-700 dark:text-teal-300">{a.code}</TableCell>
                    <TableCell className="py-1.5 text-xs text-muted-foreground">{a.name}</TableCell>
                    <TableCell className="py-1.5 text-right text-xs tabular-nums">{a.count}</TableCell>
                    <TableCell className="py-1.5 text-right text-xs tabular-nums">{a.percent.toFixed(2)}%</TableCell>
                    <TableCell className={cn('py-1.5 text-right text-xs tabular-nums', a.hydropathy > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400')}>
                      {a.hydropathy.toFixed(1)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </SectionCard>

        <div className="space-y-4 md:space-y-6">
          {/* 二级结构倾向 */}
          <SectionCard icon={Activity} title="二级结构倾向" subtitle="Chou-Fasman 参数">
            <div className="space-y-3.5">
              <BarRow label="α-螺旋 Helix" value={r.ssTendency.helix} max={maxSS} tone="bg-teal-500" />
              <BarRow label="β-折叠 Sheet" value={r.ssTendency.sheet} max={maxSS} tone="bg-emerald-500" />
              <BarRow label="β-转角 Turn" value={r.ssTendency.turn} max={maxSS} tone="bg-amber-500" />
            </div>
            <p className="mt-3 text-[11px] text-muted-foreground">
              三类倾向归一化为相对比例, 数值越高表示该类二级结构元件出现可能性越大。
            </p>
          </SectionCard>

          {/* 消光系数 + 末端 */}
          <SectionCard icon={Ruler} title="消光系数与末端序列" subtitle="ε280 nm">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border bg-muted/40 p-3">
                <div className="text-[11px] text-muted-foreground">还原态 (所有 Cys 还原)</div>
                <div className="mt-1 text-lg font-bold tabular-nums text-teal-600 dark:text-teal-400">
                  {r.extinctionCoefficient.reduced.toLocaleString()}
                </div>
                <div className="text-[10px] text-muted-foreground">M⁻¹·cm⁻¹</div>
              </div>
              <div className="rounded-lg border bg-muted/40 p-3">
                <div className="text-[11px] text-muted-foreground">氧化态 (二硫键形成)</div>
                <div className="mt-1 text-lg font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
                  {r.extinctionCoefficient.oxidized.toLocaleString()}
                </div>
                <div className="text-[10px] text-muted-foreground">M⁻¹·cm⁻¹</div>
              </div>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div className="rounded-lg border p-3">
                <div className="text-[11px] text-muted-foreground">N 端 (前 10 aa)</div>
                <div className="mt-1 break-all font-mono text-xs font-semibold">{r.nTerm}</div>
              </div>
              <div className="rounded-lg border p-3">
                <div className="text-[11px] text-muted-foreground">C 端 (末 10 aa)</div>
                <div className="mt-1 break-all font-mono text-xs font-semibold">{r.cTerm}</div>
              </div>
            </div>
          </SectionCard>
        </div>
      </div>

      {/* 疏水性剖面 */}
      <SectionCard
        icon={Waves}
        title="疏水性剖面"
        subtitle="Kyte-Doolittle · 窗口 9"
      >
        <div className="h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={hydData} margin={{ top: 12, right: 24, bottom: 4, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" vertical={false} />
              <XAxis dataKey="position" type="number" domain={['dataMin', 'dataMax']} fontSize={11} stroke="#a1a1aa" />
              <YAxis domain={[-4.5, 4.5]} fontSize={11} stroke="#a1a1aa" />
              <Tooltip
                formatter={(value) => [Number(value).toFixed(2), '疏水性']}
                labelFormatter={(label) => `残基位置 ${label}`}
                contentStyle={{ fontSize: 12, borderRadius: 8 }}
              />
              <ReferenceLine y={0} stroke="#a1a1aa" strokeDasharray="4 4" />
              <ReferenceLine
                y={1.6}
                stroke="#f59e0b"
                strokeDasharray="6 3"
                label={{ value: '疏水阈值 1.6', position: 'insideTopRight', fontSize: 10, fill: '#f59e0b' }}
              />
              <Line type="monotone" dataKey="value" stroke={CHART_TEAL} strokeWidth={1.5} dot={false} name="疏水性" />
              <Line type="monotone" dataKey="hydro" stroke={CHART_EMERALD} strokeWidth={2.5} dot={false} connectNulls={false} name="疏水区 (>1.6)" />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {r.hydropathyBins.map((b) => (
            <Badge key={b.range} variant="secondary" className="gap-1 font-normal tabular-nums">
              {b.range}: {b.count} 位点
            </Badge>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          深绿加粗区段为高于 1.6 阈值的潜在跨膜 / 疏水核心区域。
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
    <div className="space-y-4 md:space-y-6">
      {/* 关键指标 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MetricCard label="序列长度" value={r.length.toLocaleString()} unit="nt" />
        <MetricCard label="GC 含量" value={r.gcContent.toFixed(1)} unit="%" tone="teal" hint={`${r.baseCounts.find((b) => b.base === 'G')?.count ?? 0} G + ${r.baseCounts.find((b) => b.base === 'C')?.count ?? 0} C`} />
        <MetricCard label="AT 含量" value={r.atContent.toFixed(1)} unit="%" tone="amber" />
        <MetricCard label="解链温度 Tm" value={r.meltingTemp.toFixed(1)} unit="℃" hint="Wallace / GC 经验公式" />
        <MetricCard label="分子量" value={r.molecularWeight.toLocaleString()} unit="Da" />
        <MetricCard label="核酸类型" value={r.isRna ? 'RNA' : 'DNA'} hint={r.isRna ? '含 U 无 T' : '含 T'} tone="emerald" />
      </div>

      {/* GC 条 */}
      <div className="grid gap-4 lg:grid-cols-2 md:gap-6">
        <SectionCard icon={Dna} title="碱基组成" subtitle="四碱基占比">
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
                    paddingAngle={3}
                  >
                    {r.baseCounts.map((b) => (
                      <Cell key={b.base} fill={BASE_COLORS[b.base] ?? '#a3a3a3'} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value, name) => [`${value} 个`, `碱基 ${name}`]}
                    contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="w-full space-y-2">
              {r.baseCounts.map((b) => (
                <div key={b.base} className="flex items-center gap-2.5">
                  <span className="h-3 w-3 shrink-0 rounded-sm" style={{ background: BASE_COLORS[b.base] ?? '#a3a3a3' }} />
                  <span className="w-6 font-mono text-xs font-bold">{b.base}</span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full" style={{ width: `${b.percent}%`, background: BASE_COLORS[b.base] ?? '#a3a3a3' }} />
                  </div>
                  <span className="w-20 text-right text-[11px] tabular-nums text-muted-foreground">
                    {b.count} · {b.percent.toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </SectionCard>

        {/* GC 滑动窗口 */}
        <SectionCard icon={Thermometer} title="GC 滑动窗口" subtitle="窗口 30 nt">
          <div className="h-[260px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={gcData} margin={{ top: 12, right: 24, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" vertical={false} />
                <XAxis dataKey="position" type="number" domain={['dataMin', 'dataMax']} fontSize={11} stroke="#a1a1aa" />
                <YAxis unit="%" domain={[0, 100]} fontSize={11} stroke="#a1a1aa" />
                <Tooltip
                  formatter={(value) => [`${Number(value).toFixed(1)}%`, '窗口 GC']}
                  labelFormatter={(label) => `位置 ${label}`}
                  contentStyle={{ fontSize: 12, borderRadius: 8 }}
                />
                <ReferenceLine y={50} stroke="#f59e0b" strokeDasharray="6 3" label={{ value: '50%', position: 'insideTopRight', fontSize: 10, fill: '#f59e0b' }} />
                <Line type="monotone" dataKey="gcWindow" stroke={CHART_TEAL} strokeWidth={1.5} dot={false} name="GC%" />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            GC 含量显著偏离 50% 的区段可能影响退火温度与二级结构稳定性。
          </p>
        </SectionCard>
      </div>

      {/* ORF 表 */}
      <SectionCard icon={Sparkles} title="开放阅读框 (ORF)" subtitle={`${r.orfs.length} 个 ≥30 nt · 正链 3 框`}>
        {r.orfs.length > 0 ? (
          <div className="max-h-64 overflow-y-auto custom-scrollbar rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="h-8 text-[11px]">阅读框</TableHead>
                  <TableHead className="h-8 text-right text-[11px]">起始 (nt)</TableHead>
                  <TableHead className="h-8 text-right text-[11px]">终止 (nt)</TableHead>
                  <TableHead className="h-8 text-right text-[11px]">长度 (nt)</TableHead>
                  <TableHead className="h-8 text-right text-[11px]">蛋白长度 (aa)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {r.orfs.map((o, i) => (
                  <TableRow key={`${o.start}-${i}`}>
                    <TableCell className="py-1.5 font-mono text-xs">{o.strand}</TableCell>
                    <TableCell className="py-1.5 text-right text-xs tabular-nums">{o.start}</TableCell>
                    <TableCell className="py-1.5 text-right text-xs tabular-nums">{o.end}</TableCell>
                    <TableCell className="py-1.5 text-right text-xs tabular-nums">{o.length}</TableCell>
                    <TableCell className="py-1.5 text-right text-xs font-semibold tabular-nums text-teal-700 dark:text-teal-300">{o.proteinLength}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
            未发现 ≥30 nt 的完整 ORF (含起始密码子与终止密码子)
          </p>
        )}
      </SectionCard>

      <div className="grid gap-4 lg:grid-cols-2 md:gap-6">
        {/* 翻译蛋白序列 */}
        <SectionCard
          icon={ArrowRight}
          title="翻译蛋白序列"
          subtitle={r.proteinTranslation ? `${r.proteinTranslation.length} aa · 最长 ORF` : ''}
        >
          {r.proteinTranslation ? (
            <Collapsible open={translationOpen} onOpenChange={setTranslationOpen}>
              <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 rounded-lg border bg-muted/30 px-3 py-2 text-left text-xs hover:bg-muted/60">
                <span className="truncate font-mono">{r.proteinTranslation.slice(0, 60)}…</span>
                <ChevronDown className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform', translationOpen && 'rotate-180')} />
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="mt-2 max-h-56 overflow-y-auto custom-scrollbar rounded-lg border bg-muted/30 p-3 font-mono text-xs break-all leading-relaxed">
                  {r.proteinTranslation}
                </div>
              </CollapsibleContent>
              <div className="mt-2 flex gap-2">
                <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={copyTranslation}>
                  <Copy className="h-3 w-3" />复制序列
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1.5 text-xs"
                  onClick={() => navigate('alignment', { seq: r.proteinTranslation })}
                >
                  <ArrowRight className="h-3 w-3" />发送到序列比对
                </Button>
              </div>
            </Collapsible>
          ) : (
            <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">无可翻译的 ORF</p>
          )}
        </SectionCard>

        {/* 密码子使用 */}
        <SectionCard icon={Beaker} title="密码子使用偏好" subtitle="翻译区前 12 位">
          {r.codonStats.length > 0 ? (
            <div className="max-h-[280px] space-y-2 overflow-y-auto custom-scrollbar pr-1">
              {r.codonStats.slice(0, 12).map((c) => (
                <div key={c.codon} className="flex items-center gap-2.5">
                  <span className="w-12 font-mono text-xs font-bold text-teal-700 dark:text-teal-300">{c.codon}</span>
                  <span className="w-6 rounded bg-muted px-1 text-center font-mono text-[10px]">{c.aminoAcid}</span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-teal-500" style={{ width: `${(c.count / maxCodon) * 100}%` }} />
                  </div>
                  <span className="w-8 text-right text-[11px] tabular-nums text-muted-foreground">{c.count}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">无密码子统计数据</p>
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

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 p-4 md:space-y-6 md:p-6">
      {/* 页头 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600 text-white shadow-lg shadow-teal-500/20">
          <FlaskConical className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-bold tracking-tight">序列理化分析</h2>
          <p className="text-xs text-muted-foreground">蛋白质 / 核酸序列全方位理化性质计算 · 支持自动类型检测</p>
        </div>
      </div>

      {/* 输入卡片 */}
      <Card className="p-4 md:p-6">
        <Tabs value={source} onValueChange={(v) => setSource(v as 'raw' | 'pdb' | 'uniprot')}>
          <TabsList className="h-auto w-full flex-wrap justify-start gap-1 sm:w-auto">
            <TabsTrigger value="raw" className="gap-1.5 text-xs"><Dna className="h-3.5 w-3.5" />直接输入</TabsTrigger>
            <TabsTrigger value="pdb" className="gap-1.5 text-xs"><Beaker className="h-3.5 w-3.5" />从 PDB</TabsTrigger>
            <TabsTrigger value="uniprot" className="gap-1.5 text-xs"><Activity className="h-3.5 w-3.5" />从 UniProt</TabsTrigger>
          </TabsList>

          <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_200px_140px]">
            <TabsContent value="raw" className="mt-0 space-y-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs text-muted-foreground">序列 (单字母编码, 自动忽略空白)</Label>
                <span className="text-[11px] tabular-nums text-muted-foreground">
                  {sequence.replace(/\s/g, '').length} 字符
                </span>
              </div>
              <Textarea
                value={sequence}
                onChange={(e) => setSequence(e.target.value)}
                placeholder="粘贴氨基酸序列 (如 MKT…) 或核酸序列 (如 ATGGCT…)…"
                className="min-h-[96px] resize-y font-mono text-xs leading-relaxed"
                spellCheck={false}
                aria-label="序列输入"
              />
              <div className="flex flex-wrap gap-2 pt-1">
                <Button
                  variant="outline" size="sm" className="h-7 gap-1.5 text-xs"
                  onClick={() => { setSource('raw'); setSequence(EXAMPLE_PROTEIN); }}
                >
                  <Sparkles className="h-3 w-3 text-teal-600" />示例: 血红蛋白 α ({EXAMPLE_PROTEIN.length} aa)
                </Button>
                <Button
                  variant="outline" size="sm" className="h-7 gap-1.5 text-xs"
                  onClick={() => { setSource('raw'); setSequence(EXAMPLE_NUCLEIC); }}
                >
                  <Sparkles className="h-3 w-3 text-emerald-600" />示例: DNA 片段 ({EXAMPLE_NUCLEIC.length} nt)
                </Button>
              </div>
            </TabsContent>

            <TabsContent value="pdb" className="mt-0 space-y-1.5">
              <Label className="text-xs text-muted-foreground">PDB ID</Label>
              <Input
                value={sourceId}
                onChange={(e) => { setSource('pdb'); setSourceId(e.target.value.toUpperCase()); }}
                placeholder="例如 6M0J"
                className="font-mono"
              />
              <p className="text-[11px] text-muted-foreground">从 RCSB 结构提取首个实体序列</p>
            </TabsContent>

            <TabsContent value="uniprot" className="mt-0 space-y-1.5">
              <Label className="text-xs text-muted-foreground">UniProt Accession</Label>
              <Input
                value={sourceId}
                onChange={(e) => { setSource('uniprot'); setSourceId(e.target.value.toUpperCase()); }}
                placeholder="例如 P69905"
                className="font-mono"
              />
              <p className="text-[11px] text-muted-foreground">从 UniProt 条目获取参考序列</p>
            </TabsContent>

            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">序列类型</Label>
              <Select value={type} onValueChange={setType}>
                <SelectTrigger aria-label="序列类型"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">自动检测</SelectItem>
                  <SelectItem value="protein">蛋白质</SelectItem>
                  <SelectItem value="nucleic">核酸</SelectItem>
                </SelectContent>
              </Select>
              <Button onClick={runAnalysis} disabled={analyzing} className="mt-2 w-full gap-2">
                {analyzing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                {analyzing ? '分析中…' : '开始分析'}
              </Button>
            </div>
          </div>
        </Tabs>

        {prefilled && (
          <p className="mt-3 rounded-lg border border-teal-500/30 bg-teal-500/5 px-3 py-2 text-xs text-teal-700 dark:text-teal-300">
            已从结构详情预填序列, 点击「开始分析」即可计算理化性质。
          </p>
        )}
      </Card>

      {/* 错误 */}
      {error && !analyzing && (
        <Card className="border-rose-500/40 bg-rose-500/5 p-4 text-sm text-rose-600 dark:text-rose-400">{error}</Card>
      )}

      {/* 加载骨架 */}
      {analyzing && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[88px] rounded-xl" />)}
          </div>
          <Skeleton className="h-[300px] w-full rounded-xl" />
        </div>
      )}

      {/* 结果 */}
      {response && !analyzing && (
        <div className="space-y-4 md:space-y-6">
          {/* 来源信息 + 导出 */}
          <Card className="p-4">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge className="gap-1 border-teal-500/40 bg-teal-500/10 text-teal-700 hover:bg-teal-500/10 dark:text-teal-300">
                {response.type === 'protein' ? '蛋白质序列' : '核酸序列'}
              </Badge>
              <span className="text-xs text-muted-foreground">来源: {response.sourceLabel}</span>
              {response.seqName && <span className="truncate text-xs text-muted-foreground">· {response.seqName}</span>}
              <Button variant="outline" size="sm" className="ml-auto h-7 gap-1.5 text-xs" onClick={exportJson}>
                <Download className="h-3 w-3" />导出 JSON
              </Button>
            </div>
          </Card>

          {/* 警告 */}
          {warnings.length > 0 && (
            <div className="flex gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4" role="alert">
              <TriangleAlert className="mt-0.5 h-4.5 w-4.5 shrink-0 text-amber-600 dark:text-amber-400" />
              <div className="space-y-1 text-xs text-amber-800 dark:text-amber-300">
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
        <Card className="flex h-56 flex-col items-center justify-center gap-2 border-dashed p-4 text-sm text-muted-foreground">
          <FlaskConical className="h-9 w-9 opacity-30" />
          输入序列或指定 PDB / UniProt ID 后开始理化分析
          <span className="text-[11px] opacity-70">将计算分子量 · 等电点 · 疏水性 · 二级结构倾向 等指标</span>
        </Card>
      )}
    </div>
  );
}
