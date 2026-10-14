'use client';

/**
 * CryoAgent Pro — 评估中心
 * 检索评估 (Precision/Recall/F1/MRR) / Ground Truth 管理 / 监控统计
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '@/lib/store';
import { cn } from '@/lib/utils';
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import {
  Activity, BarChart3, CheckCircle2, ClipboardCheck, Clock, Database, Gauge, ListChecks,
  Loader2, Play, Plus, Search, Trash2, TrendingUp, XCircle,
} from 'lucide-react';

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

function MetricBar({ label, value, color }: { label: string; value: number | null; color: string }) {
  const pct = value != null ? Math.min(100, value) : 0;
  return (
    <Card className="p-3 transition-colors hover:border-teal-500/40 md:p-4">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">{label}</span>
        <span className={cn('text-sm font-bold tabular-nums', value != null ? 'text-foreground' : 'text-muted-foreground/60')}>
          {value != null ? `${value.toFixed(2)}%` : '无 GT'}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: color }} />
      </div>
    </Card>
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
        toast.warning('未找到该查询的 Ground Truth, 指标为空 · 可在 GT 页签添加或开启自动记录');
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

  return (
    <div className="space-y-4">
      {/* 评估表单 */}
      <Card className="p-4 md:p-6">
        <CardHeader className="mb-4 p-0">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Gauge className="h-4 w-4 text-teal-600 dark:text-teal-400" />
            运行检索评估
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 p-0">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="eval-query" className="text-xs text-muted-foreground">评估查询</Label>
              <Input
                id="eval-query"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && runEval()}
                placeholder="例如: spike 蛋白的冷冻电镜结构研究"
              />
            </div>
            <div className="w-full space-y-1.5 lg:w-40">
              <Label className="text-xs text-muted-foreground">检索模式</Label>
              <Select value={mode} onValueChange={setMode}>
                <SelectTrigger aria-label="检索模式"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="hybrid">混合 (RRF)</SelectItem>
                  <SelectItem value="bm25">BM25</SelectItem>
                  <SelectItem value="vector">向量</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2 pb-2">
              <Switch id="auto-gt" checked={autoGt} onCheckedChange={setAutoGt} />
              <Label htmlFor="auto-gt" className="cursor-pointer text-xs text-muted-foreground">
                自动记录 Ground Truth
                <span className="ml-1 text-[10px] opacity-70">(top-5)</span>
              </Label>
            </div>
            <Button onClick={runEval} disabled={running} className="gap-2 lg:mb-0">
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              运行评估
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 最新结果 */}
      {running && <Skeleton className="h-56 w-full rounded-xl" />}
      {effectiveResult && !running && (
        <div className="space-y-4">
          {/* 指标 */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <MetricBar label="Precision" value={effectiveResult.metrics.precision} color="#0d9488" />
            <MetricBar label="Recall" value={effectiveResult.metrics.recall} color="#65a30d" />
            <MetricBar label="F1 分数" value={effectiveResult.metrics.f1} color="#059669" />
            <MetricBar label="MRR" value={effectiveResult.metrics.mrr} color="#d97706" />
            <MetricBar label="命中率" value={effectiveResult.metrics.hitRate} color="#ea580c" />
            <Card className="p-3 md:p-4">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-muted-foreground">检索延迟</span>
                <span className="flex items-center gap-1 text-sm font-bold tabular-nums">
                  <Clock className="h-3.5 w-3.5 text-teal-600 dark:text-teal-400" />
                  {effectiveResult.latencyMs}ms
                </span>
              </div>
              <div className="mt-2 text-[10px] text-muted-foreground/70">
                {MODE_LABELS[effectiveResult.mode] ?? effectiveResult.mode} · {effectiveResult.retrieved.length} 条结果
                {effectiveResult.hasGroundTruth ? '' : ' · 无 GT'}
              </div>
            </Card>
          </div>

          {/* 检索结果列表 */}
          <Card className="p-4 md:p-6">
            <CardHeader className="mb-3 p-0">
              <CardTitle className="flex items-center gap-2 text-sm">
                <ListChecks className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                检索结果 ({effectiveResult.retrieved.length})
                <span className="ml-2 font-normal text-[11px] text-muted-foreground">查询: {effectiveResult.query}</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="max-h-96 space-y-2 overflow-y-auto custom-scrollbar pr-1">
                {effectiveResult.retrieved.map((h) => (
                  <div key={h.id} className={cn('rounded-lg border p-3 transition-colors', h.relevant ? 'border-emerald-500/40 bg-emerald-500/5' : 'hover:border-teal-500/30')}>
                    <div className="flex items-start gap-2.5">
                      <span className={cn(
                        'flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[11px] font-bold',
                        h.rank <= 3 ? 'bg-teal-600 text-white' : 'bg-muted text-muted-foreground'
                      )}>
                        {h.rank}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="truncate text-xs font-medium">{truncate(h.title, 44)}</span>
                          {h.relevant ? (
                            <Badge className="gap-1 border-emerald-500/40 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/10 dark:text-emerald-300">
                              <CheckCircle2 className="h-3 w-3" />相关
                            </Badge>
                          ) : (
                            <Badge variant="secondary" className="gap-1 text-muted-foreground">
                              <XCircle className="h-3 w-3" />无关
                            </Badge>
                          )}
                        </div>
                        {h.section && <p className="mt-0.5 text-[10px] text-muted-foreground">{h.section}</p>}
                        {h.snippet && <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">{h.snippet}</p>}
                        <div className="mt-1.5 flex items-center gap-2">
                          <div className="h-1.5 max-w-[220px] flex-1 overflow-hidden rounded-full bg-muted">
                            <div className="h-full rounded-full bg-teal-500" style={{ width: `${Math.max(3, (h.score / maxScore) * 100)}%` }} />
                          </div>
                          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">{h.score.toFixed(4)}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* F1 对比图 */}
      {f1Data.length > 0 && (
        <Card className="p-4 md:p-6">
          <CardHeader className="mb-3 p-0">
            <CardTitle className="flex items-center gap-2 text-sm">
              <BarChart3 className="h-4 w-4 text-teal-600 dark:text-teal-400" />
              F1 走势对比 (最近 {f1Data.length} 次评估)
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="h-[220px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={f1Data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" vertical={false} />
                  <XAxis dataKey="label" fontSize={10} stroke="#a1a1aa" interval={0} angle={-20} textAnchor="end" height={44} />
                  <YAxis unit="%" domain={[0, 100]} fontSize={11} stroke="#a1a1aa" />
                  <Tooltip formatter={(value) => [`${Number(value).toFixed(2)}%`, 'F1']} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  <ReferenceLine y={0} stroke="#d4d4d8" />
                  <Bar dataKey="f1" radius={[4, 4, 0, 0]}>
                    {f1Data.map((d, i) => (
                      <Cell key={i} fill={d.hasGt ? '#0d9488' : '#d4d4d8'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">灰色柱表示该次运行无 Ground Truth (F1 为空)。</p>
          </CardContent>
        </Card>
      )}

      {/* 历史记录表 */}
      <Card className="p-4 md:p-6">
        <CardHeader className="mb-3 p-0">
          <CardTitle className="flex items-center gap-2 text-sm">
            <ClipboardCheck className="h-4 w-4 text-teal-600 dark:text-teal-400" />
            评估历史 ({runs.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {runs.length === 0 ? (
            <p className="rounded-lg border border-dashed p-6 text-center text-xs text-muted-foreground">
              暂无评估记录, 运行一次检索评估后此处将显示历史
            </p>
          ) : (
            <div className="max-h-96 overflow-y-auto custom-scrollbar rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="h-9 text-[11px]">查询</TableHead>
                    <TableHead className="h-9 text-[11px]">模式</TableHead>
                    <TableHead className="h-9 text-right text-[11px]">Precision</TableHead>
                    <TableHead className="h-9 text-right text-[11px]">Recall</TableHead>
                    <TableHead className="h-9 text-right text-[11px]">F1</TableHead>
                    <TableHead className="h-9 text-right text-[11px]">结果数</TableHead>
                    <TableHead className="h-9 text-[11px]">时间</TableHead>
                    <TableHead className="h-9 w-10" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.map((r) => (
                    <TableRow key={r.id} className="group">
                      <TableCell className="max-w-[240px] truncate py-2 text-xs" title={r.query}>{r.query}</TableCell>
                      <TableCell className="py-2">
                        <Badge variant="secondary" className="text-[10px]">{MODE_LABELS[r.mode] ?? r.mode}</Badge>
                      </TableCell>
                      <TableCell className="py-2 text-right text-xs tabular-nums">
                        <span className={r.precision != null ? 'text-teal-600 dark:text-teal-400' : 'text-muted-foreground/50'}>
                          {r.precision != null ? `${r.precision.toFixed(2)}%` : '—'}
                        </span>
                      </TableCell>
                      <TableCell className="py-2 text-right text-xs tabular-nums">
                        <span className={r.recall != null ? 'text-lime-600 dark:text-lime-400' : 'text-muted-foreground/50'}>
                          {r.recall != null ? `${r.recall.toFixed(2)}%` : '—'}
                        </span>
                      </TableCell>
                      <TableCell className="py-2 text-right text-xs font-semibold tabular-nums">
                        <span className={r.f1 != null ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground/50'}>
                          {r.f1 != null ? `${r.f1.toFixed(2)}%` : '—'}
                        </span>
                      </TableCell>
                      <TableCell className="py-2 text-right text-xs tabular-nums text-muted-foreground">{r.resultCount}</TableCell>
                      <TableCell className="py-2 whitespace-nowrap text-[11px] text-muted-foreground">{formatTime(r.createdAt)}</TableCell>
                      <TableCell className="py-2">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground opacity-0 transition-opacity hover:text-rose-600 group-hover:opacity-100"
                          onClick={() => deleteRun(r.id)}
                          disabled={deleting === r.id}
                          aria-label="删除评估记录"
                        >
                          {deleting === r.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
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
      {/* 添加表单 */}
      <Card className="p-4 md:p-6">
        <CardHeader className="mb-4 p-0">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Plus className="h-4 w-4 text-teal-600 dark:text-teal-400" />
            添加 Ground Truth
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 p-0">
          <div className="space-y-1.5">
            <Label htmlFor="gt-query" className="text-xs text-muted-foreground">查询语句</Label>
            <Input id="gt-query" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="例如: 冷冻电镜分辨率极限" />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="gt-ids" className="text-xs text-muted-foreground">相关 Chunk IDs (逗号分隔)</Label>
              <Input
                id="gt-ids"
                value={chunkIds}
                onChange={(e) => setChunkIds(e.target.value)}
                placeholder="例如: chunk-abc123, chunk-def456"
                className="font-mono text-xs"
              />
              <p className="text-[10px] text-muted-foreground">可在文献详情的分块列表中获取 chunk ID</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="gt-notes" className="text-xs text-muted-foreground">备注 (可选)</Label>
              <Input id="gt-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="例如: 人工标注 top-3" />
            </div>
          </div>
          <Button onClick={saveGt} disabled={saving} className="gap-2">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            保存 Ground Truth
          </Button>
        </CardContent>
      </Card>

      {/* GT 列表 */}
      <Card className="p-4 md:p-6">
        <CardHeader className="mb-3 p-0">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Database className="h-4 w-4 text-teal-600 dark:text-teal-400" />
            Ground Truth 列表 ({groundTruths.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {groundTruths.length === 0 ? (
            <p className="rounded-lg border border-dashed p-6 text-center text-xs text-muted-foreground">
              暂无 Ground Truth, 添加后即可计算 Precision / Recall / F1
            </p>
          ) : (
            <div className="max-h-[480px] space-y-2 overflow-y-auto custom-scrollbar pr-1">
              {groundTruths.map((g) => (
                <div key={g.id} className="group rounded-lg border p-3 transition-colors hover:border-teal-500/40">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium">{g.query}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <Badge variant="secondary" className="gap-1 text-[10px] tabular-nums">
                          <ListChecks className="h-3 w-3" />{g.relevantChunkIds.length} 个相关分块
                        </Badge>
                        {g.notes && <span className="text-[10px] text-muted-foreground">{g.notes}</span>}
                      </div>
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {g.relevantChunkIds.slice(0, 6).map((id) => (
                          <span key={id} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{id}</span>
                        ))}
                        {g.relevantChunkIds.length > 6 && (
                          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">+{g.relevantChunkIds.length - 6}</span>
                        )}
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 shrink-0 text-muted-foreground opacity-0 transition-opacity hover:text-rose-600 group-hover:opacity-100"
                      onClick={() => deleteGt(g.id)}
                      disabled={deleting === g.id}
                      aria-label="删除 Ground Truth"
                    >
                      {deleting === g.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
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
    return <Skeleton className="h-64 w-full rounded-xl" />;
  }

  return (
    <div className="space-y-4">
      {/* 指标卡 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card className="p-4 transition-colors hover:border-teal-500/40">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-teal-500/10 text-teal-600 dark:text-teal-400">
              <Search className="h-4.5 w-4.5" />
            </div>
            <div>
              <div className="text-xl font-bold tabular-nums">{monitor.totalSearches}</div>
              <div className="text-[11px] text-muted-foreground">总搜索次数</div>
            </div>
          </div>
        </Card>
        <Card className="p-4 transition-colors hover:border-teal-500/40">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
              <Clock className="h-4.5 w-4.5" />
            </div>
            <div>
              <div className="text-xl font-bold tabular-nums">
                {monitor.avgLatency != null ? `${monitor.avgLatency}ms` : '—'}
              </div>
              <div className="text-[11px] text-muted-foreground">平均检索延迟</div>
            </div>
          </div>
        </Card>
        <Card className="p-4 transition-colors hover:border-teal-500/40">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400">
              <TrendingUp className="h-4.5 w-4.5" />
            </div>
            <div>
              <div className={cn('text-xl font-bold tabular-nums', monitor.zeroResultRate > 20 ? 'text-amber-600 dark:text-amber-400' : '')}>
                {monitor.zeroResultRate}%
              </div>
              <div className="text-[11px] text-muted-foreground">零结果率</div>
            </div>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 热门查询 */}
        <Card className="p-4 md:p-6">
          <CardHeader className="mb-3 p-0">
            <CardTitle className="flex items-center gap-2 text-sm">
              <TrendingUp className="h-4 w-4 text-teal-600 dark:text-teal-400" />
              热门查询 Top 10
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {popularData.length > 0 ? (
              <div className="h-[280px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={popularData} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" horizontal={false} />
                    <XAxis type="number" allowDecimals={false} fontSize={11} stroke="#a1a1aa" />
                    <YAxis type="category" dataKey="query" width={130} fontSize={11} stroke="#a1a1aa" />
                    <Tooltip formatter={(value) => [`${value} 次`, '搜索次数']} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                    <Bar dataKey="count" radius={[0, 4, 4, 0]} fill="#0d9488" barSize={14} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <p className="rounded-lg border border-dashed p-6 text-center text-xs text-muted-foreground">
                暂无搜索日志, 使用智能问答或检索后将在此统计
              </p>
            )}
          </CardContent>
        </Card>

        {/* 延迟走势 */}
        <Card className="p-4 md:p-6">
          <CardHeader className="mb-3 p-0">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Activity className="h-4 w-4 text-teal-600 dark:text-teal-400" />
              评估检索延迟走势
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {latencyData.length > 0 ? (
              <div className="h-[280px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={latencyData} margin={{ top: 8, right: 24, bottom: 4, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" vertical={false} />
                    <XAxis dataKey="idx" fontSize={11} stroke="#a1a1aa" />
                    <YAxis unit="ms" fontSize={11} stroke="#a1a1aa" />
                    <Tooltip
                      formatter={(value) => [`${value} ms`, '延迟']}
                      labelFormatter={(label) => `第 ${label} 次评估`}
                      contentStyle={{ fontSize: 12, borderRadius: 8 }}
                    />
                    <Line type="monotone" dataKey="latency" stroke="#0d9488" strokeWidth={2} dot={{ r: 2.5, fill: '#0d9488' }} name="延迟" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <p className="rounded-lg border border-dashed p-6 text-center text-xs text-muted-foreground">
                暂无评估记录, 运行检索评估后将显示延迟走势
              </p>
            )}
          </CardContent>
        </Card>
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

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 p-4 md:space-y-6 md:p-6">
      {/* 页头 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600 text-white shadow-lg shadow-teal-500/20">
          <ClipboardCheck className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-bold tracking-tight">评估中心</h2>
          <p className="text-xs text-muted-foreground">RAG 检索质量评估 · Ground Truth 标注 · 搜索监控统计</p>
        </div>
        {data && (
          <div className="ml-auto hidden gap-3 text-[11px] text-muted-foreground sm:flex">
            <span>{data.runs.length} 次评估</span>
            <span>{data.groundTruths.length} 条 GT</span>
            <span>{data.monitor.totalSearches} 次搜索</span>
          </div>
        )}
      </div>

      {error && <Card className="border-rose-500/40 bg-rose-500/5 p-4 text-sm text-rose-600 dark:text-rose-400">{error}</Card>}

      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-28 w-full rounded-xl" />
          <Skeleton className="h-56 w-full rounded-xl" />
        </div>
      ) : (
        <Tabs defaultValue="retrieval" className="space-y-4">
          <TabsList className="h-auto w-full flex-wrap justify-start gap-1 sm:w-auto">
            <TabsTrigger value="retrieval" className="gap-1.5"><Gauge className="h-3.5 w-3.5" />检索评估</TabsTrigger>
            <TabsTrigger value="gt" className="gap-1.5"><Database className="h-3.5 w-3.5" />Ground Truth</TabsTrigger>
            <TabsTrigger value="monitor" className="gap-1.5"><Activity className="h-3.5 w-3.5" />监控统计</TabsTrigger>
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
  );
}
