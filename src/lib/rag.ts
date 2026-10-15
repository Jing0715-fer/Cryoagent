/**
 * CryoAgent Pro - RAG 检索服务
 * 从 Prisma 加载文献分块 → 构建内存索引 (BM25 + TF-IDF) → 混合检索
 * 对应原 core/lancedb_rag/rag.py + search_factory.py
 */

import { db } from '@/lib/db';
import { BM25Index, VectorIndex, rrfFuse, type SearchHit } from '@/lib/search-engine';

export type SearchMode = 'bm25' | 'vector' | 'hybrid';

interface RagIndexes {
  docs: { id: string; literatureId: string; chunkIndex: number; section: string; content: string; title?: string; authors?: string[] }[];
  bm25: BM25Index | null;
  vector: VectorIndex | null;
  builtAt: number;
}

// 全局索引缓存 (带 TTL, 文献变更时失效)
const indexCache: { data: RagIndexes | null; dirty: boolean } = { data: null, dirty: true };

export function invalidateRagIndex(): void {
  indexCache.dirty = true;
}

async function loadChunks() {
  const chunks = await db.literatureChunk.findMany({
    select: {
      id: true,
      literatureId: true,
      chunkIndex: true,
      section: true,
      content: true,
      literature: { select: { title: true, authors: true } },
    },
    orderBy: { literatureId: 'asc' },
  });
  return chunks.map((c) => ({
    id: c.id,
    literatureId: c.literatureId,
    chunkIndex: c.chunkIndex,
    section: c.section,
    content: c.content,
    title: c.literature.title,
    authors: safeParse<string[]>(c.literature.authors, []),
  }));
}

async function getIndexes(): Promise<RagIndexes> {
  if (indexCache.data && !indexCache.dirty && Date.now() - indexCache.data.builtAt < 5 * 60 * 1000) {
    return indexCache.data;
  }
  const docs = await loadChunks();
  const idx: RagIndexes = {
    docs,
    bm25: docs.length > 0 ? new BM25Index(docs) : null,
    vector: docs.length > 0 ? new VectorIndex(docs) : null,
    builtAt: Date.now(),
  };
  indexCache.data = idx;
  indexCache.dirty = false;
  return idx;
}

export interface RagResult extends SearchHit {
  literatureTitle?: string;
}

export async function ragSearch(query: string, mode: SearchMode = 'hybrid', limit = 8): Promise<RagResult[]> {
  const idx = await getIndexes();
  if (!idx.bm25 || !idx.vector || idx.docs.length === 0) return [];

  const fetchLimit = limit * 4;
  let hits: SearchHit[];
  if (mode === 'bm25') {
    hits = idx.bm25.search(query, limit);
  } else if (mode === 'vector') {
    hits = idx.vector.search(query, limit);
  } else {
    const bm25Hits = idx.bm25.search(query, fetchLimit);
    const vecHits = idx.vector.search(query, fetchLimit);
    hits = rrfFuse([bm25Hits, vecHits], limit);
    // 标记来源分数 (复用已检索的 bm25Hits, 避免循环内重复全量检索)
    const bm25ScoreMap = new Map(bm25Hits.map((b) => [b.id, b.bm25Score]));
    for (const h of hits) {
      h.bm25Score = bm25ScoreMap.get(h.id);
      h.vectorScore = vecHits.find((v) => v.id === h.id)?.vectorScore;
    }
  }
  return hits as RagResult[];
}

/** 构建供 LLM 使用的上下文文本 */
export function buildRagContext(hits: RagResult[]): string {
  if (hits.length === 0) return '';
  const parts = hits.map((h, i) => {
    const source = `[${i + 1}] ${h.title || '未命名文献'} — ${sectionLabel(h.section)} 第${h.chunkIndex + 1}块\n${h.content}`;
    return source;
  });
  return `以下是与用户问题相关的文献片段 (共 ${hits.length} 条, 按相关度排序):\n\n${parts.join('\n\n---\n\n')}`;
}

function sectionLabel(section: string): string {
  const map: Record<string, string> = {
    abstract: '摘要',
    intro: '引言',
    methods: '方法',
    results: '结果',
    discussion: '讨论',
    conclusion: '结论',
    body: '正文',
  };
  return map[section] || section;
}

export function safeParse<T>(json: string | null | undefined, fallback: T): T {
  if (!json) return fallback;
  try {
    return JSON.parse(json) as T;
  } catch {
    return fallback;
  }
}

/** 索引状态 */
export async function getRagStats() {
  const idx = await getIndexes().catch(() => null);
  return {
    chunkCount: idx?.docs.length || 0,
    literatureCount: idx ? new Set(idx.docs.map((d) => d.literatureId)).size : 0,
    indexAge: idx ? Date.now() - idx.builtAt : 0,
  };
}
