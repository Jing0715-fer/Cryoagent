/**
 * CryoAgent Pro - Agent 核心 (工具调用循环)
 * 对应原 core/agent_core.py + core/agent_tools.py + routes/qa_agent.py
 * 采用 JSON 协议驱动 LLM 工具调用 (兼容不支持原生 function-call 的模型)
 */

import { db } from '@/lib/db';
import { ragSearch } from '@/lib/rag';
import { safeParse } from '@/lib/rag';
import { alignSequences, quickSimilarity, type MatrixName } from '@/lib/alignment';
import { analyzeSequence, analyzeNucleicAcid } from '@/lib/protein-analysis';
import {
  fetchStructureDetail,
  searchRcsbStructures,
  fetchUniprotEntry,
  searchUniprotByQuery,
} from '@/lib/bio-apis';
import { chatCompletion, type ChatMessage } from '@/lib/llm';

// ============ 工具定义 ============

export interface ToolDef {
  name: string;
  description: string;
  parameters: Record<string, { type: string; description: string; required?: boolean; enum?: string[] }>;
}

export const AGENT_TOOLS: ToolDef[] = [
  {
    name: 'search_literature',
    description: '在本地文献知识库中混合检索(BM25+向量)相关文献片段。适合回答文献内容、方法细节、研究结论类问题。',
    parameters: {
      query: { type: 'string', description: '检索关键词(中英文均可)', required: true },
      limit: { type: 'number', description: '返回片段数量, 默认 6' },
    },
  },
  {
    name: 'search_structures',
    description: '在 RCSB PDB 数据库全文搜索蛋白质结构。返回 PDB ID、标题、方法、分辨率。',
    parameters: {
      query: { type: 'string', description: '搜索词, 如 "spike protein" 或 "RNA polymerase"', required: true },
      limit: { type: 'number', description: '返回数量, 默认 8' },
    },
  },
  {
    name: 'get_structure_details',
    description: '获取指定 PDB ID 的结构详情: 标题/方法/分辨率/实体/序列/UniProt/配体/引用。',
    parameters: {
      structure_id: { type: 'string', description: '4 位 PDB ID, 如 6M0J', required: true },
    },
  },
  {
    name: 'run_sequence_alignment',
    description: '比对两条蛋白质/核酸序列 (Needleman-Wunsch 全局 / Smith-Waterman 局部), 返回一致性/相似度/gap 统计与比对块。',
    parameters: {
      sequence1: { type: 'string', description: '第一条序列(单字母编码)', required: true },
      sequence2: { type: 'string', description: '第二条序列', required: true },
      algorithm: { type: 'string', description: 'needleman-wunsch 或 smith-waterman', enum: ['needleman-wunsch', 'smith-waterman'] },
      matrix: { type: 'string', description: 'BLOSUM62 / BLOSUM45 / PAM250', enum: ['BLOSUM62', 'BLOSUM45', 'PAM250'] },
    },
  },
  {
    name: 'fetch_uniprot',
    description: '获取 UniProt 蛋白质条目: 名称/物种/序列/功能注释/亚细胞定位/关键词。',
    parameters: {
      uniprot_id: { type: 'string', description: 'UniProt accession, 如 P0DTC2', required: true },
    },
  },
  {
    name: 'find_similar_sequences',
    description: '根据关键词搜索 UniProt 相关蛋白质条目。',
    parameters: {
      query: { type: 'string', description: '蛋白名称或关键词', required: true },
      limit: { type: 'number', description: '返回数量, 默认 5' },
    },
  },
  {
    name: 'get_kg_neighbors',
    description: '查询本地知识图谱中某结构(PDB ID)的邻居节点: 关联文献、共享文献的结构等。',
    parameters: {
      structure_id: { type: 'string', description: 'PDB ID', required: true },
      depth: { type: 'number', description: '遍历深度, 默认 1' },
    },
  },
  {
    name: 'compare_structures',
    description: '比较两个 PDB 结构的序列一致性与元数据差异(方法/分辨率/实体)。',
    parameters: {
      structure_id1: { type: 'string', description: '第一个 PDB ID', required: true },
      structure_id2: { type: 'string', description: '第二个 PDB ID', required: true },
    },
  },
  {
    name: 'analyze_resolution',
    description: '分析一个结构的分辨率质量, 给出 Cryo-EM/X-ray 质量评级。',
    parameters: {
      structure_id: { type: 'string', description: 'PDB ID', required: true },
      threshold: { type: 'number', description: '分辨率阈值(Å), 默认 3.0' },
    },
  },
  {
    name: 'analyze_sequence',
    description: '深度分析一条序列: 蛋白质(分子量/等电点/GRAVY/氨基酸组成/二级结构倾向)或核酸(GC 含量/Tm/ORF/翻译)。',
    parameters: {
      sequence: { type: 'string', description: '单字母编码序列', required: true },
      type: { type: 'string', description: 'protein 或 nucleic', enum: ['protein', 'nucleic'] },
    },
  },
  {
    name: 'get_publication_info',
    description: '获取本地文献库中某文献的详细信息(标题/作者/年份/DOI/摘要)。',
    parameters: {
      literature_id: { type: 'string', description: '文献 ID' },
      title_query: { type: 'string', description: '按标题模糊检索' },
    },
  },
];

// ============ 工具执行器 ============

export interface ToolCallRecord {
  tool: string;
  params: Record<string, unknown>;
  resultSummary: string;
  latencyMs: number;
  ok: boolean;
}

export async function executeTool(name: string, params: Record<string, unknown>): Promise<unknown> {
  switch (name) {
    case 'search_literature': {
      const query = String(params.query || '');
      const limit = Math.min(Number(params.limit) || 6, 12);
      const hits = await ragSearch(query, 'hybrid', limit);
      return {
        total: hits.length,
        fragments: hits.map((h, i) => ({
          index: i + 1,
          literature_id: h.literatureId,
          title: h.title || '未命名',
          section: h.section,
          score: Math.round(h.score * 1000) / 1000,
          content: h.content.slice(0, 1200),
        })),
      };
    }
    case 'search_structures': {
      const query = String(params.query || '');
      const limit = Math.min(Number(params.limit) || 8, 15);
      const hits = await searchRcsbStructures(query, limit);
      return { total: hits.length, structures: hits };
    }
    case 'get_structure_details': {
      const id = String(params.structure_id || '').toUpperCase();
      const local = await db.structure.findUnique({ where: { id } });
      const detail = await fetchStructureDetail(id);
      if (!detail && local) {
        return {
          structure_id: id,
          title: local.title,
          method: local.method,
          resolution: local.resolution,
          organism: local.organism,
          uniprot_ids: safeParse(local.uniprotIds, []),
          sequences: safeParse(local.sequenceJson, []),
          citation: safeParse(local.citationJson, null),
          note: '来自本地缓存 (RCSB 不可达)',
        };
      }
      if (!detail) return { error: `结构 ${id} 未找到 (RCSB 不可达)` };
      // 缓存到本地
      await cacheStructure(detail);
      return detail;
    }
    case 'run_sequence_alignment': {
      const s1 = String(params.sequence1 || '');
      const s2 = String(params.sequence2 || '');
      const result = alignSequences(s1, s2, {
        algorithm: (params.algorithm as 'needleman-wunsch' | 'smith-waterman') || 'needleman-wunsch',
        matrix: (params.matrix as MatrixName) || 'BLOSUM62',
        gapOpen: -11,
        gapExtend: -1,
      });
      return {
        algorithm: result.algorithm,
        matrix: result.matrix,
        score: result.score,
        identity: result.identity,
        similarity: result.similarity,
        gaps: result.gaps,
        aligned_length: result.alignedLength,
        seq1_aligned: result.seq1Aligned.slice(0, 600),
        seq2_aligned: result.seq2Aligned.slice(0, 600),
        match_line: result.matchLine.slice(0, 600),
        range1: result.seq1Range,
        range2: result.seq2Range,
        consensus: result.consensus.slice(0, 600),
      };
    }
    case 'fetch_uniprot': {
      const uid = String(params.uniprot_id || '').toUpperCase();
      const entry = await fetchUniprotEntry(uid);
      if (!entry) return { error: `UniProt ${uid} 未找到` };
      return {
        accession: entry.primaryAccession,
        name: entry.proteinDescription?.recommendedName?.fullName?.value,
        organism: entry.organism?.scientificName,
        sequence: entry.sequence?.value?.slice(0, 2000),
        length: entry.sequence?.length,
        keywords: (entry.keywords || []).map((k) => k.name).slice(0, 20),
        comments: (entry.comments || [])
          .filter((c) => ['FUNCTION', 'SUBCELLULAR LOCATION', 'TISSUE SPECIFICITY'].includes(c.commentType))
          .map((c) => ({
            type: c.commentType,
            text: (c.texts || []).map((t) => t.text).join(' ').slice(0, 800),
          })),
      };
    }
    case 'find_similar_sequences': {
      const query = String(params.query || '');
      const limit = Math.min(Number(params.limit) || 5, 10);
      const entries = await searchUniprotByQuery(query, limit);
      return {
        total: entries.length,
        entries: entries.map((e) => ({
          accession: e.primaryAccession,
          name: e.proteinDescription?.recommendedName?.fullName?.value,
          organism: e.organism?.scientificName,
          length: e.sequence?.length,
        })),
      };
    }
    case 'get_kg_neighbors': {
      const sid = String(params.structure_id || '').toUpperCase();
      const links = await db.structureLink.findMany({
        where: { structureId: sid },
        include: { literature: { select: { id: true, title: true, year: true } } },
      });
      const siblingIds = await db.structureLink.groupBy({
        by: ['structureId'],
        where: { literatureId: { in: links.map((l) => l.literatureId) }, structureId: { not: sid } },
        _count: { literatureId: true },
        orderBy: { _count: { literatureId: 'desc' } },
        take: 10,
      });
      return {
        structure_id: sid,
        literature_neighbors: links.map((l) => ({
          literature_id: l.literature.id,
          title: l.literature.title,
          year: l.literature.year,
          mention_count: l.mentionCount,
        })),
        related_structures: siblingIds.map((s) => ({
          structure_id: s.structureId,
          shared_literature: s._count.literatureId,
        })),
      };
    }
    case 'compare_structures': {
      const id1 = String(params.structure_id1 || '').toUpperCase();
      const id2 = String(params.structure_id2 || '').toUpperCase();
      const [d1, d2] = await Promise.all([fetchStructureDetail(id1), fetchStructureDetail(id2)]);
      if (!d1 || !d2) return { error: '至少一个结构未找到' };
      if (d1) await cacheStructure(d1);
      if (d2) await cacheStructure(d2);
      const seq1 = d1.sequences[0]?.sequence || '';
      const seq2 = d2.sequences[0]?.sequence || '';
      let identity: number | null = null;
      if (seq1 && seq2) {
        const aln = alignSequences(seq1, seq2, { algorithm: 'needleman-wunsch', matrix: 'BLOSUM62', gapOpen: -11, gapExtend: -1 });
        identity = aln.identity;
      }
      return {
        structure1: { id: id1, title: d1.title, method: d1.method, resolution: d1.resolution, entities: d1.entityCount },
        structure2: { id: id2, title: d2.title, method: d2.method, resolution: d2.resolution, entities: d2.entityCount },
        sequence_identity: identity,
        quick_similarity: seq1 && seq2 ? quickSimilarity(seq1, seq2) : null,
        differences: {
          method: d1.method !== d2.method,
          resolution_gap: (d1.resolution || 0) - (d2.resolution || 0),
          entity_count_diff: d1.entityCount - d2.entityCount,
        },
      };
    }
    case 'analyze_resolution': {
      const id = String(params.structure_id || '').toUpperCase();
      const threshold = Number(params.threshold) || 3.0;
      const d = await fetchStructureDetail(id);
      if (!d) return { error: `结构 ${id} 未找到` };
      await cacheStructure(d);
      const res = d.resolution;
      let grade = '未知';
      if (res != null) {
        if (res <= 2) grade = '优秀 (atomic)';
        else if (res <= 3) grade = '良好';
        else if (res <= 4) grade = '中等';
        else if (res <= 6) grade = '可用 (interpret with caution)';
        else grade = '较低 (仅轮廓)';
      }
      return {
        structure_id: id,
        method: d.method,
        resolution: res,
        threshold,
        grade,
        meets_threshold: res != null ? res <= threshold : null,
        advice:
          res != null && res > threshold
            ? `分辨率 ${res}Å 超过阈值 ${threshold}Å, 建议查找其他结构或结合 AlphaFold 模型`
            : '分辨率满足要求',
      };
    }
    case 'analyze_sequence': {
      const seq = String(params.sequence || '');
      const type = String(params.type || 'protein');
      if (type === 'nucleic') {
        const r = analyzeNucleicAcid(seq);
        return {
          type: 'nucleic',
          is_rna: r.isRna,
          length: r.length,
          gc_content: r.gcContent,
          melting_temp: r.meltingTemp,
          molecular_weight: r.molecularWeight,
          orf_count: r.orfs.length,
          top_orfs: r.orfs.slice(0, 3),
          translation_preview: r.proteinTranslation.slice(0, 200),
        };
      }
      const r = analyzeSequence(seq);
      return {
        type: 'protein',
        length: r.length,
        molecular_weight_kda: r.molecularWeightKDa,
        theoretical_pi: r.theoreticalPi,
        gravy: r.gravy,
        instability_index: r.instabilityIndex,
        stability: r.stabilityClass,
        aromaticity: r.aromaticity,
        net_charge: r.chargedResidues.net,
        ss_tendency: r.ssTendency,
        top_amino_acids: r.compositionChart.slice(0, 8).map((a) => ({ code: a.code, percent: a.percent })),
      };
    }
    case 'get_publication_info': {
      const litId = params.literature_id ? String(params.literature_id) : null;
      const titleQuery = params.title_query ? String(params.title_query) : null;
      let where: Record<string, unknown> | undefined;
      if (litId) where = { id: litId };
      else if (titleQuery) where = { title: { contains: titleQuery } };
      const lits = await db.literature.findMany({ where, take: 5, orderBy: { createdAt: 'desc' } });
      return {
        total: lits.length,
        publications: lits.map((l) => ({
          id: l.id,
          title: l.title,
          authors: safeParse<string[]>(l.authors, []),
          year: l.year,
          journal: l.journal,
          doi: l.doi,
          abstract: (l.abstract || '').slice(0, 600),
        })),
      };
    }
    default:
      return { error: `未知工具: ${name}` };
  }
}

async function cacheStructure(d: NonNullable<Awaited<ReturnType<typeof fetchStructureDetail>>>): Promise<void> {
  try {
    await db.structure.upsert({
      where: { id: d.pdbId },
      create: {
        id: d.pdbId,
        title: d.title,
        method: d.method,
        resolution: d.resolution,
        organism: d.organism,
        uniprotIds: JSON.stringify(d.uniprotIds),
        entityCount: d.entityCount,
        residueCount: d.residueCount,
        ligandInfo: JSON.stringify(d.ligands),
        citationJson: d.citation ? JSON.stringify(d.citation) : null,
        sequenceJson: JSON.stringify(d.sequences),
      },
      update: {
        title: d.title,
        method: d.method,
        resolution: d.resolution,
        organism: d.organism,
        uniprotIds: JSON.stringify(d.uniprotIds),
        entityCount: d.entityCount,
        residueCount: d.residueCount,
        ligandInfo: JSON.stringify(d.ligands),
        citationJson: d.citation ? JSON.stringify(d.citation) : null,
        sequenceJson: JSON.stringify(d.sequences),
        accessCount: { increment: 1 },
      },
    });
  } catch {
    /* 缓存失败不影响主流程 */
  }
}

// ============ Agent 循环 ============

export interface AgentOptions {
  skillId?: string | null;
  maxSteps?: number;
  onToolCall?: (record: ToolCallRecord) => void;
}

const TOOL_PROTOCOL = `你可以调用以下工具获取实时数据。当需要外部信息时, 你的回复必须是一个 JSON 对象 (独占一行, 不要 markdown 代码块):

{"action":"call_tool","tool":"<工具名>","params":{...参数对象...}}

注意: "action" 字段只允许两个值 —— "call_tool" (调用工具) 或 "final_answer" (给出最终回答)。不要把工具名写进 action 字段。

当你已收集到足够信息, 准备给出最终回答时, 输出:

{"action":"final_answer","content":"<完整的 Markdown 最终回答>"}

规则:
- 每次只调用一个工具
- 工具结果会以 "TOOL_RESULT" 角色消息返回给你
- 最多调用 6 次工具; 若信息不足也要基于已有信息作答
- 最终回答使用 Markdown, 引用文献时标注 [编号]
- 不要编造 PDB ID / UniProt ID / 数据, 一切以工具结果为准`;

export function buildToolList(tools: ToolDef[]): string {
  return tools
    .map((t) => {
      const params = Object.entries(t.parameters)
        .map(([k, v]) => `${k}(${v.type}${v.required ? ', 必填' : ''}): ${v.description}`)
        .join('; ');
      return `- ${t.name}: ${t.description}\n  参数: ${params}`;
    })
    .join('\n');
}

export async function runAgent(
  question: string,
  history: ChatMessage[],
  options: AgentOptions = {}
): Promise<{ answer: string; toolCalls: ToolCallRecord[]; messages: ChatMessage[] }> {
  const maxSteps = Math.min(options.maxSteps || 6, 8);
  const toolCalls: ToolCallRecord[] = [];
  const messages: ChatMessage[] = [...history];

  // 系统提示
  let systemPrompt = `你是 CryoAgent Pro —— 蛋白质结构智能分析 Agent。\n\n${TOOL_PROTOCOL}\n\n可用工具:\n${buildToolList(AGENT_TOOLS)}`;
  if (options.skillId) {
    const skillRow = await db.skill.findUnique({ where: { id: options.skillId } });
    if (skillRow) {
      systemPrompt += `\n\n当前激活技能: ${skillRow.name}\n${skillRow.systemPrompt}`;
      await db.skill.update({ where: { id: options.skillId }, data: { usageCount: { increment: 1 } } }).catch(() => {});
    }
  }

  messages.push({ role: 'user', content: question });

  for (let step = 0; step < maxSteps; step++) {
    const msgs: ChatMessage[] = [{ role: 'assistant', content: systemPrompt }, ...messages.slice(-16)];
    const { content } = await chatCompletion(msgs);

    // 解析 JSON action
    const action = parseAgentAction(content);
    if (!action) {
      // 无法解析 → 视为最终回答
      return { answer: content, toolCalls, messages: [...messages, { role: 'assistant', content }] };
    }
    if (action.type === 'final') {
      return { answer: action.content, toolCalls, messages: [...messages, { role: 'assistant', content: action.content }] };
    }

    // 执行工具
    const start = Date.now();
    let result: unknown;
    let ok = true;
    try {
      result = await executeTool(action.tool, action.params);
    } catch (err) {
      ok = false;
      result = { error: err instanceof Error ? err.message : String(err) };
    }
    const latencyMs = Date.now() - start;
    const record: ToolCallRecord = {
      tool: action.tool,
      params: action.params,
      resultSummary: summarizeResult(result),
      latencyMs,
      ok,
    };
    toolCalls.push(record);
    options.onToolCall?.(record);

    messages.push({ role: 'assistant', content: content.trim() });
    messages.push({
      role: 'user',
      content: `TOOL_RESULT (${action.tool}):\n${JSON.stringify(result, null, 1).slice(0, 6000)}\n\n请基于以上结果继续 (调用下一个工具或给出 final_answer)。`,
    });
  }

  // 超过最大步数, 强制总结
  messages.push({
    role: 'user',
    content: '已达到工具调用上限, 请立即基于已收集的信息输出最终回答。',
  });
  const { content } = await chatCompletion([{ role: 'assistant', content: systemPrompt }, ...messages.slice(-12)]);
  return { answer: content, toolCalls, messages: [...messages, { role: 'assistant', content }] };
}

function parseAgentAction(text: string): { type: 'tool'; tool: string; params: Record<string, unknown> } | { type: 'final'; content: string } | null {
  const cleaned = text.replace(/```json\s*/g, '').replace(/```\s*/g, '').trim();
  const tryParse = (s: string): { type: 'tool'; tool: string; params: Record<string, unknown> } | { type: 'final'; content: string } | null => {
    try {
      const obj = JSON.parse(s);
      return validateAction(obj);
    } catch {
      return null;
    }
  };
  // 尝试直接解析整段
  let result = tryParse(cleaned);
  if (result) return result;
  // 提取第一个 {...}
  const match = cleaned.match(/\{[\s\S]*\}/);
  if (match) {
    result = tryParse(match[0]);
    if (result) return result;
  }
  return null;
}

const KNOWN_TOOL_NAMES = new Set(AGENT_TOOLS.map((t) => t.name));

function validateAction(obj: unknown): { type: 'tool'; tool: string; params: Record<string, unknown> } | { type: 'final'; content: string } | null {
  if (typeof obj !== 'object' || obj === null) return null;
  const o = obj as Record<string, unknown>;
  // 标准格式: {"action":"call_tool","tool":...,"params":{...}}
  if (o.action === 'call_tool' && typeof o.tool === 'string') {
    return { type: 'tool', tool: o.tool, params: (o.params as Record<string, unknown>) || {} };
  }
  // 标准格式: {"action":"final_answer","content":"..."}
  if (o.action === 'final_answer' && typeof o.content === 'string') {
    return { type: 'final', content: o.content };
  }
  // 容错格式: {"action":"<工具名>", ...} 或 {"tool":"<工具名>","params":{...}}
  const actionName = typeof o.action === 'string' ? o.action : typeof o.tool === 'string' ? o.tool : null;
  if (actionName && KNOWN_TOOL_NAMES.has(actionName)) {
    return {
      type: 'tool',
      tool: actionName,
      params: (o.params as Record<string, unknown>) || (o.arguments as Record<string, unknown>) || (o.parameters as Record<string, unknown>) || {},
    };
  }
  // 容错格式: {"final_answer": "..."} / {"answer": "..."}
  if (typeof o.final_answer === 'string') {
    return { type: 'final', content: o.final_answer };
  }
  return null;
}

function summarizeResult(result: unknown): string {
  const s = JSON.stringify(result) || '';
  if (s.length <= 300) return s;
  return `${s.slice(0, 300)}... (${s.length} chars)`;
}
