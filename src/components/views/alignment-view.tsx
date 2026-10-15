'use client';

/**
 * CryoAgent Pro — 序列比对视图 (BENCH 设计系统)
 * Needleman-Wunsch 全局比对 / Smith-Waterman 局部比对 (Gotoh 仿射间隙)
 * 支持直接输入序列或从 PDB 提取 · BLOSUM62/45/PAM250 · 一致序列 · 历史任务
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import {
  ArrowRight, Boxes, ChevronDown, Copy, Dna, Loader2, Play, RotateCcw,
} from 'lucide-react';

// ============ 类型定义 (API 契约) ============

interface AlignmentRow {
  s1: string;
  match: string;
  s2: string;
}

interface AlignmentBlock {
  start1: number;
  end1: number;
  start2: number;
  end2: number;
  rows: AlignmentRow[];
}

interface AlignmentResult {
  algorithm: string;
  matrix: string;
  score: number;
  identity: number;
  similarity: number;
  gaps: number;
  gapRatio: number;
  alignedLength: number;
  seq1Aligned: string;
  seq2Aligned: string;
  matchLine: string;
  blocks: AlignmentBlock[];
  seq1Range: [number, number];
  seq2Range: [number, number];
  consensus: string;
  transitions: number;
  transversions: number;
}

interface AlignmentResponse {
  taskId: string;
  seq1Name: string;
  seq2Name: string;
  seq1Length: number;
  seq2Length: number;
  computeMs: number;
  result: AlignmentResult;
}

interface AlignmentTask {
  id: string;
  seq1Name: string;
  seq2Name: string;
  algorithm: string;
  matrix: string;
  identity: number;
  score: number;
  createdAt: string;
}

// ============ 示例序列 (人血红蛋白 α / β 亚基) ============

const HBA = 'MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHFDLSHGSAQVKGHGKKVADALTNAVAHVDDMPNALSALSDLHAHKLRVDPVNFKLLSHCLLVTLAAHLPAEFTPAVHASLDKFLASVSTVLTSKYR';
const HBB = 'MVHLTPEEKSAVTALWGKVNVDEVGGEALGRLLVVYPWTQRFFESFGDLSTPDAVMGNPKVKAHGKKVLGAFSDGLAHLDNLKGTFATLSELHCDKLHVDPENFRLLGNVLVCVLAHHFGKEFTPPVQAAYQKVVAGVANALAHKYH';

const MAX_DISPLAY_BLOCKS = 50;

/** Chothia-Lesk 经验公式: 由序列一致性估算结构 RMSD (Å) */
function estimateRmsd(identity: number): number {
  if (identity <= 0) return NaN;
  return Math.round(0.4 * Math.exp(1.9 * (1 - identity / 100)) * 100) / 100;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

// ============ BENCH 面板基元 ============

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
function Empty({ text }: { text: string }) {
  return (
    <div className="label-tech flex h-full min-h-[88px] items-center justify-center px-4 py-8 text-center !text-[10px] normal-case !tracking-[0.06em]">
      {text}
    </div>
  );
}

/** 仪器式分段控件 */
function Segmented<T extends string>({
  value, onChange, options, ariaLabel, mono,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  ariaLabel: string;
  mono?: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-1" role="radiogroup" aria-label={ariaLabel}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'flex h-11 items-center rounded-[5px] border px-3 text-xs transition-colors sm:h-8',
            mono && 'font-mono text-[11px]',
            value === o.value
              ? 'border-primary/50 bg-accent font-medium text-accent-foreground'
              : 'border-input bg-card text-muted-foreground hover:border-foreground/25 hover:text-foreground'
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ============ 序列输入子面板 ============

function SequencePanel({
  title,
  name,
  onNameChange,
  sequence,
  onSequenceChange,
  pdbId,
  onPdbIdChange,
  mode,
  onModeChange,
}: {
  title: string;
  name: string;
  onNameChange: (v: string) => void;
  sequence: string;
  onSequenceChange: (v: string) => void;
  pdbId: string;
  onPdbIdChange: (v: string) => void;
  mode: 'raw' | 'pdb';
  onModeChange: (m: 'raw' | 'pdb') => void;
}) {
  const cleaned = sequence.replace(/\s/g, '');
  return (
    <div className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="label-tech !text-[10px] text-foreground/75">{title}</span>
        <div className="flex rounded-[5px] border p-0.5" role="radiogroup" aria-label={`${title} 输入方式`}>
          <button
            type="button"
            role="radio"
            aria-checked={mode === 'raw'}
            onClick={() => onModeChange('raw')}
            className={cn(
              'rounded-[3px] px-2.5 py-1 text-[11px] transition-colors',
              mode === 'raw' ? 'bg-accent font-medium text-accent-foreground' : 'text-muted-foreground hover:text-foreground'
            )}
          >
            直接输入
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={mode === 'pdb'}
            onClick={() => onModeChange('pdb')}
            className={cn(
              'rounded-[3px] px-2.5 py-1 text-[11px] transition-colors',
              mode === 'pdb' ? 'bg-accent font-medium text-accent-foreground' : 'text-muted-foreground hover:text-foreground'
            )}
          >
            PDB 提取
          </button>
        </div>
      </div>

      <div className="space-y-1.5">
        <label className="label-tech !text-[9px] normal-case !tracking-[0.06em]" htmlFor={`${title}-name`}>
          序列名称 · 可选
        </label>
        <Input
          id={`${title}-name`}
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="例如 Hemoglobin alpha"
          className="h-9 text-xs"
        />
      </div>

      {mode === 'raw' ? (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="label-tech !text-[9px] normal-case !tracking-[0.06em]" htmlFor={`${title}-seq`}>
              氨基酸 / 核酸序列
            </label>
            <span className="num text-[10px] text-muted-foreground">{cleaned.length} 残基</span>
          </div>
          <Textarea
            id={`${title}-seq`}
            value={sequence}
            onChange={(e) => onSequenceChange(e.target.value)}
            placeholder="粘贴 FASTA 或纯序列…"
            className="min-h-[110px] resize-y font-mono text-xs leading-relaxed"
            spellCheck={false}
            aria-label={`${title} 序列输入`}
          />
        </div>
      ) : (
        <div className="space-y-1.5">
          <label className="label-tech !text-[9px] normal-case !tracking-[0.06em]" htmlFor={`${title}-pdb`}>
            PDB ID · 自动提取首个实体序列
          </label>
          <Input
            id={`${title}-pdb`}
            value={pdbId}
            onChange={(e) => onPdbIdChange(e.target.value.toUpperCase())}
            placeholder="例如 6M0J"
            className="h-9 font-mono text-xs"
            aria-label={`${title} PDB ID 输入`}
          />
          <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Boxes className="h-3 w-3 shrink-0" strokeWidth={1.75} />
            服务端从 RCSB 拉取结构并提取序列 (含缓存)
          </p>
        </div>
      )}
    </div>
  );
}

// ============ 比对块渲染 (60 残基/块 · 行号 mono) ============

function AlignmentBlocks({ result, seq1Name, seq2Name }: { result: AlignmentResult; seq1Name: string; seq2Name: string }) {
  const blocks = result.blocks.slice(0, MAX_DISPLAY_BLOCKS);
  const residueClass = (c: string, m: string | undefined) =>
    m === '|' ? 'aln-match' : m === ':' ? 'aln-positive' : c === '-' ? 'aln-gap' : 'text-foreground/80';
  const markClass = (c: string) => (c === '|' ? 'text-chart-1' : c === ':' ? 'text-chart-2' : 'opacity-25');

  return (
    <div className="space-y-5 overflow-x-auto custom-scrollbar" role="region" aria-label="比对结果块">
      <div className="min-w-max">
        <div className="flex flex-wrap items-baseline gap-x-8 gap-y-1 border-b pb-2.5">
          <div className="min-w-0">
            <span className="label-tech !text-[9px]">SEQ 01</span>
            <span className="ml-2 truncate align-baseline text-xs font-medium">{seq1Name}</span>
          </div>
          <div className="min-w-0">
            <span className="label-tech !text-[9px]">SEQ 02</span>
            <span className="ml-2 truncate align-baseline text-xs font-medium">{seq2Name}</span>
          </div>
          <div className="ml-auto flex items-center gap-4">
            <span className="flex items-center gap-1.5 font-mono text-[9px] text-muted-foreground">
              <span className="h-2 w-2 rounded-[2px] bg-chart-1" aria-hidden />相同
            </span>
            <span className="flex items-center gap-1.5 font-mono text-[9px] text-muted-foreground">
              <span className="h-2 w-2 rounded-[2px] bg-chart-2" aria-hidden />正相似
            </span>
            <span className="flex items-center gap-1.5 font-mono text-[9px] text-muted-foreground">
              <span className="h-2 w-2 rounded-[2px] bg-muted-foreground/50" aria-hidden />GAP
            </span>
          </div>
        </div>

        {blocks.map((block, bi) => {
          const s1 = block.rows.map((r) => r.s1).join('');
          const match = block.rows.map((r) => r.match).join('');
          const s2 = block.rows.map((r) => r.s2).join('');
          return (
            <div key={bi} className="pt-4">
              <div className="label-tech mb-1 !text-[9px]">
                {`BLOCK ${String(bi + 1).padStart(2, '0')} · SEQ1 ${block.start1}–${block.end1} · SEQ2 ${block.start2}–${block.end2}`}
              </div>
              <div className="flex items-baseline gap-3">
                <span className="num w-11 shrink-0 text-right text-[10px] text-muted-foreground/70">{block.start1}</span>
                <span className="seq-mono whitespace-pre text-xs leading-5">
                  {s1.split('').map((c, i) => (
                    <span key={i} className={residueClass(c, match[i])}>{c}</span>
                  ))}
                </span>
              </div>
              <div className="flex items-baseline gap-3">
                <span className="w-11 shrink-0" aria-hidden />
                <span className="seq-mono whitespace-pre text-xs leading-5">
                  {match.split('').map((c, i) => (
                    <span key={i} className={markClass(c)}>{c === ' ' ? '·' : c}</span>
                  ))}
                </span>
              </div>
              <div className="flex items-baseline gap-3">
                <span className="num w-11 shrink-0 text-right text-[10px] text-muted-foreground/70">{block.start2}</span>
                <span className="seq-mono whitespace-pre text-xs leading-5">
                  {s2.split('').map((c, i) => (
                    <span key={i} className={residueClass(c, match[i])}>{c}</span>
                  ))}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      {result.blocks.length > MAX_DISPLAY_BLOCKS && (
        <p className="rounded-md border border-dashed px-3 py-2.5 text-center text-xs text-muted-foreground">
          仅显示前 {MAX_DISPLAY_BLOCKS} 块 ({result.blocks.length} 块共 {result.alignedLength} 列), 完整结果请使用「复制比对结果」
        </p>
      )}
    </div>
  );
}

// ============ 主组件 ============

export function AlignmentView() {
  const viewParams = useAppStore((s) => s.viewParams);

  // 预填: viewParams.seq → 序列 1; viewParams.seq1/seq2 → 两条
  const [seq1, setSeq1] = useState(() => viewParams.seq1 ?? viewParams.seq ?? '');
  const [seq2, setSeq2] = useState(() => viewParams.seq2 ?? '');
  const prefilled = Boolean(viewParams.seq || viewParams.seq1 || viewParams.seq2);

  const [name1, setName1] = useState(() => (viewParams.seq1 ? 'Sequence 1' : viewParams.seq ? '预填序列' : ''));
  const [name2, setName2] = useState('');
  const [pdbId1, setPdbId1] = useState('');
  const [pdbId2, setPdbId2] = useState('');
  const [mode1, setMode1] = useState<'raw' | 'pdb'>('raw');
  const [mode2, setMode2] = useState<'raw' | 'pdb'>('raw');
  const [algorithm, setAlgorithm] = useState('needleman-wunsch');
  const [matrix, setMatrix] = useState('BLOSUM62');

  const [aligning, setAligning] = useState(false);
  const [response, setResponse] = useState<AlignmentResponse | null>(null);

  const [tasks, setTasks] = useState<AlignmentTask[]>([]);
  const [tasksLoading, setTasksLoading] = useState(true);
  const [consensusOpen, setConsensusOpen] = useState(false);

  const loadTasks = useCallback(async () => {
    try {
      const d = await api<{ tasks: AlignmentTask[] }>('/api/alignment');
      setTasks(d.tasks);
    } catch {
      /* 静默失败 */
    } finally {
      setTasksLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api<{ tasks: AlignmentTask[] }>('/api/alignment');
        if (!cancelled) setTasks(d.tasks);
      } catch {
        /* 静默失败 */
      } finally {
        if (!cancelled) setTasksLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const result = response?.result;

  const rmsd = useMemo(() => (result ? estimateRmsd(result.identity) : null), [result]);

  const runAlignment = async () => {
    const s1 = mode1 === 'raw' ? seq1.replace(/\s/g, '') : '';
    const s2 = mode2 === 'raw' ? seq2.replace(/\s/g, '') : '';
    if (mode1 === 'raw' && !s1) { toast.error('请输入序列 1'); return; }
    if (mode2 === 'raw' && !s2) { toast.error('请输入序列 2'); return; }
    if (mode1 === 'pdb' && !pdbId1.trim()) { toast.error('请输入 PDB ID 1'); return; }
    if (mode2 === 'pdb' && !pdbId2.trim()) { toast.error('请输入 PDB ID 2'); return; }

    setAligning(true);
    setResponse(null);
    try {
      const d = await api<AlignmentResponse>('/api/alignment', {
        method: 'POST',
        body: JSON.stringify({
          sequence1: s1 || undefined,
          sequence2: s2 || undefined,
          pdbId1: mode1 === 'pdb' ? pdbId1.trim() : undefined,
          pdbId2: mode2 === 'pdb' ? pdbId2.trim() : undefined,
          seq1Name: name1.trim() || undefined,
          seq2Name: name2.trim() || undefined,
          algorithm,
          matrix,
        }),
      });
      setResponse(d);
      setConsensusOpen(false);
      toast.success(`比对完成 · 得分 ${d.result.score} · 一致性 ${d.result.identity}%`);
      void loadTasks();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '比对失败');
    } finally {
      setAligning(false);
    }
  };

  const copyAlignment = async () => {
    if (!result || !response) return;
    const lines: string[] = [
      `# CryoAgent Pro 序列比对`,
      `# ${response.seq1Name} (${response.seq1Length} aa) vs ${response.seq2Name} (${response.seq2Length} aa)`,
      `# 算法: ${result.algorithm} · 矩阵: ${result.matrix} · 得分: ${result.score} · 一致性: ${result.identity}% · 相似度: ${result.similarity}%`,
      '',
    ];
    for (const block of result.blocks) {
      const s1 = block.rows.map((r) => r.s1).join('');
      const match = block.rows.map((r) => r.match).join('');
      const s2 = block.rows.map((r) => r.s2).join('');
      lines.push(`${response.seq1Name.slice(0, 14).padEnd(14)} ${String(block.start1).padStart(6)} ${s1}`);
      lines.push(`${' '.repeat(14)} ${' '.repeat(6)} ${match}`);
      lines.push(`${response.seq2Name.slice(0, 14).padEnd(14)} ${String(block.start2).padStart(6)} ${s2}`);
      lines.push('');
    }
    try {
      await navigator.clipboard.writeText(lines.join('\n'));
      toast.success('比对结果已复制到剪贴板');
    } catch {
      toast.error('复制失败, 请手动选择文本');
    }
  };

  const clearAll = () => {
    setSeq1(''); setSeq2(''); setName1(''); setName2('');
    setPdbId1(''); setPdbId2(''); setMode1('raw'); setMode2('raw');
    setResponse(null);
  };

  const identityTone = (v: number) =>
    v >= 40 ? 'text-chart-1'
      : v >= 20 ? 'text-foreground'
        : 'text-muted-foreground';

  return (
    <div className="animate-fade-in-up">
      {/* ===== Masthead — 坐标纸 + 模块代号 ===== */}
      <div className="grid-bg relative border-b">
        <div className="flex flex-wrap items-end justify-between gap-4 px-4 py-6 md:px-6">
          <div>
            <div className="label-tech !text-[10px]">Alignment · 序列比对</div>
            <h1 className="mt-1.5 text-[26px] font-semibold leading-none tracking-tight md:text-[30px]">
              序列比对
              <span className="font-display ml-2 font-normal italic text-muted-foreground">Pairwise Alignment</span>
            </h1>
            <p className="mt-2.5 max-w-lg text-xs leading-relaxed text-muted-foreground">
              Gotoh 仿射间隙动态规划 — NW 全局 / SW 局部比对 · BLOSUM / PAM 替换矩阵 · 一致序列与 Chothia-Lesk RMSD 估算 · 支持 RCSB 实体序列提取
            </p>
          </div>
          <div className="label-tech space-y-1.5 text-right !text-[10px]">
            <div className="flex items-center justify-end gap-2">
              <span className="status-dot" aria-hidden /> GOTOH AFFINE GAP
            </div>
            <div className="text-muted-foreground/60">BLOSUM62 · GAP -11 / -1</div>
            <div className="text-muted-foreground/60">CAP 2000 × 2000 AA</div>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-4 md:p-6">
        {prefilled && (
          <div className="flex items-center gap-2.5 rounded-lg border border-primary/30 bg-accent/40 px-4 py-2.5">
            <span className="status-dot" aria-hidden />
            <p className="text-xs text-accent-foreground">已从其他视图预填序列 — 可直接执行比对, 或编辑后使用。</p>
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
          {/* ===== 主区域 ===== */}
          <div className="min-w-0 space-y-4">
            {/* 序列输入 */}
            <Panel>
              <PanelHead title="序列输入 · INPUT" hint="FASTA / 纯序列 · RCSB 提取" />
              <div className="grid gap-4 p-4 md:grid-cols-2 md:gap-x-6">
                <SequencePanel
                  title="序列 1 · SEQ 01"
                  name={name1} onNameChange={setName1}
                  sequence={seq1} onSequenceChange={setSeq1}
                  pdbId={pdbId1} onPdbIdChange={setPdbId1}
                  mode={mode1} onModeChange={setMode1}
                />
                <div className="md:border-l md:pl-6">
                  <SequencePanel
                    title="序列 2 · SEQ 02"
                    name={name2} onNameChange={setName2}
                    sequence={seq2} onSequenceChange={setSeq2}
                    pdbId={pdbId2} onPdbIdChange={setPdbId2}
                    mode={mode2} onModeChange={setMode2}
                  />
                </div>
              </div>
            </Panel>

            {/* 比对参数 */}
            <Panel>
              <PanelHead title="比对参数 · PARAMETERS" hint="GOTOH · GAP OPEN -11 / EXTEND -1" />
              <div className="flex flex-col gap-4 p-4 lg:flex-row lg:items-start">
                <div className="min-w-0 flex-1 space-y-1.5">
                  <span className="label-tech !text-[9px]">比对算法</span>
                  <Segmented
                    value={algorithm}
                    onChange={setAlgorithm}
                    ariaLabel="比对算法"
                    options={[
                      { value: 'needleman-wunsch', label: 'NW · 全局比对' },
                      { value: 'smith-waterman', label: 'SW · 局部比对' },
                    ]}
                  />
                </div>
                <div className="min-w-0 flex-1 space-y-1.5">
                  <span className="label-tech !text-[9px]">替换矩阵</span>
                  <Segmented
                    mono
                    value={matrix}
                    onChange={setMatrix}
                    ariaLabel="替换矩阵"
                    options={[
                      { value: 'BLOSUM62', label: 'BLOSUM62' },
                      { value: 'BLOSUM45', label: 'BLOSUM45' },
                      { value: 'PAM250', label: 'PAM250' },
                    ]}
                  />
                </div>
                <div className="flex shrink-0 gap-2 lg:pt-5">
                  <Button onClick={runAlignment} disabled={aligning} className="gap-2">
                    {aligning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" strokeWidth={1.75} />}
                    开始比对
                  </Button>
                  <Button variant="outline" onClick={clearAll} className="gap-2" aria-label="清空输入">
                    <RotateCcw className="h-4 w-4" strokeWidth={1.75} />
                    清空
                  </Button>
                </div>
              </div>
            </Panel>

            {/* 结果 */}
            {aligning && <Skeleton className="h-64 w-full rounded-lg" />}
            {response && result && !aligning && (
              <div className="space-y-4">
                {/* 指标条 — hairline 分隔 */}
                <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-4">
                  {[
                    { label: '比对得分', value: String(result.score), hint: `${result.matrix} · GAP -11/-1` },
                    { label: '一致性', value: `${result.identity}%`, hint: '完全相同残基占比', accent: true },
                    { label: '相似度', value: `${result.similarity}%`, hint: '含正相似替换' },
                    { label: 'Gap 数量', value: String(result.gaps), hint: `占比 ${result.gapRatio}%` },
                    { label: '比对长度', value: `${result.alignedLength} 列`, hint: `SEQ1 ${response.seq1Length} / SEQ2 ${response.seq2Length} AA` },
                    { label: 'RMSD 估算', value: Number.isNaN(rmsd) ? '—' : `${rmsd?.toFixed(2)} Å`, hint: 'Chothia-Lesk 经验公式' },
                    { label: '转换', value: String(result.transitions), hint: 'TRANSITION · 嘌呤↔嘌呤' },
                    { label: '颠换', value: String(result.transversions), hint: 'TRANSVERSION · 嘌呤↔嘧啶' },
                  ].map((m) => (
                    <div key={m.label} className="min-w-0 bg-card px-4 py-3">
                      <div className="label-tech !text-[9px]">{m.label}</div>
                      <div className={cn('num mt-1 text-[20px] font-medium leading-none tracking-tight', m.accent && 'text-primary')}>{m.value}</div>
                      <div className="label-tech mt-1.5 !text-[9px] normal-case !tracking-normal text-muted-foreground/70">{m.hint}</div>
                    </div>
                  ))}
                </div>

                {/* 比对视图 + 一致序列 */}
                <Panel>
                  <PanelHead
                    title="比对视图 · ALIGNMENT VIEW"
                    hint={`${result.algorithm === 'smith-waterman' ? 'SW 局部' : 'NW 全局'} · ${result.matrix} · ${response.computeMs} ms`}
                    action={
                      <button
                        type="button"
                        onClick={copyAlignment}
                        className="label-tech ml-2 flex shrink-0 items-center gap-1 !text-[9px] !text-primary transition-opacity hover:opacity-70"
                      >
                        复制比对结果 <Copy className="h-3 w-3" strokeWidth={1.75} />
                      </button>
                    }
                  />
                  <div className="p-4">
                    <AlignmentBlocks result={result} seq1Name={response.seq1Name} seq2Name={response.seq2Name} />
                  </div>
                  <Collapsible open={consensusOpen} onOpenChange={setConsensusOpen}>
                    <div className="border-t">
                      <CollapsibleTrigger className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-accent/50">
                        <span className="label-tech !text-[10px] text-foreground/75">一致序列 · CONSENSUS</span>
                        <span className="label-tech ml-auto !text-[9px]">{result.consensus.length} 残基</span>
                        <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform', consensusOpen && 'rotate-180')} />
                      </CollapsibleTrigger>
                      <CollapsibleContent>
                        <div className="px-4 pb-4">
                          <p className="mb-2 text-[11px] text-muted-foreground">
                            两序列逐位取众数残基 (小写表示存在分歧), 可用于快速查看保守位点。
                          </p>
                          <div className="seq-mono max-h-56 overflow-y-auto custom-scrollbar rounded-md border bg-muted/30 p-3 text-xs leading-relaxed">
                            {result.consensus}
                          </div>
                        </div>
                      </CollapsibleContent>
                    </div>
                  </Collapsible>
                </Panel>
              </div>
            )}

            {!response && !aligning && (
              <Panel>
                <Empty text="NO RESULT — 输入两条序列 (或 PDB ID) 后点击「开始比对」, 右侧提供示例序列一键填充" />
              </Panel>
            )}
          </div>

          {/* ===== 侧栏 ===== */}
          <div className="min-w-0 space-y-4">
            {/* 示例序列 */}
            <Panel>
              <PanelHead title="示例序列 · SAMPLES" hint="HBA / HBB · ~45% ID" />
              <div className="divide-y">
                <button
                  type="button"
                  onClick={() => { setMode1('raw'); setSeq1(HBA); setName1('HBA · 人血红蛋白 α'); }}
                  className="group flex w-full items-center gap-3 py-2.5 pl-4 pr-3 text-left transition-colors hover:bg-accent/50"
                >
                  <Dna className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium leading-tight">填充示例 A → 序列 1</span>
                    <span className="label-tech mt-0.5 block !text-[9px] normal-case !tracking-normal">HBA · 人血红蛋白 α · {HBA.length} AA</span>
                  </span>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40 transition-all group-hover:translate-x-0.5 group-hover:text-foreground" />
                </button>
                <button
                  type="button"
                  onClick={() => { setMode2('raw'); setSeq2(HBB); setName2('HBB · 人血红蛋白 β'); }}
                  className="group flex w-full items-center gap-3 py-2.5 pl-4 pr-3 text-left transition-colors hover:bg-accent/50"
                >
                  <Dna className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium leading-tight">填充示例 B → 序列 2</span>
                    <span className="label-tech mt-0.5 block !text-[9px] normal-case !tracking-normal">HBB · 人血红蛋白 β · {HBB.length} AA</span>
                  </span>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40 transition-all group-hover:translate-x-0.5 group-hover:text-foreground" />
                </button>
              </div>
              <p className="border-t px-4 py-2 text-[11px] text-muted-foreground">
                人血红蛋白 α / β 亚基 — 一致性约 45%, 适合演示全局比对。
              </p>
            </Panel>

            {/* 算法说明 */}
            <Panel>
              <PanelHead title="算法说明 · NOTES" />
              <div className="divide-y">
                {[
                  ['NW · 全局', 'Needleman-Wunsch — 适合同源全长序列, 端到端对齐'],
                  ['SW · 局部', 'Smith-Waterman — 查找共享结构域 / 局部同源片段'],
                  ['GAP 罚分', '仿射间隙 open -11 · extend -1'],
                  ['矩阵上限', '2000 × 2000 残基, 超长序列请先截断'],
                ].map(([k, v]) => (
                  <div key={k} className="px-4 py-2">
                    <div className="num text-[11px] font-medium">{k}</div>
                    <div className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{v}</div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </div>

        {/* ===== 比对历史 — 仪器表格 ===== */}
        <Panel>
          <PanelHead
            title="比对历史 · HISTORY"
            hint={tasksLoading ? 'LOADING…' : `${tasks.length} 条`}
            action={
              <button
                type="button"
                onClick={() => void loadTasks()}
                className="label-tech ml-2 flex shrink-0 items-center gap-1 !text-[9px] !text-primary transition-opacity hover:opacity-70"
              >
                刷新 <RotateCcw className="h-3 w-3" strokeWidth={1.75} />
              </button>
            }
          />
          {tasksLoading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-9 rounded-md" />)}
            </div>
          ) : tasks.length === 0 ? (
            <Empty text="NO HISTORY — 完成第一次比对后在此显示任务记录" />
          ) : (
            <div className="max-h-[360px] overflow-y-auto custom-scrollbar">
              <table className="bench">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>序列对</th>
                    <th>ALG</th>
                    <th>MATRIX</th>
                    <th className="!text-right">IDENTITY</th>
                    <th className="!text-right">SCORE</th>
                  </tr>
                </thead>
                <tbody>
                  {tasks.map((t) => (
                    <tr key={t.id}>
                      <td className="num whitespace-nowrap text-muted-foreground">{formatDate(t.createdAt)}</td>
                      <td className="max-w-[340px]">
                        <span className="block truncate" title={`${t.seq1Name} vs ${t.seq2Name}`}>
                          {t.seq1Name.length > 18 ? `${t.seq1Name.slice(0, 18)}…` : t.seq1Name}
                          <span className="mx-1.5 text-muted-foreground">vs</span>
                          {t.seq2Name.length > 18 ? `${t.seq2Name.slice(0, 18)}…` : t.seq2Name}
                        </span>
                      </td>
                      <td className="num">{t.algorithm === 'smith-waterman' ? 'SW' : 'NW'}</td>
                      <td className="num">{t.matrix}</td>
                      <td className={cn('num text-right font-medium', identityTone(t.identity))}>{t.identity}%</td>
                      <td className="num text-right">{t.score}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
