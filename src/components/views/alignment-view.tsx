'use client';

/**
 * CryoAgent Pro — 序列比对视图
 * Needleman-Wunsch 全局比对 / Smith-Waterman 局部比对 (Gotoh 仿射间隙)
 * 支持直接输入序列或从 PDB 提取 · BLOSUM62/45/PAM250 · 一致序列 · 历史任务
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import {
  Boxes, ChevronDown, Copy, Dna, FlaskConical, GitCompareArrows, History, Loader2,
  Play, RotateCcw, Sparkles, Trash2, Wand2,
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

// ============ 序列输入面板 ============

function SequencePanel({
  title,
  tone,
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
  tone: 'teal' | 'emerald';
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
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <CardTitle className={cn('flex items-center gap-2 text-sm', tone === 'teal' ? 'text-teal-700 dark:text-teal-300' : 'text-emerald-700 dark:text-emerald-300')}>
          <Dna className="h-4 w-4" />
          {title}
        </CardTitle>
        <div className="flex rounded-lg border p-0.5 text-[11px]">
          <button
            type="button"
            onClick={() => onModeChange('raw')}
            className={cn('rounded-md px-2 py-1 transition-colors', mode === 'raw' ? 'bg-teal-600/10 font-medium text-teal-700 dark:text-teal-300' : 'text-muted-foreground hover:text-foreground')}
          >
            直接输入
          </button>
          <button
            type="button"
            onClick={() => onModeChange('pdb')}
            className={cn('rounded-md px-2 py-1 transition-colors', mode === 'pdb' ? 'bg-teal-600/10 font-medium text-teal-700 dark:text-teal-300' : 'text-muted-foreground hover:text-foreground')}
          >
            从 PDB 获取
          </button>
        </div>
      </div>

      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">序列名称 (可选)</Label>
          <Input value={name} onChange={(e) => onNameChange(e.target.value)} placeholder="例如 Hemoglobin alpha" />
        </div>

        {mode === 'raw' ? (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">氨基酸 / 核酸序列</Label>
              <span className="text-[11px] tabular-nums text-muted-foreground">{cleaned.length} 残基</span>
            </div>
            <Textarea
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
            <Label className="text-xs text-muted-foreground">PDB ID (自动提取首个实体序列)</Label>
            <Input
              value={pdbId}
              onChange={(e) => onPdbIdChange(e.target.value.toUpperCase())}
              placeholder="例如 6M0J"
              className="font-mono"
            />
            <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <Boxes className="h-3 w-3" />
              服务端从 RCSB 拉取结构并提取序列 (含缓存)
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}

// ============ 比对块渲染 ============

function AlignmentBlocks({ result, seq1Name, seq2Name }: { result: AlignmentResult; seq1Name: string; seq2Name: string }) {
  const blocks = result.blocks.slice(0, MAX_DISPLAY_BLOCKS);
  return (
    <div className="space-y-4 overflow-x-auto custom-scrollbar" role="region" aria-label="比对结果块">
      {blocks.map((block, bi) => {
        const s1 = block.rows.map((r) => r.s1).join('');
        const match = block.rows.map((r) => r.match).join('');
        const s2 = block.rows.map((r) => r.s2).join('');
        const pos1 = String(block.start1).padStart(6, ' ');
        const pos2 = String(block.start2).padStart(6, ' ');
        return (
          <div key={bi} className="font-mono text-xs leading-5">
            <div className="whitespace-pre text-muted-foreground">
              {`${seq1Name.slice(0, 10).padEnd(10)} ${pos1} `}
              {s1.split('').map((c, i) => (
                <span
                  key={i}
                  className={cn(
                    match[i] === '|' ? 'font-bold text-emerald-600 dark:text-emerald-400'
                      : match[i] === ':' ? 'text-teal-600 dark:text-teal-400'
                        : c === '-' ? 'text-rose-500'
                          : 'text-foreground/80'
                  )}
                >
                  {c}
                </span>
              ))}
            </div>
            <div className="whitespace-pre text-muted-foreground/60">
              {' '.repeat(10 + 7)}
              {match.split('').map((c, i) => (
                <span key={i} className={cn(c === '|' ? 'text-emerald-500' : c === ':' ? 'text-teal-500' : 'opacity-20')}>
                  {c === ' ' ? '·' : c}
                </span>
              ))}
            </div>
            <div className="whitespace-pre text-muted-foreground">
              {`${seq2Name.slice(0, 10).padEnd(10)} ${pos2} `}
              {s2.split('').map((c, i) => (
                <span
                  key={i}
                  className={cn(
                    match[i] === '|' ? 'font-bold text-emerald-600 dark:text-emerald-400'
                      : match[i] === ':' ? 'text-teal-600 dark:text-teal-400'
                        : c === '-' ? 'text-rose-500'
                          : 'text-foreground/80'
                  )}
                >
                  {c}
                </span>
              ))}
            </div>
            <div className="mt-1 text-[10px] text-muted-foreground/60">
              区间: seq1 {block.start1}-{block.end1} · seq2 {block.start2}-{block.end2}
            </div>
          </div>
        );
      })}
      {result.blocks.length > MAX_DISPLAY_BLOCKS && (
        <p className="rounded-lg border border-dashed p-3 text-center text-xs text-muted-foreground">
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
    v >= 40 ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30'
      : v >= 20 ? 'bg-teal-500/10 text-teal-700 dark:text-teal-300 border-teal-500/30'
        : 'bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30';

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 p-4 md:space-y-6 md:p-6">
      {/* 页头 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600 text-white shadow-lg shadow-teal-500/20">
          <GitCompareArrows className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-bold tracking-tight">序列比对</h2>
          <p className="text-xs text-muted-foreground">Gotoh 仿射间隙动态规划 · NW 全局 / SW 局部 · 多种替换矩阵</p>
        </div>
      </div>

      {prefilled && (
        <Card className="border-teal-500/30 bg-teal-500/5 p-3 text-xs text-teal-700 dark:text-teal-300">
          已从其他视图预填序列, 可直接点击「开始比对」或编辑后使用。
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        {/* 主区域 */}
        <div className="space-y-4">
          {/* 输入面板 */}
          <div className="grid gap-4 md:grid-cols-2">
            <SequencePanel
              title="序列 1" tone="teal"
              name={name1} onNameChange={setName1}
              sequence={seq1} onSequenceChange={setSeq1}
              pdbId={pdbId1} onPdbIdChange={setPdbId1}
              mode={mode1} onModeChange={setMode1}
            />
            <SequencePanel
              title="序列 2" tone="emerald"
              name={name2} onNameChange={setName2}
              sequence={seq2} onSequenceChange={setSeq2}
              pdbId={pdbId2} onPdbIdChange={setPdbId2}
              mode={mode2} onModeChange={setMode2}
            />
          </div>

          {/* 控制条 */}
          <Card className="p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1 space-y-1.5">
                <Label className="text-xs text-muted-foreground">比对算法</Label>
                <Select value={algorithm} onValueChange={setAlgorithm}>
                  <SelectTrigger aria-label="比对算法"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="needleman-wunsch">Needleman-Wunsch · 全局比对</SelectItem>
                    <SelectItem value="smith-waterman">Smith-Waterman · 局部比对</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex-1 space-y-1.5">
                <Label className="text-xs text-muted-foreground">替换矩阵</Label>
                <Select value={matrix} onValueChange={setMatrix}>
                  <SelectTrigger aria-label="替换矩阵"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="BLOSUM62">BLOSUM62 (默认)</SelectItem>
                    <SelectItem value="BLOSUM45">BLOSUM45 (远缘)</SelectItem>
                    <SelectItem value="PAM250">PAM250 (远缘)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex gap-2">
                <Button onClick={runAlignment} disabled={aligning} className="gap-2">
                  {aligning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  开始比对
                </Button>
                <Button variant="outline" onClick={clearAll} className="gap-2" aria-label="清空输入">
                  <RotateCcw className="h-4 w-4" />
                  清空
                </Button>
              </div>
            </div>
          </Card>

          {/* 结果 */}
          {aligning && <Skeleton className="h-64 w-full rounded-xl" />}
          {response && result && !aligning && (
            <div className="space-y-4">
              {/* 指标卡片 */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: '比对得分', value: String(result.score), hint: `${result.matrix} · gap -11/-1` },
                  { label: '一致性', value: `${result.identity}%`, hint: '完全相同残基占比', accent: 'text-emerald-600 dark:text-emerald-400' },
                  { label: '相似度', value: `${result.similarity}%`, hint: '含正相似替换', accent: 'text-teal-600 dark:text-teal-400' },
                  { label: 'Gap 数量', value: String(result.gaps), hint: `占比 ${result.gapRatio}%` },
                  { label: '比对长度', value: `${result.alignedLength} 列`, hint: `seq1 ${response.seq1Length} / seq2 ${response.seq2Length} aa` },
                  { label: 'RMSD 估算', value: Number.isNaN(rmsd) ? '—' : `${rmsd?.toFixed(2)} Å`, hint: 'Chothia-Lesk 经验公式' },
                  { label: '转换 (Transition)', value: String(result.transitions), hint: '嘌呤嘌呤↔嘌呤 / 嘧啶↔嘧啶' },
                  { label: '颠换 (Transversion)', value: String(result.transversions), hint: '嘌呤↔嘧啶' },
                ].map((m) => (
                  <Card key={m.label} className="p-3 transition-colors hover:border-teal-500/40">
                    <div className="text-[11px] text-muted-foreground">{m.label}</div>
                    <div className={cn('mt-0.5 text-lg font-bold tabular-nums', m.accent)}>{m.value}</div>
                    <div className="mt-0.5 text-[10px] text-muted-foreground/70">{m.hint}</div>
                  </Card>
                ))}
              </div>

              {/* 比对块 */}
              <Card className="p-4">
                <CardHeader className="mb-3 flex-row items-center justify-between space-y-0 p-0">
                  <CardTitle className="flex items-center gap-2 text-sm">
                    <GitCompareArrows className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                    比对结果
                    <Badge variant="secondary" className="font-normal">
                      {result.algorithm === 'smith-waterman' ? '局部' : '全局'} · {result.matrix}
                    </Badge>
                  </CardTitle>
                  <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                    <span className="hidden items-center gap-1 sm:flex"><span className="font-bold text-emerald-600 dark:text-emerald-400">■</span>相同</span>
                    <span className="hidden items-center gap-1 sm:flex"><span className="text-teal-500">■</span>正相似</span>
                    <span className="hidden items-center gap-1 sm:flex"><span className="text-rose-500">■</span>Gap</span>
                    <span>{response.computeMs} ms</span>
                    <Button size="sm" variant="outline" onClick={copyAlignment} className="h-7 gap-1.5 text-xs">
                      <Copy className="h-3 w-3" />复制比对结果
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  <AlignmentBlocks result={result} seq1Name={response.seq1Name} seq2Name={response.seq2Name} />
                </CardContent>
              </Card>

              {/* 一致序列 */}
              <Card className="p-4">
                <Collapsible open={consensusOpen} onOpenChange={setConsensusOpen}>
                  <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 text-left">
                    <CardTitle className="flex items-center gap-2 text-sm">
                      <Sparkles className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                      一致序列 (Consensus)
                      <Badge variant="secondary" className="font-normal">{result.consensus.length} 残基</Badge>
                    </CardTitle>
                    <ChevronDown className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform', consensusOpen && 'rotate-180')} />
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <p className="mb-2 text-[11px] text-muted-foreground">两序列逐位取众数残基 (小写表示存在分歧), 可用于快速查看保守位点。</p>
                    <div className="max-h-56 overflow-y-auto custom-scrollbar rounded-lg border bg-muted/30 p-3 font-mono text-xs break-all leading-relaxed">
                      {result.consensus}
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              </Card>
            </div>
          )}

          {!response && !aligning && (
            <Card className="flex h-56 flex-col items-center justify-center gap-2 border-dashed p-4 text-sm text-muted-foreground">
              <GitCompareArrows className="h-9 w-9 opacity-30" />
              输入两条序列 (或 PDB ID) 后点击「开始比对」
              <span className="text-[11px] opacity-70">右侧提供示例序列一键填充</span>
            </Card>
          )}
        </div>

        {/* 侧栏 */}
        <div className="space-y-4">
          {/* 示例序列 */}
          <Card className="p-4">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Wand2 className="h-4 w-4 text-teal-600 dark:text-teal-400" />
              示例序列
            </CardTitle>
            <p className="mt-1.5 text-[11px] text-muted-foreground">人血红蛋白 α / β 亚基 (一致性约 45%)</p>
            <div className="mt-3 space-y-2">
              <Button
                variant="outline"
                className="w-full justify-start gap-2 text-xs"
                onClick={() => { setMode1('raw'); setSeq1(HBA); setName1('HBA · 人血红蛋白 α'); }}
              >
                <Dna className="h-3.5 w-3.5 text-teal-600" />
                填充示例 A → 序列 1 ({HBA.length} aa)
              </Button>
              <Button
                variant="outline"
                className="w-full justify-start gap-2 text-xs"
                onClick={() => { setMode2('raw'); setSeq2(HBB); setName2('HBB · 人血红蛋白 β'); }}
              >
                <Dna className="h-3.5 w-3.5 text-emerald-600" />
                填充示例 B → 序列 2 ({HBB.length} aa)
              </Button>
            </div>
          </Card>

          {/* 最近比对 */}
          <Card className="flex flex-col p-4">
            <CardTitle className="flex items-center gap-2 text-sm">
              <History className="h-4 w-4 text-teal-600 dark:text-teal-400" />
              最近比对
              <span className="ml-auto text-[11px] font-normal text-muted-foreground">{tasks.length} 条</span>
            </CardTitle>
            <div className="mt-3 max-h-[480px] space-y-1.5 overflow-y-auto custom-scrollbar pr-1">
              {tasksLoading && Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-lg" />)}
              {!tasksLoading && tasks.length === 0 && (
                <p className="py-8 text-center text-xs text-muted-foreground">暂无比对历史</p>
              )}
              {tasks.map((t) => (
                <div key={t.id} className="rounded-lg border p-2.5 transition-colors hover:border-teal-500/40">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium" title={`${t.seq1Name} vs ${t.seq2Name}`}>
                        {t.seq1Name.length > 14 ? `${t.seq1Name.slice(0, 14)}…` : t.seq1Name}
                        <span className="mx-1 text-muted-foreground">vs</span>
                        {t.seq2Name.length > 14 ? `${t.seq2Name.slice(0, 14)}…` : t.seq2Name}
                      </p>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        {formatDate(t.createdAt)} · {t.algorithm === 'smith-waterman' ? 'SW' : 'NW'} · {t.matrix}
                      </p>
                    </div>
                    <span className={cn('shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-semibold tabular-nums', identityTone(t.identity))}>
                      {t.identity}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
            {tasks.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="mt-2 h-7 gap-1.5 text-xs text-muted-foreground"
                onClick={() => void loadTasks()}
              >
                <RotateCcw className="h-3 w-3" />刷新列表
              </Button>
            )}
          </Card>

          {/* 说明 */}
          <Card className="p-4 text-[11px] leading-relaxed text-muted-foreground">
            <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-foreground">
              <FlaskConical className="h-3.5 w-3.5 text-teal-600 dark:text-teal-400" />
              算法说明
            </div>
            <p className="mb-1"><span className="font-medium text-foreground">NW 全局比对</span>: 适合同源全长序列, 端到端对齐。</p>
            <p className="mb-1"><span className="font-medium text-foreground">SW 局部比对</span>: 适合查找共享结构域 / 局部同源片段。</p>
            <p className="flex items-center gap-1"><Trash2 className="h-3 w-3 opacity-60" />序列上限 8000 残基, 超长请截断。</p>
          </Card>
        </div>
      </div>
    </div>
  );
}
