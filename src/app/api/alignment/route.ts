import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { alignSequences, generateConsensus, type MatrixName } from '@/lib/alignment';
import { fetchStructureDetail } from '@/lib/bio-apis';

/**
 * POST /api/alignment — 序列比对
 * 对应原 routes/alignment.py (align/result/compare/extract-pdb)
 */
export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      sequence1?: string;
      sequence2?: string;
      seq1Name?: string;
      seq2Name?: string;
      algorithm?: 'needleman-wunsch' | 'smith-waterman';
      matrix?: MatrixName;
      pdbId1?: string;
      pdbId2?: string;
      consensusMode?: boolean;
    };

    let seq1 = (body.sequence1 || '').trim();
    let seq2 = (body.sequence2 || '').trim();
    let seq1Name = body.seq1Name || 'Sequence 1';
    let seq2Name = body.seq2Name || 'Sequence 2';

    // 从 PDB 提取序列 (对应原 extract-pdb-id)
    if (body.pdbId1 && !seq1) {
      const d = await fetchStructureDetail(body.pdbId1);
      if (!d || d.sequences.length === 0) {
        return NextResponse.json({ error: `无法获取 ${body.pdbId1} 的序列` }, { status: 404 });
      }
      seq1 = d.sequences[0].sequence;
      seq1Name = `${body.pdbId1.toUpperCase()} — ${(d.sequences[0].description || '').slice(0, 30)}`;
    }
    if (body.pdbId2 && !seq2) {
      const d = await fetchStructureDetail(body.pdbId2);
      if (!d || d.sequences.length === 0) {
        return NextResponse.json({ error: `无法获取 ${body.pdbId2} 的序列` }, { status: 404 });
      }
      seq2 = d.sequences[0].sequence;
      seq2Name = `${body.pdbId2.toUpperCase()} — ${(d.sequences[0].description || '').slice(0, 30)}`;
    }

    if (!seq1 || !seq2) {
      return NextResponse.json({ error: '需要两条序列 (或 PDB ID)' }, { status: 400 });
    }
    // S2 修复: 限制 DP 矩阵规模，防止 OOM (6 个 (n+1)*(m+1) 矩阵)
    const MAX_LEN = 4000;
    const MAX_CELLS = 4_000_000; // ≈ 2000×2000, 覆盖几乎所有真实蛋白序列
    if (seq1.length > MAX_LEN || seq2.length > MAX_LEN) {
      return NextResponse.json({ error: `序列过长 (单条最大 ${MAX_LEN} 残基), 请截断后重试` }, { status: 400 });
    }
    if ((seq1.length + 1) * (seq2.length + 1) > MAX_CELLS) {
      return NextResponse.json(
        { error: `比对矩阵过大 (${seq1.length}×${seq2.length} 超过 2000×2000), 建议截断至更短片段` },
        { status: 400 }
      );
    }

    const algorithm = body.algorithm === 'smith-waterman' ? 'smith-waterman' : 'needleman-wunsch';
    const matrix: MatrixName = ['BLOSUM62', 'BLOSUM45', 'PAM250', 'IDENTITY'].includes(body.matrix as MatrixName)
      ? (body.matrix as MatrixName)
      : 'BLOSUM62';

    const start = Date.now();
    const result = alignSequences(seq1, seq2, { algorithm, matrix, gapOpen: -11, gapExtend: -1 });
    const computeMs = Date.now() - start;

    const consensus = body.consensusMode !== false ? generateConsensus([result.seq1Aligned, result.seq2Aligned]) : result.consensus;

    // 保存任务记录
    const task = await db.alignmentTask.create({
      data: {
        seq1: seq1.slice(0, 5000),
        seq2: seq2.slice(0, 5000),
        seq1Name,
        seq2Name,
        algorithm,
        matrix,
        status: 'completed',
        result: JSON.stringify({ ...result, consensus }),
        identity: result.identity,
        score: result.score,
      },
    });

    return NextResponse.json({
      taskId: task.id,
      seq1Name,
      seq2Name,
      seq1Length: seq1.length,
      seq2Length: seq2.length,
      computeMs,
      result: { ...result, consensus },
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '比对失败' }, { status: 500 });
  }
}

/** GET /api/alignment — 历史比对任务 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = Math.min(parseInt(searchParams.get('limit') || '20') || 20, 100);
    const tasks = await db.alignmentTask.findMany({
      orderBy: { createdAt: 'desc' },
      take: limit,
      select: {
        id: true,
        seq1Name: true,
        seq2Name: true,
        algorithm: true,
        matrix: true,
        identity: true,
        score: true,
        createdAt: true,
      },
    });
    return NextResponse.json({ tasks });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}
