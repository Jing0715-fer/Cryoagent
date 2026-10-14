import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { getUserOrAnonymous } from '@/lib/auth';

/** GET /api/notes — 笔记列表 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const literatureId = searchParams.get('literatureId');
    const notes = await db.note.findMany({
      where: literatureId ? { literatureId } : undefined,
      orderBy: { createdAt: 'desc' },
      take: 100,
      include: { literature: { select: { id: true, title: true } } },
    });
    return NextResponse.json({
      notes: notes.map((n) => ({
        id: n.id,
        literatureId: n.literatureId,
        literatureTitle: n.literature?.title,
        content: n.content,
        anchor: n.anchor,
        createdAt: n.createdAt,
      })),
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}

/** POST /api/notes — 新建笔记 (新增功能: 文献阅读笔记) */
export async function POST(request: Request) {
  try {
    const user = await getUserOrAnonymous();
    const body = (await request.json()) as { literatureId?: string; content?: string; anchor?: string };
    if (!body.content?.trim()) return NextResponse.json({ error: '笔记内容为空' }, { status: 400 });
    const note = await db.note.create({
      data: {
        userId: user.id === 'anonymous' ? null : user.id,
        literatureId: body.literatureId || null,
        content: body.content.trim().slice(0, 5000),
        anchor: body.anchor,
      },
    });
    return NextResponse.json({ success: true, note });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '创建失败' }, { status: 500 });
  }
}

/** DELETE /api/notes?id= — 删除笔记 */
export async function DELETE(request: Request) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get('id');
  if (!id) return NextResponse.json({ error: '缺少 id' }, { status: 400 });
  await db.note.delete({ where: { id } });
  return NextResponse.json({ success: true });
}
