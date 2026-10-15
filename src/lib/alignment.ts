/**
 * CryoAgent Pro - 专业序列比对引擎
 * TypeScript 实现 Needleman-Wunsch (全局) / Smith-Waterman (局部) 比对
 * 支持 BLOSUM62 / BLOSUM45 / PAM250 替换矩阵, 仿射间隙罚分
 * 对应原 Flask 版 core/alignment_engine.py (BioPython pairwise2 等价实现)
 */

// ============ 替换矩阵 ============

export type MatrixName = 'BLOSUM62' | 'BLOSUM45' | 'PAM250' | 'IDENTITY';

const AA_ORDER = 'ARNDCQEGHILKMFPSTWYVBZX*'.split('');

const BLOSUM62_DATA =
  '4 -1 -2 -2 0 -1 -1 0 -2 -1 -1 -1 -1 -2 -1 1 0 -3 -2 0 -2 -1 0 -4 ' +
  '-1 5 0 -2 -3 1 0 -2 0 -3 -2 2 -1 -3 -2 -1 -1 -3 -2 -3 -1 0 -1 -4 ' +
  '-2 0 6 1 -3 0 0 0 1 -3 -3 0 -2 -3 -2 1 0 -4 -2 -3 3 0 -1 -4 ' +
  '-2 -2 1 6 -3 0 2 -1 -1 -3 -4 1 -3 -3 -1 0 -1 -4 -3 -3 4 1 -1 -4 ' +
  '0 -3 -3 -3 9 -3 -4 -3 -3 -1 -1 -3 -1 -2 -3 -1 -1 -2 -2 -1 -3 -2 -1 -4 ' +
  '-1 1 0 0 -3 5 2 -2 0 -3 -2 1 0 -3 -1 0 -1 -2 -1 -2 0 3 -1 -4 ' +
  '-1 0 0 2 -4 2 5 -2 0 -3 -3 1 -2 -3 -1 0 -1 -3 -2 -2 1 4 -1 -4 ' +
  '0 -2 0 -1 -3 -2 -2 6 -2 -4 -4 -2 -3 -3 -2 0 -2 -2 -3 -3 -1 -2 -1 -4 ' +
  '-2 0 1 -1 -3 0 0 -2 8 -3 -3 -1 -2 -1 -2 -1 -2 -2 2 -3 0 0 -1 -4 ' +
  '-1 -3 -3 -3 -1 -3 -3 -4 -3 4 2 -3 1 0 -3 -2 -1 -3 -1 3 -3 -3 -1 -4 ' +
  '-1 -2 -3 -4 -1 -2 -3 -4 -3 2 4 -2 2 0 -3 -2 -1 -2 -1 1 -4 -3 -1 -4 ' +
  '-1 2 0 1 -3 1 1 -2 -1 -3 -2 5 -1 -3 -1 0 -1 -3 -2 -2 0 1 -1 -4 ' +
  '-1 -1 -2 -3 -1 0 -2 -3 -2 1 2 -1 5 0 -2 -1 -1 -1 -1 1 -3 -1 -1 -4 ' +
  '-2 -3 -3 -3 -2 -3 -3 -3 -1 0 0 -3 0 6 -4 -2 -2 1 3 -1 -3 -3 -1 -4 ' +
  '-1 -2 -2 -1 -3 -1 -1 -2 -2 -3 -3 -1 -2 -4 7 -1 -1 -4 -3 -2 -2 -1 -2 -4 ' +
  '1 -1 1 0 -1 0 0 0 -1 -2 -2 0 -1 -2 -1 4 1 -3 -2 -2 0 0 0 -4 ' +
  '0 -1 0 -1 -1 -1 -1 -2 -2 -1 -1 -1 -1 -2 -1 1 5 -2 -2 0 -1 -1 0 -4 ' +
  '-3 -3 -4 -4 -2 -2 -3 -2 -2 -3 -2 -3 -1 1 -4 -3 -2 11 2 -3 -4 -3 -2 -4 ' +
  '-2 -2 -2 -3 -2 -1 -2 -3 2 -1 -1 -2 -1 3 -3 -2 -2 2 7 -1 -3 -2 -1 -4 ' +
  '0 -3 -3 -3 -1 -2 -2 -3 -3 3 1 -2 1 -1 -2 -2 0 -3 -1 4 -3 -2 -1 -4 ' +
  '-2 -1 3 4 -3 0 1 -1 0 -3 -4 0 -3 -3 -2 0 -1 -4 -3 -3 4 1 -1 -4 ' +
  '-1 0 0 1 -3 3 4 -2 0 -3 -3 1 -1 -3 -1 0 -1 -3 -2 -2 1 4 -1 -4 ' +
  '0 -1 -1 -1 -2 -1 -1 -1 -1 -1 -1 -1 -1 -1 -2 0 0 -2 -1 -1 -1 -1 -1 -4 ' +
  '-4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 1 ';

const BLOSUM45_DATA =
  '5 -2 -1 -2 -1 -1 -1 0 -2 -1 -2 -1 -1 -3 -1 1 0 -3 -2 0 -2 -1 0 -5 ' +
  '-2 6 -1 -3 1 -1 -3 0 -4 -3 1 -2 -3 -2 -3 0 -1 -4 -3 -3 3 1 -1 -5 ' +
  '-1 -1 7 1 -2 0 0 0 1 -4 -3 0 -2 -4 -1 0 -1 -5 -3 -4 2 0 -1 -5 ' +
  '-2 -3 1 7 -3 0 1 -1 -1 -4 -3 0 -4 -4 -1 0 -1 -5 -4 -3 3 1 -1 -5 ' +
  '-1 1 -2 -3 8 -2 -4 -2 -4 -2 -1 -3 -2 -2 -3 0 -1 -3 -1 -2 -2 -3 -2 -5 ' +
  '-1 -1 0 0 -2 6 2 -1 -1 -3 -2 0 -2 -3 0 0 -1 -4 -2 -3 0 2 -1 -5 ' +
  '-1 -3 0 1 -4 2 6 -2 -1 -4 -3 0 -3 -4 0 0 -1 -4 -3 -2 1 4 -1 -5 ' +
  '0 0 0 -1 -2 -1 -2 7 -2 -4 -3 -2 -2 -3 -2 0 -1 -3 -3 -2 -1 -2 -1 -5 ' +
  '-2 -4 1 -1 -4 -1 -1 -2 9 -3 -4 -1 -3 -2 -2 -1 -3 -2 2 -3 0 -1 -2 -5 ' +
  '-1 -3 -4 -4 -2 -3 -4 -4 -3 5 2 -3 2 0 -3 -3 -2 -2 -1 3 -4 -3 -1 -5 ' +
  '-2 1 -3 -3 -1 -2 -3 -3 -4 2 5 -3 3 0 -3 -3 -2 -2 -1 1 -3 -2 -1 -5 ' +
  '-1 -2 0 0 -3 0 0 -2 -1 -3 -3 5 -2 -3 0 0 -1 -4 -3 -2 0 1 -1 -5 ' +
  '-1 -3 -2 -4 -2 -2 -3 -2 -3 2 3 -2 6 0 -3 -2 -1 -1 -1 2 -3 -1 -1 -5 ' +
  '-3 -2 -4 -4 -2 -3 -4 -3 -2 0 0 -3 0 8 -4 -2 -2 1 4 -1 -4 -3 -1 -5 ' +
  '-1 -3 -1 -1 -3 0 0 -2 -2 -3 -3 0 -3 -4 8 -1 -1 -4 -3 -2 -2 -1 -2 -5 ' +
  '1 0 0 0 0 0 0 0 -1 -3 -3 0 -2 -2 -1 4 1 -3 -2 -1 0 0 0 -5 ' +
  '0 -1 -1 -1 -1 -1 -1 -1 -3 -2 -2 -1 -1 -2 -1 1 5 -3 -2 0 -1 -1 0 -5 ' +
  '-3 -4 -5 -5 -3 -4 -4 -3 -2 -2 -2 -4 -1 1 -4 -3 -3 11 2 -3 -4 -3 -2 -5 ' +
  '-2 -3 -3 -4 -1 -2 -3 -3 2 -1 -1 -3 -1 4 -3 -2 -2 2 7 -1 -3 -2 -1 -5 ' +
  '0 -3 -4 -3 -2 -3 -2 -2 -3 3 1 -2 2 -1 -2 -1 0 -3 -1 4 -3 -2 -1 -5 ' +
  '-2 3 2 3 -2 0 1 -1 0 -4 -3 0 -3 -4 -2 0 -1 -4 -3 -3 3 1 -1 -5 ' +
  '-1 1 0 1 -3 2 4 -2 -1 -3 -2 1 -1 -3 -1 0 -1 -4 -2 -2 1 4 -1 -5 ' +
  '0 -1 -1 -1 -2 -1 -1 -1 -2 -1 -1 -1 -1 -1 -2 0 0 -2 -1 -1 -1 -1 -1 -5 ' +
  '-5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 -5 1 ';

const PAM250_DATA =
  '2 -2 0 0 -2 0 0 1 -1 -1 -2 -1 -1 -3 1 1 1 -6 -4 0 0 0 -1 -8 ' +
  '-2 3 -4 -5 0 -1 -2 -4 -5 -3 -3 2 -4 -4 -3 0 -1 -7 -5 -3 -3 -1 -2 -8 ' +
  '0 -4 8 -1 -5 -3 1 -3 -2 -5 -4 0 -3 -6 0 0 -1 -8 -6 -4 2 -2 -2 -8 ' +
  '0 -5 -1 9 -7 -3 0 -5 -6 -6 -4 0 -5 -7 -2 0 -1 -9 -7 -4 1 -1 -3 -8 ' +
  '-2 0 -5 -7 15 -5 -6 -7 -7 -4 -4 -5 -4 -7 -6 -2 -3 -4 -5 -4 -4 -5 -3 -8 ' +
  '0 -1 -3 -3 -5 6 1 -3 -2 -3 -2 1 0 -5 0 0 -1 -7 -5 -1 0 3 -2 -8 ' +
  '0 -2 1 0 -6 1 7 -1 -1 -5 -2 0 -2 -5 0 0 -1 -6 -4 -2 1 4 -2 -8 ' +
  '1 -4 -3 -5 -7 -3 -1 10 -4 -7 -5 -2 -5 -6 -3 -1 -2 -5 -5 -4 -2 -3 -3 -8 ' +
  '-1 -5 -2 -6 -7 -2 -1 -4 9 -5 -2 0 -3 -4 -2 -2 -3 -3 -1 -4 0 -1 -2 -8 ' +
  '-1 -3 -5 -6 -4 -3 -5 -7 -5 7 1 -4 1 -2 -4 -3 -2 -5 -2 1 -4 -4 -2 -8 ' +
  '-2 -3 -4 -4 -4 -2 -2 -5 -2 1 6 -3 3 0 -3 -3 -2 -3 -2 0 -3 -2 -1 -8 ' +
  '-1 2 0 0 -5 1 0 -2 0 -4 -3 4 -3 -5 -2 0 -1 -6 -4 0 0 1 -2 -8 ' +
  '-1 -4 -3 -5 -4 0 -2 -5 -3 1 3 -3 8 0 -3 -1 -1 -2 -1 0 -3 -1 -1 -8 ' +
  '-3 -4 -6 -7 -7 -5 -5 -6 -4 -2 0 -5 0 9 -6 -3 -3 0 5 -4 -5 -4 -3 -8 ' +
  '1 -3 0 -2 -6 0 0 -3 -2 -4 -3 -2 -3 -6 9 0 -1 -8 -6 -4 -2 -1 -4 -8 ' +
  '1 0 0 0 -2 0 0 -1 -2 -3 -3 0 -1 -3 0 4 2 -5 -3 -1 0 0 -1 -8 ' +
  '1 -1 -1 -1 -3 -1 -1 -2 -3 -2 -2 -1 -1 -3 -1 2 4 -3 -2 0 0 0 -1 -8 ' +
  '-6 -7 -8 -9 -4 -7 -6 -5 -3 -5 -3 -6 -2 0 -8 -5 -3 4 0 -6 -5 -4 -6 -8 ' +
  '-4 -5 -6 -7 -5 -5 -4 -5 -1 -2 -2 -4 -1 5 -6 -3 -2 0 8 -5 -3 -3 -4 -8 ' +
  '0 -3 -4 -4 -4 -1 -2 -4 -4 1 0 0 0 -4 -4 -1 0 -6 -5 5 -2 -2 -3 -8 ' +
  '0 -3 2 1 -4 0 1 -2 0 -4 -3 0 -3 -5 -2 0 0 -5 -3 -2 3 2 -2 -8 ' +
  '0 -1 -2 -1 -5 3 4 -3 -1 -4 -2 1 -1 -4 -1 0 0 -4 -3 -2 2 5 -2 -8 ' +
  '-1 -2 -2 -3 -3 -2 -2 -3 -2 -2 -1 -2 -1 -3 -4 -1 -1 -6 -4 -3 -2 -2 -1 -8 ' +
  '-8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 1 ';

function parseMatrix(data: string): Map<string, number> {
  const values = data.trim().split(/\s+/).map(Number);
  const matrix = new Map<string, number>();
  let k = 0;
  for (const a of AA_ORDER) {
    for (const b of AA_ORDER) {
      matrix.set(`${a}${b}`, values[k++] ?? 0);
    }
  }
  return matrix;
}

export const SUBSTITUTION_MATRICES: Record<Exclude<MatrixName, 'IDENTITY'>, Map<string, number>> = {
  BLOSUM62: parseMatrix(BLOSUM62_DATA),
  BLOSUM45: parseMatrix(BLOSUM45_DATA),
  PAM250: parseMatrix(PAM250_DATA),
};

export function getScore(a: string, b: string, matrix: MatrixName): number {
  if (matrix === 'IDENTITY') return a === b ? 5 : -3;
  const m = SUBSTITUTION_MATRICES[matrix];
  if (!m) return a === b ? 5 : -3;
  const key = `${a.toUpperCase()}${b.toUpperCase()}`;
  return m.get(key) ?? -4;
}

// ============ 比对算法 ============

export interface AlignmentParams {
  algorithm: 'needleman-wunsch' | 'smith-waterman';
  matrix: MatrixName;
  gapOpen: number; // 负数
  gapExtend: number; // 负数
}

export interface AlignmentResult {
  algorithm: string;
  matrix: string;
  score: number;
  identity: number; // 0-100
  similarity: number; // 正相似度百分比
  gaps: number;
  gapRatio: number;
  alignedLength: number;
  seq1Aligned: string;
  seq2Aligned: string;
  matchLine: string; // | : . 格式
  blocks: AlignmentBlock[];
  seq1Range: [number, number];
  seq2Range: [number, number];
  consensus: string;
  transitions: number;
  transversions: number;
}

export interface AlignmentBlock {
  start1: number;
  end1: number;
  start2: number;
  end2: number;
  rows: { s1: string; match: string; s2: string }[];
}

const DIRECTION = { DIAG: 0, UP: 1, LEFT: 2 } as const;

/** 仿射间隙 Needleman-Wunsch / Smith-Waterman (Gotoh 算法) */
export function alignSequences(
  seq1Raw: string,
  seq2Raw: string,
  params: AlignmentParams = {
    algorithm: 'needleman-wunsch',
    matrix: 'BLOSUM62',
    gapOpen: -11,
    gapExtend: -1,
  }
): AlignmentResult {
  const seq1 = seq1Raw.toUpperCase().replace(/[^A-Z*]/g, '');
  const seq2 = seq2Raw.toUpperCase().replace(/[^A-Z*]/g, '');
  const n = seq1.length;
  const m = seq2.length;
  const { algorithm, matrix, gapOpen, gapExtend } = params;
  const isLocal = algorithm === 'smith-waterman';

  const NEG = -1e9;
  // DP 矩阵: M (match/mismatch), X (gap in seq2 / 来自 seq1), Y (gap in seq1)
  const M: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  const X: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  const Y: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  const traceM: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  const traceX: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  const traceY: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));

  M[0][0] = 0;
  if (!isLocal) {
    X[0][0] = gapOpen;
    Y[0][0] = gapOpen;
    for (let i = 1; i <= n; i++) {
      M[i][0] = NEG;
      X[i][0] = gapOpen + (i - 1) * gapExtend;
      Y[i][0] = NEG;
    }
    for (let j = 1; j <= m; j++) {
      M[0][j] = NEG;
      X[0][j] = NEG;
      Y[0][j] = gapOpen + (j - 1) * gapExtend;
    }
  }

  let bestScore = 0;
  let bestI = 0;
  let bestJ = 0;

  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      // X: seq1 残基对 gap (seq2 插入 gap)
      const xOpen = Math.max(M[i - 1][j], Y[i - 1][j]) + gapOpen;
      const xExt = X[i - 1][j] + gapExtend;
      X[i][j] = Math.max(xOpen, xExt);
      traceX[i][j] = xOpen >= xExt ? (M[i - 1][j] >= Y[i - 1][j] ? DIRECTION.DIAG : DIRECTION.LEFT) : DIRECTION.UP;

      // Y: seq2 残基对 gap (seq1 插入 gap)
      const yOpen = Math.max(M[i][j - 1], X[i][j - 1]) + gapOpen;
      const yExt = Y[i][j - 1] + gapExtend;
      Y[i][j] = Math.max(yOpen, yExt);
      traceY[i][j] = yOpen >= yExt ? (M[i][j - 1] >= X[i][j - 1] ? DIRECTION.DIAG : DIRECTION.UP) : DIRECTION.LEFT;

      // M: 对角
      const sub = getScore(seq1[i - 1], seq2[j - 1], matrix);
      const mDiag = Math.max(M[i - 1][j - 1], X[i - 1][j - 1], Y[i - 1][j - 1]) + sub;
      if (isLocal) {
        M[i][j] = Math.max(0, mDiag);
        traceM[i][j] = mDiag > 0 ? DIRECTION.DIAG : -1;
        if (M[i][j] > bestScore) {
          bestScore = M[i][j];
          bestI = i;
          bestJ = j;
        }
      } else {
        M[i][j] = mDiag;
        traceM[i][j] = DIRECTION.DIAG;
        if (M[i - 1][j - 1] >= X[i - 1][j - 1] && M[i - 1][j - 1] >= Y[i - 1][j - 1]) traceM[i][j] = DIRECTION.DIAG;
        else if (X[i - 1][j - 1] >= Y[i - 1][j - 1]) traceM[i][j] = DIRECTION.UP;
        else traceM[i][j] = DIRECTION.LEFT;
      }
    }
  }

  // 回溯起点
  let i: number, j: number;
  if (isLocal) {
    i = bestI;
    j = bestJ;
  } else {
    i = n;
    j = m;
  }
  const finalScore = isLocal ? bestScore : Math.max(M[n][m], X[n][m], Y[n][m]);

  // 回溯
  const out1: string[] = [];
  const out2: string[] = [];
  let cur = 'M' as 'M' | 'X' | 'Y';
  if (!isLocal) {
    if (X[n][m] >= M[n][m] && X[n][m] >= Y[n][m]) cur = 'X';
    else if (Y[n][m] >= M[n][m]) cur = 'Y';
  }

  while (i > 0 || j > 0) {
    if (isLocal && (i === 0 || j === 0)) break;
    if (i > 0 && j > 0 && cur === 'M') {
      out1.push(seq1[i - 1]);
      out2.push(seq2[j - 1]);
      const t = traceM[i][j];
      if (isLocal && t === -1) break;
      i--;
      j--;
      // 切换到来源矩阵
      if (!isLocal) {
        if (t === DIRECTION.UP) cur = 'X';
        else if (t === DIRECTION.LEFT) cur = 'Y';
      }
    } else if (i > 0 && (cur === 'X' || j === 0)) {
      out1.push(seq1[i - 1]);
      out2.push('-');
      const t = traceX[i][j];
      if (t === DIRECTION.UP) {
        // 延续 gap
      } else {
        // gap 开启, 来自 M 或 Y
        if (!isLocal) cur = t === DIRECTION.LEFT ? 'Y' : 'M';
        else cur = 'M';
      }
      i--;
    } else if (j > 0) {
      out1.push('-');
      out2.push(seq2[j - 1]);
      const t = traceY[i][j];
      if (t === DIRECTION.LEFT) {
        // 延续 gap
      } else {
        if (!isLocal) cur = t === DIRECTION.UP ? 'X' : 'M';
        else cur = 'M';
      }
      j--;
    } else {
      break;
    }
  }

  const a1 = out1.reverse().join('');
  const a2 = out2.reverse().join('');

  // 统计
  let matches = 0;
  let positives = 0;
  let gaps = 0;
  let transitions = 0;
  let transversions = 0;
  const matchChars: string[] = [];
  const consensusChars: string[] = [];
  const PURINES = new Set(['A', 'G']);
  const PYRIMIDINES = new Set(['C', 'T', 'U']);

  for (let k = 0; k < a1.length; k++) {
    const c1 = a1[k];
    const c2 = a2[k];
    if (c1 === '-' || c2 === '-') {
      gaps++;
      matchChars.push(' ');
      consensusChars.push(c1 === '-' ? c2 : c1);
    } else if (c1 === c2) {
      matches++;
      positives++;
      matchChars.push('|');
      consensusChars.push(c1);
      if (PURINES.has(c1) && PURINES.has(c2)) transitions++;
      else if (PYRIMIDINES.has(c1) && PYRIMIDINES.has(c2)) transitions++;
      else if (PURINES.has(c1) !== PURINES.has(c2)) transversions++;
    } else {
      const sc = getScore(c1, c2, matrix);
      if (sc > 0) {
        positives++;
        matchChars.push(':');
      } else if (sc === 0) {
        matchChars.push('.');
      } else {
        matchChars.push(' ');
      }
      consensusChars.push(sc >= 0 ? c1 : c2);
    }
  }

  const alignedLength = a1.length;
  const identity = alignedLength > 0 ? (matches / alignedLength) * 100 : 0;
  const similarity = alignedLength > 0 ? (positives / alignedLength) * 100 : 0;

  // 分块显示 (60 残基每块)
  const blockSize = 60;
  const blocks: AlignmentBlock[] = [];
  let pos1 = isLocal ? i + 1 : 1;
  let pos2 = isLocal ? j + 1 : 1;

  for (let start = 0; start < alignedLength; start += blockSize) {
    const end = Math.min(start + blockSize, alignedLength);
    const rows: { s1: string; match: string; s2: string }[] = [];
    let blockPos1 = pos1;
    let blockPos2 = pos2;
    for (let k = start; k < end; k += 10) {
      const ke = Math.min(k + 10, end);
      const s1seg = a1.slice(k, ke);
      const s2seg = a2.slice(k, ke);
      const mseg = matchChars.slice(k, ke).join('');
      rows.push({ s1: s1seg, match: mseg, s2: s2seg });
      blockPos1 += s1seg.replace(/-/g, '').length;
      blockPos2 += s2seg.replace(/-/g, '').length;
    }
    blocks.push({
      start1: pos1,
      end1: blockPos1 - 1,
      start2: pos2,
      end2: blockPos2 - 1,
      rows,
    });
    pos1 = blockPos1;
    pos2 = blockPos2;
  }

  return {
    algorithm,
    matrix,
    score: finalScore,
    identity: Math.round(identity * 100) / 100,
    similarity: Math.round(similarity * 100) / 100,
    gaps,
    gapRatio: alignedLength > 0 ? Math.round((gaps / alignedLength) * 10000) / 100 : 0,
    alignedLength,
    seq1Aligned: a1,
    seq2Aligned: a2,
    matchLine: matchChars.join(''),
    blocks,
    seq1Range: [isLocal ? i + 1 : 1, isLocal ? bestI : n],
    seq2Range: [isLocal ? j + 1 : 1, isLocal ? bestJ : m],
    consensus: consensusChars.join(''),
    transitions,
    transversions,
  };
}

/** 核酸/蛋白质快速相似性 (无 gap, 滑动窗口) */
export function quickSimilarity(s1: string, s2: string): number {
  const a = s1.toUpperCase();
  const b = s2.toUpperCase();
  if (a === b) return 100;
  const len = Math.min(a.length, b.length);
  if (len === 0) return 0;
  let same = 0;
  for (let i = 0; i < len; i++) if (a[i] === b[i]) same++;
  return Math.round((same / len) * 10000) / 100;
}

/** 生成一致序列 */
export function generateConsensus(sequences: string[]): string {
  if (sequences.length === 0) return '';
  const maxLen = Math.max(...sequences.map((s) => s.length));
  const consensus: string[] = [];
  const threshold = sequences.length / 2;
  for (let i = 0; i < maxLen; i++) {
    const counts = new Map<string, number>();
    for (const s of sequences) {
      const c = s.toUpperCase()[i];
      if (c && c !== '-') counts.set(c, (counts.get(c) || 0) + 1);
    }
    let best = '-';
    let bestCount = 0;
    for (const [c, n] of counts) {
      if (n > bestCount) {
        best = c;
        bestCount = n;
      }
    }
    consensus.push(bestCount >= threshold ? best : best.toLowerCase());
  }
  return consensus.join('');
}
