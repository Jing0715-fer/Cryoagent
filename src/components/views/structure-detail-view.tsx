'use client';

/**
 * CryoAgent Pro — 结构详情页 (含 3Dmol.js 3D 查看器)
 * 头部元数据 / 3D 查看器 / 概览 / 实体序列 / 关联文献 / 相关结构
 */

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { toast } from 'sonner';
import {
  ArrowLeft, Boxes, Calendar, Copy, Dna, ExternalLink, FileText, FlaskConical,
  GitCompareArrows, Layers, Link2, Loader2, Microscope, RefreshCw, RotateCcw,
  Sparkles, TriangleAlert,
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

// ============ 通用组件 ============

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

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toISOString().slice(0, 10);
  } catch {
    return iso;
  }
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
          viewerRef.current = Mol.createViewer(el, { backgroundColor: '#fafafa', antialias: true });
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
    <Card className="gap-4 p-4 md:p-6">
      {/* 工具栏 */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2">
          <Boxes className="h-5 w-5 text-teal-600 dark:text-teal-400" />
          <h3 className="text-base font-semibold">3D 结构查看器</h3>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Select value={style} onValueChange={(v) => setStyle(v as ViewerStyle)}>
            <SelectTrigger size="sm" className="w-[100px]" aria-label="显示样式">
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
            <SelectTrigger size="sm" className="w-[112px]" aria-label="着色方式">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="spectrum">光谱渐变</SelectItem>
              <SelectItem value="residue">按残基</SelectItem>
              <SelectItem value="chain">按链</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={resetView} className="gap-1.5">
            <RotateCcw className="h-3.5 w-3.5" />
            重置视角
          </Button>
        </div>
      </div>

      {/* 查看器画布 */}
      <div className="relative overflow-hidden rounded-lg border bg-[#fafafa]">
        <div ref={containerRef} className="h-[420px] w-full" data-testid="mol-viewer" />

        {showOverlay && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-background/70 backdrop-blur-[1px]">
            <Loader2 className="h-6 w-6 animate-spin text-teal-600" />
            <p className="text-xs text-muted-foreground">
              {!molReady ? '正在加载 3Dmol.js 渲染引擎…' : '正在获取 PDB 坐标数据…'}
            </p>
          </div>
        )}

        {showError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-background p-6 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-rose-500/10">
              <TriangleAlert className="h-5 w-5 text-rose-500" />
            </div>
            <p className="text-sm font-medium">3D 查看器不可用</p>
            <p className="max-w-sm text-xs leading-relaxed text-muted-foreground">
              {molError || pdbErrorShown}
            </p>
            <Button variant="outline" size="sm" onClick={retry} className="gap-1.5">
              <RefreshCw className="h-3.5 w-3.5" />
              重试
            </Button>
          </div>
        )}

        <div className="pointer-events-none absolute bottom-2 right-2 rounded bg-background/80 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
          {source === 'alphafold' ? `AlphaFold · ${alphaFold.uniprotId}` : `RCSB · ${pdbId}`}
        </div>
      </div>

      {/* AlphaFold 切换 */}
      <div className="flex flex-wrap items-center gap-2">
        {alphaFold.available ? (
          source === 'alphafold' ? (
            <Button variant="outline" size="sm" onClick={() => setSource('rcsb')} className="gap-1.5">
              <Boxes className="h-3.5 w-3.5" />
              返回实验结构
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSource('alphafold')}
              className="gap-1.5 border-teal-500/50 text-teal-700 hover:bg-teal-500/10 dark:text-teal-300"
            >
              <Sparkles className="h-3.5 w-3.5" />
              查看 AlphaFold 模型
            </Button>
          )
        ) : (
          <Badge variant="secondary">暂无 AlphaFold 预测模型</Badge>
        )}
        <p className="text-[11px] text-muted-foreground">
          {source === 'alphafold'
            ? `当前展示 AlphaFold 预测模型 (UniProt: ${alphaFold.uniprotId})`
            : '当前展示 RCSB 实验结构 · 可拖拽旋转 / 滚轮缩放'}
        </p>
      </div>
    </Card>
  );
}

// ============ 实体序列卡片 ============

function SequenceCard({
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
    <Card className="gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">实体 {seq.entityId}</span>
        <Badge variant="secondary">{seq.length} aa</Badge>
        {seq.chains.map((c) => (
          <Badge key={c} variant="outline" className="font-mono text-[10px]">
            链 {c}
          </Badge>
        ))}
        {seq.uniprotIds.map((u) => (
          <a key={u} href={`https://www.uniprot.org/uniprotkb/${u}`} target="_blank" rel="noreferrer">
            <Badge
              variant="outline"
              className="font-mono text-[10px] text-teal-700 hover:border-teal-500/50 dark:text-teal-300"
            >
              {u}
              <ExternalLink className="h-2.5 w-2.5" />
            </Badge>
          </a>
        ))}
      </div>

      {seq.description && <p className="text-xs text-muted-foreground">{seq.description}</p>}

      <div className="max-h-40 overflow-y-auto custom-scrollbar rounded-lg bg-muted/50 p-3">
        <p className="break-all font-mono text-xs leading-relaxed">{seq.sequence}</p>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => onCopy(seq.sequence)} className="gap-1.5">
          <Copy className="h-3.5 w-3.5" />
          复制序列
        </Button>
        <Button variant="outline" size="sm" onClick={() => onAlign(seq.sequence)} className="gap-1.5">
          <GitCompareArrows className="h-3.5 w-3.5" />
          发送到比对
        </Button>
        <Button variant="outline" size="sm" onClick={() => onAnalyze(seq.sequence)} className="gap-1.5">
          <FlaskConical className="h-3.5 w-3.5" />
          理化分析
        </Button>
      </div>
    </Card>
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
      <div className="mx-auto w-full max-w-3xl p-4 md:p-6">
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
      <div className="mx-auto w-full max-w-6xl space-y-4 p-4 md:p-6">
        <Skeleton className="h-8 w-40" />
        <Card className="gap-3 p-6">
          <Skeleton className="h-8 w-36" />
          <Skeleton className="h-5 w-3/4" />
          <div className="flex gap-2">
            <Skeleton className="h-5 w-16" />
            <Skeleton className="h-5 w-14" />
            <Skeleton className="h-5 w-20" />
          </div>
        </Card>
        <Skeleton className="h-[500px] w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="mx-auto w-full max-w-3xl p-4 md:p-6">
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
    <div className="mx-auto w-full max-w-6xl p-4 md:p-6">
      {/* 顶部操作栏 */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => navigate('structures')} className="gap-1.5">
          <ArrowLeft className="h-4 w-4" />
          返回结构浏览器
        </Button>
        <Badge variant={detail.fromCache ? 'secondary' : 'outline'}>
          {detail.fromCache ? '本地缓存' : '实时数据'}
        </Badge>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void doRefresh()}
          disabled={refreshing}
          className="ml-auto gap-1.5"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} />
          {refreshing ? '正在从 RCSB 刷新…' : '刷新数据'}
        </Button>
      </div>

      {/* 头部信息卡 */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
        <Card className="gap-4 p-6">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <span className="font-mono text-2xl font-bold tracking-wider text-teal-700 dark:text-teal-300">
                  {s.pdbId}
                </span>
                {detail.alphaFold.available && (
                  <Badge className="gap-1 border border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
                    <Sparkles className="h-3 w-3" />
                    AlphaFold 可用
                  </Badge>
                )}
              </div>
              <h2 className="mt-2 text-lg font-semibold leading-snug">{s.title}</h2>
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <MethodBadge method={s.method} />
                {s.resolution != null && <Badge variant="secondary">{s.resolution} Å</Badge>}
                {s.organism && (
                  <Badge variant="outline" className="max-w-64 gap-1 truncate">
                    <Dna className="h-3 w-3 shrink-0" />
                    <span className="truncate">{s.organism}</span>
                  </Badge>
                )}
                {s.entityCount != null && <Badge variant="secondary">{s.entityCount} 实体</Badge>}
                {s.residueCount != null && <Badge variant="secondary">{s.residueCount} 残基</Badge>}
                {s.emdbIds.map((e) => (
                  <a key={e} href={`https://www.ebi.ac.uk/emdb/${e}`} target="_blank" rel="noreferrer">
                    <Badge
                      variant="outline"
                      className="cursor-pointer gap-1 hover:border-teal-500/50 hover:text-teal-700 dark:hover:text-teal-300"
                    >
                      EMDB {e}
                      <ExternalLink className="h-3 w-3" />
                    </Badge>
                  </a>
                ))}
              </div>
            </div>
            <Button asChild variant="outline" size="sm" className="w-fit gap-1.5">
              <a href={`https://www.rcsb.org/structure/${s.pdbId}`} target="_blank" rel="noreferrer">
                <ExternalLink className="h-3.5 w-3.5" />
                RCSB 页面
              </a>
            </Button>
          </div>
        </Card>
      </motion.div>

      {/* 3D 查看器 */}
      <div className="my-4">
        <StructureViewer3D key={s.pdbId} pdbId={s.pdbId} alphaFold={detail.alphaFold} />
      </div>

      {/* 主体 Tabs */}
      <Tabs defaultValue="overview" className="gap-4">
        <TabsList className="grid h-auto w-full grid-cols-2 sm:inline-flex sm:w-auto">
          <TabsTrigger value="overview" className="px-3 py-1.5 text-xs sm:text-sm">概览</TabsTrigger>
          <TabsTrigger value="sequences" className="px-3 py-1.5 text-xs sm:text-sm">实体序列</TabsTrigger>
          <TabsTrigger value="literature" className="px-3 py-1.5 text-xs sm:text-sm">关联文献</TabsTrigger>
          <TabsTrigger value="related" className="px-3 py-1.5 text-xs sm:text-sm">相关结构</TabsTrigger>
        </TabsList>

        {/* ======== 概览 ======== */}
        <TabsContent value="overview">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {s.citation && (
              <Card className="gap-3 p-4">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <FileText className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                  结构引文
                </div>
                <p className="text-sm leading-relaxed">{s.citation.title}</p>
                <p className="text-xs text-muted-foreground">
                  {s.citation.authors.slice(0, 8).join(', ')}
                  {s.citation.authors.length > 8 ? ' 等' : ''}
                </p>
                <p className="text-xs text-muted-foreground">
                  {[s.citation.journal, s.citation.year].filter(Boolean).join(' · ') || '—'}
                </p>
              </Card>
            )}

            <Card className="gap-3 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <Calendar className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                基本信息
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-lg bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">沉积日期</p>
                  <p className="mt-0.5 font-medium">{formatDate(s.depositDate)}</p>
                </div>
                <div className="rounded-lg bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">释放日期</p>
                  <p className="mt-0.5 font-medium">{formatDate(s.releaseDate)}</p>
                </div>
                <div className="rounded-lg bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">实体数</p>
                  <p className="mt-0.5 font-medium">{s.entityCount ?? '—'}</p>
                </div>
                <div className="rounded-lg bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">残基数</p>
                  <p className="mt-0.5 font-medium">{s.residueCount ?? '—'}</p>
                </div>
              </div>
            </Card>

            {s.uniprotIds.length > 0 && (
              <Card className="gap-3 p-4 lg:col-span-2">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <Dna className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                  UniProt 注释 ({s.uniprotIds.length})
                </div>
                <div className="overflow-x-auto custom-scrollbar">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-32">Accession</TableHead>
                        <TableHead>蛋白名称</TableHead>
                        <TableHead className="w-40">链</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {s.uniprotIds.map((u) => (
                        <TableRow key={u.uniprotId}>
                          <TableCell className="font-mono text-xs">
                            <a
                              href={`https://www.uniprot.org/uniprotkb/${u.uniprotId}`}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-teal-600 hover:underline dark:text-teal-400"
                            >
                              {u.uniprotId}
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          </TableCell>
                          <TableCell className="text-xs">{u.proteinName || '—'}</TableCell>
                          <TableCell>
                            <div className="flex flex-wrap gap-1">
                              {u.chains.map((c) => (
                                <Badge key={c} variant="secondary" className="font-mono text-[10px]">
                                  {c}
                                </Badge>
                              ))}
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </Card>
            )}

            <Card className="gap-3 p-4 lg:col-span-2">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <Microscope className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                配体 ({s.ligands.length})
              </div>
              {s.ligands.length === 0 ? (
                <p className="text-xs text-muted-foreground">暂无配体信息</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {s.ligands.map((l, i) => (
                    <Badge
                      key={`${l.name}-${i}`}
                      variant="outline"
                      title={[l.formula, l.description].filter(Boolean).join(' · ')}
                      className="gap-1 font-mono text-[11px]"
                    >
                      {l.name}
                      {l.formula && <span className="text-muted-foreground">{l.formula}</span>}
                    </Badge>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </TabsContent>

        {/* ======== 实体序列 ======== */}
        <TabsContent value="sequences">
          {s.sequences.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed py-12 text-center">
              <Layers className="h-6 w-6 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">暂无实体序列数据, 可尝试刷新获取 RCSB 实时数据</p>
            </div>
          ) : (
            <div className="space-y-4">
              {s.sequences.map((seq) => (
                <SequenceCard
                  key={seq.entityId}
                  seq={seq}
                  onCopy={(v) => void copySequence(v)}
                  onAlign={(v) => navigate('alignment', { seq: v })}
                  onAnalyze={(v) => navigate('sequence-analyzer', { seq: v })}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* ======== 关联文献 ======== */}
        <TabsContent value="literature">
          {detail.literature.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed py-12 text-center">
              <FileText className="h-6 w-6 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                暂无关联文献 — 上传提及该 PDB ID 的文献后会自动建立关联
              </p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {detail.literature.map((l) => (
                <Card
                  key={l.id}
                  role="button"
                  tabIndex={0}
                  className="cursor-pointer gap-3 p-4 transition-all hover:border-teal-500/50 hover:shadow-md"
                  onClick={() => navigate('literature-detail', { id: l.id })}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      navigate('literature-detail', { id: l.id });
                    }
                  }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="line-clamp-2 text-sm font-semibold leading-snug">{l.title}</p>
                    <Badge variant="secondary" className="shrink-0 gap-1">
                      <Link2 className="h-3 w-3" />
                      提及 {l.mentionCount}
                    </Badge>
                  </div>
                  <p className="truncate text-xs text-muted-foreground">
                    {l.authors.length > 0
                      ? `${l.authors.slice(0, 3).join(', ')}${l.authors.length > 3 ? ' 等' : ''}`
                      : '未知作者'}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {[l.year, l.journal].filter(Boolean).join(' · ') || '—'}
                  </p>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        {/* ======== 相关结构 ======== */}
        <TabsContent value="related">
          {detail.relatedStructures.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed py-12 text-center">
              <Boxes className="h-6 w-6 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">暂无相关结构 (基于共享文献计算)</p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {detail.relatedStructures.map((r) => (
                <Card
                  key={r.id}
                  role="button"
                  tabIndex={0}
                  className="cursor-pointer gap-3 p-4 transition-all hover:border-teal-500/50 hover:shadow-md"
                  onClick={() => navigate('structure-detail', { id: r.id })}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      navigate('structure-detail', { id: r.id });
                    }
                  }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-base font-bold text-teal-700 dark:text-teal-300">
                      {r.id}
                    </span>
                    <Badge
                      variant="outline"
                      className="border-teal-500/30 bg-teal-500/10 text-[11px] text-teal-700 dark:text-teal-300"
                    >
                      共享 {r.sharedLiterature} 篇文献
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">与当前结构在文献中共同出现</p>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
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
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed py-16 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-rose-500/10">
        <TriangleAlert className="h-6 w-6 text-rose-500" />
      </div>
      <div>
        <p className="font-medium">{title}</p>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={onBack} className="gap-1.5">
          <Boxes className="h-3.5 w-3.5" />
          返回结构浏览器
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
