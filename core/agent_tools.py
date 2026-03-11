"""
Agent Tools System - 智能问答Agent可用的工具定义
"""
import asyncio
import json
import logging
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    """工具参数定义"""
    name: str
    description: str
    type: str = "string"
    required: bool = True
    default: Any = None
    enum: List[Any] = None


@dataclass
class AgentTool:
    """Agent工具定义"""
    name: str
    description: str
    parameters: List[ToolParameter]
    execute: Callable = None
    category: str = "general"

    def to_dict(self) -> Dict:
        """转换为API响应格式"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": [
                {
                    "name": p.name,
                    "description": p.description,
                    "type": p.type,
                    "required": p.required,
                    "default": p.default,
                    "enum": p.enum
                }
                for p in self.parameters
            ],
            "category": self.category
        }


class ToolRegistry:
    """工具注册表 - 管理所有可用工具"""

    def __init__(self):
        self._tools: Dict[str, AgentTool] = {}
        self._executors: Dict[str, Callable] = {}

    def register(self, tool: AgentTool):
        """注册工具"""
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def register_executor(self, tool_name: str, executor: Callable):
        """注册工具执行器"""
        self._executors[tool_name] = executor
        logger.info(f"Registered executor for tool: {tool_name}")

    def get_tool(self, name: str) -> Optional[AgentTool]:
        """获取工具定义"""
        return self._tools.get(name)

    def get_all_tools(self) -> List[AgentTool]:
        """获取所有工具"""
        return list(self._tools.values())

    def list_tools(self) -> List[Dict]:
        """列出所有工具（用于API响应）"""
        return [tool.to_dict() for tool in self._tools.values()]

    async def execute_tool(self, tool_name: str, params: Dict) -> Dict:
        """执行工具"""
        if tool_name not in self._executors:
            return {"success": False, "error": f"Tool {tool_name} not found"}

        try:
            executor = self._executors[tool_name]
            # 支持异步和同步执行器
            if asyncio.iscoroutinefunction(executor):
                result = await executor(**params)
            else:
                result = executor(**params)
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return {"success": False, "error": str(e)}


# 全局工具注册表
_tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """获取全局工具注册表"""
    return _tool_registry


# ============================================
# 工具实现
# ============================================

def search_literature_executor(query: str, limit: int = 10, **kwargs) -> Dict:
    """执行文献搜索"""
    from flask import current_app
    try:
        with current_app.app_context():
            from core.literature_index import IntegratedLiteratureIndexer
            from core.literature_db import search_literature

            # 尝试使用向量搜索
            try:
                manager = IntegratedLiteratureIndexer()
                results = manager.search(query, top_k=limit)
                if results:
                    # 向量搜索结果已包含 title, authors, journal, year 等信息
                    # 直接使用这些结果，不需要再查询数据库
                    logger.info(f"Vector search found {len(results)} results")
                    return {
                        "query": query,
                        "count": len(results),
                        "total_results": len(results),
                        "results": results
                    }
            except Exception as e:
                logger.warning(f"Vector search failed, falling back to database: {e}")

            # 回退到数据库搜索
            entries = search_literature(query, limit=limit)
            # 将 LiteratureEntry 对象转换为字典列表
            literature_list = []
            for entry in entries:
                if hasattr(entry, '__dict__'):
                    literature_list.append({
                        'id': getattr(entry, 'id', None),
                        'title': getattr(entry, 'title', ''),
                        'authors': getattr(entry, 'authors', ''),
                        'journal': getattr(entry, 'journal', ''),
                        'year': getattr(entry, 'year', None),
                        'doi': getattr(entry, 'doi', ''),
                        'abstract': getattr(entry, 'abstract', ''),
                    })
                else:
                    literature_list.append(entry)
            return {
                "query": query,
                "count": len(literature_list),
                "total_results": len(literature_list),
                "results": literature_list
            }
    except Exception as e:
        logger.error(f"Error in search_literature: {e}")
        return {"query": query, "count": 0, "results": [], "error": str(e)}


def search_structures_executor(query: str, source: str = "pdb", limit: int = 10, **kwargs) -> Dict:
    """执行结构搜索"""
    try:
        from core.structure_database import get_enhanced_structure_manager

        manager = get_enhanced_structure_manager()
        db = manager.database  # 获取底层的 StructureOfflineDatabase

        # 获取 protein_info（如果 AI 已经提取了蛋白信息）
        protein_info = kwargs.get("protein_info", {})
        all_results = []
        searched_queries = set()

        # 构建搜索查询列表
        search_queries = [query]

        if protein_info:
            # 添加标准名称
            if protein_info.get("standard_name"):
                search_queries.append(protein_info["standard_name"])
            # 添加基因名称
            if protein_info.get("gene_name"):
                search_queries.append(protein_info["gene_name"])
            # 添加 UniProt ID
            if protein_info.get("uniprot_id"):
                search_queries.append(protein_info["uniprot_id"])
            # 添加变体
            if protein_info.get("variants"):
                search_queries.extend(protein_info["variants"])

        # 去重并搜索
        for q in search_queries:
            q = q.strip()
            if not q or q in searched_queries:
                continue
            searched_queries.add(q)

            # 搜索结构数据库
            try:
                results = db.search_structures(query=q, limit=limit)
                if results:
                    all_results.extend(results)
            except Exception as e:
                logger.warning(f"Search failed for {q}: {e}")

            # 通过 protein_mapper 查找
            if not any(r.get("pdb_id") or r.get("id") for r in all_results if r):
                try:
                    if hasattr(manager, 'protein_mapper') and manager.protein_mapper:
                        structure_ids = manager.protein_mapper.find_structures_by_protein_name(q)
                        if structure_ids:
                            for sid in structure_ids[:limit]:
                                struct = db.get_structure(sid)
                                if struct and struct not in all_results:
                                    all_results.append(struct)
                except Exception as e:
                    logger.warning(f"protein_mapper search failed for {q}: {e}")

        results = all_results

        # 如果仍然没有结果，从 UniProt 获取序列作为回退
        if not results:
            # 尝试使用 UniProt ID 或基因名
            search_uniprot = protein_info.get("uniprot_id") or protein_info.get("gene_name") or query
            try:
                from core.uniprot_client import UniProtAPIClient
                client = UniProtAPIClient()
                uniprot_data = client.get_sequence(search_uniprot)
                if uniprot_data:
                    results = [{
                        "pdb_id": None,
                        "title": f"UniProt: {search_uniprot}",
                        "resolution": None,
                        "method": "UniProt",
                        "emdb_id": None,
                        "sequence": uniprot_data.get("sequence", ""),
                        "sequence_length": uniprot_data.get("length", 0),
                        "source": "uniprot"
                    }]
            except Exception as e:
                logger.warning(f"UniProt fallback search failed: {e}")

        # 去重并获取实体序列
        seen = set()
        unique_results = []
        for r in results:
            if r:
                pid = r.get("id") or r.get("pdb_id") or r.get("structure_id")
                if pid and pid not in seen:
                    seen.add(pid)

                    # 从 structure_entities 表获取序列
                    # 实际字段名：
                    # - sequence: 氨基酸序列
                    # - length: 序列长度
                    # - molecule_type: 分子类型 (polypeptide(L), protein, DNA, RNA)
                    # - molecule_name: 分子名称
                    # - gene_names: 基因名称
                    try:
                        import sqlite3
                        conn = sqlite3.connect(db.db_path)
                        conn.row_factory = sqlite3.Row
                        cursor = conn.cursor()
                        # 使用模糊匹配 molecule_type，因为可能是 'polypeptide(L)'
                        cursor.execute('''
                            SELECT entity_id, sequence, length, molecule_type, molecule_name, gene_names, chain_ids, in_chains
                            FROM structure_entities
                            WHERE structure_id = ? AND (molecule_type LIKE '%protein%' OR molecule_type LIKE '%polypeptide%')
                        ''', (pid,))
                        entities = cursor.fetchall()
                        conn.close()

                        logger.info(f"[search_structures] Found {len(entities)} entities for {pid}")

                        # 构建实体列表，每个实体单独保留（不合并序列）
                        if entities:
                            entity_list = []
                            all_sequences = []
                            total_length = 0
                            molecule_names = set()
                            gene_names_set = set()

                            for entity in entities:
                                entity_dict = dict(entity)
                                seq = entity_dict.get("sequence", "")
                                entity_id = entity_dict.get("entity_id", "")
                                chain_ids = entity_dict.get("chain_ids", "") or entity_dict.get("in_chains", "")
                                molecule_name = entity_dict.get("molecule_name", "")
                                gene_name = entity_dict.get("gene_names", "")

                                if seq:
                                    # 保存实体详情
                                    entity_list.append({
                                        "entity_id": entity_id,
                                        "chain_ids": chain_ids,
                                        "protein_name": molecule_name,
                                        "gene": gene_name,
                                        "sequence": seq,
                                        "length": len(seq)
                                    })
                                    all_sequences.append(seq)
                                    total_length += len(seq)

                                if molecule_name:
                                    molecule_names.add(molecule_name)
                                if gene_name:
                                    gene_names_set.add(gene_name)

                            # 保存实体列表（供 FASTA 格式输出）
                            r["entities"] = entity_list

                            # 兼容旧格式：合并序列
                            if all_sequences:
                                r["sequence"] = "\n".join(all_sequences)
                                r["sequence_length"] = total_length
                                logger.info(f"[search_structures] Got {len(entity_list)} entities, total sequence length: {total_length}")
                            if molecule_names:
                                r["protein_name"] = ", ".join(molecule_names)
                            if gene_names_set:
                                r["gene"] = ", ".join(gene_names_set)
                    except Exception as e:
                        logger.warning(f"Failed to get entity sequences for {pid}: {e}")

                    unique_results.append(r)
                elif not pid and r not in unique_results:
                    unique_results.append(r)

        return {
            "query": query,
            "source": source,
            "count": len(unique_results),
            "results": [
                {
                    "pdb_id": r.get("id") or r.get("pdb_id") or r.get("structure_id"),
                    "title": r.get("title", ""),
                    "resolution": r.get("resolution"),
                    "method": r.get("method", ""),
                    "emdb_id": r.get("emdb_id"),
                    "source": r.get("source", "structure_db"),
                    # 新增：实体列表（每个实体单独一条序列）
                    "entities": r.get("entities", []),
                    # 保留兼容性
                    "sequence": r.get("sequence", ""),
                    "sequence_length": r.get("sequence_length") or len(r.get("sequence", "")) if r.get("sequence") else None,
                    "gene": r.get("gene", ""),
                    "protein_name": r.get("protein_name", "")
                }
                for r in unique_results[:limit]
            ]
        }
    except Exception as e:
        logger.error(f"Error in search_structures: {e}")
        return {"query": query, "count": 0, "results": [], "error": str(e)}


def run_sequence_alignment_executor(sequence1: str, sequence2: str = None,
                                   uniprot1: str = None, uniprot2: str = None,
                                   algorithm: str = "global", **kwargs) -> Dict:
    """执行序列比对"""
    try:
        from core.alignment_engine import ProfessionalAlignmentEngine

        engine = ProfessionalAlignmentEngine()

        # 处理UniProt ID
        if uniprot1:
            from core.uniprot_client import UniProtAPIClient
            client = UniProtAPIClient()
            seq1_data = client.get_sequence(uniprot1)
            if not seq1_data:
                return {"success": False, "error": f"UniProt ID {uniprot1} not found"}
            sequence1 = seq1_data.get("sequence", "")

        if uniprot2:
            from core.uniprot_client import UniProtAPIClient
            client = UniProtAPIClient()
            seq2_data = client.get_sequence(uniprot2)
            if not seq2_data:
                return {"success": False, "error": f"UniProt ID {uniprot2} not found"}
            sequence2 = seq2_data.get("sequence", "")

        if not sequence1:
            return {"success": False, "error": "No sequence provided"}

        if not sequence2:
            return {"success": False, "error": "Second sequence required"}

        # 执行比对
        result = engine.align_with_biopython(sequence1, sequence2, algorithm=algorithm)

        return {
            "success": True,
            "sequence1": sequence1[:50] + "..." if len(sequence1) > 50 else sequence1,
            "sequence2": sequence2[:50] + "..." if len(sequence2) > 50 else sequence2,
            "algorithm": algorithm,
            "alignment": result
        }
    except Exception as e:
        logger.error(f"Error in sequence alignment: {e}")
        return {"success": False, "error": str(e)}


def get_structure_details_executor(structure_id: str, **kwargs) -> Dict:
    """获取结构详情"""
    try:
        from core.structure_database import get_enhanced_structure_manager
        from flask import current_app

        manager = get_enhanced_structure_manager()
        db = manager.database

        # 先在离线数据库中查找
        structure = db.get_structure(structure_id.upper())

        if not structure:
            # 尝试从RCSB API获取
            import requests
            rcsb_url = f"https://data.rcsb.org/rest/v1/core/entry/{structure_id.upper()}"
            resp = requests.get(rcsb_url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                structure = {
                    "pdb_id": structure_id.upper(),
                    "title": data.get("title", ""),
                    "experimental_method": data.get("exptl_method", ""),
                    "resolution": data.get("rcsb_entry_info", {}).get("resolution_combined", [None])[0] if data.get("rcsb_entry_info") else None,
                    "source": "rcsb"
                }
            else:
                return {"success": False, "error": f"Structure {structure_id} not found"}

        return {
            "success": True,
            "structure": structure
        }
    except Exception as e:
        logger.error(f"Error getting structure details: {e}")
        return {"success": False, "error": str(e)}


def get_kg_neighbors_executor(structure_id: str, depth: int = 1, **kwargs) -> Dict:
    """获取知识图谱邻居节点"""
    try:
        from core.structure_knowledge_graph import StructureKnowledgeGraph

        kg = StructureKnowledgeGraph()
        neighbors = kg.get_neighbors(structure_id.upper(), depth=depth)

        return {
            "success": True,
            "structure_id": structure_id,
            "depth": depth,
            "neighbors": neighbors
        }
    except Exception as e:
        logger.error(f"Error getting KG neighbors: {e}")
        return {"success": False, "error": str(e)}


def get_user_history_executor(user_id: str = None, session_id: str = None,
                               limit: int = 20, **kwargs) -> Dict:
    """获取用户问答历史"""
    try:
        from flask import current_app
        from flask_login import current_user

        # 确定用户ID
        if not user_id:
            if current_user.is_authenticated:
                user_id = current_user.id
            else:
                return {"success": False, "error": "User not authenticated"}

        # 从数据库获取历史
        with current_app.app_context():
            from core.literature_db import get_qa_history
            history = get_qa_history(user_id=user_id, session_id=session_id, limit=limit)

        return {
            "success": True,
            "user_id": user_id,
            "session_id": session_id,
            "count": len(history),
            "history": history
        }
    except Exception as e:
        logger.error(f"Error getting user history: {e}")
        return {"success": False, "error": str(e)}


def compare_structures_executor(structure_id1: str, structure_id2: str, **kwargs) -> Dict:
    """执行蛋白质结构比较"""
    try:
        from core.structure_database import get_enhanced_structure_manager

        manager = get_enhanced_structure_manager()
        db = manager.database

        # 获取两个结构的信息
        struct1 = db.get_structure(structure_id1.upper())
        struct2 = db.get_structure(structure_id2.upper())

        if not struct1:
            import requests
            rcsb_url = f"https://data.rcsb.org/rest/v1/core/entry/{structure_id1.upper()}"
            resp = requests.get(rcsb_url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                struct1 = {
                    "pdb_id": structure_id1.upper(),
                    "title": data.get("title", ""),
                    "experimental_method": data.get("exptl_method", ""),
                    "resolution": data.get("rcsb_entry_info", {}).get("resolution_combined", [None])[0],
                    "source": "rcsb"
                }

        if not struct2:
            import requests
            rcsb_url = f"https://data.rcsb.org/rest/v1/core/entry/{structure_id2.upper()}"
            resp = requests.get(rcsb_url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                struct2 = {
                    "pdb_id": structure_id2.upper(),
                    "title": data.get("title", ""),
                    "experimental_method": data.get("exptl_method", ""),
                    "resolution": data.get("rcsb_entry_info", {}).get("resolution_combined", [None])[0],
                    "source": "rcsb"
                }

        if not struct1 or not struct2:
            return {"success": False, "error": f"One or both structures not found"}

        # 简单的结构比较（基于元数据）
        comparison = {
            "structure1": struct1,
            "structure2": struct2,
            "comparison": {
                "same_method": struct1.get("experimental_method") == struct2.get("experimental_method"),
                "resolution_diff": abs(struct1.get("resolution", 0) - struct2.get("resolution", 0)) if struct1.get("resolution") and struct2.get("resolution") else None,
                "method1": struct1.get("experimental_method"),
                "method2": struct2.get("experimental_method")
            }
        }

        return {
            "success": True,
            "comparison": comparison
        }
    except Exception as e:
        logger.error(f"Error comparing structures: {e}")
        return {"success": False, "error": str(e)}


def analyze_resolution_executor(structure_id: str, threshold: float = 3.0, **kwargs) -> Dict:
    """执行分辨率分析"""
    try:
        from core.structure_database import get_enhanced_structure_manager

        manager = get_enhanced_structure_manager()
        db = manager.database
        structure = db.get_structure(structure_id.upper())

        if not structure:
            import requests
            rcsb_url = f"https://data.rcsb.org/rest/v1/core/entry/{structure_id.upper()}"
            resp = requests.get(rcsb_url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                structure = {
                    "pdb_id": structure_id.upper(),
                    "resolution": data.get("rcsb_entry_info", {}).get("resolution_combined", [None])[0],
                    "title": data.get("title", "")
                }

        if not structure:
            return {"success": False, "error": f"Structure {structure_id} not found"}

        resolution = structure.get("resolution")

        if resolution is None:
            return {
                "success": True,
                "structure_id": structure_id,
                "has_resolution": False,
                "message": "No resolution data available (likely EM structure)"
            }

        # 分析分辨率质量
        quality = "high" if resolution <= 2.0 else "medium" if resolution <= 3.0 else "low"

        analysis = {
            "structure_id": structure_id,
            "resolution": resolution,
            "quality": quality,
            "meets_threshold": resolution <= threshold,
            "threshold": threshold,
            "title": structure.get("title", "")
        }

        return {
            "success": True,
            "analysis": analysis
        }
    except Exception as e:
        logger.error(f"Error analyzing resolution: {e}")
        return {"success": False, "error": str(e)}


def find_similar_sequences_executor(sequence: str, database: str = "uniprot",
                                    limit: int = 10, **kwargs) -> Dict:
    """查找相似序列"""
    try:
        import requests

        # 使用 NCBI BLAST API 或 UniProt 的搜索功能
        if database.lower() == "uniprot":
            # 使用 UniProt API 进行序列搜索
            url = "https://rest.uniprot.org/idrun/ba"
            data = {
                "sequence": sequence,
                "alignments": limit
            }
            resp = requests.post(url, json=data, timeout=30)
            if resp.status_code == 200:
                results = resp.json()
                return {
                    "success": True,
                    "database": database,
                    "count": len(results.get("results", [])),
                    "results": results.get("results", [])
                }
            else:
                # 回退到简单的 FASTA 搜索
                return _fallback_uniprot_search(sequence, limit)

        return {"success": False, "error": f"Unsupported database: {database}"}
    except Exception as e:
        logger.error(f"Error finding similar sequences: {e}")
        return {"success": False, "error": str(e)}


def _fallback_uniprot_search(sequence: str, limit: int) -> Dict:
    """UniProt 搜索回退方案"""
    try:
        # 使用简单的 BLAST 搜索
        import requests

        url = "https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi"
        params = {
            "CMD": "Put",
            "QUERY": sequence,
            "DATABASE": "nr",
            "FORMAT_TYPE": "JSON"
        }
        resp = requests.get(url, params=params, timeout=30)

        return {
            "success": True,
            "message": "Sequence search initiated",
            "search_url": resp.url if hasattr(resp, 'url') else "",
            "note": "Please use NCBI BLAST directly for detailed results"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_publication_info_executor(pmid: str = None, doi: str = None, **kwargs) -> Dict:
    """获取出版物信息"""
    try:
        import requests

        if pmid:
            # 从 PubMed 获取信息
            url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
            params = {
                "db": "pubmed",
                "id": pmid,
                "retmode": "json"
            }
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                pub_data = data.get("result", {}).get(pmid, {})

                return {
                    "success": True,
                    "pmid": pmid,
                    "title": pub_data.get("title", ""),
                    "authors": pub_data.get("authors", []),
                    "journal": pub_data.get("fulljournalname", ""),
                    "pubdate": pub_data.get("pubdate", ""),
                    "source": "pubmed"
                }

        elif doi:
            # 从 CrossRef 获取信息
            url = f"https://api.crossref.org/works/{doi}"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                item = data.get("message", {})

                return {
                    "success": True,
                    "doi": doi,
                    "title": item.get("title", [""])[0] if item.get("title") else "",
                    "authors": [a.get("given", "") + " " + a.get("family", "") for a in item.get("author", [])],
                    "journal": item.get("container-title", [""])[0] if item.get("container-title") else "",
                    "pubdate": item.get("published-print", {}).get("date-parts", [[""]])[0][0] if item.get("published-print") else "",
                    "source": "crossref"
                }

        return {"success": False, "error": "Please provide PMID or DOI"}

    except Exception as e:
        logger.error(f"Error getting publication info: {e}")
        return {"success": False, "error": str(e)}


def run_blast_executor(sequence: str, database: str = "nr", **kwargs) -> Dict:
    """执行在线 BLAST 分析"""
    try:
        import requests

        # NCBI BLAST API
        url = "https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi"
        params = {
            "CMD": "Put",
            "QUERY": sequence,
            "DATABASE": database,
            "FORMAT_TYPE": "JSON",
            "ALIGNMENTS": 10,
            "ALIGNMENT_VIEW": "Pairwise"
        }

        resp = requests.get(url, params=params, timeout=30)

        return {
            "success": True,
            "message": "BLAST job submitted",
            "database": database,
            "query_length": len(sequence),
            "blast_url": resp.url if hasattr(resp, 'url') else "",
            "note": "访问上面的链接查看 BLAST 结果"
        }
    except Exception as e:
        logger.error(f"Error running BLAST: {e}")
        return {"success": False, "error": str(e)}


def fetch_uniprot_executor(uniprot_id: str, **kwargs) -> Dict:
    """获取 UniProt 数据"""
    try:
        from core.uniprot_client import UniProtClient

        client = UniProtClient()
        data = client.get_sequence(uniprot_id)

        if data:
            return {
                "success": True,
                "uniprot_id": uniprot_id,
                "sequence": data.get("sequence", ""),
                "length": data.get("length", 0),
                "mass": data.get("mass", 0),
                "protein_name": data.get("protein_name", ""),
                "organism": data.get("organism", "")
            }

        # 尝试直接从 UniProt API 获取
        import requests
        url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}.json"
        resp = requests.get(url, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            seq = data.get("sequence", {})

            return {
                "success": True,
                "uniprot_id": uniprot_id,
                "sequence": seq.get("value", ""),
                "length": seq.get("length", 0),
                "mass": seq.get("molWeight", 0),
                "protein_name": data.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value", ""),
                "organism": data.get("organism", {}).get("scientificName", "")
            }

        return {"success": False, "error": f"UniProt ID {uniprot_id} not found"}

    except Exception as e:
        logger.error(f"Error fetching UniProt: {e}")
        return {"success": False, "error": str(e)}


# ============================================
# 工具初始化函数
# ============================================

def initialize_tools():
    """初始化所有工具并注册到全局注册表"""
    registry = get_tool_registry()

    # 1. 文献搜索工具
    literature_tool = AgentTool(
        name="search_literature",
        description="""搜索科学文献数据库。根据关键词查找相关文献，返回文献标题、作者、期刊等信息。

适用场景：
- 问某蛋白/基因相关的文献
- 问某技术的文献
- 问某实验方法的文献

返回数据：
- title: 文献标题
- authors: 作者列表
- journal: 期刊名称
- year: 发表年份
- abstract: 摘要（如有）""",
        category="search",
        parameters=[
            ToolParameter(name="query", description="搜索关键词", type="string", required=True),
            ToolParameter(name="limit", description="返回结果数量限制", type="integer", required=False, default=10)
        ]
    )
    registry.register(literature_tool)
    registry.register_executor("search_literature", search_literature_executor)

    # 2. 结构搜索工具
    # 数据库索引：
    # - structures 表: id(PDB), title, resolution, method, gene, protein_name
    # - structure_entities 表: entity_poly_seq_one_letter_code(序列), entity_poly_seq_length, molecule_type
    # - uniprot_structure_mapping 表: uniprot_id, structure_id, gene_name
    structure_tool = AgentTool(
        name="search_structures",
        description="""搜索蛋白质结构数据库(PDB/EMDB)。根据ID或关键词查找相关结构信息。

适用场景：
- 问蛋白质的序列是什么
- 问结构的分辨率、实验方法
- 根据蛋白名称/基因名查找对应结构
- 查询某个PDB ID的详细信息

返回数据：
- pdb_id: PDB ID
- title: 结构标题
- resolution: 分辨率(Å)
- method: 实验方法(X-ray/Cryo-EM)
- sequence: 氨基酸序列
- sequence_length: 序列长度
- gene: 基因名称
- protein_name: 蛋白名称""",
        category="search",
        parameters=[
            ToolParameter(name="query", description="搜索关键词（蛋白名称/基因名/PDB ID）", type="string", required=True),
            ToolParameter(name="source", description="结构来源(pdb/emdb)", type="string", required=False, default="pdb"),
            ToolParameter(name="limit", description="返回结果数量限制", type="integer", required=False, default=10),
            ToolParameter(name="protein_info", description="AI提取的蛋白信息（可选，包含standard_name, gene_name, uniprot_id等）", type="object", required=False, default=None)
        ]
    )
    registry.register(structure_tool)
    registry.register_executor("search_structures", search_structures_executor)

    # 3. 序列比对工具
    alignment_tool = AgentTool(
        name="run_sequence_alignment",
        description="进行蛋白质序列比对。比对两条蛋白质序列的相似性，返回比对结果和相似度。",
        category="analysis",
        parameters=[
            ToolParameter(name="sequence1", description="第一条蛋白质序列", type="string", required=False),
            ToolParameter(name="sequence2", description="第二条蛋白质序列", type="string", required=False),
            ToolParameter(name="uniprot1", description="第一个UniProt ID", type="string", required=False),
            ToolParameter(name="uniprot2", description="第二个UniProt ID", type="string", required=False),
            ToolParameter(name="algorithm", description="比对算法(global/local/semiglobal)", type="string", required=False, default="global")
        ]
    )
    registry.register(alignment_tool)
    registry.register_executor("run_sequence_alignment", run_sequence_alignment_executor)

    # 4. 结构详情工具
    details_tool = AgentTool(
        name="get_structure_details",
        description="获取指定PDB/EMDB结构的详细信息，包括分辨率、实验方法、相关文献等。",
        category="lookup",
        parameters=[
            ToolParameter(name="structure_id", description="PDB或EMDB ID", type="string", required=True)
        ]
    )
    registry.register(details_tool)
    registry.register_executor("get_structure_details", get_structure_details_executor)

    # 5. 知识图谱工具
    kg_tool = AgentTool(
        name="get_kg_neighbors",
        description="获取结构在知识图谱中的关联节点，包括相似结构、相关文献等。",
        category="knowledge",
        parameters=[
            ToolParameter(name="structure_id", description="PDB或EMDB ID", type="string", required=True),
            ToolParameter(name="depth", description="查询深度", type="integer", required=False, default=1)
        ]
    )
    registry.register(kg_tool)
    registry.register_executor("get_kg_neighbors", get_kg_neighbors_executor)

    # 6. 历史记录工具
    history_tool = AgentTool(
        name="get_user_history",
        description="获取用户的问答历史记录。",
        category="utility",
        parameters=[
            ToolParameter(name="session_id", description="会话ID（可选）", type="string", required=False),
            ToolParameter(name="limit", description="返回记录数量", type="integer", required=False, default=20)
        ]
    )
    registry.register(history_tool)
    registry.register_executor("get_user_history", get_user_history_executor)

    # 7. 结构比较工具
    compare_tool = AgentTool(
        name="compare_structures",
        description="比较两个蛋白质结构的异同，包括分辨率、实验方法等。",
        category="analysis",
        parameters=[
            ToolParameter(name="structure_id1", description="第一个PDB ID", type="string", required=True),
            ToolParameter(name="structure_id2", description="第二个PDB ID", type="string", required=True)
        ]
    )
    registry.register(compare_tool)
    registry.register_executor("compare_structures", compare_structures_executor)

    # 8. 分辨率分析工具
    resolution_tool = AgentTool(
        name="analyze_resolution",
        description="分析蛋白质结构的分辨率质量，判断是否符合给定阈值。",
        category="analysis",
        parameters=[
            ToolParameter(name="structure_id", description="PDB ID", type="string", required=True),
            ToolParameter(name="threshold", description="分辨率阈值(Å)", type="float", required=False, default=3.0)
        ]
    )
    registry.register(resolution_tool)
    registry.register_executor("analyze_resolution", analyze_resolution_executor)

    # 9. 相似序列查找工具
    similar_seq_tool = AgentTool(
        name="find_similar_sequences",
        description="在数据库中查找与给定蛋白质序列相似的序列。",
        category="search",
        parameters=[
            ToolParameter(name="sequence", description="蛋白质序列", type="string", required=True),
            ToolParameter(name="database", description="搜索数据库", type="string", required=False, default="uniprot"),
            ToolParameter(name="limit", description="返回结果数量", type="integer", required=False, default=10)
        ]
    )
    registry.register(similar_seq_tool)
    registry.register_executor("find_similar_sequences", find_similar_sequences_executor)

    # 10. 出版物信息查询工具
    pubinfo_tool = AgentTool(
        name="get_publication_info",
        description="根据PMID或DOI获取科学出版物的详细信息。",
        category="lookup",
        parameters=[
            ToolParameter(name="pmid", description="PubMed ID", type="string", required=False),
            ToolParameter(name="doi", description="DOI", type="string", required=False)
        ]
    )
    registry.register(pubinfo_tool)
    registry.register_executor("get_publication_info", get_publication_info_executor)

    # 11. BLAST分析工具
    blast_tool = AgentTool(
        name="run_blast",
        description="在NCBI进行在线BLAST序列比对分析。",
        category="analysis",
        parameters=[
            ToolParameter(name="sequence", description="蛋白质序列", type="string", required=True),
            ToolParameter(name="database", description="BLAST数据库", type="string", required=False, default="nr")
        ]
    )
    registry.register(blast_tool)
    registry.register_executor("run_blast", run_blast_executor)

    # 12. UniProt数据获取工具
    uniprot_tool = AgentTool(
        name="fetch_uniprot",
        description="根据UniProt ID获取蛋白质序列和详细信息。",
        category="lookup",
        parameters=[
            ToolParameter(name="uniprot_id", description="UniProt ID (如 P0A8V2)", type="string", required=True)
        ]
    )
    registry.register(uniprot_tool)
    registry.register_executor("fetch_uniprot", fetch_uniprot_executor)

    # ============================================
    # PyMOL 工具 (蛋白质结构深度分析)
    # ============================================

    def pymol_analyze_executor(pdb_id: str, analysis_type: str = "info", **kwargs) -> Dict:
        """执行 PyMOL 结构分析"""
        try:
            from core.pymol_wrapper import get_pymol_wrapper

            wrapper = get_pymol_wrapper()
            if not wrapper.is_available():
                return {
                    "success": False,
                    "error": "PyMOL not available. Install with: pip install pymol-open-source"
                }

            result = wrapper.analyze_structure(pdb_id, analysis_type)
            return {
                "success": True,
                "pdb_id": pdb_id,
                "analysis_type": analysis_type,
                "result": result
            }
        except Exception as e:
            logger.error(f"Error in pymol_analyze: {e}")
            return {"success": False, "error": str(e)}

    def pymol_rmsd_executor(pdb_id1: str, pdb_id2: str, **kwargs) -> Dict:
        """计算 RMSD"""
        try:
            from core.pymol_wrapper import get_pymol_wrapper

            wrapper = get_pymol_wrapper()
            if not wrapper.is_available():
                return {
                    "success": False,
                    "error": "PyMOL not available. Install with: pip install pymol-open-source"
                }

            result = wrapper.calculate_rmsd(pdb_id1, pdb_id2)
            return {
                "success": True,
                "result": result
            }
        except Exception as e:
            logger.error(f"Error in pymol_rmsd: {e}")
            return {"success": False, "error": str(e)}

    def pymol_align_executor(pdb_id1: str, pdb_id2: str, **kwargs) -> Dict:
        """对齐结构"""
        try:
            from core.pymol_wrapper import get_pymol_wrapper

            wrapper = get_pymol_wrapper()
            if not wrapper.is_available():
                return {
                    "success": False,
                    "error": "PyMOL not available. Install with: pip install pymol-open-source"
                }

            result = wrapper.align_structures(pdb_id1, pdb_id2)
            return {
                "success": True,
                "result": result
            }
        except Exception as e:
            logger.error(f"Error in pymol_align: {e}")
            return {"success": False, "error": str(e)}

    def pymol_ss_executor(pdb_id: str, **kwargs) -> Dict:
        """分析二级结构"""
        try:
            from core.pymol_wrapper import get_pymol_wrapper

            wrapper = get_pymol_wrapper()
            if not wrapper.is_available():
                return {
                    "success": False,
                    "error": "PyMOL not available. Install with: pip install pymol-open-source"
                }

            result = wrapper.analyze_secondary_structure(pdb_id)
            return {
                "success": True,
                "result": result
            }
        except Exception as e:
            logger.error(f"Error in pymol_ss: {e}")
            return {"success": False, "error": str(e)}

    def pymol_image_executor(pdb_id: str, style: str = "cartoon",
                            color: str = "rainbow", **kwargs) -> Dict:
        """生成结构图像"""
        try:
            from core.pymol_wrapper import get_pymol_wrapper

            wrapper = get_pymol_wrapper()
            if not wrapper.is_available():
                return {
                    "success": False,
                    "error": "PyMOL not available. Install with: pip install pymol-open-source"
                }

            image_path = wrapper.generate_image(pdb_id, style, color)
            if image_path:
                return {
                    "success": True,
                    "result": {
                        "pdb_id": pdb_id,
                        "image_path": image_path,
                        "style": style
                    }
                }
            return {
                "success": False,
                "error": "Failed to generate image"
            }
        except Exception as e:
            logger.error(f"Error in pymol_image: {e}")
            return {"success": False, "error": str(e)}

    def pymol_session_executor(pdb_id: str, session_name: str = None, **kwargs) -> Dict:
        """生成 PyMOL session 文件"""
        try:
            from core.pymol_wrapper import get_pymol_wrapper

            wrapper = get_pymol_wrapper()
            if not wrapper.is_available():
                return {
                    "success": False,
                    "error": "PyMOL not available. Install with: pip install pymol-open-source"
                }

            session_path = wrapper.save_session(pdb_id, session_name)
            if session_path:
                return {
                    "success": True,
                    "pdb_id": pdb_id,
                    "session_path": session_path
                }
            return {
                "success": False,
                "error": "Failed to save session"
            }
        except Exception as e:
            logger.error(f"Error in pymol_session: {e}")
            return {"success": False, "error": str(e)}

    # 注册 PyMOL 工具
    # 13. PyMOL 结构分析工具
    pymol_analyze_tool = AgentTool(
        name="pymol_analyze",
        description="使用 PyMOL 进行蛋白质结构深度分析，包括结构信息、二级结构、表面分析等。",
        category="analysis",
        parameters=[
            ToolParameter(name="pdb_id", description="PDB ID (如 1ABC)", type="string", required=True),
            ToolParameter(name="analysis_type", description="分析类型: info/secondary_structure/surface/contacts",
                         type="string", required=False, default="info")
        ]
    )
    registry.register(pymol_analyze_tool)
    registry.register_executor("pymol_analyze", pymol_analyze_executor)

    # 14. PyMOL RMSD 计算
    pymol_rmsd_tool = AgentTool(
        name="pymol_rmsd",
        description="使用 PyMOL 计算两个蛋白质结构之间的 RMSD (Root Mean Square Deviation)。",
        category="analysis",
        parameters=[
            ToolParameter(name="pdb_id1", description="第一个 PDB ID", type="string", required=True),
            ToolParameter(name="pdb_id2", description="第二个 PDB ID", type="string", required=True)
        ]
    )
    registry.register(pymol_rmsd_tool)
    registry.register_executor("pymol_rmsd", pymol_rmsd_executor)

    # 15. PyMOL 结构对齐
    pymol_align_tool = AgentTool(
        name="pymol_align",
        description="使用 PyMOL 对齐两个蛋白质结构。",
        category="analysis",
        parameters=[
            ToolParameter(name="pdb_id1", description="第一个 PDB ID", type="string", required=True),
            ToolParameter(name="pdb_id2", description="第二个 PDB ID", type="string", required=True)
        ]
    )
    registry.register(pymol_align_tool)
    registry.register_executor("pymol_align", pymol_align_executor)

    # 16. PyMOL 二级结构分析
    pymol_ss_tool = AgentTool(
        name="pymol_ss",
        description="使用 PyMOL 分析蛋白质二级结构 (α螺旋、β折叠、环区)。",
        category="analysis",
        parameters=[
            ToolParameter(name="pdb_id", description="PDB ID", type="string", required=True)
        ]
    )
    registry.register(pymol_ss_tool)
    registry.register_executor("pymol_ss", pymol_ss_executor)

    # 17. PyMOL 图像生成
    pymol_image_tool = AgentTool(
        name="pymol_image",
        description="使用 PyMOL 生成蛋白质结构图像。",
        category="visualization",
        parameters=[
            ToolParameter(name="pdb_id", description="PDB ID", type="string", required=True),
            ToolParameter(name="style", description="可视化风格: cartoon/sticks/spheres/surface",
                         type="string", required=False, default="cartoon"),
            ToolParameter(name="color", description="颜色方案: rainbow/chain/structure/hydrophobicity",
                         type="string", required=False, default="rainbow")
        ]
    )
    registry.register(pymol_image_tool)
    registry.register_executor("pymol_image", pymol_image_executor)

    # 18. PyMOL Session 生成
    pymol_session_tool = AgentTool(
        name="pymol_session",
        description="保存 PyMOL session 文件 (.pse)，可后续在 PyMOL 中打开进行交互式分析。",
        category="utility",
        parameters=[
            ToolParameter(name="pdb_id", description="PDB ID", type="string", required=True),
            ToolParameter(name="session_name", description="Session 文件名(可选)", type="string", required=False)
        ]
    )
    registry.register(pymol_session_tool)
    registry.register_executor("pymol_session", pymol_session_executor)

    logger.info(f"Initialized {len(registry.get_all_tools())} agent tools")
    return registry
