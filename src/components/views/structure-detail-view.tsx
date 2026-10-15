'use client';

/**
 * CryoAgent Pro — 结构详情 (BENCH 设计系统)
 * masthead(PDB ID 编辑性标题) + 3D 查看器主区 + 侧栏 mono 元数据 + 仪器表格/密集列表
 * 功能不变: 3Dmol.js 渲染 / AlphaFold 切换 / 序列操作 / 关联文献与相关结构
 */

import { useEffect, useRef, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import {
  ArrowLeft, Copy, ExternalLink, FlaskConical, GitCompareArrows, Loader2,
  RefreshCw, RotateCcw, TriangleAlert,
} from 'lucide-react';

// ============ 类型定义 (API 契约) ============

interface UniprotRef {
  uniprotId: string;
  chains: string[];
  proteinName: string;
}

interface LigandInfo {
  name: string;
  formula?: string;
  description?: string;
}

interface CitationInfo {
  title: string;
  journal: string;
  year: number | null;
  authors: string[];
}

interface SequenceInfo {
  entityId: string;
  chains: string[];
  sequence: string;
  length: number;
  description: string;
  uniprotIds: string[];
}

interface StructureDetailInfo {
  pdbId: string;
  title: string;
  method: string | null;
  resolution: number | null;
  organism: string | null;
  uniprotIds: UniprotRef[];
  entityCount: number | null;
  residueCount: number | null;
  ligands: LigandInfo[];
  citation: CitationInfo | null;
  sequences: SequenceInfo[];
  depositDate: string | null;
  releaseDate: string | null;
  emdbIds: string[];
}

interface RelatedLiterature {
  id: string;
  title: string;
  year: number | null;
  journal: string | null;
  authors: string[];
  mentionCount: number;
}

interface StructureDetailResponse {
  structure: StructureDetailInfo;
  literature: RelatedLiterature[];
  relatedStructures: { id: string; sharedLiterature: number }[];
  alphaFold: { available: boolean; uniprotId: string | null };
  fromCache: boolean;
  forceRefresh: boolean;
}

// ============ 3Dmol.js 类型与加载器 ============

type ViewerStyle = 'cartoon' | 'stick' | 'sphere' | 'line';
type ViewerColor = 'spectrum' | 'residue' | 'chain';

interface Mol3DViewer {
  addModel(data: string, format: string): void;
  setStyle(selector: Record<string, unknown>, style: Record<string, unknown>): void;
  setBackgroundColor(color: string): void;
  zoomTo(): void;
  render(): void;
  clear(): void;
  resize(): void;
}

interface Mol3DGlobal {
  createViewer(element: HTMLElement | string, config: Record<string, unknown>): Mol3DViewer;
}

declare global {
  interface Window {
    $3Dmol?: Mol3DGlobal;
  }
}

let molScriptPromise: Promise<void> | null = null;

/** 动态注入 3Dmol.js CDN 脚本 (全局仅注入一次) */
function load3Dmol(): Promise<void> {
  if (typeof window === 'undefined') return Promise.reject(new Error('3D 查看器仅在浏览器环境可用'));
  if (window.$3Dmol) return Promise.resolve();
  if (molScriptPromise) return molScriptPromise;
  molScriptPromise = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://3Dmol.org/build/3Dmol-min.js';
    script.async = true;
    script.onload = () => {
      if (window.$3Dmol) resolve();
      else {
        molScriptPromise = null;
        reject(new Error('3Dmol.js 脚本已加载但全局对象缺失'));
      }
    };
    script.onerror = () => {
      molScriptPromise = null;
      script.remove();
      reject(new Error('无法从 CDN 加载 3Dmol.js, 请检查网络后重试'));
    };
    document.head.appendChild(script);
  });
  return molScriptPromise;
}

function buildStyleSpec(style: ViewerStyle, color: ViewerColor): Record<string, unknown> {
  const colorSpec: Record<string, unknown> =
    color === 'spectrum' ? { color: 'spectrum' } : { colorscheme: color };
  return { [style]: colorSpec };
}

/** 获取 PDB 原始文本 (非 JSON 接口, 不能用 api<T>()) */
async function fetchPdbText(url: string): Promise<string> {
  const resp = await fetch(url);
  if (!resp.ok) {
    let message = `PDB 数据获取失败 (${resp.status})`;
    try {
      const data = (await resp.json()) as { error?: string };
      if (data.error) message = data.error;
    } catch {
      /* 错误体不是 JSON */
    }
    throw new Error(message);
  }
  const text = await resp.text();
  if (!text.trim()) throw new Error('PDB 数据为空');
  return text;
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
    <div className="label-tech flex h-full min-h-[96px] items-center justify-center px-4 py-10 text-center !text-[10px] normal-case !tracking-[0.06em]">
      {text}
    </div>
  );
}

/** 实验方法短码标签 — 分类编码走 chart 色系 */
function methodShort(method: string | null): string {
  const m = (method || '').toUpperCase();
  if (m.includes('X-RAY')) return 'X-RAY';
  if (m.includes('ELECTRON MICROSCOPY')) return 'CRYO-EM';
  if (m.includes('NMR')) return 'NMR';
  if (m.includes('ALPHAFOLD') || m.includes('PREDICT')) return 'PRED';
  return method ? method.slice(0, 8).toUpperCase() : '—';
}

function methodTone(method: string | null): string {
  const m = (method || '').toUpperCase();
  if (m.includes('X-RAY')) return 'border-chart-3/45 text-chart-3';
  if (m.includes('ELECTRON MICROSCOPY')) return 'border-chart-2/45 text-chart-2';
  if (m.includes('NMR')) return 'border-chart-4/45 text-chart-4';
  if (m.includes('ALPHAFOLD') || m.includes('PREDICT')) return 'border-chart-5/45 text-chart-5';
  return 'border-border text-muted-foreground';
}

function MethodTag({ method }: { method: string | null }) {
  return (
    <span
      className={cn(
        'shrink-0 rounded-[3px] border px-1.5 py-px font-mono text-[9px] font-medium tracking-wide',
        methodTone(method)
      )}
    >
      {methodShort(method)}
    </span>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toISOString().slice(0, 10);
  } catch {
    return iso;
  }
}

/** 侧栏 mono 键值行 */
function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-4 py-[7px]">
      <span className="label-tech shrink-0 !text-[9px]">{label}</span>
      <span className="min-w-0 truncate text-right text-[11px] font-medium">{children}</span>
    </div>
  );
}

// ============ 3D 查看器 ============

function StructureViewer3D({
  pdbId,
  alphaFold,
}: {
  pdbId: string;
  alphaFold: { available: boolean; uniprotId: string | null };
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Mol3DViewer | null>(null);

  const [molReady, setMolReady] = useState(false);
  const [molError, setMolError] = useState<string | null>(null);
  const [pdbText, setPdbText] = useState<string | null>(null);
  const [pdbLoading, setPdbLoading] = useState(true);
  const [pdbError, setPdbError] = useState<string | null>(null);
  const [fetchNonce, setFetchNonce] = useState(0);
  const [source, setSource] = useState<'rcsb' | 'alphafold'>('rcsb');
  const [style, setStyle] = useState<ViewerStyle>('cartoon');
  const [color, setColor] = useState<ViewerColor>('spectrum');

  // 1. 加载 3Dmol.js 脚本
  useEffect(() => {
    let cancelled = false;
    load3Dmol()
      .then(() => {
        if (!cancelled) setMolReady(true);
      })
      .catch((err: unknown) => {
        if (!cancelled) setMolError(err instanceof Error ? err.message : '3Dmol.js 加载失败');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 2. 获取 PDB 坐标文本 (缺 UniProt ID 的异常情况在渲染层派生, 避免 effect 内同步 setState)
  const afIdMissing = source === 'alphafold' && !alphaFold.uniprotId;
  const fetchId = source === 'alphafold' ? alphaFold.uniprotId : pdbId;

  useEffect(() => {
    if (!fetchId) return;
    let cancelled = false;
    const url =
      source === 'alphafold'
        ? `/api/structure/${encodeURIComponent(fetchId)}/pdb?source=alphafold`
        : `/api/structure/${encodeURIComponent(fetchId)}/pdb`;
    void (async () => {
      setPdbLoading(true);
      setPdbError(null);
      try {
        const text = await fetchPdbText(url);
        if (!cancelled) setPdbText(text);
      } catch (err) {
        if (!cancelled) setPdbError(err instanceof Error ? err.message : 'PDB 数据加载失败');
      } finally {
        if (!cancelled) setPdbLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchId, source, fetchNonce]);

  // 3. 创建/重绘查看器 (样式或着色变化时重绘); rAF 回调内执行, 等待布局尺寸就绪
  useEffect(() => {
    const el = containerRef.current;
    const Mol = window.$3Dmol;
    if (!molReady || !Mol || !pdbText || !el) return;
    const raf = requestAnimationFrame(() => {
      try {
        if (!viewerRef.current) {
          viewerRef.current = Mol.createViewer(el, { backgroundColor: '#171b1d', antialias: true });
        }
        const viewer = viewerRef.current;
        viewer.clear();
        viewer.addModel(pdbText, 'pdb');
        viewer.setStyle({}, buildStyleSpec(style, color));
        viewer.zoomTo();
        viewer.render();
      } catch {
        setMolError('3D 渲染失败, 结构数据可能不完整');
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [molReady, pdbText, style, color]);

  // 4. 窗口缩放自适应
  useEffect(() => {
    const onResize = () => viewerRef.current?.resize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const resetView = () => {
    const viewer = viewerRef.current;
    if (!viewer || !pdbText) return;
    try {
      viewer.clear();
      viewer.addModel(pdbText, 'pdb');
      viewer.setStyle({}, buildStyleSpec(style, color));
      viewer.zoomTo();
      viewer.render();
    } catch {
      toast.error('重置视角失败');
    }
  };

  const retry = () => {
    if (molError) {
      setMolError(null);
      load3Dmol()
        .then(() => setMolReady(true))
        .catch((err: unknown) =>
          setMolError(err instanceof Error ? err.message : '3Dmol.js 加载失败')
        );
    }
    if (pdbError) setFetchNonce((n) => n + 1);
  };

  const pdbErrorShown =
    pdbError ?? (afIdMissing ? '缺少 UniProt ID, 无法加载 AlphaFold 模型' : null);
  const showOverlay = (pdbLoading || !molReady) && !molError && !pdbErrorShown;
  const showError = Boolean(molError || pdbErrorShown);

  return (
    <Panel>
      {/* 工具栏 — 面板头内嵌渲染控制 */}
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
        <span className="label-tech !text-[10px] text-foreground/75">3D Viewer · 三维结构</span>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <Select value={style} onValueChange={(v) => setStyle(v as ViewerStyle)}>
            <SelectTrigger size="sm" className="h-8 w-[92px] rounded-[5px] text-xs" aria-label="显示样式">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="cartoon">带状</SelectItem>
              <SelectItem value="stick">棒状</SelectItem>
              <SelectItem value="sphere">球状</SelectItem>
              <SelectItem value="line">线状</SelectItem>
            </SelectContent>
          </Select>
          <Select value={color} onValueChange={(v) => setColor(v as ViewerColor)}>
            <SelectTrigger size="sm" className="h-8 w-[104px] rounded-[5px] text-xs" aria-label="着色方式">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="spectrum">光谱渐变</SelectItem>
              <SelectItem value="residue">按残基</SelectItem>
              <SelectItem value="chain">按链</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={resetView} className="h-8 gap-1.5 text-xs">
            <RotateCcw className="h-3.5 w-3.5" strokeWidth={1.75} />
            重置视角
          </Button>
        </div>
      </div>

      {/* 查看器画布 — 石墨仪器屏 + 内凹屏幕质感 */}
      <div className="p-2">
        <div className="relative overflow-hidden rounded-md border bg-[#171b1d] shadow-[inset_0_1px_4px_rgba(0,0,0,0.35)]">
          <div ref={containerRef} className="h-[420px] w-full" data-testid="mol-viewer" />

          {/* 左上角渲染模式铭牌 — mono 短码 */}
          <div
            className="pointer-events-none absolute left-2.5 top-2.5 space-y-0.5 font-mono text-[9px] uppercase tracking-[0.14em]"
            aria-hidden
          >
            <div className="text-white/50">RNDR·{style.toUpperCase()} / {color.toUpperCase()}</div>
            <div className="text-white/35">SURFACE·DRAG ROTATE</div>
          </div>

          {showOverlay && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-[#171b1d]/80">
              <Loader2 className="h-5 w-5 animate-spin text-white/70" strokeWidth={1.75} />
              <p className="font-mono text-[10px] tracking-[0.06em] text-white/55">
                {!molReady ? '正在加载 3Dmol.js 渲染引擎…' : '正在获取 PDB 坐标数据…'}
              </p>
            </div>
          )}

          {showError && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[#171b1d]/95 p-6 text-center">
              <TriangleAlert className="h-5 w-5 text-white/60" strokeWidth={1.75} />
              <div>
                <p className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-white/60">VIEWER UNAVAILABLE</p>
                <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-white/45">
                  {molError || pdbErrorShown}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={retry}
                className="h-8 gap-1.5 border-white/25 bg-transparent text-xs text-white/80 hover:bg-white/10 hover:text-white"
              >
                <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.75} />
                重试
              </Button>
            </div>
          )}

          <div className="pointer-events-none absolute bottom-2 right-2.5 font-mono text-[9px] uppercase tracking-[0.18em] text-white/35">
            {source === 'alphafold' ? `ALPHAFOLD · ${alphaFold.uniprotId}` : `RCSB · ${pdbId}`}
          </div>
        </div>
      </div>

      {/* 数据源切换 — 底部条 */}
      <div className="flex flex-wrap items-center gap-2.5 border-t px-4 py-2.5">
        {alphaFold.available ? (
          source === 'alphafold' ? (
            <Button variant="outline" size="sm" onClick={() => setSource('rcsb')} className="h-8 gap-1.5 text-xs">
              返回实验结构
            </Button>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setSource('alphafold')} className="h-8 gap-1.5 text-xs">
              查看 AlphaFold 模型
            </Button>
          )
        ) : (
          <span className="rounded-[3px] border border-border px-1.5 py-px font-mono text-[9px] text-muted-foreground">
            NO ALPHAFOLD MODEL
          </span>
        )}
        <p className="label-tech !text-[9px] normal-case !tracking-normal">
          {source === 'alphafold'
            ? `当前展示 AlphaFold 预测模型 · UNIPROT ${alphaFold.uniprotId}`
            : '当前展示 RCSB 实验结构 · 可拖拽旋转 / 滚轮缩放'}
        </p>
      </div>
    </Panel>
  );
}

// ============ 实体序列面板 ============

function SequencePanel({
  seq,
  onCopy,
  onAlign,
  onAnalyze,
}: {
  seq: SequenceInfo;
  onCopy: (sequence: string) => void;
  onAlign: (sequence: string) => void;
  onAnalyze: (sequence: string) => void;
}) {
  return (
    <Panel>
      <PanelHead
        title={`Entity ${seq.entityId} · 实体序列`}
        hint={`${seq.length} AA`}
        action={
          <span className="flex flex-wrap items-center gap-1.5">
            {seq.chains.map((c) => (
              <span key={c} className="rounded-[3px] border border-border px-1.5 py-px font-mono text-[9px] text-muted-foreground">
                CHAIN {c}
              </span>
            ))}
            {seq.uniprotIds.map((u) => (
              <a
                key={u}
                href={`https://www.uniprot.org/uniprotkb/${u}`}
                target="_blank"
                rel="noreferrer"
                className="num inline-flex items-center gap-1 rounded-[3px] border border-primary/35 px-1.5 py-px text-[9px] font-medium text-primary transition-colors hover:bg-accent"
              >
                {u}
                <ExternalLink className="h-2.5 w-2.5" strokeWidth={1.75} />
              </a>
            ))}
          </span>
        }
      />
      <div className="space-y-3 p-4">
        {seq.description && (
          <p className="text-xs leading-relaxed text-muted-foreground">{seq.description}</p>
        )}

        <div className="max-h-40 overflow-y-auto custom-scrollbar rounded-md border bg-muted/40 p-3">
          <p className="seq-mono text-xs leading-relaxed">{seq.sequence}</p>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => onCopy(seq.sequence)} className="h-8 gap-1.5 text-xs">
            <Copy className="h-3.5 w-3.5" strokeWidth={1.75} />
            复制序列
          </Button>
          <Button variant="outline" size="sm" onClick={() => onAlign(seq.sequence)} className="h-8 gap-1.5 text-xs">
            <GitCompareArrows className="h-3.5 w-3.5" strokeWidth={1.75} />
            发送到比对
          </Button>
          <Button variant="outline" size="sm" onClick={() => onAnalyze(seq.sequence)} className="h-8 gap-1.5 text-xs">
            <FlaskConical className="h-3.5 w-3.5" strokeWidth={1.75} />
            理化分析
          </Button>
        </div>
      </div>
    </Panel>
  );
}

// ============ 主视图 ============

export function StructureDetailView() {
  const viewParams = useAppStore((s) => s.viewParams);
  const navigate = useAppStore((s) => s.navigate);
  const id = viewParams.id;

  const [detail, setDetail] = useState<StructureDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  // 拉取结构详情
  useEffect(() => {
    if (!id) {
      setLoading(false);
      setError('缺少结构 ID, 请从结构浏览器进入');
      return;
    }
    let cancelled = false;
    const ctrl = new AbortController();
    setLoading(true);
    api<StructureDetailResponse>(`/api/structure/${encodeURIComponent(id)}`, { signal: ctrl.signal })
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

  // 切换相关结构时回到顶部
  useEffect(() => {
    const main = document.querySelector('main');
    if (main) main.scrollTo({ top: 0 });
  }, [id]);

  const doRefresh = async () => {
    if (!id || refreshing) return;
    setRefreshing(true);
    try {
      const d = await api<StructureDetailResponse>(
        `/api/structure/${encodeURIComponent(id)}?refresh=true`
      );
      setDetail(d);
      toast.success('已从 RCSB 刷新结构数据');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '刷新失败');
    } finally {
      setRefreshing(false);
    }
  };

  const copySequence = async (sequence: string) => {
    try {
      await navigator.clipboard.writeText(sequence);
      toast.success(`已复制 ${sequence.length} 个残基到剪贴板`);
    } catch {
      toast.error('复制失败, 请手动选择序列文本复制');
    }
  };

  // ===== 加载 / 错误态 =====
  if (!id) {
    return (
      <div className="p-4 md:p-6">
        <StructureError
          title="缺少结构 ID"
          description="请从结构浏览器或文献关联结构进入详情页"
          onBack={() => navigate('structures')}
        />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="animate-fade-in-up">
        <div className="grid-bg border-b">
          <div className="space-y-3 px-4 py-6 md:px-6">
            <div className="flex items-center justify-between">
              <Skeleton className="h-3 w-32" />
              <Skeleton className="h-3 w-24" />
            </div>
            <Skeleton className="h-8 w-44" />
            <Skeleton className="h-3 w-full max-w-lg" />
          </div>
        </div>
        <div className="space-y-4 p-4 md:p-6">
          <div className="grid gap-4 lg:grid-cols-3">
            <Skeleton className="h-[520px] rounded-lg lg:col-span-2" />
            <Skeleton className="h-[520px] rounded-lg" />
          </div>
          <Skeleton className="h-40 rounded-lg" />
        </div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="p-4 md:p-6">
        <StructureError
          title="结构加载失败"
          description={error || '未找到该结构'}
          onBack={() => navigate('structures')}
          onRetry={() => setReloadKey((k) => k + 1)}
        />
      </div>
    );
  }

  const s = detail.structure;

  return (
    <div className="animate-fade-in-up">
      {/* ===== Masthead — PDB ID 编辑性标题 + 数据源状态 ===== */}
      <div className="grid-bg border-b">
        <div className="px-4 py-5 md:px-6">
          {/* 导航行 */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => navigate('structures')}
              className="label-tech flex items-center gap-1.5 !text-[10px] transition-colors hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.75} />
              PDB LIBRARY · 返回结构浏览器
            </button>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void doRefresh()}
                disabled={refreshing}
                className="label-tech flex h-8 items-center gap-1.5 rounded-[5px] border bg-card px-2.5 !text-[10px] transition-colors hover:border-foreground/25 disabled:opacity-50"
              >
                <RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} strokeWidth={1.75} />
                {refreshing ? 'RCSB SYNC…' : '刷新数据'}
              </button>
              <a
                href={`https://www.rcsb.org/structure/${s.pdbId}`}
                target="_blank"
                rel="noreferrer"
                className="label-tech flex h-8 items-center gap-1.5 rounded-[5px] border bg-card px-2.5 !text-[10px] transition-colors hover:border-foreground/25"
              >
                <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.75} />
                RCSB 页面
              </a>
            </div>
          </div>

          {/* 标题块 */}
          <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
            <div className="min-w-0">
              <div className="label-tech !text-[10px]">PDB Entry · 结构详情</div>
              <div className="mt-1.5 flex flex-wrap items-center gap-2.5">
                <h1 className="font-display text-[30px] leading-none tracking-tight md:text-[34px]">{s.pdbId}</h1>
                <MethodTag method={s.method} />
                {s.resolution != null && (
                  <span className="num text-xs text-muted-foreground">{s.resolution.toFixed(1)}Å</span>
                )}
                {detail.alphaFold.available && (
                  <span className="rounded-[3px] border border-primary/40 px-1.5 py-px font-mono text-[9px] font-medium text-primary">
                    ALPHAFOLD
                  </span>
                )}
              </div>
              <p className="mt-2.5 max-w-xl text-xs leading-relaxed text-muted-foreground">{s.title}</p>
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                {s.organism && (
                  <span className="truncate text-[11px] text-muted-foreground">{s.organism}</span>
                )}
                {s.emdbIds.map((e) => (
                  <a
                    key={e}
                    href={`https://www.ebi.ac.uk/emdb/${e}`}
                    target="_blank"
                    rel="noreferrer"
                    className="num text-[10px] text-primary transition-opacity hover:opacity-70"
                  >
                    EMDB {e}
                  </a>
                ))}
              </div>
            </div>

            {/* 状态铭牌 */}
            <div className="label-tech space-y-1.5 text-right !text-[10px]">
              <div className="flex items-center justify-end gap-2">
                <span className="status-dot" data-tone={detail.fromCache ? undefined : 'amber'} aria-hidden />
                {detail.fromCache ? 'CACHED · 本地缓存' : 'LIVE · RCSB 实时'}
              </div>
              <div className="num text-muted-foreground/60">
                DEPOSIT {formatDate(s.depositDate)} · RELEASE {formatDate(s.releaseDate)}
              </div>
              <div className="num text-muted-foreground/60">
                {s.entityCount ?? '—'} ENT · {s.residueCount ?? '—'} RES · {s.uniprotIds.length} UNIPROT
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-4 md:p-6">
        {/* ===== 主区: 3D 查看器 (2/3) + 元数据侧栏 (1/3) ===== */}
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <StructureViewer3D key={s.pdbId} pdbId={s.pdbId} alphaFold={detail.alphaFold} />
          </div>

          <Panel className="flex flex-col">
            <PanelHead title="Metadata · 元数据" hint={detail.fromCache ? 'CACHED' : 'LIVE'} />
            <div className="divide-y text-muted-foreground/40 [&>*]:divide-x-0">
              <MetaRow label="实验方法">
                <span className="flex items-center gap-2">
                  <MethodTag method={s.method} />
                  <span className="num text-[10px] text-muted-foreground">{s.method || '—'}</span>
                </span>
              </MetaRow>
              <MetaRow label="分辨率">
                <span className="num">{s.resolution != null ? `${s.resolution.toFixed(2)} Å` : '—'}</span>
              </MetaRow>
              <MetaRow label="生物体">{s.organism || '—'}</MetaRow>
              <MetaRow label="实体数">
                <span className="num">{s.entityCount ?? '—'}</span>
              </MetaRow>
              <MetaRow label="残基数">
                <span className="num">{s.residueCount ?? '—'}</span>
              </MetaRow>
              <MetaRow label="沉积日期">
                <span className="num">{formatDate(s.depositDate)}</span>
              </MetaRow>
              <MetaRow label="释放日期">
                <span className="num">{formatDate(s.releaseDate)}</span>
              </MetaRow>
              <MetaRow label="EMDB">
                {s.emdbIds.length > 0 ? (
                  <span className="flex flex-wrap justify-end gap-x-2">
                    {s.emdbIds.map((e) => (
                      <a
                        key={e}
                        href={`https://www.ebi.ac.uk/emdb/${e}`}
                        target="_blank"
                        rel="noreferrer"
                        className="num text-primary transition-opacity hover:opacity-70"
                      >
                        {e}
                      </a>
                    ))}
                  </span>
                ) : (
                  '—'
                )}
              </MetaRow>
              <MetaRow label="AlphaFold">
                <span className="num">{detail.alphaFold.available ? detail.alphaFold.uniprotId || 'AVAILABLE' : '—'}</span>
              </MetaRow>
              <MetaRow label="配体">
                <span className="num">{s.ligands.length > 0 ? `${s.ligands.length} 项` : '—'}</span>
              </MetaRow>
            </div>
          </Panel>
        </div>

        {/* ===== 主体 Tabs ===== */}
        <Tabs defaultValue="overview" className="gap-4">
          <TabsList className="h-9 w-full gap-0 rounded-[5px] border bg-card p-[3px] shadow-none sm:w-auto">
            {(
              [
                ['overview', `概览`],
                ['sequences', `实体序列${s.sequences.length ? ` ${s.sequences.length}` : ''}`],
                ['literature', `关联文献${detail.literature.length ? ` ${detail.literature.length}` : ''}`],
                ['related', `相关结构${detail.relatedStructures.length ? ` ${detail.relatedStructures.length}` : ''}`],
              ] as const
            ).map(([value, label]) => (
              <TabsTrigger
                key={value}
                value={value}
                className="flex-1 gap-1.5 rounded-[4px] px-3.5 py-1.5 text-xs data-[state=active]:bg-accent data-[state=active]:text-accent-foreground data-[state=active]:shadow-none sm:flex-none"
              >
                {label}
              </TabsTrigger>
            ))}
          </TabsList>

          {/* ======== 概览 ======== */}
          <TabsContent value="overview" className="space-y-4">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {s.citation && (
                <Panel>
                  <PanelHead
                    title="Citation · 结构引文"
                    hint={[s.citation.journal, s.citation.year].filter(Boolean).join(' · ') || undefined}
                  />
                  <div className="space-y-2 p-4">
                    <p className="text-[13px] font-medium leading-relaxed">{s.citation.title}</p>
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      {s.citation.authors.slice(0, 8).join(', ')}
                      {s.citation.authors.length > 8 ? ' 等' : ''}
                    </p>
                    <p className="num text-[10px] text-muted-foreground/70">
                      {[s.citation.journal, s.citation.year].filter(Boolean).join(' · ') || '—'}
                    </p>
                  </div>
                </Panel>
              )}

              <Panel className={cn(!s.citation && 'lg:col-span-2')}>
                <PanelHead title="UniProt · 蛋白质注释" hint={`${s.uniprotIds.length} 条映射`} />
                {s.uniprotIds.length === 0 ? (
                  <Empty text="NO MAPPING — 该结构暂无 UniProt 交叉引用" />
                ) : (
                  <div className="overflow-x-auto custom-scrollbar">
                    <table className="bench">
                      <thead>
                        <tr>
                          <th>ACCESSION</th>
                          <th>蛋白名称</th>
                          <th>链</th>
                        </tr>
                      </thead>
                      <tbody>
                        {s.uniprotIds.map((u) => (
                          <tr key={u.uniprotId}>
                            <td className="num">
                              <a
                                href={`https://www.uniprot.org/uniprotkb/${u.uniprotId}`}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 font-medium text-primary transition-opacity hover:opacity-70"
                              >
                                {u.uniprotId}
                                <ExternalLink className="h-3 w-3" strokeWidth={1.75} />
                              </a>
                            </td>
                            <td className="text-xs">{u.proteinName || '—'}</td>
                            <td className="num text-xs text-muted-foreground">{u.chains.join(' · ') || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>

              <Panel className="lg:col-span-2">
                <PanelHead title="Ligands · 配体" hint={`${s.ligands.length} 项`} />
                {s.ligands.length === 0 ? (
                  <Empty text="NO LIGANDS — 该结构无配体记录" />
                ) : (
                  <div className="flex flex-wrap gap-2 p-4">
                    {s.ligands.map((l, i) => (
                      <span
                        key={`${l.name}-${i}`}
                        title={l.description || l.formula || undefined}
                        className="inline-flex items-baseline gap-1.5 rounded-[3px] border px-1.5 py-px font-mono text-[10px]"
                      >
                        {l.name}
                        {l.formula && <span className="text-muted-foreground">{l.formula}</span>}
                      </span>
                    ))}
                  </div>
                )}
              </Panel>
            </div>
          </TabsContent>

          {/* ======== 实体序列 ======== */}
          <TabsContent value="sequences" className="space-y-4">
            {s.sequences.length === 0 ? (
              <Panel>
                <PanelHead title="Sequences · 实体序列" />
                <Empty text="NO SEQUENCES — 暂无实体序列数据, 可尝试刷新获取 RCSB 实时数据" />
              </Panel>
            ) : (
              s.sequences.map((seq) => (
                <SequencePanel
                  key={seq.entityId}
                  seq={seq}
                  onCopy={(v) => void copySequence(v)}
                  onAlign={(v) => navigate('alignment', { seq: v })}
                  onAnalyze={(v) => navigate('sequence-analyzer', { seq: v })}
                />
              ))
            )}
          </TabsContent>

          {/* ======== 关联文献 ======== */}
          <TabsContent value="literature" className="space-y-4">
            <Panel>
              <PanelHead title="Related Literature · 关联文献" hint={`${detail.literature.length} 篇 · 提及计数`} />
              {detail.literature.length === 0 ? (
                <Empty text="NO LINKS — 上传提及该 PDB ID 的文献后会自动建立关联" />
              ) : (
                <div className="divide-y">
                  {detail.literature.map((l) => (
                    <button
                      key={l.id}
                      type="button"
                      aria-label={`查看文献 ${l.title}`}
                      onClick={() => navigate('literature-detail', { id: l.id })}
                      className="flex w-full items-baseline gap-3 px-4 py-2.5 text-left transition-colors hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
                    >
                      <span className="num w-10 shrink-0 text-[10px] text-muted-foreground/60">LIT</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium leading-snug">{l.title}</span>
                        <span className="mt-0.5 block truncate text-[10px] text-muted-foreground">
                          {l.authors.length > 0
                            ? `${l.authors.slice(0, 3).join(', ')}${l.authors.length > 3 ? ' 等' : ''}`
                            : '未知作者'}
                          {' · '}
                          {[l.year, l.journal].filter(Boolean).join(' · ') || '—'}
                        </span>
                      </span>
                      <span className="num shrink-0 text-[10px] text-muted-foreground">×{l.mentionCount}</span>
                    </button>
                  ))}
                </div>
              )}
            </Panel>
          </TabsContent>

          {/* ======== 相关结构 ======== */}
          <TabsContent value="related" className="space-y-4">
            <Panel>
              <PanelHead title="Related Structures · 相关结构" hint="BY 共享文献" />
              {detail.relatedStructures.length === 0 ? (
                <Empty text="NO RELATED — 暂无相关结构 (基于共享文献计算)" />
              ) : (
                <div className="divide-y">
                  {detail.relatedStructures.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      aria-label={`查看结构 ${r.id}`}
                      onClick={() => navigate('structure-detail', { id: r.id })}
                      className="flex w-full items-baseline gap-3 px-4 py-2.5 text-left transition-colors hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
                    >
                      <span className="num text-[13px] font-semibold tracking-tight">{r.id}</span>
                      <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">
                        与当前结构在文献中共同出现
                      </span>
                      <span className="num shrink-0 text-[10px] text-muted-foreground">SHARE {r.sharedLiterature}</span>
                    </button>
                  ))}
                </div>
              )}
            </Panel>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

// ============ 错误态 ============

function StructureError({
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
    <div className="mx-auto w-full max-w-md rounded-lg border border-destructive/40 bg-destructive/5 p-5">
      <div className="flex items-center gap-2 border-b border-destructive/30 pb-2.5">
        <TriangleAlert className="h-4 w-4 text-destructive" strokeWidth={1.75} />
        <span className="label-tech !text-[10px] !text-destructive">ENTRY LOAD FAILED</span>
      </div>
      <p className="mt-3 text-sm font-medium">{title}</p>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p>
      <div className="mt-4 flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={onBack} className="h-8 gap-1.5 text-xs">
          <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.75} />
          返回结构浏览器
        </Button>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry} className="h-8 text-xs">
            重试
          </Button>
        )}
      </div>
    </div>
  );
}
