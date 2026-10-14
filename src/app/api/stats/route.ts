import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { getRagStats } from '@/lib/rag';

/**
 * GET /api/stats — 平台统计仪表盘 (对应原 routes/utils.py stats)
 */
export async function GET() {
  try {
    const [
      literatureCount,
      chunkCount,
      structureCount,
      qaCount,
      agentCount,
      skillCount,
      alignmentCount,
      linkCount,
      noteCount,
      userCount,
      searchLogCount,
    ] = await Promise.all([
      db.literature.count(),
      db.literatureChunk.count(),
      db.structure.count(),
      db.qaHistory.count(),
      db.qaHistory.count({ where: { mode: 'agent' } }),
      db.skill.count(),
      db.alignmentTask.count(),
      db.structureLink.count(),
      db.note.count(),
      db.user.count(),
      db.searchLog.count(),
    ]);

    // 最近 14 天 QA 活跃
    const since = new Date(Date.now() - 14 * 24 * 3600 * 1000);
    const recentQa = await db.qaHistory.findMany({
      where: { createdAt: { gte: since } },
      select: { createdAt: true, mode: true },
      orderBy: { createdAt: 'asc' },
    });
    const qaByDay = new Map<string, { date: string; rag: number; agent: number }>();
    for (let i = 13; i >= 0; i--) {
      const d = new Date(Date.now() - i * 24 * 3600 * 1000);
      const key = d.toISOString().slice(5, 10);
      qaByDay.set(key, { date: key, rag: 0, agent: 0 });
    }
    for (const q of recentQa) {
      const key = q.createdAt.toISOString().slice(5, 10);
      const entry = qaByDay.get(key);
      if (entry) {
        if (q.mode === 'agent') entry.agent++;
        else entry.rag++;
      }
    }

    // 结构方法分布
    const methodStats = await db.structure.groupBy({
      by: ['method'],
      _count: { id: true },
      orderBy: { _count: { id: 'desc' } },
      take: 8,
    });

    // 热门结构
    const popularStructures = await db.structureLink.groupBy({
      by: ['structureId'],
      _count: { literatureId: true },
      orderBy: { _count: { literatureId: 'desc' } },
      take: 8,
    });

    // 文献年份分布
    const yearStats = await db.literature.groupBy({
      by: ['year'],
      _count: { id: true },
      orderBy: { year: 'asc' },
      take: 12,
    });

    // 最近搜索
    const recentSearches = await db.searchLog.findMany({ orderBy: { createdAt: 'desc' }, take: 8 });

    // 最近问答
    const recentQaItems = await db.qaHistory.findMany({
      orderBy: { createdAt: 'desc' },
      take: 8,
      select: { id: true, question: true, mode: true, createdAt: true, latencyMs: true },
    });

    // 平均检索延迟
    let searchAvgLatency: number | null = null;
    try {
      const agg = await db.searchLog.aggregate({ _avg: { latencyMs: true } });
      searchAvgLatency = agg._avg.latencyMs;
    } catch {
      searchAvgLatency = null;
    }

    const ragStats = await getRagStats().catch(() => ({ chunkCount: 0, literatureCount: 0, indexAge: 0 }));

    return NextResponse.json({
      totals: {
        literature: literatureCount,
        chunks: chunkCount,
        structures: structureCount,
        qa: qaCount,
        agentQa: agentCount,
        skills: skillCount,
        alignments: alignmentCount,
        links: linkCount,
        notes: noteCount,
        users: userCount,
        searches: searchLogCount,
      },
      qaActivity: [...qaByDay.values()],
      methodStats: methodStats.map((m) => ({ method: m.method || '未知', count: m._count.id })),
      popularStructures: popularStructures.map((p) => ({ id: p.structureId, links: p._count.literatureId })),
      yearStats: yearStats.filter((y) => y.year).map((y) => ({ year: y.year, count: y._count.id })),
      recentSearches: recentSearches.map((s) => ({ query: s.query, mode: s.mode, latencyMs: s.latencyMs, createdAt: s.createdAt })),
      recentQa: recentQaItems,
      searchAvgLatency: searchAvgLatency != null ? Math.round(searchAvgLatency) : null,
      ragIndex: ragStats,
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '统计失败' }, { status: 500 });
  }
}
