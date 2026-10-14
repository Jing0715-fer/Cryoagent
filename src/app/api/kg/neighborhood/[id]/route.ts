import { NextResponse } from 'next/server';
import { db } from '@/lib/db';

/** GET /api/kg/neighborhood/[id] — 结构邻域查询 (对应原 get_neighborhood) */
export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id: rawId } = await params;
    const structureId = rawId.toUpperCase().trim();
    const { searchParams } = new URL(request.url);
    const depth = Math.min(parseInt(searchParams.get('depth') || '1'), 2);
    const limit = Math.min(parseInt(searchParams.get('limit') || '30'), 60);

    const center = await db.structure.findUnique({ where: { id: structureId } });
    const links = await db.structureLink.findMany({
      where: { structureId },
      include: { literature: { select: { id: true, title: true, year: true, journal: true } } },
      orderBy: { mentionCount: 'desc' },
      take: limit,
    });

    const nodes: { id: string; label: string; type: string; weight: number; extra?: Record<string, unknown> }[] = [];
    const edges: { source: string; target: string; weight: number; type: string }[] = [];

    nodes.push({
      id: `struct:${structureId}`,
      label: structureId,
      type: 'structure',
      weight: 10,
      extra: { title: center?.title, method: center?.method, resolution: center?.resolution },
    });

    for (const l of links) {
      const litNodeId = `lit:${l.literatureId}`;
      nodes.push({
        id: litNodeId,
        label: (l.literature.title || '未命名').slice(0, 36),
        type: 'literature',
        weight: Math.min(5, 1 + l.mentionCount),
        extra: { year: l.literature.year, journal: l.literature.journal },
      });
      edges.push({ source: `struct:${structureId}`, target: litNodeId, weight: l.mentionCount, type: 'mentions' });

      // depth=2: 加入共享该文献的其他结构
      if (depth >= 2) {
        const siblings = await db.structureLink.findMany({
          where: { literatureId: l.literatureId, structureId: { not: structureId } },
          take: 5,
          include: { structure: { select: { title: true, method: true } } },
        });
        for (const s of siblings) {
          const nodeId = `struct:${s.structureId}`;
          if (!nodes.find((n) => n.id === nodeId)) {
            nodes.push({
              id: nodeId,
              label: s.structureId,
              type: 'structure',
              weight: 3,
              extra: { title: s.structure.title, method: s.structure.method },
            });
          }
          edges.push({ source: litNodeId, target: nodeId, weight: 1, type: 'mentions' });
        }
      }
    }

    // UniProt 邻居
    if (center) {
      let uniprotIds: { uniprotId: string; proteinName?: string }[] = [];
      try {
        uniprotIds = JSON.parse(center.uniprotIds || '[]');
      } catch {
        uniprotIds = [];
      }
      for (const u of uniprotIds.slice(0, 6)) {
        const nodeId = `uniprot:${u.uniprotId}`;
        nodes.push({
          id: nodeId,
          label: u.proteinName || u.uniprotId,
          type: 'uniprot',
          weight: 4,
        });
        edges.push({ source: `struct:${structureId}`, target: nodeId, weight: 1, type: 'maps_to' });
      }
    }

    return NextResponse.json({
      center: structureId,
      depth,
      nodes,
      edges,
      stats: { nodeCount: nodes.length, edgeCount: edges.length },
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '邻域查询失败' }, { status: 500 });
  }
}
