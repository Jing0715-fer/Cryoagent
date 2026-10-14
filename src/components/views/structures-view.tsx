'use client';

/**
 * CryoAgent Pro — 结构浏览器
 * 本地缓存列表 (搜索/方法过滤/分页) + RCSB 远程搜索
 */

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import {
  Boxes, ChevronLeft, ChevronRight, Dna, FileText, Loader2, Search, TriangleAlert, X,
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

// ============ 工具函数 ============

function MethodBadge({ method }: { method: string | null }) {
  const m = (method || '').toUpperCase();
  let cls = 'border-border bg-muted text-muted-foreground';
  let label = method || '未知方法';
  if (m.includes('X-RAY')) {
    cls = 'border-teal-500/30 bg-teal-500/10 text-teal-700 dark:text-teal-300';
    label = 'X-RAY';
  } else if (m.includes('ELECTRON MICROSCOPY')) {
    cls = 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300';
    label = 'Cryo-EM';
  } else if (m.includes('NMR')) {
    cls = 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300';
    label = 'NMR';
  } else if (m.includes('ALPHAFOLD') || m.includes('PREDICT')) {
    cls = 'border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-700 dark:text-fuchsia-300';
    label = '预测模型';
  }
  return (
    <Badge variant="outline" className={cn('shrink-0 text-[11px]', cls)}>
      {label}
    </Badge>
  );
}

function sourceLabel(source: string | null): string {
  switch (source) {
    case 'rcsb':
      return 'RCSB 缓存';
    case 'auto-extracted':
      return '文献提取';
    case 'seed':
      return '示例数据';
    default:
      return source || '本地缓存';
  }
}

// ============ 本地结构卡片 ============

function StructureCard({ item, index }: { item: StructureListItem; index: number }) {
  const navigate = useAppStore((s) => s.navigate);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: Math.min(index * 0.04, 0.4), ease: 'easeOut' }}
      className="h-full"
    >
      <Card
        role="button"
        tabIndex={0}
        aria-label={`查看结构 ${item.id}`}
        className="flex h-full cursor-pointer flex-col gap-3 p-4 transition-all hover:border-teal-500/50 hover:shadow-md"
        onClick={() => navigate('structure-detail', { id: item.id })}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            navigate('structure-detail', { id: item.id });
          }
        }}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-lg font-bold tracking-wide text-teal-700 dark:text-teal-300">
            {item.id}
          </span>
          <MethodBadge method={item.method} />
        </div>

        <p className="line-clamp-2 min-h-10 text-sm font-medium leading-snug">{item.title}</p>

        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
          {item.resolution != null && <Badge variant="secondary">{item.resolution} Å</Badge>}
          {item.entityCount != null && <Badge variant="secondary">{item.entityCount} 实体</Badge>}
          <Badge variant="secondary" className="gap-1">
            <FileText className="h-3 w-3" />
            {item.literatureCount} 文献
          </Badge>
        </div>

        {item.organism && (
          <p className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
            <Dna className="h-3 w-3 shrink-0" />
            {item.organism}
          </p>
        )}

        <div className="mt-auto flex items-center justify-between border-t pt-2 text-[11px] text-muted-foreground">
          <span>{sourceLabel(item.source)}</span>
          <span>访问 {item.accessCount} 次</span>
        </div>
      </Card>
    </motion.div>
  );
}

// ============ RCSB 搜索命中卡片 ============

function RcsbHitCard({ hit, index }: { hit: RcsbHit; index: number }) {
  const navigate = useAppStore((s) => s.navigate);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: Math.min(index * 0.04, 0.4), ease: 'easeOut' }}
      className="h-full"
    >
      <Card
        role="button"
        tabIndex={0}
        aria-label={`查看 RCSB 结构 ${hit.identifier}`}
        className="flex h-full cursor-pointer flex-col gap-3 p-4 transition-all hover:border-teal-500/50 hover:shadow-md"
        onClick={() => navigate('structure-detail', { id: hit.identifier })}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            navigate('structure-detail', { id: hit.identifier });
          }
        }}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-lg font-bold tracking-wide text-teal-700 dark:text-teal-300">
            {hit.identifier}
          </span>
          <div className="flex shrink-0 items-center gap-1.5">
            {hit.cached && (
              <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
                已缓存
              </Badge>
            )}
            <Badge variant="secondary">得分 {hit.score.toFixed(1)}</Badge>
          </div>
        </div>

        <p className="line-clamp-2 min-h-10 text-sm font-medium leading-snug">{hit.title || '未提供标题'}</p>

        <div className="mt-auto flex flex-wrap items-center gap-1.5">
          <MethodBadge method={hit.method ?? null} />
          {hit.resolution != null && <Badge variant="secondary">{hit.resolution} Å</Badge>}
        </div>
      </Card>
    </motion.div>
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
    <div className="mx-auto w-full max-w-7xl p-4 md:p-6">
      {/* 页头 */}
      <div className="mb-4 flex items-center gap-2">
        <Boxes className="h-5 w-5 text-teal-600 dark:text-teal-400" />
        <h2 className="text-lg font-semibold">结构浏览器</h2>
        {tab === 'local' && data && <span className="text-sm text-muted-foreground">共 {data.total} 个结构</span>}
      </div>

      <Tabs value={tab} onValueChange={setTab} className="gap-4">
        <TabsList className="grid h-auto w-full grid-cols-2 sm:inline-flex sm:w-auto">
          <TabsTrigger value="local" className="px-4 py-1.5 text-xs sm:text-sm">本地缓存</TabsTrigger>
          <TabsTrigger value="rcsb" className="px-4 py-1.5 text-xs sm:text-sm">RCSB 搜索</TabsTrigger>
        </TabsList>

        {/* ======== 本地缓存 ======== */}
        <TabsContent value="local" className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="搜索 PDB ID 或标题…"
                className="pl-9 pr-9"
                aria-label="搜索本地结构"
              />
              {searchInput && (
                <button
                  type="button"
                  aria-label="清空搜索"
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
                  onClick={() => setSearchInput('')}
                >
                  <X className="h-4 w-4" />
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
              <SelectTrigger className="w-full sm:w-[220px]" aria-label="实验方法过滤">
                <SelectValue placeholder="实验方法" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部方法</SelectItem>
                <SelectItem value="X-RAY DIFFRACTION">X-RAY DIFFRACTION</SelectItem>
                <SelectItem value="ELECTRON MICROSCOPY">ELECTRON MICROSCOPY</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {loading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Card key={i} className="flex flex-col gap-3 p-4">
                  <div className="flex items-center justify-between">
                    <Skeleton className="h-6 w-20" />
                    <Skeleton className="h-5 w-14" />
                  </div>
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-3/5" />
                  <div className="mt-auto flex gap-2">
                    <Skeleton className="h-5 w-14" />
                    <Skeleton className="h-5 w-14" />
                  </div>
                </Card>
              ))}
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed py-16 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-rose-500/10">
                <TriangleAlert className="h-6 w-6 text-rose-500" />
              </div>
              <div>
                <p className="font-medium">结构列表加载失败</p>
                <p className="mt-1 text-sm text-muted-foreground">{error}</p>
              </div>
              <Button variant="outline" size="sm" onClick={() => setReloadKey((k) => k + 1)}>
                重试
              </Button>
            </div>
          ) : data && data.items.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed py-16 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-teal-500/10">
                <Boxes className="h-6 w-6 text-teal-600 dark:text-teal-400" />
              </div>
              <div>
                <p className="font-medium">{query || method !== 'all' ? '没有匹配的结构' : '本地结构缓存为空'}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {query || method !== 'all' ? '试试调整搜索关键词或方法过滤条件' : '切换到「RCSB 搜索」查找结构, 打开详情页后会自动缓存到本地'}
                </p>
              </div>
              {!query && method === 'all' && (
                <Button variant="outline" size="sm" onClick={() => setTab('rcsb')} className="gap-1.5">
                  <Search className="h-3.5 w-3.5" />
                  去搜索 RCSB
                </Button>
              )}
            </div>
          ) : data ? (
            <>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {data.items.map((item, i) => (
                  <StructureCard key={item.id} item={item} index={i} />
                ))}
              </div>

              {/* 分页 */}
              <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-between">
                <span className="text-xs text-muted-foreground">
                  共 {data.total} 个结构 · 第 {data.page}/{totalPages} 页
                </span>
                <div className="flex items-center gap-1.5">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    className="gap-1"
                  >
                    <ChevronLeft className="h-4 w-4" />
                    上一页
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    className="gap-1"
                  >
                    下一页
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </>
          ) : null}
        </TabsContent>

        {/* ======== RCSB 搜索 ======== */}
        <TabsContent value="rcsb" className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={rcsbQuery}
                onChange={(e) => setRcsbQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void runSearch()}
                placeholder="搜索 RCSB PDB 全文数据库, 如 spike protein, ribosome…"
                className="pl-9"
                aria-label="RCSB 搜索关键词"
              />
            </div>
            <div className="flex items-center gap-2">
              <Select value={String(limit)} onValueChange={(v) => setLimit(Number(v))}>
                <SelectTrigger className="w-[92px]" aria-label="结果数量">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="10">10 条</SelectItem>
                  <SelectItem value="20">20 条</SelectItem>
                  <SelectItem value="30">30 条</SelectItem>
                </SelectContent>
              </Select>
              <Button
                className="gap-1.5 bg-teal-600 text-white hover:bg-teal-700"
                disabled={searching}
                onClick={() => void runSearch()}
              >
                {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                {searching ? '搜索中…' : '搜索'}
              </Button>
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            远程搜索 RCSB Protein Data Bank · 点击结果进入详情页后将自动缓存到本地数据库
          </p>

          {searching ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Card key={i} className="flex flex-col gap-3 p-4">
                  <div className="flex items-center justify-between">
                    <Skeleton className="h-6 w-20" />
                    <Skeleton className="h-5 w-16" />
                  </div>
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-2/5" />
                </Card>
              ))}
            </div>
          ) : rcsbError ? (
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed py-16 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-rose-500/10">
                <TriangleAlert className="h-6 w-6 text-rose-500" />
              </div>
              <div>
                <p className="font-medium">RCSB 搜索失败</p>
                <p className="mt-1 max-w-md text-sm text-muted-foreground">{rcsbError}</p>
              </div>
              <Button variant="outline" size="sm" onClick={() => void runSearch()} className="gap-1.5">
                重试
              </Button>
            </div>
          ) : results ? (
            results.hits.length === 0 ? (
              <div className="rounded-xl border border-dashed py-12 text-center text-sm text-muted-foreground">
                未找到与「{results.query}」匹配的结构, 试试英文关键词
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {results.hits.map((hit, i) => (
                  <RcsbHitCard key={hit.identifier} hit={hit} index={i} />
                ))}
              </div>
            )
          ) : hasSearched ? null : (
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed py-16 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-teal-500/10">
                <Search className="h-6 w-6 text-teal-600 dark:text-teal-400" />
              </div>
              <div>
                <p className="font-medium">搜索 RCSB 结构数据库</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  输入蛋白质名称、物种或关键词, 例如「spike protein」「ribosome」「histone」
                </p>
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
