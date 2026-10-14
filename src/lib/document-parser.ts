/**
 * CryoAgent Pro - PDF/文本文献解析与分块
 * 对应原 core/literature_parser.py + routes/literature.py 的分块逻辑
 */

import { readFile } from 'fs/promises';
import path from 'path';

export interface ParsedSection {
  section: string;
  page: number | null;
  content: string;
}

export interface ParsedDocument {
  fullText: string;
  sections: ParsedSection[];
  wordCount: number;
  pageCount: number;
  metadata: { title?: string; authors?: string[]; doi?: string; year?: number };
}

/** 提取 PDF 文本 (pdf-parse v2), 失败时降级为错误 */
export async function parsePdf(filePath: string): Promise<ParsedDocument> {
  const buf = await readFile(filePath);
  const { PDFParse } = await import('pdf-parse');
  const parser = new PDFParse({ data: buf });
  try {
    const [textResult, infoResult] = await Promise.all([
      parser.getText(),
      parser.getInfo().catch(() => null),
    ]);
    const info = (infoResult?.info as Record<string, unknown> | undefined) || {};
    return {
      fullText: textResult.text || '',
      sections: detectSections(textResult.text || ''),
      wordCount: countWords(textResult.text || ''),
      pageCount: textResult.total || textResult.pages.length || 1,
      metadata: extractMetadata(textResult.text || '', info),
    };
  } finally {
    await parser.destroy().catch(() => {});
  }
}

export async function parseTextFile(filePath: string): Promise<ParsedDocument> {
  const text = await readFile(filePath, 'utf-8');
  return {
    fullText: text,
    sections: detectSections(text),
    wordCount: countWords(text),
    pageCount: Math.max(1, Math.ceil(text.length / 3000)),
    metadata: extractMetadata(text, {}),
  };
}

/** 分块 (对应原 _split_text_for_appendix: 500 词, 重叠 50) */
export function chunkDocument(doc: ParsedDocument): {
  chunkIndex: number;
  section: string;
  page: number | null;
  content: string;
  wordCount: number;
}[] {
  const CHUNK_SIZE = 480;
  const OVERLAP = 50;
  const chunks: { chunkIndex: number; section: string; page: number | null; content: string; wordCount: number }[] = [];
  let index = 0;

  for (const sec of doc.sections) {
    const words = sec.content.split(/\s+/).filter(Boolean);
    if (words.length === 0) continue;
    for (let start = 0; start < words.length; start += CHUNK_SIZE - OVERLAP) {
      const slice = words.slice(start, start + CHUNK_SIZE).join(' ');
      if (slice.trim().length < 20) continue;
      chunks.push({
        chunkIndex: index++,
        section: sec.section,
        page: sec.page,
        content: slice,
        wordCount: words.slice(start, start + CHUNK_SIZE).length,
      });
      if (start + CHUNK_SIZE >= words.length) break;
    }
  }

  // 兜底: 无分段时按全文切块
  if (chunks.length === 0 && doc.fullText.trim().length > 0) {
    const words = doc.fullText.split(/\s+/).filter(Boolean);
    for (let start = 0; start < words.length; start += CHUNK_SIZE - OVERLAP) {
      const slice = words.slice(start, start + CHUNK_SIZE).join(' ');
      if (slice.trim().length < 20) continue;
      chunks.push({
        chunkIndex: chunks.length,
        section: 'body',
        page: null,
        content: slice,
        wordCount: words.slice(start, start + CHUNK_SIZE).length,
      });
      if (start + CHUNK_SIZE >= words.length) break;
    }
  }
  return chunks;
}

/** 识别论文章节 (中英文) */
function detectSections(text: string): ParsedSection[] {
  const patterns: { section: string; re: RegExp }[] = [
    { section: 'abstract', re: /^\s*(abstract|summary)\b/im },
    { section: 'intro', re: /^\s*(introduction|background)\b/im },
    { section: 'methods', re: /^\s*(methods?|materials? and methods?|experimental procedures?|materials)\b/im },
    { section: 'results', re: /^\s*(results?)\b/im },
    { section: 'discussion', re: /^\s*(discussion)\b/im },
    { section: 'conclusion', re: /^\s*(conclusions?|acknowledgments?)\b/im },
    { section: 'references', re: /^\s*(references?)\b/im },
  ];

  const lines = text.split('\n');
  const found: { section: string; lineIdx: number }[] = [];
  for (const p of patterns) {
    for (let i = 0; i < lines.length; i++) {
      if (p.re.test(lines[i]) && lines[i].length < 120) {
        found.push({ section: p.section, lineIdx: i });
        break;
      }
    }
  }
  found.sort((a, b) => a.lineIdx - b.lineIdx);

  if (found.length === 0) {
    return [{ section: 'body', page: null, content: text }];
  }

  const sections: ParsedSection[] = [];
  // 头部 (若 abstract 不是第 0 行, 前面的内容归为 header→abstract)
  const first = found[0];
  if (first.lineIdx > 3) {
    sections.push({ section: 'abstract', page: null, content: lines.slice(0, first.lineIdx).join('\n') });
  }
  for (let i = 0; i < found.length; i++) {
    const start = found[i].lineIdx;
    const end = i + 1 < found.length ? found[i + 1].lineIdx : lines.length;
    // 跳过 references (不做检索源)
    if (found[i].section === 'references') break;
    const content = lines.slice(start, end).join('\n').trim();
    if (content.length > 50) sections.push({ section: found[i].section, page: null, content });
  }
  return sections.length > 0 ? sections : [{ section: 'body', page: null, content: text }];
}

/** 从文本/元数据提取 标题/作者/DOI/年份 */
function extractMetadata(text: string, info: Record<string, unknown>): ParsedDocument['metadata'] {
  const meta: ParsedDocument['metadata'] = {};
  const infoTitle = (info?.Title as string) || '';
  const infoAuthor = (info?.Author as string) || '';
  if (infoTitle && infoTitle.length > 8 && !/untitled|microsoft word/i.test(infoTitle)) meta.title = infoTitle.trim();
  if (infoAuthor && infoAuthor.length > 2) meta.authors = infoAuthor.split(/[,;]\s*/).slice(0, 12);

  // DOI
  const doiMatch = text.match(/(?:doi|DOI)\s*[:.]?\s*(10\.\d{4,}\/[^\s"<>]{3,60})/);
  if (doiMatch) meta.doi = doiMatch[1].replace(/[.,;]$/, '');

  // 年份 (优先 20xx)
  const yearMatch = text.match(/\b(19[89]\d|20[0-2]\d)\b/);
  if (yearMatch) meta.year = parseInt(yearMatch[1]);

  // 无 info title 时, 从文本首行猜
  if (!meta.title) {
    const lines = text.split('\n').map((l) => l.trim()).filter((l) => l.length > 15 && l.length < 200);
    if (lines.length > 0) {
      const candidates = lines.slice(0, 6);
      meta.title = candidates.sort((a, b) => b.length - a.length)[0].replace(/\s+/g, ' ').slice(0, 150);
    }
  }
  return meta;
}

function countWords(text: string): number {
  const latin = text.match(/[A-Za-z0-9'-]+/g)?.length || 0;
  const cjk = text.match(/[\u4e00-\u9fff]/g)?.length || 0;
  return latin + cjk;
}

/** 从文本自动提取 PDB ID 引用 (对应原 structure_extractor) */
export function extractPdbIds(text: string): string[] {
  const ids = new Set<string>();
  // 形如 "PDB ID 6M0J" / "(6M0J)" / "PDB: 7A5I" 等
  const re = /\b(?:PDB(?:\s*(?:ID|entry|code))?\s*[:=]?\s*)?([1-9][A-Z0-9]{3})\b/g;
  let m: RegExpExecArray | null;
  let count = 0;
  while ((m = re.exec(text)) !== null && count < 2000) {
    const candidate = m[1];
    // 排除纯数字或常见误报
    if (/^[0-9]+$/.test(candidate)) continue;
    if (candidate.length !== 4) continue;
    ids.add(candidate);
    count++;
    if (ids.size > 60) break;
  }
  return [...ids].slice(0, 60);
}

/** 提取 UniProt ID */
export function extractUniprotIds(text: string): string[] {
  const ids = new Set<string>();
  const re = /\b([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})\b/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m[1].length >= 6) ids.add(m[1]);
    if (ids.size > 40) break;
  }
  return [...ids];
}

export const UPLOAD_DIR = path.join(process.cwd(), 'uploads');
