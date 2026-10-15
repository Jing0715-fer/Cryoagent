'use client';

/**
 * CryoAgent Pro — 文献详情 · Library Item (BENCH 设计系统)
 * masthead(书目信息) + KPI hairline 条 + 摘要面板 + 分块/结构/笔记/元数据 Panel Tabs
 */

import { useEffect, useMemo, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsContent } from '@/components/ui/tabs';
import { MethodBadge, SegmentedTabs, StatCard } from '@/components/ui/bench-widgets';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import {
  ArrowLeft, Boxes, ChevronDown, ChevronUp, Database, ExternalLink, FileText, Loader2, PencilLine, Plus,
  Search, Star, StickyNote, Trash2,
} from 'lucide-react';

// ============ 类型定义 (API 契约) ============

interface LiteratureMeta {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  journal: string | null;
  doi: string | null;
  abstract: string | null;
  keywords: string | null;
  fileName: string | null;
  fileSize: number | null;
  parseStatus: string;
  chunkCount: number;
  wordCount: number;
  isFavorite: boolean;
  createdAt: string;
  updatedAt: string;
}

interface Chunk {
  id: string;
  chunkIndex: number;
  section: string;
  page: number | null;
  content: string;
  wordCount: number;
}

interface LinkedStructure {
  id: string;
  title: string;
  method: string | null;
  resolution: number | null;
  mentionCount: number;
}

interface NoteItem {
  id: string;
  literatureId: string | null;
  content: string;
  anchor: string | null;
  createdAt: string;
}

interface LiteratureDetailResponse {
  literature: LiteratureMeta;
  chunks: Chunk[];
  structures: LinkedStructure[];
  notes: NoteItem[];
  sectionStats: { section: string; count: number }[];
}

// ============ 工具函数 ============

function formatDate(iso: string): string {
  try {
    return new Date(iso).toISOString().slice(0, 10);
  } catch {
    return iso;
  }
}

function formatSize(bytes: number | null): string {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// ============ 元数据编辑表单 (对话框与元数据 Tab 共用) ============

interface MetadataFormState {
  title: string;
  journal: string;
  year: string;
  keywords: string;
  authors: string;
  abstract: string;
}

function toFormState(lit: LiteratureMeta): MetadataFormState {
  return {
    title: lit.title ?? '',
    journal: lit.journal ?? '',
    year: lit.year != null ? String(lit.year) : '',
    keywords: lit.keywords ?? '',
    authors: Array.isArray(lit.authors) ? lit.authors.join(', ') : '',
    abstract: lit.abstract ?? '',
  };
}

function MetadataForm({
  state,
  onChange,
  disabled,
}: {
  state: MetadataFormState;
  onChange: (patch: Partial<MetadataFormState>) => void;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <label htmlFor="meta-title" className="label-tech block !text-[10px]">标题</label>
        <Input
          id="meta-title"
          className="h-9"
          value={state.title}
          onChange={(e) => onChange({ title: e.target.value })}
          disabled={disabled}
        />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor="meta-journal" className="label-tech block !text-[10px]">期刊</label>
          <Input
            id="meta-journal"
            className="h-9"
            value={state.journal}
            onChange={(e) => onChange({ journal: e.target.value })}
            placeholder="如 Nature"
            disabled={disabled}
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="meta-year" className="label-tech block !text-[10px]">年份</label>
          <Input
            id="meta-year"
            className="h-9"
            type="number"
            value={state.year}
            onChange={(e) => onChange({ year: e.target.value })}
            placeholder="如 2020"
            disabled={disabled}
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <label htmlFor="meta-authors" className="label-tech block !text-[10px]">作者 (逗号分隔)</label>
        <Input
          id="meta-authors"
          className="h-9"
          value={state.authors}
          onChange={(e) => onChange({ authors: e.target.value })}
          placeholder="Zhang Y, Wang X, …"
          disabled={disabled}
        />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="meta-keywords" className="label-tech block !text-[10px]">关键词 (逗号分隔)</label>
        <Input
          id="meta-keywords"
          className="h-9"
          value={state.keywords}
          onChange={(e) => onChange({ keywords: e.target.value })}
          placeholder="cryo-EM, spike, ACE2"
          disabled={disabled}
        />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="meta-abstract" className="label-tech block !text-[10px]">摘要</label>
        <Textarea
          id="meta-abstract"
          className="min-h-28"
          value={state.abstract}
          onChange={(e) => onChange({ abstract: e.target.value })}
          disabled={disabled}
        />
      </div>
    </div>
  );
}

// ============ 分块检索 Tab ============

function ChunksTab({ chunks, sectionStats }: { chunks: Chunk[]; sectionStats: { section: string; count: number }[] }) {
  const [filter, setFilter] = useState('');
  const [section, setSection] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return chunks.filter((c) => {
      if (section && c.section !== section) return false;
      if (f && !c.content.toLowerCase().includes(f) && !c.section.toLowerCase().includes(f)) return false;
      return true;
    });
  }, [chunks, filter, section]);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const totalChunks = sectionStats.reduce((a, s) => a + s.count, 0);

  return (
    <div className="space-y-3">
      {/* 搜索 + 分区统计 tag */}
      <div className="flex flex-col gap-2.5">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" strokeWidth={1.75} />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="在分块内容中检索…"
            className="h-11 pl-9 md:h-9"
            aria-label="在分块中搜索"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setSection(null)}
            aria-pressed={section === null}
            className={cn(
              'min-h-9 rounded-[3px] border px-2 py-1 font-mono text-[10px] transition-colors',
              section === null
                ? 'border-primary/60 bg-primary/10 font-medium text-primary'
                : 'text-muted-foreground hover:border-foreground/25 hover:text-foreground'
            )}
          >
            全部 <span className="ml-0.5 opacity-70">{totalChunks}</span>
          </button>
          {sectionStats.map((s) => (
            <button
              key={s.section}
              type="button"
              onClick={() => setSection(section === s.section ? null : s.section)}
              aria-pressed={section === s.section}
              className={cn(
                'min-h-9 rounded-[3px] border px-2 py-1 font-mono text-[10px] transition-colors',
                section === s.section
                  ? 'border-primary/60 bg-primary/10 font-medium text-primary'
                  : 'text-muted-foreground hover:border-foreground/25 hover:text-foreground'
              )}
            >
              {s.section} <span className="ml-0.5 opacity-70">{s.count}</span>
            </button>
          ))}
        </div>
      </div>

      {/* 分块密集列表 */}
      {filtered.length === 0 ? (
        <div className="label-tech flex min-h-[88px] items-center justify-center rounded-lg border border-dashed !text-[10px] normal-case !tracking-[0.06em]">
          NO MATCH — 没有匹配的分块
        </div>
      ) : (
        <section className="overflow-hidden rounded-lg border bg-card">
          <div className="flex items-center gap-3 border-b px-4 py-2.5">
            <span className="label-tech !text-[10px] text-foreground/75">Chunks · 检索分块</span>
            <span className="label-tech ml-auto !text-[9px]">
              {filtered.length}/{chunks.length}
            </span>
          </div>
          <div className="max-h-[70vh] divide-y overflow-y-auto custom-scrollbar">
            {filtered.map((c) => {
              const isExpanded = expanded.has(c.id);
              return (
                <div key={c.id} className="px-4 py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="shrink-0 rounded-[3px] border border-border px-1.5 py-px font-mono text-[9px] font-medium tracking-wide text-muted-foreground">
                      {c.section}
                    </span>
                    <span className="num text-[10px] text-muted-foreground">#{c.chunkIndex}</span>
                    {c.page != null && <span className="num text-[10px] text-muted-foreground">P.{c.page}</span>}
                    <span className="num ml-auto text-[10px] text-muted-foreground">{c.wordCount} W</span>
                  </div>
                  <p
                    className={cn(
                      'mt-1.5 text-[12px] leading-relaxed text-foreground/90',
                      isExpanded
                        ? 'max-h-72 overflow-y-auto whitespace-pre-wrap pr-1 custom-scrollbar'
                        : 'line-clamp-4'
                    )}
                  >
                    {c.content}
                  </p>
                  <button
                    type="button"
                    onClick={() => toggle(c.id)}
                    className="label-tech mt-1 flex h-8 items-center gap-1 rounded-[4px] px-1.5 !text-[9px] text-primary transition-opacity hover:opacity-70"
                    aria-expanded={isExpanded}
                  >
                    {isExpanded ? '收起' : '展开全文'}
                    {isExpanded ? (
                      <ChevronUp className="h-3 w-3" strokeWidth={1.75} />
                    ) : (
                      <ChevronDown className="h-3 w-3" strokeWidth={1.75} />
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

// ============ 阅读笔记 Tab ============

function NotesTab({ literatureId, initialNotes }: { literatureId: string; initialNotes: NoteItem[] }) {
  const [notes, setNotes] = useState<NoteItem[]>(initialNotes);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    setNotes(initialNotes);
  }, [initialNotes]);

  const addNote = async () => {
    const content = draft.trim();
    if (!content) return;
    setBusy(true);
    try {
      const d = await api<{ success: boolean; note: NoteItem }>('/api/notes', {
        method: 'POST',
        body: JSON.stringify({ literatureId, content }),
      });
      setNotes((n) => [d.note, ...n]);
      setDraft('');
      toast.success('笔记已添加');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '添加失败');
    } finally {
      setBusy(false);
    }
  };

  const deleteNote = async (id: string) => {
    setDeletingId(id);
    try {
      await api<{ success: boolean }>(`/api/notes?id=${encodeURIComponent(id)}`, { method: 'DELETE' });
      setNotes((n) => n.filter((x) => x.id !== id));
      toast.success('笔记已删除');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-3">
      {/* 新笔记输入 */}
      <div className="space-y-2">
        <label htmlFor="note-draft" className="label-tech block !text-[10px]">New Note · 新笔记</label>
        <Textarea
          id="note-draft"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="记录阅读心得、实验想法或关键结论…"
          className="min-h-24"
          aria-label="新笔记内容"
        />
        <Button
          size="sm"
          disabled={!draft.trim() || busy}
          onClick={() => void addNote()}
          className="h-11 gap-1.5 md:h-9"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} /> : <Plus className="h-4 w-4" strokeWidth={1.75} />}
          添加笔记
        </Button>
      </div>

      {/* 笔记列表 */}
      {notes.length === 0 ? (
        <div className="label-tech flex min-h-[88px] items-center justify-center rounded-lg border border-dashed !text-[10px] normal-case !tracking-[0.06em]">
          NO NOTES — 在上方记录第一条阅读笔记
        </div>
      ) : (
        <section className="overflow-hidden rounded-lg border bg-card">
          <div className="flex items-center gap-3 border-b px-4 py-2.5">
            <span className="label-tech !text-[10px] text-foreground/75">Notes · 阅读笔记</span>
            <span className="label-tech ml-auto !text-[9px]">{notes.length} ENTRIES</span>
          </div>
          <div className="max-h-[60vh] divide-y overflow-y-auto custom-scrollbar">
            {notes.map((n) => (
              <div key={n.id} className="px-4 py-2.5">
                <div className="flex items-center gap-2">
                  <span className="num text-[10px] text-muted-foreground">{formatDate(n.createdAt)}</span>
                  {n.anchor && (
                    <span className="shrink-0 rounded-[3px] border border-border px-1.5 py-px font-mono text-[9px] tracking-wide text-muted-foreground">
                      {n.anchor}
                    </span>
                  )}
                  <button
                    type="button"
                    className="ml-auto flex h-11 w-11 items-center justify-center rounded-[4px] text-muted-foreground transition-colors hover:bg-accent/60 hover:text-destructive md:h-8 md:w-8"
                    aria-label="删除笔记"
                    disabled={deletingId === n.id}
                    onClick={() => void deleteNote(n.id)}
                  >
                    {deletingId === n.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
                    )}
                  </button>
                </div>
                <p className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed">{n.content}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

// ============ 主视图 ============

export function LiteratureDetailView() {
  const viewParams = useAppStore((s) => s.viewParams);
  const navigate = useAppStore((s) => s.navigate);
  const id = viewParams.id;

  const [detail, setDetail] = useState<LiteratureDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [favBusy, setFavBusy] = useState(false);
  const [tab, setTab] = useState('chunks');

  // 编辑对话框
  const [editOpen, setEditOpen] = useState(false);
  const [savingMeta, setSavingMeta] = useState(false);
  const [form, setForm] = useState<MetadataFormState | null>(null);

  // 拉取详情
  useEffect(() => {
    if (!id) {
      setLoading(false);
      setError('缺少文献 ID, 请从文献列表进入');
      return;
    }
    let cancelled = false;
    const ctrl = new AbortController();
    setLoading(true);
    api<LiteratureDetailResponse>(`/api/literature/${encodeURIComponent(id)}`, { signal: ctrl.signal })
      .then((d) => {
        if (!cancelled) {
          setDetail(d);
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
  }, [id, reloadKey]);

  // 表单与详情同步
  useEffect(() => {
    if (detail) setForm(toFormState(detail.literature));
  }, [detail]);

  // 滚动到顶部
  useEffect(() => {
    const main = document.querySelector('main');
    if (main) main.scrollTo({ top: 0 });
  }, [id]);

  const toggleFav = async () => {
    if (!detail || favBusy) return;
    const next = !detail.literature.isFavorite;
    setFavBusy(true);
    // 乐观更新
    setDetail((d) =>
      d ? { ...d, literature: { ...d.literature, isFavorite: next } } : d
    );
    try {
      await api<{ success: boolean }>(`/api/literature/${detail.literature.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ isFavorite: next }),
      });
      toast.success(next ? '已加入收藏' : '已取消收藏');
    } catch (err) {
      setDetail((d) =>
        d ? { ...d, literature: { ...d.literature, isFavorite: !next } } : d
      );
      toast.error(err instanceof Error ? err.message : '操作失败');
    } finally {
      setFavBusy(false);
    }
  };

  const saveMeta = async (after?: () => void) => {
    if (!detail || !form || savingMeta) return;
    setSavingMeta(true);
    try {
      const yearNum = form.year.trim() ? Number(form.year) : undefined;
      if (form.year.trim() && Number.isNaN(yearNum)) throw new Error('年份格式不正确');
      await api<{ success: boolean }>(`/api/literature/${detail.literature.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title: form.title.trim(),
          journal: form.journal.trim(),
          year: yearNum,
          keywords: form.keywords.trim(),
          authors: form.authors.split(/[,，;；]/).map((a) => a.trim()).filter(Boolean),
          abstract: form.abstract,
        }),
      });
      toast.success('元数据已更新');
      setReloadKey((k) => k + 1);
      after?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSavingMeta(false);
    }
  };

  // ===== 加载 / 错误态 =====
  if (!id) {
    return (
      <div className="p-4 md:p-6">
        <EmptyState
          title="缺少文献 ID"
          description="请从文献列表选择一篇文献进入详情"
          onBack={() => navigate('literature')}
        />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-4 p-4 md:p-6">
        <div className="space-y-2.5 px-1">
          <Skeleton className="shimmer h-3 w-36" />
          <Skeleton className="shimmer h-7 w-3/4" />
          <Skeleton className="shimmer h-3.5 w-1/2" />
        </div>
        <div className="grid grid-cols-2 gap-2.5 sm:gap-3 md:grid-cols-4 [grid-auto-rows:1fr]">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-lg border bg-card p-3">
              <Skeleton className="shimmer h-2.5 w-12" />
              <Skeleton className="shimmer mt-2 h-5 w-14" />
            </div>
          ))}
        </div>
        <Skeleton className="shimmer h-64 w-full rounded-lg" />
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="p-4 md:p-6">
        <EmptyState
          title="文献加载失败"
          description={error || '未找到该文献'}
          onBack={() => navigate('literature')}
          onRetry={() => setReloadKey((k) => k + 1)}
        />
      </div>
    );
  }

  const lit = detail.literature;
  const isFav = lit.isFavorite;

  return (
    <div className="animate-fade-in-up">
      {/* ===== Masthead — 书目信息 ===== */}
      <div className="grid-bg border-b">
        <div className="px-4 py-4 md:px-6 md:py-5">
          <div className="flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => navigate('literature')}
              className="label-tech flex h-11 items-center gap-1.5 rounded-[4px] px-1 !text-[10px] text-muted-foreground transition-colors hover:text-foreground md:h-8"
            >
              <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.75} />
              返回列表
            </button>
            <span className="label-tech !text-[10px]">Library / Item · 文献详情</span>
          </div>
          <h1 className="mt-2.5 max-w-4xl text-[22px] font-semibold leading-snug tracking-tight md:text-[26px] md:line-clamp-2">
            {lit.title}
          </h1>
          <p className="mt-1.5 max-w-3xl truncate text-xs text-muted-foreground">
            {lit.authors.length > 0 ? lit.authors.join(', ') : '未知作者'}
          </p>
          <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            {lit.year != null && <span className="num">{lit.year}</span>}
            {lit.journal && <span className="truncate">{lit.journal}</span>}
            {lit.doi && (
              <a
                href={`https://doi.org/${lit.doi}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-0.5 font-mono text-[10px] text-primary hover:underline"
              >
                <ExternalLink className="h-2.5 w-2.5 shrink-0" strokeWidth={1.75} />
                DOI: {lit.doi}
              </a>
            )}
            <span className="num">入库 {formatDate(lit.createdAt)}</span>
            <span className="num ml-auto hidden shrink-0 text-muted-foreground/60 sm:inline">
              {formatSize(lit.fileSize)} · {lit.parseStatus.toUpperCase()}
            </span>
          </div>
          {lit.keywords && (
            <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
              {lit.keywords.split(/[,，;；]/).map((k) => k.trim()).filter(Boolean).map((k) => (
                <span
                  key={k}
                  className="rounded-[3px] border border-border px-1.5 py-px font-mono text-[9px] tracking-wide text-muted-foreground"
                >
                  {k}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="mx-auto w-full max-w-5xl space-y-4 p-4 md:p-6">
        {/* ===== 操作行 ===== */}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void toggleFav()}
            disabled={favBusy}
            className={cn('h-11 gap-1.5 md:h-9', isFav && 'border-chart-2/60 text-chart-2 hover:bg-chart-2/10 hover:text-chart-2')}
          >
            {favBusy ? (
              <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} />
            ) : (
              <Star className={cn('h-4 w-4', isFav && 'fill-chart-2 text-chart-2')} strokeWidth={1.75} />
            )}
            {isFav ? '已收藏' : '收藏'}
          </Button>
          <Button variant="outline" size="sm" onClick={() => setEditOpen(true)} className="h-11 gap-1.5 md:h-9">
            <PencilLine className="h-4 w-4" strokeWidth={1.75} />
            编辑元数据
          </Button>
          <span className="label-tech ml-auto hidden !text-[9px] sm:inline">
            FILE {lit.fileName ?? '—'} · CHUNK {lit.chunkCount}
          </span>
        </div>

        {/* ===== KPI StatCard 网格 — 领域色渐变图标 + 计数动画 ===== */}
        <div className="grid grid-cols-2 gap-2.5 sm:gap-3 md:grid-cols-4 [grid-auto-rows:1fr]">
          <StatCard
            title="分块"
            value={lit.chunkCount}
            subtitle="RAG INDEX"
            icon={<Database className="h-3.5 w-3.5" />}
            gradient="from-[#c9872e] to-[#a06b1a]"
            accent="#c9872e"
            delay={0}
            tooltip={`检索分块 ${lit.chunkCount} 个`}
          />
          <StatCard
            title="总词数"
            value={lit.wordCount}
            subtitle="PARSED"
            icon={<FileText className="h-3.5 w-3.5" />}
            gradient="from-[#6b7280] to-[#4b5563]"
            accent="#6b7280"
            delay={45}
            tooltip={`解析总词数 ${lit.wordCount.toLocaleString()}`}
          />
          <StatCard
            title="关联结构"
            value={detail.structures.length}
            subtitle="PDB LINK"
            icon={<Boxes className="h-3.5 w-3.5" />}
            gradient="from-[#2d8f8f] to-[#1a6b6b]"
            accent="#2d8f8f"
            delay={90}
            tooltip={`文中提及并自动关联的结构 ${detail.structures.length} 个`}
          />
          <StatCard
            title="阅读笔记"
            value={detail.notes.length}
            subtitle="ANNOTATION"
            icon={<StickyNote className="h-3.5 w-3.5" />}
            gradient="from-[#c96442] to-[#a04e32]"
            accent="#c96442"
            delay={135}
            tooltip={`阅读笔记 ${detail.notes.length} 条`}
          />
        </div>

        {/* ===== 摘要面板 ===== */}
        {lit.abstract && (
          <section className="overflow-hidden rounded-lg border bg-card">
            <div className="flex items-center gap-3 border-b px-4 py-2.5">
              <span className="label-tech !text-[10px] text-foreground/75">Abstract · 摘要</span>
              <span className="label-tech ml-auto !text-[9px]">AUTO EXTRACTED</span>
            </div>
            <div className="px-4 py-3">
              <p className="text-[13px] leading-[1.8] text-foreground/90">{lit.abstract}</p>
            </div>
          </section>
        )}

        {/* ===== 主体 Tabs — 滑动药丸分段控制 ===== */}
        <Tabs value={tab} onValueChange={setTab} className="gap-3">
          <SegmentedTabs
            className="w-full sm:w-auto [&>button]:flex-1 [&>button]:min-w-0 sm:[&>button]:flex-none"
            value={tab}
            onChange={setTab}
            options={[
              { value: 'chunks', label: '分块检索' },
              { value: 'structures', label: '关联结构' },
              { value: 'notes', label: '阅读笔记' },
              { value: 'metadata', label: '元数据' },
            ]}
          />

          {/* 分块检索 */}
          <TabsContent value="chunks">
            <ChunksTab chunks={detail.chunks} sectionStats={detail.sectionStats} />
          </TabsContent>

          {/* 关联结构 */}
          <TabsContent value="structures">
            {detail.structures.length === 0 ? (
              <div className="label-tech flex min-h-[88px] items-center justify-center rounded-lg border border-dashed !text-[10px] normal-case !tracking-[0.06em]">
                NO LINKS — 上传文献时检测到的 PDB ID 将自动建立结构关联
              </div>
            ) : (
              <section className="overflow-hidden rounded-lg border bg-card">
                <div className="flex items-center gap-3 border-b px-4 py-2.5">
                  <span className="label-tech !text-[10px] text-foreground/75">Linked Structures · 关联结构</span>
                  <span className="label-tech ml-auto !text-[9px]">{detail.structures.length} ENTRIES</span>
                </div>
                <div className="divide-y">
                  {detail.structures.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      role="button"
                      tabIndex={0}
                      className="flex min-h-11 w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-accent/50"
                      onClick={() => navigate('structure-detail', { id: s.id })}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          navigate('structure-detail', { id: s.id });
                        }
                      }}
                      aria-label={`查看结构 ${s.id}`}
                    >
                      <span className="num shrink-0 text-[13px] font-semibold tracking-tight">{s.id}</span>
                      <MethodBadge method={s.method} />
                      <span className="hidden min-w-0 flex-1 truncate text-xs text-muted-foreground md:block">{s.title}</span>
                      {s.resolution != null && (
                        <span className="num ml-auto shrink-0 text-[10px] text-muted-foreground">{s.resolution} Å</span>
                      )}
                      <span className="num shrink-0 text-[10px] text-muted-foreground" title="文中提及次数">
                        ×{s.mentionCount}
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            )}
          </TabsContent>

          {/* 阅读笔记 */}
          <TabsContent value="notes">
            <NotesTab literatureId={lit.id} initialNotes={detail.notes} />
          </TabsContent>

          {/* 元数据编辑 */}
          <TabsContent value="metadata">
            {form && (
              <section className="overflow-hidden rounded-lg border bg-card">
                <div className="flex items-center gap-3 border-b px-4 py-2.5">
                  <span className="label-tech !text-[10px] text-foreground/75">Metadata · 元数据编辑</span>
                  <span className="label-tech ml-auto !text-[9px]">PATCH /api/literature/:id</span>
                </div>
                <div className="p-4">
                  <MetadataForm
                    state={form}
                    onChange={(patch) => setForm((f) => (f ? { ...f, ...patch } : f))}
                    disabled={savingMeta}
                  />
                  <div className="mt-4 flex items-center justify-end gap-2">
                    <Button variant="outline" size="sm" disabled={savingMeta} onClick={() => setForm(toFormState(lit))} className="h-9">
                      重置
                    </Button>
                    <Button
                      size="sm"
                      disabled={savingMeta}
                      onClick={() => void saveMeta()}
                      className="h-9 gap-1.5"
                    >
                      {savingMeta && <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} />}
                      保存修改
                    </Button>
                  </div>
                </div>
              </section>
            )}
          </TabsContent>
        </Tabs>
      </div>

      {/* 编辑信息对话框 */}
      <Dialog open={editOpen} onOpenChange={(open) => !savingMeta && setEditOpen(open)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto custom-scrollbar sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-baseline gap-2">
              编辑文献信息
              <span className="label-tech !text-[9px]">METADATA</span>
            </DialogTitle>
            <DialogDescription>修改后将立即保存到数据库</DialogDescription>
          </DialogHeader>
          {form && <MetadataForm state={form} onChange={(patch) => setForm((f) => (f ? { ...f, ...patch } : f))} disabled={savingMeta} />}
          <DialogFooter>
            <Button variant="outline" disabled={savingMeta} onClick={() => setEditOpen(false)} className="h-9">
              取消
            </Button>
            <Button
              disabled={savingMeta}
              onClick={() => void saveMeta(() => setEditOpen(false))}
              className="h-9 gap-1.5"
            >
              {savingMeta && <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} />}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ============ 空态 / 错误态 ============

function EmptyState({
  title,
  description,
  onBack,
  onRetry,
}: {
  title: string;
  description: string;
  onBack: () => void;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
      <div className="label-tech !text-[10px] !text-destructive">{title}</div>
      <p className="mt-1 text-sm text-destructive/90">{description}</p>
      <div className="mt-3 flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={onBack} className="h-11 gap-1.5 md:h-9">
          <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.75} />
          返回文献列表
        </Button>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry} className="h-11 md:h-9">
            重试
          </Button>
        )}
      </div>
    </div>
  );
}
