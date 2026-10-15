'use client';

/**
 * CryoAgent Pro — 智能问答 · QA Console (BENCH 设计系统)
 * RAG 流式检索 + Agent 工具调用 · 对话记录式排版 (无气泡) · 仪器模式切换
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAppStore, streamSse, api } from '@/lib/store';
import { MarkdownView } from '@/components/markdown-view';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { SegmentedTabs } from '@/components/ui/bench-widgets';
import { cn } from '@/lib/utils';
import {
  Send, Square, Plus, BookOpen, Cpu, Sparkles, History,
  Wrench, ChevronDown, ChevronUp, Copy, Check,
  RefreshCw, PanelRightOpen, PanelRightClose, CircleAlert, X,
} from 'lucide-react';
import { toast } from 'sonner';

interface ChatSource {
  index: number;
  literatureId: string;
  chunkIndex: number;
  title: string;
  section: string;
  score: number;
  snippet: string;
}

interface ToolCall {
  tool: string;
  params: Record<string, unknown>;
  resultSummary: string;
  latencyMs: number;
  ok: boolean;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: ChatSource[];
  toolCalls?: ToolCall[];
  mode?: string;
  skillName?: string | null;
  streaming?: boolean;
  latencyMs?: number;
  tokensUsed?: number;
  error?: boolean;
}

interface SkillInfo {
  id: string;
  name: string;
  category: string;
  categoryLabel?: string;
  description: string;
  examples: string[];
}

const WELCOME_PROMPTS = [
  { code: 'PPI', text: 'SARS-CoV-2 spike 蛋白与 ACE2 的结合亲和力如何？' },
  { code: 'RES', text: 'Cryo-EM 达到原子分辨率需要哪些条件？' },
  { code: 'CMP', text: '比较 6M0J 和 6VXX 两个结构' },
  { code: 'AF2', text: 'AlphaFold 的预测精度达到了什么水平？' },
];

let msgId = 0;
const nextId = () => `msg-${++msgId}-${Date.now()}`;

/* ============ BENCH 局部工具 (与 dashboard-view 同构) ============ */

const TAG_TONES = {
  muted: 'border-border text-muted-foreground',
  agent: 'border-chart-2/50 text-chart-2',
  skill: 'border-chart-3/50 text-chart-3',
  error: 'border-destructive/50 text-destructive',
  primary: 'border-primary/50 text-primary',
} as const;

function Tag({ tone = 'muted', className, ...props }: React.HTMLAttributes<HTMLSpanElement> & { tone?: keyof typeof TAG_TONES }) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-[3px] border px-1.5 py-px font-mono text-[9px] font-medium tracking-wide',
        TAG_TONES[tone],
        className
      )}
      {...props}
    />
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="label-tech flex h-full min-h-[88px] items-center justify-center px-4 py-8 text-center !text-[10px] normal-case !tracking-[0.06em]">
      {text}
    </div>
  );
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

export function QaView() {
  const viewParams = useAppStore((s) => s.viewParams);
  const navigate = useAppStore((s) => s.navigate);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<'rag' | 'agent'>('rag');
  const [sessionId, setSessionId] = useState(`chat-${Date.now()}`);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [activeSkill, setActiveSkill] = useState<string | null>(null);
  const [showSources, setShowSources] = useState(true);
  const [historySessions, setHistorySessions] = useState<{ sessionId: string; question: string; count: number; lastAt: string; mode: string }[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [sessionsOpen, setSessionsOpen] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expandedTools, setExpandedTools] = useState<Set<string>>(new Set());
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesRef = useRef<Message[]>([]);

  messagesRef.current = messages;

  // 加载技能列表
  useEffect(() => {
    api<{ skills: SkillInfo[] }>('/api/skills')
      .then((d) => setSkills(d.skills))
      .catch(() => {});
  }, []);

  // 加载历史会话
  useEffect(() => {
    api<{ sessions: typeof historySessions }>('/api/qa/history?limit=60')
      .then((d) => setHistorySessions(d.sessions || []))
      .catch(() => {});
  }, []);

  // 技能预选 (从技能中心跳转)
  useEffect(() => {
    if (viewParams.skillId) {
      setActiveSkill(viewParams.skillId);
      const skill = skills.find((s) => s.id === viewParams.skillId);
      if (skill) {
        toast.success(`已激活技能: ${skill.name}`, { description: skill.description });
      }
    }

  }, [viewParams.skillId]);

  // 自动滚动
  const scrollToBottom = useCallback((smooth = true) => {
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    });
  }, []);

  useEffect(() => {
    scrollToBottom(false);
  }, [messages.length, scrollToBottom]);

  const sendQuestion = async (questionRaw?: string) => {
    const question = (questionRaw ?? input).trim();
    if (!question || busy) return;

    setInput('');
    setBusy(true);
    const userMsg: Message = { id: nextId(), role: 'user', content: question };
    const assistantId = nextId();
    const assistantMsg: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      streaming: true,
      mode,
      skillName: activeSkill ? skills.find((s) => s.id === activeSkill)?.name : null,
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    scrollToBottom();

    // 历史上下文
    const history = messagesRef.current
      .filter((m) => !m.streaming && !m.error && m.content)
      .slice(-8)
      .map((m) => ({ role: m.role, content: m.role === 'assistant' ? m.content.slice(0, 2000) : m.content }));

    if (mode === 'rag') {
      const controller = new AbortController();
      abortRef.current = controller;
      await streamSse(
        '/api/qa/ask',
        { question, sessionId, mode: 'rag', skillId: activeSkill, history },
        {
          onMeta: (meta) => {
            const m = meta as { sources?: ChatSource[]; skill?: { name: string } | null; autoSkillMatched?: boolean };
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId
                  ? { ...msg, sources: m.sources || [], skillName: m.skill?.name || msg.skillName }
                  : msg
              )
            );
          },
          onDelta: (text) => {
            setMessages((prev) =>
              prev.map((msg) => (msg.id === assistantId ? { ...msg, content: msg.content + text } : msg))
            );
            scrollToBottom();
          },
          onNotice: (n) => {
            const notice = (n as { message?: string }).message;
            if (notice) toast.info(notice);
          },
          onDone: (d) => {
            const done = d as { latencyMs: number; tokensUsed: number };
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId ? { ...msg, streaming: false, latencyMs: done.latencyMs, tokensUsed: done.tokensUsed } : msg
              )
            );
          },
          onError: (message) => {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId ? { ...msg, streaming: false, error: true, content: msg.content || `ERROR · ${message}` } : msg
              )
            );
            toast.error(message);
          },
        },
        controller.signal
      );
      abortRef.current = null;
    } else {
      // Agent 模式
      try {
        const d = await api<{ answer: string; toolCalls: ToolCall[] }>('/api/qa/agent', {
          method: 'POST',
          body: JSON.stringify({ question, sessionId, skillId: activeSkill, history }),
        });
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantId
              ? { ...msg, content: d.answer, toolCalls: d.toolCalls, streaming: false }
              : msg
          )
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Agent 执行失败';
        setMessages((prev) =>
          prev.map((msg) => (msg.id === assistantId ? { ...msg, streaming: false, error: true, content: `ERROR · ${message}` } : msg))
        );
        toast.error(message);
      }
    }

    setBusy(false);
    inputRef.current?.focus();
  };

  const stopStreaming = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    setMessages((prev) => prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)));
  };

  const newSession = () => {
    setMessages([]);
    setSessionId(`chat-${Date.now()}`);
    setActiveSkill(null);
    inputRef.current?.focus();
  };

  const loadSession = async (sid: string) => {
    try {
      const d = await api<{ items: { question: string; answer: string; mode: string; sources: ChatSource[]; toolCalls: ToolCall[]; createdAt: string }[] }>(
        `/api/qa/history?sessionId=${sid}`
      );
      const restored: Message[] = [];
      for (const item of d.items) {
        restored.push({ id: nextId(), role: 'user', content: item.question });
        restored.push({
          id: nextId(),
          role: 'assistant',
          content: item.answer,
          sources: item.sources,
          toolCalls: item.toolCalls,
          mode: item.mode,
        });
      }
      setMessages(restored);
      setSessionId(sid);
      setShowHistory(false);
      scrollToBottom(false);
    } catch {
      toast.error('加载会话失败');
    }
  };

  const copyMessage = (msg: Message) => {
    void navigator.clipboard.writeText(msg.content);
    setCopiedId(msg.id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const toggleToolExpand = (id: string) => {
    setExpandedTools((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const activeSkillInfo = skills.find((s) => s.id === activeSkill);
  const lastWithSources = [...messages].reverse().find((m) => m.sources && m.sources.length > 0);

  return (
    <div className="flex h-full min-h-0 flex-col animate-fade-in-up">
      {/* ===== Masthead — 坐标纸 + 控制台铭牌 ===== */}
      <div className="grid-bg shrink-0 border-b">
        <div className="flex flex-wrap items-end justify-between gap-3 px-4 py-4 md:px-6 md:py-5">
          <div>
            <div className="label-tech !text-[10px]">QA Console · 智能问答</div>
            <h1 className="font-display mt-1.5 text-[24px] font-semibold leading-none tracking-tight md:text-[28px]">
              智能问答 <span className="title-accent">Q&amp;A</span>
            </h1>
            <p className="mt-2 max-w-lg text-xs leading-relaxed text-muted-foreground">
              基于本地文献库的混合检索问答 · RAG 回答附可溯源引用；AGENT 模式自动调用结构 / 序列 / 文献工具多步推理
            </p>
          </div>
          <div className="label-tech space-y-1.5 text-right !text-[10px]">
            <div className="flex items-center justify-end gap-2">
              <span className="status-dot" data-tone={busy ? 'amber' : undefined} aria-hidden />
              {busy ? 'GENERATING' : 'READY'}
            </div>
            <div className="text-muted-foreground/60">HYBRID BM25+VEC · SSE STREAM</div>
            <div className="num text-muted-foreground/60">SESSION {sessionId.slice(-8).toUpperCase()}</div>
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* ===== 主对话列 ===== */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* 工具条 */}
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-card px-4 py-2 md:px-6">
            <Button
              variant="outline"
              size="sm"
              className="h-11 gap-1.5 text-xs md:h-8"
              onClick={newSession}
            >
              <Plus className="h-3.5 w-3.5" strokeWidth={1.75} />新对话
            </Button>
            <span className="label-tech hidden !text-[9px] md:inline">
              {messages.length > 0 ? `${messages.length} MSG · ${historySessions.length} SESSIONS` : 'SESSION EMPTY'}
            </span>
            <div className="ml-auto flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-11 w-11 md:h-8 md:w-8"
                onClick={() => setShowSources(!showSources)}
                aria-pressed={showSources}
                aria-label="切换检索来源侧栏"
                title="切换来源侧栏"
              >
                {showSources ? <PanelRightClose className="h-4 w-4" strokeWidth={1.75} /> : <PanelRightOpen className="h-4 w-4" strokeWidth={1.75} />}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-11 w-11 md:h-8 md:w-8"
                onClick={() => setShowHistory(true)}
                aria-label="打开历史会话"
                title="历史会话"
              >
                <History className="h-4 w-4" strokeWidth={1.75} />
              </Button>
            </div>
          </div>

          {/* 消息区 — 对话记录式排版 */}
          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center px-4 py-10">
                <div className="label-tech !text-[10px]">
                  NO SESSION — {mode === 'rag' ? 'RAG 检索模式 · 回答附引用来源' : 'AGENT 工具模式 · 多步推理可审计'}
                </div>
                <h2 className="mt-3 text-lg font-semibold tracking-tight">向文献知识库提问</h2>
                <p className="mt-1.5 max-w-md text-center text-xs leading-relaxed text-muted-foreground">
                  回答由本地知识库检索生成并标注引用片段 · 支持多轮上下文追问
                </p>

                {/* 预设问题 — hairline 密集行 */}
                <div className="mt-6 w-full max-w-2xl overflow-hidden rounded-lg border bg-card">
                  <div className="border-b px-4 py-2.5">
                    <span className="label-tech !text-[10px] text-foreground/75">Preset Queries · 预设问题</span>
                  </div>
                  <div className="divide-y">
                    {WELCOME_PROMPTS.map((p) => (
                      <button
                        key={p.text}
                        onClick={() => void sendQuestion(p.text)}
                        className="group lift-on-hover flex min-h-11 w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-accent/50"
                        type="button"
                      >
                        <span className="num w-8 shrink-0 text-[10px] text-muted-foreground/60">{p.code}</span>
                        <span className="min-w-0 flex-1 truncate text-[13px]">{p.text}</span>
                        <span className="label-tech !text-[9px] text-primary opacity-0 transition-opacity group-hover:opacity-100">RUN</span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* 技能快捷挂载 */}
                {skills.length > 0 && (
                  <div className="mt-5 w-full max-w-2xl">
                    <div className="label-tech mb-2 !text-[9px]">Skills · 专家技能挂载 (点击启用 / 取消)</div>
                    <div className="flex flex-wrap gap-1.5">
                      {skills.slice(0, 8).map((s) => (
                        <button
                          key={s.id}
                          onClick={() => setActiveSkill(activeSkill === s.id ? null : s.id)}
                          aria-pressed={activeSkill === s.id}
                          className={cn(
                            'lift-on-hover min-h-9 rounded-[3px] border px-2 py-1.5 font-mono text-[10px] transition-colors',
                            activeSkill === s.id
                              ? 'border-chart-3/60 bg-chart-3/10 text-chart-3'
                              : 'text-muted-foreground hover:border-foreground/25 hover:text-foreground'
                          )}
                          type="button"
                        >
                          {s.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="mx-auto max-w-3xl space-y-5 px-4 py-6">
                {messages.map((msg) => (
                  <MessageBubble
                    key={msg.id}
                    msg={msg}
                    copied={copiedId === msg.id}
                    onCopy={() => copyMessage(msg)}
                    expandedTools={expandedTools}
                    onToggleTool={() => toggleToolExpand(msg.id)}
                    onSourceClick={(litId) => navigate('literature-detail', { id: litId })}
                  />
                ))}
              </div>
            )}
          </div>

          {/* ===== 输入区 — 仪器面板 ===== */}
          <div className="shrink-0 border-t bg-card">
            <div className="mx-auto max-w-3xl px-4 py-3">
              {/* 模式切换 + 状态行 */}
              <div className="mb-2 flex flex-wrap items-center gap-2">
                {/* 模式切换 — 滑动药丸分段控制 */}
                <SegmentedTabs
                  value={mode}
                  onChange={(v) => setMode(v === 'agent' ? 'agent' : 'rag')}
                  options={[
                    {
                      value: 'rag',
                      label: (
                        <>
                          <BookOpen className="h-3.5 w-3.5" strokeWidth={1.75} />检索 RAG
                        </>
                      ),
                    },
                    {
                      value: 'agent',
                      label: (
                        <>
                          <Cpu className="h-3.5 w-3.5" strokeWidth={1.75} />智能体 AGENT
                        </>
                      ),
                    },
                  ]}
                />

                {activeSkillInfo && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        onClick={() => setActiveSkill(null)}
                        aria-label={`取消技能 ${activeSkillInfo.name}`}
                        className="flex min-h-11 items-center gap-1.5 rounded-[3px] border border-chart-3/50 bg-chart-3/5 px-2 font-mono text-[10px] text-chart-3 transition-colors hover:border-chart-3 md:min-h-8 md:py-1"
                      >
                        <Sparkles className="h-3 w-3" strokeWidth={1.75} />
                        {activeSkillInfo.name}
                        <X className="h-3 w-3" strokeWidth={1.75} />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-xs text-xs">{activeSkillInfo.description}</TooltipContent>
                  </Tooltip>
                )}

                {busy && (
                  <span className="label-tech ml-auto flex items-center gap-1.5 !text-[9px] text-chart-2">
                    <RefreshCw className="h-3 w-3 animate-spin" strokeWidth={1.75} />
                    {mode === 'agent' ? 'AGENT 推理中 · 可能需要 1-2 分钟' : '检索并生成中'}
                  </span>
                )}
              </div>

              {/* textarea + 发送/中止 */}
              <div className="flex items-end gap-2 rounded-[5px] border bg-background transition-colors focus-within:border-primary/50">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      void sendQuestion();
                    }
                  }}
                  rows={2}
                  aria-label="问题输入框"
                  placeholder={mode === 'agent' ? 'AGENT 模式 · 例如 "比较 6M0J 和 6VXX 的结构"...' : '输入问题 · Enter 发送 · Shift+Enter 换行'}
                  className="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-3.5 py-2.5 text-sm outline-none placeholder:text-muted-foreground/60"
                  disabled={busy}
                />
                <div className="flex shrink-0 gap-1.5 p-1.5">
                  {busy ? (
                    <Button
                      size="icon"
                      variant="destructive"
                      className="h-11 w-11 rounded-[5px] md:h-9 md:w-9"
                      onClick={stopStreaming}
                      aria-label="中止生成"
                    >
                      <Square className="h-3.5 w-3.5" strokeWidth={1.75} />
                    </Button>
                  ) : (
                    <Button
                      size="icon"
                      className="h-11 w-11 rounded-[5px] md:h-9 md:w-9"
                      onClick={() => void sendQuestion()}
                      disabled={!input.trim()}
                      aria-label="发送问题"
                    >
                      <Send className="h-3.5 w-3.5" strokeWidth={1.75} />
                    </Button>
                  )}
                </div>
              </div>

              <div className="mt-2 flex items-center justify-between gap-3">
                <p className="label-tech !text-[9px] normal-case !tracking-normal text-muted-foreground/70">
                  {mode === 'rag'
                    ? '回答基于本地文献库 · AI 可能出错, 请核实关键信息'
                    : 'AGENT 将调用 11 个专业工具多步推理 · 工具调用全程可审计'}
                </p>
                <span className="label-tech hidden !text-[9px] text-muted-foreground/50 sm:inline">
                  {historySessions.length} SESSIONS LOGGED
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* ===== 右侧侧栏 — 会话历史 + 检索来源 ===== */}
        {showSources && (
          <aside className="hidden w-[300px] shrink-0 flex-col border-l bg-card lg:flex">
            {/* 会话历史 (可折叠) */}
            <section className={cn('flex min-h-0 flex-col border-b', sessionsOpen ? 'flex-[1.1]' : 'shrink-0')}>
              <div className="flex items-center gap-2 border-b px-4 py-2.5">
                <span className="label-tech !text-[10px] text-foreground/75">Session Log · 会话历史</span>
                <button
                  type="button"
                  onClick={() => setSessionsOpen(!sessionsOpen)}
                  className="ml-auto flex h-8 w-8 items-center justify-center rounded-[4px] text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
                  aria-label={sessionsOpen ? '折叠会话历史' : '展开会话历史'}
                  aria-expanded={sessionsOpen}
                >
                  {sessionsOpen ? <ChevronUp className="h-3.5 w-3.5" strokeWidth={1.75} /> : <ChevronDown className="h-3.5 w-3.5" strokeWidth={1.75} />}
                </button>
              </div>
              {sessionsOpen && (
                <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
                  {historySessions.length === 0 ? (
                    <Empty text="NO SESSIONS — 发起第一次提问后记录于此" />
                  ) : (
                    <div className="divide-y">
                      {historySessions.map((s) => (
                        <button
                          key={s.sessionId}
                          onClick={() => void loadSession(s.sessionId)}
                          className={cn(
                            'flex min-h-11 w-full flex-col gap-1 px-4 py-2.5 text-left transition-colors hover:bg-accent/50',
                            s.sessionId === sessionId && 'bg-accent/40'
                          )}
                          type="button"
                          aria-label={`加载会话 ${s.question}`}
                        >
                          <div className="flex w-full items-center gap-2">
                            <Tag tone={s.mode === 'agent' ? 'agent' : 'muted'}>{s.mode === 'agent' ? 'AGENT' : 'RAG'}</Tag>
                            <span className="num ml-auto text-[10px] text-muted-foreground">{s.count} 轮</span>
                          </div>
                          <span className="w-full truncate text-xs">{s.question}</span>
                          <span className="num text-[10px] text-muted-foreground/70">
                            {new Date(s.lastAt).toLocaleDateString('zh-CN')}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* 检索来源 */}
            <section className="flex min-h-0 flex-1 flex-col">
              <PanelHead title="Sources · 检索来源" hint="LATEST ANSWER" />
              <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
                {!lastWithSources?.sources ? (
                  <Empty text="NO SOURCES — 提问后显示 RAG 检索片段" />
                ) : (
                  lastWithSources.sources.map((src) => (
                    <button
                      key={`${src.literatureId}-${src.chunkIndex}`}
                      onClick={() => navigate('literature-detail', { id: src.literatureId })}
                      className="block w-full border-b px-4 py-2.5 text-left transition-colors last:border-b-0 hover:bg-accent/50"
                      type="button"
                      aria-label={`查看文献 ${src.title}`}
                    >
                      <div className="flex items-baseline gap-2">
                        <span className="num text-[10px] text-primary">[{src.index}]</span>
                        <span className="num ml-auto text-[10px] text-muted-foreground">{src.score.toFixed(3)}</span>
                      </div>
                      <div className="mt-0.5 truncate text-[11px] font-medium">{src.title}</div>
                      <div className="label-tech mt-0.5 !text-[9px] normal-case !tracking-normal">
                        {src.section} · CHUNK #{src.chunkIndex + 1}
                      </div>
                      <p className="mt-1 line-clamp-3 text-[10px] leading-4 text-muted-foreground">{src.snippet}</p>
                    </button>
                  ))
                )}
              </div>
            </section>
          </aside>
        )}
      </div>

      {/* 历史会话抽屉 (移动端 / 全屏入口) */}
      <Dialog open={showHistory} onOpenChange={setShowHistory}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              <History className="h-4 w-4" strokeWidth={1.75} />历史会话
            </DialogTitle>
          </DialogHeader>
          <ScrollArea className="max-h-[60vh]">
            {historySessions.length === 0 ? (
              <Empty text="NO SESSIONS — 暂无历史会话记录" />
            ) : (
              <div className="divide-y overflow-hidden rounded-lg border">
                {historySessions.map((s) => (
                  <button
                    key={s.sessionId}
                    onClick={() => void loadSession(s.sessionId)}
                    className={cn(
                      'flex min-h-11 w-full flex-col gap-1 px-3.5 py-2.5 text-left transition-colors hover:bg-accent/50',
                      s.sessionId === sessionId && 'bg-accent/40'
                    )}
                    type="button"
                    aria-label={`加载会话 ${s.question}`}
                  >
                    <div className="flex w-full items-center gap-2">
                      <Tag tone={s.mode === 'agent' ? 'agent' : 'muted'}>{s.mode === 'agent' ? 'AGENT' : 'RAG'}</Tag>
                      <span className="num ml-auto text-[10px] text-muted-foreground">{s.count} 轮对话</span>
                      <span className="num text-[10px] text-muted-foreground/70">
                        {new Date(s.lastAt).toLocaleDateString('zh-CN')}
                      </span>
                    </div>
                    <span className="w-full truncate text-xs">{s.question}</span>
                  </button>
                ))}
              </div>
            )}
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** 消息行 — 对话记录式 (用户: 左信号条块 / AI: 无底色 + mono 元信息头) */
function MessageBubble({
  msg,
  copied,
  onCopy,
  expandedTools,
  onToggleTool,
  onSourceClick,
}: {
  msg: Message;
  copied: boolean;
  onCopy: () => void;
  expandedTools: Set<string>;
  onToggleTool: () => void;
  onSourceClick: (literatureId: string) => void;
}) {
  if (msg.role === 'user') {
    return (
      <div className="flex flex-col items-end">
        <div className="label-tech mb-1 !text-[9px]">USER · 提问</div>
        <div className="max-w-[85%] border-l-2 border-primary bg-accent/40 py-2.5 pl-4 pr-3.5 text-sm leading-relaxed">
          {msg.content}
        </div>
      </div>
    );
  }

  const toolsExpanded = expandedTools.has(msg.id);

  return (
    <div className="group">
      {/* mono 元信息行 */}
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <Tag tone={msg.mode === 'agent' ? 'agent' : 'muted'}>{msg.mode === 'agent' ? 'AGENT' : 'RAG'}</Tag>
        {msg.skillName && <Tag tone="skill">{msg.skillName}</Tag>}
        {msg.streaming && (
          <span className="label-tech flex items-center gap-1.5 !text-[9px] text-chart-2">
            <span className="status-dot" data-tone="amber" aria-hidden />
            STREAMING
          </span>
        )}
        {msg.latencyMs != null && (
          <span className="num text-[10px] text-muted-foreground">{(msg.latencyMs / 1000).toFixed(1)}s</span>
        )}
        {msg.tokensUsed != null && (
          <span className="num text-[10px] text-muted-foreground">{msg.tokensUsed} tok</span>
        )}
        {msg.sources && msg.sources.length > 0 && !msg.streaming && (
          <span className="num text-[10px] text-muted-foreground">[{msg.sources.length} refs]</span>
        )}
        <span className="label-tech ml-auto !text-[9px]">CRYOAGENT</span>
      </div>

      {/* 工具调用 — 可折叠审计面板 */}
      {msg.toolCalls && msg.toolCalls.length > 0 && (
        <div className="mb-2 overflow-hidden rounded-lg border border-chart-2/40">
          <button
            type="button"
            onClick={onToggleTool}
            aria-expanded={toolsExpanded}
            className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-accent/50"
          >
            <Wrench className="h-3.5 w-3.5 shrink-0 text-chart-2" strokeWidth={1.75} />
            <span className="label-tech !text-[10px] text-foreground/75">TOOL CALLS · {msg.toolCalls.length}</span>
            <span className="flex min-w-0 gap-1 overflow-hidden">
              {msg.toolCalls.map((tc, i) => (
                <span key={i} className="num shrink-0 rounded-[3px] border border-border px-1 py-px text-[9px] text-muted-foreground">
                  {tc.tool}
                </span>
              ))}
            </span>
            {toolsExpanded ? (
              <ChevronUp className="ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} />
            ) : (
              <ChevronDown className="ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} />
            )}
          </button>
          {toolsExpanded && (
            <div className="divide-y border-t bg-card">
              {msg.toolCalls.map((tc, i) => (
                <div key={i} className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="status-dot" data-tone={tc.ok ? undefined : 'red'} aria-hidden />
                    <span className="font-mono text-[11px] font-semibold">{tc.tool}</span>
                    <span className="num ml-auto text-[10px] text-muted-foreground">{tc.latencyMs}ms</span>
                  </div>
                  <div className="mt-1 break-all font-mono text-[9px] leading-relaxed text-muted-foreground">
                    params: {JSON.stringify(tc.params).slice(0, 120)}
                  </div>
                  <div className="mt-0.5 break-all font-mono text-[9px] leading-relaxed text-muted-foreground">
                    result: {tc.resultSummary.slice(0, 300)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 正文 — 无底色, 流式带光标 */}
      {msg.streaming && !msg.content ? (
        <div className="flex items-center gap-2 py-2">
          <span className="status-dot" data-tone="amber" aria-hidden />
          <span className="label-tech !text-[10px]">
            {msg.mode === 'agent' ? 'AGENT 推理中 · 调用外部工具' : '检索文献并生成回答'}
          </span>
        </div>
      ) : (
        <div className={cn(msg.error && 'rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3')}>
          {msg.error && (
            <div className="mb-1 flex items-center gap-1.5 text-[10px] font-medium text-destructive">
              <CircleAlert className="h-3.5 w-3.5" strokeWidth={1.75} />回答生成失败
            </div>
          )}
          <MarkdownView content={msg.content} />
          {msg.streaming && <span className="typing-cursor" aria-hidden />}
        </div>
      )}

      {/* 复制 — 悬停出现 */}
      {!msg.streaming && msg.content && (
        <div className="mt-1 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
          <button
            type="button"
            onClick={onCopy}
            className="label-tech flex h-8 items-center gap-1 rounded-[4px] px-2 !text-[9px] text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-primary" strokeWidth={1.75} />COPIED
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" strokeWidth={1.75} />COPY
              </>
            )}
          </button>
        </div>
      )}

      {/* 引用来源 — hairline 密集列表, 悬停展开片段 */}
      {msg.sources && msg.sources.length > 0 && !msg.streaming && (
        <div className="mt-2.5">
          <div className="label-tech border-t py-1.5 !text-[9px]">Citations · 引用来源 ({msg.sources.length})</div>
          <div className="divide-y border-t">
            {msg.sources.map((src) => (
              <button
                key={`${src.literatureId}-${src.chunkIndex}`}
                onClick={() => onSourceClick(src.literatureId)}
                className="group/src flex w-full items-baseline gap-2.5 px-1 py-2 text-left transition-colors hover:bg-accent/50"
                type="button"
                aria-label={`查看引用文献 ${src.title}`}
              >
                <span className="num shrink-0 text-[10px] text-primary">[{src.index}]</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[11px] font-medium">{src.title}</span>
                  <span className="label-tech mt-0.5 block !text-[9px] normal-case !tracking-normal">
                    {src.section} · CHUNK #{src.chunkIndex + 1}
                  </span>
                  <span className="mt-0.5 hidden text-[10px] leading-4 text-muted-foreground/85 group-hover/src:block line-clamp-2">
                    {src.snippet}
                  </span>
                </span>
                <span className="num shrink-0 text-[10px] text-muted-foreground">{src.score.toFixed(3)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
