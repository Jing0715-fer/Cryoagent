"""
QAAgent - 智能问答Agent核心逻辑
支持多轮对话、工具调用、选项式追问
"""
import asyncio
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ActionType(Enum):
    """Agent行动类型"""
    CLARIFY = "clarify"      # 需要澄清
    TOOL = "tool"            # 调用工具
    ANSWER = "answer"        # 生成答案
    FINISH = "finish"        # 结束对话


@dataclass
class ClarificationOption:
    """澄清问题选项"""
    id: str
    label: str
    description: str = ""
    value: Any = None
    icon: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "value": self.value if self.value is not None else self.id,
            "icon": self.icon
        }


@dataclass
class Clarification:
    """澄清请求"""
    question: str
    options: List[ClarificationOption]
    context: str = ""  # 补充说明

    def to_dict(self) -> Dict:
        return {
            "type": "clarification",
            "question": self.question,
            "options": [opt.to_dict() for opt in self.options],
            "context": self.context
        }


@dataclass
class ToolCall:
    """工具调用请求"""
    tool_name: str
    params: Dict[str, Any]
    reason: str = ""

    def to_dict(self) -> Dict:
        return {
            "type": "tool_call",
            "tool_name": self.tool_name,
            "params": self.params,
            "reason": self.reason
        }


@dataclass
class AgentAction:
    """Agent决策结果"""
    type: ActionType
    question: str = ""           # 用于clarify类型
    options: List[ClarificationOption] = field(default_factory=list)  # 用于clarify类型
    tool_call: ToolCall = None   # 用于tool类型
    reasoning: str = ""           # 决策理由
    extra_info: Dict[str, Any] = field(default_factory=dict)  # 额外信息（如 is_image_only）

    def to_dict(self) -> Dict:
        result = {
            "type": self.type.value,
            "reasoning": self.reasoning
        }

        if self.type == ActionType.CLARIFY:
            result["question"] = self.question
            result["options"] = [opt.to_dict() for opt in self.options]
        elif self.type == ActionType.TOOL and self.tool_call:
            result["tool_call"] = self.tool_call.to_dict()

        return result


@dataclass
class ToolResult:
    """工具执行结果"""
    tool_name: str
    success: bool
    result: Any
    error: str = ""
    execution_time: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "execution_time": self.execution_time
        }


class QAAgent:
    """智能问答Agent"""

    def __init__(self, tool_registry, max_iterations: int = 5, max_tokens: int = None):
        self.tool_registry = tool_registry
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens  # 最大输出token数
        self.tools = tool_registry.get_all_tools()
        self.tool_map = {t.name: t for t in self.tools}
        self.current_skill = None  # 当前激活的 Skill

    def set_skill(self, skill):
        """设置当前使用的 Skill"""
        self.current_skill = skill
        # 根据 Skill 更新工具列表
        if skill and skill.tools:
            self.tools = [self.tool_map.get(t) for t in skill.tools if t in self.tool_map]
            self.tools = [t for t in self.tools if t is not None]

    async def process(self, question: str, context: List[Dict],
                     session_data: Dict = None, skill_id: str = None, max_tokens: int = None) -> Dict:
        """
        处理用户问题

        Args:
            question: 用户问题
            context: 对话上下文（历史消息和工具结果）
            session_data: 会话数据（可选）
            skill_id: Skill ID（可选）
            max_tokens: 最大输出token数（可选）

        Returns:
            Agent响应，包含type字段标识响应类型
        """
        if session_data is None:
            session_data = {}

        # 存储max_tokens供后续使用
        self.max_tokens = max_tokens

        # 加载 Skill（如果指定了 skill_id）
        if skill_id and not self.current_skill:
            from core.skills import get_skill_registry
            skill_registry = get_skill_registry()
            skill = skill_registry.get_skill(skill_id)
            if skill:
                self.set_skill(skill)
                logger.info(f"Loaded skill: {skill.name}")

        # Agent主循环
        iteration = 0
        tool_results = []

        while iteration < self.max_iterations:
            iteration += 1

            # 1. 分析问题，决定下一步行动
            action = await self.plan_action(question, context, tool_results, session_data)

            logger.info(f"[Agent] Iteration {iteration}: {action.type.value} - {action.reasoning}")

            # 2. 如果需要澄清，返回带选项的Clarification
            if action.type == ActionType.CLARIFY:
                return {
                    "type": "clarification",
                    "clarification": action.question,
                    "options": [opt.to_dict() for opt in action.options],
                    "iteration": iteration,
                    "reasoning": action.reasoning
                }

            # 3. 如果需要调用工具
            if action.type == ActionType.TOOL:
                tool_call = action.tool_call

                # 执行工具
                result = await self.execute_tool(tool_call.tool_name, tool_call.params)
                tool_result = ToolResult(
                    tool_name=tool_call.tool_name,
                    success=result.get("success", False),
                    result=result.get("result", result),
                    error=result.get("error", "")
                )
                tool_results.append(tool_result.to_dict())

                # 将工具结果添加到上下文
                context.append({
                    "role": "tool",
                    "tool": tool_call.tool_name,
                    "result": tool_result.to_dict()
                })

                # 如果工具执行失败，可能需要澄清
                if not tool_result.success:
                    return {
                        "type": "error",
                        "message": f"工具执行失败: {tool_result.error}",
                        "suggestion": "请检查输入是否正确，或尝试其他方式"
                    }

                # 继续循环，检查是否需要更多工具调用
                continue

            # 4. 如果准备完毕，生成答案
            if action.type == ActionType.ANSWER:
                # 检查是否是纯图片请求，如果是则跳过 AI 生成
                is_image_only = action.extra_info.get("is_image_only", False)
                if is_image_only:
                    # 纯图片请求，直接返回精简响应
                    logger.info("[Agent] 调用 _generate_image_only_answer...")
                    answer = self._generate_image_only_answer(question, tool_results)
                    logger.info(f"[Agent] 生成答案完成: {answer[:50]}...")

                    # 清理 tool_results，移除不可序列化的对象
                    cleaned_tool_results = []
                    for tr in tool_results:
                        cleaned_tr = {
                            'tool_name': tr.get('tool_name', ''),
                            'success': tr.get('success', False),
                        }
                        # 只保留可序列化的 result
                        result_data = tr.get('result')
                        if result_data and isinstance(result_data, dict):
                            cleaned_result = {}
                            for k, v in result_data.items():
                                # 只保留基本类型
                                if isinstance(v, (str, int, float, bool, type(None), list, dict)):
                                    cleaned_result[k] = v
                            cleaned_tr['result'] = cleaned_result
                        cleaned_tool_results.append(cleaned_tr)

                    logger.info(f"[Agent] tool_results 清理完成: {len(cleaned_tool_results)}")

                    # 清理 extra_info
                    cleaned_extra_info = {}
                    if action.extra_info:
                        for k, v in action.extra_info.items():
                            if isinstance(v, (str, int, float, bool, type(None))):
                                cleaned_extra_info[k] = v

                    result = {
                        "type": "answer",
                        "content": answer,
                        "iteration": iteration,
                        "tool_results": cleaned_tool_results,
                        "reasoning": action.reasoning,
                        "extra_info": cleaned_extra_info
                    }

                    # 测试 JSON 序列化
                    try:
                        json_str = json.dumps(result)
                        logger.info(f"[Agent] JSON 序列化成功，长度: {len(json_str)}")
                    except Exception as e:
                        logger.error(f"[Agent] JSON 序列化失败: {e}")
                        result = {
                            "type": "answer",
                            "content": answer,
                            "iteration": iteration,
                            "tool_results": [],
                            "reasoning": action.reasoning,
                            "extra_info": {"is_image_only": True}
                        }

                    logger.info(f"[Agent] 准备返回结果...")
                    return result
                else:
                    # 正常调用 AI 生成答案
                    answer = await self.generate_answer(question, context, tool_results, max_tokens=self.max_tokens)
                    return {
                        "type": "answer",
                        "content": answer,
                        "iteration": iteration,
                        "tool_results": tool_results,
                        "reasoning": action.reasoning
                    }

            # 5. 结束对话
            if action.type == ActionType.FINISH:
                answer = await self.generate_answer(question, context, tool_results)
                return {
                    "type": "answer",
                    "content": answer,
                    "iteration": iteration,
                    "tool_results": tool_results,
                    "reasoning": action.reasoning
                }

        # 超过最大迭代次数
        return {
            "type": "answer",
            "content": "问题较为复杂，已进行多轮尝试。如需更精确的答案，请尝试将问题拆分或提供更多具体信息。",
            "iteration": iteration,
            "tool_results": tool_results
        }

    async def plan_action(self, question: str, context: List[Dict],
                         tool_results: List[Dict], session_data: Dict) -> AgentAction:
        """
        分析问题，决定下一步行动

        使用AI分析问题类型和需要的信息，决定是澄清、调用工具还是生成答案
        如果设置了 Skill，优先使用 Skill 定义的工具
        """
        from flask import current_app
        from flask_login import current_user
        from utils.ai_client import get_ai_client, load_ai_config

        # 准备上下文信息
        context_summary = self._summarize_context(context, tool_results)

        # 检查是否已经有足够的信息
        if tool_results:
            # 分析工具结果，判断是否足以回答问题
            enough_info, extra_info = await self._check_sufficient_info(question, tool_results)
            if enough_info:
                # 检查是否是纯图片请求
                reasoning = "已获取足够信息生成答案"
                if extra_info.get("is_image_only"):
                    reasoning = "已获取足够信息生成答案 (纯图片请求)"
                return AgentAction(
                    type=ActionType.ANSWER,
                    reasoning=reasoning,
                    extra_info=extra_info
                )

        # 检查是否需要澄清
        clarification = await self._check_needs_clarification(question, context, tool_results, session_data)
        if clarification:
            return AgentAction(
                type=ActionType.CLARIFY,
                question=clarification.question,
                options=clarification.options,
                reasoning="需要用户澄清具体需求"
            )

        # 决定使用哪个工具
        tool_call = await self._decide_tool(question, context, tool_results, session_data)
        if tool_call:
            return AgentAction(
                type=ActionType.TOOL,
                tool_call=tool_call,
                reasoning=f"调用工具 {tool_call.tool_name} 获取信息"
            )

        # 默认生成答案
        return AgentAction(
            type=ActionType.ANSWER,
            reasoning="基于已有信息生成答案"
        )

    async def _check_needs_clarification(self, question: str, context: List[Dict],
                                         tool_results: List[Dict], session_data: Dict) -> Optional[Clarification]:
        """
        检查问题是否需要澄清
        返回Clarification对象如果需要澄清，否则返回None
        """
        question_lower = question.lower()

        # 检测是否需要进行序列比对
        if any(keyword in question_lower for keyword in ["比对", "比较", "alignment", "compare", "相似"]):
            # 检查是否提供了足够的序列信息
            has_sequences = False

            # 检查上下文中的序列信息
            for item in context:
                if item.get("role") == "user" and ("序列" in item.get("content", "") or "sequence" in item.get("content", "").lower()):
                    has_sequences = True
                    break

            # 检查工具结果
            for result in tool_results:
                if result.get("tool_name") == "run_sequence_alignment":
                    has_sequences = True
                    break

            if not has_sequences:
                # 需要澄清序列输入方式
                return Clarification(
                    question="请选择序列输入方式：",
                    options=[
                        ClarificationOption(
                            id="pdb_select",
                            label="从已上传结构选择",
                            description="从您已上传的PDB/EMDB结构中提取序列",
                            value="pdb_select"
                        ),
                        ClarificationOption(
                            id="uniprot",
                            label="输入UniProt ID",
                            description="输入UniProt蛋白质 accession（如 P0A8V2）",
                            value="uniprot"
                        ),
                        ClarificationOption(
                            id="sequence",
                            label="直接输入序列",
                            description="粘贴蛋白质氨基酸序列",
                            value="sequence"
                        )
                    ]
                )

        # 检测是否需要查询结构详情
        if any(keyword in question_lower for keyword in ["结构", "结构详情", "resolution", "分辨率"]):
            # 尝试从问题中提取结构ID
            import re
            pdb_pattern = r'\b[0-9][A-Za-z0-9]{3}\b'
            emdb_pattern = r'EMD[-]?\d+'

            pdb_matches = re.findall(pdb_pattern, question)
            emdb_matches = re.findall(emdb_pattern, question, re.IGNORECASE)

            if not pdb_matches and not emdb_matches:
                # 需要澄清要查询的结构
                return Clarification(
                    question="请提供要查询的结构：",
                    options=[
                        ClarificationOption(
                            id="pdb_input",
                            label="输入PDB ID",
                            description="如 6Y4F, 7K5U",
                            value="pdb_input"
                        ),
                        ClarificationOption(
                            id="emdb_input",
                            label="输入EMDB ID",
                            description="如 EMD-12345",
                            value="emdb_input"
                        ),
                        ClarificationOption(
                            id="pdb_search",
                            label="搜索结构",
                            description="输入关键词搜索PDB/EMDB",
                            value="pdb_search"
                        )
                    ]
                )

        # 检测是否需要搜索文献
        if any(keyword in question_lower for keyword in ["文献", "论文", "article", "paper", "publication"]):
            # 文献搜索通常不需要澄清，直接执行
            pass

        return None

    async def _decide_tool(self, question: str, context: List[Dict],
                          tool_results: List[Dict], session_data: Dict) -> Optional[ToolCall]:
        """
        决定使用哪个工具

        流程：
        1. 第一轮：调用 AI 分析问题，判断需要什么工具
        2. 后续轮次：根据已有结果决定下一步
        """
        import re
        question_lower = question.lower()

        # 0. 如果已经执行过搜索工具，尝试优化搜索策略
        for tr in tool_results:
            if tr.get("tool_name") in ["search_structures", "search_literature"]:
                if tr.get("success"):
                    data = tr.get("result", {})
                    count = data.get("count", 0)
                    if count > 0:
                        logger.info("[DecideTool] 已有搜索结果，不再重复搜索")
                        return None  # 有结果，直接生成答案
                    else:
                        # 搜索无结果，尝试优化搜索词
                        logger.info("[DecideTool] 搜索无结果，尝试优化搜索词")
                        # 提取之前的搜索词
                        tool_params = tr.get("tool_params", {})
                        old_query = tool_params.get("query", "")

                        # 如果之前搜索词包含 "purification method"，尝试去掉
                        if "purification" in old_query.lower() or "method" in old_query.lower():
                            # 去掉修饰词，只搜索核心关键词
                            new_query = question
                            # 移除常见修饰词
                            for word in ["purification", "method", "methods", "纯化", "方法", "实验", "protocol"]:
                                new_query = new_query.replace(word, "").strip()
                            # 清理多余空格
                            new_query = " ".join(new_query.split())
                            if new_query and len(new_query) > 2:
                                logger.info(f"[DecideTool] 尝试新搜索词: {new_query}")
                                return ToolCall(
                                    tool_name=tr.get("tool_name"),
                                    params={"query": new_query, "limit": 10}
                                )

                        # 如果无法优化搜索词，返回 None 让 Agent 生成答案
                        logger.info("[DecideTool] 无法优化搜索词，直接生成答案")
                        return None
                else:
                    logger.info("[DecideTool] 之前的搜索失败，尝试其他方法")

        # 检查是否需要生成结构图像 (PyMOL)
        pdb_pattern = r'\b[0-9][A-Za-z0-9]{3}\b'
        pdb_matches = re.findall(pdb_pattern, question)
        pdb_id = pdb_matches[0].upper() if pdb_matches else None

        if any(keyword in question_lower for keyword in ["image", "图片", "图像", "可视化", "visualize", "show structure", "展示结构", "生成图像", "generate image", "cartoon", "stick", "ribbon", "surface"]):
            if pdb_id:
                style = "cartoon"
                if "stick" in question_lower:
                    style = "sticks"
                elif "ribbon" in question_lower:
                    style = "ribbon"
                elif "surface" in question_lower:
                    style = "surface"
                elif "line" in question_lower:
                    style = "line"

                return ToolCall(
                    tool_name="pymol_image",
                    params={"pdb_id": pdb_id, "style": style, "color": "rainbow"}
                )

        # 检查是否需要序列比对
        if any(keyword in question_lower for keyword in ["比对", "比较", "alignment", "compare", "相似度"]):
            sequences = self._extract_sequences_from_context(context, tool_results, session_data)

            if sequences.get("seq1") and sequences.get("seq2"):
                return ToolCall(
                    tool_name="run_sequence_alignment",
                    params={"sequence1": sequences["seq1"], "sequence2": sequences["seq2"], "algorithm": "global"}
                )
            elif sequences.get("uniprot1") and sequences.get("uniprot2"):
                return ToolCall(
                    tool_name="run_sequence_alignment",
                    params={"uniprot1": sequences["uniprot1"], "uniprot2": sequences["uniprot2"], "algorithm": "global"}
                )

        # 检查是否需要知识图谱查询
        if any(keyword in question_lower for keyword in ["关联", "相关", "邻居", "neighbor", "related"]):
            if pdb_id:
                return ToolCall(
                    tool_name="get_kg_neighbors",
                    params={"structure_id": pdb_id, "depth": 1}
                )

        # 检查是否需要获取结构详情
        if any(keyword in question_lower for keyword in ["结构详情", "分辨率", "method", "实验方法", "详细信息", "详情"]):
            if pdb_id:
                return ToolCall(
                    tool_name="get_structure_details",
                    params={"structure_id": pdb_id}
                )

        # 其他情况：调用 AI 分析问题，判断使用什么工具
        # 这是核心改进：第一轮让 AI 分析问题
        analysis_result = await self._analyze_question_and_decide_tool(question, tool_results)
        if analysis_result:
            return analysis_result

        # 如果 AI 分析没有返回工具，检查是否是简单问题
        simple_question_patterns = [
            "什么是", "是什么", "what is", "定义",
            "解释", "explain", "介绍", "introduce",
            "总结", "summarize", "摘要"
        ]
        is_simple = any(pattern in question_lower for pattern in simple_question_patterns)

        if is_simple:
            return None  # 直接回答

        # 默认搜索文献
        return ToolCall(
            tool_name="search_literature",
            params={"query": question, "limit": 10}
        )

    async def _analyze_question_and_decide_tool(self, question: str, tool_results: List[Dict]) -> Optional[ToolCall]:
        """
        使用 AI 分析问题，判断需要什么工具

        根据数据库索引文档，AI 可以判断：
        - 问题涉及结构/序列 → search_structures
        - 问题涉及文献 → search_literature
        - 问题涉及结构详情 → get_structure_details
        """
        try:
            from utils.ai_client import get_ai_client, load_ai_config

            config = load_ai_config()
            client = get_ai_client(config)

            # 数据库索引文档内容
            db_index = """
## 数据库索引说明

### structures 表 - 存储结构元数据
- 字段: id (PDB ID), title, resolution, method, organism, gene, protein_name
- 用途: 查询结构的基本信息（分辨率、实验方法、标题等）

### structure_entities 表 - 存储实体序列信息
- 字段: structure_id, entity_poly_seq_one_letter_code (氨基酸序列), entity_poly_seq_length (序列长度), molecule_type, protein_name, gene_name
- 用途: 查询氨基酸序列、序列长度

### uniprot_structure_mapping 表 - UniProt 与结构映射
- 字段: uniprot_id, structure_id, gene_name, protein_name
- 用途: 根据 UniProt ID 查找对应结构

## 可用工具说明

1. search_structures: 搜索结构数据库
   - 输入: query (搜索关键词), source (pdb/emdb), limit
   - 返回: 结构列表，包含序列信息
   - 适用: 问序列、结构、蛋白名称

2. search_literature: 搜索文献数据库
   - 输入: query (搜索关键词), limit
   - 返回: 文献列表
   - 适用: 问文献、论文

3. get_structure_details: 获取结构详情
   - 输入: structure_id (PDB ID)
   - 返回: 结构详细信息
   - 适用: 问特定 PDB 的详细信息

4. pymol_image: 生成结构图像
   - 输入: pdb_id, style, color
   - 返回: 结构图像
   - 适用: 需要结构可视化

5. get_kg_neighbors: 获取知识图谱关联
   - 输入: structure_id, depth
   - 返回: 相关结构列表
   - 适用: 问相关结构
"""

            # 构建已有结果摘要
            results_summary = ""
            if tool_results:
                results_summary = "\n## 已完成的工具调用：\n"
                for tr in tool_results:
                    name = tr.get("tool_name", "unknown")
                    success = tr.get("success", False)
                    data = tr.get("result", {})
                    count = data.get("count", 0)
                    results_summary += f"- {name}: {'成功' if success else '失败'}, 返回 {count} 条结果\n"

            prompt = f"""你是一个智能问答助手，负责分析用户问题并选择合适的工具。

## 用户问题
{question}

{db_index}

{results_summary}

请分析这个问题，判断需要调用什么工具来回答。

问题分析要点：
1. 问题是否涉及蛋白质的序列？→ 使用 search_structures
2. 问题是否涉及结构详情（分辨率、实验方法）？→ 使用 search_structures 或 get_structure_details
3. 问题是否涉及文献？→ 使用 search_literature
4. 问题是否需要生成图片？→ 使用 pymol_image
5. 问题是否需要获取关联结构？→ 使用 get_kg_neighbors

请按以下 JSON 格式返回分析结果：
{{
    "needs_tool": true/false,
    "reasoning": "分析理由",
    "tool_name": "工具名称（如果需要）",
    "tool_params": {{"参数": "值"}},
    "can_answer_directly": true/false（如果不需要工具可以直接回答）
}}

只返回 JSON，不要其他内容。"""

            messages = [{"role": "user", "content": prompt}]
            response = client.chat(messages)

            if response.get('success'):
                content = response.get('content', '')
                import json
                import re

                # 提取 JSON
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    result = json.loads(json_match.group())
                    logger.info(f"[AnalyzeQuestion] AI 分析结果: {result}")

                    # 如果判断不需要工具，直接回答
                    if result.get("can_answer_directly") or not result.get("needs_tool"):
                        return None

                    # 返回需要调用的工具
                    tool_name = result.get("tool_name")
                    tool_params = result.get("tool_params", {})

                    if tool_name:
                        # 如果需要搜索结构，提取蛋白名称
                        if tool_name == "search_structures":
                            protein_info = await self._extract_protein_name(question)
                            if protein_info:
                                tool_params["protein_info"] = protein_info

                        return ToolCall(
                            tool_name=tool_name,
                            params=tool_params
                        )
        except Exception as e:
            logger.warning(f"AI 分析问题失败: {e}")

        return None

    async def _extract_protein_name(self, question: str) -> Optional[Dict]:
        """使用 AI 提取和标准化蛋白质名称"""
        try:
            from utils.ai_client import get_ai_client, load_ai_config

            config = load_ai_config()
            client = get_ai_client(config)

            prompt = f"""从用户问题中提取蛋白质/基因名称，并标准化。

用户问题：{question}

请按以下 JSON 格式返回：
{{
    "standard_name": "标准蛋白名称(英文首字母大写，如 GPR179)",
    "gene_name": "基因名称(如 GPR179)",
    "uniprot_id": "UniProt ID(如 Q9H5V6)，如果没有则为空",
    "variants": ["其他常用名称变体1", "其他常用名称变体2"],
    "protein_type": "受体/酶/通道/抗体等，如果不确定则为空"
}}

只返回 JSON，不要其他内容。"""

            messages = [{"role": "user", "content": prompt}]
            response = client.chat(messages)

            if response.get('success'):
                content = response.get('content', '')
                import json
                import re
                json_match = re.search(r'\{[^}]+\}', content, re.DOTALL)
                if json_match:
                    protein_info = json.loads(json_match.group())
                    return protein_info
        except Exception as e:
            logger.warning(f"AI 提取蛋白名称失败: {e}")

        return None

    def _extract_sequences_from_context(self, context: List[Dict],
                                       tool_results: List[Dict],
                                       session_data: Dict) -> Dict:
        """从上下文中提取序列信息"""
        sequences = {}

        # 从session_data中获取
        if session_data:
            if session_data.get("seq1"):
                sequences["seq1"] = session_data["seq1"]
            if session_data.get("seq2"):
                sequences["seq2"] = session_data["seq2"]
            if session_data.get("uniprot1"):
                sequences["uniprot1"] = session_data["uniprot1"]
            if session_data.get("uniprot2"):
                sequences["uniprot2"] = session_data["uniprot2"]

        # 从工具结果中获取
        for result in tool_results:
            if result.get("tool_name") == "run_sequence_alignment":
                # 已经执行过比对了
                pass

        return sequences

    async def _check_sufficient_info(self, question: str, tool_results: List[Dict]) -> Tuple[bool, Dict[str, Any]]:
        """
        检查是否已经获取足够的信息来回答问题

        Returns:
            Tuple[bool, Dict]: (是否信息足够，附加标记)
            - 对于纯图片请求，返回 (True, {"is_image_only": True})
            - 对于其他请求，返回 (True/False, {})
        """
        if not tool_results:
            logger.info("[CheckSufficient] tool_results is empty")
            return False, {}

        question_lower = question.lower()
        logger.info(f"[CheckSufficient] Checking {len(tool_results)} tool results for question: {question[:50]}")
        logger.info(f"[CheckSufficient] question_lower: {question_lower}")
        logger.info(f"[CheckSufficient] All tool results: {[r.get('tool_name') for r in tool_results]}")

        extra_info = {}

        # 简化检查：只要有任何工具返回了成功结果，就认为信息足够
        # 让 AI 来决定如何整理这些结果
        for result in tool_results:
            if result.get("success"):
                data = result.get("result", {})
                # 检查各种可能的结果计数
                count = data.get("count", 0) or data.get("total_results", 0) or len(data.get("results", []))
                logger.info(f"[CheckSufficient] Tool {result.get('tool_name')} data: count={data.get('count')}, total_results={data.get('total_results')}, results_len={len(data.get('results', []))}, final_count={count}")
                if count > 0:
                    logger.info(f"[CheckSufficient] Found {count} results from {result.get('tool_name')}, sufficient")
                    return True, {}

        # 检查是否需要生成结构图像（纯图片请求）
        image_keywords = ["image", "图片", "图像", "可视化", "visualize", "show", "展示", "生成图像", "cartoon", "stick", "ribbon", "surface", "line"]
        if any(kw in question_lower for kw in image_keywords):
            for result in tool_results:
                if result.get("tool_name") == "pymol_image" and result.get("success"):
                    # 纯图片请求，标记为 image_only，跳过 AI 生成
                    extra_info["is_image_only"] = True
                    logger.info(f"[CheckSufficient] Image-only request detected")
                    return True, extra_info

        logger.info("[CheckSufficient] Not enough info, returning False")
        return False, {}

    async def execute_tool(self, tool_name: str, params: Dict) -> Dict:
        """执行工具"""
        import time
        start_time = time.time()

        try:
            result = await self.tool_registry.execute_tool(tool_name, params)
            execution_time = time.time() - start_time

            logger.info(f"Tool {tool_name} executed in {execution_time:.2f}s")

            return result
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _select_relevant_structures(self, question: str, structures: List[Dict], top_k: int = 5) -> List[Dict]:
        """
        使用 AI 筛选最相关的结构（当结果超过 5 个时）

        Args:
            question: 用户问题
            structures: 结构列表
            top_k: 返回的最大数量

        Returns:
            筛选后的结构列表
        """
        try:
            from utils.ai_client import get_ai_client, load_ai_config

            config = load_ai_config()
            client = get_ai_client(config)

            # 构建结构摘要
            struct_summaries = []
            for i, s in enumerate(structures):
                pdb_id = s.get('pdb_id', 'N/A')
                title = s.get('title', '')[:50]
                gene = s.get('gene', '')
                protein_name = s.get('protein_name', '')
                seq_len = len(s.get('sequence', '')) if s.get('sequence') else s.get('sequence_length', 0)
                struct_summaries.append(f"{i}: PDB={pdb_id}, Gene={gene}, Protein={protein_name[:30]}, SeqLen={seq_len}, Title={title}")

            prompt = f"""用户问题：{question}

请从以下结构中选择与问题最相关的 {top_k} 个结构（按相关性排序）：

{chr(10).join(struct_summaries)}

请按以下 JSON 格式返回选中的索引列表：
{{"selected_indices": [0, 2, 5, ...]}}

只返回 JSON，不要其他内容。选择最可能包含用户所需信息的结构。"""

            messages = [{"role": "user", "content": prompt}]
            response = client.chat(messages)

            if response.get('success'):
                import json
                import re
                content = response.get('content', '')
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    result = json.loads(json_match.group())
                    indices = result.get('selected_indices', [])
                    selected = [structures[i] for i in indices if 0 <= i < len(structures)]
                    logger.info(f"[SelectStructures] AI selected {len(selected)} structures from {len(structures)}")
                    return selected[:top_k]
        except Exception as e:
            logger.warning(f"AI 筛选结构失败: {e}")

        # 回退：返回前 top_k 个
        return structures[:top_k]

    async def generate_answer(self, question: str, context: List[Dict],
                             tool_results: List[Dict], max_tokens: int = None) -> str:
        """生成最终答案

        Args:
            question: 用户问题
            context: 对话上下文
            tool_results: 工具执行结果
            max_tokens: 最大输出token数（可选，默认从配置读取）
        """
        from utils.ai_client import get_ai_client, load_ai_config

        # 如果设置了 Skill，使用 Skill 的 system prompt
        system_prompt = self.current_skill.system_prompt if self.current_skill else ""

        # 获取配置中的 max_tokens
        config = load_ai_config()
        if max_tokens is None:
            max_tokens = config.get('max_tokens', 8096)

        # 准备上下文
        context_parts = []

        # 收集所有结构用于智能筛选
        all_structures = []
        structure_tool_result = None
        for result in tool_results:
            if result.get("tool_name") == "search_structures" and result.get("success"):
                structure_tool_result = result
                items = result.get("result", {}).get("results", [])
                all_structures.extend(items)

        # 添加工具结果
        for result in tool_results:
            tool_name = result.get("tool_name", "")
            if result.get("success"):
                data = result.get("result", {})

                if tool_name == "search_literature":
                    items = data.get("results", [])
                    if items:
                        context_parts.append("## 相关文献（按相关度排序）：\n")
                        # 限制文献数量为 5 个，但提供完整内容
                        for i, item in enumerate(items[:5], 1):
                            title = item.get("title", "Unknown")
                            authors = item.get("authors", [])
                            journal = item.get("journal", "")
                            year = item.get("year", "")
                            doi = item.get("doi", "")
                            # 获取完整内容（不再是摘要）
                            content = item.get("content", "") or item.get("abstract", "")
                            relevance_score = item.get("relevance_score", 0)
                            chunk_count = item.get("chunk_count", 1)

                            context_parts.append(
                                f"\n{'='*60}\n"
                                f"文献 {i}: {title}\n"
                                f"{'='*60}\n"
                                f"作者: {', '.join(authors[:5])}{' et al.' if len(authors) > 5 else ''}\n"
                                f"期刊: {journal} ({year})\n"
                                f"DOI: {doi}\n"
                            )
                            if relevance_score:
                                context_parts.append(f"相关度评分: {relevance_score:.1f}/100\n")
                            if chunk_count > 1:
                                context_parts.append(f"注：此内容包含原文 {chunk_count} 个相邻段落\n")

                            # 添加完整内容
                            if content:
                                # 限制长度避免超出token限制
                                max_content_length = 8000  # 每篇文献最多8000字符
                                if len(content) > max_content_length:
                                    content = content[:max_content_length] + "\n... [内容已截断]"
                                context_parts.append(f"\n【原文内容】:\n{content}\n")

                elif tool_name == "search_structures":
                    items = data.get("results", [])
                    if items:
                        context_parts.append("## 相关结构：\n")

                        # 如果超过 5 个结构，先让 AI 筛选
                        if len(items) > 5:
                            selected_items = await self._select_relevant_structures(question, items, top_k=5)
                        else:
                            selected_items = items

                        for i, item in enumerate(selected_items, 1):
                            pdb_id = item.get("pdb_id", "")
                            title = item.get("title", "")
                            resolution = item.get("resolution")
                            method = item.get("method", "")
                            sequence = item.get("sequence", "")
                            seq_length = item.get("sequence_length")
                            gene = item.get("gene", "")
                            protein_name = item.get("protein_name", "")
                            source = item.get("source", "structure_db")

                            context_parts.append(f"{i}. PDB ID: {pdb_id or 'N/A'}\n")
                            if title:
                                context_parts.append(f"   标题: {title[:80]}\n")
                            if protein_name:
                                context_parts.append(f"   蛋白名称: {protein_name}\n")
                            if gene:
                                context_parts.append(f"   基因: {gene}\n")
                            if resolution:
                                context_parts.append(f"   分辨率: {resolution} Å\n")
                            if method:
                                context_parts.append(f"   实验方法: {method}\n")
                            if source:
                                context_parts.append(f"   数据来源: {source}\n")
                            if sequence:
                                # 检查是否有实体列表（FASTA 格式）
                                entities = item.get("entities", [])
                                if entities:
                                    context_parts.append(f"   序列 (FASTA 格式):\n")
                                    for ent in entities:
                                        entity_id = ent.get("entity_id", "")
                                        chain = ent.get("chain_ids", "")
                                        protein = ent.get("protein_name", "")
                                        gene = ent.get("gene", "")
                                        seq = ent.get("sequence", "")

                                        # 构建 FASTA header: >PDB_ID|Chain|Protein|Gene
                                        header_parts = [pdb_id]
                                        if chain:
                                            header_parts.append(f"Chain_{chain}")
                                        if protein:
                                            header_parts.append(protein[:30])  # 限制长度
                                        if gene:
                                            header_parts.append(gene)

                                        fasta_header = "|".join(header_parts)
                                        context_parts.append(f"   >{fasta_header}\n")
                                        context_parts.append(f"   {seq}\n")
                                else:
                                    # 兼容旧格式
                                    context_parts.append(f"   序列: {sequence}\n")
                                context_parts.append(f"   序列长度: {len(sequence)} 残基\n")
                            elif seq_length:
                                context_parts.append(f"   序列长度: {seq_length} 残基\n")

                elif tool_name == "get_structure_details":
                    struct = data.get("structure", {})
                    if struct:
                        context_parts.append("## 结构信息：\n")
                        context_parts.append(f"- PDB ID: {struct.get('pdb_id', 'N/A')}\n")
                        context_parts.append(f"- 标题: {struct.get('title', 'N/A')}\n")
                        resolution = struct.get("resolution")
                        context_parts.append(f"- 分辨率: {resolution} Å\n" if resolution else "- 分辨率: N/A\n")
                        context_parts.append(f"- 实验方法: {struct.get('experimental_method', 'N/A')}\n")

                elif tool_name == "run_sequence_alignment":
                    alignment = data.get("alignment", {})
                    if alignment:
                        context_parts.append("## 序列比对结果：\n")
                        identity = alignment.get("identity", 0)
                        context_parts.append(f"- 相似度: {identity:.1%}\n")
                        context_parts.append(f"- 比对长度: {alignment.get('aligned_length', 0)}\n")
                        context_parts.append(f"- 匹配: {alignment.get('matches', 0)}, 间隙: {alignment.get('gaps', 0)}\n")

                elif tool_name == "get_kg_neighbors":
                    neighbors = data.get("neighbors", [])
                    if neighbors:
                        context_parts.append(f"## 知识图谱关联 ({len(neighbors)}个相关结构)：\n")
                        for n in neighbors[:5]:
                            context_parts.append(f"- {n.get('structure_id', 'N/A')}: {n.get('relationship', 'related')}\n")

                elif tool_name == "pymol_image":
                    image_path = data.get("image_path")
                    pdb_id = data.get("pdb_id")
                    if image_path:
                        context_parts.append(f"## 结构图像：\n")
                        context_parts.append(f"- PDB ID: {pdb_id}\n")
                        context_parts.append(f"- 图像路径: {image_path}\n")
                        # 将相对路径转换为访问URL
                        filename = image_path.split('/')[-1] if '/' in image_path else image_path
                        context_parts.append(f"- 访问URL: /api/pymol/sessions/{filename}\n")

        if not context_parts:
            context_parts.append("未找到相关信息")

        # 使用AI生成答案
        try:
            config = load_ai_config()
            client = get_ai_client(config)

            # 检测是否涉及序列问题
            question_lower = question.lower()
            is_sequence_question = any(kw in question_lower for kw in [
                "序列", "sequence", "氨基酸", "amino acid", "残基", "residue"
            ])

            # 构建提示词
            base_prompt = f"""基于以下检索到的文献原文回答用户问题。

用户问题：{question}

{''.join(context_parts)}

**回答要求**：
1. **详细步骤**：如果文献中包含实验方法、操作步骤或流程，必须从原文提取并列出完整的详细步骤，不要简单概括
2. **引用来源**：回答时必须标注信息来源，格式为 [文献X: 标题]
3. **多文献对比**：如果多篇文献涉及同一主题，请分别说明并比较差异
4. **原文引用**：关键信息请直接引用原文片段
5. **结构化输出**：使用编号列表、表格等方式组织信息，便于阅读
6. **语言**：请用中文回答

**特别提醒**：
- 用户询问的是具体实验方法/步骤，请从原文整理出完整的操作流程
- 不要只给简短总结，要提供足够详细的信息让用户能够复现
- 如果文献中没有足够详细的信息，请明确说明"文献未提供详细步骤" """
            # 如果是序列问题，添加额外强调
            if is_sequence_question:
                base_prompt += """

**特别强调**：用户询问的是序列信息，你必须在回答中完整显示相关序列！"""

            # 如果有 Skill，添加 Skill 的系统提示
            if system_prompt:
                prompt = f"""{system_prompt}

---

{base_prompt}"""
            else:
                prompt = base_prompt

            # client.chat 需要 messages 列表格式
            messages = [{"role": "user", "content": prompt}]

            # client.chat 是同步方法，返回 {'success': True, 'content': '...', 'model': '...'}
            response = client.chat(messages, max_tokens=max_tokens)
            if response.get('success'):
                return response.get('content', '')
            else:
                raise Exception(response.get('error', 'Unknown error'))
        except Exception as e:
            logger.error(f"Error generating answer: {e}")
            # 回退到简单格式
            return f"根据查询结果：\n\n{''.join(context_parts)}"

    def _summarize_context(self, context: List[Dict], tool_results: List[Dict]) -> str:
        """总结上下文用于AI分析"""
        parts = []

        for item in context[-3:]:  # 最近3条
            role = item.get("role", "")
            content = item.get("content", "")
            if content:
                parts.append(f"{role}: {content[:100]}")

        if tool_results:
            parts.append(f"已执行 {len(tool_results)} 个工具")

        return " | ".join(parts) if parts else "无上下文"

    def _generate_image_only_answer(self, question: str, tool_results: List[Dict]) -> str:
        """
        为纯图片请求生成精简答案（不调用 AI）

        Args:
            question: 用户问题
            tool_results: 工具执行结果

        Returns:
            精简答案字符串
        """
        for result in tool_results:
            if result.get("tool_name") == "pymol_image" and result.get("success"):
                data = result.get("result", {})
                # 处理嵌套的 result 结构
                if "result" in data:
                    data = data.get("result", {})
                pdb_id = data.get("pdb_id", "")
                image_path = data.get("image_path", "")
                style = data.get("style", "")

                # 生成精简答案
                answer = f"已为您生成 {pdb_id} 的{style}结构图像。"
                return answer

        # 如果没有找到图片，返回默认答案
        return "已为您完成请求。"

    def _generate_fallback_answer(self, question: str, tool_results: List[Dict]) -> str:
        """
        生成降级答案（当 AI 超时时使用）

        Args:
            question: 用户问题
            tool_results: 工具执行结果

        Returns:
            降级答案字符串
        """
        context_parts = []

        for result in tool_results:
            if not result.get('success'):
                continue

            tool_name = result.get('tool_name', '')
            data = result.get('result', {})

            if tool_name == 'pymol_image':
                pdb_id = data.get('pdb_id', '')
                image_path = data.get('image_path', '')
                if image_path:
                    filename = image_path.split('/')[-1]
                    context_parts.append(f"[图片已生成] {pdb_id} - /api/pymol/sessions/{filename}")

            elif tool_name == 'search_structures':
                items = data.get('results', [])
                if items:
                    context_parts.append(f"[找到 {len(items)} 个结构]")
                    for item in items[:3]:
                        pdb_id = item.get('pdb_id', '')
                        title = item.get('title', '')[:50]
                        context_parts.append(f"  - {pdb_id}: {title}")

            elif tool_name == 'search_literature':
                items = data.get('results', [])
                if items:
                    context_parts.append(f"[找到 {len(items)} 篇文献]")
                    for item in items[:3]:
                        title = item.get('title', '')[:50]
                        context_parts.append(f"  - {title}")

        if context_parts:
            return "AI 服务暂时不可用，以下是查询结果：\n\n" + "\n".join(context_parts)
        else:
            return "AI 服务暂时不可用，请稍后重试。"


# ============================================
# 辅助函数
# ============================================

def create_agent(tool_registry, skill_id: str = None) -> QAAgent:
    """创建Agent实例

    Args:
        tool_registry: 工具注册表
        skill_id: 可选的 Skill ID

    Returns:
        QAAgent 实例
    """
    agent = QAAgent(tool_registry, max_iterations=5)

    # 如果指定了 skill_id，加载对应的 Skill
    if skill_id:
        from core.skills import get_skill_registry
        skill_registry = get_skill_registry()
        skill = skill_registry.get_skill(skill_id)
        if skill:
            agent.set_skill(skill)
            logger.info(f"Agent created with skill: {skill.name}")

    return agent
