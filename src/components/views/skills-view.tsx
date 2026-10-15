'use client';

/**
 * CryoAgent Pro — 技能中心 (BENCH 设计系统)
 * 14 个预设专家技能: 分类分组面板 + 密集行 / 详情弹窗 (系统提示词 + 步骤 + 工具) / 关键词匹配测试器
 */

import { useEffect, useMemo, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { DEFAULT_SKILLS } from '@/lib/skills';
import { MarkdownView } from '@/components/markdown-view';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { StatCard } from '@/components/ui/bench-widgets';
import { toast } from 'sonner';
import {
  Activity, ArrowRight, Layers, Loader2, MessageSquare, Search, Sparkles, Target,
} from 'lucide-react';

// ============ 类型定义 (API 契约) ============

interface SkillStepSummary {
  id: string;
  name: string;
  tool: string;
  condition?: string;
}

interface SkillSummary {
  id: string;
  name: string;
  description: string;
  category: string;
  categoryLabel: string;
  triggerKeywords: string[];
  tools: string[];
  steps: SkillStepSummary[];
  examples: string[];
  usageCount: number;
  successCount?: number;
  isBuiltin: boolean;
}

interface SkillsResponse {
  total: number;
  categories: { id: string; label: string; count: number }[];
  skills: SkillSummary[];
}

interface MatchResponse {
  query: string;
  total: number;
  matches: { skill: { id: string; name: string; category: string; description: string }; matchedKeywords: string[]; score: number }[];
}

/** GET /api/skills 不返回系统提示词, 从内置技能库补全 */
const SYSTEM_PROMPTS = new Map(DEFAULT_SKILLS.map((s) => [s.id, s.systemPrompt]));

// ============ 分类编码 — 左 2px 色条 (chart-1..5 循环) ============

const CATEGORY_BAR: Record<string, string> = {
  structure: 'bg-chart-1',
  literature: 'bg-chart-2',
  sequence: 'bg-chart-3',
  methodology: 'bg-chart-4',
  design: 'bg-chart-5',
  visualization: 'bg-chart-1',
  target: 'bg-chart-2',
  mutation: 'bg-chart-4',
  knowledge: 'bg-chart-5',
};

const CATEGORY_TAG: Record<string, string> = {
  structure: 'border-chart-1/50 text-chart-1',
  literature: 'border-chart-2/50 text-chart-2',
  sequence: 'border-chart-3/50 text-chart-3',
  methodology: 'border-chart-4/50 text-chart-4',
  design: 'border-chart-5/50 text-chart-5',
  visualization: 'border-chart-1/50 text-chart-1',
  target: 'border-chart-2/50 text-chart-2',
  mutation: 'border-chart-4/50 text-chart-4',
  knowledge: 'border-chart-5/50 text-chart-5',
};

const CATEGORY_CODE: Record<string, string> = {
  structure: 'STR',
  literature: 'LIT',
  sequence: 'SEQ',
  methodology: 'MTD',
  design: 'DSN',
  visualization: 'VIZ',
  target: 'TGT',
  mutation: 'MUT',
  knowledge: 'KG',
};

function categoryBar(category: string): string {
  return CATEGORY_BAR[category] ?? 'bg-chart-5';
}

function categoryTag(category: string): string {
  return CATEGORY_TAG[category] ?? 'border-chart-5/50 text-chart-5';
}

function categoryCode(category: string): string {
  return CATEGORY_CODE[category] ?? category.slice(0, 3).toUpperCase();
}

// ============ 技能拉丁短码 ============

const SKILL_CODE: Record<string, string> = {
  structure_compare: 'STR·CMP',
  literature_review: 'LIT·REV',
  sequence_analysis: 'SEQ·ANL',
  methodology_guide: 'MTD·GDE',
  protein_design: 'PRO·DSN',
  data_visualization: 'DAT·VIZ',
  target_analysis: 'TGT·ANL',
  mutation_analysis: 'MUT·ANL',
  structure_3d_analysis: 'STR·3D',
  structure_alignment: 'STR·ALN',
  pocket_finder: 'PKT·FND',
  sequence_properties: 'SEQ·PHY',
  kg_navigator: 'KG·NAV',
  paper_skimmer: 'PPR·SKM',
};

function skillCode(id: string): string {
  return SKILL_CODE[id] ?? id.replace(/_/g, '').slice(0, 7).toUpperCase();
}

// ============ 查询高亮 ============

function HighlightedQuery({ query, keywords }: { query: string; keywords: string[] }) {
  const parts = useMemo(() => {
    if (keywords.length === 0) return [query];
    const escaped = keywords.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const re = new RegExp(`(${escaped.join('|')})`, 'gi');
    return query.split(re);
  }, [query, keywords]);

  if (keywords.length === 0) return <span>{query}</span>;
  return (
    <span className="break-all">
      {parts.map((part, i) =>
        keywords.some((k) => k.toLowerCase() === part.toLowerCase()) ? (
          <mark key={i} className="rounded-[2px] bg-primary/15 px-0.5 font-semibold text-primary">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </span>
  );
}

// ============ 技能密集行 ============

function SkillRow({ skill, onSelect }: { skill: SkillSummary; onSelect: (s: SkillSummary) => void }) {
  const shownKeywords = skill.triggerKeywords.slice(0, 5);
  const rest = skill.triggerKeywords.length - shownKeywords.length;
  return (
    <button
      type="button"
      onClick={() => onSelect(skill)}
      className="group flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-accent/50"
      aria-label={`查看技能 ${skill.name}`}
    >
      <span className="num w-[58px] shrink-0 pt-[3px] text-[9px] font-medium tracking-wider text-muted-foreground/70">
        {skillCode(skill.id)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
          <span className="text-[13px] font-medium leading-tight">{skill.name}</span>
          <span className="num text-[10px] text-muted-foreground/70">{skill.usageCount} 次调用</span>
        </span>
        <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">{skill.description}</span>
        <span className="mt-1.5 flex flex-wrap items-center gap-1">
          {shownKeywords.map((k) => (
            <span key={k} className="rounded-[3px] border px-1.5 py-px font-mono text-[9px] text-muted-foreground">{k}</span>
          ))}
          {rest > 0 && <span className="font-mono text-[9px] text-muted-foreground/60">+{rest}</span>}
        </span>
      </span>
      <ArrowRight className="mt-1 hidden h-3.5 w-3.5 shrink-0 text-muted-foreground/40 transition-all group-hover:translate-x-0.5 group-hover:text-foreground sm:block" />
    </button>
  );
}

// ============ 技能详情弹窗 ============

function SkillDialog({ skill, onClose }: { skill: SkillSummary | null; onClose: () => void }) {
  const navigate = useAppStore((s) => s.navigate);
  const systemPrompt = skill ? SYSTEM_PROMPTS.get(skill.id) : undefined;

  if (!skill) return null;
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto custom-scrollbar">
        <DialogHeader>
          <div className="flex flex-wrap items-center gap-2 pr-6">
            <DialogTitle className="text-base">{skill.name}</DialogTitle>
            <span className={cn('rounded-[3px] border px-1.5 py-px font-mono text-[9px]', categoryTag(skill.category))}>
              {skill.categoryLabel}
            </span>
            {skill.isBuiltin && (
              <span className="rounded-[3px] border px-1.5 py-px font-mono text-[9px] text-muted-foreground">BUILTIN</span>
            )}
            <span className="num ml-auto text-[9px] tracking-wider text-muted-foreground/60">{skillCode(skill.id)}</span>
          </div>
          <DialogDescription className="text-xs leading-relaxed">{skill.description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {/* 使用统计 — mono 键值行 */}
          <div className="label-tech flex flex-wrap gap-x-5 gap-y-1 !text-[9px]">
            <span>使用 <span className="num text-foreground">{skill.usageCount}</span></span>
            {skill.successCount != null && <span>成功 <span className="num text-foreground">{skill.successCount}</span></span>}
            <span>工具 <span className="num text-foreground">{skill.tools.length}</span></span>
            <span>示例 <span className="num text-foreground">{skill.examples.length}</span></span>
          </div>

          {/* 触发关键词 */}
          <div>
            <h4 className="label-tech mb-2 !text-[10px] text-foreground/75">触发关键词 · TRIGGERS</h4>
            <div className="flex flex-wrap gap-1.5">
              {skill.triggerKeywords.map((k) => (
                <span key={k} className="rounded-[3px] border px-1.5 py-px font-mono text-[10px] text-muted-foreground">{k}</span>
              ))}
            </div>
          </div>

          {/* 系统提示词 */}
          <div>
            <h4 className="label-tech mb-2 !text-[10px] text-foreground/75">系统提示词 · SYSTEM PROMPT</h4>
            {systemPrompt ? (
              <div className="rounded-md border bg-muted/30 p-4">
                <MarkdownView content={systemPrompt} />
              </div>
            ) : (
              <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">该技能未提供内置系统提示词</p>
            )}
          </div>

          {/* 执行步骤 */}
          <div>
            <h4 className="label-tech mb-2 !text-[10px] text-foreground/75">执行步骤 · PIPELINE</h4>
            {skill.steps.length > 0 ? (
              <ol className="divide-y rounded-md border">
                {skill.steps.map((step, i) => (
                  <li key={step.id} className="flex gap-3 px-3 py-2.5">
                    <span className="num w-6 shrink-0 pt-0.5 text-[10px] text-muted-foreground/70">{String(i + 1).padStart(2, '0')}</span>
                    <div className="min-w-0">
                      <div className="text-xs font-medium">{step.name}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <span className="rounded-[3px] border border-primary/40 px-1.5 py-px font-mono text-[9px] text-primary">{step.tool}</span>
                        {step.condition && <span className="text-[10px] text-muted-foreground">条件: {step.condition}</span>}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">无固定步骤, 由 LLM 自主规划</p>
            )}
          </div>

          {/* 工具列表 */}
          <div>
            <h4 className="label-tech mb-2 !text-[10px] text-foreground/75">可用工具 · TOOLS</h4>
            <div className="flex flex-wrap gap-1.5">
              {skill.tools.map((t) => (
                <span key={t} className="rounded-[3px] border px-1.5 py-px font-mono text-[10px] text-muted-foreground">{t}</span>
              ))}
            </div>
          </div>

          {/* 示例问题 */}
          <div>
            <h4 className="label-tech mb-2 !text-[10px] text-foreground/75">示例问题 · EXAMPLES</h4>
            <div className="space-y-2">
              {skill.examples.map((ex) => (
                <p key={ex} className="border-l-2 border-primary/40 pl-3 text-xs italic text-muted-foreground">
                  “{ex}”
                </p>
              ))}
            </div>
          </div>

          {/* 操作 */}
          <Button
            className="w-full gap-2"
            onClick={() => {
              navigate('qa', { skillId: skill.id });
              onClose();
            }}
          >
            <MessageSquare className="h-4 w-4" strokeWidth={1.75} />
            用此技能提问
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ============ 匹配测试器 ============

function SkillMatcher() {
  const [query, setQuery] = useState('');
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<MatchResponse | null>(null);
  const navigate = useAppStore((s) => s.navigate);

  const runTest = async () => {
    const q = query.trim();
    if (!q) {
      toast.error('请输入测试语句');
      return;
    }
    setTesting(true);
    setResult(null);
    try {
      const d = await api<MatchResponse>('/api/skills', { method: 'POST', body: JSON.stringify({ query: q }) });
      setResult(d);
      if (d.matches.length === 0) toast.info('没有技能命中该语句的关键词');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '匹配测试失败');
    } finally {
      setTesting(false);
    }
  };

  return (
    <section className="card-shadow rounded-lg border bg-card">
      <div className="flex items-center gap-3 border-b px-4 py-2.5">
        <span className="label-tech !text-[10px] text-foreground/75">匹配测试器 · ROUTER TEST</span>
        <span className="label-tech ml-auto !text-[9px]">KEYWORD MATCH</span>
      </div>
      <div className="space-y-3 p-4">
        <p className="text-[11px] text-muted-foreground">
          输入一句话, 实时查看将自动启用哪些技能 (基于触发关键词命中)。
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" strokeWidth={1.75} />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && runTest()}
              placeholder="例如: 比较 6M0J 和 7A5I 的结构差异"
              className="h-11 pl-9 text-xs sm:h-9"
              aria-label="技能匹配测试输入"
            />
          </div>
          <Button onClick={runTest} disabled={testing} className="h-11 gap-2 sm:h-9">
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Target className="h-4 w-4" strokeWidth={1.75} />}
            测试匹配
          </Button>
        </div>

        {result && (
          <div className="space-y-2 pt-1">
            <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs">
              <span className="label-tech !text-[9px]">INPUT </span>
              <HighlightedQuery query={result.query} keywords={result.matches.flatMap((m) => m.matchedKeywords)} />
            </div>
            {result.matches.length === 0 ? (
              <div className="label-tech flex min-h-[88px] items-center justify-center px-4 py-6 text-center !text-[10px] normal-case !tracking-[0.06em]">
                NO MATCH — 将使用通用问答模式
              </div>
            ) : (
              <div className="max-h-72 divide-y overflow-y-auto custom-scrollbar rounded-lg border">
                {result.matches.map((m) => (
                  <div key={m.skill.id} className="relative flex items-start gap-3 px-4 py-2.5 transition-colors hover:bg-accent/50">
                    <span className={cn('absolute inset-y-[9px] left-0 w-[2px]', categoryBar(m.skill.category))} aria-hidden />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-2">
                        <span className="text-[13px] font-medium leading-tight">{m.skill.name}</span>
                        <span className="label-tech !text-[9px]">{m.skill.category}</span>
                      </div>
                      <p className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">{m.skill.description}</p>
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {m.matchedKeywords.map((k) => (
                          <span key={k} className="rounded-[3px] border border-primary/40 px-1.5 py-px font-mono text-[9px] text-primary">{k}</span>
                        ))}
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1 pt-0.5">
                      <span className="num text-[11px] font-medium text-primary">命中 {m.score}</span>
                      <button
                        type="button"
                        onClick={() => navigate('qa', { skillId: m.skill.id })}
                        className="label-tech flex items-center gap-1 !text-[9px] !text-primary transition-opacity hover:opacity-70"
                      >
                        去提问 <ArrowRight className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

// ============ 主组件 ============

export function SkillsView() {
  const [data, setData] = useState<SkillsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [category, setCategory] = useState('all');
  const [selected, setSelected] = useState<SkillSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api<SkillsResponse>('/api/skills');
        if (cancelled) return;
        setData(d);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : '加载技能失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const categories = data?.categories ?? [];
  const skills = useMemo(() => {
    if (!data) return [];
    return category === 'all' ? data.skills : data.skills.filter((s) => s.category === category);
  }, [data, category]);

  /** 按类别分组 → 分组 Panel + 密集行 */
  const grouped = useMemo(() => {
    const map = new Map<string, SkillSummary[]>();
    for (const s of skills) {
      if (!map.has(s.category)) map.set(s.category, []);
      map.get(s.category)!.push(s);
    }
    const order = (data?.categories ?? []).map((c) => c.id);
    const ids = [...order.filter((id) => map.has(id)), ...[...map.keys()].filter((id) => !order.includes(id))];
    return ids.map((id) => {
      const list = map.get(id)!;
      return { id, label: list[0]?.categoryLabel ?? id, skills: list };
    });
  }, [skills, data]);

  return (
    <div className="animate-fade-in-up">
      {/* ===== Masthead — 坐标纸 + 模块代号 ===== */}
      <div className="grid-bg relative border-b">
        <div className="flex flex-wrap items-end justify-between gap-4 px-4 py-6 md:px-6">
          <div>
            <div className="label-tech !text-[10px]">Skills · 技能中心</div>
            <h1 className="font-display mt-1.5 text-[26px] font-semibold leading-none tracking-tight md:text-[30px]">
              技能中心
              <span className="title-accent">Expert Skills</span>
            </h1>
            <p className="mt-2.5 max-w-lg text-xs leading-relaxed text-muted-foreground">
              预设专家技能库 — 按触发关键词自动路由激活, 覆盖结构比较 · 文献综述 · 序列分析 · 实验方法 · 靶点与突变分析
            </p>
          </div>
          <div className="label-tech space-y-1.5 text-right !text-[10px]">
            <div className="flex items-center justify-end gap-2">
              <span className="status-dot" aria-hidden /> KEYWORD ROUTER ACTIVE
            </div>
            <div className="text-muted-foreground/60">
              {data ? `${data.total} SKILLS · ${data.categories.length} CATEGORIES` : 'LOADING…'}
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-4 md:p-6">
        {/* ===== 技能规模 StatCard — 领域色渐变图标 + 计数动画 ===== */}
        <div className="grid grid-cols-2 gap-2.5 sm:gap-3 md:grid-cols-3 [grid-auto-rows:1fr]">
          <StatCard
            title="技能总数"
            value={data?.total ?? 0}
            subtitle="预设专家技能 · 关键词自动路由"
            icon={<Sparkles className="h-3.5 w-3.5" />}
            gradient="from-[#c96442] to-[#a04e32]"
            accent="#c96442"
            loading={loading}
            delay={0}
            tooltip={`预设专家技能 ${data?.total ?? 0} 个 · ${data?.categories.length ?? 0} 分类`}
          />
          <StatCard
            title="覆盖分类"
            value={data?.categories.length ?? 0}
            subtitle="结构 · 文献 · 序列 · 方法 · 靶点"
            icon={<Layers className="h-3.5 w-3.5" />}
            gradient="from-[#6b7280] to-[#4b5563]"
            accent="#6b7280"
            loading={loading}
            delay={45}
          />
          <StatCard
            title="累计调用"
            value={data?.skills.reduce((sum, s) => sum + s.usageCount, 0) ?? 0}
            subtitle="历史技能调用次数 · 全库"
            icon={<Activity className="h-3.5 w-3.5" />}
            gradient="from-[#7c5cbf] to-[#5a3d99]"
            accent="#7c5cbf"
            loading={loading}
            delay={90}
            className="col-span-2 md:col-span-1"
          />
        </div>

        {/* 错误 */}
        {error && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4" role="alert">
            <div className="label-tech !text-[10px] !text-destructive">SKILLS LOAD FAILED</div>
            <p className="mt-1 text-sm text-destructive">{error}</p>
          </div>
        )}

        {/* 分类过滤 — mono 标签行 */}
        {!loading && !error && (
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="技能分类过滤">
            <button
              type="button"
              onClick={() => setCategory('all')}
              aria-pressed={category === 'all'}
              className={cn(
                'flex h-11 items-center rounded-[5px] border px-3 text-xs transition-colors sm:h-8',
                category === 'all'
                  ? 'border-primary/50 bg-accent font-medium text-accent-foreground'
                  : 'border-border text-muted-foreground hover:border-foreground/25 hover:text-foreground'
              )}
            >
              全部 <span className="num ml-1.5 text-[10px] opacity-70">{data?.total ?? 0}</span>
            </button>
            {categories.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setCategory(c.id)}
                aria-pressed={category === c.id}
                className={cn(
                  'flex h-11 items-center rounded-[5px] border px-3 text-xs transition-colors sm:h-8',
                  category === c.id
                    ? 'border-primary/50 bg-accent font-medium text-accent-foreground'
                    : 'border-border text-muted-foreground hover:border-foreground/25 hover:text-foreground'
                )}
              >
                {c.label} <span className="num ml-1.5 text-[10px] opacity-70">{c.count}</span>
              </button>
            ))}
          </div>
        )}

        {/* 技能目录 — 分组 Panel + 密集行 */}
        {loading ? (
          <section className="card-shadow rounded-lg border bg-card">
            <div className="flex items-center gap-3 border-b px-4 py-2.5">
              <span className="label-tech !text-[10px] text-foreground/75">技能目录 · CATALOG</span>
              <span className="label-tech ml-auto !text-[9px]">LOADING…</span>
            </div>
            <div className="divide-y">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="px-4 py-3">
                  <Skeleton className="shimmer h-4 w-36" />
                  <Skeleton className="shimmer mt-2 h-3 w-full max-w-md" />
                </div>
              ))}
            </div>
          </section>
        ) : (
          <div className={cn('grid gap-4', category === 'all' && 'xl:grid-cols-2')}>
            {grouped.map((cat) => (
              <section key={cat.id} className="card-shadow rounded-lg border bg-card">
                <div className="relative flex items-center gap-3 border-b px-4 py-2.5">
                  <span className={cn('absolute inset-y-[9px] left-0 w-[2px]', categoryBar(cat.id))} aria-hidden />
                  <span className="label-tech !text-[10px] text-foreground/75">{cat.label} · {categoryCode(cat.id)}</span>
                  <span className="label-tech ml-auto !text-[9px]">{cat.skills.length} SKILLS</span>
                </div>
                <div className="divide-y">
                  {cat.skills.map((s) => (
                    <SkillRow key={s.id} skill={s} onSelect={setSelected} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
        {!loading && !error && grouped.length === 0 && (
          <section className="rounded-lg border bg-card">
            <div className="label-tech flex min-h-[88px] items-center justify-center px-4 py-8 text-center !text-[10px] normal-case !tracking-[0.06em]">
              NO SKILLS — 该分类下暂无技能
            </div>
          </section>
        )}

        {/* 匹配测试器 */}
        <SkillMatcher />

        {/* 详情弹窗 */}
        <SkillDialog skill={selected} onClose={() => setSelected(null)} />
      </div>
    </div>
  );
}
