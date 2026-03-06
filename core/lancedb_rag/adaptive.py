# adaptive.py - 自适应检索
"""
自适应检索模块

根据查询类型自动选择检索策略
"""

import logging
import re
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ============= 查询类型 =============

class QueryType(Enum):
    """查询类型"""
    LITERATURE = "literature"  # 文献检索
    STRUCTURE = "structure"  # 结构检索
    HYBRID = "hybrid"  # 混合检索
    GENERAL = "general"  # 通用查询
    COMPARISON = "comparison"  # 对比查询
    DETAILED = "detailed"  # 详细查询


# ============= 检索策略 =============

@dataclass
class RetrievalStrategy:
    """检索策略配置"""
    use_vector: bool = True
    use_bm25: bool = True
    use_rerank: bool = False
    vector_weight: float = 0.5
    bm25_weight: float = 0.5
    top_k: int = 10
    min_score: float = 0.0
    recency_boost: bool = False
    include_structured: bool = True


@dataclass
class AdaptiveConfig:
    """自适应检索配置"""
    default_strategy: RetrievalStrategy = field(default_factory=RetrievalStrategy)
    query_type_detection: bool = True
    dynamic_top_k: bool = True
    min_top_k: int = 5
    max_top_k: int = 20


# ============= 查询类型检测器 =============

class QueryTypeDetector:
    """
    查询类型检测器

    通过规则和模式匹配识别查询类型
    """

    # 关键词模式
    LITERATURE_KEYWORDS = [
        "paper", "article", "publication", "research", "study",
        "doi", "pmid", "arxiv", "journal", "conference",
        "abstract", "citation", "author", "published",
        "论文", "文献", "发表", "研究", "期刊",
    ]

    STRUCTURE_KEYWORDS = [
        "pdb", "emdb", "alphafold", "structure", "protein",
        "crystal", "cryo-em", "resolution", "x-ray", "nmr",
        "原子结构", "蛋白质结构", "三维结构", "PDB", "EMDB",
    ]

    COMPARISON_KEYWORDS = [
        "compare", "comparison", "difference", "versus", "vs",
        "better", "worse", "advantage", "disadvantage",
        "对比", "比较", "差异", "优势", "劣势",
    ]

    DETAILED_KEYWORDS = [
        "detail", "explain", "describe", "mechanism", "process",
        "how", "why", "what is", "explain",
        "详细", "解释", "机制", "原理", "如何", "为什么",
    ]

    def __init__(self):
        """初始化检测器"""
        self._compile_patterns()

    def _compile_patterns(self):
        """编译正则表达式模式"""
        # DOI 模式
        self.doi_pattern = re.compile(
            r'10\.\d{4,}/[^\s]+',
            re.IGNORECASE
        )

        # PMID 模式
        self.pmid_pattern = re.compile(
            r'PMID:?\s*\d+',
            re.IGNORECASE
        )

        # PDB/EMDB 模式
        self.structure_id_pattern = re.compile(
            r'\b(pdb|emdb|af)-?[0-9a-z]{4,6}\b',
            re.IGNORECASE
        )

    def detect(self, query: str) -> QueryType:
        """
        检测查询类型

        Args:
            query: 查询文本

        Returns:
            查询类型
        """
        query_lower = query.lower()

        # 检查精确匹配
        if self.doi_pattern.search(query) or self.pmid_pattern.search(query):
            return QueryType.LITERATURE

        if self.structure_id_pattern.search(query):
            return QueryType.STRUCTURE

        # 关键词计数
        lit_count = sum(1 for kw in self.LITERATURE_KEYWORDS if kw in query_lower)
        struct_count = sum(1 for kw in self.STRUCTURE_KEYWORDS if kw in query_lower)
        comp_count = sum(1 for kw in self.COMPARISON_KEYWORDS if kw in query_lower)
        det_count = sum(1 for kw in self.DETAILED_KEYWORDS if kw in query_lower)

        # 根据关键词数量判断
        if lit_count > 0 and struct_count > 0:
            return QueryType.HYBRID
        elif struct_count > lit_count and struct_count > 0:
            return QueryType.STRUCTURE
        elif lit_count > 0:
            return QueryType.LITERATURE
        elif comp_count > 0:
            return QueryType.COMPARISON
        elif det_count > 0:
            return QueryType.DETAILED

        return QueryType.GENERAL

    def get_strategy(self, query_type: QueryType) -> RetrievalStrategy:
        """
        获取查询类型对应的检索策略

        Args:
            query_type: 查询类型

        Returns:
            检索策略
        """
        strategies = {
            QueryType.LITERATURE: RetrievalStrategy(
                use_vector=True,
                use_bm25=True,
                use_rerank=True,
                vector_weight=0.6,
                bm25_weight=0.4,
                top_k=10,
            ),
            QueryType.STRUCTURE: RetrievalStrategy(
                use_vector=True,
                use_bm25=True,
                use_rerank=True,
                vector_weight=0.7,
                bm25_weight=0.3,
                top_k=5,
            ),
            QueryType.HYBRID: RetrievalStrategy(
                use_vector=True,
                use_bm25=True,
                use_rerank=True,
                vector_weight=0.5,
                bm25_weight=0.5,
                top_k=15,
                include_structured=True,
            ),
            QueryType.COMPARISON: RetrievalStrategy(
                use_vector=True,
                use_bm25=True,
                use_rerank=True,
                vector_weight=0.4,
                bm25_weight=0.6,
                top_k=20,
            ),
            QueryType.DETAILED: RetrievalStrategy(
                use_vector=True,
                use_bm25=True,
                use_rerank=True,
                vector_weight=0.5,
                bm25_weight=0.5,
                top_k=10,
                recency_boost=True,
            ),
            QueryType.GENERAL: RetrievalStrategy(
                use_vector=True,
                use_bm25=True,
                use_rerank=False,
                vector_weight=0.5,
                bm25_weight=0.5,
                top_k=5,
            ),
        }

        return strategies.get(query_type, RetrievalStrategy())


# ============= 自适应检索器 =============

class AdaptiveRetrieval:
    """
    自适应检索器

    根据查询类型自动选择最优检索策略
    """

    def __init__(
        self,
        config: Optional[AdaptiveConfig] = None,
        vector_search_fn: Optional[Callable] = None,
        bm25_index: Optional[Any] = None,
        reranker: Optional[Any] = None,
    ):
        """
        初始化自适应检索器

        Args:
            config: 自适应检索配置
            vector_search_fn: 向量搜索函数
            bm25_index: BM25 索引
            reranker: 重排序器
        """
        self.config = config or AdaptiveConfig()
        self.vector_search_fn = vector_search_fn
        self.bm25_index = bm25_index
        self.reranker = reranker

        self.detector = QueryTypeDetector()

        # 动态 top_k 调整
        self._query_complexity_history: List[Dict[str, Any]] = []

    def search(
        self,
        query: str,
        documents: Optional[List[Dict[str, Any]]] = None,
        text_field: str = "text",
        id_field: str = "id",
        force_type: Optional[QueryType] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        自适应搜索

        Args:
            query: 查询文本
            documents: 文档列表
            text_field: 文本字段名
            id_field: ID 字段名
            force_type: 强制指定查询类型
            **kwargs: 其他参数

        Returns:
            搜索结果和元信息
        """
        # 检测查询类型
        query_type = force_type or (
            self.detector.detect(query) if self.config.query_type_detection
            else QueryType.GENERAL
        )

        # 获取检索策略
        strategy = self.detector.get_strategy(query_type)

        # 动态调整 top_k
        if self.config.dynamic_top_k:
            strategy.top_k = self._adjust_top_k(query)

        logger.info(f"查询类型: {query_type.value}, 策略: vector={strategy.use_vector}, bm25={strategy.use_bm25}, rerank={strategy.use_rerank}, top_k={strategy.top_k}")

        # 执行检索
        results = self._execute_search(
            query=query,
            documents=documents,
            text_field=text_field,
            id_field=id_field,
            strategy=strategy,
            **kwargs
        )

        # 记录查询复杂度
        self._record_query_complexity(query, query_type, strategy)

        return {
            "results": results,
            "query_type": query_type.value,
            "strategy": {
                "use_vector": strategy.use_vector,
                "use_bm25": strategy.use_bm25,
                "use_rerank": strategy.use_rerank,
                "top_k": strategy.top_k,
            },
        }

    def _adjust_top_k(self, query: str) -> int:
        """
        动态调整 top_k

        根据查询长度和复杂度调整返回数量
        """
        base_top_k = self.config.default_strategy.top_k

        # 长度调整
        query_length = len(query.split())
        if query_length > 20:
            return min(base_top_k + 5, self.config.max_top_k)
        elif query_length > 10:
            return base_top_k

        # 复杂度历史调整
        if len(self._query_complexity_history) >= 3:
            recent_complexity = sum(
                h.get("complexity", 0)
                for h in self._query_complexity_history[-3:]
            ) / 3

            if recent_complexity > 0.7:
                return min(base_top_k + 3, self.config.max_top_k)

        return max(base_top_k, self.config.min_top_k)

    def _execute_search(
        self,
        query: str,
        documents: Optional[List[Dict[str, Any]]],
        text_field: str,
        id_field: str,
        strategy: RetrievalStrategy,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        执行检索

        Args:
            query: 查询
            documents: 文档列表
            text_field: 文本字段
            id_field: ID 字段
            strategy: 检索策略
            **kwargs: 其他参数

        Returns:
            检索结果
        """
        from .hybrid import HybridSearchEngine, FusionStrategy

        vector_results = []
        bm25_results = []

        # 向量搜索
        if strategy.use_vector and self.vector_search_fn:
            vector_results = self.vector_search_fn(query, top_k=strategy.top_k * 2)

        # BM25 搜索
        if strategy.use_bm25 and self.bm25_index and documents:
            bm25_results = self.bm25_index.search_with_documents(
                query, documents, text_field, id_field, top_k=strategy.top_k * 2
            )

        # 混合融合
        if vector_results or bm25_results:
            hybrid_engine = HybridSearchEngine()
            results = hybrid_engine.search(
                query=query,
                vector_results=vector_results,
                bm25_results=bm25_results,
            )
        else:
            results = []

        # 重排序
        if strategy.use_rerank and self.reranker and results:
            docs_for_rerank = [
                {**r, "text": r.get(text_field, r.get("content", ""))}
                for r in results
            ]
            results = self.reranker.rerank(
                query=query,
                documents=docs_for_rerank,
                top_k=strategy.top_k,
            )

        # 时间权重提升
        if strategy.recency_boost:
            results = self._apply_recency_boost(results)

        # 过滤低分结果
        results = [
            r for r in results
            if r.get("hybrid_score", r.get("rerank_score", 0)) >= strategy.min_score
        ]

        return results[:strategy.top_k]

    def _apply_recency_boost(
        self,
        results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """应用时间权重提升"""
        import time

        current_time = time.time()
        decay = 0.98

        for result in results:
            timestamp = result.get("timestamp") or result.get("created_at")
            if timestamp:
                try:
                    if isinstance(timestamp, str):
                        from datetime import datetime
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp()

                    days_ago = (current_time - timestamp) / 86400
                    decay_factor = decay ** days_ago
                    score = result.get("hybrid_score", 0)
                    result["hybrid_score"] = score * decay_factor
                except:
                    pass

        results.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)
        return results

    def _record_query_complexity(
        self,
        query: str,
        query_type: QueryType,
        strategy: RetrievalStrategy
    ):
        """记录查询复杂度"""
        complexity = len(query.split()) / 20.0  # 简单复杂度计算

        self._query_complexity_history.append({
            "query": query,
            "type": query_type.value,
            "complexity": complexity,
            "top_k": strategy.top_k,
        })

        # 保持历史长度
        if len(self._query_complexity_history) > 100:
            self._query_complexity_history = self._query_complexity_history[-50:]


# ============= 便捷函数 =============

def create_adaptive_retrieval(
    use_rerank: bool = True,
    dynamic_top_k: bool = True,
) -> AdaptiveRetrieval:
    """
    创建自适应检索器

    Args:
        use_rerank: 是否使用重排序
        dynamic_top_k: 是否动态调整 top_k

    Returns:
        AdaptiveRetrieval 实例
    """
    config = AdaptiveConfig(
        query_type_detection=True,
        dynamic_top_k=dynamic_top_k,
    )
    return AdaptiveRetrieval(config=config)
