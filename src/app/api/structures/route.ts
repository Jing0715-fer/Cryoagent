import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { searchRcsbStructures } from '@/lib/bio-apis';
import { safeParse } from '@/lib/rag';

/** GET /api/structures — 本地结构缓存列表 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const q = searchParams.get('q') || '';
    const page = Math.max(1, parseInt(searchParams.get('page') || '1'));
    const pageSize = Math.min(60, parseInt(searchParams.get('pageSize') || '24'));
    const method = searchParams.get('method');

    const where: Record<string, unknown> = {};
    if (q) where.OR = [{ id: { contains: q.toUpperCase() } }, { title: { contains: q } }];
    if (method) where.method = { contains: method };

    const [total, items] = await Promise.all([
      db.structure.count({ where }),
      db.structure.findMany({
        where,
        orderBy: { updatedAt: 'desc' },
        skip: (page - 1) * pageSize,
        take: pageSize,
        include: { _count: { select: { literatureLinks: true } } },
      }),
    ]);

    return NextResponse.json({
      total,
      page,
      pageSize,
      items: items.map((s) => ({
        id: s.id,
        title: s.title,
        method: s.method,
        resolution: s.resolution,
        organism: s.organism,
        entityCount: s.entityCount,
        residueCount: s.residueCount,
        uniprotIds: safeParse(s.uniprotIds, [] as { uniprotId: string; proteinName: string }[]),
        literatureCount: s._count.literatureLinks,
        accessCount: s.accessCount,
        source: s.source,
        updatedAt: s.updatedAt,
      })),
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}

/** POST /api/structures — RCSB 远程搜索 (对应原 search_structures) */
export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { query?: string; limit?: number };
    const query = (body.query || '').trim();
    if (!query) return NextResponse.json({ error: '缺少 query' }, { status: 400 });
    const limit = Math.min(Math.max(Number(body.limit) || 12, 1), 30);
    const hits = await searchRcsbStructures(query, limit);

    // 标记本地已有的
    const localIds = new Set(hits.length ? await db.structure.findMany({ where: { id: { in: hits.map((h) => h.identifier) } }, select: { id: true } }).then((r) => r.map((x) => x.id)) : []);

    return NextResponse.json({
      query,
      total: hits.length,
      hits: hits.map((h) => ({ ...h, cached: localIds.has(h.identifier) })),
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : 'RCSB 搜索失败' }, { status: 502 });
  }
}
