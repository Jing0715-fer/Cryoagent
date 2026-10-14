'use client';

/**
 * CryoAgent Pro — 文献详情页
 * 头部元数据卡 / 统计行 / 分块检索 / 关联结构 / 阅读笔记 / 元数据编辑
 */

import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import {
  ArrowLeft, BookOpen, Boxes, ChevronDown, ChevronUp, ExternalLink, FileText, Layers, Link2,
  Loader2, PencilLine, Plus, Search, Star, StickyNote, Trash2, TriangleAlert,
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

const SECTION_COLORS: Record<string, string> = {
  abstract: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  introduction: 'border-teal-500/30 bg-teal-500/10 text-teal-700 dark:text-teal-300',
  methods: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  results: 'border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300',
  discussion: 'border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300',
  conclusion: 'border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-700 dark:text-fuchsia-300',
  references: 'border-stone-500/30 bg-stone-500/10 text-stone-700 dark:text-stone-300',
};

function sectionColor(section: string): string {
  const s = section.toLowerCase();
  for (const key of Object.keys(SECTION_COLORS)) {
    if (s.includes(key)) return SECTION_COLORS[key];
  }
  return 'border-border bg-muted text-muted-foreground';
}

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
    <Badge variant="outline" className={cn('text-[11px]', cls)}>
      {label}
    </Badge>
  );
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toISOString().slice(0, 10);
  } catch {
    return iso;
  }
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
        <Label htmlFor="meta-title">标题</Label>
        <Input
          id="meta-title"
          value={state.title}
          onChange={(e) => onChange({ title: e.target.value })}
          disabled={disabled}
        />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="meta-journal">期刊</Label>
          <Input
            id="meta-journal"
            value={state.journal}
            onChange={(e) => onChange({ journal: e.target.value })}
            placeholder="如 Nature"
            disabled={disabled}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="meta-year">年份</Label>
          <Input
            id="meta-year"
            type="number"
            value={state.year}
            onChange={(e) => onChange({ year: e.target.value })}
            placeholder="如 2020"
            disabled={disabled}
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="meta-authors">作者 (逗号分隔)</Label>
        <Input
          id="meta-authors"
          value={state.authors}
          onChange={(e) => onChange({ authors: e.target.value })}
          placeholder="Zhang Y, Wang X, …"
          disabled={disabled}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="meta-keywords">关键词 (逗号分隔)</Label>
        <Input
          id="meta-keywords"
          value={state.keywords}
          onChange={(e) => onChange({ keywords: e.target.value })}
          placeholder="cryo-EM, spike, ACE2"
          disabled={disabled}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="meta-abstract">摘要</Label>
        <Textarea
          id="meta-abstract"
          className="min-h-32"
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
      {/* 搜索 + 分区统计 chips */}
      <div className="flex flex-col gap-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="在分块内容中搜索…"
            className="pl-9"
            aria-label="在分块中搜索"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setSection(null)}
            className={cn(
              'rounded-full border px-2.5 py-1 text-xs transition-colors',
              section === null
                ? 'border-teal-500/50 bg-teal-500/10 font-medium text-teal-700 dark:text-teal-300'
                : 'border-border text-muted-foreground hover:border-teal-500/30 hover:text-foreground'
            )}
          >
            全部 <span className="ml-0.5 opacity-70">{totalChunks}</span>
          </button>
          {sectionStats.map((s) => (
            <button
              key={s.section}
              type="button"
              onClick={() => setSection(section === s.section ? null : s.section)}
              className={cn(
                'rounded-full border px-2.5 py-1 text-xs transition-colors',
                section === s.section
                  ? 'border-teal-500/50 bg-teal-500/10 font-medium text-teal-700 dark:text-teal-300'
                  : 'border-border text-muted-foreground hover:border-teal-500/30 hover:text-foreground'
              )}
            >
              {s.section} <span className="ml-0.5 opacity-70">{s.count}</span>
            </button>
          ))}
        </div>
      </div>

      {/* 分块列表 */}
      {filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed py-12 text-center text-sm text-muted-foreground">
          没有匹配的分块
        </div>
      ) : (
        <div className="max-h-[70vh] space-y-3 overflow-y-auto pr-1 custom-scrollbar">
          {filtered.map((c) => {
            const isExpanded = expanded.has(c.id);
            return (
              <Card key={c.id} className="gap-3 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className={cn('font-medium', sectionColor(c.section))}>
                    {c.section}
                  </Badge>
                  <span className="text-xs text-muted-foreground">#{c.chunkIndex}</span>
                  {c.page != null && <span className="text-xs text-muted-foreground">第 {c.page} 页</span>}
                  <span className="ml-auto text-xs text-muted-foreground">{c.wordCount} 词</span>
                </div>
                <p
                  className={cn(
                    'text-sm leading-relaxed text-foreground/90',
                    isExpanded
                      ? 'max-h-72 overflow-y-auto whitespace-pre-wrap pr-1 custom-scrollbar'
                      : 'line-clamp-4'
                  )}
                >
                  {c.content}
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-fit gap-1 px-2 text-xs text-teal-600 dark:text-teal-400"
                  onClick={() => toggle(c.id)}
                >
                  {isExpanded ? '收起' : '展开全文'}
                  {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                </Button>
              </Card>
            );
          })}
        </div>
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
    <div className="space-y-4">
      {/* 新笔记输入 */}
      <div className="space-y-2">
        <Textarea
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
          className="gap-1.5 bg-teal-600 text-white hover:bg-teal-700"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          添加笔记
        </Button>
      </div>

      {/* 笔记列表 */}
      {notes.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <StickyNote className="h-6 w-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">还没有笔记, 在上方记录第一条阅读笔记吧</p>
        </div>
      ) : (
        <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1 custom-scrollbar">
          {notes.map((n) => (
            <Card key={n.id} className="gap-2.5 p-4">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <StickyNote className="h-3.5 w-3.5 text-teal-600 dark:text-teal-400" />
                {formatDate(n.createdAt)}
                {n.anchor && <Badge variant="secondary" className="text-[10px]">{n.anchor}</Badge>}
                <Button
                  variant="ghost"
                  size="icon"
                  className="ml-auto h-6 w-6 text-muted-foreground hover:text-red-500"
                  aria-label="删除笔记"
                  disabled={deletingId === n.id}
                  onClick={() => void deleteNote(n.id)}
                >
                  {deletingId === n.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5" />
                  )}
                </Button>
              </div>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{n.content}</p>
            </Card>
          ))}
        </div>
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
      <div className="mx-auto w-full max-w-3xl p-4 md:p-6">
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
      <div className="mx-auto w-full max-w-5xl space-y-4 p-4 md:p-6">
        <Skeleton className="h-8 w-32" />
        <Card className="gap-4 p-6">
          <Skeleton className="h-6 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-2/5" />
          <Skeleton className="h-20 w-full" />
        </Card>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="gap-2 p-4">
              <Skeleton className="h-3 w-12" />
              <Skeleton className="h-6 w-16" />
            </Card>
          ))}
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="mx-auto w-full max-w-3xl p-4 md:p-6">
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

  const stats = [
    { label: '分块', value: lit.chunkCount, icon: Layers },
    { label: '总词数', value: lit.wordCount.toLocaleString(), icon: FileText },
    { label: '关联结构', value: detail.structures.length, icon: Boxes },
    { label: '阅读笔记', value: detail.notes.length, icon: StickyNote },
  ];

  return (
    <div className="mx-auto w-full max-w-5xl p-4 md:p-6">
      {/* 返回 */}
      <div className="mb-4 flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => navigate('literature')} className="gap-1.5">
          <ArrowLeft className="h-4 w-4" />
          返回列表
        </Button>
      </div>

      {/* 头部信息卡 */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
        <Card className="gap-4 p-6">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="min-w-0 space-y-2">
              <h2 className="text-xl font-bold leading-tight">{lit.title}</h2>
              <p className="text-sm text-muted-foreground">
                {lit.authors.length > 0 ? lit.authors.join(', ') : '未知作者'}
              </p>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                {lit.year != null && <span>{lit.year}</span>}
                {lit.journal && <span>· {lit.journal}</span>}
                {lit.doi && (
                  <a
                    href={`https://doi.org/${lit.doi}`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-teal-600 hover:underline dark:text-teal-400"
                  >
                    <ExternalLink className="h-3 w-3" />
                    DOI: {lit.doi}
                  </a>
                )}
                <span>· 上传于 {formatDate(lit.createdAt)}</span>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <Button variant="outline" size="sm" onClick={() => void toggleFav()} disabled={favBusy} className="gap-1.5">
                {favBusy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Star className={cn('h-4 w-4', isFav && 'fill-amber-400 text-amber-400')} />
                )}
                {isFav ? '已收藏' : '收藏'}
              </Button>
              <Button variant="outline" size="sm" onClick={() => setEditOpen(true)} className="gap-1.5">
                <PencilLine className="h-4 w-4" />
                编辑信息
              </Button>
            </div>
          </div>

          {lit.keywords && (
            <div className="flex flex-wrap items-center gap-1.5">
              {lit.keywords.split(/[,，;；]/).map((k) => k.trim()).filter(Boolean).map((k) => (
                <Badge key={k} variant="secondary" className="text-[11px]">{k}</Badge>
              ))}
            </div>
          )}

          {lit.abstract && (
            <div className="rounded-lg bg-muted/50 p-4">
              <span className="mb-1.5 block text-xs font-semibold text-muted-foreground">摘要</span>
              <p className="text-sm leading-relaxed text-foreground/90">{lit.abstract}</p>
            </div>
          )}
        </Card>
      </motion.div>

      {/* 统计行 */}
      <div className="my-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label} className="flex-row items-center justify-between gap-2 p-4">
            <div className="flex items-center gap-2">
              <s.icon className="h-4 w-4 text-teal-600 dark:text-teal-400" />
              <span className="text-xs text-muted-foreground">{s.label}</span>
            </div>
            <span className="text-lg font-bold text-teal-700 dark:text-teal-300">{s.value}</span>
          </Card>
        ))}
      </div>

      {/* 主体 Tabs */}
      <Tabs defaultValue="chunks" className="gap-4">
        <TabsList className="grid h-auto w-full grid-cols-2 sm:inline-flex sm:w-auto">
          <TabsTrigger value="chunks" className="px-3 py-1.5 text-xs sm:text-sm">分块检索</TabsTrigger>
          <TabsTrigger value="structures" className="px-3 py-1.5 text-xs sm:text-sm">关联结构</TabsTrigger>
          <TabsTrigger value="notes" className="px-3 py-1.5 text-xs sm:text-sm">阅读笔记</TabsTrigger>
          <TabsTrigger value="metadata" className="px-3 py-1.5 text-xs sm:text-sm">元数据</TabsTrigger>
        </TabsList>

        {/* 分块检索 */}
        <TabsContent value="chunks">
          <ChunksTab chunks={detail.chunks} sectionStats={detail.sectionStats} />
        </TabsContent>

        {/* 关联结构 */}
        <TabsContent value="structures">
          {detail.structures.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed py-12 text-center">
              <Boxes className="h-6 w-6 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                暂无关联结构 — 上传文献时检测到的 PDB ID 会自动建立关联
              </p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {detail.structures.map((s) => (
                <Card
                  key={s.id}
                  role="button"
                  tabIndex={0}
                  className="cursor-pointer gap-3 p-4 transition-all hover:border-teal-500/50 hover:shadow-md"
                  onClick={() => navigate('structure-detail', { id: s.id })}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      navigate('structure-detail', { id: s.id });
                    }
                  }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-base font-bold text-teal-700 dark:text-teal-300">{s.id}</span>
                    <MethodBadge method={s.method} />
                  </div>
                  <p className="line-clamp-2 text-sm leading-snug">{s.title}</p>
                  <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    {s.resolution != null && <Badge variant="secondary">{s.resolution} Å</Badge>}
                    <Badge variant="secondary" className="gap-1">
                      <Link2 className="h-3 w-3" />
                      提及 {s.mentionCount} 次
                    </Badge>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        {/* 阅读笔记 */}
        <TabsContent value="notes">
          <NotesTab literatureId={lit.id} initialNotes={detail.notes} />
        </TabsContent>

        {/* 元数据编辑 */}
        <TabsContent value="metadata">
          {form && (
            <Card className="gap-4 p-6">
              <div className="flex items-center gap-2">
                <PencilLine className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                <h3 className="text-sm font-semibold">编辑文献元数据</h3>
              </div>
              <MetadataForm
                state={form}
                onChange={(patch) => setForm((f) => (f ? { ...f, ...patch } : f))}
                disabled={savingMeta}
              />
              <div className="flex items-center justify-end gap-2">
                <Button variant="outline" size="sm" disabled={savingMeta} onClick={() => setForm(toFormState(lit))}>
                  重置
                </Button>
                <Button
                  size="sm"
                  className="gap-1.5 bg-teal-600 text-white hover:bg-teal-700"
                  disabled={savingMeta}
                  onClick={() => void saveMeta()}
                >
                  {savingMeta && <Loader2 className="h-4 w-4 animate-spin" />}
                  保存修改
                </Button>
              </div>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      {/* 编辑信息对话框 */}
      <Dialog open={editOpen} onOpenChange={(open) => !savingMeta && setEditOpen(open)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto custom-scrollbar sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>编辑文献信息</DialogTitle>
            <DialogDescription>修改后将立即保存到数据库</DialogDescription>
          </DialogHeader>
          {form && <MetadataForm state={form} onChange={(patch) => setForm((f) => (f ? { ...f, ...patch } : f))} disabled={savingMeta} />}
          <DialogFooter>
            <Button variant="outline" disabled={savingMeta} onClick={() => setEditOpen(false)}>
              取消
            </Button>
            <Button
              className="gap-1.5 bg-teal-600 text-white hover:bg-teal-700"
              disabled={savingMeta}
              onClick={() => void saveMeta(() => setEditOpen(false))}
            >
              {savingMeta && <Loader2 className="h-4 w-4 animate-spin" />}
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
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed py-16 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-rose-500/10">
        <TriangleAlert className="h-6 w-6 text-rose-500" />
      </div>
      <div>
        <p className="font-medium">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={onBack} className="gap-1.5">
          <BookOpen className="h-3.5 w-3.5" />
          返回文献列表
        </Button>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            重试
          </Button>
        )}
      </div>
    </div>
  );
}
