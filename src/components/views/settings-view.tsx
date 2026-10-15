'use client';

/**
 * CryoAgent Pro — 系统设置 (BENCH 设计系统)
 * AI 运行时 (连接测试) / 检索与 Agent 参数 / 外部服务代理 / 系统信息与数据规模
 * 结构: grid-bg masthead + 配置 Panel 组 + label-tech 字段标签 + mono 键值行
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import {
  Bot, Cloud, ExternalLink, Info, Loader2, Save, ShieldCheck, SlidersHorizontal, Zap,
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

// ============ BENCH 基础组件 ============

/** 面板骨架 — 统一 hairline 分区容器 */
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

/** mono 短码 tag — outline 语义色 */
function MiniTag({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex shrink-0 items-center rounded-[3px] border px-1.5 py-px font-mono text-[9px] font-medium tracking-wide', className)}>
      {children}
    </span>
  );
}

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

  /* ===== Masthead — 坐标纸 + 编辑性标题 ===== */
  const masthead = (
    <div className="grid-bg border-b">
      <div className="flex flex-wrap items-end justify-between gap-4 px-4 py-6 md:px-6">
        <div>
          <div className="label-tech !text-[10px]">Config · 系统设置</div>
          <h1 className="font-display mt-1.5 text-[26px] font-semibold leading-none tracking-tight md:text-[30px]">
            系统设置
            <span className="title-accent">
              Configuration
            </span>
          </h1>
          <p className="mt-2.5 max-w-lg text-xs leading-relaxed text-muted-foreground">
            平台运行参数 — AI 运行时 · 检索与 Agent 参数 · 外部服务代理 · 数据规模
          </p>
        </div>
        <div className="label-tech space-y-1.5 text-right !text-[10px]">
          <div className="flex items-center justify-end gap-2">
            <span className="status-dot" aria-hidden />
            {loading ? 'CONFIG LOADING' : 'CONFIG LOADED'}
          </div>
          <div className="text-muted-foreground/60">PERSIST /api/config · SQLITE</div>
        </div>
      </div>
    </div>
  );

  if (loading) {
    return (
      <div className="animate-fade-in-up">
        {masthead}
        <div className="space-y-4 p-4 md:p-6">
          <Skeleton className="shimmer h-9 w-full max-w-md rounded-lg" />
          <Skeleton className="shimmer h-48 w-full rounded-lg" />
          <Skeleton className="shimmer h-64 w-full rounded-lg" />
        </div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in-up">
      {masthead}

      <div className="space-y-4 p-4 md:p-6">
        <Tabs defaultValue="ai" className="space-y-4">
          <TabsList className="h-auto w-full flex-wrap justify-start gap-1 rounded-lg border bg-card p-1 sm:w-auto">
            <TabsTrigger value="ai" className="h-7 gap-1.5 px-3 text-xs data-[state=active]:!bg-accent data-[state=active]:!shadow-none dark:data-[state=active]:!bg-accent dark:data-[state=active]:!border-transparent">
              <Bot className="h-3.5 w-3.5" strokeWidth={1.75} />AI 配置
            </TabsTrigger>
            <TabsTrigger value="retrieval" className="h-7 gap-1.5 px-3 text-xs data-[state=active]:!bg-accent data-[state=active]:!shadow-none dark:data-[state=active]:!bg-accent dark:data-[state=active]:!border-transparent">
              <SlidersHorizontal className="h-3.5 w-3.5" strokeWidth={1.75} />检索配置
            </TabsTrigger>
            <TabsTrigger value="services" className="h-7 gap-1.5 px-3 text-xs data-[state=active]:!bg-accent data-[state=active]:!shadow-none dark:data-[state=active]:!bg-accent dark:data-[state=active]:!border-transparent">
              <Cloud className="h-3.5 w-3.5" strokeWidth={1.75} />外部服务
            </TabsTrigger>
            <TabsTrigger value="about" className="h-7 gap-1.5 px-3 text-xs data-[state=active]:!bg-accent data-[state=active]:!shadow-none dark:data-[state=active]:!bg-accent dark:data-[state=active]:!border-transparent">
              <Info className="h-3.5 w-3.5" strokeWidth={1.75} />关于
            </TabsTrigger>
          </TabsList>

          {/* ============ AI 配置 ============ */}
          <TabsContent value="ai" className="space-y-4">
            <Panel>
              <PanelHead title="运行时模型 · LLM RUNTIME" hint="SERVER-SIDE" />
              <div className="divide-y">
                <div className="flex items-baseline justify-between gap-4 px-4 py-[9px]">
                  <span className="text-[11px] text-muted-foreground">当前模型</span>
                  <span className="flex items-center gap-2">
                    <span className="num text-[13px] font-semibold text-primary">{config?.llmModel ?? 'glm-4.6'}</span>
                    <MiniTag className="border-border text-muted-foreground">服务端调用</MiniTag>
                  </span>
                </div>
                <div className="flex items-baseline justify-between gap-4 px-4 py-[9px]">
                  <span className="text-[11px] text-muted-foreground">默认问答模式</span>
                  <span className="text-xs font-medium">
                    {config?.defaultQaMode === 'agent' ? 'Agent 工具调用' : config?.defaultQaMode === 'direct' ? '直接对话' : 'RAG 检索增强'}
                  </span>
                </div>
                <div className="flex items-baseline justify-between gap-4 px-4 py-[9px]">
                  <span className="text-[11px] text-muted-foreground">调用通道</span>
                  <span className="font-mono text-[11px]">z-ai-web-dev-sdk</span>
                </div>
                <div className="flex items-baseline justify-between gap-4 px-4 py-[9px]">
                  <span className="text-[11px] text-muted-foreground">流式输出</span>
                  <span className="font-mono text-[11px] text-muted-foreground">SSE · text/event-stream</span>
                </div>
              </div>
              <div className="flex items-start gap-2 border-t px-4 py-2.5">
                <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" strokeWidth={1.75} aria-hidden />
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  LLM 在服务端调用, API 凭证不经过浏览器; 流式输出经由 SSE 推送至前端。
                </p>
              </div>
            </Panel>

            <Panel>
              <PanelHead title="连接测试 · PING" hint="PUT /api/config" />
              <div className="space-y-3 p-4">
                <Button onClick={testConnection} disabled={testing} className="h-9">
                  {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" strokeWidth={1.75} />}
                  {testing ? '测试中…' : '测试 AI 连接'}
                </Button>

                {testResult && (
                  <div className="rounded-lg border border-primary/40 bg-accent/25 p-3" role="status">
                    <div className="label-tech !text-primary">
                      LINK OK · <span className="num">{testResult.latencyMs}ms</span>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      模型回复: <span className="font-mono text-foreground">{testResult.reply}</span>
                    </p>
                  </div>
                )}

                {testError && (
                  <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3" role="alert">
                    <div className="label-tech !text-destructive">LINK FAILED</div>
                    <p className="mt-1 break-all text-xs text-destructive">{testError}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground/70">常见原因: 上游限流 (429) / 凭证失效 / 网络中断, 稍后可重试。</p>
                  </div>
                )}
              </div>
            </Panel>
          </TabsContent>

          {/* ============ 检索配置 ============ */}
          <TabsContent value="retrieval" className="space-y-4">
            <Panel>
              <PanelHead title="检索与 Agent 参数 · RETRIEVAL" hint="POST /api/config" />
              <div className="p-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="cfg-mode" className="label-tech">默认检索模式 · MODE</Label>
                    <Select value={defaultSearchMode} onValueChange={setDefaultSearchMode}>
                      <SelectTrigger id="cfg-mode" aria-label="默认检索模式" className="h-9 w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="hybrid">混合检索 (BM25 + 向量 RRF)</SelectItem>
                        <SelectItem value="bm25">BM25 关键词</SelectItem>
                        <SelectItem value="vector">TF-IDF 向量余弦</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="label-tech !text-[9px] normal-case !tracking-normal">问答与评估的默认检索通道</p>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="cfg-sources" className="label-tech">引用来源上限 · MAX SOURCES</Label>
                    <Input
                      id="cfg-sources"
                      type="number"
                      min={1}
                      max={20}
                      value={maxSources}
                      onChange={(e) => setMaxSources(e.target.value)}
                      className="h-9 num"
                    />
                    <p className="label-tech !text-[9px] normal-case !tracking-normal">单次问答引用的文献分块数上限</p>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="cfg-steps" className="label-tech">Agent 最大步数 · MAX STEPS</Label>
                    <Input
                      id="cfg-steps"
                      type="number"
                      min={1}
                      max={20}
                      value={agentMaxSteps}
                      onChange={(e) => setAgentMaxSteps(e.target.value)}
                      className="h-9 num"
                    />
                    <p className="label-tech !text-[9px] normal-case !tracking-normal">工具调用循环上限, 防止无限执行</p>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="cfg-chunk" className="label-tech">分块大小 · CHUNK SIZE</Label>
                    <Input
                      id="cfg-chunk"
                      type="number"
                      min={100}
                      max={2000}
                      step={20}
                      value={chunkSize}
                      onChange={(e) => setChunkSize(e.target.value)}
                      className="h-9 num"
                    />
                    <p className="label-tech !text-[9px] normal-case !tracking-normal">字符 · 对新上传文献生效</p>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="cfg-overlap" className="label-tech">分块重叠 · CHUNK OVERLAP</Label>
                    <Input
                      id="cfg-overlap"
                      type="number"
                      min={0}
                      max={500}
                      step={10}
                      value={chunkOverlap}
                      onChange={(e) => setChunkOverlap(e.target.value)}
                      className="h-9 num"
                    />
                    <p className="label-tech !text-[9px] normal-case !tracking-normal">字符 · 相邻分块重叠区</p>
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3 border-t px-4 py-3">
                <Button onClick={saveConfig} disabled={saving} className="h-9">
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" strokeWidth={1.75} />}
                  保存配置
                </Button>
                <p className="label-tech !text-[9px] normal-case !tracking-normal">立即生效 · 用于后续问答检索与文档解析</p>
              </div>
            </Panel>
          </TabsContent>

          {/* ============ 外部服务 ============ */}
          <TabsContent value="services" className="space-y-4">
            <Panel>
              <PanelHead title="代理架构 · PROXY POLICY" />
              <div className="flex items-start gap-2 p-4">
                <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" strokeWidth={1.75} aria-hidden />
                <p className="text-xs leading-relaxed text-muted-foreground">
                  外部生物信息学服务全部通过<b className="text-foreground">内置服务端代理</b>访问: 浏览器仅与本项目 API 通信,
                  由 Next.js 服务端转发请求并缓存结果 (SQLite), 避免跨域与密钥泄露。
                </p>
              </div>
            </Panel>

            <Panel>
              <PanelHead title="外部服务 · UPSTREAM" hint={`${EXTERNAL_SERVICES.length} SOURCES`} />
              <div className="divide-y">
                {EXTERNAL_SERVICES.map((svc) => (
                  <div key={svc.name} className="px-4 py-3 transition-colors hover:bg-accent/50">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[13px] font-medium leading-tight">{svc.name}</span>
                      <MiniTag className="border-primary/50 text-primary">内置代理</MiniTag>
                      <span className="ml-auto flex items-center gap-3">
                        {svc.links.map((l) => (
                          <a
                            key={l.url}
                            href={l.url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 font-mono text-[10px] text-primary transition-opacity hover:opacity-70"
                          >
                            <ExternalLink className="h-3 w-3" strokeWidth={1.75} aria-hidden />{l.label}
                          </a>
                        ))}
                      </span>
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{svc.desc}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {svc.endpoints.map((ep) => (
                        <code key={ep} className="rounded-[3px] border bg-muted/50 px-1.5 py-px font-mono text-[9px] text-muted-foreground">{ep}</code>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          </TabsContent>

          {/* ============ 关于 ============ */}
          <TabsContent value="about" className="space-y-4">
            <Panel>
              <PanelHead title="系统信息 · SYSTEM" />
              <div className="p-4">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2">
                  <span className="font-display text-[26px] leading-none tracking-tight">
                    CryoAgent <span className="italic text-primary">Pro</span>
                  </span>
                  <span className="num text-[11px] text-muted-foreground">v2.0.0</span>
                  <span className="label-tech ml-auto flex items-center gap-1.5 !text-[10px]">
                    <span className="status-dot" aria-hidden /> SYS ONLINE
                  </span>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">蛋白质结构智能分析平台 · Next.js 全栈重构版</p>
                <div className="mt-3 flex flex-wrap gap-1.5 border-t pt-3">
                  {['Next.js 16', 'TypeScript 5', 'Tailwind CSS 4', 'shadcn/ui', 'Prisma + SQLite', 'Recharts', '3Dmol.js', 'z-ai LLM', 'BM25 + 向量混合检索'].map((t) => (
                    <span key={t} className="rounded-[3px] border px-1.5 py-px font-mono text-[9px] text-muted-foreground">{t}</span>
                  ))}
                </div>
              </div>
            </Panel>

            <Panel>
              <PanelHead title="重构说明 · REFACTOR NOTES" />
              <div className="space-y-2 p-4 text-xs leading-relaxed text-muted-foreground">
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
                  并新增: <span className="font-medium text-primary">序列理化分析</span> (蛋白质/核酸全套指标)、
                  多矩阵比对、知识图谱路径发现、接口文档在线调试等特性。
                </p>
              </div>
            </Panel>

            <Panel>
              <PanelHead title="数据规模 · DATA VOLUME" hint={totals ? `${totals.literature} 篇文献入库` : undefined} />
              {totals ? (
                <div className="grid grid-cols-3 gap-px bg-border sm:grid-cols-4 lg:grid-cols-6">
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
                    <div key={s.label} className="bg-card px-3 py-2.5">
                      <div className="num text-[17px] font-medium leading-none tracking-tight">{s.value.toLocaleString()}</div>
                      <div className="label-tech mt-1.5 !text-[9px]">{s.label}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="p-4 text-xs text-muted-foreground">统计数据加载中…</p>
              )}
            </Panel>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
