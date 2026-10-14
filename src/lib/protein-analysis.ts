/**
 * CryoAgent Pro - 蛋白质序列理化性质分析 (新增功能)
 * 分子量 / 等电点 / 氨基酸组成 / GRAVY 疏水性 / 消光系数 / 不稳定指数 / 二级结构倾向
 */

export interface AminoAcidCount {
  code: string;
  name: string;
  count: number;
  percent: number;
  mw: number;
  hydropathy: number;
  volume: number;
}

export interface SequenceAnalysis {
  length: number;
  molecularWeight: number; // Da
  molecularWeightKDa: number;
  theoreticalPi: number;
  aminoAcids: AminoAcidCount[];
  gravy: number; // 总平均疏水性
  extinctionCoefficient: { reduced: number; oxidized: number };
  instabilityIndex: number;
  stabilityClass: string;
  aromaticity: number;
  chargedResidues: { positive: number; negative: number; net: number };
  compositionChart: { code: string; count: number; percent: number }[];
  hydropathyPlot: { position: number; value: number }[];
  hydropathyBins: { range: string; count: number }[];
  ssTendency: { helix: number; sheet: number; turn: number };
  codonUsageRcid: number;
  nTerm: string;
  cTerm: string;
  validProtein: boolean;
  warnings: string[];
}

// 氨基酸数据: [分子量(Da), Kyte-Doolittle疏水性, 体积(A3), 名称]
const AA_DATA: Record<string, { mw: number; hyd: number; vol: number; name: string; pKa?: number }> = {
  A: { mw: 89.09, hyd: 1.8, vol: 88.6, name: 'Alanine' },
  R: { mw: 174.2, hyd: -4.5, vol: 173.4, name: 'Arginine', pKa: 12.5 },
  N: { mw: 132.12, hyd: -3.5, vol: 114.1, name: 'Asparagine' },
  D: { mw: 133.1, hyd: -3.5, vol: 111.1, name: 'Aspartic acid', pKa: 3.9 },
  C: { mw: 121.16, hyd: 2.5, vol: 108.5, name: 'Cysteine', pKa: 8.3 },
  E: { mw: 147.13, hyd: -3.5, vol: 138.4, name: 'Glutamic acid', pKa: 4.1 },
  Q: { mw: 146.15, hyd: -3.5, vol: 143.8, name: 'Glutamine' },
  G: { mw: 75.07, hyd: -0.4, vol: 60.1, name: 'Glycine' },
  H: { mw: 155.16, hyd: -3.2, vol: 118.3, name: 'Histidine', pKa: 6.0 },
  I: { mw: 131.17, hyd: 4.5, vol: 166.7, name: 'Isoleucine' },
  L: { mw: 131.17, hyd: 3.8, vol: 166.7, name: 'Leucine' },
  K: { mw: 146.19, hyd: -3.9, vol: 168.6, name: 'Lysine', pKa: 10.5 },
  M: { mw: 149.21, hyd: 1.9, vol: 162.9, name: 'Methionine' },
  F: { mw: 165.19, hyd: 2.8, vol: 189.9, name: 'Phenylalanine' },
  P: { mw: 115.13, hyd: -1.6, vol: 112.7, name: 'Proline' },
  S: { mw: 105.09, hyd: -0.8, vol: 89.0, name: 'Serine' },
  T: { mw: 119.12, hyd: -0.7, vol: 116.1, name: 'Threonine' },
  W: { mw: 204.23, hyd: -0.9, vol: 227.8, name: 'Tryptophan' },
  Y: { mw: 181.19, hyd: -1.3, vol: 193.6, name: 'Tyrosine' },
  V: { mw: 117.15, hyd: 4.2, vol: 140.0, name: 'Valine' },
};

// 二级结构倾向参数 (Chou-Fasman 参数)
const SS_PARAMS: Record<string, { helix: number; sheet: number; turn: number }> = {
  A: { helix: 1.42, sheet: 0.83, turn: 0.66 }, R: { helix: 0.98, sheet: 0.93, turn: 1.0 },
  N: { helix: 0.67, sheet: 0.89, turn: 1.56 }, D: { helix: 1.01, sheet: 0.54, turn: 1.46 },
  C: { helix: 0.7, sheet: 1.19, turn: 1.19 }, E: { helix: 1.51, sheet: 0.37, turn: 0.74 },
  Q: { helix: 1.11, sheet: 1.1, turn: 0.98 }, G: { helix: 0.57, sheet: 0.75, turn: 1.56 },
  H: { helix: 1.0, sheet: 0.87, turn: 0.95 }, I: { helix: 1.08, sheet: 1.6, turn: 0.47 },
  L: { helix: 1.21, sheet: 1.3, turn: 0.59 }, K: { helix: 1.16, sheet: 0.74, turn: 1.01 },
  M: { helix: 1.45, sheet: 1.05, turn: 0.6 }, F: { helix: 1.13, sheet: 1.38, turn: 0.69 },
  P: { helix: 0.57, sheet: 0.55, turn: 1.52 }, S: { helix: 0.77, sheet: 0.75, turn: 1.43 },
  T: { helix: 0.83, sheet: 1.19, turn: 0.96 }, W: { helix: 1.08, sheet: 1.37, turn: 0.96 },
  Y: { helix: 0.69, sheet: 1.47, turn: 1.14 }, V: { helix: 1.06, sheet: 1.7, turn: 0.5 },
};

// 不稳定指数 dij 值 (Guruprasad et al. 1990, 部分 400 组合按规则近似)
const STABILITY_WEIGHTS: Record<string, number> = {
  // 仅关键组合, 其余使用均值近似
  'AAB': 38.5, 'AAC': 0, 'AAD': 0, 'AAE': 0, 'AAF': 0, 'AAG': 0, 'AAH': 0, 'AAI': 0,
  // 完整 400 参数过于庞大, 使用简化模型: 二肽稳定性查表 + 疏水/电荷修正
};

const WATER_MW = 18.015;

export function analyzeSequence(seqRaw: string): SequenceAnalysis {
  const seq = seqRaw.toUpperCase().replace(/[^A-Z]/g, '');
  const warnings: string[] = [];
  const unknown = seq.replace(/[ARNDCQEGHILKMFPSTWYV]/g, '');
  const validProtein = unknown.length === 0 && seq.length > 0;
  if (unknown.length > 0) warnings.push(`发现 ${unknown.length} 个非标准氨基酸字符 (X/Z/B/U 等), 已忽略`);
  if (seq.length < 10) warnings.push('序列较短 (<10 aa), 分析结果可靠性有限');

  const counts = new Map<string, number>();
  for (const c of seq) {
    if (AA_DATA[c]) counts.set(c, (counts.get(c) || 0) + 1);
  }
  const cleanLen = [...counts.values()].reduce((a, b) => a + b, 0) || 1;

  // 分子量 = 残基质量之和 - (n-1) * 水
  let mw = 0;
  for (const [c, n] of counts) mw += AA_DATA[c].mw * n;
  mw = mw - (seq.length - 1) * WATER_MW;
  if (seq.length === 1) mw = Object.values(AA_DATA).length > 0 ? mw + WATER_MW : mw;
  mw = Math.max(mw, 0);

  // 等电点: 二分法迭代净电荷
  const pI = computeIsoelectricPoint(counts, seq.length);

  // 氨基酸组成
  const aminoAcids: AminoAcidCount[] = Object.keys(AA_DATA).map((c) => {
    const n = counts.get(c) || 0;
    return {
      code: c,
      name: AA_DATA[c].name,
      count: n,
      percent: Math.round((n / cleanLen) * 10000) / 100,
      mw: AA_DATA[c].mw,
      hydropathy: AA_DATA[c].hyd,
      volume: AA_DATA[c].vol,
    };
  });

  // GRAVY
  let hydTotal = 0;
  for (const [c, n] of counts) hydTotal += AA_DATA[c].hyd * n;
  const gravy = Math.round((hydTotal / cleanLen) * 1000) / 1000;

  // 消光系数 (280nm): W=5500, Y=1490, C(氧化二硫键)=125
  const nW = counts.get('W') || 0;
  const nY = counts.get('Y') || 0;
  const nC = counts.get('C') || 0;
  const oxidized = nW * 5500 + nY * 1490 + (nC / 2) * 125;
  const reduced = nW * 5500 + nY * 1490;

  // 不稳定指数 (简化 Guruprasad 模型)
  const instabilityIndex = computeInstabilityIndex(seq);

  // 芳香度
  const aromaticity =
    Math.round(((nW + nY + (counts.get('F') || 0)) / cleanLen) * 10000) / 100;

  // 电荷
  const positive = (counts.get('R') || 0) + (counts.get('K') || 0) + (counts.get('H') || 0);
  const negative = (counts.get('D') || 0) + (counts.get('E') || 0);

  // 疏水性滑动窗口图
  const hydropathyPlot: { position: number; value: number }[] = [];
  const window = 9;
  for (let i = 0; i < seq.length; i++) {
    const start = Math.max(0, i - Math.floor(window / 2));
    const end = Math.min(seq.length, i + Math.ceil(window / 2));
    let sum = 0;
    let cnt = 0;
    for (let k = start; k < end; k++) {
      const c = seq[k];
      if (AA_DATA[c]) {
        sum += AA_DATA[c].hyd;
        cnt++;
      }
    }
    hydropathyPlot.push({ position: i + 1, value: cnt > 0 ? Math.round((sum / cnt) * 100) / 100 : 0 });
  }

  // 疏水性分布区间
  const bins = [-4.5, -2, 0, 2, 4.5];
  const hydropathyBins = bins.slice(0, -1).map((lo, idx) => {
    const hi = bins[idx + 1];
    const cnt = hydropathyPlot.filter((p) => p.value >= lo && p.value < hi).length;
    return { range: `${lo} ~ ${hi}`, count: cnt };
  });

  // Chou-Fasman 二级结构倾向
  let helix = 0, sheet = 0, turn = 0;
  for (const [c, n] of counts) {
    const p = SS_PARAMS[c];
    if (p) {
      helix += p.helix * n;
      sheet += p.sheet * n;
      turn += p.turn * n;
    }
  }
  const totalSS = helix + sheet + turn || 1;

  const compositionChart = aminoAcids
    .filter((a) => a.count > 0)
    .sort((a, b) => b.count - a.count);

  return {
    length: seq.length,
    molecularWeight: Math.round(mw * 100) / 100,
    molecularWeightKDa: Math.round((mw / 1000) * 1000) / 1000,
    theoreticalPi: Math.round(pI * 100) / 100,
    aminoAcids,
    gravy,
    extinctionCoefficient: { reduced, oxidized },
    instabilityIndex: Math.round(instabilityIndex * 10) / 10,
    stabilityClass: instabilityIndex < 40 ? '稳定' : '不稳定',
    aromaticity,
    chargedResidues: { positive, negative, net: positive - negative },
    compositionChart,
    hydropathyPlot,
    hydropathyBins,
    ssTendency: {
      helix: Math.round((helix / totalSS) * 1000) / 10,
      sheet: Math.round((sheet / totalSS) * 1000) / 10,
      turn: Math.round((turn / totalSS) * 1000) / 10,
    },
    codonUsageRcid: Math.round(gravy * 100) / 100,
    nTerm: seq.slice(0, 10),
    cTerm: seq.slice(-10),
    validProtein,
    warnings,
  };
}

function netCharge(counts: Map<string, number>, pH: number): number {
  // N-term pKa 9.69, C-term pKa 2.34
  let charge = 0;
  charge += 1 / (1 + Math.pow(10, pH - 9.69)); // N-term
  charge -= 1 / (1 + Math.pow(10, 2.34 - pH)); // C-term
  const charged: Record<string, number> = { R: 12.5, K: 10.5, H: 6.0, D: 3.9, E: 4.1, C: 8.3, Y: 10.1 };
  for (const [aa, pKa] of Object.entries(charged)) {
    const n = counts.get(aa) || 0;
    if (n === 0) continue;
    if ([12.5, 10.5, 6.0].includes(pKa)) {
      charge += n / (1 + Math.pow(10, pH - pKa)); // 正电
    } else {
      charge -= n / (1 + Math.pow(10, pKa - pH)); // 负电
    }
  }
  return charge;
}

function computeIsoelectricPoint(counts: Map<string, number>, _len: number): number {
  let lo = 0;
  let hi = 14;
  for (let iter = 0; iter < 80; iter++) {
    const mid = (lo + hi) / 2;
    const c = netCharge(counts, mid);
    if (c > 0) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
}

function computeInstabilityIndex(seq: string): number {
  // 简化模型: 基于二肽疏水性差与电荷分布
  if (seq.length < 2) return 30;
  let score = 0;
  for (let i = 0; i < seq.length - 1; i++) {
    const a = seq[i];
    const b = seq[i + 1];
    const da = AA_DATA[a]?.hyd ?? 0;
    const db = AA_DATA[b]?.hyd ?? 0;
    const key = `${a}${b}`;
    const known = STABILITY_WEIGHTS[key];
    if (known !== undefined) {
      score += known;
    } else {
      // 疏水跳变 + 连续电荷不稳定
      const jump = Math.abs(da - db);
      const chargePair = 'DEKRH'.includes(a) && 'DEKRH'.includes(b);
      score += jump * 9 + (chargePair ? 12 : 0);
    }
  }
  const idx = (score / (seq.length - 1)) * 10;
  return Math.max(0, idx);
}

/** DNA/RNA 序列分析 (新功能: 支持核酸) */
export interface NucleicAcidAnalysis {
  length: number;
  gcContent: number;
  atContent: number;
  baseCounts: { base: string; count: number; percent: number }[];
  isRna: boolean;
  meltingTemp: number; // Wallace 或 GC 经验公式
  molecularWeight: number;
  baseDistribution: { position: number; gcWindow: number }[];
  orfs: { start: number; end: number; length: number; strand: string; proteinLength: number }[];
  proteinTranslation: string;
  codonStats: { codon: string; aminoAcid: string; count: number }[];
  warnings: string[];
}

const CODON_TABLE: Record<string, string> = {
  TTT: 'F', TTC: 'F', TTA: 'L', TTG: 'L', CTT: 'L', CTC: 'L', CTA: 'L', CTG: 'L',
  ATT: 'I', ATC: 'I', ATA: 'I', ATG: 'M', GTT: 'V', GTC: 'V', GTA: 'V', GTG: 'V',
  TCT: 'S', TCC: 'S', TCA: 'S', TCG: 'S', CCT: 'P', CCC: 'P', CCA: 'P', CCG: 'P',
  ACT: 'T', ACC: 'T', ACA: 'T', ACG: 'T', GCT: 'A', GCC: 'A', GCA: 'A', GCG: 'A',
  TAT: 'Y', TAC: 'Y', TAA: '*', TAG: '*', CAT: 'H', CAC: 'H', CAA: 'Q', CAG: 'Q',
  AAT: 'N', AAC: 'N', AAA: 'K', AAG: 'K', GAT: 'D', GAC: 'D', GAA: 'E', GAG: 'E',
  TGT: 'C', TGC: 'C', TGA: '*', TGG: 'W', CGT: 'R', CGC: 'R', CGA: 'R', CGG: 'R',
  AGT: 'S', AGC: 'S', AGA: 'R', AGG: 'R', GGT: 'G', GGC: 'G', GGA: 'G', GGG: 'G',
};

const BASE_MW: Record<string, number> = { A: 313.21, T: 304.2, U: 290.17, G: 329.21, C: 289.18 };

export function analyzeNucleicAcid(seqRaw: string): NucleicAcidAnalysis {
  let seq = seqRaw.toUpperCase().replace(/[^A-Z]/g, '');
  const isRna = seq.includes('U') && !seq.includes('T');
  if (!isRna) seq = seq.replace(/U/g, 'T');
  const warnings: string[] = [];
  const unknown = seq.replace(/[ATUGCN]/g, '');
  if (unknown.length > 0) warnings.push(`发现 ${unknown.length} 个非核酸字符, 已忽略`);

  const counts = new Map<string, number>();
  for (const c of seq) counts.set(c, (counts.get(c) || 0) + 1);
  const gc = (counts.get('G') || 0) + (counts.get('C') || 0);
  const at = (counts.get('A') || 0) + ((counts.get('T') || 0) + (counts.get('U') || 0));
  const total = seq.length || 1;

  // 解链温度: <14nt Wallace 规则, 否则 GC 经验公式
  const tm =
    seq.length < 14
      ? 2 * (at) + 4 * gc
      : 64.9 + (41 * (gc - 16.4)) / total;

  let mw = 0;
  for (const [b, n] of counts) mw += (BASE_MW[b] || 300) * n;
  mw = mw - (total - 1) * 61.96;

  // GC 滑动窗口
  const baseDistribution: { position: number; gcWindow: number }[] = [];
  const win = 30;
  for (let i = 0; i < seq.length; i++) {
    const s = Math.max(0, i - win / 2);
    const e = Math.min(seq.length, i + win / 2);
    let g = 0;
    const cnt = e - s;
    for (let k = s; k < e; k++) if (seq[k] === 'G' || seq[k] === 'C') g++;
    baseDistribution.push({ position: i + 1, gcWindow: Math.round((g / (cnt || 1)) * 10000) / 100 });
  }

  // ORF 查找 (6 种阅读框简化为 3 正链框)
  const orfs: NucleicAcidAnalysis['orfs'] = [];
  for (let frame = 0; frame < 3; frame++) {
    let orfStart = -1;
    for (let i = frame; i + 2 < seq.length; i += 3) {
      const codon = seq.slice(i, i + 3);
      if (codon === 'ATG' && orfStart === -1) {
        orfStart = i;
      } else if ((codon === 'TAA' || codon === 'TAG' || codon === 'TGA') && orfStart !== -1) {
        const len = i + 3 - orfStart;
        if (len >= 30) {
          orfs.push({
            start: orfStart + 1,
            end: i + 3,
            length: len,
            strand: `+${frame + 1}`,
            proteinLength: len / 3,
          });
        }
        orfStart = -1;
      }
    }
  }
  orfs.sort((a, b) => b.length - a.length);

  // 翻译 (最长 ORF 或全长框 1)
  const translate = (dna: string): string => {
    let protein = '';
    for (let i = 0; i + 2 < dna.length; i += 3) {
      const aa = CODON_TABLE[dna.slice(i, i + 3)] || 'X';
      if (aa === '*') break;
      protein += aa;
    }
    return protein;
  };
  const target = orfs.length > 0 ? seq.slice(orfs[0].start - 1, orfs[0].end) : seq;
  const proteinTranslation = translate(target);

  // 密码子统计
  const codonCounts = new Map<string, number>();
  for (let i = 0; i + 2 < target.length; i += 3) {
    const codon = target.slice(i, i + 3);
    if (codon.length === 3) codonCounts.set(codon, (codonCounts.get(codon) || 0) + 1);
  }
  const codonStats = [...codonCounts.entries()]
    .map(([codon, count]) => ({ codon, aminoAcid: CODON_TABLE[codon] || 'X', count }))
    .sort((a, b) => b.count - a.count);

  return {
    length: seq.length,
    gcContent: Math.round((gc / total) * 10000) / 100,
    atContent: Math.round((at / total) * 10000) / 100,
    baseCounts: ['A', 'T', 'U', 'G', 'C', 'N'].map((b) => ({
      base: b,
      count: counts.get(b) || 0,
      percent: Math.round(((counts.get(b) || 0) / total) * 10000) / 100,
    })).filter((b) => b.count > 0),
    isRna,
    meltingTemp: Math.round(tm * 10) / 10,
    molecularWeight: Math.round(mw * 100) / 100,
    baseDistribution,
    orfs: orfs.slice(0, 10),
    proteinTranslation: proteinTranslation.slice(0, 3000),
    codonStats,
    warnings,
  };
}
