/**
 * CryoAgent Pro - 外部生物学数据库客户端
 * RCSB PDB / UniProt / AlphaFold / EMDB (服务端调用, 带内存缓存)
 * 对应原 Flask 版 core/pdb_fetcher.py + core/uniprot_client.py
 */

const CACHE_TTL = 1000 * 60 * 60 * 6; // 6 小时
const cache = new Map<string, { data: unknown; ts: number }>();

async function cachedFetch<T>(key: string, url: string, timeoutMs = 15000): Promise<T | null> {
  const hit = cache.get(key);
  if (hit && Date.now() - hit.ts < CACHE_TTL) return hit.data as T;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const resp = await fetch(url, {
      signal: controller.signal,
      headers: { 'User-Agent': 'CryoAgentPro/2.0 (Next.js)' },
    });
    clearTimeout(timer);
    if (!resp.ok) return null;
    const data = (await resp.json()) as T;
    cache.set(key, { data, ts: Date.now() });
    return data;
  } catch {
    return null;
  }
}

async function cachedText(key: string, url: string, timeoutMs = 20000): Promise<string | null> {
  const hit = cache.get(key);
  if (hit && Date.now() - hit.ts < CACHE_TTL) return hit.data as string;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const resp = await fetch(url, {
      signal: controller.signal,
      headers: { 'User-Agent': 'CryoAgentPro/2.0' },
    });
    clearTimeout(timer);
    if (!resp.ok) return null;
    const data = await resp.text();
    cache.set(key, { data, ts: Date.now() });
    return data;
  } catch {
    return null;
  }
}

// ============ RCSB PDB ============

export interface RcsbEntry {
  rcsb_id: string;
  struct: { title: string };
  exptl?: { method: string }[];
  rcsb_entry_info?: {
    resolution_combined?: number[];
    polymer_entity_count?: number;
    deposited_polymer_entity_instance_count?: number;
    polymer_monomer_count?: number;
  };
  rcsb_primary_citation?: {
    title?: string;
    journal_abbrev?: string;
    year?: number;
    rcsb_authors?: string[];
    pdbid?: string;
  };
  rcsb_accession_info?: {
    deposit_date?: string;
    initial_release_date?: string;
  };
  organismNames?: string[];
}

export interface RcsbEntity {
  rcsb_polymer_entity: {
    entity_id: string;
    pdbx_description: string;
    rcsb_polymer_entity_container_identifiers?: { uniprot_ids?: string[]; asym_ids?: string[] };
  };
  entity_poly?: {
    pdbx_seq_one_letter_code_can?: string;
  };
  rcsb_entity_source_organism?: { ncbi_scientific_name?: string; scientific_name?: string }[];
}

export interface StructureDetail {
  pdbId: string;
  title: string;
  method: string | null;
  resolution: number | null;
  organism: string | null;
  uniprotIds: { uniprotId: string; chains: string[]; proteinName: string }[];
  entityCount: number;
  residueCount: number | null;
  ligands: { name: string; formula?: string; description?: string }[];
  citation: {
    title: string;
    journal: string;
    year: number | null;
    authors: string[];
  } | null;
  sequences: {
    entityId: string;
    chains: string[];
    sequence: string;
    length: number;
    description: string;
    uniprotIds: string[];
  }[];
  depositDate: string | null;
  releaseDate: string | null;
  emdbIds: string[];
}

/** 获取 PDB 结构完整详情 (对应原 fetch_complete_metadata) */
export async function fetchStructureDetail(pdbIdRaw: string): Promise<StructureDetail | null> {
  const pdbId = pdbIdRaw.toUpperCase().trim();
  const entry = await cachedFetch<RcsbEntry>(`entry:${pdbId}`, `https://data.rcsb.org/rest/v1/core/entry/${pdbId}`);
  if (!entry) return null;

  // 获取所有实体: 尝试 1..N (并行, 失败返回 null 不阻塞其他实体)
  const entityCount = entry.rcsb_entry_info?.polymer_entity_count || 1;
  const allEntities: RcsbEntity[] = (
    await Promise.all(
      Array.from({ length: Math.min(entityCount, 10) }, (_, i) =>
        cachedFetch<RcsbEntity>(
          `entity:${pdbId}:${i + 1}`,
          `https://data.rcsb.org/rest/v1/core/polymer_entity/${pdbId}/${i + 1}`
        )
      )
    )
  ).filter((e): e is RcsbEntity => e !== null);

  // 配体信息
  const ligands = await cachedFetch<{ rcsb_ligand_container_identifiers?: { id?: string } }[]>(
    `ligands:${pdbId}`,
    `https://data.rcsb.org/rest/v1/core/chem_ref/${pdbId}`,
    5000
  );

  // UniProt 蛋白名称
  const uniprotMap = new Map<string, { chains: string[]; proteinName: string }>();
  for (const e of allEntities) {
    const ids = e.rcsb_polymer_entity?.rcsb_polymer_entity_container_identifiers?.uniprot_ids || [];
    const chains = e.rcsb_polymer_entity?.rcsb_polymer_entity_container_identifiers?.asym_ids || [];
    for (const uid of ids) {
      const key = uid.toUpperCase();
      if (!uniprotMap.has(key)) uniprotMap.set(key, { chains: [...chains], proteinName: '' });
      else {
        const cur = uniprotMap.get(key)!;
        for (const c of chains) if (!cur.chains.includes(c)) cur.chains.push(c);
      }
    }
  }
  // 蛋白名称: 取前 8 个 UniProt 查询 (并行)
  const uidList = [...uniprotMap.keys()].slice(0, 8);
  await Promise.all(
    uidList.map(async (uid) => {
      const uni = await fetchUniprotEntry(uid);
      if (uni) {
        uniprotMap.get(uid)!.proteinName =
          uni.proteinDescription?.recommendedName?.fullName?.value?.slice(0, 60) || '';
      }
    })
  );

  // 序列
  const sequences = allEntities.map((e) => {
    const raw = e.entity_poly?.pdbx_seq_one_letter_code_can || '';
    const seq = raw.replace(/\s+/g, '');
    return {
      entityId: e.rcsb_polymer_entity.entity_id,
      chains: e.rcsb_polymer_entity.rcsb_polymer_entity_container_identifiers?.asym_ids || [],
      sequence: seq,
      length: seq.length,
      description: e.rcsb_polymer_entity.pdbx_description || `Entity ${e.rcsb_polymer_entity.entity_id}`,
      uniprotIds: e.rcsb_polymer_entity.rcsb_polymer_entity_container_identifiers?.uniprot_ids || [],
    };
  });

  // EMDB 关联 (cross-reference)
  const emdbIds = await fetchRelatedEmdb(pdbId);

  const cit = entry.rcsb_primary_citation;

  return {
    pdbId,
    title: entry.struct?.title || pdbId,
    method: entry.exptl?.[0]?.method || null,
    resolution: entry.rcsb_entry_info?.resolution_combined?.[0] ?? null,
    organism: allEntities[0]?.rcsb_entity_source_organism?.[0]?.ncbi_scientific_name || null,
    uniprotIds: [...uniprotMap.entries()].map(([uniprotId, v]) => ({ uniprotId, ...v })),
    entityCount: entityCount,
    residueCount: entry.rcsb_entry_info?.polymer_monomer_count ?? null,
    ligands: (ligands || [])
      .map((l) => ({ name: l.rcsb_ligand_container_identifiers?.id || '' }))
      .filter((l) => l.name && l.name !== pdbId)
      .slice(0, 20),
    citation: cit
      ? {
          title: cit.title || '',
          journal: cit.journal_abbrev || '',
          year: cit.year ?? null,
          authors: cit.rcsb_authors || [],
        }
      : null,
    sequences,
    depositDate: entry.rcsb_accession_info?.deposit_date || null,
    releaseDate: entry.rcsb_accession_info?.initial_release_date || null,
    emdbIds,
  };
}

// ============ RCSB PDB 实体搜索 ============
async function fetchRelatedEmdb(pdbId: string): Promise<string[]> {
  try {
    const data = await cachedText(`emdb:${pdbId}`, `https://www.ebi.ac.uk/pdbe/api/pdb/entry/summary/${pdbId.toLowerCase()}`, 10000);
    if (!data) return [];
    const parsed = JSON.parse(data) as Record<string, { emd?: string }[]>;
    const emdIds: string[] = [];
    for (const entries of Object.values(parsed)) {
      for (const e of entries) {
        if (e.emd) {
          const ids = Array.isArray(e.emd) ? e.emd : [e.emd];
          for (const id of ids) {
            const formatted = String(id).toUpperCase();
            if (formatted && !emdIds.includes(formatted)) emdIds.push(formatted);
          }
        }
      }
    }
    return emdIds;
  } catch {
    return [];
  }
}

/** RCSB 全文搜索 (对应原 search_structures) */
export interface RcsbSearchHit {
  identifier: string;
  score: number;
  title?: string;
  method?: string;
  resolution?: number;
}

export async function searchRcsbStructures(query: string, limit = 20): Promise<RcsbSearchHit[]> {
  const body = {
    query: {
      type: 'group',
      logical_operator: 'or',
      nodes: [
        {
          type: 'terminal',
          service: 'full_text',
          parameters: { value: query },
        },
        {
          type: 'terminal',
          service: 'text',
          parameters: {
            attribute: 'struct.title',
            operator: 'contains_words',
            value: query,
          },
        },
      ],
    },
    request_options: {
      paginate: { start: 0, rows: limit },
      results_content_type: ['experimental'],
      scoring_strategy: 'combined',
    },
    return_type: 'entry',
  };

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    const resp = await fetch('https://search.rcsb.org/rcsbsearch/v2/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!resp.ok) return [];
    const data = (await resp.json()) as {
      result_set?: { identifier: string; score: number }[];
      total_count: number;
    };
    const hits = (data.result_set || []).slice(0, limit);
    // 补充标题
    return await Promise.all(
      hits.map(async (h) => {
        const entry = await cachedFetch<RcsbEntry>(`entry:${h.identifier}`, `https://data.rcsb.org/rest/v1/core/entry/${h.identifier}`, 8000);
        return {
          identifier: h.identifier,
          score: Math.round(h.score * 1000) / 1000,
          title: entry?.struct?.title,
          method: entry?.exptl?.[0]?.method,
          resolution: entry?.rcsb_entry_info?.resolution_combined?.[0],
        };
      })
    );
  } catch {
    return [];
  }
}

/** 获取 PDB 原始文件文本 (给 3Dmol 用) */
export async function fetchPdbFile(pdbId: string): Promise<string | null> {
  const id = pdbId.toUpperCase().trim();
  const text = await cachedText(`pdbfile:${id}`, `https://files.rcsb.org/download/${id}.pdb`, 25000);
  if (text) return text;
  // 回退 mmCIF
  const cif = await cachedText(`ciffile:${id}`, `https://files.rcsb.org/download/${id}.cif`, 25000);
  return cif;
}

/** 获取 AlphaFold 预测 PDB */
export async function fetchAlphaFoldModel(uniprotId: string): Promise<string | null> {
  const uid = uniprotId.toUpperCase().trim();
  return cachedText(`af:${uid}`, `https://alphafold.ebi.ac.uk/files/AF-${uid}-F1-model_v4.pdb`, 25000);
}

// ============ UniProt ============

export interface UniprotEntry {
  primaryAccession: string;
  uniProtkbId?: string;
  proteinDescription?: {
    recommendedName?: { fullName?: { value?: string } };
    submissionNames?: { fullName?: { value?: string } }[];
  };
  organism?: { scientificName?: string; commonName?: string };
  sequence?: { value?: string; length?: number; molWeight?: number };
  proteinExistence?: string;
  keywords?: { name: string }[];
  genes?: { geneName?: { value?: string } }[];
  comments?: {
    commentType: string;
    texts?: { text?: string }[];
    subcellularLocations?: { location?: { value?: string } }[];
  }[];
  dbReferences?: { id: string; properties?: { value: string }[] }[];
  entryType?: string;
}

export async function fetchUniprotEntry(uniprotId: string): Promise<UniprotEntry | null> {
  const uid = uniprotId.toUpperCase().trim();
  return cachedFetch<UniprotEntry>(`uniprot:${uid}`, `https://rest.uniprot.org/uniprotkb/${uid}.json`, 12000);
}

/** UniProt 相似序列搜索 (对应原 find_similar_sequences / _fallback_uniprot_search) */
export async function searchUniprotBySequence(sequence: string, limit = 10): Promise<UniprotEntry[]> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    const resp = await fetch(
      `https://rest.uniprot.org/uniprotkb/search?query=${encodeURIComponent(sequence.slice(0, 100))}&format=json&size=${limit}`,
      { signal: controller.signal }
    );
    clearTimeout(timer);
    if (!resp.ok) return [];
    const data = (await resp.json()) as { results?: UniprotEntry[] };
    return data.results || [];
  } catch {
    return [];
  }
}

/** UniProt 文本搜索 */
export async function searchUniprotByQuery(query: string, limit = 10): Promise<UniprotEntry[]> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    const resp = await fetch(
      `https://rest.uniprot.org/uniprotkb/search?query=${encodeURIComponent(query)}&format=json&size=${limit}&fields=accession,id,protein_name,organism_name,length,sequence`,
      { signal: controller.signal }
    );
    clearTimeout(timer);
    if (!resp.ok) return [];
    const data = (await resp.json()) as { results?: UniprotEntry[] };
    return data.results || [];
  } catch {
    return [];
  }
}

/** EMDB 条目信息 */
export interface EmdbEntry {
  emdb_id: string;
  title: string;
  method?: string;
  resolution?: number;
}

export async function fetchEmdbEntry(emdbId: string): Promise<EmdbEntry | null> {
  const id = emdbId.toUpperCase().replace(/[^0-9EMDB-]/g, '');
  const formatted = id.startsWith('EMD-') ? id : `EMD-${id.replace('EMDB', '').replace('-', '')}`;
  try {
    const text = await cachedText(`emdb:${formatted}`, `https://www.ebi.ac.uk/pdbe/api/emdb/entry/summary/${formatted}`, 12000);
    if (!text) return null;
    const parsed = JSON.parse(text) as Record<
      string,
      { title?: string; experiment?: { technique?: string }; resolution?: number }[]
    >;
    for (const entries of Object.values(parsed)) {
      const e = entries[0];
      if (e) {
        return {
          emdb_id: formatted,
          title: e.title || formatted,
          method: e.experiment?.technique,
          resolution: e.resolution,
        };
      }
    }
    return null;
  } catch {
    return null;
  }
}
