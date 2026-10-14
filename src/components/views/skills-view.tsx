'use client';

/**
 * CryoAgent Pro — 技能中心
 * 14 个预设专家技能: 分类浏览 / 详情弹窗 (系统提示词 + 步骤 + 工具) / 关键词匹配测试器
 */

import { useEffect, useMemo, useState } from 'react';
import { useAppStore, api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { DEFAULT_SKILLS } from '@/lib/skills';
import { MarkdownView } from '@/components/markdown-view';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import {
  ArrowRight, BadgeCheck, Loader2, MessageSquare, Search, Sparkles, Target, TrendingUp, Wrench,
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

// ============ 分类配色 ============

const CATEGORY_CLASSES: Record<string, string> = {
  structure: 'border-teal-500/30 bg-teal-500/10 text-teal-700 dark:text-teal-300',
  literature: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  sequence: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  methodology: 'border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300',
  design: 'border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-300',
  visualization: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300',
  target: 'border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300',
  mutation: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300',
  knowledge: 'border-lime-500/30 bg-lime-500/10 text-lime-700 dark:text-lime-300',
};

function categoryClass(category: string): string {
  return CATEGORY_CLASSES[category] ?? 'border-zinc-500/30 bg-zinc-500/10 text-zinc-600 dark:text-zinc-400';
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
          <mark key={i} className="rounded bg-emerald-500/20 px-0.5 font-semibold text-emerald-700 dark:text-emerald-300">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </span>
  );
}

// ============ 技能卡片 ============

function SkillCard({ skill, onSelect }: { skill: SkillSummary; onSelect: (s: SkillSummary) => void }) {
  const shownKeywords = skill.triggerKeywords.slice(0, 5);
  const rest = skill.triggerKeywords.length - shownKeywords.length;
  return (
    <Card
      className="group cursor-pointer p-4 transition-all hover:border-teal-500/50 hover:shadow-md hover:shadow-teal-500/5"
      onClick={() => onSelect(skill)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(skill)}
      aria-label={`查看技能 ${skill.name}`}
    >
      <div className="flex items-start justify-between gap-2">
        <CardTitle className="text-sm leading-snug">{skill.name}</CardTitle>
        <span className={cn('shrink-0 rounded-full border px-2 py-0.5 text-[10px]', categoryClass(skill.category))}>
          {skill.categoryLabel}
        </span>
      </div>
      <p className="mt-2 line-clamp-2 min-h-[32px] text-xs text-muted-foreground">{skill.description}</p>

      <div className="mt-3 flex flex-wrap gap-1">
        {shownKeywords.map((k) => (
          <span key={k} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{k}</span>
        ))}
        {rest > 0 && <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">+{rest}</span>}
      </div>

      <div className="mt-3 flex items-center gap-3 border-t pt-2.5 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1"><Wrench className="h-3 w-3" />{skill.tools.length} 工具</span>
        <span className="flex items-center gap-1"><TrendingUp className="h-3 w-3" />{skill.usageCount} 次使用</span>
        <ArrowRight className="ml-auto h-3.5 w-3.5 text-teal-600 opacity-0 transition-opacity group-hover:opacity-100 dark:text-teal-400" />
      </div>
    </Card>
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
            <span className={cn('rounded-full border px-2 py-0.5 text-[10px]', categoryClass(skill.category))}>
              {skill.categoryLabel}
            </span>
            {skill.isBuiltin && (
              <Badge variant="secondary" className="gap-1 font-normal">
                <BadgeCheck className="h-3 w-3 text-emerald-600" />内置
              </Badge>
            )}
          </div>
          <DialogDescription className="text-xs leading-relaxed">{skill.description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {/* 使用统计 */}
          <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5"><TrendingUp className="h-3.5 w-3.5 text-teal-600 dark:text-teal-400" />使用 {skill.usageCount} 次</span>
            {skill.successCount != null && <span className="flex items-center gap-1.5"><BadgeCheck className="h-3.5 w-3.5 text-emerald-600" />成功 {skill.successCount} 次</span>}
            <span className="flex items-center gap-1.5"><Wrench className="h-3.5 w-3.5" />{skill.tools.length} 个工具</span>
            <span className="flex items-center gap-1.5"><Sparkles className="h-3.5 w-3.5" />{skill.examples.length} 个示例</span>
          </div>

          {/* 触发关键词 */}
          <div>
            <h4 className="mb-2 text-xs font-semibold">触发关键词</h4>
            <div className="flex flex-wrap gap-1.5">
              {skill.triggerKeywords.map((k) => (
                <span key={k} className="rounded-full border border-teal-500/30 bg-teal-500/10 px-2 py-0.5 text-[11px] text-teal-700 dark:text-teal-300">{k}</span>
              ))}
            </div>
          </div>

          {/* 系统提示词 */}
          <div>
            <h4 className="mb-2 text-xs font-semibold">系统提示词</h4>
            {systemPrompt ? (
              <div className="rounded-xl border bg-muted/30 p-4">
                <MarkdownView content={systemPrompt} />
              </div>
            ) : (
              <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">该技能未提供内置系统提示词</p>
            )}
          </div>

          {/* 执行步骤 */}
          <div>
            <h4 className="mb-2 text-xs font-semibold">执行步骤</h4>
            {skill.steps.length > 0 ? (
              <ol className="relative ml-2.5 space-y-4 border-l-2 border-teal-500/25 pl-6">
                {skill.steps.map((step, i) => (
                  <li key={step.id} className="relative">
                    <span className="absolute -left-[34px] top-0 flex h-5 w-5 items-center justify-center rounded-full bg-teal-600 text-[10px] font-bold text-white">
                      {i + 1}
                    </span>
                    <div className="text-xs font-medium">{step.name}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">{step.tool}</span>
                      {step.condition && <span className="text-[10px] text-muted-foreground">条件: {step.condition}</span>}
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">无固定步骤, 由 LLM 自主规划</p>
            )}
          </div>

          {/* 工具列表 */}
          <div>
            <h4 className="mb-2 text-xs font-semibold">可用工具</h4>
            <div className="flex flex-wrap gap-1.5">
              {skill.tools.map((t) => (
                <span key={t} className="rounded border bg-muted/60 px-2 py-1 font-mono text-[11px]">{t}</span>
              ))}
            </div>
          </div>

          {/* 示例问题 */}
          <div>
            <h4 className="mb-2 text-xs font-semibold">示例问题</h4>
            <div className="space-y-1.5">
              {skill.examples.map((ex) => (
                <p key={ex} className="rounded-lg border-l-2 border-emerald-500/50 bg-muted/30 px-3 py-2 text-xs italic text-muted-foreground">
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
            <MessageSquare className="h-4 w-4" />
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
    <Card className="p-4 md:p-6">
      <CardHeader className="mb-3 p-0">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Target className="h-4 w-4 text-teal-600 dark:text-teal-400" />
          技能匹配测试器
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 p-0">
        <p className="text-[11px] text-muted-foreground">
          输入一句话, 实时查看将自动启用哪些技能 (基于触发关键词命中)。
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && runTest()}
              placeholder="例如: 比较 6M0J 和 7A5I 的结构差异"
              className="pl-9"
              aria-label="技能匹配测试输入"
            />
          </div>
          <Button onClick={runTest} disabled={testing} className="gap-2">
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Target className="h-4 w-4" />}
            测试匹配
          </Button>
        </div>

        {result && (
          <div className="space-y-2 pt-1">
            <div className="rounded-lg border bg-muted/30 px-3 py-2 text-xs">
              <span className="text-muted-foreground">输入: </span>
              <HighlightedQuery query={result.query} keywords={result.matches.flatMap((m) => m.matchedKeywords)} />
            </div>
            {result.matches.length === 0 ? (
              <p className="rounded-lg border border-dashed p-3 text-center text-xs text-muted-foreground">
                无命中技能, 将使用通用问答模式
              </p>
            ) : (
              <div className="max-h-72 space-y-1.5 overflow-y-auto custom-scrollbar pr-1">
                {result.matches.map((m) => (
                  <div
                    key={m.skill.id}
                    className="flex items-start gap-2.5 rounded-lg border p-2.5 transition-colors hover:border-teal-500/40"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-xs font-semibold">{m.skill.name}</span>
                        <span className={cn('rounded-full border px-1.5 py-0.5 text-[10px]', categoryClass(m.skill.category))}>
                          {m.skill.category}
                        </span>
                      </div>
                      <p className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">{m.skill.description}</p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {m.matchedKeywords.map((k) => (
                          <span key={k} className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-300">
                            {k}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <Badge variant="secondary" className="tabular-nums">命中 {m.score}</Badge>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 gap-1 px-2 text-[11px] text-teal-600 dark:text-teal-400"
                        onClick={() => navigate('qa', { skillId: m.skill.id })}
                      >
                        去提问<ArrowRight className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
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

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 p-4 md:space-y-6 md:p-6">
      {/* 页头 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600 text-white shadow-lg shadow-teal-500/20">
          <Sparkles className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-bold tracking-tight">技能中心</h2>
          <p className="text-xs text-muted-foreground">
            {data ? `${data.total} 个预设专家技能 · 提问时按关键词自动激活` : '预设专家技能 · 提问时按关键词自动激活'}
          </p>
        </div>
      </div>

      {/* 错误 */}
      {error && <Card className="border-rose-500/40 bg-rose-500/5 p-4 text-sm text-rose-600 dark:text-rose-400">{error}</Card>}

      {/* 分类过滤 */}
      {!loading && !error && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setCategory('all')}
            className={cn(
              'rounded-full border px-3 py-1.5 text-xs transition-colors',
              category === 'all'
                ? 'border-teal-500 bg-teal-600 font-medium text-white'
                : 'border-border text-muted-foreground hover:border-teal-500/40 hover:text-foreground'
            )}
          >
            全部 <span className="ml-1 tabular-nums opacity-80">{data?.total ?? 0}</span>
          </button>
          {categories.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setCategory(c.id)}
              className={cn(
                'rounded-full border px-3 py-1.5 text-xs transition-colors',
                category === c.id
                  ? 'border-teal-500 bg-teal-600 font-medium text-white'
                  : 'border-border text-muted-foreground hover:border-teal-500/40 hover:text-foreground'
              )}
            >
              {c.label} <span className="ml-1 tabular-nums opacity-80">{c.count}</span>
            </button>
          ))}
        </div>
      )}

      {/* 技能卡片网格 */}
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[190px] rounded-xl" />)}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {skills.map((s) => (
            <SkillCard key={s.id} skill={s} onSelect={setSelected} />
          ))}
        </div>
      )}
      {!loading && !error && skills.length === 0 && (
        <Card className="flex h-40 flex-col items-center justify-center gap-2 border-dashed p-4 text-sm text-muted-foreground">
          <Sparkles className="h-8 w-8 opacity-30" />
          该分类下暂无技能
        </Card>
      )}

      {/* 匹配测试器 */}
      <SkillMatcher />

      {/* 详情弹窗 */}
      <SkillDialog skill={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
