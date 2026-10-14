import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { safeParse } from '@/lib/rag';
import { quickSimilarity } from '@/lib/alignment';

/**
 * GET /api/kg — 知识图谱全局数据 (nodes + edges + stats)
 * 对应原 routes/kg.py + core/structure_knowledge_graph.py
 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const view = searchParams.get('view') || 'global';
    const limit = Math.min(parseInt(searchParams.get('limit') || '150'), 400);

    if (view === 'stats') {
      const [structureCount, litCount, linkCount, popular] = await Promise.all([
        db.structure.count(),
        db.literature.count(),
        db.structureLink.count(),
        db.structureLink.groupBy({
          by: ['structureId'],
          _count: { literatureId: true },
          orderBy: { _count: { literatureId: 'desc' } },
          take: 10,
        }),
      ]);
      const popularDetailed = await Promise.all(
        popular.map(async (p) => {
          const s = await db.structure.findUnique({ where: { id: p.structureId }, select: { title: true, method: true } });
          return { id: p.structureId, title: s?.title || p.structureId, method: s?.method, linkCount: p._count.literatureId };
        })
      );
      return NextResponse.json({
        stats: {
          nodeCount: structureCount + litCount,
          structureCount,
          literatureCount: litCount,
          edgeCount: linkCount,
        },
        popularStructures: popularDetailed,
      });
    }

    // 全图
    const links = await db.structureLink.findMany({
      include: {
        structure: { select: { id: true, title: true, method: true, resolution: true } },
        literature: { select: { id: true, title: true, year: true, journal: true } },
      },
      take: limit,
    });

    const nodes = new Map<string, { id: string; label: string; type: string; method?: string | null; year?: number | null; weight: number }>();
    const edges: { source: string; target: string; weight: number; type: string }[] = [];

    for (const l of links) {
      const structNode = {
        id: `struct:${l.structureId}`,
        label: l.structureId,
        type: 'structure',
        method: l.structure.method,
        year: null as number | null,
        weight: 1,
      };
      const litNode = {
        id: `lit:${l.literatureId}`,
        label: (l.literature.title || '未命名').slice(0, 40),
        type: 'literature',
        method: null,
        year: l.literature.year,
        weight: 1,
      };
      if (!nodes.has(structNode.id)) nodes.set(structNode.id, structNode);
      else nodes.get(structNode.id)!.weight++;
      if (!nodes.has(litNode.id)) nodes.set(litNode.id, litNode);
      else nodes.get(litNode.id)!.weight++;
      edges.push({ source: structNode.id, target: litNode.id, weight: l.mentionCount, type: 'mentions' });
    }

    // UniProt 节点 (来自结构缓存的 uniprotIds)
    const structures = await db.structure.findMany({ take: 100, select: { id: true, uniprotIds: true } });
    for (const s of structures) {
      const uids = safeParse<{ uniprotId: string; proteinName?: string }[]>(s.uniprotIds, []);
      for (const u of uids.slice(0, 6)) {
        const nodeId = `uniprot:${u.uniprotId}`;
        if (!nodes.has(nodeId)) {
          nodes.set(nodeId, {
            id: nodeId,
            label: u.proteinName || u.uniprotId,
            type: 'uniprot',
            method: null,
            year: null,
            weight: 1,
          });
        }
        const structNodeId = `struct:${s.id}`;
        if (nodes.has(structNodeId)) {
          edges.push({ source: structNodeId, target: nodeId, weight: 1, type: 'maps_to' });
        }
      }
    }

    return NextResponse.json({
      nodes: [...nodes.values()],
      edges,
      stats: { nodeCount: nodes.size, edgeCount: edges.length },
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}

/** POST /api/kg — 图谱搜索 */
export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { query?: string; type?: string };
    const query = (body.query || '').trim();
    if (!query) return NextResponse.json({ error: '缺少 query' }, { status: 400 });

    const upper = query.toUpperCase();
    const structures = await db.structure.findMany({
      where: { OR: [{ id: { contains: upper } }, { title: { contains: query } }] },
      take: 10,
      include: { _count: { select: { literatureLinks: true } } },
    });
    const literature = await db.literature.findMany({
      where: { OR: [{ title: { contains: query } }, { abstract: { contains: query } }, { keywords: { contains: query } }] },
      take: 10,
      include: { _count: { select: { structureLinks: true } } },
    });

    return NextResponse.json({
      query,
      structures: structures.map((s) => ({
        id: s.id,
        label: s.id,
        title: s.title,
        method: s.method,
        literatureCount: s._count.literatureLinks,
      })),
      literature: literature.map((l) => ({
        id: l.id,
        label: l.title.slice(0, 50),
        year: l.year,
        structureCount: l._count.structureLinks,
      })),
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '搜索失败' }, { status: 500 });
  }
}

/** PUT /api/kg — 两个结构间的路径与序列相似性 (对应原 find_paths) */
export async function PUT(request: Request) {
  try {
    const body = (await request.json()) as { source?: string; target?: string };
    const source = (body.source || '').toUpperCase();
    const target = (body.target || '').toUpperCase();
    if (!source || !target) return NextResponse.json({ error: '缺少 source/target' }, { status: 400 });

    // BFS 找路径: structure → literature → structure
    const visited = new Set<string>([source]);
    const queue: { node: string; path: string[] }[] = [{ node: source, path: [source] }];
    let foundPath: string[] | null = null;

    while (queue.length > 0 && !foundPath) {
      const { node, path } = queue.shift()!;
      if (node === target) {
        foundPath = path;
        break;
      }
      const links = await db.structureLink.findMany({ where: { structureId: node }, select: { literatureId: true } });
      for (const l of links) {
        if (visited.has(`lit:${l.literatureId}`)) continue;
        visited.add(`lit:${l.literatureId}`);
        const siblings = await db.structureLink.findMany({
          where: { literatureId: l.literatureId, structureId: { not: node } },
          select: { structureId: true },
        });
        for (const s of siblings) {
          if (s.structureId === target) {
            foundPath = [...path, `lit:${l.literatureId}`, target];
            break;
          }
          if (!visited.has(s.structureId)) {
            visited.add(s.structureId);
            queue.push({ node: s.structureId, path: [...path, `lit:${l.literatureId}`, s.structureId] });
          }
        }
        if (foundPath) break;
      }
    }

    // 序列相似性
    const [s1, s2] = await Promise.all([
      db.structure.findUnique({ where: { id: source }, select: { sequenceJson: true, title: true } }),
      db.structure.findUnique({ where: { id: target }, select: { sequenceJson: true, title: true } }),
    ]);
    let sequenceSimilarity: number | null = null;
    const seqs1 = safeParse<{ sequence: string }[]>(s1?.sequenceJson, []);
    const seqs2 = safeParse<{ sequence: string }[]>(s2?.sequenceJson, []);
    if (seqs1[0]?.sequence && seqs2[0]?.sequence) {
      sequenceSimilarity = quickSimilarity(seqs1[0].sequence, seqs2[0].sequence);
    }

    return NextResponse.json({
      source,
      target,
      path: foundPath,
      connected: !!foundPath,
      pathLength: foundPath ? foundPath.length : null,
      sequenceSimilarity,
      titles: { [source]: s1?.title || source, [target]: s2?.title || target },
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '路径查询失败' }, { status: 500 });
  }
}
