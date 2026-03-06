"""
Skill 框架 - 预设的应用场景和工作流
"""
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SkillStep:
    """Skill 工作流步骤"""
    id: str
    name: str
    tool: str              # 调用的工具
    condition: str = ""    # 执行条件（可选）
    transform: str = ""    # 结果转换方式

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "tool": self.tool,
            "condition": self.condition,
            "transform": self.transform
        }


@dataclass
class Skill:
    """Skill 定义"""
    id: str                    # 唯一标识
    name: str                  # 显示名称
    description: str           # 描述
    category: str              # 分类
    trigger_keywords: List[str]  # 触发关键词
    system_prompt: str         # 系统提示词
    tools: List[str]           # 所需工具列表
    steps: List[SkillStep] = field(default_factory=list)  # 工作流步骤
    examples: List[str] = field(default_factory=list)     # 示例问题
    parameters: Dict = field(default_factory=dict)
    requires_clarification: bool = False  # 是否需要追问

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "trigger_keywords": self.trigger_keywords,
            "tools": self.tools,
            "steps": [step.to_dict() for step in self.steps],
            "examples": self.examples,
            "parameters": self.parameters,
            "requires_clarification": self.requires_clarification
        }

    def matches_query(self, query: str) -> bool:
        """检查查询是否匹配此 Skill"""
        query_lower = query.lower()
        return any(keyword.lower() in query_lower for keyword in self.trigger_keywords)
