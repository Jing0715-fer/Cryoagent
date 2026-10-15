'use client';

/**
 * CryoAgent Pro — 结构浏览器 (BENCH 设计系统)
 * masthead(坐标纸) + 仪器面板式检索工具栏 + 密集行列表 + 分页导轨
 * 功能不变: 本地缓存列表 (防抖搜索/方法过滤/分页) + RCSB 远程搜索
 */

import { useEffect, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent } from '@/components/ui/tabs';
import { MethodBadge, SegmentedTabs } from '@/components/ui/bench-widgets';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import {
  ChevronLeft, ChevronRight, Loader2, Search, X,
} from 'lucide-react';

// ============ 类型定义 (API 契约) ============

type MethodFilter = 'all' | 'X-RAY DIFFRACTION' | 'ELECTRON MICROSCOPY';

interface StructureListItem {
  id: string;
  title: string;
  method: string | null;
  resolution: number | null;
  organism: string | null;
  entityCount: number | null;
  residueCount: number | null;
  literatureCount: number;
  accessCount: number;
  source: string | null;
  updatedAt: string;
}

interface StructuresListResponse {
  total: number;
  page: number;
  pageSize: number;
  items: StructureListItem[];
}

interface RcsbHit {
  identifier: string;
  score: number;
  title?: string;
  method?: string;
  resolution?: number;
  cached: boolean;
}

interface RcsbSearchResponse {
  query: string;
  total: number;
  hits: RcsbHit[];
}

// ============ BENCH 基础组件 ============

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
function Empty({ text, action }: { text: string; action?: React.ReactNode }) {
  return (
    <div className="flex h-full min-h-[120px] flex-col items-center justify-center gap-3 px-4 py-10 text-center">
      <p className="label-tech !text-[10px] normal-case !tracking-[0.06em]">{text}</p>
      {action}
    </div>
  );
}

/** 分辨率质量读数条 — 24×3px 仪器读数, 宽度按分辨率分档 (一眼判断数据质量) */
function ResolutionBar({ value }: { value: number | null }) {
  let widthPct = 25;
  let tone = 'bg-muted-foreground/35';
  if (value != null) {
    if (value <= 1.5) {
      widthPct = 100;
      tone = 'bg-chart-1';
    } else if (value <= 2.5) {
      widthPct = 80;
      tone = 'bg-chart-1';
    } else if (value <= 3.5) {
      widthPct = 60;
      tone = 'bg-chart-1';
    } else if (value <= 5) {
      widthPct = 40;
      tone = 'bg-chart-1';
    }
  }
  return (
    <span
      className="inline-flex h-[3px] w-6 shrink-0 items-center overflow-hidden rounded-[1px] bg-foreground/10"
      aria-hidden
    >
      <span className={cn('h-full rounded-[1px]', tone)} style={{ width: `${widthPct}%` }} />
    </span>
  );
}

/** 错误面板 — hairline destructive, 无图标装饰 */
function ErrorBlock({ label, message, onRetry }: { label: string; message: string; onRetry: () => void }) {
  return (
    <div className="m-4 rounded-md border border-destructive/40 bg-destructive/5 p-4">
      <div className="label-tech !text-[10px] !text-destructive">{label}</div>
      <p className="mt-1 text-xs leading-relaxed text-destructive/90">{message}</p>
      <Button variant="outline" size="sm" className="mt-3 h-8 border-destructive/40 text-xs text-destructive hover:bg-destructive/10" onClick={onRetry}>
        重试
      </Button>
    </div>
  );
}

function sourceLabel(source: string | null): string {
  switch (source) {
    case 'rcsb':
      return 'RCSB';
    case 'auto-extracted':
      return 'EXTRACT';
    case 'seed':
      return 'SEED';
    default:
      return 'LOCAL';
  }
}

// ============ 本地缓存 · 密集行 ============

function StructureRow({ item }: { item: StructureListItem }) {
  const navigate = useAppStore((s) => s.navigate);

  return (
    <button
      type="button"
      aria-label={`查看结构 ${item.id}`}
      onClick={() => navigate('structure-detail', { id: item.id })}
      className="group flex w-full flex-col gap-1 px-4 py-2.5 text-left transition-colors hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
        {/* PDB ID — 左侧 2px 分类短色条 + hover 转信号色 */}
        <span className="flex shrink-0 items-start gap-1.5">
          <span className="mt-[3px] h-3.5 w-[2px] shrink-0 bg-chart-1/70" aria-hidden />
          <span className="num text-[15px] font-semibold leading-none tracking-tight text-foreground transition-colors group-hover:text-primary">
            {item.id}
          </span>
        </span>
        <MethodBadge method={item.method} />
        {item.resolution != null && (
          <span className="flex shrink-0 items-center gap-1.5">
            <span className="num text-[10px] text-muted-foreground">{item.resolution.toFixed(1)}Å</span>
            <ResolutionBar value={item.resolution} />
          </span>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-2.5">
          <span className="num text-[10px] text-muted-foreground">LIT {item.literatureCount}</span>
          <span className="num hidden text-[10px] text-muted-foreground/60 sm:inline">VIEW {item.accessCount}</span>
          <span className="rounded-[3px] border border-border px-1 py-px font-mono text-[9px] text-muted-foreground/80">
            {sourceLabel(item.source)}
          </span>
        </span>
      </div>
      <p className="min-w-0 truncate text-xs text-muted-foreground">{item.title}</p>
      {/* 第二 mono 数据行 — 物种 / 实体 / 残基 */}
      {(item.organism || item.entityCount != null || item.residueCount != null) && (
        <div className="flex min-w-0 items-baseline gap-x-2.5">
          {item.organism && (
            <p className="min-w-0 max-w-[300px] truncate font-mono text-[10px] text-muted-foreground/55">
              {item.organism}
            </p>
          )}
          {item.entityCount != null && (
            <span className="num hidden shrink-0 text-[10px] text-muted-foreground/55 sm:inline">
              {item.entityCount} ENT
            </span>
          )}
          {item.residueCount != null && (
            <span className="num hidden shrink-0 text-[10px] text-muted-foreground/55 md:inline">
              {item.residueCount.toLocaleString()} RES
            </span>
          )}
        </div>
      )}
    </button>
  );
}

// ============ RCSB 搜索 · 密集行 ============

function RcsbHitRow({ hit }: { hit: RcsbHit }) {
  const navigate = useAppStore((s) => s.navigate);

  return (
    <button
      type="button"
      aria-label={`查看 RCSB 结构 ${hit.identifier}`}
      onClick={() => navigate('structure-detail', { id: hit.identifier })}
      className="group flex w-full flex-col gap-1 px-4 py-2.5 text-left transition-colors hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
        <span className="flex shrink-0 items-start gap-1.5">
          <span className="mt-[3px] h-3.5 w-[2px] shrink-0 bg-chart-1/70" aria-hidden />
          <span className="num text-[15px] font-semibold leading-none tracking-tight text-foreground transition-colors group-hover:text-primary">
            {hit.identifier}
          </span>
        </span>
        {hit.cached && (
          <span className="shrink-0 rounded-[3px] border border-primary/40 px-1.5 py-px font-mono text-[9px] font-medium text-primary">
            CACHED
          </span>
        )}
        <MethodBadge method={hit.method ?? null} />
        {hit.resolution != null && (
          <span className="flex shrink-0 items-center gap-1.5">
            <span className="num text-[10px] text-muted-foreground">{hit.resolution.toFixed(1)}Å</span>
            <ResolutionBar value={hit.resolution} />
          </span>
        )}
        <span className="num ml-auto shrink-0 text-[10px] text-muted-foreground/70">SCORE {hit.score.toFixed(1)}</span>
      </div>
      <p className="min-w-0 truncate text-xs text-muted-foreground">{hit.title || '未提供标题'}</p>
    </button>
  );
}

// ============ 主视图 ============

export function StructuresView() {
  const [tab, setTab] = useState('local');

  // 本地缓存列表状态
  const [searchInput, setSearchInput] = useState('');
  const [query, setQuery] = useState('');
  const [method, setMethod] = useState<MethodFilter>('all');
  const [page, setPage] = useState(1);
  const [pageSize] = useState(24);
  const [data, setData] = useState<StructuresListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // RCSB 搜索状态
  const [rcsbQuery, setRcsbQuery] = useState('');
  const [limit, setLimit] = useState(12);
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<RcsbSearchResponse | null>(null);
  const [rcsbError, setRcsbError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  // 搜索防抖
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(searchInput.trim());
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  // 拉取本地结构列表
  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    setLoading(true);
    const params = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
    if (query) params.set('q', query);
    if (method !== 'all') params.set('method', method);
    api<StructuresListResponse>(`/api/structures?${params.toString()}`, { signal: ctrl.signal })
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (cancelled || (err instanceof Error && err.name === 'AbortError')) return;
        setError(err instanceof Error ? err.message : '加载失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [query, page, pageSize, method, reloadKey]);

  // RCSB 搜索
  const runSearch = async () => {
    const q = rcsbQuery.trim();
    if (!q) {
      toast.error('请输入搜索关键词');
      return;
    }
    setSearching(true);
    setRcsbError(null);
    try {
      const d = await api<RcsbSearchResponse>('/api/structures', {
        method: 'POST',
        body: JSON.stringify({ query: q, limit }),
      });
      setResults(d);
      setHasSearched(true);
      if (d.hits.length === 0) toast.info('RCSB 中未找到匹配结构');
    } catch (err) {
      setRcsbError(err instanceof Error ? err.message : 'RCSB 搜索失败');
    } finally {
      setSearching(false);
    }
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1;

  return (
    <div className="animate-fade-in-up">
      {/* ===== Masthead — 坐标纸 + 编辑性标题 ===== */}
      <div className="grid-bg border-b">
        <div className="flex flex-wrap items-end justify-between gap-4 px-4 py-6 md:px-6">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="label-tech !text-[10px]">PDB Library · 结构浏览器</div>
              <span className="plate-label rounded-[3px] border border-border px-1.5 py-px" title="Chapter · Library">
                CH·LIB
              </span>
            </div>
            <h1 className="font-display mt-1.5 text-[26px] font-semibold leading-none tracking-tight md:text-[30px]">
              结构浏览器
              <span className="title-accent">Structure Library</span>
            </h1>
            <p className="mt-2.5 max-w-lg text-xs leading-relaxed text-muted-foreground">
              本地结构缓存与 RCSB Protein Data Bank 远程检索 — 打开详情自动入库, 支撑 3D 可视化与知识图谱关联
            </p>
          </div>
          <div className="label-tech space-y-1.5 text-right !text-[10px]">
            <div className="flex items-center justify-end gap-2">
              <span className="status-dot" aria-hidden />
              {loading ? 'SYNCING…' : `LOCAL CACHE ${data?.total ?? 0}`}
            </div>
            <div className="text-muted-foreground/60">RCSB REMOTE · SEARCH API</div>
          </div>
        </div>
      </div>

      <div className="p-4 md:p-6">
        <Tabs value={tab} onValueChange={setTab} className="gap-4">
          <SegmentedTabs
            className="w-full sm:w-auto [&>button]:flex-1 [&>button]:min-w-0 sm:[&>button]:flex-none"
            value={tab}
            onChange={setTab}
            options={[
              {
                value: 'local',
                label: (
                  <>
                    本地缓存
                    {data && <span className="num text-[9px] text-muted-foreground">{data.total}</span>}
                  </>
                ),
              },
              { value: 'rcsb', label: 'RCSB 搜索' },
            ]}
          />

          {/* ======== 本地缓存 ======== */}
          <TabsContent value="local" className="space-y-4">
            <Panel>
              <PanelHead
                title="Local Cache · 本地缓存"
                hint={data ? `${data.total} 条 · PAGE ${data.page}/${totalPages}` : undefined}
                action={
                  <button
                    type="button"
                    onClick={() => setReloadKey((k) => k + 1)}
                    className="label-tech ml-2 !text-[9px] text-primary transition-opacity hover:opacity-70"
                  >
                    重新拉取
                  </button>
                }
              />

              {/* 检索工具栏 */}
              <div className="flex flex-col gap-2 border-b px-3 py-2.5 sm:flex-row sm:items-center">
                <div className="relative flex-1">
                  <Search
                    className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
                    strokeWidth={1.75}
                  />
                  <Input
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                    placeholder="搜索 PDB ID 或标题…"
                    className="h-9 pl-8 pr-9 font-mono text-xs"
                    aria-label="搜索本地结构"
                  />
                  {searchInput && (
                    <button
                      type="button"
                      aria-label="清空搜索"
                      className="absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-[4px] text-muted-foreground transition-colors hover:text-foreground"
                      onClick={() => setSearchInput('')}
                    >
                      <X className="h-3.5 w-3.5" strokeWidth={1.75} />
                    </button>
                  )}
                </div>
                <Select
                  value={method}
                  onValueChange={(v) => {
                    setMethod(v as MethodFilter);
                    setPage(1);
                  }}
                >
                  <SelectTrigger className="h-9 w-full rounded-[5px] text-xs sm:w-[190px]" aria-label="实验方法过滤">
                    <SelectValue placeholder="实验方法" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部方法</SelectItem>
                    <SelectItem value="X-RAY DIFFRACTION">X-RAY DIFFRACTION</SelectItem>
                    <SelectItem value="ELECTRON MICROSCOPY">ELECTRON MICROSCOPY</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* 列表体 */}
              {loading ? (
                <div className="divide-y">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <div key={i} className="flex items-center gap-3 px-4 py-3">
                      <Skeleton className="shimmer h-4 w-14" />
                      <Skeleton className="shimmer h-4 w-16" />
                      <Skeleton className="shimmer h-3 flex-1" />
                      <Skeleton className="shimmer hidden h-3 w-20 sm:block" />
                    </div>
                  ))}
                </div>
              ) : error ? (
                <ErrorBlock label="LIST LOAD FAILED" message={error} onRetry={() => setReloadKey((k) => k + 1)} />
              ) : data && data.items.length === 0 ? (
                <Empty
                  text={
                    query || method !== 'all'
                      ? 'NO MATCH — 调整关键词或实验方法过滤条件'
                      : 'NO DATA — 本地缓存为空, 去 RCSB 搜索并打开结构详情后自动入库'
                  }
                  action={
                    !query && method === 'all' ? (
                      <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" onClick={() => setTab('rcsb')}>
                        <Search className="h-3.5 w-3.5" strokeWidth={1.75} />
                        去搜索 RCSB
                      </Button>
                    ) : undefined
                  }
                />
              ) : data ? (
                <div className="divide-y">
                  {data.items.map((item) => (
                    <StructureRow key={item.id} item={item} />
                  ))}
                </div>
              ) : null}

              {/* 分页导轨 */}
              {data && data.items.length > 0 && (
                <div className="flex flex-col items-center gap-2 border-t px-4 py-2 sm:flex-row sm:justify-between">
                  <span className="num text-[10px] text-muted-foreground">
                    {data.total} ENTRIES · PAGE {data.page}/{totalPages}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page <= 1}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      className="h-8 gap-1 text-xs"
                    >
                      <ChevronLeft className="h-3.5 w-3.5" strokeWidth={1.75} />
                      上一页
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page >= totalPages}
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      className="h-8 gap-1 text-xs"
                    >
                      下一页
                      <ChevronRight className="h-3.5 w-3.5" strokeWidth={1.75} />
                    </Button>
                  </div>
                </div>
              )}
            </Panel>
          </TabsContent>

          {/* ======== RCSB 搜索 ======== */}
          <TabsContent value="rcsb" className="space-y-4">
            <Panel>
              <PanelHead
                title="Remote Search · RCSB 检索"
                hint={results ? `${results.total} 条命中` : 'PDBe / RCSB API'}
              />

              {/* 检索工具栏 */}
              <div className="flex flex-col gap-2 border-b px-3 py-2.5 sm:flex-row sm:items-center">
                <div className="relative flex-1">
                  <Search
                    className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
                    strokeWidth={1.75}
                  />
                  <Input
                    value={rcsbQuery}
                    onChange={(e) => setRcsbQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && void runSearch()}
                    placeholder="检索 RCSB PDB 全文数据库, 如 spike protein, ribosome…"
                    className="h-9 pl-8 text-xs"
                    aria-label="RCSB 搜索关键词"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <Select value={String(limit)} onValueChange={(v) => setLimit(Number(v))}>
                    <SelectTrigger className="h-9 w-[92px] rounded-[5px] text-xs" aria-label="结果数量">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="10">10 条</SelectItem>
                      <SelectItem value="20">20 条</SelectItem>
                      <SelectItem value="30">30 条</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    className="h-9 gap-1.5 text-xs font-medium"
                    disabled={searching}
                    onClick={() => void runSearch()}
                  >
                    {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} /> : <Search className="h-3.5 w-3.5" strokeWidth={1.75} />}
                    {searching ? '检索中…' : '搜索'}
                  </Button>
                </div>
              </div>

              <div className="label-tech border-b px-4 py-2 !text-[9px] normal-case !tracking-normal">
                远程检索 RCSB Protein Data Bank · 命中结果打开详情页后自动缓存到本地数据库
              </div>

              {/* 结果体 */}
              {searching ? (
                <div className="divide-y">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="flex items-center gap-3 px-4 py-3">
                      <Skeleton className="shimmer h-4 w-14" />
                      <Skeleton className="shimmer h-4 w-16" />
                      <Skeleton className="shimmer h-3 flex-1" />
                    </div>
                  ))}
                </div>
              ) : rcsbError ? (
                <ErrorBlock label="RCSB SEARCH FAILED" message={rcsbError} onRetry={() => void runSearch()} />
              ) : results ? (
                results.hits.length === 0 ? (
                  <Empty text={`NO MATCH — 未找到与「${results.query}」匹配的结构, 尝试英文关键词`} />
                ) : (
                  <div className="divide-y">
                    {results.hits.map((hit) => (
                      <RcsbHitRow key={hit.identifier} hit={hit} />
                    ))}
                  </div>
                )
              ) : hasSearched ? null : (
                <Empty text="READY — 输入蛋白名称 / 物种 / 关键词开始检索, 如 spike protein · ribosome · histone" />
              )}
            </Panel>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
