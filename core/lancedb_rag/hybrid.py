# hybrid.py - 混合搜索引擎
"""
混合搜索引擎模块

实现多种混合检索策略:
- RRF (Reciprocal Rank Fusion)
- 加权融合
- COIL
"""

import logging
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
import numpy as np
from enum import Enum

logger = logging.getLogger(__name__)


# ============= 融合策略 =============

class FusionStrategy(Enum):
    """融合策略类型"""
    RRF = "rrf"  # Reciprocal Rank Fusion
    WEIGHTED = "weighted"  # 加权融合
    COIL = "coil"  # Contextualized Inverse Index Ranking
    SIMPLE_ADD = "simple_add"  # 简单相加


@dataclass
class HybridSearchConfig:
    """混合搜索配置"""
    vector_weight: float = 0.5  # 向量搜索权重
    bm25_weight: float = 0.5  # BM25 搜索权重
    fusion_strategy: FusionStrategy = FusionStrategy.RRF
    rrf_k: int = 60  # RRF 参数
    min_score: float = 0.0  # 最小分数阈值
    top_k: int = 10  # 返回结果数量
    use_rerank: bool = False  # 是否使用重排序
    recency_boost: bool = False  # 是否启用时间权重提升
    recency_decay: float = 0.98  # 时间衰减因子
    length_normalize: bool = True  # 是否进行长度归一化


class HybridSearchEngine:
    """
    混合搜索引擎

    结合向量搜索和 BM25 全文搜索，提供多种融合策略
    """

    def __init__(
        self,
        config: Optional[HybridSearchConfig] = None,
        vector_search_fn: Optional[Callable] = None,
        bm25_index: Optional[Any] = None,
    ):
        """
        初始化混合搜索引擎

        Args:
            config: 混合搜索配置
            vector_search_fn: 向量搜索函数
            bm25_index: BM25 索引
        """
        self.config = config or HybridSearchConfig()
        self.vector_search_fn = vector_search_fn
        self.bm25_index = bm25_index

    def search(
        self,
        query: str,
        vector_results: Optional[List[Dict[str, Any]]] = None,
        bm25_results: Optional[List[Dict[str, Any]]] = None,
        documents: Optional[List[Dict[str, Any]]] = None,
        text_field: str = "text",
        id_field: str = "id",
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        混合搜索

        Args:
            query: 查询文本
            vector_results: 预计算的向量搜索结果
            bm25_results: 预计算的 BM25 搜索结果
            documents: 完整文档列表（用于计算）
            text_field: 文本字段名
            id_field: ID 字段名
            **kwargs: 其他搜索参数

        Returns:
            混合搜索结果
        """
        # 获取向量搜索结果
        if vector_results is None:
            if self.vector_search_fn:
                vector_results = self.vector_search_fn(query, **kwargs)
            else:
                vector_results = []

        # 获取 BM25 搜索结果
        if bm25_results is None:
            if self.bm25_index and documents:
                bm25_results = self.bm25_index.search_with_documents(
                    query, documents, text_field, id_field
                )
            else:
                bm25_results = []

        # 融合结果
        if self.config.fusion_strategy == FusionStrategy.RRF:
            results = self._rrf_fusion(vector_results, bm25_results)
        elif self.config.fusion_strategy == FusionStrategy.WEIGHTED:
            results = self._weighted_fusion(vector_results, bm25_results)
        elif self.config.fusion_strategy == FusionStrategy.SIMPLE_ADD:
            results = self._simple_add_fusion(vector_results, bm25_results)
        else:
            results = self._rrf_fusion(vector_results, bm25_results)

        # 应用时间权重提升
        if self.config.recency_boost:
            results = self._apply_recency_boost(results)

        # 长度归一化
        if self.config.length_normalize:
            results = self._apply_length_normalization(results)

        # 过滤低分结果
        results = [
            r for r in results
            if r.get("hybrid_score", 0) >= self.config.min_score
        ]

        # 返回 top_k
        return results[:self.config.top_k]

    def _rrf_fusion(
        self,
        vector_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        倒数排名融合 (RRF)

        RRF 分数 = Σ 1 / (k + rank)
        """
        scores: Dict[str, float] = {}
        doc_map: Dict[str, Dict[str, Any]] = {}

        k = self.config.rrf_k

        # 融合向量搜索结果
        for rank, result in enumerate(vector_results):
            doc_id = str(result.get("doc_id") or result.get("id", rank))
            if doc_id not in doc_map:
                doc_map[doc_id] = result.copy()
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)

        # 融合 BM25 结果
        for rank, result in enumerate(bm25_results):
            doc_id = str(result.get("doc_id") or result.get("id", rank))
            if doc_id not in doc_map:
                doc_map[doc_id] = result.copy()
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)

        # 构建最终结果
        results = [
            {**doc_map[doc_id], "hybrid_score": score, "doc_id": doc_id}
            for doc_id, score in scores.items()
        ]
        results.sort(key=lambda x: x["hybrid_score"], reverse=True)

        return results

    def _weighted_fusion(
        self,
        vector_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        加权融合

        将向量搜索和 BM25 的分数按权重相加
        """
        scores: Dict[str, float] = {}
        doc_map: Dict[str, Dict[str, Any]] = {}

        # 归一化向量分数
        if vector_results:
            max_vec_score = max(r.get("score", 0) for r in vector_results) or 1
            for result in vector_results:
                doc_id = str(result.get("doc_id") or result.get("id"))
                if doc_id not in doc_map:
                    doc_map[doc_id] = result.copy()
                vec_score = result.get("score", 0) / max_vec_score
                scores[doc_id] = scores.get(doc_id, 0) + vec_score * self.config.vector_weight

        # 归一化 BM25 分数
        if bm25_results:
            max_bm25_score = max(r.get("bm25_score", r.get("score", 0)) for r in bm25_results) or 1
            for result in bm25_results:
                doc_id = str(result.get("doc_id") or result.get("id"))
                if doc_id not in doc_map:
                    doc_map[doc_id] = result.copy()
                bm25_score = result.get("bm25_score", result.get("score", 0)) / max_bm25_score
                scores[doc_id] = scores.get(doc_id, 0) + bm25_score * self.config.bm25_weight

        # 构建最终结果
        results = [
            {**doc_map[doc_id], "hybrid_score": score, "doc_id": doc_id}
            for doc_id, score in scores.items()
        ]
        results.sort(key=lambda x: x["hybrid_score"], reverse=True)

        return results

    def _simple_add_fusion(
        self,
        vector_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        简单相加融合

        将两个结果集合并，相加相同文档的分数
        """
        scores: Dict[str, float] = {}
        doc_map: Dict[str, Dict[str, Any]] = {}

        # 添加向量分数
        for result in vector_results:
            doc_id = str(result.get("doc_id") or result.get("id"))
            if doc_id not in doc_map:
                doc_map[doc_id] = result.copy()
            scores[doc_id] = scores.get(doc_id, 0) + result.get("score", 0)

        # 添加 BM25 分数
        for result in bm25_results:
            doc_id = str(result.get("doc_id") or result.get("id"))
            if doc_id not in doc_map:
                doc_map[doc_id] = result.copy()
            scores[doc_id] = scores.get(doc_id, 0) + result.get("bm25_score", result.get("score", 0))

        # 构建最终结果
        results = [
            {**doc_map[doc_id], "hybrid_score": score, "doc_id": doc_id}
            for doc_id, score in scores.items()
        ]
        results.sort(key=lambda x: x["hybrid_score"], reverse=True)

        return results

    def _apply_recency_boost(
        self,
        results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        应用时间权重提升

        较新的文档获得更高的分数
        """
        import time
        current_time = time.time()

        for result in results:
            # 尝试获取时间戳
            timestamp = result.get("timestamp") or result.get("created_at")
            if timestamp:
                # 转换时间戳
                if isinstance(timestamp, str):
                    try:
                        from datetime import datetime
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp()
                    except:
                        timestamp = current_time
                elif isinstance(timestamp, (int, float)):
                    timestamp = timestamp

                # 计算时间差（天）
                days_ago = (current_time - timestamp) / 86400

                # 应用衰减
                decay = self.config.recency_decay ** days_ago

                # 更新分数
                result["hybrid_score"] = result.get("hybrid_score", 0) * decay

        # 重新排序
        results.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)

        return results

    def _apply_length_normalization(
        self,
        results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        应用长度归一化

        使用 BM25 风格的长度归一化
        """
        for result in results:
            text = result.get("text", "")
            if text:
                # 简单归一化：分数除以文档长度的平方根
                length = len(text.split())
                if length > 0:
                    # 使用类似 BM25 的归一化
                    normalized = 1.0 / (1 + np.log1p(length))
                    result["hybrid_score"] = result.get("hybrid_score", 0) * normalized

        return results


# ============= 便捷函数 =============

def create_hybrid_engine(
    vector_weight: float = 0.5,
    bm25_weight: float = 0.5,
    strategy: FusionStrategy = FusionStrategy.RRF,
    **kwargs
) -> HybridSearchEngine:
    """
    创建混合搜索引擎的便捷函数

    Args:
        vector_weight: 向量权重
        bm25_weight: BM25 权重
        strategy: 融合策略
        **kwargs: 其他配置参数

    Returns:
        HybridSearchEngine 实例
    """
    config = HybridSearchConfig(
        vector_weight=vector_weight,
        bm25_weight=bm25_weight,
        fusion_strategy=strategy,
        **kwargs
    )
    return HybridSearchEngine(config=config)
