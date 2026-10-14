import { NextResponse } from 'next/server';
import { analyzeSequence, analyzeNucleicAcid } from '@/lib/protein-analysis';
import { fetchStructureDetail, fetchUniprotEntry } from '@/lib/bio-apis';

/**
 * POST /api/sequence/analyze — 序列理化性质深度分析 (新增功能)
 * 支持: 直接输入序列 / PDB ID / UniProt ID
 */
export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      sequence?: string;
      type?: 'auto' | 'protein' | 'nucleic';
      source?: 'raw' | 'pdb' | 'uniprot';
      sourceId?: string;
    };

    let sequence = (body.sequence || '').trim().toUpperCase();
    let sourceLabel = '直接输入';
    let seqName = '';

    if (body.source === 'pdb' && body.sourceId) {
      const d = await fetchStructureDetail(body.sourceId);
      if (!d || d.sequences.length === 0) {
        return NextResponse.json({ error: `无法获取 ${body.sourceId} 的序列` }, { status: 404 });
      }
      sequence = d.sequences[0].sequence;
      sourceLabel = `PDB ${d.pdbId}`;
      seqName = d.sequences[0].description;
    } else if (body.source === 'uniprot' && body.sourceId) {
      const e = await fetchUniprotEntry(body.sourceId);
      if (!e?.sequence?.value) {
        return NextResponse.json({ error: `无法获取 ${body.sourceId} 的序列` }, { status: 404 });
      }
      sequence = e.sequence.value;
      sourceLabel = `UniProt ${e.primaryAccession}`;
      seqName = e.proteinDescription?.recommendedName?.fullName?.value || '';
    }

    if (!sequence || sequence.length < 2) {
      return NextResponse.json({ error: '序列为空或过短' }, { status: 400 });
    }
    if (sequence.length > 50000) {
      return NextResponse.json({ error: '序列过长 (最大 50000)' }, { status: 400 });
    }

    // 自动检测类型
    let type = body.type || 'auto';
    if (type === 'auto') {
      const proteinChars = sequence.replace(/[ARNDCQEGHILKMFPSTWYV]/g, '').length;
      const nucleicChars = sequence.replace(/[ACGTU]/g, '').length;
      if (proteinChars === 0 && /[IL]/.test(sequence)) type = 'protein';
      else if (nucleicChars === 0 && /[TU]/.test(sequence)) type = 'nucleic';
      else type = proteinChars <= nucleicChars ? 'protein' : 'nucleic';
    }

    if (type === 'nucleic') {
      const result = analyzeNucleicAcid(sequence);
      return NextResponse.json({ type, sourceLabel, seqName, sequenceLength: sequence.length, result });
    }
    const result = analyzeSequence(sequence);
    return NextResponse.json({ type, sourceLabel, seqName, sequenceLength: sequence.length, result });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '分析失败' }, { status: 500 });
  }
}
