'use client';

/**
 * CryoAgent Pro — 评估中心 (BENCH 设计系统)
 * 检索质量基准 (Precision / Recall / F1 / MRR / HitRate) · Ground Truth 标注 · 搜索监控
 * 结构: grid-bg masthead + mono 页签 + KPI hairline 分隔条 + 密集数据行 + table.bench
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '@/lib/store';
import { cn } from '@/lib/utils';
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import { Activity, Database, Gauge, Loader2, Play, Plus, Trash2 } from 'lucide-react';

// ============ 类型定义 (API 契约) ============

interface RetrievedItem {
  rank: number;
  id: string;
  title: string;
  section?: string;
  score: number;
  snippet?: string;
  relevant: boolean;
}

interface RunDetails {
  retrieved?: RetrievedItem[];
  relevantIds?: string[];
  hasGroundTruth?: boolean;
}

interface EvalRun {
  id: string;
  query: string;
  mode: string;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  mrr: number | null;
  hitRate: number | null;
  latencyMs: number;
  resultCount: number;
  createdAt: string;
  details: RunDetails | null;
}

interface GroundTruth {
  id: string;
  query: string;
  relevantChunkIds: string[];
  notes: string | null;
}

interface Monitor {
  totalSearches: number;
  avgLatency: number | null;
  zeroResultRate: number;
  popularQueries: { query: string; count: number }[];
}

interface AllResponse {
  runs: EvalRun[];
  groundTruths: GroundTruth[];
  monitor: Monitor;
}

interface EvalPostResponse {
  runId: string;
  query: string;
  mode: string;
  latencyMs: number;
  hasGroundTruth: boolean;
  metrics: { precision: number | null; recall: number | null; f1: number | null; mrr: number | null; hitRate: number | null };
  retrieved: RetrievedItem[];
}

// ============ 工具 ============

const MODE_LABELS: Record<string, string> = { bm25: 'BM25', vector: '向量', hybrid: '混合' };
const MODE_TAGS: Record<string, string> = { bm25: 'BM25', vector: 'VEC', hybrid: 'HYB' };

const AXIS = {
  fontSize: 9,
  fontFamily: 'var(--font-plex-mono), monospace',
  fill: 'currentColor',
  opacity: 0.55,
};
const TOOLTIP_STYLE = {
  fontSize: 11,
  fontFamily: 'var(--font-plex-mono), monospace',
  borderRadius: 4,
  border: '1px solid var(--border)',
  background: 'var(--popover)',
  color: 'var(--popover-foreground)',
  padding: '4px 8px',
};

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

// ============ BENCH 基础组件 ============

/** 面板骨架 — 统一 hairline 分区容器 */
function Panel({ children, className }: { children: React.ReactNode; className?: string }) {
  return <section className={cn('rounded-lg border bg-card', className)}>{children}</section>;
}

function PanelHead({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 border-b px-4 py-2.5">
      <span className="label-tech !text-[10px] text-foreground/75">{title}</span>
      {hint && <span className="label-tech ml-auto !text-[9px]">{hint}</span>}
      {action}
    </div>
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

/** mono 短码 tag — outline 语义色 */
function MiniTag({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex shrink-0 items-center rounded-[3px] border px-1.5 py-px font-mono text-[9px] font-medium tracking-wide', className)}>
      {children}
    </span>
  );
}

// ============ 检索评估 Tab ============

function RetrievalEvalTab({
  runs, onDeleted, onRunCompleted,
}: {
  runs: EvalRun[];
  onDeleted: (id: string) => void;
  onRunCompleted: () => void;
}) {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('hybrid');
  const [autoGt, setAutoGt] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<EvalPostResponse | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const effectiveResult = result;

  const runEval = async () => {
    const q = query.trim();
    if (!q) { toast.error('请输入评估查询语句'); return; }
    setRunning(true);
    try {
      const d = await api<EvalPostResponse>('/api/evaluation', {
        method: 'POST',
        body: JSON.stringify({ query: q, mode, autoGroundTruth: autoGt }),
      });
      setResult(d);
      onRunCompleted();
      if (!d.hasGroundTruth) {
        toast.warning('未找到该查询的 Ground Truth, 指标为空 · 可在标注页签添加或开启自动记录');
      } else {
        toast.success(`评估完成 · F1 ${d.metrics.f1?.toFixed(2) ?? '—'}% · ${d.latencyMs}ms`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '评估失败');
    } finally {
      setRunning(false);
    }
  };

  const deleteRun = async (id: string) => {
    setDeleting(id);
    try {
      await api<{ success: boolean }>(`/api/evaluation?runId=${encodeURIComponent(id)}`, { method: 'DELETE' });
      onDeleted(id);
      toast.success('已删除评估记录');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeleting(null);
    }
  };

  // F1 对比图数据 (时间正序)
  const f1Data = useMemo(
    () => [...runs].slice(0, 15).reverse().map((r, i) => ({ label: `${i + 1} ${truncate(r.query, 8)}`, f1: r.f1 ?? 0, hasGt: r.f1 != null })),
    [runs]
  );
  const maxScore = Math.max(...(effectiveResult?.retrieved ?? []).map((h) => h.score), 0.0001);

  const metrics = effectiveResult
    ? [
        { label: 'Precision · 查准率', sub: '检索命中中的相关占比', value: effectiveResult.metrics.precision },
        { label: 'Recall · 查全率', sub: '相关内容被召回的占比', value: effectiveResult.metrics.recall },
        { label: 'F1 · 调和均值', sub: 'P 与 R 的调和平均', value: effectiveResult.metrics.f1 },
        { label: 'MRR · 倒数排名', sub: '首个相关结果的排名倒数', value: effectiveResult.metrics.mrr },
        { label: 'HitRate · 命中率', sub: '至少命中一个相关结果', value: effectiveResult.metrics.hitRate },
      ]
    : [];

  return (
    <div className="space-y-4">
      {/* ===== 运行控制台 ===== */}
      <Panel>
        <PanelHead title="运行控制台 · EVAL RUN" hint={runs.length ? `${runs.length} 条历史` : 'POST /api/evaluation'} />
        <div className="p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
            <div className="min-w-0 flex-1 space-y-1.5">
              <Label htmlFor="eval-query" className="label-tech">评估查询 · QUERY</Label>
              <Input
                id="eval-query"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && runEval()}
                placeholder="例如: spike 蛋白的冷冻电镜结构研究"
                className="h-9"
              />
            </div>
            <div className="w-full space-y-1.5 lg:w-44">
              <Label className="label-tech" htmlFor="eval-mode">检索模式 · MODE</Label>
              <Select value={mode} onValueChange={setMode}>
                <SelectTrigger id="eval-mode" aria-label="检索模式" className="h-9 w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="hybrid">混合 (RRF)</SelectItem>
                  <SelectItem value="bm25">BM25</SelectItem>
                  <SelectItem value="vector">向量</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2.5 pb-1.5">
              <Switch id="auto-gt" checked={autoGt} onCheckedChange={setAutoGt} />
              <Label htmlFor="auto-gt" className="label-tech cursor-pointer normal-case !tracking-normal">
                自动记录 GT (TOP-5)
              </Label>
            </div>
            <Button onClick={runEval} disabled={running} className="h-9 shrink-0">
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" strokeWidth={1.75} />}
              运行评估
            </Button>
          </div>
        </div>
      </Panel>

      {/* ===== 最新结果 ===== */}
      {running && <Skeleton className="h-56 w-full rounded-lg" />}
      {effectiveResult && !running && (
        <div className="space-y-4">
          {/* KPI 条 — hairline 分隔, mono 大数字 */}
          <div className="grid grid-cols-2 divide-x divide-border rounded-lg border bg-card md:grid-cols-3 lg:grid-cols-6 [&>*:nth-child(2)]:border-l-0 md:[&>*]:border-l md:[&>*:first-child]:border-l-0 lg:[&>*:nth-child(2)]:border-l">
            {metrics.map((m) => (
              <div key={m.label} className="min-w-0 px-4 py-3">
                <div className="label-tech !text-[9px]">{m.label}</div>
                <div className={cn('num mt-1 text-[22px] font-medium leading-none tracking-tight', m.value == null && 'text-muted-foreground/50')}>
                  {m.value != null ? m.value.toFixed(2) : '—'}
                  {m.value != null && <span className="ml-0.5 text-[11px] font-normal text-muted-foreground">%</span>}
                </div>
                <div className="mt-2 h-[3px] w-full overflow-hidden rounded-full bg-muted" aria-hidden>
                  <div
                    className="h-full rounded-full bg-primary transition-all duration-500"
                    style={{ width: `${m.value != null ? Math.min(100, m.value) : 0}%` }}
                  />
                </div>
                <div className="label-tech mt-1.5 !text-[9px] normal-case !tracking-normal text-muted-foreground/70">
                  {m.value != null ? m.sub : 'NO GROUND TRUTH'}
                </div>
              </div>
            ))}
            <div className="min-w-0 px-4 py-3">
              <div className="label-tech !text-[9px]">Latency · 延迟</div>
              <div className="num mt-1 text-[22px] font-medium leading-none tracking-tight">
                {effectiveResult.latencyMs}
                <span className="ml-0.5 text-[11px] font-normal text-muted-foreground">ms</span>
              </div>
              <div className="label-tech mt-2 !text-[9px] normal-case !tracking-normal text-muted-foreground/70">
                {MODE_LABELS[effectiveResult.mode] ?? effectiveResult.mode} 检索 · {effectiveResult.retrieved.length} 条结果
              </div>
              <div className="label-tech mt-1.5 !text-[9px] normal-case !tracking-normal text-muted-foreground/70">
                {effectiveResult.hasGroundTruth ? 'GT MATCHED' : '无 GT 标注'}
              </div>
            </div>
          </div>

          {/* ===== 检索结果 — 密集列表行 ===== */}
          <Panel>
            <PanelHead
              title={`检索结果 · ${effectiveResult.retrieved.length} 条`}
              hint={`Q: ${truncate(effectiveResult.query, 20)}`}
            />
            <div className="max-h-96 overflow-y-auto custom-scrollbar">
              {effectiveResult.retrieved.length > 0 ? (
                <div className="divide-y">
                  {effectiveResult.retrieved.map((h) => (
                    <div key={h.id} className="flex items-start gap-3 px-4 py-2.5 transition-colors hover:bg-accent/50">
                      <span
                        className={cn(
                          'num w-6 shrink-0 pt-px text-[12px] font-semibold',
                          h.rank <= 3 ? 'text-primary' : 'text-muted-foreground/60'
                        )}
                      >
                        {String(h.rank).padStart(2, '0')}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <span className="min-w-0 truncate text-xs font-medium">{truncate(h.title, 44)}</span>
                          {h.relevant ? (
                            <MiniTag className="border-primary/50 text-primary">相关</MiniTag>
                          ) : (
                            <MiniTag className="border-border text-muted-foreground/70">无关</MiniTag>
                          )}
                        </div>
                        {h.section && <p className="label-tech mt-0.5 !text-[9px] normal-case !tracking-normal">{h.section}</p>}
                        {h.snippet && <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">{h.snippet}</p>}
                        <div className="mt-1.5 flex items-center gap-2">
                          <div className="h-[3px] max-w-[220px] flex-1 overflow-hidden rounded-full bg-muted" aria-hidden>
                            <div
                              className="h-full rounded-full bg-primary"
                              style={{ width: `${Math.max(3, (h.score / maxScore) * 100)}%` }}
                            />
                          </div>
                          <span className="num shrink-0 text-[10px] text-muted-foreground/70">{h.score.toFixed(4)}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty text="NO HITS — 该查询未召回任何分块" />
              )}
            </div>
          </Panel>
        </div>
      )}

      {/* ===== F1 走势 ===== */}
      {f1Data.length > 0 && (
        <Panel>
          <PanelHead title="F1 走势" hint={`最近 ${f1Data.length} 次运行`} />
          <div className="p-3">
            <ResponsiveContainer width="100%" height={210}>
              <BarChart data={f1Data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid strokeDasharray="2 5" stroke="currentColor" vertical={false} opacity={0.08} />
                <XAxis dataKey="label" tick={AXIS} angle={-20} textAnchor="end" height={44} interval={0} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={{ opacity: 0.2 }} />
                <YAxis unit="%" domain={[0, 100]} tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={false} width={34} />
                <Tooltip formatter={(value) => [`${Number(value).toFixed(2)}%`, 'F1']} contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--accent)', opacity: 0.5 }} />
                <ReferenceLine y={0} stroke="currentColor" opacity={0.2} />
                <Bar dataKey="f1" barSize={14}>
                  {f1Data.map((d, i) => (
                    <Cell key={i} fill={d.hasGt ? 'var(--chart-1)' : 'var(--chart-5)'} fillOpacity={d.hasGt ? 1 : 0.45} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <p className="label-tech mt-1 !text-[9px] normal-case !tracking-normal">灰柱 = 该次运行无 Ground Truth (F1 为空)</p>
          </div>
        </Panel>
      )}

      {/* ===== 评估历史 ===== */}
      <Panel>
        <PanelHead title="评估历史" hint={`${runs.length} 条记录`} />
        {runs.length === 0 ? (
          <Empty text="NO RUNS — 运行一次检索评估后此处显示历史" />
        ) : (
          <div className="max-h-96 overflow-auto custom-scrollbar">
            <table className="bench">
              <thead>
                <tr>
                  <th>查询</th>
                  <th>模式</th>
                  <th className="text-right">Precision</th>
                  <th className="text-right">Recall</th>
                  <th className="text-right">F1</th>
                  <th className="text-right">结果数</th>
                  <th>时间</th>
                  <th className="w-10" aria-label="操作" />
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className="group">
                    <td className="max-w-[240px] truncate" title={r.query}>{r.query}</td>
                    <td>
                      <MiniTag className="border-border text-muted-foreground">{MODE_TAGS[r.mode] ?? r.mode}</MiniTag>
                    </td>
                    <td className="num text-right">{r.precision != null ? `${r.precision.toFixed(2)}%` : '—'}</td>
                    <td className="num text-right">{r.recall != null ? `${r.recall.toFixed(2)}%` : '—'}</td>
                    <td className="num text-right font-semibold">{r.f1 != null ? `${r.f1.toFixed(2)}%` : '—'}</td>
                    <td className="num text-right text-muted-foreground">{r.resultCount}</td>
                    <td className="num whitespace-nowrap text-muted-foreground">{formatTime(r.createdAt)}</td>
                    <td>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="relative h-8 w-8 text-muted-foreground transition-colors hover:text-destructive after:absolute after:-inset-2 md:opacity-0 md:group-hover:opacity-100"
                        onClick={() => deleteRun(r.id)}
                        disabled={deleting === r.id}
                        aria-label="删除评估记录"
                      >
                        {deleting === r.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

// ============ Ground Truth Tab ============

function GroundTruthTab({
  groundTruths, onChanged,
}: {
  groundTruths: GroundTruth[];
  onChanged: () => void;
}) {
  const [query, setQuery] = useState('');
  const [chunkIds, setChunkIds] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const saveGt = async () => {
    const q = query.trim();
    if (!q) { toast.error('请输入查询语句'); return; }
    const ids = chunkIds.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
    if (ids.length === 0) { toast.error('请输入至少一个相关 chunk ID (逗号分隔)'); return; }
    setSaving(true);
    try {
      await api<{ success: boolean }>('/api/evaluation', {
        method: 'PUT',
        body: JSON.stringify({ query: q, relevantChunkIds: ids, notes: notes.trim() || undefined }),
      });
      toast.success('Ground Truth 已保存');
      setQuery(''); setChunkIds(''); setNotes('');
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const deleteGt = async (id: string) => {
    setDeleting(id);
    try {
      await api<{ success: boolean }>(`/api/evaluation?groundTruthId=${encodeURIComponent(id)}`, { method: 'DELETE' });
      toast.success('已删除 Ground Truth');
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="space-y-4">
      {/* ===== 标注录入 ===== */}
      <Panel>
        <PanelHead title="标注录入 · GROUND TRUTH" hint="PUT /api/evaluation" />
        <div className="space-y-4 p-4">
          <div className="space-y-1.5">
            <Label htmlFor="gt-query" className="label-tech">查询语句 · QUERY</Label>
            <Input id="gt-query" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="例如: 冷冻电镜分辨率极限" className="h-9" />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="gt-ids" className="label-tech">相关 Chunk IDs · 逗号分隔</Label>
              <Input
                id="gt-ids"
                value={chunkIds}
                onChange={(e) => setChunkIds(e.target.value)}
                placeholder="例如: chunk-abc123, chunk-def456"
                className="h-9 font-mono text-xs"
              />
              <p className="label-tech !text-[9px] normal-case !tracking-normal">可在文献详情的分块列表中获取 chunk ID</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="gt-notes" className="label-tech">备注 · NOTES (可选)</Label>
              <Input id="gt-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="例如: 人工标注 top-3" className="h-9" />
            </div>
          </div>
          <Button onClick={saveGt} disabled={saving} className="h-9">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" strokeWidth={1.75} />}
            保存 Ground Truth
          </Button>
        </div>
      </Panel>

      {/* ===== 标注集 — 密集列表 ===== */}
      <Panel>
        <PanelHead title="标注集" hint={`${groundTruths.length} 条 GT`} />
        {groundTruths.length === 0 ? (
          <Empty text="NO GROUND TRUTH — 添加标注后即可计算 Precision / Recall / F1" />
        ) : (
          <div className="max-h-[480px] overflow-y-auto custom-scrollbar">
            <div className="divide-y">
              {groundTruths.map((g) => (
                <div key={g.id} className="group flex items-start gap-3 px-4 py-2.5 transition-colors hover:bg-accent/50">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium">{g.query}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <MiniTag className="border-primary/50 text-primary">
                        <span className="num">{g.relevantChunkIds.length}</span> 相关分块
                      </MiniTag>
                      {g.notes && <span className="text-[10px] text-muted-foreground">{g.notes}</span>}
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {g.relevantChunkIds.slice(0, 6).map((id) => (
                        <span key={id} className="rounded-[3px] border bg-muted/50 px-1.5 py-px font-mono text-[9px] text-muted-foreground">{id}</span>
                      ))}
                      {g.relevantChunkIds.length > 6 && (
                        <span className="num rounded-[3px] border px-1.5 py-px text-[9px] text-muted-foreground/70">+{g.relevantChunkIds.length - 6}</span>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="relative h-8 w-8 shrink-0 text-muted-foreground transition-colors hover:text-destructive after:absolute after:-inset-2 md:opacity-0 md:group-hover:opacity-100"
                    onClick={() => deleteGt(g.id)}
                    disabled={deleting === g.id}
                    aria-label="删除 Ground Truth"
                  >
                    {deleting === g.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />}
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}

// ============ 监控统计 Tab ============

function MonitorTab({ monitor, runs }: { monitor: Monitor | null; runs: EvalRun[] }) {
  const popularData = useMemo(
    () => (monitor?.popularQueries ?? []).map((q) => ({ query: truncate(q.query, 14), count: q.count })),
    [monitor]
  );
  const latencyData = useMemo(
    () => [...runs].slice(0, 20).reverse().map((r, i) => ({ idx: i + 1, latency: r.latencyMs, query: truncate(r.query, 16) })),
    [runs]
  );

  if (!monitor) {
    return <Skeleton className="h-64 w-full rounded-lg" />;
  }

  return (
    <div className="space-y-4">
      {/* KPI 条 — hairline 分隔 */}
      <div className="grid grid-cols-1 divide-y divide-border rounded-lg border bg-card sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <div className="min-w-0 px-4 py-3">
          <div className="label-tech !text-[9px]">累计搜索</div>
          <div className="num mt-1 text-[22px] font-medium leading-none tracking-tight">{monitor.totalSearches}</div>
          <div className="label-tech mt-1.5 !text-[9px] normal-case !tracking-normal text-muted-foreground/70">SEARCH LOG TOTAL</div>
        </div>
        <div className="min-w-0 px-4 py-3">
          <div className="label-tech !text-[9px]">平均检索延迟</div>
          <div className="num mt-1 text-[22px] font-medium leading-none tracking-tight">
            {monitor.avgLatency != null ? monitor.avgLatency : '—'}
            {monitor.avgLatency != null && <span className="ml-0.5 text-[11px] font-normal text-muted-foreground">ms</span>}
          </div>
          <div className="label-tech mt-1.5 !text-[9px] normal-case !tracking-normal text-muted-foreground/70">全量搜索日志均值</div>
        </div>
        <div className="min-w-0 px-4 py-3">
          <div className="label-tech flex items-center gap-1.5 !text-[9px]">
            零结果率
            {monitor.zeroResultRate > 20 && <span className="status-dot" data-tone="amber" aria-hidden />}
          </div>
          <div className={cn('num mt-1 text-[22px] font-medium leading-none tracking-tight', monitor.zeroResultRate > 20 && 'text-chart-2')}>
            {monitor.zeroResultRate}
            <span className="ml-0.5 text-[11px] font-normal text-muted-foreground">%</span>
          </div>
          <div className="label-tech mt-1.5 !text-[9px] normal-case !tracking-normal text-muted-foreground/70">
            {monitor.zeroResultRate > 20 ? '偏高 — 建议扩充语料或调整分块' : '空召回占比正常'}
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 热门查询 */}
        <Panel>
          <PanelHead title="热门查询 · Top 10" hint="BY 搜索日志" />
          <div className="p-3">
            {popularData.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={popularData} layout="vertical" margin={{ top: 4, right: 12, left: 8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="2 5" stroke="currentColor" horizontal={false} opacity={0.08} />
                  <XAxis type="number" allowDecimals={false} tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={{ opacity: 0.2 }} />
                  <YAxis type="category" dataKey="query" width={110} tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={false} />
                  <Tooltip formatter={(value) => [`${value} 次`, '搜索次数']} contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--accent)', opacity: 0.5 }} />
                  <Bar dataKey="count" fill="var(--chart-1)" barSize={10} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <Empty text="NO LOGS — 使用智能问答或检索后将在此统计" />
            )}
          </div>
        </Panel>

        {/* 延迟走势 */}
        <Panel>
          <PanelHead title="评估延迟走势" hint={`${latencyData.length} 次运行`} />
          <div className="p-3">
            {latencyData.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={latencyData} margin={{ top: 6, right: 8, left: -14, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="2 5" stroke="currentColor" vertical={false} opacity={0.08} />
                  <XAxis dataKey="idx" tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={{ opacity: 0.2 }} />
                  <YAxis unit="ms" tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={false} width={44} />
                  <Tooltip
                    formatter={(value) => [`${value} ms`, '延迟']}
                    labelFormatter={(label) => `第 ${label} 次评估`}
                    contentStyle={TOOLTIP_STYLE}
                  />
                  <Line type="monotone" dataKey="latency" name="延迟" stroke="var(--chart-1)" strokeWidth={1.75} dot={{ r: 2.5, fill: 'var(--chart-1)', strokeWidth: 0 }} activeDot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <Empty text="NO RUNS — 运行检索评估后将显示延迟走势" />
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}

// ============ 主组件 ============

export function EvaluationView() {
  const [data, setData] = useState<AllResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadAll = useCallback(async () => {
    try {
      const d = await api<AllResponse>('/api/evaluation?view=all');
      setData(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载评估数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api<AllResponse>('/api/evaluation?view=all');
        if (cancelled) return;
        setData(d);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : '加载评估数据失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleRunDeleted = (id: string) => {
    setData((prev) => (prev ? { ...prev, runs: prev.runs.filter((r) => r.id !== id) } : prev));
  };

  const handleGtChanged = () => { void loadAll(); };

  /* ===== Masthead — 坐标纸 + 编辑性标题 ===== */
  const masthead = (
    <div className="grid-bg border-b">
      <div className="flex flex-wrap items-end justify-between gap-4 px-4 py-6 md:px-6">
        <div>
          <div className="label-tech !text-[10px]">Benchmark · 评估中心</div>
          <h1 className="mt-1.5 text-[26px] font-semibold leading-none tracking-tight md:text-[30px]">
            评估中心
            <span className="font-display ml-2.5 align-middle text-[20px] font-normal italic tracking-normal text-muted-foreground/60 md:text-[24px]">
              Benchmark
            </span>
          </h1>
          <p className="mt-2.5 max-w-lg text-xs leading-relaxed text-muted-foreground">
            RAG 检索质量基准 — Precision / Recall / F1 / MRR 测量 · Ground Truth 标注 · 检索服务监控
          </p>
        </div>
        <div className="label-tech space-y-1.5 text-right !text-[10px]">
          <div className="flex items-center justify-end gap-2">
            <span className="status-dot" data-tone={data ? (data.groundTruths.length > 0 ? undefined : 'amber') : 'muted'} aria-hidden />
            {data ? (data.groundTruths.length > 0 ? 'GT SET READY' : 'NO GROUND TRUTH') : 'LOADING'}
          </div>
          <div className="text-muted-foreground/60">
            {data ? `${data.runs.length} RUNS · ${data.groundTruths.length} GT · ${data.monitor.totalSearches} SEARCHES` : 'BM25 + VEC · RRF FUSION'}
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="animate-fade-in-up">
      {masthead}

      <div className="space-y-4 p-4 md:p-6">
        {error && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
            <div className="label-tech !text-destructive">EVAL DATA LOAD FAILED</div>
            <p className="mt-1 text-sm text-destructive">{error}</p>
          </div>
        )}

        {loading ? (
          <div className="space-y-4">
            <Skeleton className="h-10 w-full max-w-md rounded-lg" />
            <Skeleton className="h-36 w-full rounded-lg" />
            <Skeleton className="h-56 w-full rounded-lg" />
          </div>
        ) : (
          <Tabs defaultValue="retrieval" className="space-y-4">
            <TabsList className="h-auto w-full flex-wrap justify-start gap-1 rounded-lg border bg-card p-1 sm:w-auto">
              <TabsTrigger value="retrieval" className="h-7 gap-1.5 px-3 text-xs data-[state=active]:!bg-accent data-[state=active]:!shadow-none dark:data-[state=active]:!bg-accent dark:data-[state=active]:!border-transparent">
                <Gauge className="h-3.5 w-3.5" strokeWidth={1.75} />检索评估
              </TabsTrigger>
              <TabsTrigger value="gt" className="h-7 gap-1.5 px-3 text-xs data-[state=active]:!bg-accent data-[state=active]:!shadow-none dark:data-[state=active]:!bg-accent dark:data-[state=active]:!border-transparent">
                <Database className="h-3.5 w-3.5" strokeWidth={1.75} />Ground Truth
              </TabsTrigger>
              <TabsTrigger value="monitor" className="h-7 gap-1.5 px-3 text-xs data-[state=active]:!bg-accent data-[state=active]:!shadow-none dark:data-[state=active]:!bg-accent dark:data-[state=active]:!border-transparent">
                <Activity className="h-3.5 w-3.5" strokeWidth={1.75} />监控统计
              </TabsTrigger>
            </TabsList>

            <TabsContent value="retrieval">
              <RetrievalEvalTab runs={data?.runs ?? []} onDeleted={handleRunDeleted} onRunCompleted={handleGtChanged} />
            </TabsContent>

            <TabsContent value="gt">
              <GroundTruthTab groundTruths={data?.groundTruths ?? []} onChanged={handleGtChanged} />
            </TabsContent>

            <TabsContent value="monitor">
              <MonitorTab monitor={data?.monitor ?? null} runs={data?.runs ?? []} />
            </TabsContent>
          </Tabs>
        )}
      </div>
    </div>
  );
}
