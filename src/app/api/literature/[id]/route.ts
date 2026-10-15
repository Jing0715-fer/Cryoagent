import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { safeParse, invalidateRagIndex } from '@/lib/rag';
import { readFile } from 'fs/promises';
import path from 'path';

const UPLOAD_DIR = path.join(process.cwd(), 'uploads');

/** GET /api/literature/[id] — 文献详情 (含分块统计、关联结构、笔记) */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const lit = await db.literature.findUnique({
      where: { id },
      include: {
        structureLinks: {
          include: { structure: { select: { id: true, title: true, method: true, resolution: true } } },
          orderBy: { mentionCount: 'desc' },
        },
        notes: { orderBy: { createdAt: 'desc' } },
        chunks: {
          select: { id: true, chunkIndex: true, section: true, page: true, content: true, wordCount: true },
          orderBy: { chunkIndex: 'asc' },
        },
      },
    });
    if (!lit) return NextResponse.json({ error: '文献未找到' }, { status: 404 });

    const sections = new Map<string, number>();
    for (const c of lit.chunks) sections.set(c.section, (sections.get(c.section) || 0) + 1);

    return NextResponse.json({
      literature: {
        id: lit.id,
        title: lit.title,
        authors: safeParse<string[]>(lit.authors, []),
        year: lit.year,
        journal: lit.journal,
        doi: lit.doi,
        abstract: lit.abstract,
        keywords: lit.keywords,
        fileName: lit.fileName,
        fileSize: lit.fileSize,
        parseStatus: lit.parseStatus,
        chunkCount: lit.chunkCount,
        wordCount: lit.wordCount,
        isFavorite: lit.isFavorite,
        createdAt: lit.createdAt,
        updatedAt: lit.updatedAt,
      },
      chunks: lit.chunks,
      structures: lit.structureLinks.map((l) => ({
        ...l.structure,
        mentionCount: l.mentionCount,
      })),
      notes: lit.notes,
      sectionStats: [...sections.entries()].map(([section, count]) => ({ section, count })),
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}

/** PATCH /api/literature/[id] — 更新元数据 / 收藏 */
export async function PATCH(request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const body = (await request.json()) as {
      title?: string;
      journal?: string;
      year?: number;
      keywords?: string;
      isFavorite?: boolean;
      authors?: string[];
      abstract?: string;
    };
    const lit = await db.literature.update({
      where: { id },
      data: {
        ...(body.title !== undefined && { title: body.title }),
        ...(body.journal !== undefined && { journal: body.journal }),
        ...(body.year !== undefined && { year: body.year }),
        ...(body.keywords !== undefined && { keywords: body.keywords }),
        ...(body.isFavorite !== undefined && { isFavorite: body.isFavorite }),
        ...(body.authors !== undefined && { authors: JSON.stringify(body.authors) }),
        ...(body.abstract !== undefined && { abstract: body.abstract }),
      },
    });
    return NextResponse.json({ success: true, literature: { id: lit.id, title: lit.title, isFavorite: lit.isFavorite } });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '更新失败' }, { status: 500 });
  }
}

/** DELETE /api/literature/[id] — 删除文献及其分块 */
export async function DELETE(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const lit = await db.literature.findUnique({ where: { id }, select: { filePath: true } });
    if (!lit) return NextResponse.json({ error: '文献未找到' }, { status: 404 });
    await db.literature.delete({ where: { id } });
    invalidateRagIndex();
    void lit.filePath; // 文件保留以便恢复, 不物理删除
    return NextResponse.json({ success: true });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '删除失败' }, { status: 500 });
  }
}

/** PUT /api/literature/[id] — 获取原文全文文本 */
export async function PUT(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const lit = await db.literature.findUnique({ where: { id }, select: { filePath: true, fileName: true } });
    if (!lit) return NextResponse.json({ error: '文献未找到' }, { status: 404 });
    if (!lit.filePath) return NextResponse.json({ error: '无原始文件' }, { status: 404 });
    try {
      const text = await readFile(path.join(UPLOAD_DIR, lit.filePath), 'utf-8').catch(() => null);
      return NextResponse.json({ fileName: lit.fileName, text: text ? text.slice(0, 50000) : null });
    } catch {
      return NextResponse.json({ fileName: lit.fileName, text: null });
    }
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '读取失败' }, { status: 500 });
  }
}
