'use client';

/**
 * CryoAgent Pro — 仪表盘 (新增功能)
 * 平台统计总览 + 活跃趋势 + 快速入口
 */

import { useEffect, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  BookOpen, Boxes, MessageSquare, Sparkles, GitCompareArrows, Network, Search,
  ArrowRight, TrendingUp, Database, Cpu, Zap, FileText, ChevronRight, Activity,
} from 'lucide-react';

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

const METHOD_COLORS = ['#0d9488', '#f59e0b', '#8b5cf6', '#10b981', '#ef4444', '#64748b'];

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

  const quickActions = [
    { label: '智能问答', desc: 'RAG + Agent 双模式', icon: MessageSquare, view: 'qa' as const, accent: 'from-teal-500 to-emerald-500' },
    { label: '文献管理', desc: '上传 PDF 建立知识库', icon: BookOpen, view: 'literature' as const, accent: 'from-amber-500 to-orange-500' },
    { label: '结构浏览器', desc: 'RCSB 3D 结构查看', icon: Boxes, view: 'structures' as const, accent: 'from-violet-500 to-purple-500' },
    { label: '序列比对', desc: 'NW/SW + BLOSUM', icon: GitCompareArrows, view: 'alignment' as const, accent: 'from-rose-500 to-pink-500' },
  ];

  if (error) {
    return (
      <div className="p-6 text-sm text-red-600">统计加载失败: {error}</div>
    );
  }

  return (
    <div className="space-y-6 p-4 md:p-6">
      {/* 头部横幅 */}
      <div className="relative overflow-hidden rounded-2xl border bg-gradient-to-br from-teal-500/10 via-emerald-500/5 to-transparent p-6 md:p-8">
        <div className="absolute -right-16 -top-16 h-64 w-64 rounded-full bg-teal-500/10 blur-3xl" />
        <div className="relative">
          <div className="flex items-center gap-2 text-xs font-medium text-teal-700 dark:text-teal-400">
            <Zap className="h-3.5 w-3.5" />
            Cryo-EM · 蛋白质结构智能分析平台
          </div>
          <h1 className="mt-2 text-2xl font-bold tracking-tight md:text-3xl">
            CryoAgent <span className="text-teal-600 dark:text-teal-400">Pro</span>
          </h1>
          <p className="mt-1.5 max-w-xl text-sm text-muted-foreground">
            基于 AI 的冷冻电镜文献与蛋白质结构分析系统 — 混合检索 · Agent 工具调用 · 3D 结构可视化 · 序列深度分析
          </p>
          <div className="mt-4 flex flex-wrap gap-2 text-[11px]">
            <Badge variant="secondary" className="gap-1"><Database className="h-3 w-3" />BM25 + 向量混合检索</Badge>
            <Badge variant="secondary" className="gap-1"><Cpu className="h-3 w-3" />11 Agent 工具</Badge>
            <Badge variant="secondary" className="gap-1"><Sparkles className="h-3 w-3" />14 专家技能</Badge>
            <Badge variant="secondary" className="gap-1"><Activity className="h-3 w-3" />SSE 流式输出</Badge>
          </div>
        </div>
      </div>

      {/* 统计卡 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {[
          { label: '文献', value: data?.totals.literature, icon: BookOpen, color: 'text-amber-600' },
          { label: '检索分块', value: data?.totals.chunks, icon: FileText, color: 'text-teal-600' },
          { label: '蛋白结构', value: data?.totals.structures, icon: Boxes, color: 'text-violet-600' },
          { label: '问答总数', value: data?.totals.qa, icon: MessageSquare, color: 'text-emerald-600' },
          { label: '技能', value: data?.totals.skills, icon: Sparkles, color: 'text-rose-600' },
          { label: '比对任务', value: data?.totals.alignments, icon: GitCompareArrows, color: 'text-cyan-600' },
        ].map((stat) => (
          <Card key={stat.label} className="border-border/60 transition-all hover:border-teal-500/40 hover:shadow-md">
            <CardContent className="flex items-center gap-3 p-4">
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted ${stat.color}`}>
                <stat.icon className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                {stat.value === undefined ? (
                  <Skeleton className="h-7 w-12" />
                ) : (
                  <div className="text-xl font-bold tabular-nums">{stat.value.toLocaleString()}</div>
                )}
                <div className="text-[11px] text-muted-foreground">{stat.label}</div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* QA 活跃趋势 */}
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <TrendingUp className="h-4 w-4 text-teal-600" />
              问答活跃趋势 (14 天)
            </CardTitle>
            <Badge variant="outline" className="text-[10px]">
              Agent {data?.totals.agentQa ?? 0} / RAG {data ? data.totals.qa - data.totals.agentQa : 0}
            </Badge>
          </CardHeader>
          <CardContent className="pl-2">
            {data ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={data.qaActivity}>
                  <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="currentColor" opacity={0.5} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10 }} stroke="currentColor" opacity={0.5} width={28} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  <Bar dataKey="rag" name="RAG 问答" stackId="a" fill="#0d9488" radius={[0, 0, 0, 0]} />
                  <Bar dataKey="agent" name="Agent 问答" stackId="a" fill="#f59e0b" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <Skeleton className="h-[220px] w-full" />
            )}
          </CardContent>
        </Card>

        {/* 快速入口 */}
        <div className="grid grid-cols-2 gap-3">
          {quickActions.map((action) => (
            <button
              key={action.label}
              onClick={() => navigate(action.view)}
              className="group relative overflow-hidden rounded-xl border bg-card p-4 text-left transition-all hover:-translate-y-0.5 hover:shadow-lg"
              type="button"
            >
              <div className={`absolute -right-8 -top-8 h-20 w-20 rounded-full bg-gradient-to-br ${action.accent} opacity-10 transition-transform group-hover:scale-150`} />
              <action.icon className={`h-6 w-6 bg-gradient-to-br ${action.accent} bg-clip-text text-transparent`} style={{ stroke: 'url(#grad)' }} />
              <div className="mt-2 text-sm font-semibold">{action.label}</div>
              <div className="text-[11px] text-muted-foreground">{action.desc}</div>
              <ArrowRight className="mt-2 h-3.5 w-3.5 text-muted-foreground transition-transform group-hover:translate-x-1" />
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* 实验方法分布 */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <Boxes className="h-4 w-4 text-violet-600" />
              实验方法分布
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data && data.methodStats.length > 0 ? (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={data.methodStats} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
                  <XAxis type="number" tick={{ fontSize: 10 }} stroke="currentColor" opacity={0.5} />
                  <YAxis type="category" dataKey="method" tick={{ fontSize: 9 }} width={110} stroke="currentColor" opacity={0.5} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  <Bar dataKey="count" radius={[0, 3, 3, 0]}>
                    {data.methodStats.map((_, i) => (
                      <Cell key={i} fill={METHOD_COLORS[i % METHOD_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-[180px] items-center justify-center text-xs text-muted-foreground">
                暂无结构方法数据 — 去结构浏览器搜索缓存结构
              </div>
            )}
          </CardContent>
        </Card>

        {/* 热门结构 */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <Network className="h-4 w-4 text-teal-600" />
              知识图谱热门结构
            </CardTitle>
            <Button variant="ghost" size="sm" className="h-6 text-[11px]" onClick={() => navigate('kg')}>
              查看图谱 <ChevronRight className="ml-0.5 h-3 w-3" />
            </Button>
          </CardHeader>
          <CardContent className="space-y-1.5">
            {data && data.popularStructures.length > 0 ? (
              data.popularStructures.slice(0, 6).map((s, i) => (
                <button
                  key={s.id}
                  onClick={() => navigate('structure-detail', { id: s.id })}
                  className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-accent"
                  type="button"
                >
                  <span className={`w-5 text-center text-xs font-bold ${i < 3 ? 'text-teal-600 dark:text-teal-400' : 'text-muted-foreground'}`}>
                    {i + 1}
                  </span>
                  <span className="font-mono text-sm font-semibold">{s.id}</span>
                  <span className="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground">
                    <BookOpen className="h-3 w-3" />
                    {s.links} 篇文献
                  </span>
                </button>
              ))
            ) : (
              <div className="flex h-[180px] items-center justify-center text-xs text-muted-foreground">
                上传文献后将自动建立关联
              </div>
            )}
          </CardContent>
        </Card>

        {/* 系统健康 */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <Search className="h-4 w-4 text-emerald-600" />
              检索服务
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2.5">
              <span className="text-xs text-muted-foreground">索引分块数</span>
              <span className="font-mono text-sm font-semibold">{data?.ragIndex.chunkCount ?? '—'}</span>
            </div>
            <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2.5">
              <span className="text-xs text-muted-foreground">平均检索延迟</span>
              <span className="font-mono text-sm font-semibold">
                {data?.searchAvgLatency != null ? `${data.searchAvgLatency}ms` : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2.5">
              <span className="text-xs text-muted-foreground">总搜索次数</span>
              <span className="font-mono text-sm font-semibold">{data?.totals.searches ?? '—'}</span>
            </div>
            <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2.5">
              <span className="text-xs text-muted-foreground">知识关联边</span>
              <span className="font-mono text-sm font-semibold">{data?.totals.links ?? '—'}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 最近活动 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <MessageSquare className="h-4 w-4 text-teal-600" />
              最近问答
            </CardTitle>
            <Button variant="ghost" size="sm" className="h-6 text-[11px]" onClick={() => navigate('qa')}>
              继续对话 <ChevronRight className="ml-0.5 h-3 w-3" />
            </Button>
          </CardHeader>
          <CardContent className="max-h-64 space-y-1.5 overflow-y-auto custom-scrollbar">
            {data && data.recentQa.length > 0 ? (
              data.recentQa.map((qa) => (
                <div key={qa.id} className="flex items-center gap-2 rounded-lg px-2 py-2 transition-colors hover:bg-accent">
                  <Badge variant={qa.mode === 'agent' ? 'default' : 'secondary'} className="shrink-0 text-[9px]">
                    {qa.mode === 'agent' ? 'AGENT' : 'RAG'}
                  </Badge>
                  <span className="min-w-0 flex-1 truncate text-xs">{qa.question}</span>
                  <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                    {qa.latencyMs ? `${(qa.latencyMs / 1000).toFixed(1)}s` : ''}
                  </span>
                </div>
              ))
            ) : (
              <div className="flex h-24 items-center justify-center text-xs text-muted-foreground">
                还没有问答记录 — 去「智能问答」试试吧
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <FileText className="h-4 w-4 text-amber-600" />
              文献年份分布
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data && data.yearStats.length > 0 ? (
              <ResponsiveContainer width="100%" height={160}>
                <LineChart data={data.yearStats}>
                  <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
                  <XAxis dataKey="year" tick={{ fontSize: 10 }} stroke="currentColor" opacity={0.5} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10 }} stroke="currentColor" opacity={0.5} width={24} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  <Line type="monotone" dataKey="count" stroke="#0d9488" strokeWidth={2} dot={{ r: 3, fill: '#0d9488' }} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-[160px] items-center justify-center text-xs text-muted-foreground">
                暂无文献数据 — 上传第一篇 PDF
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
