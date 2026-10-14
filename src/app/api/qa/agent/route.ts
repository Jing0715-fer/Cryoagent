import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { getUserOrAnonymous } from '@/lib/auth';
import { runAgent } from '@/lib/agent';
import type { ChatMessage } from '@/lib/llm';

/**
 * POST /api/qa/agent — Agent 模式问答 (工具调用循环)
 * 对应原 routes/qa_agent.py agent_process + stream
 */
export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      question?: string;
      sessionId?: string;
      skillId?: string | null;
      history?: ChatMessage[];
    };
    const question = (body.question || '').trim();
    if (!question) return NextResponse.json({ error: '缺少 question' }, { status: 400 });

    const sessionId = body.sessionId || `agent-${Date.now()}`;
    const user = await getUserOrAnonymous();
    const history = (body.history || []).slice(-10);

    const toolCallEvents: unknown[] = [];
    const result = await runAgent(question, history, {
      skillId: body.skillId || null,
      maxSteps: 6,
      onToolCall: (record) => {
        toolCallEvents.push(record);
      },
    });

    // 保存历史
    await db.qaHistory
      .create({
        data: {
          userId: user.id === 'anonymous' ? null : user.id,
          sessionId,
          question,
          answer: result.answer,
          mode: 'agent',
          skillId: body.skillId || null,
          toolCalls: JSON.stringify(result.toolCalls),
          tokensUsed: Math.ceil(result.answer.length / 3),
          latencyMs: result.toolCalls.reduce((a, t) => a + t.latencyMs, 0),
        },
      })
      .catch(() => {});

    // 更新 Agent 会话
    const sessionMessages = [...history, { role: 'user' as const, content: question }, ...result.messages.slice(-2)];
    await db.agentSession
      .upsert({
        where: { id: sessionId },
        create: {
          id: sessionId,
          userId: user.id === 'anonymous' ? null : user.id,
          title: question.slice(0, 40),
          messages: JSON.stringify(sessionMessages),
        },
        update: {
          messages: JSON.stringify(sessionMessages),
          title: question.slice(0, 40),
          updatedAt: new Date(),
        },
      })
      .catch(() => {});

    return NextResponse.json({
      sessionId,
      answer: result.answer,
      toolCalls: result.toolCalls,
      toolCallEvents,
      contextTurns: result.messages.length,
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : 'Agent 执行失败' }, { status: 500 });
  }
}

/** GET /api/qa/agent — Agent 会话列表 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const sessionId = searchParams.get('sessionId');
    if (sessionId) {
      const session = await db.agentSession.findUnique({ where: { id: sessionId } });
      if (!session) return NextResponse.json({ error: '会话未找到' }, { status: 404 });
      return NextResponse.json({
        session: { id: session.id, title: session.title, messages: JSON.parse(session.messages), updatedAt: session.updatedAt },
      });
    }
    const sessions = await db.agentSession.findMany({
      orderBy: { updatedAt: 'desc' },
      take: 30,
      select: { id: true, title: true, updatedAt: true },
    });
    return NextResponse.json({ sessions });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}

/** DELETE /api/qa/agent?sessionId= — 删除会话 */
export async function DELETE(request: Request) {
  const { searchParams } = new URL(request.url);
  const sessionId = searchParams.get('sessionId');
  if (!sessionId) return NextResponse.json({ error: '缺少 sessionId' }, { status: 400 });
  await db.agentSession.deleteMany({ where: { id: sessionId } });
  return NextResponse.json({ success: true });
}
