'use client';

/**
 * CryoAgent Pro — 系统设置
 * AI 配置 (连接测试) / 检索配置 (保存) / 外部服务 (内置代理) / 关于
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import {
  Atom, Bot, CheckCircle2, Cloud, ExternalLink, Info, Loader2, MessageSquare,
  Save, Search, Settings, ShieldCheck, SlidersHorizontal, XCircle, Zap,
} from 'lucide-react';

// ============ 类型定义 (API 契约) ============

interface AppConfig {
  defaultQaMode?: string;
  defaultSearchMode?: string;
  maxSources?: number;
  theme?: string;
  agentMaxSteps?: number;
  chunkSize?: number;
  chunkOverlap?: number;
  llmModel?: string;
}

interface ConfigResponse {
  config: AppConfig;
}

interface TestResponse {
  success: boolean;
  latencyMs: number;
  reply: string;
  tokensUsed?: number;
}

interface StatsTotals {
  literature: number;
  chunks: number;
  structures: number;
  qa: number;
  agentQa: number;
  skills: number;
  alignments: number;
  links: number;
  notes: number;
  users: number;
  searches: number;
}

// ============ 外部服务数据 ============

const EXTERNAL_SERVICES = [
  {
    name: 'RCSB PDB',
    desc: '蛋白质结构数据库 · 结构搜索、详情、坐标文件 (mmCIF/PDB) 均由服务端代理拉取并缓存到本地 SQLite。',
    endpoints: ['/api/structures', '/api/structure/[id]', '/api/structure/[id]/pdb'],
    links: [
      { label: 'rcsb.org', url: 'https://www.rcsb.org' },
      { label: 'data.rcsb.org', url: 'https://data.rcsb.org' },
    ],
  },
  {
    name: 'UniProt',
    desc: '蛋白质序列与功能注释库 · 用于序列提取、结构关联与理化分析的序列来源。',
    endpoints: ['/api/uniprot/[id]', '/api/sequence/analyze'],
    links: [{ label: 'uniprot.org', url: 'https://www.uniprot.org' }],
  },
  {
    name: 'AlphaFold DB',
    desc: 'DeepMind 预测结构数据库 · 结构详情页可加载 AlphaFold 预测模型进行 3D 对比查看。',
    endpoints: ['/api/structure/[id]/pdb?source=alphafold'],
    links: [{ label: 'alphafold.ebi.ac.uk', url: 'https://alphafold.ebi.ac.uk' }],
  },
];

// ============ 主组件 ============

export function SettingsView() {
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [totals, setTotals] = useState<StatsTotals | null>(null);

  // 检索配置表单
  const [defaultSearchMode, setDefaultSearchMode] = useState('hybrid');
  const [maxSources, setMaxSources] = useState('6');
  const [agentMaxSteps, setAgentMaxSteps] = useState('6');
  const [chunkSize, setChunkSize] = useState('480');
  const [chunkOverlap, setChunkOverlap] = useState('50');
  const [saving, setSaving] = useState(false);

  // 连接测试
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ latencyMs: number; reply: string } | null>(null);
  const [testError, setTestError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [configR, statsR] = await Promise.all([
          api<ConfigResponse>('/api/config'),
          api<{ totals: StatsTotals }>('/api/stats'),
        ]);
        if (cancelled) return;
        setConfig(configR.config);
        setTotals(statsR.totals);
        setDefaultSearchMode(String(configR.config.defaultSearchMode ?? 'hybrid'));
        setMaxSources(String(configR.config.maxSources ?? 6));
        setAgentMaxSteps(String(configR.config.agentMaxSteps ?? 6));
        setChunkSize(String(configR.config.chunkSize ?? 480));
        setChunkOverlap(String(configR.config.chunkOverlap ?? 50));
      } catch {
        if (!cancelled) toast.error('加载配置失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const saveConfig = async () => {
    setSaving(true);
    try {
      await api<{ success: boolean }>('/api/config', {
        method: 'POST',
        body: JSON.stringify({
          defaultSearchMode,
          maxSources: parseInt(maxSources, 10) || 6,
          agentMaxSteps: parseInt(agentMaxSteps, 10) || 6,
          chunkSize: parseInt(chunkSize, 10) || 480,
          chunkOverlap: parseInt(chunkOverlap, 10) || 50,
        }),
      });
      toast.success('检索配置已保存');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    setTestError('');
    try {
      const d = await api<TestResponse>('/api/config', { method: 'PUT' });
      setTestResult({ latencyMs: d.latencyMs, reply: d.reply });
      toast.success(`AI 连接正常 · 延迟 ${d.latencyMs}ms`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '连接测试失败';
      setTestError(msg);
      toast.error(`AI 连接失败: ${msg}`);
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-5xl space-y-4 p-4 md:p-6">
        <Skeleton className="h-10 w-56 rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl space-y-4 p-4 md:space-y-6 md:p-6">
      {/* 页头 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600 text-white shadow-lg shadow-teal-500/20">
          <Settings className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-bold tracking-tight">系统设置</h2>
          <p className="text-xs text-muted-foreground">AI 连接 · 检索参数 · 外部服务 · 平台信息</p>
        </div>
      </div>

      <Tabs defaultValue="ai" className="space-y-4">
        <TabsList className="h-auto w-full flex-wrap justify-start gap-1 sm:w-auto">
          <TabsTrigger value="ai" className="gap-1.5"><Bot className="h-3.5 w-3.5" />AI 配置</TabsTrigger>
          <TabsTrigger value="retrieval" className="gap-1.5"><SlidersHorizontal className="h-3.5 w-3.5" />检索配置</TabsTrigger>
          <TabsTrigger value="services" className="gap-1.5"><Cloud className="h-3.5 w-3.5" />外部服务</TabsTrigger>
          <TabsTrigger value="about" className="gap-1.5"><Info className="h-3.5 w-3.5" />关于</TabsTrigger>
        </TabsList>

        {/* ============ AI 配置 ============ */}
        <TabsContent value="ai" className="space-y-4">
          <Card className="p-4 md:p-6">
            <CardHeader className="mb-4 p-0">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Bot className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                AI 模型信息
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 p-0">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border bg-muted/40 p-3">
                  <div className="text-[11px] text-muted-foreground">当前模型</div>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="font-mono text-base font-bold text-teal-700 dark:text-teal-300">
                      {config?.llmModel ?? 'glm-4.6'}
                    </span>
                    <Badge variant="secondary" className="text-[10px]">服务端调用</Badge>
                  </div>
                </div>
                <div className="rounded-lg border bg-muted/40 p-3">
                  <div className="text-[11px] text-muted-foreground">默认问答模式</div>
                  <div className="mt-1 flex items-center gap-2 text-sm font-medium">
                    <MessageSquare className="h-3.5 w-3.5 text-teal-600 dark:text-teal-400" />
                    {config?.defaultQaMode === 'agent' ? 'Agent 工具调用' : config?.defaultQaMode === 'direct' ? '直接对话' : 'RAG 检索增强'}
                  </div>
                </div>
              </div>
              <p className="flex items-start gap-2 text-[11px] leading-relaxed text-muted-foreground">
                <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                LLM 通过 z-ai-web-dev-sdk 在服务端调用, API 凭证不经过浏览器; 流式输出经由 SSE 推送至前端。
              </p>
            </CardContent>
          </Card>

          <Card className="p-4 md:p-6">
            <CardHeader className="mb-4 p-0">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Zap className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                连接测试
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 p-0">
              <Button onClick={testConnection} disabled={testing} className="gap-2">
                {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
                {testing ? '测试中…' : '测试 AI 连接'}
              </Button>

              {testResult && (
                <div className="flex items-start gap-3 rounded-xl border border-emerald-500/40 bg-emerald-500/5 p-4">
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                  <div className="space-y-1 text-sm">
                    <p className="font-medium text-emerald-700 dark:text-emerald-300">连接成功</p>
                    <p className="text-xs text-muted-foreground">
                      延迟 <span className="font-mono font-semibold text-emerald-700 dark:text-emerald-300">{testResult.latencyMs}ms</span>
                      · 模型回复: <span className="font-mono">{testResult.reply}</span>
                    </p>
                  </div>
                </div>
              )}

              {testError && (
                <div className="flex items-start gap-3 rounded-xl border border-rose-500/40 bg-rose-500/5 p-4">
                  <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-rose-600 dark:text-rose-400" />
                  <div className="space-y-1 text-sm">
                    <p className="font-medium text-rose-700 dark:text-rose-300">连接失败</p>
                    <p className="break-all text-xs text-muted-foreground">{testError}</p>
                    <p className="text-[11px] text-muted-foreground/70">常见原因: 上游限流 (429) / 凭证失效 / 网络中断, 稍后可重试。</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ============ 检索配置 ============ */}
        <TabsContent value="retrieval" className="space-y-4">
          <Card className="p-4 md:p-6">
            <CardHeader className="mb-4 p-0">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Search className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                检索与 Agent 参数
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 p-0">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="cfg-mode" className="text-xs text-muted-foreground">默认检索模式</Label>
                  <Select value={defaultSearchMode} onValueChange={setDefaultSearchMode}>
                    <SelectTrigger id="cfg-mode" aria-label="默认检索模式"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="hybrid">混合检索 (BM25 + 向量 RRF)</SelectItem>
                      <SelectItem value="bm25">BM25 关键词</SelectItem>
                      <SelectItem value="vector">TF-IDF 向量余弦</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="cfg-sources" className="text-xs text-muted-foreground">引用来源上限 (maxSources)</Label>
                  <Input
                    id="cfg-sources"
                    type="number"
                    min={1}
                    max={20}
                    value={maxSources}
                    onChange={(e) => setMaxSources(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="cfg-steps" className="text-xs text-muted-foreground">Agent 最大步数</Label>
                  <Input
                    id="cfg-steps"
                    type="number"
                    min={1}
                    max={20}
                    value={agentMaxSteps}
                    onChange={(e) => setAgentMaxSteps(e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">工具调用循环上限, 防止无限执行</p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="cfg-chunk" className="text-xs text-muted-foreground">分块大小 (字符)</Label>
                  <Input
                    id="cfg-chunk"
                    type="number"
                    min={100}
                    max={2000}
                    step={20}
                    value={chunkSize}
                    onChange={(e) => setChunkSize(e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">对新上传文献生效</p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="cfg-overlap" className="text-xs text-muted-foreground">分块重叠 (字符)</Label>
                  <Input
                    id="cfg-overlap"
                    type="number"
                    min={0}
                    max={500}
                    step={10}
                    value={chunkOverlap}
                    onChange={(e) => setChunkOverlap(e.target.value)}
                  />
                </div>
              </div>

              <div className="flex items-center gap-3 border-t pt-4">
                <Button onClick={saveConfig} disabled={saving} className="gap-2">
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  保存配置
                </Button>
                <p className="text-[11px] text-muted-foreground">立即生效 · 用于后续问答检索与文档解析</p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ============ 外部服务 ============ */}
        <TabsContent value="services" className="space-y-4">
          <Card className="border-teal-500/30 bg-teal-500/5 p-4 text-xs leading-relaxed text-teal-800 dark:text-teal-200">
            <div className="flex items-start gap-2">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
            </div>
            <div>
              外部生物信息学服务全部通过<b>内置服务端代理</b>访问: 浏览器仅与本项目 API 通信, 由 Next.js 服务端转发请求并缓存结果 (SQLite), 避免跨域与密钥泄露。
            </div>
          </Card>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {EXTERNAL_SERVICES.map((svc) => (
              <Card key={svc.name} className="flex flex-col p-4 transition-colors hover:border-teal-500/40">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-sm">{svc.name}</CardTitle>
                  <Badge className="gap-1 border-emerald-500/40 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/10 dark:text-emerald-300">
                    <CheckCircle2 className="h-3 w-3" />内置代理
                  </Badge>
                </div>
                <p className="mt-2 flex-1 text-xs leading-relaxed text-muted-foreground">{svc.desc}</p>
                <div className="mt-3 space-y-1.5 border-t pt-3">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">代理端点</div>
                  {svc.endpoints.map((ep) => (
                    <div key={ep} className="rounded bg-muted px-2 py-1 font-mono text-[10px]">{ep}</div>
                  ))}
                  <div className="pt-1">
                    {svc.links.map((l) => (
                      <a
                        key={l.url}
                        href={l.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 pr-3 text-[11px] text-teal-600 hover:underline dark:text-teal-400"
                      >
                        <ExternalLink className="h-3 w-3" />{l.label}
                      </a>
                    ))}
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </TabsContent>

        {/* ============ 关于 ============ */}
        <TabsContent value="about" className="space-y-4">
          <Card className="p-4 md:p-6">
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-500 to-emerald-600 text-white shadow-lg shadow-teal-500/20">
                <Atom className="h-6 w-6" />
              </div>
              <div>
                <h3 className="text-base font-bold">CryoAgent Pro</h3>
                <p className="text-xs text-muted-foreground">蛋白质结构智能分析平台 · v2.0.0 · Next.js 重构版</p>
              </div>
              <div className="ml-auto flex flex-col items-end gap-1 text-[11px] text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                  </span>
                  系统在线
                </span>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-1.5">
              {['Next.js 16', 'TypeScript 5', 'Tailwind CSS 4', 'shadcn/ui', 'Prisma + SQLite', 'Recharts', '3Dmol.js', 'z-ai LLM', 'BM25 + 向量混合检索'].map((t) => (
                <Badge key={t} variant="secondary" className="font-normal">{t}</Badge>
              ))}
            </div>
          </Card>

          <Card className="p-4 md:p-6">
            <CardHeader className="mb-3 p-0">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Info className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                重构说明
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 p-0 text-xs leading-relaxed text-muted-foreground">
              <p>
                本平台由开源项目 <span className="font-mono text-foreground">CryoAgent</span> (Flask + Python + Vue3, 约 74k 行) 完整重构为
                <span className="font-medium text-foreground"> Next.js 16 全栈单页应用</span>, 保留全部核心能力:
              </p>
              <ul className="list-disc space-y-1 pl-5">
                <li>RAG 混合检索问答 (SSE 流式) + Agent 工具调用 (11 个工具)</li>
                <li>文献 PDF 解析分块索引 · 结构浏览器 (RCSB/AlphaFold) 与 3D 查看</li>
                <li>知识图谱 (邻域/路径) · NW/SW 序列比对 · 技能系统 (14 个)</li>
                <li>RAG 评估与监控 · 用户认证 · 配置管理</li>
              </ul>
              <p>
                并新增: <span className="font-medium text-teal-700 dark:text-teal-300">序列理化分析</span> (蛋白质/核酸全套指标)、
                多矩阵比对、知识图谱路径发现、接口文档在线调试等特性。
              </p>
            </CardContent>
          </Card>

          <Card className="p-4 md:p-6">
            <CardHeader className="mb-3 p-0">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Atom className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                数据规模
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {totals ? (
                <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
                  {[
                    { label: '文献', value: totals.literature },
                    { label: '文本分块', value: totals.chunks },
                    { label: '结构', value: totals.structures },
                    { label: '问答', value: totals.qa },
                    { label: 'Agent 问答', value: totals.agentQa },
                    { label: '比对任务', value: totals.alignments },
                    { label: '技能', value: totals.skills },
                    { label: '结构关联', value: totals.links },
                    { label: '笔记', value: totals.notes },
                    { label: '用户', value: totals.users },
                    { label: '搜索', value: totals.searches },
                  ].map((s) => (
                    <div key={s.label} className={cn('rounded-lg border bg-muted/40 p-2.5 text-center')}>
                      <div className="text-base font-bold tabular-nums">{s.value.toLocaleString()}</div>
                      <div className="text-[10px] text-muted-foreground">{s.label}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">统计数据加载中…</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
