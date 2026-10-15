'use client';

/**
 * CryoAgent Pro — 知识图谱视图 (BENCH 设计系统)
 * masthead + KPI 条 + 图谱画布面板 + 侧栏密集列表 + 邻域/路径查询仪器面板
 * 功能不变: 全局图谱 (ForceGraph + 搜索) / 邻域查询 (深度 1-2) / 路径发现 (结构间关系链)
 */

import { useCallback, useEffect, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { ForceGraph, type GraphEdge, type GraphNode } from '@/components/force-graph';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent } from '@/components/ui/tabs';
import { MethodBadge, MiniRing, SegmentedTabs, StatCard } from '@/components/ui/bench-widgets';
import { toast } from 'sonner';
import {
  BookOpen, Boxes, ChevronRight, GitBranch, Loader2, Network, Route, Search, Share2,
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

// ============ BENCH 基础组件 ============

function Panel({ children, className }: { children: React.ReactNode; className?: string }) {
  return <section className={cn('rounded-lg border bg-card', className)}>{children}</section>;
}

function PanelHead({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
      <span className="label-tech !text-[10px] text-foreground/75">{title}</span>
      {hint && <span className="label-tech ml-auto !text-[9px]">{hint}</span>}
      {action && <div className={cn('flex items-center gap-1.5', !hint && 'ml-auto')}>{action}</div>}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="label-tech flex h-full min-h-[120px] items-center justify-center px-4 py-12 text-center !text-[10px] normal-case !tracking-[0.06em]">
      {text}
    </div>
  );
}

// ============ 工具 ============

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

  // Tab 视图切换 (受控 — 供 SegmentedTabs 滑动药丸)
  const [tab, setTab] = useState('global');

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
  const stats = statsData?.stats;

  return (
    <div className="animate-fade-in-up">
      {/* ===== Masthead — 坐标纸 + 编辑性标题 ===== */}
      <div className="grid-bg border-b">
        <div className="flex flex-wrap items-end justify-between gap-4 px-4 py-6 md:px-6">
          <div>
            <div className="label-tech !text-[10px]">Knowledge Graph · 知识图谱</div>
            <h1 className="mt-1.5 text-[26px] font-semibold leading-none tracking-tight md:text-[30px]">
              知识图谱
              <span className="font-display ml-2.5 font-normal italic title-gradient">Knowledge Graph</span>
            </h1>
            <p className="mt-2.5 max-w-lg text-xs leading-relaxed text-muted-foreground">
              结构 — 文献 — 蛋白质三元关联网络 · 力导向可视化 · 邻域展开 · 最短路径发现与序列相似度参考
            </p>
          </div>
          <div className="label-tech space-y-1.5 text-right !text-[10px]">
            <div className="flex items-center justify-end gap-2">
              <span className="status-dot" aria-hidden />
              {stats ? `NODES ${stats.nodeCount} · EDGES ${stats.edgeCount}` : 'SYNCING…'}
            </div>
            <div className="text-muted-foreground/60">FORCE-DIRECTED · SVG CANVAS</div>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-4 md:p-6">
        {/* ===== KPI — StatCard 网格: 领域色渐变图标 + 计数动画 + 迷你可视化 ===== */}
        {error ? (
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
            <div className="label-tech !text-[10px] !text-destructive">GRAPH LOAD FAILED</div>
            <p className="mt-1 text-xs text-destructive/90">{error}</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4 [grid-auto-rows:1fr]">
            <StatCard
              title="节点总数"
              value={stats?.nodeCount ?? 0}
              subtitle={stats ? '结构 · 文献 · 蛋白实体' : undefined}
              icon={<Network className="h-3.5 w-3.5" />}
              gradient="from-[#6b7280] to-[#4b5563]"
              accent="#6b7280"
              loading={!stats}
              delay={0}
              tooltip={stats ? `知识图谱节点 ${stats.nodeCount} 个` : undefined}
            />
            <StatCard
              title="结构节点"
              value={stats?.structureCount ?? 0}
              subtitle={
                stats
                  ? `占节点 ${Math.round((stats.structureCount / Math.max(stats.nodeCount, 1)) * 100)}%`
                  : undefined
              }
              icon={<Boxes className="h-3.5 w-3.5" />}
              gradient="from-[#2d8f8f] to-[#1a6b6b]"
              accent="#2d8f8f"
              loading={!stats}
              delay={45}
              tooltip={stats ? `结构节点 ${stats.structureCount} / 总节点 ${stats.nodeCount}` : undefined}
              indicator={
                stats ? <MiniRing value={stats.structureCount} max={stats.nodeCount} color="#2d8f8f" /> : undefined
              }
            />
            <StatCard
              title="文献节点"
              value={stats?.literatureCount ?? 0}
              subtitle={stats ? '上传文献实体' : undefined}
              icon={<BookOpen className="h-3.5 w-3.5" />}
              gradient="from-[#c96442] to-[#a04e32]"
              accent="#c96442"
              loading={!stats}
              delay={90}
              tooltip={stats ? `文献节点 ${stats.literatureCount} 篇` : undefined}
            />
            <StatCard
              title="关联边"
              value={stats?.edgeCount ?? 0}
              subtitle={stats ? '结构 ↔ 文献关联' : undefined}
              icon={<Share2 className="h-3.5 w-3.5" />}
              gradient="from-[#7c5cbf] to-[#5a3d99]"
              accent="#7c5cbf"
              loading={!stats}
              delay={135}
              tooltip={stats ? `关联边 ${stats.edgeCount} 条` : undefined}
            />
          </div>
        )}

        <Tabs value={tab} onValueChange={setTab} className="gap-4">
          <SegmentedTabs
            className="w-full sm:w-auto [&>button]:flex-1 [&>button]:min-w-0 sm:[&>button]:flex-none"
            value={tab}
            onChange={setTab}
            options={[
              {
                value: 'global',
                label: (
                  <>
                    <Network className="h-3.5 w-3.5" strokeWidth={1.75} /> 全局图谱
                  </>
                ),
              },
              {
                value: 'neighborhood',
                label: (
                  <>
                    <GitBranch className="h-3.5 w-3.5" strokeWidth={1.75} /> 邻域查询
                  </>
                ),
              },
              {
                value: 'path',
                label: (
                  <>
                    <Route className="h-3.5 w-3.5" strokeWidth={1.75} /> 路径发现
                  </>
                ),
              },
            ]}
          />

          {/* ============ 全局图谱 ============ */}
          <TabsContent value="global" className="space-y-4">
            {/* 检索工具栏 */}
            <Panel>
              <PanelHead title="Query · 图谱检索" hint="STRUCTURE / LITERATURE" />
              <div className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center">
                <div className="relative flex-1">
                  <Search
                    className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
                    strokeWidth={1.75}
                  />
                  <Input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && void runSearch()}
                    placeholder="搜索结构标题 / PDB ID / 文献关键词…"
                    className="h-9 pl-8 text-xs"
                    aria-label="图谱搜索"
                  />
                </div>
                <Button onClick={() => void runSearch()} disabled={searching} className="h-9 gap-1.5 text-xs font-medium">
                  {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} /> : <Search className="h-3.5 w-3.5" strokeWidth={1.75} />}
                  搜索图谱
                </Button>
              </div>
            </Panel>

            {/* 搜索结果 */}
            {searchResults && (
              <Panel>
                <PanelHead
                  title="Results · 检索结果"
                  hint={`QUERY “${searchResults.query}” · ${searchResults.structures.length + searchResults.literature.length} 条`}
                />
                <div>
                  {searchResults.structures.length > 0 && (
                    <div>
                      <div className="label-tech border-b bg-muted/40 px-4 py-1.5 !text-[9px]">Structures · 结构</div>
                      <div className="divide-y">
                        {searchResults.structures.map((s) => (
                          <button
                            key={s.id}
                            type="button"
                            aria-label={`查看结构 ${s.id}`}
                            onClick={() => navigate('structure-detail', { id: s.id })}
                            className="flex w-full items-baseline gap-2.5 px-4 py-2 text-left transition-colors hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
                          >
                            <span className="num text-[13px] font-semibold tracking-tight">{s.id}</span>
                            <MethodBadge method={s.method} />
                            <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{s.title}</span>
                            <span className="num shrink-0 text-[10px] text-muted-foreground">LIT {s.literatureCount}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {searchResults.literature.length > 0 && (
                    <div>
                      <div className="label-tech border-b bg-muted/40 px-4 py-1.5 !text-[9px]">Literature · 文献</div>
                      <div className="max-h-64 divide-y overflow-y-auto custom-scrollbar">
                        {searchResults.literature.map((l) => (
                          <button
                            key={l.id}
                            type="button"
                            aria-label={`查看文献 ${l.label}`}
                            onClick={() => navigate('literature-detail', { id: l.id })}
                            className="flex w-full items-baseline gap-3 px-4 py-2 text-left transition-colors hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
                          >
                            <span className="num shrink-0 text-[10px] text-muted-foreground/60">{l.year ?? '—'}</span>
                            <span className="min-w-0 flex-1 truncate text-xs">{l.label}</span>
                            <span className="num shrink-0 text-[10px] text-muted-foreground">{l.structureCount} STRUCT</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {searchResults.structures.length === 0 && searchResults.literature.length === 0 && (
                    <Empty text="NO MATCH — 未找到匹配的结构或文献, 尝试其他关键词" />
                  )}
                </div>
              </Panel>
            )}

            <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
              {/* 力导向图画布 */}
              <Panel>
                <PanelHead
                  title="Global Graph · 全局关联网络"
                  hint={graph ? `${graph.stats.nodeCount}N · ${graph.stats.edgeCount}E · 拖拽/缩放/点击` : undefined}
                />
                <div className="p-2">
                  {loading ? (
                    <Skeleton className="shimmer h-[460px] w-full rounded-md" />
                  ) : graph && graph.nodes.length > 0 ? (
                    <div className="relative overflow-hidden rounded-md">
                      <ForceGraph nodes={graph.nodes} edges={graph.edges} height={460} onNodeClick={handleNodeClick} />
                      {/* 内凹屏幕质感 — 顶部暗色内影 (深浅色主题均可接受) */}
                      <div
                        className="pointer-events-none absolute inset-0 rounded-md shadow-[inset_0_1px_3px_rgba(0,0,0,0.08)]"
                        aria-hidden
                      />
                    </div>
                  ) : (
                    <Empty text="NO DATA — 请先上传文献并关联结构, 图谱节点随文献库自动生长" />
                  )}
                </div>
              </Panel>

              {/* 热门结构 */}
              <Panel className="flex flex-col">
                <PanelHead title="Top Structures · 热门结构" hint="BY 文献关联" />
                <div className="max-h-[478px] flex-1 divide-y overflow-y-auto custom-scrollbar">
                  {loading && Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="px-4 py-3">
                      <Skeleton className="shimmer h-3.5 w-20" />
                      <Skeleton className="shimmer mt-1.5 h-2.5 w-full" />
                    </div>
                  ))}
                  {popular.map((s, i) => (
                    <button
                      key={s.id}
                      type="button"
                      aria-label={`查看结构 ${s.id}`}
                      onClick={() => navigate('structure-detail', { id: s.id })}
                      className="flex w-full items-baseline gap-2.5 px-4 py-2.5 text-left transition-colors hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
                    >
                      <span
                        className={cn(
                          'num w-4 shrink-0 text-[10px]',
                          i < 3 ? 'font-semibold text-primary' : 'text-muted-foreground/60'
                        )}
                      >
                        {String(i + 1).padStart(2, '0')}
                      </span>
                      <span className="num text-[13px] font-semibold tracking-tight">{s.id}</span>
                      <span className="ml-auto num shrink-0 text-[10px] text-muted-foreground">{s.linkCount} 篇</span>
                      <span className="sr-only">{s.title}</span>
                    </button>
                  ))}
                  {!loading && popular.length === 0 && <Empty text="NO DATA — 暂无文献关联结构" />}
                </div>
              </Panel>
            </div>
          </TabsContent>

          {/* ============ 邻域查询 ============ */}
          <TabsContent value="neighborhood" className="space-y-4">
            <Panel>
              <PanelHead title="Neighborhood · 邻域查询" hint="DEPTH 1–2" />
              <div className="p-3">
                <div className="flex flex-col gap-2.5 sm:flex-row sm:items-end">
                  <div className="flex-1 space-y-1.5">
                    <label htmlFor="nb-id" className="label-tech block !text-[10px]">PDB ID</label>
                    <Input
                      id="nb-id"
                      value={nbId}
                      onChange={(e) => setNbId(e.target.value.toUpperCase())}
                      onKeyDown={(e) => e.key === 'Enter' && void runNeighborhood()}
                      placeholder="例如 6M0J"
                      className="h-9 font-mono text-xs uppercase"
                    />
                  </div>
                  <div className="w-full space-y-1.5 sm:w-[180px]">
                    <label className="label-tech block !text-[10px]">展开深度</label>
                    <Select value={nbDepth} onValueChange={setNbDepth}>
                      <SelectTrigger className="h-9 rounded-[5px] text-xs" aria-label="展开深度">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="1">1 — 直接关联</SelectItem>
                        <SelectItem value="2">2 — 二级扩展</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <Button onClick={() => void runNeighborhood()} disabled={nbLoading} className="h-9 gap-1.5 text-xs font-medium">
                    {nbLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} /> : <GitBranch className="h-3.5 w-3.5" strokeWidth={1.75} />}
                    查询邻域
                  </Button>
                </div>
                <p className="label-tech mt-2.5 !text-[9px] normal-case !tracking-normal">
                  深度 1 显示该结构直接关联的文献与 UniProt · 深度 2 额外展开共享文献的其他结构
                </p>
              </div>
            </Panel>

            {nbLoading && (
              <Panel>
                <div className="p-2">
                  <Skeleton className="shimmer h-[460px] w-full rounded-md" />
                </div>
              </Panel>
            )}
            {nbError && (
              <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
                <div className="label-tech !text-[10px] !text-destructive">NEIGHBORHOOD QUERY FAILED</div>
                <p className="mt-1 text-xs text-destructive/90">{nbError}</p>
              </div>
            )}
            {nbData && !nbLoading && (
              <Panel>
                <PanelHead
                  title={`NB · ${nbData.center}`}
                  hint={`${nbData.stats.nodeCount}N · ${nbData.stats.edgeCount}E · DEPTH ${nbData.depth}`}
                />
                <div className="p-2">
                  {nbData.nodes.length > 1 ? (
                    <div className="relative overflow-hidden rounded-md">
                      <ForceGraph
                        nodes={nbData.nodes}
                        edges={nbData.edges}
                        height={460}
                        centerId={`struct:${nbData.center}`}
                        onNodeClick={handleNodeClick}
                      />
                      <div
                        className="pointer-events-none absolute inset-0 rounded-md shadow-[inset_0_1px_3px_rgba(0,0,0,0.08)]"
                        aria-hidden
                      />
                    </div>
                  ) : (
                    <Empty text={`NO LINKS — ${nbData.center} 暂无关联文献, 请先在文献中检测该结构`} />
                  )}
                </div>
              </Panel>
            )}
            {!nbData && !nbLoading && !nbError && (
              <Panel>
                <PanelHead title="Neighborhood · 邻域查询" hint="STANDBY" />
                <Empty text="READY — 输入 PDB ID 查询其知识图谱邻域" />
              </Panel>
            )}
          </TabsContent>

          {/* ============ 路径发现 ============ */}
          <TabsContent value="path" className="space-y-4">
            <Panel>
              <PanelHead title="Path Finder · 路径发现" hint="BFS ≤ 2 跳" />
              <div className="p-3">
                <div className="flex flex-col gap-2.5 sm:flex-row sm:items-end">
                  <div className="flex-1 space-y-1.5">
                    <label htmlFor="path-src" className="label-tech block !text-[10px]">起点结构 · PDB</label>
                    <Input
                      id="path-src"
                      value={pathSource}
                      onChange={(e) => setPathSource(e.target.value.toUpperCase())}
                      placeholder="例如 6M0J"
                      className="h-9 font-mono text-xs uppercase"
                    />
                  </div>
                  <div className="flex-1 space-y-1.5">
                    <label htmlFor="path-dst" className="label-tech block !text-[10px]">终点结构 · PDB</label>
                    <Input
                      id="path-dst"
                      value={pathTarget}
                      onChange={(e) => setPathTarget(e.target.value.toUpperCase())}
                      placeholder="例如 7A5I"
                      className="h-9 font-mono text-xs uppercase"
                    />
                  </div>
                  <Button onClick={() => void runPath()} disabled={pathLoading} className="h-9 gap-1.5 text-xs font-medium">
                    {pathLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} /> : <Route className="h-3.5 w-3.5" strokeWidth={1.75} />}
                    发现路径
                  </Button>
                </div>
                <p className="label-tech mt-2.5 !text-[9px] normal-case !tracking-normal">
                  通过 BFS 在图谱中寻找两个结构间的最短关联链, 并计算首条实体序列的相似度
                </p>
              </div>
            </Panel>

            {pathLoading && (
              <Panel>
                <div className="p-4">
                  <Skeleton className="shimmer h-8 w-48" />
                  <Skeleton className="shimmer mt-4 h-7 w-full" />
                  <Skeleton className="shimmer mt-4 h-16 w-full" />
                </div>
              </Panel>
            )}
            {pathResult && !pathLoading && (
              <Panel>
                <PanelHead
                  title="Path Result · 路径结果"
                  hint={pathResult.connected ? `CONNECTED · ${pathResult.pathLength} NODES` : 'DISCONNECTED'}
                />
                <div className="space-y-4 p-4">
                  {/* 端点行 */}
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="num text-[13px] font-semibold tracking-tight">{pathResult.source}</span>
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/60" strokeWidth={1.75} />
                    <span className="num text-[13px] font-semibold tracking-tight">{pathResult.target}</span>
                    <span
                      className={cn(
                        'ml-1 rounded-[3px] border px-1.5 py-px font-mono text-[9px] font-medium',
                        pathResult.connected ? 'border-chart-1/45 text-chart-1' : 'border-destructive/45 text-destructive'
                      )}
                    >
                      {pathResult.connected ? 'CONNECTED' : 'DISCONNECTED'}
                    </span>
                  </div>

                  {/* 路径链 — mono 节点标签, 无插画 */}
                  {pathResult.path ? (
                    <div className="flex flex-wrap items-center gap-1.5">
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
                                'max-w-[240px] truncate rounded-[3px] border px-1.5 py-px font-mono text-[10px] transition-colors',
                                isStruct
                                  ? 'border-chart-1/40 text-chart-1 hover:bg-accent'
                                  : 'border-chart-2/40 text-chart-2 hover:bg-accent'
                              )}
                              title={title || rawId}
                            >
                              {isStruct ? rawId : (title ? title.slice(0, 18) : rawId.slice(0, 8))}
                            </button>
                            {i < pathResult.path!.length - 1 && (
                              <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground/50" strokeWidth={1.75} />
                            )}
                          </span>
                        );
                      })}
                    </div>
                  ) : (
                    <Empty text="NO PATH — 两个结构之间不存在 ≤ 2 跳的文献关联路径" />
                  )}

                  {/* 指标条 — hairline 分隔 */}
                  <div className="grid grid-cols-3 divide-x divide-border rounded-md border">
                    <div className="px-3.5 py-2.5">
                      <div className="label-tech !text-[9px]">路径长度</div>
                      <div className="num mt-1 text-lg font-medium leading-none tracking-tight">
                        {pathResult.pathLength != null ? pathResult.pathLength : '—'}
                      </div>
                    </div>
                    <div className="px-3.5 py-2.5">
                      <div className="label-tech !text-[9px]">首实体序列相似度</div>
                      <div className="num mt-1 text-lg font-medium leading-none tracking-tight">
                        {pathResult.sequenceSimilarity != null ? `${pathResult.sequenceSimilarity}%` : '—'}
                      </div>
                      {pathResult.sequenceSimilarity != null && (
                        <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted">
                          <div
                            className={cn(
                              'h-full rounded-full',
                              pathResult.sequenceSimilarity >= 40
                                ? 'bg-chart-1'
                                : pathResult.sequenceSimilarity >= 20
                                  ? 'bg-chart-2'
                                  : 'bg-chart-4'
                            )}
                            style={{ width: `${Math.min(100, pathResult.sequenceSimilarity)}%` }}
                          />
                        </div>
                      )}
                    </div>
                    <div className="px-3.5 py-2.5">
                      <div className="label-tech !text-[9px]">中间文献</div>
                      <div className="num mt-1 text-lg font-medium leading-none tracking-tight">
                        {pathResult.path ? pathResult.path.filter((n) => n.startsWith('lit:')).length : '—'}
                      </div>
                    </div>
                  </div>
                </div>
              </Panel>
            )}
            {!pathResult && !pathLoading && (
              <Panel>
                <PanelHead title="Path Finder · 路径发现" hint="STANDBY" />
                <Empty text="READY — 输入两个 PDB ID, 发现它们之间的关联路径" />
              </Panel>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
