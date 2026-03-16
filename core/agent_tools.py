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
# 方法查询优化
# ============================================

# 方法查询检测关键词
METHOD_QUERY_INDICATORS = [
    # 中文
    '方法', '纯化', '表达', 'protocol', 'procedure', '步骤', '流程', '工艺',
    '条件', 'buffer', '缓冲液', '去垢剂', 'detergent', '层析', '色谱',
    'chromatography', '结晶', 'crystal', '制备', 'preparation',
    '提取', 'extraction', '分离', 'isolation', '培养', 'culture',
    # 英文
    'purification', 'purify', 'purified', 'expression', 'express', 'expressed',
    'solubilization', 'solubilize', 'reconstitution', 'reconstitute',
    'incubation', 'incubate', 'centrifugation', 'centrifuge', 'elution', 'elute',
]

# 方法查询扩展词表
METHOD_QUERY_EXPANSION = {
    # 基础词 -> 扩展词列表
    'purification': ['purify', 'purified', 'affinity chromatography', 'size exclusion',
                     'ion exchange', 'gel filtration', 'nickel column', 'his-tag'],
    'expression': ['express', 'expressed', 'baculovirus', 'insect cells', 'sf9', 'hek293',
                   'e. coli', 'bacterial expression', 'mammalian expression'],
    'protocol': ['procedure', 'method', 'workflow', 'steps', 'pipeline'],
    'buffer': ['buffer composition', 'tris', 'hepes', 'pbs', 'salt concentration'],
    'detergent': ['detergents', 'surfactant', 'ddm', 'dodecyl maltoside', 'lmng',
                  'digitonin', 'chaps', 'og', 'ng', 'dm'],
    '纯化': ['亲和层析', '凝胶过滤', '离子交换', '镍柱', 'his标签'],
    '表达': ['表达系统', '杆状病毒', '昆虫细胞', '大肠杆菌', '哺乳动物细胞'],
    '方法': ['protocol', 'procedure', 'workflow', 'steps'],
}

# 方法内容特征词
METHOD_CONTENT_INDICATORS = {
    # 步骤指示词
    'step_markers': [
        'step', 'steps', 'first', 'second', 'third', 'fourth', 'fifth',
        'then', 'next', 'finally', 'subsequently', 'thereafter',
        '步骤', '第一步', '第二步', '第三步', '首先', '然后', '接着', '最后',
    ],
    # 数字单位 (表示具体实验参数)
    'numeric_units': [
        'mm', 'μm', 'nm', 'ml', 'μl', 'l', 'mg', 'μg', 'g', 'kg',
        'mmol', 'μm', 'nmol', 'molar', 'mol', 'm',
        'min', 'hr', 'hrs', 'hour', 'hours', 'sec', 'second', 'seconds',
        'rpm', 'g', '°c', 'c', 'k', 'ph',
        '毫升', '微升', '升', '毫克', '微克', '克', '摩尔', '分钟', '小时', '秒', '度',
    ],
    # 试剂耗材
    'reagents': [
        'buffer', 'detergent', 'column', 'resin', 'beads',
        'tris', 'hepes', 'pbs', 'nacl', 'kcl', 'mgcl2', 'cacl2', 'edta', 'dtt',
        'glycerol', 'glycerol', 'sucrose', 'imidazole',
        'ddm', 'dodecyl', 'maltoside', 'lmng', 'digitonin', 'chaps',
        '缓冲液', '去垢剂', '柱子', '树脂', '微珠', '离心管',
    ],
}


def _is_method_query(query: str) -> bool:
    """检测是否是方法类查询"""
    query_lower = query.lower()
    return any(indicator.lower() in query_lower for indicator in METHOD_QUERY_INDICATORS)


def _expand_method_query(query: str) -> List[str]:
    """
    扩展方法查询

    将方法查询扩展为多个子查询，覆盖不同方面的关键词
    """
    expanded_queries = [query]  # 保留原始查询

    # 检测查询中的方法关键词
    detected_methods = []
    query_lower = query.lower()

    for keyword, expansions in METHOD_QUERY_EXPANSION.items():
        if keyword.lower() in query_lower:
            detected_methods.extend(expansions)

    # 为每个检测到的方向生成扩展查询
    if detected_methods:
        # 基础扩展：添加检测到的相关词
        expansion_terms = ' '.join(detected_methods[:8])  # 限制数量避免过长
        expanded_queries.append(f"{query} {expansion_terms}")

        # 技术细节扩展
        if 'purif' in query_lower or '纯化' in query:
            expanded_queries.append(f"{query} purification buffer detergent chromatography column")
        if 'express' in query_lower or '表达' in query:
            expanded_queries.append(f"{query} expression system cell line vector")
        if 'protocol' in query_lower or 'protocol' in query:
            expanded_queries.append(f"{query} protocol procedure steps workflow")

    return list(set(expanded_queries))  # 去重


def _score_method_content(content: str) -> float:
    """
    评分内容的方法详细程度

    返回 0-100 的分数，分数越高表示包含越详细的方法信息
    """
    content_lower = content.lower()
    score = 0.0

    # 步骤指示词加分
    step_matches = sum(1 for marker in METHOD_CONTENT_INDICATORS['step_markers']
                       if marker.lower() in content_lower)
    score += min(step_matches * 5, 25)  # 最多25分

    # 数字单位加分（表示具体参数）
    unit_matches = sum(1 for unit in METHOD_CONTENT_INDICATORS['numeric_units']
                       if unit.lower() in content_lower)
    score += min(unit_matches * 3, 30)  # 最多30分

    # 试剂耗材加分
    reagent_matches = sum(1 for reagent in METHOD_CONTENT_INDICATORS['reagents']
                          if reagent.lower() in content_lower)
    score += min(reagent_matches * 4, 40)  # 最多40分

    # 检测数值参数模式 (如 "20 mM", "4°C", "12 hours")
    import re
    numeric_patterns = [
        r'\d+\s*(mm|μm|nm|ml|μl|m|mg|μg|g)\b',  # 浓度/体积单位
        r'\d+\s*(min|hr|hour|sec|second)\b',  # 时间单位
        r'\d+\s*(rpm|g|°c|c)\b',  # 转速/温度单位
        r'\d+\.\d+\s*\%',  # 百分比
        r'ph\s*[=:]?\s*\d+\.?\d*',  # pH值
    ]
    for pattern in numeric_patterns:
        matches = len(re.findall(pattern, content_lower))
        score += min(matches * 5, 20)  # 每个模式最多20分

    return min(score, 100)  # 封顶100分


def _multi_stage_method_search(query: str, limit: int = 10) -> List[Dict]:
    """
    多阶段方法检索

    专门针对方法类查询的多轮检索策略：
    1. 第一阶段：检索目标实体相关文献
    2. 第二阶段：在这些文献中搜索方法关键词
    3. 第三阶段：获取方法段落的完整上下文
    """
    from flask import current_app
    from core.search_factory import search_vector
    from core.literature_index import EntityType
    from core.lancedb_rag.rag import get_unified_rag

    try:
        # 阶段1：获取实体相关文献（扩大搜索范围）
        # 提取实体名称（假设查询是 "XXX的方法" 格式）
        entity_query = query
        for indicator in METHOD_QUERY_INDICATORS:
            entity_query = entity_query.replace(indicator, '').strip()

        # 如果提取后实体名为空，使用原始查询
        if not entity_query:
            entity_query = query

        logger.info(f"[MultiStage] Stage 1: Searching entity '{entity_query}'")

        # 获取实体相关文档（获取更多用于后续过滤）
        stage1_results = search_vector(
            query=entity_query,
            top_k=limit * 5,  # 获取更多候选
            entity_filter=EntityType.LITERATURE,
            search_type='vector'
        )

        if not stage1_results:
            return []

        # 收集相关文献ID
        doc_ids = set()
        for r in stage1_results:
            doc = r.get('document', {})
            doc_id = doc.get('doc_id') or r.get('id', '').split('_chunk_')[0]
            if doc_id:
                doc_ids.add(doc_id)

        logger.info(f"[MultiStage] Stage 1: Found {len(doc_ids)} unique documents")

        # 阶段2：在这些文档中搜索方法相关内容
        # 构建方法扩展查询
        method_queries = _expand_method_query(query)
        logger.info(f"[MultiStage] Stage 2: Expanded queries: {method_queries}")

        # 使用 RAG 系统进行更精细的检索
        rag = get_unified_rag()
        all_method_results = []

        # 方法查询优先搜索 full_text 章节（因为当前分块只有 abstract/full_text/key_findings）
        # TODO: 实现章节感知分块后，可以改为 ['methods', 'results']
        method_sections = ['full_text']
        logger.info(f"[MultiStage] Searching in sections: {method_sections}")

        for mq in method_queries:
            try:
                logger.info(f"[MultiStage] Searching with query: {mq}")
                method_results = rag.retrieve_chunks(
                    query=mq,
                    top_k=limit * 4,  # 获取更多结果用于后续过滤
                    sections=method_sections,  # 限制在方法相关章节
                    use_rerank=True,
                )
                logger.info(f"[MultiStage] Found {len(method_results)} results from vector search (sections filter)")

                # 回退策略：如果章节过滤返回太少结果，直接使用LanceDB查询
                if len(method_results) < limit:
                    logger.info(f"[MultiStage] Section filter returned too few results, using direct DB query")

                    try:
                        # 直接使用 LanceDB 查询目标文档的 methods 章节
                        import lancedb
                        from flask import current_app

                        # 使用正确的 LanceDB 路径
                        db_path = current_app.config.get('LANCEDB_PATH', 'data/lancedb')
                        db = lancedb.connect(db_path)
                        table = db.open_table('literature')

                        # 为目标文档构建 where 子句（使用 full_text 章节，因为当前分块只有 abstract/full_text/key_findings）
                        doc_id_list = ", ".join([f"'{d}'" for d in doc_ids])
                        where_clause = f"section IN ('full_text') AND doc_id IN ({doc_id_list})"

                        logger.info(f"[MultiStage] Direct DB query: {where_clause}")

                        # 查询数据库
                        db_results = table.search().where(where_clause).limit(50).to_list()
                        logger.info(f"[MultiStage] Direct DB query returned {len(db_results)} results")

                        # 转换为标准格式
                        from core.lancedb_rag.rag import get_unified_rag
                        rag = get_unified_rag()

                        for r in db_results:
                            formatted = {
                                'id': r.get('id'),
                                'doc_id': r.get('doc_id'),
                                'section': r.get('section'),
                                'content': r.get('full_text', ''),
                                'score': 0.5,  # 默认分数
                                'title': r.get('title', ''),
                                'year': r.get('year'),
                                'journal': r.get('journal', ''),
                            }

                            # 计算方法得分
                            method_score = _score_method_content(formatted['content'])
                            keyword_matches = sum(1 for kw in [
                                'purification', 'expression', 'protocol', 'buffer', 'detergent',
                                'chromatography', 'column', 'resin', 'elution',
                                '纯化', '表达', '缓冲液', '层析'
                            ] if kw in formatted['content'].lower())

                            if keyword_matches >= 2:
                                method_score += min(keyword_matches * 5, 30)

                            formatted['method_score'] = method_score
                            formatted['method_keywords_found'] = keyword_matches

                            method_results.append(formatted)

                    except Exception as e:
                        logger.error(f"[MultiStage] Direct DB query failed: {e}")
                        import traceback
                        traceback.print_exc()

                    logger.info(f"[MultiStage] After direct DB query: {len(method_results)} results")

                logger.info(f"[MultiStage] Processing {len(method_results)} results")

                # 过滤：只保留来自第一阶段文档的结果，并增强方法关键词过滤
                for r in method_results:
                    doc_id = r.get('doc_id', '').split('_chunk_')[0]
                    if doc_id in doc_ids or not doc_ids:
                        content = r.get('content', '')

                        # 计算方法内容得分
                        method_score = _score_method_content(content)

                        # 增强：检查是否包含方法关键词
                        method_keywords = [
                            'purification', 'expression', 'protocol', 'buffer', 'detergent',
                            'chromatography', 'column', 'resin', 'elution', 'solubilization',
                            'reconstitution', 'incubation', 'centrifugation', 'preparation',
                            'extraction', 'isolation', 'concentration', 'dialysis',
                            '纯化', '表达', '缓冲液', '去垢剂', '层析', '色谱',
                            '柱子', '树脂', '洗脱', '增溶', '复溶', '提取', '分离',
                            '步骤', 'procedure', 'protocol', 'method', 'reagent'
                        ]
                        content_lower = content.lower()
                        keyword_matches = sum(1 for kw in method_keywords if kw in content_lower)

                        # 如果包含方法关键词，提高方法得分
                        if keyword_matches >= 2:
                            method_score += min(keyword_matches * 5, 30)
                            logger.debug(f"[MultiStage] Chunk {r.get('id')} has {keyword_matches} method keywords")

                        r['method_score'] = method_score
                        r['method_content_score'] = method_score
                        r['method_keywords_found'] = keyword_matches
                        all_method_results.append(r)
            except Exception as e:
                logger.warning(f"[MultiStage] Query '{mq}' failed: {e}")

        # 过滤掉方法得分太低的结果
        min_method_score = 15  # 最低方法得分阈值
        filtered_method_results = [
            r for r in all_method_results
            if r.get('method_score', 0) >= min_method_score
        ]

        logger.info(f"[MultiStage] After method score filter: {len(filtered_method_results)} results (min_score={min_method_score})")

        # 去重并排序
        seen_ids = set()
        unique_results = []
        for r in sorted(filtered_method_results,
                        key=lambda x: (x.get('method_score', 0), x.get('score', 0)),
                        reverse=True):
            rid = r.get('id')
            if rid not in seen_ids:
                seen_ids.add(rid)
                unique_results.append(r)

        logger.info(f"[MultiStage] Stage 2: Found {len(unique_results)} unique method results")

        # 阶段3：获取完整上下文（邻居块扩展）
        # 已经由 _include_neighbor_chunks 在 RAG 中处理
        return unique_results[:limit]

    except Exception as e:
        logger.error(f"[MultiStage] Error: {e}")
        return []


# ============================================
# 工具实现
# ============================================

def search_literature_executor(query: str, limit: int = 10, **kwargs) -> Dict:
    """执行文献搜索 - 使用 LanceDB 向量搜索，并通过AI过滤相关结果"""
    from flask import current_app
    try:
        with current_app.app_context():
            from core.search_factory import search_vector
            from core.literature_index import EntityType

            # 检测是否是方法类查询
            is_method_query = _is_method_query(query)

            if is_method_query:
                logger.info(f"[Search] Detected method query: '{query}'")

                # 方法查询：使用多阶段检索策略
                method_results = _multi_stage_method_search(query, limit=limit * 2)

                if method_results:
                    logger.info(f"[Search] Multi-stage search found {len(method_results)} results")

                    # 转换为标准格式
                    literature_list = []
                    for r in method_results:
                        # 从 RAG 结果中提取内容（已经包含邻居块合并）
                        text_content = r.get('content', '') or r.get('full_text', '')

                        # 获取文档元数据
                        doc = r.get('document', {})
                        if doc:
                            title = doc.get('title', '')
                            authors = doc.get('authors', [])
                            journal = doc.get('journal', '')
                            year = doc.get('year')
                            doi = doc.get('doi', '')
                            has_neighbors = doc.get('has_neighbors', False)
                            chunk_count = doc.get('chunk_count', 1)
                            is_method = doc.get('is_method_content', False)
                        else:
                            title = r.get('title', '')
                            authors = []
                            journal = r.get('journal', '')
                            year = r.get('year')
                            doi = ''
                            has_neighbors = False
                            chunk_count = 1
                            is_method = False

                        lit_entry = {
                            'id': r.get('id'),
                            'title': title,
                            'authors': authors,
                            'journal': journal,
                            'year': year,
                            'doi': doi,
                            'abstract': text_content[:500] + '...' if len(text_content) > 500 else text_content,
                            'content': text_content,
                            'score': r.get('score', 0),
                            'method_score': r.get('method_score', 0) or r.get('method_content_score', 0),
                            'has_neighbors': has_neighbors,
                            'chunk_index': r.get('chunk_index', 0),
                            'chunk_count': chunk_count,
                            'is_method_content': is_method,
                        }

                        logger.info(f"[Search] Method result: id={r.get('id')}, "
                                   f"has_neighbors={has_neighbors}, content_len={len(text_content)}, "
                                   f"method_score={lit_entry['method_score']}")

                        literature_list.append(lit_entry)

                    # 方法内容过滤和排序
                    logger.info(f"[Search] Before method filter: {len(literature_list)} results")
                    literature_list = _filter_method_results(query, literature_list, limit)
                    logger.info(f"[Search] After method filter: {len(literature_list)} results")

                    return {
                        "query": query,
                        "is_method_query": True,
                        "count": len(literature_list),
                        "total_results": len(literature_list),
                        "results": literature_list
                    }

            # 非方法查询或方法查询未找到结果：使用标准搜索
            # 查询扩展（即使是普通查询也可以受益）
            expanded_queries = _expand_method_query(query) if is_method_query else [query]
            all_results = []

            for eq in expanded_queries:
                results = search_vector(
                    query=eq,
                    top_k=limit * 2,
                    entity_filter=EntityType.LITERATURE,
                    search_type='hybrid'
                )
                all_results.extend(results)

            # 去重
            seen_ids = set()
            unique_results = []
            for r in all_results:
                rid = r.get('id')
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    unique_results.append(r)

            # 转换结果为统一格式
            literature_list = []
            for r in unique_results:
                doc = r.get('document', {})
                # 使用 full_text 或 content 字段
                text_content = doc.get('full_text', '') or doc.get('content', '') or doc.get('abstract', '')

                # 计算方法内容得分（用于方法查询）
                method_score = 0
                if is_method_query:
                    method_score = _score_method_content(text_content)

                literature_list.append({
                    'id': r.get('id'),
                    'title': doc.get('title', ''),
                    'authors': doc.get('authors', []),
                    'journal': doc.get('journal', ''),
                    'year': doc.get('year'),
                    'doi': doc.get('doi', ''),
                    'abstract': text_content,
                    'content': text_content,
                    'score': r.get('score', 0),
                    'method_score': method_score,
                    'has_neighbors': doc.get('has_neighbors', False),
                    'chunk_count': doc.get('chunk_count', 1),
                })

            # AI过滤：只保留与查询相关的结果
            if literature_list and kwargs.get('use_ai_filter', True):
                try:
                    if is_method_query:
                        # 方法查询使用方法专用过滤
                        literature_list = _filter_method_results(query, literature_list, limit)
                    else:
                        # 普通查询使用标准过滤
                        literature_list = _filter_relevant_literature(query, literature_list, limit)
                except Exception as e:
                    logger.warning(f"AI过滤失败，使用原始结果: {e}")
                    literature_list = literature_list[:limit]

            logger.info(f"Vector search found {len(literature_list)} results after filtering")
            return {
                "query": query,
                "is_method_query": is_method_query,
                "count": len(literature_list),
                "total_results": len(literature_list),
                "results": literature_list
            }
    except Exception as e:
        logger.error(f"Error in search_literature: {e}")
        return {"query": query, "count": 0, "results": [], "error": str(e)}


def _filter_relevant_literature(query: str, literature_list: List[Dict], limit: int) -> List[Dict]:
    """
    使用AI过滤只保留与查询相关的文献

    评估每个文献与查询的相关性，保留高相关度的结果
    """
    try:
        from core.agent_core import get_text_embedding, ask_literature_question

        # 为每个文献计算相关性
        filtered_results = []

        for lit in literature_list:
            content = lit.get('content', '')[:2000]  # 限制长度避免token过多
            if not content:
                continue

            # 构建相关性评估提示
            relevance_prompt = f"""评估以下文献内容与查询问题的相关程度。

查询问题：{query}

文献标题：{lit.get('title', 'Unknown')}

文献内容：
{content}

请判断这篇文献是否包含回答查询问题所需的具体信息。
只关注实质性相关内容，忽略泛泛而谈的介绍。

回复格式：只回复一个数字 0-100，表示相关度分数。
- 90-100：直接包含回答问题的具体信息
- 70-89：包含相关背景和方法信息
- 50-69：有一定相关性但信息不完整
- 0-49：不相关或只有泛泛介绍"""

            try:
                # 使用简单规则快速评估（避免多次API调用）
                # 检查关键词匹配
                query_keywords = set(query.lower().split())
                content_lower = content.lower()

                # 基础分数
                relevance_score = lit.get('score', 0.5) * 100  # 基础向量相似度

                # 关键词匹配加分
                keyword_matches = sum(1 for kw in query_keywords if kw in content_lower)
                relevance_score += min(keyword_matches * 5, 20)

                # 特定内容类型加分
                if 'purif' in content_lower or 'express' in content_lower:
                    relevance_score += 15
                if 'method' in content_lower or 'protocol' in content_lower:
                    relevance_score += 10

                lit['relevance_score'] = min(relevance_score, 100)

                # 只保留相关度>=60的结果
                if relevance_score >= 60:
                    filtered_results.append(lit)

            except Exception as e:
                logger.debug(f"相关性评估失败: {e}")
                # 评估失败时保留该文献
                lit['relevance_score'] = lit.get('score', 0.5) * 100
                filtered_results.append(lit)

        # 按相关性排序并返回top_k
        filtered_results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        return filtered_results[:limit]

    except Exception as e:
        logger.error(f"AI过滤过程失败: {e}")
        return literature_list[:limit]


def _filter_method_results(query: str, literature_list: List[Dict], limit: int) -> List[Dict]:
    """
    方法查询专用过滤 - 优先保留包含详细方法信息的结果

    不仅评估相关性，还评估方法内容的详细程度
    严格过滤掉不相关实体（如查询GPR158时排除GPR179的内容）
    """
    try:
        filtered_results = []
        query_lower = query.lower()

        # 提取查询中的目标实体名（如 GPR158）
        # 支持多种格式：GPR158, GPCR, Protein Name 等
        import re
        entity_names = []

        # 尝试匹配常见的蛋白质/GPCR命名格式
        # 例如：GPR158, GPER1, CXCR4, etc.
        protein_patterns = [
            r'gpr\d+',  # GPR158, GPR179, etc.
            r'gper\d+',  # GPER1, etc.
            r'cxcr\d+',  # CXCR4, etc.
            r'[a-z]{2,6}\d{1,3}',  # 一般蛋白质命名格式
        ]

        for pattern in protein_patterns:
            matches = re.findall(pattern, query_lower)
            entity_names.extend(matches)

        # 如果没有匹配到，尝试从查询开头提取大写/数字组合
        if not entity_names:
            words = query_lower.split()
            for word in words:
                # 提取像 GPR158 这样的实体名
                if len(word) >= 3 and any(c.isdigit() for c in word):
                    entity_names.append(word.strip('.,;:!?'))

        # 去重并记录目标实体
        target_entities = list(set(entity_names))
        logger.info(f"[_filter_method_results] Detected target entities: {target_entities}")

        # 定义需要排除的相似实体（如果查询GPR158，排除GPR179等）
        # 这些会降低分数
        similar_but_different = []
        if target_entities:
            for target in target_entities:
                # 找出类似命名的其他实体
                for lit in literature_list:
                    title = lit.get('title', '').lower()
                    content = lit.get('content', '').lower()

                    # 在标题和内容中查找类似格式的实体
                    all_entities_in_content = re.findall(r'gpr\d+', content)
                    all_entities_in_content.extend(re.findall(r'gpr\d+', title))

                    for entity in all_entities_in_content:
                        # 如果实体格式相似但不同（如 GPR158 vs GPR179）
                        if entity != target and entity.startswith(target[:3]):
                            similar_but_different.append(entity)

        similar_but_different = list(set(similar_but_different))
        if similar_but_different:
            logger.info(f"[_filter_method_results] Similar but different entities to exclude: {similar_but_different}")

        for lit in literature_list:
            content = lit.get('content', '')
            title = lit.get('title', '')
            if not content:
                continue

            content_lower = content.lower()
            title_lower = title.lower()
            combined_text = content_lower + " " + title_lower

            # 0. 【硬性过滤】检查是否包含不相关的实体
            # 如果内容主要讨论的是其他相似实体，则跳过
            if similar_but_different:
                wrong_entity_count = sum(1 for e in similar_but_different if e in combined_text)
                target_entity_count = sum(1 for e in target_entities if e in combined_text)

                # 如果错误实体出现次数 >= 目标实体出现次数，跳过
                if wrong_entity_count > 0 and wrong_entity_count >= target_entity_count:
                    logger.debug(f"Skipping result with wrong entity: {wrong_entity_count} vs {target_entity_count}")
                    continue

            # 1. 【硬性要求】必须包含目标实体
            entity_matched = False
            for entity in target_entities:
                if entity in combined_text:
                    entity_matched = True
                    break

            # 如果没有匹配到任何目标实体，检查标题
            if not entity_matched and target_entities:
                # 如果标题包含实体名，也认为是匹配的（因为摘要是关于该实体的）
                for entity in target_entities:
                    if entity in title_lower:
                        entity_matched = True
                        logger.debug(f"Entity {entity} found in title, considering matched")
                        break

            # 如果没有匹配到任何目标实体，大幅降低分数或跳过
            if not entity_matched and target_entities:
                logger.debug(f"Result doesn't contain target entity {target_entities}, skipping")
                continue

            # 2. 基础相关性分数
            relevance_score = lit.get('score', 0.5) * 60  # 提高基础向量相似度权重（最高60分）

            # 3. 方法内容详细程度分数
            method_score = lit.get('method_score', 0)
            if method_score == 0:
                method_score = _score_method_content(content)

            # 4. 关键词匹配加分
            query_keywords = [kw for kw in query_lower.split() if len(kw) > 2]
            keyword_matches = sum(1 for kw in query_keywords if kw in content_lower)
            keyword_score = min(keyword_matches * 5, 25)  # 提高关键词匹配权重

            # 5. 实体匹配加分（确保内容是关于正确实体的）
            entity_score = 0
            if entity_matched:
                entity_score = 15  # 匹配到目标实体给予基础分
                # 如果标题和正文都包含实体，额外加分
                title_has_entity = any(e in title_lower for e in target_entities)
                content_has_entity = any(e in content_lower for e in target_entities)
                if title_has_entity and content_has_entity:
                    entity_score += 10

            # 6. 方法特定关键词加分
            method_keywords = [
                'purification', 'expression', 'protocol', 'buffer', 'detergent',
                'chromatography', 'column', 'resin', 'elution', 'solubilization',
                'reconstitution', 'incubation', 'centrifugation', 'preparation',
                '纯化', '表达', '缓冲液', '去垢剂', '层析', '色谱', '柱子', '树脂',
                '步骤', 'procedure', 'protocol', 'method'
            ]
            method_kw_matches = sum(1 for kw in method_keywords if kw in content_lower)
            method_kw_score = min(method_kw_matches * 4, 30)  # 提高方法关键词权重

            # 7. 来源章节加分（如果是 methods section）
            section_score = 0
            if lit.get('source_section') == 'methods':
                section_score = 20  # methods section 给予额外加分

            # 计算总分
            total_score = relevance_score + method_score + keyword_score + entity_score + method_kw_score + section_score
            lit['total_score'] = min(total_score, 100)
            lit['method_detail_score'] = method_score
            lit['entity_matched'] = entity_matched

            # 记录详细评分日志
            logger.debug(f"[_filter_method_results] Score breakdown for {lit.get('id', 'unknown')}: "
                        f"relevance={relevance_score:.1f}, method={method_score:.1f}, "
                        f"keyword={keyword_score:.1f}, entity={entity_score:.1f}, "
                        f"method_kw={method_kw_score:.1f}, section={section_score:.1f}, total={total_score:.1f}")

            # 保留标准（进一步放宽）：
            # 1. 必须匹配目标实体（或标题匹配）
            # 2. 方法得分 >= 10（大幅降低）
            # 3. 总分 >= 35（大幅降低）
            if entity_matched and method_score >= 10 and total_score >= 35:
                filtered_results.append(lit)
                logger.debug(f"[_filter_method_results] KEPT result {lit.get('id', 'unknown')}, content_len={len(content)}")
            else:
                logger.debug(f"[_filter_method_results] SKIPPED result {lit.get('id', 'unknown')}: "
                            f"entity_matched={entity_matched}, method_score={method_score}, total={total_score}")

        # 按总分排序
        filtered_results.sort(key=lambda x: x.get('total_score', 0), reverse=True)

        logger.info(f"[_filter_method_results] Filtered {len(literature_list)} -> {len(filtered_results)} results")
        return filtered_results[:limit]

    except Exception as e:
        logger.error(f"方法过滤失败: {e}")
        # 失败时返回原始列表按方法分数排序的结果
        literature_list.sort(key=lambda x: x.get('method_score', 0), reverse=True)
        return literature_list[:limit]


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
