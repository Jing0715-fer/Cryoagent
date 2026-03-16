# metrics.py - 检索质量指标计算
"""
检索质量指标计算模块

实现标准检索评估指标：
- Precision@K
- Recall@K
- MRR (Mean Reciprocal Rank)
- NDCG@K (Normalized Discounted Cumulative Gain)
- MAP (Mean Average Precision)
"""

import math
from typing import List, Dict, Set, Optional
from dataclasses import dataclass, field


@dataclass
class RetrievalMetrics:
    """检索质量指标集合"""

    # Precision 指标
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0
    precision_at_20: float = 0.0

    # Recall 指标
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    recall_at_20: float = 0.0

    # 排序指标
    mrr: float = 0.0  # Mean Reciprocal Rank
    map_score: float = 0.0  # Mean Average Precision

    # NDCG 指标
    ndcg_at_5: float = 0.0
    ndcg_at_10: float = 0.0
    ndcg_at_20: float = 0.0

    # 统计信息
    total_queries: int = 0
    avg_latency_ms: float = 0.0

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'precision_at_5': self.precision_at_5,
            'precision_at_10': self.precision_at_10,
            'precision_at_20': self.precision_at_20,
            'recall_at_5': self.recall_at_5,
            'recall_at_10': self.recall_at_10,
            'recall_at_20': self.recall_at_20,
            'mrr': self.mrr,
            'map_score': self.map_score,
            'ndcg_at_5': self.ndcg_at_5,
            'ndcg_at_10': self.ndcg_at_10,
            'ndcg_at_20': self.ndcg_at_20,
            'total_queries': self.total_queries,
            'avg_latency_ms': self.avg_latency_ms,
        }


class MetricsCalculator:
    """检索指标计算器"""

    @staticmethod
    def precision_at_k(
        retrieved_ids: List[str],
        relevant_ids: Set[str],
        k: int
    ) -> float:
        """
        计算 Precision@K

        Precision@K = 前 K 个结果中相关文档数量 / K

        Args:
            retrieved_ids: 检索返回的文档 ID 列表（按相关性排序）
            relevant_ids: 相关文档 ID 集合
            k: 截断位置

        Returns:
            Precision@K 值
        """
        if k <= 0:
            return 0.0

        retrieved_at_k = set(retrieved_ids[:k])
        relevant_retrieved = retrieved_at_k & relevant_ids

        return len(relevant_retrieved) / k

    @staticmethod
    def recall_at_k(
        retrieved_ids: List[str],
        relevant_ids: Set[str],
        k: int
    ) -> float:
        """
        计算 Recall@K

        Recall@K = 前 K 个结果中命中的相关文档数量 / 总相关文档数量

        Args:
            retrieved_ids: 检索返回的文档 ID 列表（按相关性排序）
            relevant_ids: 相关文档 ID 集合
            k: 截断位置

        Returns:
            Recall@K 值
        """
        if not relevant_ids:
            return 0.0

        retrieved_at_k = set(retrieved_ids[:k])
        relevant_retrieved = retrieved_at_k & relevant_ids

        return len(relevant_retrieved) / len(relevant_ids)

    @staticmethod
    def mrr(
        retrieved_ids: List[str],
        relevant_ids: Set[str]
    ) -> float:
        """
        计算 MRR (Mean Reciprocal Rank)

        MRR = 1 / 第一个相关结果的排名
        如果没有相关结果，返回 0

        Args:
            retrieved_ids: 检索返回的文档 ID 列表（按相关性排序）
            relevant_ids: 相关文档 ID 集合

        Returns:
            MRR 值
        """
        for rank, doc_id in enumerate(retrieved_ids, start=1):
            if doc_id in relevant_ids:
                return 1.0 / rank

        return 0.0

    @staticmethod
    def average_precision(
        retrieved_ids: List[str],
        relevant_ids: Set[str]
    ) -> float:
        """
        计算 Average Precision (AP)

        AP = sum(Precision@k * rel(k)) / |R|
        其中 rel(k) = 1 如果第 k 个结果相关，否则为 0

        Args:
            retrieved_ids: 检索返回的文档 ID 列表（按相关性排序）
            relevant_ids: 相关文档 ID 集合

        Returns:
            AP 值
        """
        if not relevant_ids:
            return 0.0

        precision_sum = 0.0
        relevant_count = 0

        for k, doc_id in enumerate(retrieved_ids, start=1):
            if doc_id in relevant_ids:
                relevant_count += 1
                precision_at_k = relevant_count / k
                precision_sum += precision_at_k

        return precision_sum / len(relevant_ids)

    @staticmethod
    def dcg_at_k(
        retrieved_ids: List[str],
        relevance_scores: Dict[str, float],
        k: int
    ) -> float:
        """
        计算 DCG@K (Discounted Cumulative Gain)

        DCG@K = sum(rel_i / log2(i + 1)) for i = 1 to K

        Args:
            retrieved_ids: 检索返回的文档 ID 列表（按相关性排序）
            relevance_scores: 文档 ID 到相关性分数的映射
            k: 截断位置

        Returns:
            DCG@K 值
        """
        dcg = 0.0

        for i, doc_id in enumerate(retrieved_ids[:k], start=1):
            rel = relevance_scores.get(doc_id, 0.0)
            # 使用 log2(i+1) 作为折扣因子
            dcg += rel / math.log2(i + 1)

        return dcg

    @staticmethod
    def ndcg_at_k(
        retrieved_ids: List[str],
        relevance_scores: Dict[str, float],
        k: int
    ) -> float:
        """
        计算 NDCG@K (Normalized Discounted Cumulative Gain)

        NDCG@K = DCG@K / IDCG@K

        其中 IDCG 是理想情况下的 DCG（按相关性分数降序排列）

        Args:
            retrieved_ids: 检索返回的文档 ID 列表（按相关性排序）
            relevance_scores: 文档 ID 到相关性分数的映射
            k: 截断位置

        Returns:
            NDCG@K 值
        """
        # 计算 DCG
        dcg = MetricsCalculator.dcg_at_k(retrieved_ids, relevance_scores, k)

        # 计算 IDCG（理想情况）
        ideal_order = sorted(relevance_scores.values(), reverse=True)
        idcg = 0.0
        for i, rel in enumerate(ideal_order[:k], start=1):
            idcg += rel / math.log2(i + 1)

        if idcg == 0:
            return 0.0

        return dcg / idcg


def calculate_all_metrics(
    retrieved_ids: List[str],
    relevant_ids: Set[str],
    relevance_scores: Optional[Dict[str, float]] = None,
    k_values: List[int] = [5, 10, 20]
) -> RetrievalMetrics:
    """
    计算所有检索指标

    Args:
        retrieved_ids: 检索返回的文档 ID 列表（按相关性排序）
        relevant_ids: 相关文档 ID 集合
        relevance_scores: 可选的文档 ID 到相关性分数的映射（用于 NDCG）
        k_values: 要计算的 K 值列表

    Returns:
        RetrievalMetrics 对象
    """
    metrics = RetrievalMetrics()

    # 计算 Precision@K 和 Recall@K
    for k in k_values:
        precision = MetricsCalculator.precision_at_k(retrieved_ids, relevant_ids, k)
        recall = MetricsCalculator.recall_at_k(retrieved_ids, relevant_ids, k)

        if k == 5:
            metrics.precision_at_5 = precision
            metrics.recall_at_5 = recall
        elif k == 10:
            metrics.precision_at_10 = precision
            metrics.recall_at_10 = recall
        elif k == 20:
            metrics.precision_at_20 = precision
            metrics.recall_at_20 = recall

    # 计算 MRR
    metrics.mrr = MetricsCalculator.mrr(retrieved_ids, relevant_ids)

    # 计算 MAP
    metrics.map_score = MetricsCalculator.average_precision(retrieved_ids, relevant_ids)

    # 计算 NDCG（如果提供了相关性分数）
    if relevance_scores:
        for k in k_values:
            ndcg = MetricsCalculator.ndcg_at_k(retrieved_ids, relevance_scores, k)

            if k == 5:
                metrics.ndcg_at_5 = ndcg
            elif k == 10:
                metrics.ndcg_at_10 = ndcg
            elif k == 20:
                metrics.ndcg_at_20 = ndcg
    else:
        # 如果没有相关性分数，使用二元相关性（相关=1，不相关=0）
        binary_scores = {doc_id: 1.0 for doc_id in relevant_ids}
        for k in k_values:
            ndcg = MetricsCalculator.ndcg_at_k(retrieved_ids, binary_scores, k)

            if k == 5:
                metrics.ndcg_at_5 = ndcg
            elif k == 10:
                metrics.ndcg_at_10 = ndcg
            elif k == 20:
                metrics.ndcg_at_20 = ndcg

    return metrics


def aggregate_metrics(
    all_metrics: List[RetrievalMetrics]
) -> RetrievalMetrics:
    """
    聚合多个查询的指标

    计算所有查询的平均指标值

    Args:
        all_metrics: 各查询的 RetrievalMetrics 列表

    Returns:
        聚合后的 RetrievalMetrics
    """
    if not all_metrics:
        return RetrievalMetrics()

    n = len(all_metrics)
    aggregated = RetrievalMetrics(total_queries=n)

    for m in all_metrics:
        aggregated.precision_at_5 += m.precision_at_5
        aggregated.precision_at_10 += m.precision_at_10
        aggregated.precision_at_20 += m.precision_at_20
        aggregated.recall_at_5 += m.recall_at_5
        aggregated.recall_at_10 += m.recall_at_10
        aggregated.recall_at_20 += m.recall_at_20
        aggregated.mrr += m.mrr
        aggregated.map_score += m.map_score
        aggregated.ndcg_at_5 += m.ndcg_at_5
        aggregated.ndcg_at_10 += m.ndcg_at_10
        aggregated.ndcg_at_20 += m.ndcg_at_20
        aggregated.avg_latency_ms += m.avg_latency_ms

    # 计算平均值
    aggregated.precision_at_5 /= n
    aggregated.precision_at_10 /= n
    aggregated.precision_at_20 /= n
    aggregated.recall_at_5 /= n
    aggregated.recall_at_10 /= n
    aggregated.recall_at_20 /= n
    aggregated.mrr /= n
    aggregated.map_score /= n
    aggregated.ndcg_at_5 /= n
    aggregated.ndcg_at_10 /= n
    aggregated.ndcg_at_20 /= n
    aggregated.avg_latency_ms /= n

    return aggregated