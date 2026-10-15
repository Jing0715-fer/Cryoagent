import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { safeParse } from '@/lib/rag';
import { getUserOrAnonymous } from '@/lib/auth';
import { parsePdf, parseTextFile, chunkDocument, extractPdbIds, extractUniprotIds } from '@/lib/document-parser';
import { invalidateRagIndex } from '@/lib/rag';
import { writeFile, mkdir } from 'fs/promises';
import path from 'path';
import crypto from 'crypto';

const UPLOAD_DIR = path.join(process.cwd(), 'uploads');

/** GET /api/literature — 文献列表 (分页/搜索/排序) */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const q = searchParams.get('q') || '';
    const page = Math.max(1, parseInt(searchParams.get('page') || '1') || 1);
    const pageSize = Math.min(50, Math.max(5, parseInt(searchParams.get('pageSize') || '12')));
    const sort = searchParams.get('sort') || 'recent';
    const favorite = searchParams.get('favorite');

    const where: Record<string, unknown> = {};
    if (q) {
      where.OR = [
        { title: { contains: q } },
        { abstract: { contains: q } },
        { authors: { contains: q } },
        { journal: { contains: q } },
        { keywords: { contains: q } },
      ];
    }
    if (favorite === 'true') where.isFavorite = true;

    const orderBy: Record<string, string> =
      sort === 'year' ? { year: 'desc' } : sort === 'title' ? { title: 'asc' } : { createdAt: 'desc' };

    const [total, items] = await Promise.all([
      db.literature.count({ where }),
      db.literature.findMany({
        where,
        orderBy,
        skip: (page - 1) * pageSize,
        take: pageSize,
        select: {
          id: true,
          title: true,
          authors: true,
          year: true,
          journal: true,
          doi: true,
          abstract: true,
          keywords: true,
          parseStatus: true,
          chunkCount: true,
          wordCount: true,
          fileSize: true,
          isFavorite: true,
          createdAt: true,
          _count: { select: { structureLinks: true, notes: true } },
        },
      }),
    ]);

    return NextResponse.json({
      total,
      page,
      pageSize,
      items: items.map((l) => ({
        ...l,
        authors: safeParse<string[]>(l.authors, []),
        structureCount: l._count.structureLinks,
        noteCount: l._count.notes,
      })),
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}

/** POST /api/literature — 上传 PDF/TXT 并解析索引 */
export async function POST(request: Request) {
  try {
    const user = await getUserOrAnonymous();
    const formData = await request.formData();
    const file = formData.get('file') as File | null;
    if (!file) {
      return NextResponse.json({ error: '未收到文件' }, { status: 400 });
    }
    const isPdf = file.name.toLowerCase().endsWith('.pdf');
    const isText = /\.(txt|md|text)$/i.test(file.name);
    if (!isPdf && !isText) {
      return NextResponse.json({ error: '仅支持 PDF / TXT / MD 文件' }, { status: 400 });
    }
    if (file.size > 30 * 1024 * 1024) {
      return NextResponse.json({ error: '文件超过 30MB 限制' }, { status: 400 });
    }

    await mkdir(UPLOAD_DIR, { recursive: true });
    const storedName = `${crypto.randomUUID()}${path.extname(file.name)}`;
    const filePath = path.join(UPLOAD_DIR, storedName);
    const buffer = Buffer.from(await file.arrayBuffer());
    await writeFile(filePath, buffer);

    // 解析
    let parsed;
    try {
      parsed = isPdf ? await parsePdf(filePath) : await parseTextFile(filePath);
    } catch (err) {
      return NextResponse.json(
        { error: `解析失败: ${err instanceof Error ? err.message : '未知错误'}` },
        { status: 422 }
      );
    }

    const chunks = chunkDocument(parsed);
    const pdbIds = extractPdbIds(parsed.fullText);
    const uniprotIds = extractUniprotIds(parsed.fullText);
    const titleOverride = (formData.get('title') as string) || '';

    const lit = await db.literature.create({
      data: {
        title: titleOverride || parsed.metadata.title || file.name.replace(/\.[^.]+$/, ''),
        authors: JSON.stringify(parsed.metadata.authors || []),
        year: parsed.metadata.year,
        journal: null,
        doi: parsed.metadata.doi,
        abstract: parsed.sections.find((s) => s.section === 'abstract')?.content.slice(0, 1500) || null,
        fileName: file.name,
        filePath: storedName,
        fileSize: file.size,
        parseStatus: 'parsed',
        chunkCount: chunks.length,
        wordCount: parsed.wordCount,
      },
    });

    if (chunks.length > 0) {
      await db.literatureChunk.createMany({
        data: chunks.map((c) => ({
          literatureId: lit.id,
          chunkIndex: c.chunkIndex,
          section: c.section,
          page: c.page,
          content: c.content,
          wordCount: c.wordCount,
        })),
      });
    }

    // 自动关联结构: 验证提取的 PDB ID
    let linkedStructures = 0;
    for (const pdbId of pdbIds.slice(0, 15)) {
      try {
        const local = await db.structure.findUnique({ where: { id: pdbId } });
        if (!local) {
          // 不主动拉 RCSB (慢), 只登记占位
          await db.structure.upsert({
            where: { id: pdbId },
            create: { id: pdbId, title: `${pdbId} (待更新)`, source: 'auto-extracted' },
            update: {},
          });
        }
        await db.structureLink.upsert({
          where: { literatureId_structureId: { literatureId: lit.id, structureId: pdbId } },
          create: { literatureId: lit.id, structureId: pdbId },
          update: { mentionCount: { increment: 1 } },
        });
        linkedStructures++;
      } catch {
        /* skip */
      }
    }

    invalidateRagIndex();

    return NextResponse.json({
      success: true,
      literature: {
        id: lit.id,
        title: lit.title,
        chunkCount: chunks.length,
        wordCount: parsed.wordCount,
        pageCount: parsed.pageCount,
      },
      detected: {
        pdbIds,
        uniprotIds,
        linkedStructures,
        metadata: parsed.metadata,
        uploadedBy: user.username,
      },
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '上传失败' }, { status: 500 });
  }
}
