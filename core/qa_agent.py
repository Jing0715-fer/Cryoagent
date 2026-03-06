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

    def __init__(self, tool_registry, max_iterations: int = 5):
        self.tool_registry = tool_registry
        self.max_iterations = max_iterations
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
                     session_data: Dict = None, skill_id: str = None) -> Dict:
        """
        处理用户问题

        Args:
            question: 用户问题
            context: 对话上下文（历史消息和工具结果）
            session_data: 会话数据（可选）

        Returns:
            Agent响应，包含type字段标识响应类型
        """
        if session_data is None:
            session_data = {}

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
                answer = await self.generate_answer(question, context, tool_results)
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
            enough_info = await self._check_sufficient_info(question, tool_results)
            if enough_info:
                return AgentAction(
                    type=ActionType.ANSWER,
                    reasoning="已获取足够信息生成答案"
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
        """
        question_lower = question.lower()
        import re

        # 1. 检查是否需要获取结构详情
        if any(keyword in question_lower for keyword in ["结构详情", "分辨率", "method", "实验方法", "详细信息"]):
            # 尝试提取结构ID
            pdb_pattern = r'\b[0-9][A-Za-z0-9]{3}\b'
            emdb_pattern = r'EMD[-]?\d+'

            pdb_matches = re.findall(pdb_pattern, question)
            emdb_matches = re.findall(emdb_pattern, question, re.IGNORECASE)

            if pdb_matches or emdb_matches:
                structure_id = pdb_matches[0].upper() if pdb_matches else emdb_matches[0].upper()
                return ToolCall(
                    tool_name="get_structure_details",
                    params={"structure_id": structure_id}
                )

        # 2. 检查是否需要序列比对
        if any(keyword in question_lower for keyword in ["比对", "比较", "alignment", "compare", "相似度"]):
            # 从上下文或session中获取序列
            sequences = self._extract_sequences_from_context(context, tool_results, session_data)

            if sequences.get("seq1") and sequences.get("seq2"):
                return ToolCall(
                    tool_name="run_sequence_alignment",
                    params={
                        "sequence1": sequences["seq1"],
                        "sequence2": sequences["seq2"],
                        "algorithm": "global"
                    }
                )
            elif sequences.get("uniprot1") and sequences.get("uniprot2"):
                return ToolCall(
                    tool_name="run_sequence_alignment",
                    params={
                        "uniprot1": sequences["uniprot1"],
                        "uniprot2": sequences["uniprot2"],
                        "algorithm": "global"
                    }
                )

        # 3. 检查是否需要知识图谱查询
        if any(keyword in question_lower for keyword in ["关联", "相关", "邻居", "neighbor", "related"]):
            pdb_pattern = r'\b[0-9][A-Za-z0-9]{3}\b'
            matches = re.findall(pdb_pattern, question)
            if matches:
                return ToolCall(
                    tool_name="get_kg_neighbors",
                    params={"structure_id": matches[0].upper(), "depth": 1}
                )

        # 4. 默认使用文献搜索
        return ToolCall(
            tool_name="search_literature",
            params={"query": question, "limit": 10}
        )

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

    async def _check_sufficient_info(self, question: str, tool_results: List[Dict]) -> bool:
        """检查是否已经获取足够的信息来回答问题"""
        if not tool_results:
            return False

        question_lower = question.lower()

        # 检查是否问的是结构详情
        if any(kw in question_lower for kw in ["分辨率", "resolution", "实验方法", "method"]):
            for result in tool_results:
                if result.get("tool_name") == "get_structure_details" and result.get("success"):
                    return True

        # 检查是否问的是比对结果
        if any(kw in question_lower for kw in ["比对", "相似", "alignment", "similarity"]):
            for result in tool_results:
                if result.get("tool_name") == "run_sequence_alignment" and result.get("success"):
                    return True

        # 检查是否问的是文献
        if any(kw in question_lower for kw in ["文献", "论文", "article"]):
            for result in tool_results:
                if result.get("tool_name") == "search_literature" and result.get("success"):
                    return True

        return False

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

    async def generate_answer(self, question: str, context: List[Dict],
                             tool_results: List[Dict]) -> str:
        """生成最终答案"""
        from utils.ai_client import get_ai_client, load_ai_config

        # 如果设置了 Skill，使用 Skill 的 system prompt
        system_prompt = self.current_skill.system_prompt if self.current_skill else ""

        # 准备上下文
        context_parts = []

        # 添加工具结果
        for result in tool_results:
            tool_name = result.get("tool_name", "")
            if result.get("success"):
                data = result.get("result", {})

                if tool_name == "search_literature":
                    items = data.get("results", [])
                    if items:
                        context_parts.append("## 相关文献：\n")
                        for i, item in enumerate(items[:5], 1):
                            title = item.get("title", "Unknown")
                            authors = item.get("authors", [])
                            journal = item.get("journal", "")
                            year = item.get("year", "")
                            context_parts.append(
                                f"{i}. {title}\n"
                                f"   作者: {', '.join(authors[:3])}{' et al.' if len(authors) > 3 else ''}\n"
                                f"   期刊: {journal} ({year})\n"
                            )

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

        if not context_parts:
            context_parts.append("未找到相关信息")

        # 使用AI生成答案
        try:
            config = load_ai_config()
            client = get_ai_client(config)

            # 构建提示词
            base_prompt = f"""基于以下信息回答用户问题：

用户问题：{question}

{''.join(context_parts)}

请用中文生成一个简洁、准确的回答。"""

            # 如果有 Skill，添加 Skill 的系统提示
            if system_prompt:
                prompt = f"""{system_prompt}

---

{base_prompt}"""
            else:
                prompt = base_prompt

            response = await client.chat(prompt)
            return response
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
