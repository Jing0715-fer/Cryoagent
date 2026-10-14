/**
 * CryoAgent Pro - 混合检索引擎
 * TypeScript 实现 BM25 全文检索 + TF-IDF 向量余弦相似度 + RRF 融合
 * 对应原 Flask 版 core/lancedb_rag/ (bm25.py / hybrid.py / rag.py)
 */

export interface SearchDoc {
  id: string;
  literatureId: string;
  chunkIndex: number;
  section: string;
  content: string;
  title?: string;
  authors?: string[];
}

export interface SearchHit {
  id: string;
  literatureId: string;
  chunkIndex: number;
  section: string;
  content: string;
  title?: string;
  authors?: string[];
  score: number;
  bm25Score?: number;
  vectorScore?: number;
  snippet: string;
}

// ============ 分词 ============

const STOP_WORDS = new Set([
  '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
  '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
  'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have',
  'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may',
  'might', 'shall', 'can', 'of', 'in', 'to', 'for', 'with', 'on', 'at', 'by',
  'from', 'as', 'and', 'or', 'but', 'if', 'then', 'than', 'that', 'this',
  'these', 'those', 'it', 'its', 'we', 'they', 'he', 'she', 'his', 'her',
]);

/** 中英文混合分词: 英文按词, 中文按单字 + 二元组 */
export function tokenize(text: string): string[] {
  const clean = text.toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, ' ');
  const tokens: string[] = [];
  // 英文词
  const words = clean.split(/\s+/).filter(Boolean);
  for (const w of words) {
    if (/[a-z0-9-]+/.test(w) && !STOP_WORDS.has(w) && w.length > 1) {
      tokens.push(w);
    }
  }
  // 中文单字 + bigram
  const cjk = clean.match(/[\u4e00-\u9fff]+/g) || [];
  for (const seg of cjk) {
    for (let i = 0; i < seg.length; i++) {
      tokens.push(seg[i]);
      if (i + 1 < seg.length) tokens.push(seg.slice(i, i + 2));
    }
  }
  return tokens;
}

// ============ BM25 ============

export class BM25Index {
  private docs: SearchDoc[] = [];
  private docTokens: string[][] = [];
  private df: Map<string, number> = new Map();
  private avgLen = 0;
  private k1 = 1.5;
  private b = 0.75;

  constructor(docs: SearchDoc[]) {
    this.build(docs);
  }

  build(docs: SearchDoc[]) {
    this.docs = docs;
    this.docTokens = docs.map((d) => tokenize(`${d.title || ''} ${d.content}`));
    this.df = new Map();
    let total = 0;
    for (const toks of this.docTokens) {
      total += toks.length;
      const seen = new Set(toks);
      for (const t of seen) this.df.set(t, (this.df.get(t) || 0) + 1);
    }
    this.avgLen = this.docTokens.length > 0 ? total / this.docTokens.length : 0;
  }

  search(query: string, limit = 10): SearchHit[] {
    const qTokens = tokenize(query);
    const N = this.docs.length;
    const results: { doc: SearchDoc; score: number }[] = [];

    for (let i = 0; i < this.docs.length; i++) {
      const toks = this.docTokens[i];
      const tf = new Map<string, number>();
      for (const t of toks) tf.set(t, (tf.get(t) || 0) + 1);

      let score = 0;
      for (const qt of qTokens) {
        const f = tf.get(qt) || 0;
        if (f === 0) continue;
        const n = this.df.get(qt) || 0;
        const idf = Math.log(1 + (N - n + 0.5) / (n + 0.5));
        const docLen = toks.length / (this.avgLen || 1);
        const norm = this.k1 * (1 - this.b + this.b * docLen) + f;
        score += idf * (((this.k1 + 1) * f) / norm);
      }
      if (score > 0) results.push({ doc: this.docs[i], score });
    }

    results.sort((a, b) => b.score - a.score);
    return results.slice(0, limit).map((r) => ({
      ...r.doc,
      score: r.score,
      bm25Score: r.score,
      snippet: makeSnippet(r.doc.content, query),
    }));
  }
}

// ============ TF-IDF 向量余弦 ============

export class VectorIndex {
  private docs: SearchDoc[] = [];
  private docVectors: Map<string, number>[] = [];
  private idf: Map<string, number> = new Map();

  constructor(docs: SearchDoc[]) {
    this.build(docs);
  }

  build(docs: SearchDoc[]) {
    this.docs = docs;
    const docTokens = docs.map((d) => tokenize(`${d.title || ''} ${d.content}`));
    const N = docs.length;
    const df = new Map<string, number>();
    for (const toks of docTokens) {
      for (const t of new Set(toks)) df.set(t, (df.get(t) || 0) + 1);
    }
    this.idf = new Map();
    for (const [t, n] of df) this.idf.set(t, Math.log(1 + N / n));

    this.docVectors = docTokens.map((toks) => {
      const tf = new Map<string, number>();
      for (const t of toks) tf.set(t, (tf.get(t) || 0) + 1);
      const vec = new Map<string, number>();
      for (const [t, f] of tf) {
        const w = (1 + Math.log(f)) * (this.idf.get(t) || 0);
        vec.set(t, w);
      }
      // L2 归一化
      let norm = 0;
      for (const v of vec.values()) norm += v * v;
      norm = Math.sqrt(norm) || 1;
      for (const [t, v] of vec) vec.set(t, v / norm);
      return vec;
    });
  }

  search(query: string, limit = 10): SearchHit[] {
    const qTokens = tokenize(query);
    const qtf = new Map<string, number>();
    for (const t of qTokens) qtf.set(t, (qtf.get(t) || 0) + 1);
    const qVec = new Map<string, number>();
    for (const [t, f] of qtf) {
      const w = (1 + Math.log(f)) * (this.idf.get(t) || 0);
      qVec.set(t, w);
    }
    let qNorm = 0;
    for (const v of qVec.values()) qNorm += v * v;
    qNorm = Math.sqrt(qNorm) || 1;

    const results: { doc: SearchDoc; score: number }[] = [];
    for (let i = 0; i < this.docs.length; i++) {
      let dot = 0;
      for (const [t, w] of qVec) {
        const dw = this.docVectors[i].get(t);
        if (dw) dot += (w / qNorm) * dw;
      }
      if (dot > 0) results.push({ doc: this.docs[i], score: dot });
    }

    results.sort((a, b) => b.score - a.score);
    return results.slice(0, limit).map((r) => ({
      ...r.doc,
      score: r.score,
      vectorScore: r.score,
      snippet: makeSnippet(r.doc.content, query),
    }));
  }
}

// ============ RRF 混合融合 ============

export function rrfFuse(lists: SearchHit[][], limit = 10, k = 60): SearchHit[] {
  const scores = new Map<string, { hit: SearchHit; score: number }>();
  for (const list of lists) {
    list.forEach((hit, rank) => {
      const cur = scores.get(hit.id);
      const contribution = 1 / (k + rank + 1);
      if (cur) {
        cur.score += contribution;
        cur.hit.score = cur.score;
        cur.hit.bm25Score = cur.hit.bm25Score ?? hit.bm25Score;
        cur.hit.vectorScore = cur.hit.vectorScore ?? hit.vectorScore;
      } else {
        scores.set(hit.id, { hit: { ...hit }, score: contribution });
      }
    });
  }
  const merged = [...scores.values()].sort((a, b) => b.score - a.score);
  return merged.slice(0, limit).map((m) => ({ ...m.hit, score: m.score }));
}

// ============ 工具函数 ============

export function makeSnippet(content: string, query: string, maxLen = 220): string {
  const tokens = tokenize(query).filter((t) => t.length > 1);
  let bestPos = 0;
  let bestScore = -1;
  const lower = content.toLowerCase();
  const window = 150;
  for (let i = 0; i < Math.max(1, content.length - window); i += 60) {
    const seg = lower.slice(i, i + window);
    let s = 0;
    for (const t of tokens) if (seg.includes(t)) s++;
    if (s > bestScore) {
      bestScore = s;
      bestPos = i;
    }
  }
  let snippet = content.slice(bestPos, bestPos + maxLen);
  if (bestPos > 0) snippet = '...' + snippet;
  if (bestPos + maxLen < content.length) snippet += '...';
  return snippet.replace(/\s+/g, ' ').trim();
}

/** 高亮片段中的关键词 (返回分段) */
export function highlightSegments(text: string, query: string): { text: string; hit: boolean }[] {
  const tokens = tokenize(query).filter((t) => t.length > 1);
  if (tokens.length === 0) return [{ text, hit: false }];
  const pattern = new RegExp(
    `(${tokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`,
    'gi'
  );
  const parts = text.split(pattern);
  return parts
    .filter((p) => p.length > 0)
    .map((p) => ({ text: p, hit: pattern.test(p) }));
}
