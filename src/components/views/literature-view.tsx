'use client';

/**
 * CryoAgent Pro — 文献管理 · Library Index (BENCH 设计系统)
 * masthead(坐标纸) + 检索工具行 + 密集索引列表(hairline 行) + 分页页脚 + 上传解析面板
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import {
  ChevronLeft, ChevronRight, ExternalLink, FileText, Loader2,
  Search, Star, Trash2, Upload, X,
} from 'lucide-react';

// ============ 类型定义 (API 契约) ============

type SortKey = 'recent' | 'year' | 'title';

interface LiteratureItem {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  journal: string | null;
  doi: string | null;
  parseStatus: string;
  chunkCount: number;
  wordCount: number;
  fileSize: number | null;
  isFavorite: boolean;
  createdAt: string;
  structureCount: number;
  noteCount: number;
}

interface LiteratureListResponse {
  total: number;
  page: number;
  pageSize: number;
  items: LiteratureItem[];
}

interface UploadResponse {
  success: boolean;
  literature: { id: string; title: string; chunkCount: number; wordCount: number; pageCount: number };
  detected: { pdbIds: string[]; uniprotIds: string[]; linkedStructures: number };
}

// ============ 工具函数 ============

const UPLOAD_PHASES = ['正在上传文件…', '正在解析文档内容…', '正在分块并建立索引…', '正在检测关联结构…'];

function formatSize(bytes: number | null): string {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toISOString().slice(0, 10);
  } catch {
    return iso;
  }
}

// ============ 文献索引行 (密集列表) ============

function LiteratureRow({
  item,
  index,
  onDeleted,
  onFavoriteToggled,
}: {
  item: LiteratureItem;
  index: number;
  onDeleted: (id: string) => void;
  onFavoriteToggled: (id: string, isFavorite: boolean) => void;
}) {
  const navigate = useAppStore((s) => s.navigate);
  const [fav, setFav] = useState(item.isFavorite);
  const [favBusy, setFavBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const toggleFav = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (favBusy) return;
    const next = !fav;
    setFavBusy(true);
    setFav(next); // 乐观更新
    try {
      await api<{ success: boolean }>(`/api/literature/${item.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ isFavorite: next }),
      });
      onFavoriteToggled(item.id, next);
      toast.success(next ? '已加入收藏' : '已取消收藏');
    } catch (err) {
      setFav(!next);
      toast.error(err instanceof Error ? err.message : '操作失败');
    } finally {
      setFavBusy(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api<{ success: boolean }>(`/api/literature/${item.id}`, { method: 'DELETE' });
      toast.success('文献已删除');
      onDeleted(item.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeleting(false);
      setConfirmOpen(false);
    }
  };

  return (
    <div className="relative">
      <div
        role="button"
        tabIndex={0}
        aria-label={`打开文献 ${item.title}`}
        className="group flex min-h-11 cursor-pointer items-start gap-3 px-4 py-2.5 transition-colors hover:bg-accent/50 md:items-center"
        onClick={() => navigate('literature-detail', { id: item.id })}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            navigate('literature-detail', { id: item.id });
          }
        }}
      >
        {/* 序号 — 期刊目录式 */}
        <span className="num hidden w-7 shrink-0 pt-1 text-[10px] text-muted-foreground/60 md:block md:pt-0">
          {String(index + 1).padStart(2, '0')}
        </span>

        {/* 标题 + 书目元信息 */}
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <h3 className="truncate text-[13px] font-medium leading-snug">{item.title}</h3>
            {item.parseStatus !== 'parsed' && (
              <span className="shrink-0 rounded-[3px] border border-chart-2/50 px-1.5 py-px font-mono text-[9px] font-medium tracking-wide text-chart-2">
                {item.parseStatus.toUpperCase()}
              </span>
            )}
            {fav && (
              <span className="shrink-0 rounded-[3px] border border-chart-2/40 px-1.5 py-px font-mono text-[9px] font-medium tracking-wide text-chart-2/90">
                收藏
              </span>
            )}
          </div>
          <div className="mt-0.5 flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 text-[11px] text-muted-foreground">
            <span className="max-w-[45%] truncate">
              {item.authors.length > 0
                ? `${item.authors.slice(0, 3).join(', ')}${item.authors.length > 3 ? ' 等' : ''}`
                : '未知作者'}
            </span>
            <span className="shrink-0">{[item.year, item.journal].filter(Boolean).join(' · ') || '—'}</span>
            {item.doi && (
              <a
                href={`https://doi.org/${item.doi}`}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="inline-flex max-w-[200px] shrink-0 items-center gap-0.5 truncate font-mono text-[10px] text-primary hover:underline"
              >
                <ExternalLink className="h-2.5 w-2.5 shrink-0" strokeWidth={1.75} />
                <span className="truncate">{item.doi}</span>
              </a>
            )}
            <span className="num shrink-0 text-[10px] text-muted-foreground/80 md:hidden">
              {item.chunkCount} CHK · {item.structureCount} PDB
            </span>
          </div>
        </div>

        {/* 统计列 — mono 数字 */}
        <div className="hidden shrink-0 items-center gap-3 md:flex">
          <span className="num text-[10px] text-muted-foreground" title="检索分块">{item.chunkCount} CHK</span>
          <span className="num text-[10px] text-muted-foreground" title="总词数">{(item.wordCount / 1000).toFixed(1)}k W</span>
          <span className="num text-[10px] text-muted-foreground" title="关联结构">{item.structureCount} PDB</span>
          {item.noteCount > 0 && (
            <span className="num text-[10px] text-muted-foreground" title="阅读笔记">{item.noteCount} NOTE</span>
          )}
        </div>

        {/* 入库日期 */}
        <span
          className="num hidden w-[76px] shrink-0 text-right text-[10px] text-muted-foreground/70 lg:block"
          title={`${formatSize(item.fileSize)} · ${item.parseStatus}`}
        >
          {formatDate(item.createdAt)}
        </span>

        {/* 行操作: 收藏常显, 删除悬停显示 (移动端常显) */}
        <div className="flex shrink-0 items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="h-11 w-11 md:h-8 md:w-8"
            aria-label={fav ? '取消收藏' : '加入收藏'}
            disabled={favBusy}
            onClick={toggleFav}
          >
            {favBusy ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.75} />
            ) : (
              <Star
                className={cn('h-4 w-4', fav ? 'fill-chart-2 text-chart-2' : 'text-muted-foreground')}
                strokeWidth={1.75}
              />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-11 w-11 text-muted-foreground transition-colors hover:text-destructive md:h-8 md:w-8 md:opacity-0 md:group-hover:opacity-100"
            aria-label="删除文献"
            onClick={(e) => {
              e.stopPropagation();
              setConfirmOpen(true);
            }}
          >
            <Trash2 className="h-4 w-4" strokeWidth={1.75} />
          </Button>
        </div>
      </div>

      {/* 删除确认 */}
      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除文献?</AlertDialogTitle>
            <AlertDialogDescription>
              此操作将删除「{item.title}」及其全部分块、索引与关联关系, 且不可恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction
              disabled={deleting}
              className="bg-destructive text-white hover:bg-destructive/90"
              onClick={(e) => {
                e.preventDefault();
                void handleDelete();
              }}
            >
              {deleting ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} /> : '删除'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// ============ 主视图 ============

export function LiteratureView() {
  // 列表状态
  const [searchInput, setSearchInput] = useState('');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<SortKey>('recent');
  const [favOnly, setFavOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [data, setData] = useState<LiteratureListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // 上传状态
  const [uploadOpen, setUploadOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [titleInput, setTitleInput] = useState('');
  const [uploading, setUploading] = useState(false);
  const [phase, setPhase] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 搜索防抖
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(searchInput.trim());
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  // 拉取列表 (服务端分页)
  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    setLoading(true);
    const params = new URLSearchParams({ page: String(page), pageSize: String(pageSize), sort });
    if (query) params.set('q', query);
    if (favOnly) params.set('favorite', 'true');
    api<LiteratureListResponse>(`/api/literature?${params.toString()}`, { signal: ctrl.signal })
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
  }, [query, page, pageSize, sort, favOnly, reloadKey]);

  // 上传阶段的进度文案轮换
  useEffect(() => {
    if (!uploading) {
      setPhase(0);
      return;
    }
    const t = setInterval(() => setPhase((p) => Math.min(p + 1, UPLOAD_PHASES.length - 1)), 1500);
    return () => clearInterval(t);
  }, [uploading]);

  const handleDeleted = useCallback((id: string) => {
    setData((d) => (d ? { ...d, total: Math.max(0, d.total - 1), items: d.items.filter((it) => it.id !== id) } : d));
  }, []);

  const handleFavoriteToggled = useCallback(
    (id: string, isFavorite: boolean) => {
      setData((d) => {
        if (!d) return d;
        // 收藏过滤模式下取消收藏 → 从列表移除
        if (favOnly && !isFavorite) {
          return { ...d, total: Math.max(0, d.total - 1), items: d.items.filter((it) => it.id !== id) };
        }
        return { ...d, items: d.items.map((it) => (it.id === id ? { ...it, isFavorite } : it)) };
      });
    },
    [favOnly]
  );

  const handleUpload = async () => {
    if (!file) {
      toast.error('请先选择 PDF / TXT / MD 文件');
      return;
    }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      if (titleInput.trim()) fd.append('title', titleInput.trim());
      const d = await api<UploadResponse>('/api/literature', { method: 'POST', body: fd });
      toast.success(`上传成功：${d.literature.title}`, {
        description: `解析为 ${d.literature.chunkCount} 个分块 · 检测到 ${d.detected.pdbIds.length} 个 PDB ID · 自动关联 ${d.detected.linkedStructures} 个结构`,
      });
      setUploadOpen(false);
      setFile(null);
      setTitleInput('');
      if (fileInputRef.current) fileInputRef.current.value = '';
      setPage(1);
      setReloadKey((k) => k + 1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '上传失败');
    } finally {
      setUploading(false);
    }
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1;
  const hasFilter = Boolean(query) || favOnly;

  return (
    <div className="animate-fade-in-up">
      {/* ===== Masthead — 坐标纸 + 编辑性标题 ===== */}
      <div className="grid-bg border-b">
        <div className="flex flex-wrap items-end justify-between gap-4 px-4 py-6 md:px-6">
          <div>
            <div className="label-tech !text-[10px]">Library · 文献管理</div>
            <h1 className="font-display mt-1.5 text-[26px] font-semibold leading-none tracking-tight md:text-[30px]">
              文献库 <span className="title-accent">Index</span>
            </h1>
            <p className="mt-2.5 max-w-lg text-xs leading-relaxed text-muted-foreground">
              上传 PDF / TXT / MD 自动解析分块并建立 RAG 检索索引 · 同时检测文中 PDB / UniProt 标识并关联结构
            </p>
          </div>
          <div className="label-tech space-y-1.5 text-right !text-[10px]">
            <div className="flex items-center justify-end gap-2">
              <span className="status-dot" aria-hidden />
              {data ? `${data.total} ITEMS` : 'INDEXING…'}
            </div>
            <div className="text-muted-foreground/60">PDF · TXT · MD ≤ 30MB</div>
            <div className="text-muted-foreground/60">AUTO CHUNK · PDB LINK</div>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-4 md:p-6">
        {/* ===== 检索工具行 ===== */}
        <div className="flex flex-col gap-2.5 md:flex-row md:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" strokeWidth={1.75} />
            <Input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="搜索标题 / 作者 / 摘要 / 期刊 / 关键词…"
              className="h-11 pl-9 pr-9 md:h-9"
              aria-label="搜索文献"
            />
            {searchInput && (
              <button
                type="button"
                aria-label="清空搜索"
                className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-[4px] text-muted-foreground transition-colors hover:text-foreground"
                onClick={() => setSearchInput('')}
              >
                <X className="h-4 w-4" strokeWidth={1.75} />
              </button>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={sort}
              onValueChange={(v) => {
                setSort(v as SortKey);
                setPage(1);
              }}
            >
              <SelectTrigger className="h-11 w-[132px] md:h-9" aria-label="排序方式">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="recent">最近上传</SelectItem>
                <SelectItem value="year">年份排序</SelectItem>
                <SelectItem value="title">标题排序</SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              className={cn(
                'h-11 gap-1.5 md:h-9',
                favOnly && 'border-chart-2/60 bg-chart-2/10 text-chart-2 hover:bg-chart-2/15 hover:text-chart-2'
              )}
              onClick={() => {
                setFavOnly(!favOnly);
                setPage(1);
              }}
              aria-pressed={favOnly}
            >
              <Star className={cn('h-4 w-4', favOnly && 'fill-chart-2')} strokeWidth={1.75} />
              收藏
            </Button>
            <Button
              className="h-11 gap-1.5 md:h-9"
              onClick={() => setUploadOpen(true)}
            >
              <Upload className="h-4 w-4" strokeWidth={1.75} />
              上传文献
            </Button>
          </div>
        </div>

        {/* ===== 索引列表面板 ===== */}
        <section className="card-shadow overflow-hidden rounded-lg border bg-card">
          <div className="flex items-center gap-3 border-b px-4 py-2.5">
            <span className="label-tech !text-[10px] text-foreground/75">Library Index · 文献索引</span>
            {favOnly && <span className="label-tech !text-[9px] text-chart-2">FAVORITE ONLY</span>}
            {query && <span className="label-tech !text-[9px] normal-case !tracking-normal text-muted-foreground/70 truncate">“{query}”</span>}
            <span className="label-tech ml-auto !text-[9px]">
              {data ? `${data.total} 篇 · 显示 ${data.items.length}` : '—'}
            </span>
          </div>

          {loading ? (
            <div className="divide-y">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-4 py-3">
                  <Skeleton className="shimmer hidden h-3 w-6 md:block" />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <Skeleton className="shimmer h-4 w-3/5" />
                    <Skeleton className="shimmer h-3 w-2/5" />
                  </div>
                  <Skeleton className="shimmer hidden h-3 w-40 md:block" />
                  <Skeleton className="shimmer h-8 w-8" />
                </div>
              ))}
            </div>
          ) : error ? (
            <div className="p-4">
              <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
                <div className="label-tech !text-[10px] !text-destructive">INDEX LOAD FAILED · 列表加载失败</div>
                <p className="mt-1 text-sm text-destructive">{error}</p>
                <Button variant="outline" size="sm" className="mt-3 h-9" onClick={() => setReloadKey((k) => k + 1)}>
                  重试
                </Button>
              </div>
            </div>
          ) : data && data.items.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 px-4 py-12 text-center">
              <div className="label-tech !text-[10px] normal-case !tracking-[0.06em]">
                {hasFilter ? 'NO MATCH — 没有匹配的文献, 调整关键词或清除筛选' : 'NO DATA — 文献库为空, 上传第一篇 PDF 开始构建知识库'}
              </div>
              {!hasFilter && (
                <Button className="h-11 gap-1.5 md:h-9" onClick={() => setUploadOpen(true)}>
                  <Upload className="h-4 w-4" strokeWidth={1.75} />
                  上传第一篇文献
                </Button>
              )}
            </div>
          ) : data ? (
            <div className="divide-y">
              {data.items.map((item, i) => (
                <LiteratureRow
                  key={item.id}
                  item={item}
                  index={(data.page - 1) * data.pageSize + i}
                  onDeleted={handleDeleted}
                  onFavoriteToggled={handleFavoriteToggled}
                />
              ))}
            </div>
          ) : null}

          {/* ===== 分页页脚 ===== */}
          {data && data.items.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-t px-4 py-2">
              <span className="label-tech !text-[9px]">
                PAGE {data.page}/{totalPages} · {data.total} ITEMS
              </span>
              <div className="ml-auto flex flex-wrap items-center gap-1.5">
                <Select
                  value={String(pageSize)}
                  onValueChange={(v) => {
                    setPageSize(Number(v));
                    setPage(1);
                  }}
                >
                  <SelectTrigger size="sm" className="h-8 w-[92px]" aria-label="每页数量">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="12">12 / 页</SelectItem>
                    <SelectItem value="24">24 / 页</SelectItem>
                    <SelectItem value="48">48 / 页</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="h-11 gap-1 md:h-8"
                  aria-label="上一页"
                >
                  <ChevronLeft className="h-4 w-4" strokeWidth={1.75} />
                  上一页
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  className="h-11 gap-1 md:h-8"
                  aria-label="下一页"
                >
                  下一页
                  <ChevronRight className="h-4 w-4" strokeWidth={1.75} />
                </Button>
              </div>
            </div>
          )}
        </section>
      </div>

      {/* ===== 上传对话框 — 解析流水线 ===== */}
      <Dialog open={uploadOpen} onOpenChange={(open) => !uploading && setUploadOpen(open)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-baseline gap-2">
              上传文献
              <span className="label-tech !text-[9px]">INGEST · RAG INDEX</span>
            </DialogTitle>
            <DialogDescription>
              支持 PDF / TXT / MD (最大 30MB)。系统将自动解析、分块并建立 RAG 索引, 同时检测文中提及的 PDB / UniProt ID。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <input
              ref={fileInputRef}
              id="literature-file"
              type="file"
              accept=".pdf,.txt,.md,.text"
              className="hidden"
              disabled={uploading}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <label
              htmlFor="literature-file"
              className={cn(
                'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-6 text-center transition-colors',
                uploading && 'pointer-events-none opacity-70',
                file
                  ? 'border-primary/50 bg-accent/30'
                  : 'border-muted-foreground/30 hover:border-foreground/30 hover:bg-accent/20'
              )}
            >
              {file ? (
                <FileText className="h-5 w-5 text-primary" strokeWidth={1.75} />
              ) : (
                <Upload className="h-5 w-5 text-muted-foreground" strokeWidth={1.75} />
              )}
              {file ? (
                <span className="max-w-full truncate text-sm font-medium">{file.name}</span>
              ) : (
                <span className="text-sm text-muted-foreground">点击选择文件 (PDF / TXT / MD)</span>
              )}
              <span className="num text-[11px] text-muted-foreground">{formatSize(file?.size ?? null)}</span>
            </label>

            <div className="space-y-1.5">
              <label htmlFor="literature-title" className="label-tech block !text-[10px]">
                自定义标题 (可选)
              </label>
              <Input
                id="literature-title"
                value={titleInput}
                onChange={(e) => setTitleInput(e.target.value)}
                placeholder="留空则自动从 PDF 元数据提取"
                disabled={uploading}
                className="h-9"
              />
            </div>

            {uploading && (
              <div className="rounded-lg border px-3 py-2.5">
                {UPLOAD_PHASES.map((ph, i) => (
                  <div key={ph} className="flex min-h-7 items-center gap-2">
                    <span
                      className="status-dot"
                      data-tone={i === phase ? 'amber' : i < phase ? undefined : 'muted'}
                      aria-hidden
                    />
                    <span
                      className={cn(
                        'text-xs',
                        i === phase ? 'font-medium text-foreground' : 'text-muted-foreground',
                        i > phase && 'opacity-60'
                      )}
                    >
                      {ph}
                    </span>
                  </div>
                ))}
                <p className="label-tech mt-1.5 !text-[9px] normal-case !tracking-normal text-muted-foreground/70">
                  解析较大 PDF 可能需要十几秒, 请勿关闭对话框
                </p>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" disabled={uploading} onClick={() => setUploadOpen(false)} className="h-9">
              取消
            </Button>
            <Button disabled={!file || uploading} onClick={() => void handleUpload()} className="h-9 gap-1.5">
              {uploading && <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} />}
              {uploading ? '处理中…' : '上传并解析'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
