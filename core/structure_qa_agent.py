"""
Structure QA Agent - 结构问答智能体

提供基于结构数据的智能问答功能
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class QAContext:
    """问答上下文"""
    question: str
    protein_name: Optional[str] = None
    structure_ids: List[str] = None
    conversation_history: List[Dict] = None


class StructureQAAgent:
    """
    结构问答智能体

    专门处理与蛋白质结构相关的问题，结合结构数据库和文献进行回答
    """

    def __init__(self, literature_agent=None):
        """
        初始化结构QA智能体

        Args:
            literature_agent: 文献智能体实例，用于获取相关文献
        """
        self.literature_agent = literature_agent
        self.capabilities = {
            "protein_analysis": True,
            "structure_query": True,
            "method_extraction": True,
            "resolution_analysis": True,
            "ligand_identification": True
        }
        logger.info("StructureQAAgent 初始化完成")

    def answer(self, question: str, use_hybrid_search: bool = True,
               conversation_context: Dict = None) -> Dict[str, Any]:
        """
        回答结构相关问题

        Args:
            question: 用户问题
            use_hybrid_search: 是否使用混合搜索
            conversation_context: 对话上下文

        Returns:
            包含答案和元数据的字典
        """
        try:
            # 分析问题的意图
            intent = self._analyze_intent(question)

            # 根据意图选择处理策略
            if intent == "protein_info":
                return self._answer_protein_info(question)
            elif intent == "method_query":
                return self._answer_method_query(question)
            elif intent == "structure_comparison":
                return self._answer_structure_comparison(question)
            else:
                # 通用回答
                return self._answer_general(question, use_hybrid_search)

        except Exception as e:
            logger.error(f"StructureQAAgent 回答失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "answer": None,
                "sources": []
            }

    def _analyze_intent(self, question: str) -> str:
        """分析问题意图"""
        question_lower = question.lower()

        # 方法类问题
        method_keywords = ['method', 'protocol', 'purification', 'expression',
                          'buffer', 'detergent', 'preparation', 'procedure',
                          '方法', '纯化', '表达', '缓冲液', '去垢剂']
        if any(kw in question_lower for kw in method_keywords):
            return "method_query"

        # 结构比较类问题
        comparison_keywords = ['compare', 'difference', 'similar', 'versus',
                              'better', 'comparison', '对比', '比较', '差异']
        if any(kw in question_lower for kw in comparison_keywords):
            return "structure_comparison"

        # 蛋白质信息类问题
        protein_keywords = ['protein', 'structure', 'pdb', 'emdb',
                           'resolution', 'protein', '结构', '分辨率']
        if any(kw in question_lower for kw in protein_keywords):
            return "protein_info"

        return "general"

    def _answer_protein_info(self, question: str) -> Dict[str, Any]:
        """回答蛋白质信息相关问题"""
        # 提取蛋白质名称
        protein_names = self._extract_protein_names(question)

        if not protein_names:
            return {
                "success": False,
                "error": "无法从问题中提取蛋白质名称",
                "answer": None
            }

        # 如果有文献智能体，使用其进行搜索
        if self.literature_agent:
            try:
                result = self.literature_agent.answer_structure_question(question)
                if result and result.get("success"):
                    return result
            except Exception as e:
                logger.warning(f"使用 literature_agent 失败: {e}")

        return {
            "success": True,
            "answer": f"找到与蛋白质相关的信息: {', '.join(protein_names)}",
            "proteins": protein_names,
            "sources": []
        }

    def _answer_method_query(self, question: str) -> Dict[str, Any]:
        """回答方法学相关问题"""
        # 如果有文献智能体，优先使用其检索方法
        if self.literature_agent:
            try:
                # 尝试使用增强的方法检索
                result = self.literature_agent.answer_literature_question(
                    question,
                    use_structure_enhancement=True
                )
                if result and result.get("success"):
                    result["qa_engine"] = "structure_qa_agent_method"
                    return result
            except Exception as e:
                logger.warning(f"方法查询失败: {e}")

        return {
            "success": False,
            "error": "方法查询需要重建索引以使用章节感知检索",
            "answer": None
        }

    def _answer_structure_comparison(self, question: str) -> Dict[str, Any]:
        """回答结构比较相关问题"""
        return {
            "success": True,
            "answer": "结构比较功能需要访问结构数据库",
            "note": "此功能需要 structure_database 模块支持"
        }

    def _answer_general(self, question: str, use_hybrid_search: bool) -> Dict[str, Any]:
        """通用回答"""
        if self.literature_agent:
            try:
                return self.literature_agent.answer_literature_question(question)
            except Exception as e:
                logger.warning(f"通用问答失败: {e}")

        return {
            "success": False,
            "error": "无法回答该问题",
            "answer": None
        }

    def _extract_protein_names(self, question: str) -> List[str]:
        """从问题中提取蛋白质名称"""
        import re

        # 常见的蛋白质命名模式
        patterns = [
            r'\b([A-Z][a-z]+\s*\d+)\b',  # 如 GPR158, GLP1
            r'\b([A-Z]{2,}\d+)\b',       # 如 P53, BRCA1
        ]

        names = []
        for pattern in patterns:
            matches = re.findall(pattern, question)
            names.extend(matches)

        return list(set(names))

    def get_capabilities(self) -> Dict[str, Any]:
        """获取智能体能力信息"""
        return {
            "name": "StructureQAAgent",
            "version": "1.0.0",
            "capabilities": self.capabilities,
            "has_literature_agent": self.literature_agent is not None,
            "supported_queries": [
                "protein_structure",
                "method_protocol",
                "structure_comparison",
                "resolution_analysis"
            ]
        }

    def analyze_protein_structure(self, structure_id: str) -> Dict[str, Any]:
        """
        分析特定蛋白质结构

        Args:
            structure_id: PDB 或 EMDB ID

        Returns:
            结构分析结果
        """
        return {
            "success": True,
            "structure_id": structure_id,
            "analysis": "结构分析功能待实现",
            "note": "需要连接 structure_database 模块获取完整功能"
        }

    def extract_methods_from_literature(self, literature_data: Dict) -> List[Dict]:
        """
        从文献数据中提取方法学信息

        Args:
            literature_data: 文献数据字典

        Returns:
            方法学信息列表
        """
        methods = []

        # 尝试从章节数据中提取方法
        parsed_data = literature_data.get('parsed_data', {})
        if isinstance(parsed_data, dict):
            section_data = parsed_data.get('section_data', {})
            methods_text = section_data.get('methods', '')
            if methods_text:
                methods.append({
                    'source': 'methods_section',
                    'content': methods_text[:1000],  # 限制长度
                    'length': len(methods_text)
                })

        return methods


# 兼容性别名
CryoStructureQAAgent = StructureQAAgent
