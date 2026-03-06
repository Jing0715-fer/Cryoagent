"""
SkillRegistry - Skill 注册和管理
"""
import logging
from typing import Dict, List, Any, Optional
from .skill import Skill, SkillStep

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Skill 注册表"""

    def __init__(self):
        self._skills: Dict[str, Skill] = {}

    def register(self, skill: Skill):
        """注册 Skill"""
        self._skills[skill.id] = skill
        logger.info(f"Registered skill: {skill.id} - {skill.name}")

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """获取 Skill"""
        return self._skills.get(skill_id)

    def match_skill(self, query: str) -> Optional[Skill]:
        """根据关键词匹配 Skill"""
        query_lower = query.lower()

        # 精确匹配优先
        for skill in self._skills.values():
            if skill.id.lower() == query_lower:
                return skill

        # 关键词匹配
        matched_skills = []
        for skill in self._skills.values():
            match_count = sum(1 for kw in skill.trigger_keywords if kw.lower() in query_lower)
            if match_count > 0:
                matched_skills.append((skill, match_count))

        if matched_skills:
            # 返回匹配度最高的
            matched_skills.sort(key=lambda x: x[1], reverse=True)
            return matched_skills[0][0]

        return None

    def list_skills(self, category: str = None) -> List[Dict]:
        """列出所有 Skills"""
        skills = list(self._skills.values())

        if category:
            skills = [s for s in skills if s.category == category]

        return [skill.to_dict() for skill in skills]

    def get_categories(self) -> List[str]:
        """获取所有分类"""
        categories = set()
        for skill in self._skills.values():
            categories.add(skill.category)
        return sorted(list(categories))

    async def execute_workflow(self, skill: Skill, context: Dict,
                                tool_registry) -> List[Dict]:
        """执行 Skill 工作流"""
        results = []

        for step in skill.steps:
            logger.info(f"Executing workflow step: {step.id} - {step.name}")

            # 检查执行条件
            if step.condition and not self._evaluate_condition(step.condition, context, results):
                logger.info(f"Step {step.id} skipped due to condition")
                continue

            # 执行工具
            tool_name = step.tool
            params = self._prepare_step_params(step, context, results)

            try:
                result = await tool_registry.execute_tool(tool_name, params)
                results.append({
                    "step_id": step.id,
                    "step_name": step.name,
                    "tool": tool_name,
                    "success": result.get("success", False),
                    "result": result
                })
            except Exception as e:
                logger.error(f"Error executing workflow step {step.id}: {e}")
                results.append({
                    "step_id": step.id,
                    "step_name": step.name,
                    "tool": tool_name,
                    "success": False,
                    "error": str(e)
                })

        return results

    def _evaluate_condition(self, condition: str, context: Dict,
                           results: List[Dict]) -> bool:
        """评估执行条件"""
        # 简单的条件评估
        # 例如: "has_sequence", "has_structure_id"
        if condition == "has_sequence":
            return bool(context.get("sequence"))
        elif condition == "has_structure_id":
            return bool(context.get("structure_id"))
        elif condition == "has_pmid":
            return bool(context.get("pmid"))
        return True

    def _prepare_step_params(self, step: SkillStep, context: Dict,
                            results: List[Dict]) -> Dict:
        """准备步骤参数"""
        params = {}

        # 从上下文中提取参数
        if "sequence" in step.tool:
            params["sequence"] = context.get("sequence", "")
        if "structure" in step.tool:
            params["structure_id"] = context.get("structure_id", "")
        if "query" in step.tool:
            params["query"] = context.get("query", "")

        # 设置默认值
        params.setdefault("limit", 10)

        return params

    def validate_skill(self, skill: Skill) -> bool:
        """验证 Skill 配置"""
        if not skill.id or not skill.name:
            logger.error("Skill must have id and name")
            return False

        if not skill.tools and not skill.steps:
            logger.error("Skill must have at least one tool or step")
            return False

        return True


# 全局 Skill 注册表
_skill_registry = SkillRegistry()


def get_skill_registry() -> SkillRegistry:
    """获取全局 Skill 注册表"""
    return _skill_registry
