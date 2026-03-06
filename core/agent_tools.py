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
            from core.literature_index import LiteratureIndexManager
            from core.literature_db import search_literature

            # 尝试使用向量搜索
            try:
                manager = LiteratureIndexManager()
                results = manager.search(query, top_k=limit)
                if results:
                    # 获取完整文献信息
                    lit_ids = [r.get('id') or r.get('literature_id') for r in results]
                    literature_list = []
                    for lit_id in lit_ids:
                        if lit_id:
                            entry = search_literature(lit_id)
                            if entry:
                                literature_list.append(entry)
                    return {
                        "query": query,
                        "count": len(literature_list),
                        "results": literature_list
                    }
            except Exception as e:
                logger.warning(f"Vector search failed, falling back to database: {e}")

            # 回退到数据库搜索
            entries = search_literature(query, limit=limit)
            return {
                "query": query,
                "count": len(entries),
                "results": entries
            }
    except Exception as e:
        logger.error(f"Error in search_literature: {e}")
        return {"query": query, "count": 0, "results": [], "error": str(e)}


def search_structures_executor(query: str, source: str = "pdb", limit: int = 10, **kwargs) -> Dict:
    """执行结构搜索"""
    try:
        from core.structure_manager import StructureManager
        from core.structure_database import StructureDatabase

        db = StructureDatabase()
        manager = StructureManager(db)

        # 根据来源搜索
        if source.lower() == "pdb":
            results = db.search_structures(pdb_id=query.upper(), limit=limit)
        elif source.lower() == "emdb":
            results = db.search_structures(emdb_id=query.upper(), limit=limit)
        else:
            # 通用搜索
            results = db.search_structures(query=query, limit=limit)

        return {
            "query": query,
            "source": source,
            "count": len(results),
            "results": [
                {
                    "pdb_id": r.get("pdb_id") or r.get("structure_id"),
                    "title": r.get("title", ""),
                    "resolution": r.get("resolution"),
                    "method": r.get("experimental_method", ""),
                    "emdb_id": r.get("emdb_id")
                }
                for r in results[:limit]
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
            from core.uniprot_client import UniProtClient
            client = UniProtClient()
            seq1_data = client.get_sequence(uniprot1)
            if not seq1_data:
                return {"success": False, "error": f"UniProt ID {uniprot1} not found"}
            sequence1 = seq1_data.get("sequence", "")

        if uniprot2:
            from core.uniprot_client import UniProtClient
            client = UniProtClient()
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
        from core.structure_database import StructureDatabase
        from flask import current_app

        db = StructureDatabase()

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


# ============================================
# 工具初始化函数
# ============================================

def initialize_tools():
    """初始化所有工具并注册到全局注册表"""
    registry = get_tool_registry()

    # 1. 文献搜索工具
    literature_tool = AgentTool(
        name="search_literature",
        description="搜索科学文献数据库。根据关键词查找相关文献，返回文献标题、作者、期刊等信息。",
        category="search",
        parameters=[
            ToolParameter(name="query", description="搜索关键词", type="string", required=True),
            ToolParameter(name="limit", description="返回结果数量限制", type="integer", required=False, default=10)
        ]
    )
    registry.register(literature_tool)
    registry.register_executor("search_literature", search_literature_executor)

    # 2. 结构搜索工具
    structure_tool = AgentTool(
        name="search_structures",
        description="搜索蛋白质结构数据库(PDB/EMDB)。根据ID或关键词查找相关结构信息。",
        category="search",
        parameters=[
            ToolParameter(name="query", description="搜索关键词或结构ID", type="string", required=True),
            ToolParameter(name="source", description="结构来源(pdb/emdb)", type="string", required=False, default="pdb"),
            ToolParameter(name="limit", description="返回结果数量限制", type="integer", required=False, default=10)
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

    logger.info(f"Initialized {len(registry.get_all_tools())} agent tools")
    return registry
