import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { fetchStructureDetail, fetchAlphaFoldModel, type StructureDetail } from '@/lib/bio-apis';
import { safeParse } from '@/lib/rag';

/**
 * GET /api/structure/[id] — 结构详情 (本地缓存 + RCSB 实时, 对应原 fetch_complete_metadata)
 */
export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id: rawId } = await params;
    const id = rawId.toUpperCase().trim();
    const { searchParams } = new URL(request.url);
    const forceRefresh = searchParams.get('refresh') === 'true';

    // 本地缓存
    const local = await db.structure.findUnique({
      where: { id },
      include: {
        literatureLinks: {
          include: { literature: { select: { id: true, title: true, year: true, journal: true } } },
          orderBy: { mentionCount: 'desc' },
        },
      },
    });

    // 尝试实时刷新 (RCSB)
    let detail: StructureDetail | null = null;
    if (/^\d[A-Z0-9]{3}$/.test(id)) {
      detail = await fetchStructureDetail(id);
    }

    if (detail) {
      // upsert 缓存
      await db.structure
        .upsert({
          where: { id },
          create: {
            id,
            title: detail.title,
            method: detail.method,
            resolution: detail.resolution,
            organism: detail.organism,
            uniprotIds: JSON.stringify(detail.uniprotIds),
            entityCount: detail.entityCount,
            residueCount: detail.residueCount,
            ligandInfo: JSON.stringify(detail.ligands),
            citationJson: detail.citation ? JSON.stringify(detail.citation) : null,
            sequenceJson: JSON.stringify(detail.sequences),
            rawJson: JSON.stringify(detail).slice(0, 100000),
            accessCount: 1,
          },
          update: {
            title: detail.title,
            method: detail.method,
            resolution: detail.resolution,
            organism: detail.organism,
            uniprotIds: JSON.stringify(detail.uniprotIds),
            entityCount: detail.entityCount,
            residueCount: detail.residueCount,
            ligandInfo: JSON.stringify(detail.ligands),
            citationJson: detail.citation ? JSON.stringify(detail.citation) : null,
            sequenceJson: JSON.stringify(detail.sequences),
            accessCount: { increment: 1 },
            updatedAt: new Date(),
          },
        })
        .catch(() => {});
    } else if (local) {
      await db.structure.update({ where: { id }, data: { accessCount: { increment: 1 } } }).catch(() => {});
    }

    // 重新查询 (含文献关联)
    const merged = await db.structure.findUnique({
      where: { id },
      include: {
        literatureLinks: {
          include: { literature: { select: { id: true, title: true, year: true, journal: true, authors: true } } },
          orderBy: { mentionCount: 'desc' },
        },
      },
    });

    if (!merged && !detail) {
      return NextResponse.json({ error: `结构 ${id} 未找到 (RCSB 不可达且无本地缓存)` }, { status: 404 });
    }

    const structure = detail || {
      pdbId: merged!.id,
      title: merged!.title,
      method: merged!.method,
      resolution: merged!.resolution,
      organism: merged!.organism,
      uniprotIds: safeParse(merged!.uniprotIds, []),
      entityCount: merged!.entityCount,
      residueCount: merged!.residueCount,
      ligands: safeParse(merged!.ligandInfo, []),
      citation: safeParse(merged!.citationJson, null),
      sequences: safeParse(merged!.sequenceJson, []),
      depositDate: null,
      releaseDate: null,
      emdbIds: [],
    };

    const literature = merged
      ? merged.literatureLinks.map((l) => ({
          ...l.literature,
          authors: safeParse(l.literature.authors, [] as string[]),
          mentionCount: l.mentionCount,
        }))
      : [];

    // AlphaFold 预测可用性
    const firstUniprot = (structure.uniprotIds?.[0] as { uniprotId?: string } | undefined)?.uniprotId;
    let alphaFoldAvailable = false;
    if (firstUniprot) {
      const af = await fetchAlphaFoldModel(firstUniprot).catch(() => null);
      alphaFoldAvailable = !!af && af.length > 100;
    }

    return NextResponse.json({
      structure: { ...structure, emdbIds: structure.emdbIds || [] },
      literature,
      relatedStructures: await getRelatedStructures(id),
      alphaFold: { available: alphaFoldAvailable, uniprotId: firstUniprot || null },
      fromCache: !detail && !!merged,
      forceRefresh,
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}

async function getRelatedStructures(structureId: string): Promise<{ id: string; sharedLiterature: number }[]> {
  try {
    const links = await db.structureLink.findMany({ where: { structureId }, select: { literatureId: true } });
    if (links.length === 0) return [];
    const siblings = await db.structureLink.groupBy({
      by: ['structureId'],
      where: { literatureId: { in: links.map((l) => l.literatureId) }, structureId: { not: structureId } },
      _count: { literatureId: true },
      orderBy: { _count: { literatureId: 'desc' } },
      take: 12,
    });
    return siblings.map((s) => ({ id: s.structureId, sharedLiterature: s._count.literatureId }));
  } catch {
    return [];
  }
}
