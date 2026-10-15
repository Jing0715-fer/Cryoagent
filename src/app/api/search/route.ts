import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { ragSearch, type SearchMode } from '@/lib/rag';

/** POST /api/search — 混合检索 (bm25 | vector | hybrid) */
export async function POST(request: Request) {
  try {
    const start = Date.now();
    const body = (await request.json()) as { query?: string; mode?: SearchMode; limit?: number };
    const query = (body.query || '').trim();
    if (!query) return NextResponse.json({ error: '缺少 query' }, { status: 400 });
    const mode: SearchMode = body.mode && ['bm25', 'vector', 'hybrid'].includes(body.mode) ? body.mode : 'hybrid';
    const limit = Math.min(Math.max(Number(body.limit) || 10, 1), 30);

    const hits = await ragSearch(query, mode, limit);
    const latencyMs = Date.now() - start;

    // 记录搜索日志 (对应原 SearchMonitor)
    await db.searchLog
      .create({
        data: {
          query: query.slice(0, 500),
          mode,
          resultCount: hits.length,
          latencyMs,
          topScore: hits[0]?.score ?? null,
        },
      })
      .catch(() => {});

    return NextResponse.json({
      mode,
      latencyMs,
      total: hits.length,
      hits: hits.map((h) => ({
        id: h.id,
        literatureId: h.literatureId,
        chunkIndex: h.chunkIndex,
        section: h.section,
        title: h.title,
        authors: h.authors,
        score: Math.round(h.score * 10000) / 10000,
        bm25Score: h.bm25Score != null ? Math.round(h.bm25Score * 10000) / 10000 : null,
        vectorScore: h.vectorScore != null ? Math.round(h.vectorScore * 10000) / 10000 : null,
        snippet: h.snippet,
        content: h.content.slice(0, 2000),
      })),
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '搜索失败' }, { status: 500 });
  }
}

/** GET /api/search — 最近搜索日志 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = Math.min(parseInt(searchParams.get('limit') || '20') || 20, 100);
    const logs = await db.searchLog.findMany({ orderBy: { createdAt: 'desc' }, take: limit });
    return NextResponse.json({ logs });
  } catch {
    return NextResponse.json({ logs: [] });
  }
}
