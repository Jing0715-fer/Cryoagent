'use client';

/**
 * CryoAgent Pro — 智能问答 (RAG 流式 + Agent 工具调用)
 * 对应原版 qa.html 的完整聊天界面
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAppStore, streamSse, api } from '@/lib/store';
import { MarkdownView } from '@/components/markdown-view';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import {
  Send, Square, Plus, BookOpen, Cpu, Sparkles, FileText, Trash2, History,
  Wrench, Clock, ChevronDown, ChevronUp, Zap, MessageSquare, Copy, Check,
  RefreshCw, PanelRightOpen, PanelRightClose, CircleAlert,
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
  { text: 'SARS-CoV-2 spike 蛋白与 ACE2 的结合亲和力如何？', icon: '🔗' },
  { text: 'Cryo-EM 达到原子分辨率需要哪些条件？', icon: '🔬' },
  { text: '比较 6M0J 和 6VXX 两个结构', icon: '⚖️' },
  { text: 'AlphaFold 的预测精度达到了什么水平？', icon: '🧬' },
];

let msgId = 0;
const nextId = () => `msg-${++msgId}-${Date.now()}`;

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
                msg.id === assistantId ? { ...msg, streaming: false, error: true, content: msg.content || `⚠️ ${message}` } : msg
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
          prev.map((msg) => (msg.id === assistantId ? { ...msg, streaming: false, error: true, content: `⚠️ ${message}` } : msg))
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

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 聊天区域 */}
      <div className="flex min-h-0 flex-1">
        {/* 主聊天 */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* 顶部工具条 */}
          <div className="flex items-center gap-2 border-b px-4 py-2">
            <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={newSession}>
              <Plus className="h-3.5 w-3.5" />新对话
            </Button>
            <div className="flex rounded-lg border p-0.5">
              <button
                type="button"
                onClick={() => setMode('rag')}
                className={cn(
                  'flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium transition-all',
                  mode === 'rag' ? 'bg-teal-600 text-white shadow-sm' : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <BookOpen className="h-3 w-3" />RAG 问答
              </button>
              <button
                type="button"
                onClick={() => setMode('agent')}
                className={cn(
                  'flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium transition-all',
                  mode === 'agent' ? 'bg-amber-600 text-white shadow-sm' : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <Cpu className="h-3 w-3" />Agent 模式
              </button>
            </div>
            {activeSkillInfo && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge variant="outline" className="max-w-[180px] gap-1 truncate border-rose-500/40 text-rose-600 dark:text-rose-400">
                    <Sparkles className="h-3 w-3" />
                    {activeSkillInfo.name}
                  </Badge>
                </TooltipTrigger>
                <TooltipContent className="max-w-xs text-xs">{activeSkillInfo.description}</TooltipContent>
              </Tooltip>
            )}
            <div className="ml-auto flex items-center gap-1">
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setShowSources(!showSources)} title="切换来源面板">
                {showSources ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
              </Button>
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setShowHistory(true)} title="历史会话">
                <History className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {/* 消息列表 */}
          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center px-6 py-10">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-500 to-emerald-600 text-white shadow-xl shadow-teal-500/20">
                  <MessageSquare className="h-7 w-7" />
                </div>
                <h2 className="mt-4 text-lg font-semibold">今天想探索什么？</h2>
                <p className="mt-1 max-w-md text-center text-sm text-muted-foreground">
                  {mode === 'rag'
                    ? '基于文献知识库的 RAG 智能问答 — 回答附带引用来源'
                    : 'Agent 模式 — AI 将自动调用结构/序列/文献工具多步推理'}
                </p>
                <div className="mt-6 grid w-full max-w-2xl gap-2.5 sm:grid-cols-2">
                  {WELCOME_PROMPTS.map((p) => (
                    <button
                      key={p.text}
                      onClick={() => void sendQuestion(p.text)}
                      className="group flex items-center gap-3 rounded-xl border bg-card px-4 py-3 text-left text-sm transition-all hover:border-teal-500/50 hover:shadow-md"
                      type="button"
                    >
                      <span className="text-lg">{p.icon}</span>
                      <span className="flex-1 text-muted-foreground group-hover:text-foreground">{p.text}</span>
                    </button>
                  ))}
                </div>
                {/* 技能快捷入口 */}
                {skills.length > 0 && (
                  <div className="mt-6 w-full max-w-2xl">
                    <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                      <Sparkles className="h-3 w-3" />专家技能快捷启动
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {skills.slice(0, 8).map((s) => (
                        <button
                          key={s.id}
                          onClick={() => setActiveSkill(activeSkill === s.id ? null : s.id)}
                          className={cn(
                            'rounded-full border px-2.5 py-1 text-[11px] transition-all',
                            activeSkill === s.id
                              ? 'border-rose-500/50 bg-rose-500/10 text-rose-600 dark:text-rose-400'
                              : 'text-muted-foreground hover:border-teal-500/40 hover:text-foreground'
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
              <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
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

          {/* 输入区 */}
          <div className="border-t bg-background/95 px-4 py-3 backdrop-blur">
            <div className="mx-auto max-w-3xl">
              <div className="relative rounded-xl border bg-card shadow-sm transition-colors focus-within:border-teal-500/60">
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
                  placeholder={mode === 'agent' ? 'Agent 模式: 例如 "比较 6M0J 和 6VXX 的结构"...' : '输入问题, Enter 发送 (Shift+Enter 换行)...'}
                  className="max-h-40 w-full resize-none rounded-xl bg-transparent px-4 pb-10 pt-3 text-sm outline-none placeholder:text-muted-foreground/60"
                  disabled={busy}
                />
                <div className="absolute bottom-2 left-3 flex items-center gap-2">
                  {activeSkillInfo && (
                    <button
                      type="button"
                      onClick={() => setActiveSkill(null)}
                      className="flex items-center gap-1 rounded-full bg-rose-500/10 px-2 py-0.5 text-[10px] text-rose-600 dark:text-rose-400 hover:bg-rose-500/20"
                    >
                      <Sparkles className="h-2.5 w-2.5" />
                      {activeSkillInfo.name} ✕
                    </button>
                  )}
                  {busy && (
                    <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                      <RefreshCw className="h-3 w-3 animate-spin" />
                      {mode === 'agent' ? 'Agent 推理中 (可能需要 1-2 分钟)...' : '生成中...'}
                    </span>
                  )}
                </div>
                <div className="absolute bottom-2 right-2.5 flex gap-1.5">
                  {busy ? (
                    <Button size="icon" variant="destructive" className="h-7 w-7 rounded-lg" onClick={stopStreaming}>
                      <Square className="h-3.5 w-3.5" />
                    </Button>
                  ) : (
                    <Button
                      size="icon"
                      className="h-7 w-7 rounded-lg bg-teal-600 hover:bg-teal-700"
                      onClick={() => void sendQuestion()}
                      disabled={!input.trim()}
                    >
                      <Send className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              </div>
              <p className="mt-1.5 text-center text-[10px] text-muted-foreground">
                {mode === 'rag' ? 'AI 可能出错, 请核实重要信息 · 回答基于本地文献库' : 'Agent 将调用 11 个专业工具进行多步推理'}
              </p>
            </div>
          </div>
        </div>

        {/* 右侧来源面板 */}
        {showSources && (
          <aside className="hidden w-[300px] shrink-0 border-l bg-card/30 lg:block">
            <div className="flex h-full flex-col">
              <div className="border-b px-4 py-3">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold">
                  <FileText className="h-3.5 w-3.5 text-teal-600" />
                  检索来源
                </h3>
                <p className="mt-0.5 text-[10px] text-muted-foreground">最新回答引用的文献片段</p>
              </div>
              <ScrollArea className="flex-1">
                <div className="space-y-2 p-3">
                  {(() => {
                    const lastWithSources = [...messages].reverse().find((m) => m.sources && m.sources.length > 0);
                    if (!lastWithSources?.sources) {
                      return (
                        <div className="flex flex-col items-center justify-center gap-2 py-16 text-center text-xs text-muted-foreground">
                          <BookOpen className="h-8 w-8 opacity-30" />
                          提问后将显示相关文献片段
                        </div>
                      );
                    }
                    return lastWithSources.sources.map((src) => (
                      <button
                        key={`${src.literatureId}-${src.chunkIndex}`}
                        onClick={() => navigate('literature-detail', { id: src.literatureId })}
                        className="w-full rounded-lg border bg-card p-3 text-left transition-all hover:border-teal-500/50 hover:shadow-sm"
                        type="button"
                      >
                        <div className="flex items-start gap-2">
                          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-teal-600/10 text-[10px] font-bold text-teal-700 dark:text-teal-400">
                            {src.index}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-[11px] font-medium">{src.title}</div>
                            <div className="mt-0.5 flex items-center gap-1.5 text-[9px] text-muted-foreground">
                              <span>{src.section}</span>
                              <span>·</span>
                              <span>块 #{src.chunkIndex + 1}</span>
                              <span className="ml-auto font-mono text-teal-600 dark:text-teal-400">{src.score.toFixed(3)}</span>
                            </div>
                            <p className="mt-1.5 line-clamp-3 text-[10px] leading-4 text-muted-foreground">{src.snippet}</p>
                          </div>
                        </div>
                      </button>
                    ));
                  })()}
                </div>
              </ScrollArea>
            </div>
          </aside>
        )}
      </div>

      {/* 历史会话抽屉 */}
      <Dialog open={showHistory} onOpenChange={setShowHistory}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              <History className="h-4 w-4 text-teal-600" />历史会话
            </DialogTitle>
          </DialogHeader>
          <ScrollArea className="max-h-[60vh]">
            <div className="space-y-1.5">
              {historySessions.length === 0 ? (
                <div className="py-10 text-center text-xs text-muted-foreground">暂无历史会话</div>
              ) : (
                historySessions.map((s) => (
                  <button
                    key={s.sessionId}
                    onClick={() => void loadSession(s.sessionId)}
                    className={cn(
                      'flex w-full items-center gap-2.5 rounded-lg border p-2.5 text-left transition-all hover:border-teal-500/50 hover:shadow-sm',
                      s.sessionId === sessionId && 'border-teal-500/50 bg-teal-500/5'
                    )}
                    type="button"
                  >
                    <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium">{s.question}</div>
                      <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                        <span>{s.count} 轮对话</span>
                        <span>·</span>
                        <span>{new Date(s.lastAt).toLocaleDateString('zh-CN')}</span>
                        {s.mode === 'agent' && <Badge className="h-4 px-1 text-[8px]">AGENT</Badge>}
                      </div>
                    </div>
                  </button>
                ))
              )}
            </div>
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** 消息气泡 */
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
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-teal-600 px-4 py-2.5 text-sm text-white shadow-sm">
          {msg.content}
        </div>
      </div>
    );
  }

  const toolsExpanded = expandedTools.has(msg.id);

  return (
    <div className="group">
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 text-white shadow-md shadow-teal-500/20">
          {msg.mode === 'agent' ? <Cpu className="h-4 w-4" /> : <BookOpen className="h-4 w-4" />}
        </div>
        <div className="min-w-0 flex-1">
          {/* 头部 */}
          <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
            <span className="font-medium text-foreground">CryoAgent</span>
            {msg.skillName && (
              <Badge variant="outline" className="h-4 gap-1 border-rose-500/40 px-1.5 text-[9px] text-rose-600 dark:text-rose-400">
                <Sparkles className="h-2.5 w-2.5" />
                {msg.skillName}
              </Badge>
            )}
            {msg.mode === 'agent' && <Badge variant="outline" className="h-4 px-1.5 text-[9px] text-amber-600 dark:text-amber-400">AGENT</Badge>}
            {msg.latencyMs != null && (
              <span className="flex items-center gap-0.5">
                <Clock className="h-2.5 w-2.5" />
                {(msg.latencyMs / 1000).toFixed(1)}s
              </span>
            )}
            {msg.tokensUsed != null && <span>· {msg.tokensUsed} tokens</span>}
          </div>

          {/* 工具调用展示 */}
          {msg.toolCalls && msg.toolCalls.length > 0 && (
            <div className="mb-2 overflow-hidden rounded-lg border border-amber-500/30 bg-amber-500/5">
              <button
                type="button"
                onClick={onToggleTool}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[11px] font-medium text-amber-700 dark:text-amber-400 hover:bg-amber-500/10"
              >
                <Wrench className="h-3.5 w-3.5" />
                调用了 {msg.toolCalls.length} 个工具
                <span className="flex gap-1">
                  {msg.toolCalls.map((tc, i) => (
                    <span key={i} className="rounded bg-amber-500/15 px-1.5 py-0.5 font-mono text-[9px]">{tc.tool}</span>
                  ))}
                </span>
                {toolsExpanded ? <ChevronUp className="ml-auto h-3 w-3" /> : <ChevronDown className="ml-auto h-3 w-3" />}
              </button>
              {toolsExpanded && (
                <div className="space-y-1.5 border-t border-amber-500/20 p-2.5">
                  {msg.toolCalls.map((tc, i) => (
                    <div key={i} className="rounded-md bg-background/80 p-2 text-[10px]">
                      <div className="flex items-center gap-1.5">
                        <Zap className={cn('h-3 w-3', tc.ok ? 'text-emerald-500' : 'text-red-500')} />
                        <span className="font-mono font-semibold text-foreground">{tc.tool}</span>
                        <span className="ml-auto font-mono text-muted-foreground">{tc.latencyMs}ms</span>
                      </div>
                      <div className="mt-1 font-mono text-[9px] text-muted-foreground">
                        参数: {JSON.stringify(tc.params).slice(0, 120)}
                      </div>
                      <div className="mt-1 whitespace-pre-wrap break-all font-mono text-[9px] text-muted-foreground">
                        结果: {tc.resultSummary.slice(0, 300)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 内容 */}
          <div
            className={cn(
              'rounded-2xl rounded-tl-md border bg-card px-4 py-3 shadow-sm',
              msg.error && 'border-red-500/40 bg-red-500/5'
            )}
          >
            {msg.streaming && !msg.content ? (
              <div className="flex items-center gap-2 py-1">
                <span className="h-2 w-2 animate-pulse rounded-full bg-teal-500" />
                <span className="h-2 w-2 animate-pulse rounded-full bg-teal-500 [animation-delay:150ms]" />
                <span className="h-2 w-2 animate-pulse rounded-full bg-teal-500 [animation-delay:300ms]" />
                <span className="ml-2 text-xs text-muted-foreground">
                  {msg.mode === 'agent' ? 'Agent 正在思考并调用工具...' : '正在检索文献并生成回答...'}
                </span>
              </div>
            ) : (
              <>
                {msg.error && <CircleAlert className="mb-1 h-4 w-4 text-red-500" />}
                <MarkdownView content={msg.content} />
                {msg.streaming && <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-teal-500 align-middle" />}
              </>
            )}
          </div>

          {/* 操作按钮 */}
          {!msg.streaming && msg.content && (
            <div className="mt-1.5 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
              <Button variant="ghost" size="sm" className="h-6 gap-1 px-2 text-[10px] text-muted-foreground" onClick={onCopy}>
                {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                {copied ? '已复制' : '复制'}
              </Button>
            </div>
          )}

          {/* 来源引用 */}
          {msg.sources && msg.sources.length > 0 && !msg.streaming && (
            <div className="mt-2.5">
              <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground">
                <FileText className="h-3 w-3" />
                引用来源 ({msg.sources.length})
              </div>
              <div className="space-y-1">
                {msg.sources.map((src) => (
                  <button
                    key={`${src.literatureId}-${src.chunkIndex}`}
                    onClick={() => onSourceClick(src.literatureId)}
                    className="flex w-full items-start gap-2 rounded-lg border bg-muted/40 px-2.5 py-1.5 text-left transition-colors hover:border-teal-500/40 hover:bg-muted"
                    type="button"
                  >
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded bg-teal-600/15 text-[9px] font-bold text-teal-700 dark:text-teal-400">
                      {src.index}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[10px] font-medium">{src.title}</div>
                      <div className="truncate text-[9px] text-muted-foreground">{src.snippet}</div>
                    </div>
                    <Trash2 className="hidden h-3 w-3" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
