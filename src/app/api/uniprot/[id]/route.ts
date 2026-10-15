import { NextResponse } from 'next/server';
import { fetchUniprotEntry } from '@/lib/bio-apis';

/** GET /api/uniprot/[id] — UniProt 条目查询 (对应原 fetch_uniprot 工具) */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const entry = await fetchUniprotEntry(id);
    if (!entry) return NextResponse.json({ error: `UniProt ${id} 未找到` }, { status: 404 });
    return NextResponse.json({
      entry: {
        accession: entry.primaryAccession,
        uniProtkbId: entry.uniProtkbId,
        proteinName: entry.proteinDescription?.recommendedName?.fullName?.value,
        organism: entry.organism,
        geneNames: (entry.genes || []).map((g) => g.geneName?.value).filter(Boolean),
        sequence: entry.sequence?.value,
        length: entry.sequence?.length,
        molWeight: entry.sequence?.molWeight,
        proteinExistence: entry.proteinExistence,
        keywords: (entry.keywords || []).map((k) => k.name),
        entryType: entry.entryType,
        comments: (entry.comments || []).map((c) => ({
          type: c.commentType,
          text: (c.texts || []).map((t) => t.text).join(' '),
          locations: (c.subcellularLocations || []).map((l) => l.location?.value).filter(Boolean),
        })),
      },
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '查询失败' }, { status: 500 });
  }
}
