'use client';

/**
 * CryoAgent Pro — 接口文档
 * 全部 REST API 分组速查表 + 简单 GET 端点在线 "试一试"
 */

import { useMemo, useState } from 'react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { toast } from 'sonner';
import {
  BookMarked, BookOpen, Boxes, Bot, ClipboardCheck, GitCompareArrows, KeyRound, Loader2,
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

const METHOD_CLASSES: Record<HttpMethod, string> = {
  GET: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  POST: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  PUT: 'border-teal-500/30 bg-teal-500/10 text-teal-700 dark:text-teal-300',
  PATCH: 'border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300',
  DELETE: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300',
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

// ============ 主组件 ============

export function ApiDocsView() {
  const [search, setSearch] = useState('');
  const [trying, setTrying] = useState<Record<string, boolean>>({});
  const [results, setResults] = useState<Record<string, { ok: boolean; status: number; text: string }>>({});

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

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 p-4 md:space-y-6 md:p-6">
      {/* 页头 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600 text-white shadow-lg shadow-teal-500/20">
          <BookMarked className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-bold tracking-tight">接口文档</h2>
          <p className="text-xs text-muted-foreground">
            {TOTAL_ENDPOINTS} 个 REST 端点 · {TRYABLE_COUNT} 个支持在线调试 · 全部返回 JSON (除坐标文本)
          </p>
        </div>
      </div>

      {/* 搜索过滤 */}
      <Card className="p-4">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="按路径 / 功能 / 参数搜索端点, 例如 alignment 或 kg…"
            className="pl-9"
            aria-label="端点搜索"
          />
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {ENDPOINT_GROUPS.map((g) => (
            <button
              key={g.id}
              type="button"
              onClick={() => setSearch(g.label)}
              className="flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-teal-500/40 hover:text-foreground"
            >
              <g.icon className="h-3 w-3" />
              {g.label}
              <span className="tabular-nums opacity-60">{g.endpoints.length}</span>
            </button>
          ))}
        </div>
      </Card>

      {/* 分组表 */}
      {groups.map((g) => (
        <Card key={g.id} className="overflow-hidden p-4 md:p-6">
          <CardHeader className="mb-3 p-0">
            <CardTitle className="flex items-center gap-2 text-sm">
              <g.icon className="h-4 w-4 text-teal-600 dark:text-teal-400" />
              {g.label}
              <Badge variant="secondary" className="font-normal tabular-nums">{g.endpoints.length}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto custom-scrollbar rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="h-9 w-20 text-[11px]">方法</TableHead>
                    <TableHead className="h-9 min-w-[200px] text-[11px]">路径</TableHead>
                    <TableHead className="h-9 min-w-[180px] text-[11px]">功能</TableHead>
                    <TableHead className="h-9 min-w-[220px] text-[11px]">参数</TableHead>
                    <TableHead className="h-9 min-w-[200px] text-[11px]">响应</TableHead>
                    <TableHead className="h-9 w-20 text-[11px]">调试</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {g.endpoints.map((e) => {
                    const result = e.tryUrl ? results[e.tryUrl] : undefined;
                    const busy = e.tryUrl ? trying[e.tryUrl] : false;
                    return (
                      <TableRow key={`${e.method}-${e.path}`} className="group">
                        <TableCell className="py-2.5">
                          <span className={cn('inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-bold', METHOD_CLASSES[e.method])}>
                            {e.method}
                          </span>
                        </TableCell>
                        <TableCell className="py-2.5">
                          <code className="break-all font-mono text-xs font-semibold">{e.path}</code>
                        </TableCell>
                        <TableCell className="py-2.5 text-xs text-muted-foreground">{e.summary}</TableCell>
                        <TableCell className="py-2.5">
                          <code className="break-all font-mono text-[11px] text-muted-foreground">{e.params}</code>
                        </TableCell>
                        <TableCell className="py-2.5">
                          <code className="break-all font-mono text-[11px] text-muted-foreground">{e.response}</code>
                        </TableCell>
                        <TableCell className="py-2.5">
                          {e.tryUrl ? (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 gap-1 px-2 text-[11px]"
                              onClick={() => tryEndpoint(e)}
                              disabled={busy}
                              aria-label={`试一试 ${e.path}`}
                            >
                              {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                              试一试
                            </Button>
                          ) : (
                            <span className="text-[10px] text-muted-foreground/40">—</span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>

            {/* Try 结果 */}
            {g.endpoints
              .filter((e) => e.tryUrl && results[e.tryUrl!])
              .map((e) => {
                const r = results[e.tryUrl!];
                return (
                  <div key={`res-${e.method}-${e.path}`} className="mt-3 rounded-xl border">
                    <div className="flex flex-wrap items-center gap-2 border-b bg-muted/40 px-3 py-2">
                      <span className={cn('inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-bold', METHOD_CLASSES[e.method])}>
                        {e.method}
                      </span>
                      <code className="font-mono text-xs">{e.tryUrl}</code>
                      <span
                        className={cn(
                          'ml-auto rounded-full px-2 py-0.5 text-[10px] font-semibold',
                          r.ok ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' : 'bg-rose-500/10 text-red-700 dark:text-rose-300'
                        )}
                      >
                        HTTP {r.status}
                      </span>
                    </div>
                    <pre className="max-h-72 overflow-auto custom-scrollbar p-3 font-mono text-[11px] leading-relaxed">
                      {r.text}
                    </pre>
                  </div>
                );
              })}
          </CardContent>
        </Card>
      ))}

      {groups.length === 0 && (
        <Card className="flex h-40 flex-col items-center justify-center gap-2 border-dashed p-4 text-sm text-muted-foreground">
          <Search className="h-8 w-8 opacity-30" />
          未找到匹配 “{search}” 的端点
        </Card>
      )}

      {/* 使用说明 */}
      <Card className="p-4 text-[11px] leading-relaxed text-muted-foreground">
        <p className="mb-1 font-semibold text-foreground">使用说明</p>
        <p>· 所有请求均为同源相对路径, 无需额外鉴权头 (Session 通过 HttpOnly Cookie 维持)。</p>
        <p>· POST/PUT 请求体为 JSON; 文献上传为 FormData; SSE 问答请使用流式读取。</p>
        <p>· [id] 为路径参数; 4xx 返回 {`{error: string}`} 错误信息。</p>
      </Card>
    </div>
  );
}
