# alignment_engine.py
import json
import tempfile
import subprocess
import os
from typing import Dict, Tuple, Optional, List, Union
from Bio import Align
from Bio.Align import substitution_matrices
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.Align import MultipleSeqAlignment
import numpy as np

class ProfessionalAlignmentEngine:
    """专业序列比对引擎"""
    
    def __init__(self):
        self.available_tools = self._detect_available_tools()
    
    def _detect_available_tools(self) -> Dict[str, bool]:
        """检测可用的比对工具"""
        tools = {
            "biopython": True,  # 总是可用
            "clustalo": False,
            "mafft": False
        }
        
        # 检测 Clustal Omega
        try:
            subprocess.run(["clustalo", "--version"], 
                          capture_output=True, timeout=2)
            tools["clustalo"] = True
        except:
            pass
        
        # 检测 MAFFT
        try:
            subprocess.run(["mafft", "--version"], 
                          capture_output=True, timeout=2)
            tools["mafft"] = True
        except:
            pass
        
        return tools
    
    def parse_uniprot_ranges(self, uniprot_ranges) -> List[Dict]:
        """解析 uniprot_ranges 字段（处理字符串或列表）"""
        if isinstance(uniprot_ranges, str):
            try:
                return json.loads(uniprot_ranges)
            except:
                return []
        elif isinstance(uniprot_ranges, list):
            return uniprot_ranges
        return []
    
    def align_with_biopython(self, seq1: str, seq2: str, 
                           algorithm: str = "global",
                           matrix: str = "BLOSUM62") -> Dict:
        """使用 BioPython 进行序列比对"""
        
        # 选择算法和参数
        aligner = Align.PairwiseAligner()
        
        # 设置替换矩阵
        try:
            aligner.substitution_matrix = substitution_matrices.load(matrix)
        except:
            aligner.substitution_matrix = substitution_matrices.load("BLOSUM62")
        
        # 设置算法参数
        if algorithm == "global":
            aligner.mode = "global"
            aligner.open_gap_score = -10.0
            aligner.extend_gap_score = -0.5
        elif algorithm == "local":
            aligner.mode = "local"
            aligner.open_gap_score = -10.0
            aligner.extend_gap_score = -0.5
        elif algorithm == "semiglobal":
            aligner.mode = "global"
            aligner.query_end_gap_score = 0.0
            aligner.target_end_gap_score = 0.0
        
        # 执行比对
        alignments = aligner.align(seq1, seq2)
        
        # 获取最佳比对
        alignment = alignments[0]
        
        # 解析比对结果
        aligned_seq1 = alignment[0]
        aligned_seq2 = alignment[1]
        
        # 计算统计信息
        matches = sum(1 for a, b in zip(aligned_seq1, aligned_seq2) if a == b and a != "-")
        gaps1 = aligned_seq1.count("-")
        gaps2 = aligned_seq2.count("-")
        total_length = len(aligned_seq1)
        
        identity = (matches / (total_length - min(gaps1, gaps2))) * 100 if total_length > 0 else 0
        
        return {
            "algorithm": f"BioPython {algorithm}",
            "matrix": matrix,
            "score": alignment.score,
            "alignment": alignment,
            "aligned_seq1": aligned_seq1,
            "aligned_seq2": aligned_seq2,
            "identity": identity,
            "matches": matches,
            "gaps1": gaps1,
            "gaps2": gaps2,
            "total_length": total_length
        }
    
    def align_entity_with_all_ranges(self, entity: Dict, algorithm: str = "global", matrix: str = "BLOSUM62") -> List[Dict]:
        """
        对实体的 PDB 序列与所有 UniProt 范围进行比对。
        严格根据 uniprot_ranges 中的数据进行切片，不再依赖顶层 uniprot_sequence 字段。
        """
        pdb_seq = entity.get("sequence", "")
        if not pdb_seq:
            return [{"error": "缺少 PDB 序列"}]

        ranges = self.parse_uniprot_ranges(entity.get("uniprot_ranges", []))
        if not ranges:
            return [{"error": "无 UniProt 映射范围信息"}]

        alignment_results = []

        for mapping in ranges:
            # 1. 获取 ID
            uniprot_id = mapping.get("uniprot_id", "Unknown")
            
            # 2. 【关键修改】严格从 Range 内部获取序列，不再查找顶层字段
            full_uniprot_seq = mapping.get("uniprot_sequence", "")
            if not full_uniprot_seq:
                # 如果这个 range 对象里没有序列字段，说明数据缺失，跳过这个 range
                print(f"⚠️ Range (ID: {uniprot_id}) 缺少 'uniprot_sequence' 字段，跳过。")
                continue
            
            # 3. 解析索引
            try:
                unp_start = int(mapping.get("unp_start", 1))
                unp_end = int(mapping.get("unp_end", 1))
                pdb_start = int(mapping.get("pdb_start", 1))
                pdb_end = int(mapping.get("pdb_end", 1))
            except ValueError:
                print(f"⚠️ Range (ID: {uniprot_id}) 索引格式错误，跳过。")
                continue
            
            # 4. 切片 PDB 序列 (Python 0-based)
            try:
                p_start_idx = max(0, pdb_start - 1)
                p_end_idx = min(len(pdb_seq), pdb_end)
                pdb_segment = pdb_seq[p_start_idx:p_end_idx]
            except IndexError:
                print(f"⚠️ Range (ID: {uniprot_id}) PDB 索引超出范围，跳过。")
                continue

            # 5. 切片 UniProt 序列 (Python 0-based)
            try:
                u_start_idx = max(0, unp_start - 1)
                u_end_idx = min(len(full_uniprot_seq), unp_end)
                uniprot_segment = full_uniprot_seq[u_start_idx:u_end_idx]
            except IndexError:
                print(f"⚠️ Range (ID: {uniprot_id}) UniProt 索引超出范围，跳过。")
                continue

            # 如果切片后为空，跳过
            if not pdb_segment or not uniprot_segment:
                print(f"⚠️ Range (ID: {uniprot_id}) 切片结果为空，跳过。")
                continue

            # 6. 执行比对
            try:
                result = self.align_with_biopython(
                    pdb_segment, 
                    uniprot_segment, 
                    algorithm=algorithm,
                    matrix=matrix
                )
            except Exception as e:
                print(f"❌ Range (ID: {uniprot_id}) 比对出错: {e}")
                continue
            
            # 7. 附加元数据
            result['uniprot_id'] = uniprot_id
            result['chain_id'] = mapping.get("chain_id", "?")
            result['mapping'] = mapping
            result['pdb_segment'] = pdb_segment
            result['uniprot_segment'] = uniprot_segment
            
            alignment_results.append(result)
            
        if not alignment_results:
            return [{"error": "无法生成比对结果：所有 UniProt 范围均无效或缺少序列数据"}]
            
        return alignment_results
    
    def align_pdb_to_multiple_uniprot_merged(self, entity: Dict, algorithm: str = "global", matrix: str = "BLOSUM62") -> Dict:
        """
        将 PDB 序列与多个 UniProt 序列比对，并合并结果。
        修复：确保不同 UniProt 序列在 PDB 间隙处的长度严格对齐。
        关键修复：修复新序列初始化时机，防止错位。
        """
        pdb_seq = entity.get("sequence", "")
        if not pdb_seq:
            return {"error": "缺少 PDB 序列"}

        ranges = self.parse_uniprot_ranges(entity.get("uniprot_ranges", []))
        if not ranges:
            return {"error": "无 UniProt 映射范围信息"}

        # 1. 按物理 PDB 坐标排序
        try:
            ranges.sort(key=lambda x: int(x.get('pdb_start', 0)))
        except ValueError:
            return {"error": "Range 坐标格式错误"}

        aligned_pdb_full = []
        aligned_uniprot_map = {} 
        segment_stats = []
        last_physical_end = 0

        for mapping in ranges:
            uniprot_id = mapping.get("uniprot_id", "Unknown")
            full_uniprot_seq = mapping.get("uniprot_sequence", "")
            
            if not full_uniprot_seq:
                continue

            try:
                unp_start = int(mapping.get("unp_start", 1))
                unp_end = int(mapping.get("unp_end", 1))
                pdb_start = int(mapping.get("pdb_start", 1))
                pdb_end = int(mapping.get("pdb_end", 1))
            except ValueError:
                continue

            # --- A. 处理 PDB 物理间隙 ---
            if pdb_start > last_physical_end + 1:
                # 物理间隙的长度
                gap_physical_len = (pdb_start - 1) - last_physical_end
                gap_pdb_seq = pdb_seq[last_physical_end : pdb_start-1]
                
                aligned_pdb_full.append(gap_pdb_seq)
                
                # 【关键修复】确保所有已有的 UniProt ID 都补上相同长度的 Gap
                gap_str = "-" * len(gap_pdb_seq)
                for uid in aligned_uniprot_map:
                    aligned_uniprot_map[uid].append(gap_str)
                
                # 【BUG 修复点】删除了这里的初始化逻辑
                # 旧代码在这里初始化新 ID，导致新 ID 只有间隙长度，缺少了之前完整片段的长度
                # 正确的做法是：新 ID 留空，直到下面“追加结果”部分再一次性补齐所有之前的长度
            
            # --- B. 提取并比对 ---
            p_start_idx = max(0, pdb_start - 1)
            p_end_idx = min(len(pdb_seq), pdb_end)
            pdb_segment = pdb_seq[p_start_idx:p_end_idx]

            u_start_idx = max(0, unp_start - 1)
            u_end_idx = min(len(full_uniprot_seq), unp_end)
            uniprot_segment = full_uniprot_seq[u_start_idx:u_end_idx]

            if not pdb_segment or not uniprot_segment:
                last_physical_end = pdb_end
                continue

            result = self.align_with_biopython(pdb_segment, uniprot_segment, algorithm=algorithm, matrix=matrix)
            
            aligned_pdb_frag = result['aligned_seq1']
            aligned_uni_frag = result['aligned_seq2']
            
            if len(aligned_pdb_frag) != len(aligned_uni_frag):
                 print(f"Warning: Alignment length mismatch for {uniprot_id}, skipping.")
                 continue

            segment_stats.append({
                "uniprot_id": uniprot_id,
                "pdb_range": f"{pdb_start}-{pdb_end}",
                "identity": result['identity'],
                "matches": result['matches']
            })

            # --- C. 追加结果 ---
            # 1. 追加 PDB (比对后版本，包含 Gap)
            aligned_pdb_full.append(aligned_pdb_frag)
            
            # 2. 初始化新 ID (如果第一次出现)
            # 【关键逻辑】此时 aligned_pdb_full 已经包含了当前片段，
            # 所以 total_len - frag_len = 之前的总长度（包含之前的片段+间隙）
            if uniprot_id not in aligned_uniprot_map:
                current_pdb_len = sum(len(s) for s in aligned_pdb_full)
                # 计算之前所有内容的长度
                prev_len = current_pdb_len - len(aligned_pdb_frag)
                # 新序列初始化为之前长度的 Gap
                aligned_uniprot_map[uniprot_id] = ["-" * prev_len]

            # 3. 追加当前 UniProt 片段
            aligned_uniprot_map[uniprot_id].append(aligned_uni_frag)

            # 4. 给其他 ID 补 Gap
            frag_len = len(aligned_pdb_frag)
            for uid in list(aligned_uniprot_map.keys()):
                if uid != uniprot_id:
                    aligned_uniprot_map[uid].append("-" * frag_len)

            last_physical_end = pdb_end

        # --- D. 处理尾部物理 Gap ---
        if last_physical_end < len(pdb_seq):
            tail_pdb_seq = pdb_seq[last_physical_end:]
            tail_len = len(tail_pdb_seq)
            aligned_pdb_full.append(tail_pdb_seq)
            for uid in aligned_uniprot_map:
                aligned_uniprot_map[uid].append("-" * tail_len)

        # 拼接
        final_pdb = "".join(aligned_pdb_full)
        final_uniprot_map = {k: "".join(v) for k, v in aligned_uniprot_map.items()}

        return {
            "aligned_pdb": final_pdb,
            "aligned_sequences": final_uniprot_map,
            "stats": segment_stats
        }
    
    def format_alignment_display(self, alignment_result: Union[Dict, List[Dict]], 
                               mapping_info: Dict = None) -> str:
        """格式化比对结果显示 (支持单次比对或多次比对列表)"""
        
        is_multiple = isinstance(alignment_result, list)
        results_list = alignment_result if is_multiple else [alignment_result]
        
        output = []
        
        if is_multiple:
            output.append("=" * 80 + "\n")
            output.append(f"多范围序列比对结果 (共 {len(results_list)} 个映射)\n")
            output.append("=" * 80 + "\n\n")
        
        for idx, result in enumerate(results_list):
            if is_multiple:
                title = result.get('range_info', f"范围 {idx+1}: {result.get('uniprot_id', 'Unknown')}")
                output.append(f">>> {title} <<<\n")
                output.append("-" * 80 + "\n")
            
            output.append(f"比对算法: {result.get('algorithm', '未知')}\n")
            if 'score' in result:
                output.append(f"比对得分: {result['score']:.2f}\n")
            
            output.append("\n" + "-" * 40 + "\n")
            
            # 映射信息
            if not is_multiple and mapping_info:
                info = mapping_info
                output.append(f"  UniProt ID: {info.get('uniprot_id', 'N/A')}\n")
                output.append(f"  UniProt范围: {info.get('unp_start', '?')}-{info.get('unp_end', '?')}\n")
            elif is_multiple and 'mapping' in result:
                info = result['mapping']
                output.append(f"  UniProt ID: {info.get('uniprot_id', 'N/A')}\n")
                output.append(f"  UniProt范围: {info.get('unp_start', '?')}-{info.get('unp_end', '?')}\n")
                output.append(f"  PDB范围: {info.get('pdb_start', '?')}-{info.get('pdb_end', '?')}\n")
            
            output.append("\n")
            
            # 比对序列
            aligned_seq1 = result.get('aligned_seq1', '')
            aligned_seq2 = result.get('aligned_seq2', '')
            
            if aligned_seq1 and aligned_seq2:
                chunk_size = 60
                for i in range(0, len(aligned_seq1), chunk_size):
                    chunk_end = min(i + chunk_size, len(aligned_seq1))
                    
                    non_gap_count1 = sum(1 for c in aligned_seq1[:i] if c != '-')
                    non_gap_count2 = sum(1 for c in aligned_seq2[:i] if c != '-')
                    
                    chunk1 = aligned_seq1[i:chunk_end]
                    prefix = "PDB " if not is_multiple else "PDB_seg"
                    output.append(f"{prefix} {non_gap_count1+1:4d}: {chunk1}\n")
                    
                    chunk2 = aligned_seq2[i:chunk_end]
                    prefix = "UniP" if not is_multiple else "UniP_seg"
                    output.append(f"{prefix} {non_gap_count2+1:4d}: {chunk2}\n")
                    
                    consensus = ""
                    for a, b in zip(chunk1, chunk2):
                        if a == b and a != '-':
                            consensus += "|"
                        elif a != '-' and b != '-':
                            consensus += ":"
                        else:
                            consensus += " "
                    output.append(f"        {consensus}\n\n")
            
            output.append("-" * 40 + "\n")
            output.append(f"  序列一致性: {result.get('identity', 0):.2f}%\n")
            output.append(f"  匹配残基数: {result.get('matches', 0)}\n\n")
        
        return "".join(output)

    # --- 保留原有的其他方法 ---
    def align_with_clustalo(self, seq1: str, seq2: str, 
                          seq1_name: str = "PDB", 
                          seq2_name: str = "UniProt") -> Dict:
        """使用 Clustal Omega 进行比对"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.fasta', delete=False) as infile:
            infile.write(f">{seq1_name}\n{seq1}\n")
            infile.write(f">{seq2_name}\n{seq2}\n")
            input_path = infile.name
        
        output_path = input_path + ".aln"
        clustal_path = input_path + ".clustal"
        
        try:
            cmd = ["clustalo", "-i", input_path, "-o", clustal_path, "--outfmt=clustal", "--force", "--verbose"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                raise Exception(f"Clustal失败: {result.stderr}")
            
            with open(clustal_path, 'r') as f:
                clustal_output = f.read()
            
            lines = clustal_output.strip().split('\n')
            aligned_seq1, aligned_seq2 = "", ""
            
            for line in lines:
                if line.startswith(seq1_name):
                    parts = line.split()
                    if len(parts) >= 2: aligned_seq1 += parts[1]
                elif line.startswith(seq2_name):
                    parts = line.split()
                    if len(parts) >= 2: aligned_seq2 += parts[1]
            
            os.unlink(input_path); os.unlink(clustal_path)
            
            matches = sum(1 for a, b in zip(aligned_seq1, aligned_seq2) if a == b and a != "-")
            total = len([c for c in aligned_seq1 if c != "-" and c in "ACDEFGHIKLMNPQRSTVWY"])
            identity = (matches / total * 100) if total > 0 else 0
            
            return {"algorithm": "Clustal Omega", "aligned_seq1": aligned_seq1, "aligned_seq2": aligned_seq2, "identity": identity, "matches": matches}
        except Exception as e:
            for path in [input_path, output_path, clustal_path]:
                if os.path.exists(path): os.unlink(path)
            raise e
    
    def align_with_mafft(self, seq1: str, seq2: str) -> Dict:
        """使用 MAFFT 进行比对"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.fasta', delete=False) as infile:
            infile.write(f">PDB\n{seq1}\n>UniProt\n{seq2}\n")
            input_path = infile.name
        output_path = input_path + ".aln"
        
        try:
            cmd = ["mafft", "--auto", "--clustalout", input_path]
            with open(output_path, 'w') as outfile:
                result = subprocess.run(cmd, stdout=outfile, stderr=subprocess.PIPE, text=True, timeout=30)
            
            if result.returncode != 0: raise Exception(f"MAFFT失败: {result.stderr}")
            
            with open(output_path, 'r') as f: mafft_output = f.read()
            lines = mafft_output.strip().split('\n')
            aligned_seq1, aligned_seq2 = "", ""
            
            for line in lines:
                if line.startswith("PDB"):
                    parts = line.split()
                    if len(parts) >= 2: aligned_seq1 += parts[1]
                elif line.startswith("UniProt"):
                    parts = line.split()
                    if len(parts) >= 2: aligned_seq2 += parts[1]
            
            os.unlink(input_path); os.unlink(output_path)
            matches = sum(1 for a, b in zip(aligned_seq1, aligned_seq2) if a == b and a != "-")
            identity = (matches / len([c for c in aligned_seq1 if c != "-"]) * 100) if aligned_seq1 else 0
            return {"algorithm": "MAFFT", "aligned_seq1": aligned_seq1, "aligned_seq2": aligned_seq2, "identity": identity, "matches": matches}
        except Exception as e:
            for path in [input_path, output_path]:
                if os.path.exists(path): os.unlink(path)
            raise e

        """生成可视化的比对表示（HTML格式）"""
        aligned_seq1 = alignment_result.get('aligned_seq1', '')
        aligned_seq2 = alignment_result.get('aligned_seq2', '')
        
        if not aligned_seq1 or not aligned_seq2:
            return ""
        
        html = """
        <style>
        .alignment-container {
            font-family: 'Courier New', monospace;
            font-size: 12px;
            line-height: 1.2;
            background: #f8f9fa;
            padding: 10px;
            border-radius: 5px;
            border: 1px solid #dee2e6;
        }
        .seq-line {
            margin: 2px 0;
            white-space: nowrap;
        }
        .residue {
            display: inline-block;
            width: 12px;
            text-align: center;
            margin: 0 1px;
        }
        .match { background-color: #c8e6c9; }
        .mismatch { background-color: #ffcdd2; }
        .gap { background-color: #e0e0e0; }
        .label {
            font-weight: bold;
            margin-right: 10px;
            display: inline-block;
            width: 60px;
        }
        </style>
        
        <div class="alignment-container">
        """
        
        # 生成前100个残基的可视化
        display_length = min(100, len(aligned_seq1))
        
        for i in range(0, display_length, 50):
            chunk_end = min(i + 50, display_length)
            
            # PDB序列
            html += '<div class="seq-line"><span class="label">PDB:</span>'
            for j in range(i, chunk_end):
                aa = aligned_seq1[j]
                css_class = "gap" if aa == "-" else ("match" if aa == aligned_seq2[j] else "mismatch")
                html += f'<span class="residue {css_class}">{aa if aa != "-" else "·"}</span>'
            html += '</div>'
            
            # UniProt序列
            html += '<div class="seq-line"><span class="label">UniProt:</span>'
            for j in range(i, chunk_end):
                aa = aligned_seq2[j]
                css_class = "gap" if aa == "-" else ("match" if aa == aligned_seq1[j] else "mismatch")
                html += f'<span class="residue {css_class}">{aa if aa != "-" else "·"}</span>'
            html += '</div>'
            
            # 一致性行
            html += '<div class="seq-line"><span class="label"></span>'
            for j in range(i, chunk_end):
                a = aligned_seq1[j]
                b = aligned_seq2[j]
                if a == b and a != "-":
                    html += '<span class="residue" style="color: #2e7d32;">|</span>'
                elif a != "-" and b != "-":
                    html += '<span class="residue" style="color: #f57c00;">:</span>'
                else:
                    html += '<span class="residue"> </span>'
            html += '</div><br>'
        
        html += f"<div style='font-size: 11px; color: #666;'>显示 {display_length}/{len(aligned_seq1)} 个残基</div>"
        html += "</div>"
        
        return html