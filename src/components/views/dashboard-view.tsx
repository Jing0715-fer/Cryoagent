'use client';

/**
 * CryoAgent Pro — 平台总览 (BENCH 设计系统标杆视图)
 * masthead(坐标纸) + KPI 条(hairline 分隔) + 不对称工作区 + 密集数据行
 */

import { useEffect, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { Skeleton } from '@/components/ui/skeleton';
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ArrowRight, ArrowUpRight } from 'lucide-react';
import { cn } from '@/lib/utils';

interface StatsData {
  totals: {
    literature: number;
    chunks: number;
    structures: number;
    qa: number;
    agentQa: number;
    skills: number;
    alignments: number;
    links: number;
    notes: number;
    users: number;
    searches: number;
  };
  qaActivity: { date: string; rag: number; agent: number }[];
  methodStats: { method: string; count: number }[];
  popularStructures: { id: string; links: number }[];
  yearStats: { year: number; count: number }[];
  recentSearches: { query: string; mode: string; latencyMs: number; createdAt: string }[];
  recentQa: { id: string; question: string; mode: string; createdAt: string; latencyMs: number | null }[];
  searchAvgLatency: number | null;
  ragIndex: { chunkCount: number; literatureCount: number; indexAge: number };
}

const AXIS = { fontSize: 9, fontFamily: 'var(--font-plex-mono), monospace', fill: 'currentColor', opacity: 0.55 };
const TOOLTIP_STYLE = {
  fontSize: 11,
  fontFamily: 'var(--font-plex-mono), monospace',
  borderRadius: 4,
  border: '1px solid var(--border)',
  background: 'var(--popover)',
  color: 'var(--popover-foreground)',
  padding: '4px 8px',
};

/** 面板骨架 — 统一 hairline 分区容器 */
function Panel({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <section className={cn('rounded-lg border bg-card', className)}>{children}</section>
  );
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

export function DashboardView() {
  const navigate = useAppStore((s) => s.navigate);
  const [data, setData] = useState<StatsData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    api<StatsData>('/api/stats')
      .then((d) => mounted && setData(d))
      .catch((e) => mounted && setError(e.message));
    return () => {
      mounted = false;
    };
  }, []);

  const t = data?.totals;
  const ragQa = t ? t.qa - t.agentQa : 0;

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
          <div className="label-tech !text-destructive">STATS LOAD FAILED</div>
          <p className="mt-1 text-sm text-destructive">{error}</p>
        </div>
      </div>
    );
  }

  const kpis = [
    { label: '文献', sub: `${t?.notes ?? 0} 条笔记`, value: t?.literature },
    { label: '检索分块', sub: `${data?.ragIndex.indexAge ?? 0} 分钟前建索引`, value: t?.chunks },
    { label: '蛋白结构', sub: 'RCSB 缓存', value: t?.structures },
    { label: '问答', sub: `RAG ${ragQa} · AGENT ${t?.agentQa ?? 0}`, value: t?.qa },
    { label: '比对任务', sub: 'NW / SW', value: t?.alignments },
    { label: '图谱关联', sub: `${t?.users ?? 0} 位用户`, value: t?.links },
  ];

  const entries = [
    { label: '智能问答', desc: 'RAG + AGENT 双模式', view: 'qa' as const, bar: 'bg-chart-1' },
    { label: '文献管理', desc: 'PDF 解析 · 知识入库', view: 'literature' as const, bar: 'bg-chart-2' },
    { label: '结构浏览器', desc: 'RCSB PDB 3D 查看', view: 'structures' as const, bar: 'bg-chart-3' },
    { label: '序列比对', desc: 'NW / SW · BLOSUM', view: 'alignment' as const, bar: 'bg-chart-4' },
  ];

  return (
    <div className="animate-fade-in-up">
      {/* ===== Masthead — 坐标纸 + 编辑性标题 ===== */}
      <div className="grid-bg relative border-b">
        <div className="flex flex-wrap items-end justify-between gap-4 px-4 py-6 md:px-6 md:py-7">
          <div>
            <div className="label-tech !text-[10px]">Workbench · 平台总览</div>
            <h1 className="font-display mt-1.5 text-[28px] leading-none tracking-tight md:text-[34px]">
              CryoAgent <span className="italic text-primary">Pro</span>
            </h1>
            <p className="mt-2.5 max-w-lg text-xs leading-relaxed text-muted-foreground">
              冷冻电镜文献与蛋白质结构智能分析系统 — 混合检索 · Agent 工具调用 · 3D 可视化 · 序列深度分析
            </p>
          </div>
          <div className="label-tech space-y-1.5 text-right !text-[10px]">
            <div className="flex items-center justify-end gap-2">
              <span className="status-dot" aria-hidden /> ALL SYSTEMS NOMINAL
            </div>
            <div className="text-muted-foreground/60">
              HYBRID BM25+VEC · SSE STREAMING
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-4 md:p-6">
        {/* ===== KPI 条 — hairline 分隔, 无卡片 ===== */}
        <div className="grid grid-cols-2 divide-x divide-border rounded-lg border bg-card md:grid-cols-3 lg:grid-cols-6 [&>*:nth-child(2)]:border-l-0 md:[&>*]:border-l md:[&>*:first-child]:border-l-0 lg:[&>*:nth-child(2)]:border-l">
          {kpis.map((k) => (
            <div key={k.label} className="min-w-0 px-4 py-3">
              <div className="label-tech !text-[9px]">{k.label}</div>
              {k.value === undefined ? (
                <Skeleton className="mt-1.5 h-6 w-14" />
              ) : (
                <div className="num mt-1 text-[22px] font-medium leading-none tracking-tight">{k.value.toLocaleString()}</div>
              )}
              <div className="label-tech mt-1.5 !text-[9px] normal-case !tracking-normal text-muted-foreground/70">{k.sub}</div>
            </div>
          ))}
        </div>

        {/* ===== 主工作区: 检索活动 (2/3) + 快速入口/服务状态 (1/3) ===== */}
        <div className="grid gap-4 lg:grid-cols-3">
          <Panel className="lg:col-span-2">
            <PanelHead
              title="问答活动 · 14 天"
              hint={t ? `AGENT ${t.agentQa} / RAG ${ragQa}` : undefined}
            />
            <div className="p-3">
              {data && data.qaActivity.length > 0 ? (
                <ResponsiveContainer width="100%" height={168}>
                  <BarChart data={data.qaActivity} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="2 5" stroke="currentColor" vertical={false} opacity={0.08} />
                    <XAxis dataKey="date" tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={{ opacity: 0.2 }} />
                    <YAxis allowDecimals={false} tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={false} width={30} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--accent)', opacity: 0.5 }} />
                    <Bar dataKey="rag" name="RAG" stackId="a" fill="var(--chart-1)" />
                    <Bar dataKey="agent" name="AGENT" stackId="a" fill="var(--chart-2)" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <Empty text="NO DATA — 在「智能问答」发起第一次提问后显示活动趋势" />
              )}
            </div>
          </Panel>

          <div className="grid gap-4">
            {/* 快速入口 — 左色条语义编码 */}
            <Panel>
              <PanelHead title="快速入口" />
              <div className="divide-y">
                {entries.map((e) => (
                  <button
                    key={e.label}
                    onClick={() => navigate(e.view)}
                    className="group relative flex w-full items-center gap-3 py-2.5 pl-4 pr-3 text-left transition-colors hover:bg-accent/50"
                    type="button"
                  >
                    <span className={cn('absolute inset-y-[9px] left-0 w-[2px]', e.bar)} aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] font-medium leading-tight">{e.label}</span>
                      <span className="label-tech mt-0.5 block !text-[9px] normal-case !tracking-normal">{e.desc}</span>
                    </span>
                    <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40 transition-all group-hover:translate-x-0.5 group-hover:text-foreground" />
                  </button>
                ))}
              </div>
            </Panel>

            {/* 服务状态 — mono 键值行 */}
            <Panel className="hidden lg:block">
              <PanelHead title="检索服务" hint="RUNTIME" />
              <div className="divide-y text-muted-foreground/40 [&>*]:divide-x-0">
                {[
                  ['索引分块', data ? String(data.ragIndex.chunkCount) : '—'],
                  ['平均检索延迟', data?.searchAvgLatency != null ? `${data.searchAvgLatency}ms` : '—'],
                  ['累计搜索', t ? String(t.searches) : '—'],
                  ['知识关联边', t ? String(t.links) : '—'],
                ].map(([k, v]) => (
                  <div key={k} className="flex items-baseline justify-between px-4 py-[7px]">
                    <span className="text-[11px] text-muted-foreground">{k}</span>
                    <span className="num text-[12px] font-medium">{v}</span>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </div>

        {/* ===== 最近问答 (2/3) + 热门结构 (1/3) ===== */}
        <div className="grid gap-4 lg:grid-cols-3">
          <Panel className="lg:col-span-2">
            <PanelHead
              title="最近问答"
              hint={data?.recentQa.length ? `${data.recentQa.length} 条` : undefined}
              action={
                <button
                  onClick={() => navigate('qa')}
                  className="label-tech flex items-center gap-1 !text-[9px] text-primary transition-opacity hover:opacity-70"
                  type="button"
                >
                  继续对话 <ArrowUpRight className="h-3 w-3" />
                </button>
              }
            />
            <div className="max-h-[224px] overflow-y-auto custom-scrollbar">
              {data && data.recentQa.length > 0 ? (
                <div className="divide-y">
                  {data.recentQa.map((qa) => (
                    <button
                      key={qa.id}
                      onClick={() => navigate('qa')}
                      className="flex w-full items-center gap-3 px-4 py-2 text-left transition-colors hover:bg-accent/50"
                      type="button"
                    >
                      <span
                        className={cn(
                          'shrink-0 rounded-[3px] border px-1.5 py-px font-mono text-[9px] font-medium tracking-wide',
                          qa.mode === 'agent' ? 'border-chart-2/50 text-chart-2' : 'border-border text-muted-foreground'
                        )}
                      >
                        {qa.mode === 'agent' ? 'AGENT' : 'RAG'}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-xs">{qa.question}</span>
                      {qa.latencyMs != null && (
                        <span className="num shrink-0 text-[10px] text-muted-foreground/70">{(qa.latencyMs / 1000).toFixed(1)}s</span>
                      )}
                    </button>
                  ))}
                </div>
              ) : (
                <Empty text="NO HISTORY — 去「智能问答」向知识库提问" />
              )}
            </div>
          </Panel>

          <Panel>
            <PanelHead
              title="图谱热门结构"
              hint="BY 文献关联"
              action={
                <button
                  onClick={() => navigate('kg')}
                  className="label-tech flex items-center gap-1 !text-[9px] text-primary transition-opacity hover:opacity-70"
                  type="button"
                >
                  查看图谱 <ArrowUpRight className="h-3 w-3" />
                </button>
              }
            />
            <div className="max-h-[224px] overflow-y-auto custom-scrollbar">
              {data && data.popularStructures.length > 0 ? (
                <div className="divide-y">
                  {data.popularStructures.slice(0, 7).map((s, i) => (
                    <button
                      key={s.id}
                      onClick={() => navigate('structure-detail', { id: s.id })}
                      className="flex w-full items-baseline gap-3 px-4 py-2 text-left transition-colors hover:bg-accent/50"
                      type="button"
                    >
                      <span className="num w-4 shrink-0 text-[10px] text-muted-foreground/60">{String(i + 1).padStart(2, '0')}</span>
                      <span className="num text-[13px] font-semibold tracking-tight">{s.id}</span>
                      <span className="num ml-auto text-[10px] text-muted-foreground">{s.links} 篇</span>
                    </button>
                  ))}
                </div>
              ) : (
                <Empty text="NO LINKS — 上传文献后自动建立结构关联" />
              )}
            </div>
          </Panel>
        </div>

        {/* ===== 数据分布: 实验方法 + 年份 ===== */}
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel>
            <PanelHead title="实验方法分布" hint="RCSB CACHED" />
            <div className="p-3">
              {data && data.methodStats.length > 0 ? (
                <ResponsiveContainer width="100%" height={140}>
                  <BarChart data={data.methodStats} layout="vertical" margin={{ top: 0, right: 12, left: 8, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="2 5" stroke="currentColor" horizontal={false} opacity={0.08} />
                    <XAxis type="number" tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={{ opacity: 0.2 }} />
                    <YAxis type="category" dataKey="method" tick={AXIS} width={92} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--accent)', opacity: 0.5 }} />
                    <Bar dataKey="count" name="结构数" fill="var(--chart-1)" barSize={10}>
                      {data.methodStats.map((_, i) => (
                        <Cell key={i} fill={`var(--chart-${(i % 5) + 1})`} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <Empty text="NO DATA — 去结构浏览器缓存 RCSB 结构后显示方法分布" />
              )}
            </div>
          </Panel>

          <Panel>
            <PanelHead title="文献年份分布" hint={t ? `${t.literature} 篇入库` : undefined} />
            <div className="p-3">
              {data && data.yearStats.length > 0 ? (
                <ResponsiveContainer width="100%" height={140}>
                  <LineChart data={data.yearStats} margin={{ top: 6, right: 8, left: -22, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="2 5" stroke="currentColor" vertical={false} opacity={0.08} />
                    <XAxis dataKey="year" tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={{ opacity: 0.2 }} />
                    <YAxis allowDecimals={false} tick={AXIS} stroke="currentColor" opacity={0.3} tickLine={false} axisLine={false} width={30} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                    <Line type="monotone" dataKey="count" name="文献" stroke="var(--chart-1)" strokeWidth={1.75} dot={{ r: 2.5, fill: 'var(--chart-1)', strokeWidth: 0 }} activeDot={{ r: 4 }} />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <Empty text="NO DATA — 上传第一篇 PDF 后显示年份分布" />
              )}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
