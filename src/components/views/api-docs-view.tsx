'use client';

/**
 * CryoAgent Pro — 接口文档 (BENCH 设计系统)
 * 全部 REST 端点速查 — 左侧分组清单 + 右侧端点详情 (参数/响应 mono 代码块) + GET 在线调试
 * 结构: grid-bg masthead + 端点索引过滤台 + master-detail + table.bench 参数表
 */

import { useMemo, useState } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import {
  BookOpen, Boxes, Bot, ClipboardCheck, GitCompareArrows, KeyRound, Loader2,
  Network, Play, Search, Sparkles, Dna, Terminal,
} from 'lucide-react';

// ============ 数据模型 ============

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

interface EndpointDoc {
  method: HttpMethod;
  path: string;
  summary: string;
  params: string;
  response: string;
  /** 可在线试用的完整请求地址 */
  tryUrl?: string;
}

interface EndpointGroup {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  endpoints: EndpointDoc[];
}

/** 方法短码 tag — outline 语义色 (GET=chart-1 / POST=chart-2 / DELETE=destructive) */
const METHOD_CLASSES: Record<HttpMethod, string> = {
  GET: 'border-chart-1/50 text-chart-1',
  POST: 'border-chart-2/50 text-chart-2',
  PUT: 'border-chart-3/50 text-chart-3',
  PATCH: 'border-chart-5/50 text-chart-5',
  DELETE: 'border-destructive/50 text-destructive',
};

// ============ 端点清单 (与后端路由一一对应) ============

const ENDPOINT_GROUPS: EndpointGroup[] = [
  {
    id: 'auth',
    label: '认证',
    icon: KeyRound,
    endpoints: [
      { method: 'GET', path: '/api/auth', summary: '获取当前登录用户', params: '—', response: '{user, needSetup}', tryUrl: '/api/auth' },
      { method: 'POST', path: '/api/auth', summary: '登录 / 注册 / 登出', params: '{action:register|login|logout, username, password}', response: '{success, user}' },
    ],
  },
  {
    id: 'literature',
    label: '文献',
    icon: BookOpen,
    endpoints: [
      { method: 'GET', path: '/api/literature', summary: '文献列表 (搜索/排序/收藏/分页)', params: '?q=&page=1&pageSize=12&sort=recent|year|title&favorite=', response: '{total, page, pageSize, items[]}', tryUrl: '/api/literature' },
      { method: 'POST', path: '/api/literature', summary: '上传 PDF → 解析 → 分块 → 索引 → 关联结构', params: 'FormData {file, title?}', response: '{success, literature, detected{pdbIds,uniprotIds}}' },
      { method: 'GET', path: '/api/literature/[id]', summary: '文献详情 (分块/关联结构/笔记/分区统计)', params: '路径参数 id', response: '{literature, chunks, structures, notes, sectionStats}' },
      { method: 'PATCH', path: '/api/literature/[id]', summary: '编辑文献元数据 / 收藏', params: '{title?, journal?, year?, keywords?, authors?, abstract?, isFavorite?}', response: '{success}' },
      { method: 'PUT', path: '/api/literature/[id]', summary: '重新解析文档', params: '{fileName, text|null}', response: '{success}' },
      { method: 'DELETE', path: '/api/literature/[id]', summary: '删除文献及其分块', params: '路径参数 id', response: '{success}' },
    ],
  },
  {
    id: 'search',
    label: '检索',
    icon: Search,
    endpoints: [
      { method: 'POST', path: '/api/search', summary: '混合检索 (BM25 + TF-IDF 向量 + RRF 融合)', params: '{query, mode:bm25|vector|hybrid, limit}', response: '{mode, latencyMs, total, hits[]{score,snippet}}' },
      { method: 'GET', path: '/api/search', summary: '搜索日志', params: '?limit=', response: '{logs[]}', tryUrl: '/api/search?limit=5' },
    ],
  },
  {
    id: 'qa',
    label: '问答',
    icon: Bot,
    endpoints: [
      { method: 'POST', path: '/api/qa/ask', summary: 'RAG 流式问答 (SSE: meta/notice/delta/done)', params: '{question, sessionId, mode:rag|direct, skillId?, history?}', response: 'SSE 事件流' },
      { method: 'POST', path: '/api/qa/agent', summary: 'Agent 工具调用问答 (最多 N 步循环)', params: '{question, sessionId, skillId?, history?}', response: '{sessionId, answer, toolCalls[], contextTurns}' },
      { method: 'GET', path: '/api/qa/history', summary: '问答历史 (会话聚合 / 按模式过滤)', params: '?sessionId= | ?mode=', response: '{total, sessions[], items[]}', tryUrl: '/api/qa/history' },
      { method: 'GET', path: '/api/qa/history/[id]', summary: '单条问答详情 (含来源与工具调用)', params: '路径参数 id', response: '{item{sources[], toolCalls[]}}' },
      { method: 'DELETE', path: '/api/qa/history/[id]', summary: '删除问答记录', params: '路径参数 id', response: '{success}' },
      { method: 'GET', path: '/api/qa/agent', summary: 'Agent 会话列表 / 单会话消息', params: '?sessionId=', response: '{sessions[]} | {session{messages}}', tryUrl: '/api/qa/agent' },
    ],
  },
  {
    id: 'structure',
    label: '结构',
    icon: Boxes,
    endpoints: [
      { method: 'GET', path: '/api/structures', summary: '本地缓存结构列表', params: '?q=&page=&pageSize=&method=', response: '{total, items[]{resolution,organism,...}}', tryUrl: '/api/structures' },
      { method: 'POST', path: '/api/structures', summary: 'RCSB 远程结构搜索 (结果自动缓存)', params: '{query, limit}', response: '{query, total, hits[]{identifier,score,cached}}' },
      { method: 'GET', path: '/api/structure/[id]', summary: '结构详情 (序列/引文/关联文献/AlphaFold)', params: '路径参数 id, ?refresh=true 强制刷新', response: '{structure, literature[], relatedStructures[], alphaFold}' },
      { method: 'GET', path: '/api/structure/[id]/pdb', summary: 'PDB 坐标纯文本 (供 3Dmol 渲染)', params: '?source=rcsb|alphafold', response: 'text/plain (PDB/mmCIF)' },
    ],
  },
  {
    id: 'kg',
    label: '知识图谱',
    icon: Network,
    endpoints: [
      { method: 'GET', path: '/api/kg', summary: '全局图谱数据 或 统计概览', params: '?view=global|stats &limit=', response: '{nodes[], edges[], stats} | {stats, popularStructures}', tryUrl: '/api/kg?view=stats' },
      { method: 'GET', path: '/api/kg/neighborhood/[id]', summary: '结构邻域子图 (深度 1-2)', params: '路径参数 id, ?depth=1|2 &limit=', response: '{center, depth, nodes[], edges[], stats}' },
      { method: 'POST', path: '/api/kg', summary: '图谱搜索 (结构与文献)', params: '{query}', response: '{structures[], literature[]}' },
      { method: 'PUT', path: '/api/kg', summary: '两结构间路径发现 (BFS) + 序列相似度', params: '{source, target}', response: '{path[], connected, sequenceSimilarity}' },
    ],
  },
  {
    id: 'alignment',
    label: '比对',
    icon: GitCompareArrows,
    endpoints: [
      { method: 'POST', path: '/api/alignment', summary: '序列比对 (Gotoh NW/SW + 三种矩阵)', params: '{sequence1?, sequence2?, pdbId1?, pdbId2?, algorithm?, matrix?, seq1Name?, seq2Name?}', response: '{taskId, result{score,identity,blocks[],consensus}}' },
      { method: 'GET', path: '/api/alignment', summary: '历史比对任务列表', params: '?limit=', response: '{tasks[]{seq1Name,identity,score}}', tryUrl: '/api/alignment' },
    ],
  },
  {
    id: 'sequence',
    label: '序列',
    icon: Dna,
    endpoints: [
      { method: 'POST', path: '/api/sequence/analyze', summary: '序列理化分析 (蛋白 / 核酸自动检测)', params: '{sequence? | source:pdb|uniprot, sourceId?, type:auto|protein|nucleic}', response: '{type, result{mw,pI,gravy,composition,...} | 核酸指标}' },
      { method: 'GET', path: '/api/uniprot/[id]', summary: 'UniProt 条目 (序列/注释/关键词)', params: '路径参数 accession, 如 P69905', response: '{entry{accession, sequence, keywords}}' },
    ],
  },
  {
    id: 'skills',
    label: '技能',
    icon: Sparkles,
    endpoints: [
      { method: 'GET', path: '/api/skills', summary: '技能列表 (含分类与计数)', params: '?category=', response: '{total, categories[], skills[]}', tryUrl: '/api/skills' },
      { method: 'POST', path: '/api/skills', summary: '技能关键词匹配测试', params: '{query}', response: '{matches[{skill, matchedKeywords, score}]}' },
    ],
  },
  {
    id: 'evaluation',
    label: '评估',
    icon: ClipboardCheck,
    endpoints: [
      { method: 'GET', path: '/api/evaluation', summary: '评估记录 / Ground Truth / 监控统计', params: '?view=all|ground-truth &limit=', response: '{runs[], groundTruths[], monitor}', tryUrl: '/api/evaluation?view=all' },
      { method: 'POST', path: '/api/evaluation', summary: '运行一次检索评估 (P/R/F1/MRR)', params: '{query, mode:bm25|vector|hybrid, autoGroundTruth?}', response: '{runId, metrics, retrieved[], hasGroundTruth}' },
      { method: 'PUT', path: '/api/evaluation', summary: '添加 / 更新 Ground Truth', params: '{query, relevantChunkIds[], notes?}', response: '{success, groundTruth}' },
      { method: 'DELETE', path: '/api/evaluation', summary: '删除评估记录或 Ground Truth', params: '?runId= | ?groundTruthId=', response: '{success}' },
    ],
  },
  {
    id: 'system',
    label: '系统',
    icon: Terminal,
    endpoints: [
      { method: 'GET', path: '/api/stats', summary: '平台统计仪表盘数据', params: '—', response: '{totals, qaActivity, methodStats, ...}', tryUrl: '/api/stats' },
      { method: 'GET', path: '/api/config', summary: '读取应用配置', params: '—', response: '{config{defaultSearchMode, maxSources, ...}}', tryUrl: '/api/config' },
      { method: 'POST', path: '/api/config', summary: '保存配置项 (白名单键)', params: '{defaultSearchMode, maxSources, agentMaxSteps, ...}', response: '{success}' },
      { method: 'PUT', path: '/api/config', summary: 'AI 连接测试 (发送 ping)', params: '—', response: '{success, latencyMs, reply}' },
      { method: 'GET', path: '/api/agent/tools', summary: 'Agent 工具注册表', params: '—', response: '{total, tools[]}', tryUrl: '/api/agent/tools' },
      { method: 'GET', path: '/api/notes', summary: '阅读笔记列表', params: '?literatureId=', response: '{notes[]}', tryUrl: '/api/notes' },
      { method: 'POST', path: '/api/notes', summary: '创建笔记', params: '{literatureId?, content, anchor?}', response: '{success, note}' },
      { method: 'DELETE', path: '/api/notes', summary: '删除笔记', params: '?id=', response: '{success}' },
      { method: 'POST', path: '/api/seed', summary: '重置并注入种子数据 (慎用)', params: '—', response: '{success}' },
    ],
  },
];

const TOTAL_ENDPOINTS = ENDPOINT_GROUPS.reduce((a, g) => a + g.endpoints.length, 0);
const TRYABLE_COUNT = ENDPOINT_GROUPS.reduce((a, g) => a + g.endpoints.filter((e) => e.tryUrl).length, 0);
const DEFAULT_KEY = `${ENDPOINT_GROUPS[0].endpoints[0].method}:${ENDPOINT_GROUPS[0].endpoints[0].path}`;

// ============ BENCH 基础组件 ============

/** mono 方法短码 tag — 定宽对齐, outline 语义色 */
function MethodTag({ method, className }: { method: HttpMethod; className?: string }) {
  return (
    <span className={cn('inline-flex w-12 shrink-0 justify-center rounded-[3px] border px-1 py-px font-mono text-[9px] font-semibold tracking-wide', METHOD_CLASSES[method], className)}>
      {method}
    </span>
  );
}

/** 精确空态 — mono 指引 */
function Empty({ text }: { text: string }) {
  return (
    <div className="label-tech flex h-full min-h-[88px] items-center justify-center px-4 py-8 text-center !text-[10px] normal-case !tracking-[0.06em]">
      {text}
    </div>
  );
}

// ============ 主组件 ============

export function ApiDocsView() {
  const [search, setSearch] = useState('');
  const [trying, setTrying] = useState<Record<string, boolean>>({});
  const [results, setResults] = useState<Record<string, { ok: boolean; status: number; text: string }>>({});
  const [selectedKey, setSelectedKey] = useState(DEFAULT_KEY);

  const groups = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return ENDPOINT_GROUPS;
    return ENDPOINT_GROUPS.map((g) => ({
      ...g,
      endpoints: g.endpoints.filter(
        (e) =>
          e.path.toLowerCase().includes(q) ||
          e.summary.toLowerCase().includes(q) ||
          e.params.toLowerCase().includes(q) ||
          e.response.toLowerCase().includes(q) ||
          g.label.toLowerCase().includes(q)
      ),
    })).filter((g) => g.endpoints.length > 0);
  }, [search]);

  const selected = useMemo(() => {
    for (const g of ENDPOINT_GROUPS) {
      for (const e of g.endpoints) {
        if (`${e.method}:${e.path}` === selectedKey) return e;
      }
    }
    return ENDPOINT_GROUPS[0].endpoints[0];
  }, [selectedKey]);

  const visibleCount = useMemo(() => groups.reduce((a, g) => a + g.endpoints.length, 0), [groups]);

  const tryEndpoint = async (doc: EndpointDoc) => {
    if (!doc.tryUrl) return;
    const url = doc.tryUrl;
    setTrying((p) => ({ ...p, [url]: true }));
    try {
      const resp = await fetch(url);
      const text = await resp.text();
      let out = text;
      try {
        out = JSON.stringify(JSON.parse(text), null, 2);
      } catch {
        /* 非 JSON 响应保留原文 */
      }
      if (out.length > 4000) out = `${out.slice(0, 4000)}\n… (已截断, 完整 ${out.length} 字符)`;
      setResults((p) => ({ ...p, [url]: { ok: resp.ok, status: resp.status, text: out } }));
      toast.success(`${resp.ok ? '请求成功' : '请求返回'} · HTTP ${resp.status}`);
    } catch (err) {
      setResults((p) => ({ ...p, [url]: { ok: false, status: 0, text: err instanceof Error ? err.message : '请求失败' } }));
      toast.error('请求失败, 请检查服务状态');
    } finally {
      setTrying((p) => ({ ...p, [url]: false }));
    }
  };

  const selectedResult = selected.tryUrl ? results[selected.tryUrl] : undefined;
  const selectedBusy = selected.tryUrl ? !!trying[selected.tryUrl] : false;

  return (
    <div className="animate-fade-in-up">
      {/* ===== Masthead — 坐标纸 + 编辑性标题 ===== */}
      <div className="grid-bg border-b">
        <div className="flex flex-wrap items-end justify-between gap-4 px-4 py-6 md:px-6">
          <div>
            <div className="label-tech !text-[10px]">API Reference · 接口文档</div>
            <h1 className="mt-1.5 text-[26px] font-semibold leading-none tracking-tight md:text-[30px]">
              接口文档
              <span className="font-display ml-2.5 align-middle text-[20px] font-normal italic tracking-normal title-gradient md:text-[24px]">
                Reference
              </span>
            </h1>
            <p className="mt-2.5 max-w-lg text-xs leading-relaxed text-muted-foreground">
              平台 REST 端点速查 — 同源相对路径 · JSON 响应 (坐标文件除外) · GET 端点支持在线调试
            </p>
          </div>
          <div className="label-tech space-y-1.5 text-right !text-[10px]">
            <div className="flex items-center justify-end gap-2">
              <span className="status-dot" aria-hidden />
              <span className="num">{TOTAL_ENDPOINTS}</span> ENDPOINTS
            </div>
            <div className="text-muted-foreground/60">
              <span className="num">{TRYABLE_COUNT}</span> TRYABLE · SAME-ORIGIN
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-4 md:p-6">
        {/* ===== 端点索引过滤台 ===== */}
        <section className="rounded-lg border bg-card">
          <div className="flex items-center gap-3 border-b px-4 py-2.5">
            <span className="label-tech !text-[10px] text-foreground/75">端点索引 · Endpoint Index</span>
            <span className="label-tech ml-auto !text-[9px]">
              <span className="num">{visibleCount}</span> / <span className="num">{TOTAL_ENDPOINTS}</span> VISIBLE
            </span>
          </div>
          <div className="p-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" strokeWidth={1.75} aria-hidden />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="按路径 / 功能 / 参数检索, 例如 alignment 或 kg…"
                className="h-9 pl-9 font-mono text-xs"
                aria-label="端点搜索"
              />
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {ENDPOINT_GROUPS.map((g) => (
                <button
                  key={g.id}
                  type="button"
                  onClick={() => setSearch(g.label)}
                  className="flex h-8 items-center gap-1.5 rounded-[5px] border px-2.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                >
                  <g.icon className="h-3 w-3" aria-hidden />
                  {g.label}
                  <span className="num opacity-60">{g.endpoints.length}</span>
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* ===== 主工作区: 端点清单 (左) + 端点详情 (右) ===== */}
        <div className="grid gap-4 lg:grid-cols-5">
          {/* 左: 分组清单 */}
          <section className="rounded-lg border bg-card lg:col-span-2">
            <div className="flex items-center gap-3 border-b px-4 py-2.5">
              <span className="label-tech !text-[10px] text-foreground/75">端点清单 · Endpoints</span>
              <span className="label-tech ml-auto !text-[9px]">{groups.length} 组</span>
            </div>
            <div className="max-h-[640px] overflow-y-auto custom-scrollbar">
              {groups.map((g) => (
                <div key={g.id}>
                  <div className="label-tech border-b bg-muted/40 px-4 py-1.5 !text-[9px]">
                    {g.label} · <span className="num">{g.endpoints.length}</span>
                  </div>
                  <div className="divide-y">
                    {g.endpoints.map((e) => {
                      const key = `${e.method}:${e.path}`;
                      const active = key === selectedKey;
                      return (
                        <button
                          key={key}
                          type="button"
                          onClick={() => setSelectedKey(key)}
                          aria-current={active ? 'true' : undefined}
                          className={cn(
                            'relative flex min-h-[44px] w-full items-center gap-2.5 px-4 py-2 text-left transition-colors hover:bg-accent/50',
                            active && 'bg-accent'
                          )}
                        >
                          {active && <span className="absolute inset-y-[9px] left-0 w-[2px] bg-primary" aria-hidden />}
                          <MethodTag method={e.method} />
                          <code className={cn('min-w-0 flex-1 truncate font-mono text-[11px]', active ? 'font-medium text-foreground' : 'text-foreground/80')}>
                            {e.path}
                          </code>
                          {e.tryUrl && <span className="label-tech shrink-0 !text-[8px] text-primary/70">TRY</span>}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
              {groups.length === 0 && <Empty text={`NO MATCH — 未找到匹配 "${search}" 的端点`} />}
            </div>
          </section>

          {/* 右: 端点详情 */}
          <section className="rounded-lg border bg-card lg:col-span-3">
            <div className="flex flex-wrap items-center gap-3 border-b px-4 py-2.5">
              <span className="label-tech !text-[10px] text-foreground/75">端点详情 · Detail</span>
              {selected.tryUrl && (
                <Button
                  variant="outline"
                  size="sm"
                  className="ml-auto h-8 gap-1.5 px-3 font-mono text-[10px] uppercase tracking-wider after:absolute after:-inset-1"
                  onClick={() => tryEndpoint(selected)}
                  disabled={selectedBusy}
                  aria-label={`在线调试 ${selected.path}`}
                >
                  {selectedBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" strokeWidth={1.75} />}
                  在线调试
                </Button>
              )}
            </div>
            <div className="border-b px-4 py-3">
              <div className="flex flex-wrap items-center gap-2.5">
                <MethodTag method={selected.method} />
                <code className="num break-all text-[13px] font-semibold tracking-tight">{selected.path}</code>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{selected.summary}</p>
            </div>
            <div className="space-y-4 p-4">
              <div>
                <div className="label-tech !text-[9px]">请求参数 · PARAMS</div>
                <pre className="mt-1.5 overflow-x-auto rounded-md bg-muted/60 p-3 font-mono text-[11px] leading-relaxed text-foreground/85 custom-scrollbar">
                  {selected.params}
                </pre>
              </div>
              <div>
                <div className="label-tech !text-[9px]">响应 · RESPONSE</div>
                <pre className="mt-1.5 overflow-x-auto rounded-md bg-muted/60 p-3 font-mono text-[11px] leading-relaxed text-foreground/85 custom-scrollbar">
                  {selected.response}
                </pre>
              </div>

              {/* 在线调试结果 */}
              {selected.tryUrl && selectedResult && (
                <div className="rounded-lg border">
                  <div className="flex flex-wrap items-center gap-2 border-b bg-muted/40 px-3 py-2">
                    <MethodTag method={selected.method} />
                    <code className="min-w-0 flex-1 truncate font-mono text-[11px]">{selected.tryUrl}</code>
                    <span
                      className={cn(
                        'num shrink-0 rounded-[3px] border px-1.5 py-px text-[9px] font-medium',
                        selectedResult.ok ? 'border-primary/50 text-primary' : 'border-destructive/50 text-destructive'
                      )}
                    >
                      HTTP {selectedResult.status}
                    </span>
                  </div>
                  <pre className="max-h-72 overflow-auto custom-scrollbar p-3 font-mono text-[11px] leading-relaxed">
                    {selectedResult.text}
                  </pre>
                </div>
              )}
            </div>
          </section>
        </div>

        {/* ===== 使用说明 ===== */}
        <section className="rounded-lg border bg-card">
          <div className="flex items-center gap-3 border-b px-4 py-2.5">
            <span className="label-tech !text-[10px] text-foreground/75">使用说明 · Notes</span>
          </div>
          <div className="divide-y text-[11px] leading-relaxed text-muted-foreground">
            <p className="px-4 py-2">所有请求均为同源相对路径, 无需额外鉴权头 (Session 经 HttpOnly Cookie 维持)。</p>
            <p className="px-4 py-2">POST/PUT 请求体为 JSON; 文献上传为 FormData; SSE 问答请使用流式读取。</p>
            <p className="px-4 py-2">[id] 为路径参数; 4xx 返回 {`{error: string}`} 错误信息。</p>
          </div>
        </section>
      </div>
    </div>
  );
}
