import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { safeParse } from '@/lib/rag';

/** GET /api/qa/history — 问答历史 (按会话分组) */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const sessionId = searchParams.get('sessionId');
    const limit = Math.min(parseInt(searchParams.get('limit') || '50'), 200);
    const mode = searchParams.get('mode');

    if (sessionId) {
      const items = await db.qaHistory.findMany({
        where: { sessionId },
        orderBy: { createdAt: 'asc' },
      });
      return NextResponse.json({
        items: items.map((h) => ({
          ...h,
          sources: safeParse(h.sources, []),
          toolCalls: safeParse(h.toolCalls, []),
        })),
      });
    }

    const where = mode ? { mode } : {};
    const items = await db.qaHistory.findMany({
      where,
      orderBy: { createdAt: 'desc' },
      take: limit,
    });

    // 按会话分组
    const sessions = new Map<string, { sessionId: string; question: string; count: number; lastAt: string; mode: string }>();
    for (const h of items) {
      const existing = sessions.get(h.sessionId);
      if (existing) {
        existing.count++;
        existing.lastAt = h.createdAt.toISOString();
      } else {
        sessions.set(h.sessionId, {
          sessionId: h.sessionId,
          question: h.question,
          count: 1,
          lastAt: h.createdAt.toISOString(),
          mode: h.mode,
        });
      }
    }

    return NextResponse.json({
      total: items.length,
      sessions: [...sessions.values()].slice(0, 40),
      items: items.map((h) => ({
        id: h.id,
        sessionId: h.sessionId,
        question: h.question,
        answer: h.answer.slice(0, 200),
        mode: h.mode,
        skillId: h.skillId,
        createdAt: h.createdAt,
      })),
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}
