'use client';

/**
 * CryoAgent Pro — 知识图谱视图
 * 全局图谱 (ForceGraph + 搜索) / 邻域查询 (深度 1-2) / 路径发现 (结构间关系链)
 */

import { useCallback, useEffect, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { ForceGraph, type GraphEdge, type GraphNode } from '@/components/force-graph';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import {
  BookOpen, Boxes, ChevronRight, GitBranch, Layers, Link2, Loader2, Network,
  Route, Search, TrendingUp, Waypoints,
} from 'lucide-react';

// ============ 类型定义 (API 契约) ============

interface KgStats {
  nodeCount: number;
  structureCount: number;
  literatureCount: number;
  edgeCount: number;
}

interface KgStatsResponse {
  stats: KgStats;
  popularStructures: { id: string; title: string; method: string | null; linkCount: number }[];
}

interface KgGraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: { nodeCount: number; edgeCount: number };
}

interface KgSearchResponse {
  query: string;
  structures: { id: string; label: string; title: string; method: string | null; literatureCount: number }[];
  literature: { id: string; label: string; year: number | null; structureCount: number }[];
}

interface KgPathResponse {
  source: string;
  target: string;
  path: string[] | null;
  connected: boolean;
  pathLength: number | null;
  sequenceSimilarity: number | null;
  titles: Record<string, string>;
}

interface KgNeighborhoodResponse {
  center: string;
  depth: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: { nodeCount: number; edgeCount: number };
}

// ============ 工具 ============

function methodTone(method: string | null): string {
  if (!method) return 'bg-zinc-500/10 text-zinc-600 dark:text-zinc-400';
  if (method.includes('ELECTRON')) return 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300';
  if (method.includes('X-RAY')) return 'bg-teal-500/10 text-teal-700 dark:text-teal-300';
  if (method.includes('NMR')) return 'bg-amber-500/10 text-amber-700 dark:text-amber-300';
  return 'bg-fuchsia-500/10 text-fuchsia-700 dark:text-fuchsia-300';
}

/** 节点点击 → 跳转详情 */
function useGraphNodeNavigation() {
  const navigate = useAppStore((s) => s.navigate);
  return useCallback(
    (node: GraphNode) => {
      if (node.id.startsWith('struct:')) {
        navigate('structure-detail', { id: node.id.slice('struct:'.length) });
      } else if (node.id.startsWith('lit:')) {
        navigate('literature-detail', { id: node.id.slice('lit:'.length) });
      }
    },
    [navigate]
  );
}

// ============ 统计卡片 ============

function StatCard({ icon: Icon, label, value }: { icon: React.ComponentType<{ className?: string }>; label: string; value: number }) {
  return (
    <Card className="p-4 transition-colors hover:border-teal-500/40">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-teal-500/10 text-teal-600 dark:text-teal-400">
          <Icon className="h-4.5 w-4.5" />
        </div>
        <div className="min-w-0">
          <div className="text-xl font-bold tabular-nums">{value.toLocaleString()}</div>
          <div className="text-[11px] text-muted-foreground">{label}</div>
        </div>
      </div>
    </Card>
  );
}

// ============ 主组件 ============

export function KgView() {
  const navigate = useAppStore((s) => s.navigate);
  const handleNodeClick = useGraphNodeNavigation();

  // 全局数据
  const [statsData, setStatsData] = useState<KgStatsResponse | null>(null);
  const [graph, setGraph] = useState<KgGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // 搜索
  const [query, setQuery] = useState('');
  const [searchResults, setSearchResults] = useState<KgSearchResponse | null>(null);
  const [searching, setSearching] = useState(false);

  // 邻域
  const [nbId, setNbId] = useState('6M0J');
  const [nbDepth, setNbDepth] = useState<string>('1');
  const [nbData, setNbData] = useState<KgNeighborhoodResponse | null>(null);
  const [nbLoading, setNbLoading] = useState(false);
  const [nbError, setNbError] = useState('');

  // 路径
  const [pathSource, setPathSource] = useState('6M0J');
  const [pathTarget, setPathTarget] = useState('7A5I');
  const [pathResult, setPathResult] = useState<KgPathResponse | null>(null);
  const [pathLoading, setPathLoading] = useState(false);

  // 初始加载: 统计 + 全局图谱
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [statsR, graphR] = await Promise.all([
          api<KgStatsResponse>('/api/kg?view=stats'),
          api<KgGraphResponse>('/api/kg?view=global'),
        ]);
        if (cancelled) return;
        setStatsData(statsR);
        setGraph(graphR);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : '加载图谱失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // 搜索
  const runSearch = async () => {
    const q = query.trim();
    if (!q) {
      toast.error('请输入搜索关键词');
      return;
    }
    setSearching(true);
    setSearchResults(null);
    try {
      const d = await api<KgSearchResponse>('/api/kg', { method: 'POST', body: JSON.stringify({ query: q }) });
      setSearchResults(d);
      if (d.structures.length === 0 && d.literature.length === 0) {
        toast.info('未找到匹配的结构或文献');
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '搜索失败');
    } finally {
      setSearching(false);
    }
  };

  // 邻域查询
  const runNeighborhood = async () => {
    const id = nbId.trim().toUpperCase();
    if (!id) {
      toast.error('请输入 PDB ID');
      return;
    }
    setNbLoading(true);
    setNbError('');
    setNbData(null);
    try {
      const d = await api<KgNeighborhoodResponse>(`/api/kg/neighborhood/${encodeURIComponent(id)}?depth=${nbDepth}`);
      setNbData(d);
    } catch (err) {
      setNbError(err instanceof Error ? err.message : '邻域查询失败');
    } finally {
      setNbLoading(false);
    }
  };

  // 路径查询
  const runPath = async () => {
    const source = pathSource.trim().toUpperCase();
    const target = pathTarget.trim().toUpperCase();
    if (!source || !target) {
      toast.error('请输入两个 PDB ID');
      return;
    }
    setPathLoading(true);
    setPathResult(null);
    try {
      const d = await api<KgPathResponse>('/api/kg', { method: 'PUT', body: JSON.stringify({ source, target }) });
      setPathResult(d);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '路径查询失败');
    } finally {
      setPathLoading(false);
    }
  };

  const popular = statsData?.popularStructures ?? [];

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 p-4 md:space-y-6 md:p-6">
      {/* 页头 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600 text-white shadow-lg shadow-teal-500/20">
          <Network className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-bold tracking-tight">知识图谱</h2>
          <p className="text-xs text-muted-foreground">结构 — 文献 — 蛋白质关联网络 · 点击节点查看详情</p>
        </div>
      </div>

      {/* 统计卡片 */}
      {loading ? (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[76px] rounded-xl" />)}
        </div>
      ) : error ? (
        <Card className="border-rose-500/40 bg-rose-500/5 p-4 text-sm text-rose-600 dark:text-rose-400">{error}</Card>
      ) : statsData && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard icon={Waypoints} label="节点数" value={statsData.stats.nodeCount} />
          <StatCard icon={Boxes} label="结构节点" value={statsData.stats.structureCount} />
          <StatCard icon={BookOpen} label="文献节点" value={statsData.stats.literatureCount} />
          <StatCard icon={Link2} label="关联边数" value={statsData.stats.edgeCount} />
        </div>
      )}

      <Tabs defaultValue="global" className="space-y-4">
        <TabsList className="h-auto w-full flex-wrap justify-start gap-1 sm:w-auto">
          <TabsTrigger value="global" className="gap-1.5"><Network className="h-3.5 w-3.5" />全局图谱</TabsTrigger>
          <TabsTrigger value="neighborhood" className="gap-1.5"><GitBranch className="h-3.5 w-3.5" />邻域查询</TabsTrigger>
          <TabsTrigger value="path" className="gap-1.5"><Route className="h-3.5 w-3.5" />路径发现</TabsTrigger>
        </TabsList>

        {/* ============ 全局图谱 ============ */}
        <TabsContent value="global" className="space-y-4">
          {/* 搜索栏 */}
          <Card className="p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && runSearch()}
                  placeholder="搜索结构标题 / PDB ID / 文献关键词…"
                  className="pl-9"
                  aria-label="图谱搜索"
                />
              </div>
              <Button onClick={runSearch} disabled={searching} className="gap-2">
                {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                搜索图谱
              </Button>
            </div>
          </Card>

          {/* 搜索结果 */}
          {searchResults && (
            <Card className="border-teal-500/30 p-4">
              <CardHeader className="mb-2 p-0">
                <CardTitle className="flex items-center gap-2 text-sm">
                  <Search className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                  搜索结果 — “{searchResults.query}”
                  <Badge variant="secondary" className="ml-auto font-normal">
                    {searchResults.structures.length + searchResults.literature.length} 条
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 p-0">
                {searchResults.structures.length > 0 && (
                  <div>
                    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">结构</div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {searchResults.structures.map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() => navigate('structure-detail', { id: s.id })}
                          className="group rounded-lg border p-3 text-left transition-all hover:border-teal-500/50 hover:bg-teal-500/5"
                        >
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-bold text-teal-700 dark:text-teal-300">{s.id}</span>
                            {s.method && <span className={cn('rounded px-1.5 py-0.5 text-[10px]', methodTone(s.method))}>{s.method.slice(0, 12)}</span>}
                            <span className="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground">
                              <Layers className="h-3 w-3" />{s.literatureCount} 文献
                            </span>
                          </div>
                          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{s.title}</p>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {searchResults.literature.length > 0 && (
                  <div>
                    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">文献</div>
                    <div className="max-h-64 space-y-1.5 overflow-y-auto custom-scrollbar pr-1">
                      {searchResults.literature.map((l) => (
                        <button
                          key={l.id}
                          type="button"
                          onClick={() => navigate('literature-detail', { id: l.id })}
                          className="flex w-full items-start gap-2 rounded-lg border p-2.5 text-left transition-all hover:border-amber-500/50 hover:bg-amber-500/5"
                        >
                          <BookOpen className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
                          <div className="min-w-0 flex-1">
                            <p className="line-clamp-1 text-xs font-medium">{l.label}</p>
                            <p className="mt-0.5 text-[11px] text-muted-foreground">
                              {l.year ?? '—'} · {l.structureCount} 个关联结构
                            </p>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          <div className="grid gap-4 lg:grid-cols-[1fr_290px]">
            {/* 力导向图 */}
            <Card className="p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="flex items-center gap-2 text-sm">
                  <Waypoints className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                  全局关联网络
                </CardTitle>
                {graph && (
                  <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                    <span>{graph.stats.nodeCount} 节点</span>
                    <span>{graph.stats.edgeCount} 边</span>
                    <span className="hidden sm:inline">拖拽节点 · 滚轮缩放 · 点击跳转</span>
                  </div>
                )}
              </div>
              {loading ? (
                <Skeleton className="h-[420px] w-full rounded-xl" />
              ) : graph && graph.nodes.length > 0 ? (
                <ForceGraph nodes={graph.nodes} edges={graph.edges} height={460} onNodeClick={handleNodeClick} />
              ) : (
                <div className="flex h-[420px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed text-sm text-muted-foreground">
                  <Network className="h-8 w-8 opacity-30" />
                  暂无图谱数据, 请先上传文献并关联结构
                </div>
              )}
            </Card>

            {/* 热门结构 */}
            <Card className="flex flex-col p-4">
              <CardTitle className="flex items-center gap-2 text-sm">
                <TrendingUp className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                热门结构
                <span className="ml-auto text-[11px] font-normal text-muted-foreground">按文献关联数</span>
              </CardTitle>
              <div className="mt-3 max-h-[460px] flex-1 space-y-1.5 overflow-y-auto custom-scrollbar pr-1">
                {loading && Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}
                {popular.map((s, i) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => navigate('structure-detail', { id: s.id })}
                    className="flex w-full items-center gap-2.5 rounded-lg border p-2.5 text-left transition-all hover:border-teal-500/50 hover:bg-teal-500/5"
                  >
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-teal-500/10 text-[11px] font-bold text-teal-700 dark:text-teal-300">
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-xs font-bold">{s.id}</span>
                        <span className="text-[10px] text-muted-foreground">{s.linkCount} 文献</span>
                      </div>
                      <p className="line-clamp-1 text-[11px] text-muted-foreground">{s.title}</p>
                    </div>
                  </button>
                ))}
                {!loading && popular.length === 0 && (
                  <p className="py-8 text-center text-xs text-muted-foreground">暂无数据</p>
                )}
              </div>
            </Card>
          </div>
        </TabsContent>

        {/* ============ 邻域查询 ============ */}
        <TabsContent value="neighborhood" className="space-y-4">
          <Card className="p-4">
            <CardTitle className="mb-3 flex items-center gap-2 text-sm">
              <GitBranch className="h-4 w-4 text-teal-600 dark:text-teal-400" />
              结构邻域查询
            </CardTitle>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1 space-y-1.5">
                <Label htmlFor="nb-id" className="text-xs">PDB ID</Label>
                <Input
                  id="nb-id"
                  value={nbId}
                  onChange={(e) => setNbId(e.target.value.toUpperCase())}
                  onKeyDown={(e) => e.key === 'Enter' && runNeighborhood()}
                  placeholder="例如 6M0J"
                  className="font-mono"
                />
              </div>
              <div className="w-full space-y-1.5 sm:w-32">
                <Label className="text-xs">展开深度</Label>
                <Select value={nbDepth} onValueChange={setNbDepth}>
                  <SelectTrigger aria-label="展开深度">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">1 — 直接关联</SelectItem>
                    <SelectItem value="2">2 — 二级扩展</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button onClick={runNeighborhood} disabled={nbLoading} className="gap-2 sm:mb-0">
                {nbLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitBranch className="h-4 w-4" />}
                查询邻域
              </Button>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              深度 1 显示该结构直接关联的文献与 UniProt; 深度 2 额外展开共享文献的其他结构。
            </p>
          </Card>

          {nbLoading && <Skeleton className="h-[420px] w-full rounded-xl" />}
          {nbError && (
            <Card className="border-rose-500/40 bg-rose-500/5 p-4 text-sm text-rose-600 dark:text-rose-400">{nbError}</Card>
          )}
          {nbData && !nbLoading && (
            <Card className="p-4">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <CardTitle className="font-mono text-sm font-bold">{nbData.center}</CardTitle>
                <Badge variant="secondary">深度 {nbData.depth}</Badge>
                <div className="ml-auto flex items-center gap-3 text-[11px] text-muted-foreground">
                  <span>{nbData.stats.nodeCount} 节点</span>
                  <span>{nbData.stats.edgeCount} 边</span>
                </div>
              </div>
              {nbData.nodes.length > 1 ? (
                <ForceGraph
                  nodes={nbData.nodes}
                  edges={nbData.edges}
                  height={460}
                  centerId={`struct:${nbData.center}`}
                  onNodeClick={handleNodeClick}
                />
              ) : (
                <div className="flex h-40 flex-col items-center justify-center gap-1 rounded-xl border border-dashed text-sm text-muted-foreground">
                  <Boxes className="h-6 w-6 opacity-30" />
                  {nbData.center} 暂无关联文献, 请先在文献中检测该结构
                </div>
              )}
            </Card>
          )}
          {!nbData && !nbLoading && !nbError && (
            <Card className="flex h-48 flex-col items-center justify-center gap-2 border-dashed p-4 text-sm text-muted-foreground">
              <GitBranch className="h-8 w-8 opacity-30" />
              输入 PDB ID 查询其知识图谱邻域
            </Card>
          )}
        </TabsContent>

        {/* ============ 路径发现 ============ */}
        <TabsContent value="path" className="space-y-4">
          <Card className="p-4">
            <CardTitle className="mb-3 flex items-center gap-2 text-sm">
              <Route className="h-4 w-4 text-teal-600 dark:text-teal-400" />
              结构间路径发现
            </CardTitle>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1 space-y-1.5">
                <Label htmlFor="path-src" className="text-xs">起点结构 (PDB)</Label>
                <Input
                  id="path-src"
                  value={pathSource}
                  onChange={(e) => setPathSource(e.target.value.toUpperCase())}
                  placeholder="例如 6M0J"
                  className="font-mono"
                />
              </div>
              <div className="flex-1 space-y-1.5">
                <Label htmlFor="path-dst" className="text-xs">终点结构 (PDB)</Label>
                <Input
                  id="path-dst"
                  value={pathTarget}
                  onChange={(e) => setPathTarget(e.target.value.toUpperCase())}
                  placeholder="例如 7A5I"
                  className="font-mono"
                />
              </div>
              <Button onClick={runPath} disabled={pathLoading} className="gap-2">
                {pathLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Route className="h-4 w-4" />}
                发现路径
              </Button>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              通过 BFS 在 图谱中寻找两个结构间的最短关联链, 并计算首条实体序列的相似度。
            </p>
          </Card>

          {pathLoading && <Skeleton className="h-40 w-full rounded-xl" />}
          {pathResult && !pathLoading && (
            <Card className="p-4 md:p-6">
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-bold">{pathResult.source}</span>
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
                <span className="font-mono text-sm font-bold">{pathResult.target}</span>
                {pathResult.connected ? (
                  <Badge className="gap-1 border-emerald-500/40 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/10 dark:text-emerald-300">
                    <Link2 className="h-3 w-3" />已连接
                  </Badge>
                ) : (
                  <Badge variant="destructive" className="gap-1">
                    <Link2 className="h-3 w-3" />未连通
                  </Badge>
                )}
              </div>

              {/* 路径面包屑 */}
              {pathResult.path ? (
                <div className="mb-4 flex flex-wrap items-center gap-1.5">
                  {pathResult.path.map((nodeId, i) => {
                    const isStruct = !nodeId.startsWith('lit:');
                    const rawId = nodeId.replace(/^(struct:|lit:)/, '');
                    const title = pathResult.titles[rawId];
                    return (
                      <span key={`${nodeId}-${i}`} className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() =>
                            navigate(isStruct ? 'structure-detail' : 'literature-detail', { id: rawId })
                          }
                          className={cn(
                            'max-w-[240px] truncate rounded-full border px-2.5 py-1 text-[11px] transition-colors',
                            isStruct
                              ? 'border-teal-500/40 bg-teal-500/10 font-mono text-teal-700 hover:bg-teal-500/20 dark:text-teal-300'
                              : 'border-amber-500/40 bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 dark:text-amber-300'
                          )}
                          title={title || rawId}
                        >
                          {isStruct ? rawId : `📄 ${title ? title.slice(0, 18) : rawId.slice(0, 8)}`}
                        </button>
                        {i < pathResult.path!.length - 1 && (
                          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        )}
                      </span>
                    );
                  })}
                </div>
              ) : (
                <p className="mb-4 rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
                  两个结构之间不存在 ≤ 2 跳的文献关联路径。
                </p>
              )}

              {/* 指标 */}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                <div className="rounded-lg border bg-muted/40 p-3">
                  <div className="text-[11px] text-muted-foreground">路径长度</div>
                  <div className="mt-1 text-lg font-bold tabular-nums">
                    {pathResult.pathLength != null ? `${pathResult.pathLength} 节点` : '—'}
                  </div>
                </div>
                <div className="rounded-lg border bg-muted/40 p-3">
                  <div className="text-[11px] text-muted-foreground">首实体序列相似度</div>
                  <div className="mt-1 text-lg font-bold tabular-nums">
                    {pathResult.sequenceSimilarity != null ? `${pathResult.sequenceSimilarity}%` : '—'}
                  </div>
                  {pathResult.sequenceSimilarity != null && (
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn(
                          'h-full rounded-full',
                          pathResult.sequenceSimilarity >= 40 ? 'bg-emerald-500' : pathResult.sequenceSimilarity >= 20 ? 'bg-teal-500' : 'bg-amber-500'
                        )}
                        style={{ width: `${Math.min(100, pathResult.sequenceSimilarity)}%` }}
                      />
                    </div>
                  )}
                </div>
                <div className="rounded-lg border bg-muted/40 p-3">
                  <div className="text-[11px] text-muted-foreground">中间文献数</div>
                  <div className="mt-1 text-lg font-bold tabular-nums">
                    {pathResult.path ? pathResult.path.filter((n) => n.startsWith('lit:')).length : '—'}
                  </div>
                </div>
              </div>
            </Card>
          )}
          {!pathResult && !pathLoading && (
            <Card className="flex h-48 flex-col items-center justify-center gap-2 border-dashed p-4 text-sm text-muted-foreground">
              <Route className="h-8 w-8 opacity-30" />
              输入两个 PDB ID, 发现它们之间的关联路径
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
