import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { ragSearch, safeParse, invalidateRagIndex } from '@/lib/rag';

/**
 * RAG 检索质量评估 (对应原 routes/rag_evaluation.py)
 * GET  — 列出 runs / ground truth
 * POST — 运行评估: 对某 query 执行检索, 与 ground truth 对比计算 precision/recall/F1/MRR
 * PUT  — 添加 ground truth
 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const view = searchParams.get('view') || 'all';
    const limit = Math.min(parseInt(searchParams.get('limit') || '50') || 50, 200);

    if (view === 'ground-truth' || view === 'all') {
      const groundTruths = await db.groundTruth.findMany({ orderBy: { createdAt: 'desc' }, take: limit });
      if (view === 'ground-truth') {
        return NextResponse.json({
          groundTruths: groundTruths.map((g) => ({
            ...g,
            relevantChunkIds: safeParse(g.relevantChunkIds, [] as string[]),
          })),
        });
      }
      const runs = await db.evaluationRun.findMany({ orderBy: { createdAt: 'desc' }, take: limit });
      // 监控统计 (对应原 SearchMonitor)
      const searchLogs = await db.searchLog.findMany({ orderBy: { createdAt: 'desc' }, take: 200 });
      const avgLatency = searchLogs.length > 0 ? Math.round(searchLogs.reduce((a, l) => a + l.latencyMs, 0) / searchLogs.length) : null;
      const zeroResultRate = searchLogs.length > 0 ? searchLogs.filter((l) => l.resultCount === 0).length / searchLogs.length : 0;
      const popularQueries = new Map<string, number>();
      for (const l of searchLogs) popularQueries.set(l.query, (popularQueries.get(l.query) || 0) + 1);

      return NextResponse.json({
        runs: runs.map((r) => ({ ...r, details: safeParse(r.details, null) })),
        groundTruths: groundTruths.map((g) => ({
          ...g,
          relevantChunkIds: safeParse(g.relevantChunkIds, [] as string[]),
        })),
        monitor: {
          totalSearches: searchLogs.length,
          avgLatency,
          zeroResultRate: Math.round(zeroResultRate * 1000) / 10,
          popularQueries: [...popularQueries.entries()]
            .map(([query, count]) => ({ query, count }))
            .sort((a, b) => b.count - a.count)
            .slice(0, 10),
        },
      });
    }

    const runs = await db.evaluationRun.findMany({ orderBy: { createdAt: 'desc' }, take: limit });
    return NextResponse.json({ runs: runs.map((r) => ({ ...r, details: safeParse(r.details, null) })) });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      query?: string;
      mode?: 'bm25' | 'vector' | 'hybrid';
      groundTruthId?: string;
      relevantChunkIds?: string[];
      autoGroundTruth?: boolean; // 把当前检索结果记为 ground truth
    };
    const query = (body.query || '').trim();
    if (!query) return NextResponse.json({ error: '缺少 query' }, { status: 400 });
    const mode = body.mode || 'hybrid';

    // ground truth 解析
    let relevantIds: string[] = [];
    let groundTruthId = body.groundTruthId || null;
    if (groundTruthId) {
      const gt = await db.groundTruth.findUnique({ where: { id: groundTruthId } });
      if (gt) relevantIds = safeParse(gt.relevantChunkIds, []);
    } else if (body.relevantChunkIds?.length) {
      relevantIds = body.relevantChunkIds;
    } else {
      const gt = await db.groundTruth.findUnique({ where: { query } });
      if (gt) {
        relevantIds = safeParse(gt.relevantChunkIds, []);
        groundTruthId = gt.id;
      }
    }

    // 执行检索
    const start = Date.now();
    const hits = await ragSearch(query, mode, 10);
    const latencyMs = Date.now() - start;
    const retrievedIds = hits.map((h) => h.id);

    if (relevantIds.length === 0 && body.autoGroundTruth && retrievedIds.length > 0) {
      // 自动记录 ground truth (top 5)
      relevantIds = retrievedIds.slice(0, 5);
      const gt = await db.groundTruth.upsert({
        where: { query },
        create: { query, relevantChunkIds: JSON.stringify(relevantIds), notes: '自动生成 (top-5)' },
        update: { relevantChunkIds: JSON.stringify(relevantIds) },
      });
      groundTruthId = gt.id;
    }

    // 指标计算
    let precision = 0;
    let recall = 0;
    let f1 = 0;
    let mrr = 0;
    let hitRate = 0;

    if (relevantIds.length > 0) {
      const relevantSet = new Set(relevantIds);
      const retrievedSet = new Set(retrievedIds);
      const intersection = [...retrievedSet].filter((id) => relevantSet.has(id));
      precision = retrievedSet.size > 0 ? intersection.length / retrievedSet.size : 0;
      recall = relevantSet.size > 0 ? intersection.length / relevantSet.size : 0;
      f1 = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0;
      // MRR
      for (let i = 0; i < retrievedIds.length; i++) {
        if (relevantSet.has(retrievedIds[i])) {
          mrr = 1 / (i + 1);
          hitRate = 1;
          break;
        }
      }
    }

    const run = await db.evaluationRun.create({
      data: {
        query,
        groundTruthId,
        mode,
        precision: relevantIds.length > 0 ? Math.round(precision * 10000) / 100 : null,
        recall: relevantIds.length > 0 ? Math.round(recall * 10000) / 100 : null,
        f1: relevantIds.length > 0 ? Math.round(f1 * 10000) / 100 : null,
        mrr: relevantIds.length > 0 ? Math.round(mrr * 10000) / 100 : null,
        hitRate: relevantIds.length > 0 ? hitRate * 100 : null,
        latencyMs,
        resultCount: retrievedIds.length,
        details: JSON.stringify({
          retrieved: hits.map((h, i) => ({
            rank: i + 1,
            id: h.id,
            literatureId: h.literatureId,
            title: h.title,
            score: Math.round(h.score * 10000) / 10000,
            relevant: relevantIds.includes(h.id),
          })),
          relevantIds,
          hasGroundTruth: relevantIds.length > 0,
        }),
      },
    });

    return NextResponse.json({
      runId: run.id,
      query,
      mode,
      latencyMs,
      hasGroundTruth: relevantIds.length > 0,
      metrics: {
        precision: relevantIds.length > 0 ? Math.round(precision * 10000) / 100 : null,
        recall: relevantIds.length > 0 ? Math.round(recall * 10000) / 100 : null,
        f1: relevantIds.length > 0 ? Math.round(f1 * 10000) / 100 : null,
        mrr: relevantIds.length > 0 ? Math.round(mrr * 10000) / 100 : null,
        hitRate: relevantIds.length > 0 ? hitRate * 100 : null,
      },
      retrieved: hits.map((h, i) => ({
        rank: i + 1,
        id: h.id,
        literatureId: h.literatureId,
        title: h.title,
        section: h.section,
        score: Math.round(h.score * 10000) / 10000,
        snippet: h.snippet,
        relevant: relevantIds.includes(h.id),
      })),
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '评估失败' }, { status: 500 });
  }
}

/** PUT — 手动添加 ground truth */
export async function PUT(request: Request) {
  try {
    const body = (await request.json()) as { query?: string; relevantChunkIds?: string[]; notes?: string };
    const query = (body.query || '').trim();
    if (!query) return NextResponse.json({ error: '缺少 query' }, { status: 400 });
    const ids = body.relevantChunkIds || [];
    const gt = await db.groundTruth.upsert({
      where: { query },
      create: { query, relevantChunkIds: JSON.stringify(ids), notes: body.notes },
      update: { relevantChunkIds: JSON.stringify(ids), notes: body.notes },
    });
    return NextResponse.json({ success: true, groundTruth: { ...gt, relevantChunkIds: ids } });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '保存失败' }, { status: 500 });
  }
}

/** DELETE — 删除评估 run 或 ground truth */
export async function DELETE(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const runId = searchParams.get('runId');
    const groundTruthId = searchParams.get('groundTruthId');
    if (runId) await db.evaluationRun.delete({ where: { id: runId } });
    else if (groundTruthId) await db.groundTruth.delete({ where: { id: groundTruthId } });
    else return NextResponse.json({ error: '缺少 runId 或 groundTruthId' }, { status: 400 });
    return NextResponse.json({ success: true });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '删除失败' }, { status: 500 });
  }
}

void invalidateRagIndex;
