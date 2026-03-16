# rag_evaluation - RAG 评估模块
"""
RAG 检索质量评估模块

提供检索质量评估功能：
- Precision@K, Recall@K
- MRR (Mean Reciprocal Rank)
- NDCG@K (Normalized Discounted Cumulative Gain)
- Ground Truth 管理
- 评估结果存储
- 在线监控
"""

from .metrics import RetrievalMetrics, calculate_all_metrics
from .evaluator import RAGEvaluator, EvaluationConfig
from .ground_truth import GroundTruthManager, GroundTruthEntry
from .storage import EvaluationStorage, EvaluationRun, EvaluationResult
from .monitor import SearchMonitor, SearchLog

__all__ = [
    'RetrievalMetrics',
    'calculate_all_metrics',
    'RAGEvaluator',
    'EvaluationConfig',
    'GroundTruthManager',
    'GroundTruthEntry',
    'EvaluationStorage',
    'EvaluationRun',
    'EvaluationResult',
    'SearchMonitor',
    'SearchLog',
]

__version__ = '1.0.0'