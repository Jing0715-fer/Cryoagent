import { NextResponse } from 'next/server';
import { fetchPdbFile, fetchAlphaFoldModel } from '@/lib/bio-apis';

/**
 * GET /api/structure/[id]/pdb — 获取 PDB 原始文件文本 (供 3Dmol.js 渲染)
 * ?source=alphafold 时获取 AlphaFold 预测模型
 */
export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id: rawId } = await params;
    const { searchParams } = new URL(request.url);
    const source = searchParams.get('source') || 'rcsb';

    if (source === 'alphafold') {
      // rawId 可以是 UniProt ID
      const af = await fetchAlphaFoldModel(rawId);
      if (!af) return NextResponse.json({ error: 'AlphaFold 模型未找到' }, { status: 404 });
      return new Response(af, {
        headers: { 'Content-Type': 'chemical/x-pdb', 'Cache-Control': 'public, max-age=86400' },
      });
    }

    const id = rawId.toUpperCase().trim();
    if (!/^\d[A-Z0-9]{3}$/.test(id)) {
      return NextResponse.json({ error: '无效 PDB ID' }, { status: 400 });
    }
    const file = await fetchPdbFile(id);
    if (!file) return NextResponse.json({ error: 'PDB 文件下载失败' }, { status: 502 });
    return new Response(file, {
      headers: { 'Content-Type': 'chemical/x-pdb', 'Cache-Control': 'public, max-age=86400' },
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '获取失败' }, { status: 500 });
  }
}
