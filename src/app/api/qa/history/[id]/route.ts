import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { safeParse } from '@/lib/rag';

/** GET /api/qa/history/[id] — 单条问答详情 */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const item = await db.qaHistory.findUnique({ where: { id } });
    if (!item) return NextResponse.json({ error: '未找到' }, { status: 404 });
    return NextResponse.json({
      item: {
        ...item,
        sources: safeParse(item.sources, []),
        toolCalls: safeParse(item.toolCalls, []),
      },
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}

/** DELETE /api/qa/history/[id] */
export async function DELETE(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  await db.qaHistory.delete({ where: { id } });
  return NextResponse.json({ success: true });
}
