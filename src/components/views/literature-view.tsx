'use client';

/**
 * CryoAgent Pro — 文献管理列表页
 * 搜索 / 排序 / 收藏过滤 / 分页 / 上传解析 / 文献卡片网格
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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
  BookOpen, ChevronLeft, ChevronRight, ExternalLink, FileText, Layers, Link2, Loader2,
  Search, Star, Trash2, TriangleAlert, Upload, X,
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

// ============ 文献卡片 ============

function LiteratureCard({
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
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: Math.min(index * 0.05, 0.4), ease: 'easeOut' }}
      className="h-full"
    >
      <Card
        role="button"
        tabIndex={0}
        aria-label={`打开文献 ${item.title}`}
        className="group relative flex h-full cursor-pointer flex-col gap-3 p-4 transition-all hover:border-teal-500/50 hover:shadow-md"
        onClick={() => navigate('literature-detail', { id: item.id })}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            navigate('literature-detail', { id: item.id });
          }
        }}
      >
        {/* 右上角操作: 收藏常显 (移动端), 删除悬停显示 */}
        <div className="absolute right-2 top-2 flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={fav ? '取消收藏' : '加入收藏'}
            disabled={favBusy}
            onClick={toggleFav}
          >
            {favBusy ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            ) : (
              <Star className={cn('h-4 w-4', fav ? 'fill-amber-400 text-amber-400' : 'text-muted-foreground')} />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground opacity-100 transition-all hover:text-red-500 sm:opacity-0 sm:group-hover:opacity-100"
            aria-label="删除文献"
            onClick={(e) => {
              e.stopPropagation();
              setConfirmOpen(true);
            }}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>

        {/* 标题 */}
        <div className="flex items-start gap-2 pr-16">
          <FileText className="mt-0.5 h-5 w-5 shrink-0 text-teal-600 dark:text-teal-400" />
          <h3 className="line-clamp-2 text-sm font-semibold leading-snug">{item.title}</h3>
        </div>

        {/* 作者 / 年份期刊 */}
        <div className="space-y-1 text-xs text-muted-foreground">
          <p className="truncate">
            {item.authors.length > 0
              ? `${item.authors.slice(0, 3).join(', ')}${item.authors.length > 3 ? ' 等' : ''}`
              : '未知作者'}
          </p>
          <p className="truncate">{[item.year, item.journal].filter(Boolean).join(' · ') || '—'}</p>
        </div>

        {/* DOI */}
        {item.doi && (
          <a
            href={`https://doi.org/${item.doi}`}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex w-fit max-w-full items-center gap-1 truncate text-xs text-teal-600 hover:underline dark:text-teal-400"
          >
            <ExternalLink className="h-3 w-3 shrink-0" />
            <span className="truncate">DOI: {item.doi}</span>
          </a>
        )}

        {/* 统计行 */}
        <div className="mt-auto flex flex-wrap items-center gap-1.5 text-[11px]">
          <Badge variant="secondary" className="gap-1">
            <Layers className="h-3 w-3" />
            {item.chunkCount} 分块
          </Badge>
          <Badge variant="secondary">{(item.wordCount / 1000).toFixed(1)}k 词</Badge>
          <Badge variant="secondary" className="gap-1">
            <Link2 className="h-3 w-3" />
            {item.structureCount} 结构
          </Badge>
          {fav && (
            <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300">
              收藏
            </Badge>
          )}
          <span className="ml-auto text-muted-foreground" title={`${formatSize(item.fileSize)} · ${item.parseStatus}`}>
            {formatDate(item.createdAt)}
          </span>
        </div>
      </Card>

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
              className="bg-red-600 text-white hover:bg-red-700"
              onClick={(e) => {
                e.preventDefault();
                void handleDelete();
              }}
            >
              {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : '删除'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </motion.div>
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
    <div className="mx-auto w-full max-w-7xl p-4 md:p-6">
      {/* 页头 */}
      <div className="mb-4 flex items-center gap-2">
        <BookOpen className="h-5 w-5 text-teal-600 dark:text-teal-400" />
        <h2 className="text-lg font-semibold">文献管理</h2>
        {data && (
          <span className="text-sm text-muted-foreground">
            共 {data.total} 篇{favOnly ? ' · 仅收藏' : ''}
          </span>
        )}
      </div>

      {/* 工具栏 */}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索标题 / 作者 / 摘要 / 期刊 / 关键词…"
            className="pl-9 pr-9"
            aria-label="搜索文献"
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
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={sort}
            onValueChange={(v) => {
              setSort(v as SortKey);
              setPage(1);
            }}
          >
            <SelectTrigger className="w-[124px]" aria-label="排序方式">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="recent">最近上传</SelectItem>
              <SelectItem value="year">年份排序</SelectItem>
              <SelectItem value="title">标题排序</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant={favOnly ? 'default' : 'outline'}
            size="sm"
            className={cn('h-9 gap-1.5', favOnly && 'bg-amber-500 text-white hover:bg-amber-600')}
            onClick={() => {
              setFavOnly(!favOnly);
              setPage(1);
            }}
            aria-pressed={favOnly}
          >
            <Star className={cn('h-4 w-4', favOnly && 'fill-current')} />
            收藏
          </Button>
          <Button
            size="sm"
            className="h-9 gap-1.5 bg-teal-600 text-white hover:bg-teal-700"
            onClick={() => setUploadOpen(true)}
          >
            <Upload className="h-4 w-4" />
            上传文献
          </Button>
        </div>
      </div>

      {/* 内容区 */}
      {loading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} className="flex flex-col gap-3 p-4">
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="h-3 w-3/5" />
              <Skeleton className="h-3 w-2/5" />
              <div className="mt-auto flex gap-2">
                <Skeleton className="h-5 w-16" />
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
            <p className="font-medium">文献列表加载失败</p>
            <p className="mt-1 text-sm text-muted-foreground">{error}</p>
          </div>
          <Button variant="outline" size="sm" onClick={() => setReloadKey((k) => k + 1)}>
            重试
          </Button>
        </div>
      ) : data && data.items.length === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed py-16 text-center"
        >
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-teal-500/10">
            <BookOpen className="h-6 w-6 text-teal-600 dark:text-teal-400" />
          </div>
          <div>
            <p className="font-medium">{hasFilter ? '没有找到匹配的文献' : '文献库还是空的'}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {hasFilter ? '试试调整搜索关键词或筛选条件' : '上传 PDF 文献, 自动解析、分块并建立 RAG 检索索引'}
            </p>
          </div>
          {!hasFilter && (
            <Button className="gap-1.5 bg-teal-600 text-white hover:bg-teal-700" onClick={() => setUploadOpen(true)}>
              <Upload className="h-4 w-4" />
              上传第一篇文献
            </Button>
          )}
        </motion.div>
      ) : data ? (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.items.map((item, i) => (
              <LiteratureCard
                key={item.id}
                item={item}
                index={i}
                onDeleted={handleDeleted}
                onFavoriteToggled={handleFavoriteToggled}
              />
            ))}
          </div>

          {/* 分页 */}
          <div className="mt-6 flex flex-col items-center gap-3 sm:flex-row sm:justify-between">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>
                共 {data.total} 篇 · 第 {data.page}/{totalPages} 页
              </span>
              <Select
                value={String(pageSize)}
                onValueChange={(v) => {
                  setPageSize(Number(v));
                  setPage(1);
                }}
              >
                <SelectTrigger size="sm" className="w-[92px]" aria-label="每页数量">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="12">12 / 页</SelectItem>
                  <SelectItem value="24">24 / 页</SelectItem>
                  <SelectItem value="48">48 / 页</SelectItem>
                </SelectContent>
              </Select>
            </div>
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

      {/* 上传对话框 */}
      <Dialog open={uploadOpen} onOpenChange={(open) => !uploading && setUploadOpen(open)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>上传文献</DialogTitle>
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
                  ? 'border-teal-500/60 bg-teal-500/5 hover:border-teal-500'
                  : 'border-muted-foreground/30 hover:border-teal-500/60 hover:bg-teal-500/5'
              )}
            >
              {file ? (
                <FileText className="h-6 w-6 text-teal-600 dark:text-teal-400" />
              ) : (
                <Upload className="h-6 w-6 text-muted-foreground" />
              )}
              {file ? (
                <span className="max-w-full truncate text-sm font-medium">{file.name}</span>
              ) : (
                <span className="text-sm text-muted-foreground">点击选择文件 (PDF / TXT / MD)</span>
              )}
              <span className="text-[11px] text-muted-foreground">{formatSize(file?.size ?? null)}</span>
            </label>

            <div className="space-y-1.5">
              <Label htmlFor="literature-title">自定义标题 (可选)</Label>
              <Input
                id="literature-title"
                value={titleInput}
                onChange={(e) => setTitleInput(e.target.value)}
                placeholder="留空则自动从 PDF 元数据提取"
                disabled={uploading}
              />
            </div>

            {uploading && (
              <div className="flex items-center gap-2.5 rounded-lg bg-teal-500/5 px-3 py-2.5 text-sm">
                <Loader2 className="h-4 w-4 shrink-0 animate-spin text-teal-600" />
                <div className="min-w-0">
                  <p className="truncate font-medium">{UPLOAD_PHASES[phase]}</p>
                  <p className="text-[11px] text-muted-foreground">解析较大 PDF 可能需要十几秒, 请勿关闭对话框</p>
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" disabled={uploading} onClick={() => setUploadOpen(false)}>
              取消
            </Button>
            <Button
              disabled={!file || uploading}
              onClick={() => void handleUpload()}
              className="gap-1.5 bg-teal-600 text-white hover:bg-teal-700"
            >
              {uploading && <Loader2 className="h-4 w-4 animate-spin" />}
              {uploading ? '处理中…' : '上传并解析'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
