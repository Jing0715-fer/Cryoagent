# evaluator.py - RAG 评估器
"""
RAG 评估器主模块

提供完整的 RAG 检索评估功能：
- 执行评估运行
- 计算检索指标
- 存储评估结果
- 比较不同配置
"""

import time
import logging
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
import uuid

from .metrics import RetrievalMetrics, calculate_all_metrics, aggregate_metrics
from .ground_truth import GroundTruthManager, GroundTruthEntry
from .storage import EvaluationStorage, EvaluationRun, EvaluationResult

logger = logging.getLogger(__name__)


@dataclass
class EvaluationConfig:
    """评估配置"""

    # 检索配置
    top_k: int = 10
    search_type: str = "hybrid"  # "vector" | "bm25" | "hybrid"
    use_rerank: bool = True

    # 评估配置
    k_values: List[int] = field(default_factory=lambda: [5, 10, 20])

    # 存储配置
    save_results: bool = True
    run_name: str = ""

    def to_dict(self) -> Dict:
        return {
            'top_k': self.top_k,
            'search_type': self.search_type,
            'use_rerank': self.use_rerank,
            'k_values': self.k_values,
            'save_results': self.save_results,
        }


class RAGEvaluator:
    """RAG 评估器"""

    def __init__(
        self,
        search_fn: Callable[[str, int, Dict], List[Dict]],
        storage: Optional[EvaluationStorage] = None,
        ground_truth_manager: Optional[GroundTruthManager] = None,
    ):
        """
        初始化评估器

        Args:
            search_fn: 搜索函数，签名为 (query: str, top_k: int, config: Dict) -> List[Dict]
                       返回格式: [{"id": "...", "score": 0.9, ...}, ...]
            storage: 评估存储后端
            ground_truth_manager: Ground Truth 管理器
        """
        self.search_fn = search_fn
        self.storage = storage or EvaluationStorage()
        self.ground_truth_manager = ground_truth_manager or GroundTruthManager(self.storage)

    def evaluate_single(
        self,
        query_text: str,
        relevant_ids: List[str],
        relevance_scores: Optional[Dict[str, float]] = None,
        config: Optional[EvaluationConfig] = None,
    ) -> Dict[str, Any]:
        """
        评估单个查询

        Args:
            query_text: 查询文本
            relevant_ids: 相关文档 ID 列表
            relevance_scores: 可选的相关性分数映射
            config: 评估配置

        Returns:
            包含检索结果和指标的字典
        """
        config = config or EvaluationConfig()

        # 执行检索
        start_time = time.time()
        search_results = self.search_fn(
            query_text,
            config.top_k,
            {
                'search_type': config.search_type,
                'use_rerank': config.use_rerank,
            }
        )
        latency_ms = (time.time() - start_time) * 1000

        # 提取检索 ID
        retrieved_ids = [r.get('id') or r.get('document', {}).get('id') for r in search_results]
        retrieved_ids = [rid for rid in retrieved_ids if rid]  # 过滤 None

        # 计算指标
        metrics = calculate_all_metrics(
            retrieved_ids=retrieved_ids,
            relevant_ids=set(relevant_ids),
            relevance_scores=relevance_scores,
            k_values=config.k_values,
        )
        metrics.avg_latency_ms = latency_ms
        metrics.total_queries = 1

        return {
            'query_text': query_text,
            'retrieved_ids': retrieved_ids,
            'relevant_ids': relevant_ids,
            'search_results': search_results,
            'metrics': metrics,
            'latency_ms': latency_ms,
        }

    def evaluate_dataset(
        self,
        ground_truth_entries: Optional[List[GroundTruthEntry]] = None,
        config: Optional[EvaluationConfig] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Any]:
        """
        评估整个数据集

        Args:
            ground_truth_entries: Ground Truth 条目列表（如果为 None，使用所有已存储的条目）
            config: 评估配置
            progress_callback: 进度回调函数 (current, total)

        Returns:
            包含总体指标和各查询结果的字典
        """
        config = config or EvaluationConfig()

        # 获取 Ground Truth
        if ground_truth_entries is None:
            ground_truth_entries = self.ground_truth_manager.get_all_entries()

        if not ground_truth_entries:
            logger.warning("没有可用的 Ground Truth 数据")
            return {
                'metrics': RetrievalMetrics(),
                'results': [],
                'run_id': None,
            }

        # 创建评估运行
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        run = EvaluationRun(
            run_id=run_id,
            name=config.run_name or f"Evaluation {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            config=config.to_dict(),
        )

        # 执行评估
        all_metrics = []
        results = []

        total = len(ground_truth_entries)
        for i, entry in enumerate(ground_truth_entries):
            result = self.evaluate_single(
                query_text=entry.query_text,
                relevant_ids=entry.relevant_ids,
                relevance_scores=entry.relevance_scores,
                config=config,
            )

            all_metrics.append(result['metrics'])

            # 创建结果记录
            eval_result = EvaluationResult(
                run_id=run_id,
                query_id=entry.query_id,
                query_text=entry.query_text,
                retrieved_ids=result['retrieved_ids'],
                relevant_ids=entry.relevant_ids,
                precision_at_5=result['metrics'].precision_at_5,
                precision_at_10=result['metrics'].precision_at_10,
                recall_at_5=result['metrics'].recall_at_5,
                recall_at_10=result['metrics'].recall_at_10,
                mrr=result['metrics'].mrr,
                ndcg_at_10=result['metrics'].ndcg_at_10,
                latency_ms=result['latency_ms'],
            )
            results.append(eval_result)

            # 保存结果
            if config.save_results and self.storage:
                self.storage.save_result(eval_result)

            # 进度回调
            if progress_callback:
                progress_callback(i + 1, total)

        # 聚合指标
        aggregated = aggregate_metrics(all_metrics)

        # 更新运行记录
        run.metrics_summary = aggregated.to_dict()
        run.query_count = total

        if config.save_results and self.storage:
            self.storage.save_run(run)

        return {
            'run_id': run_id,
            'metrics': aggregated,
            'results': results,
            'config': config.to_dict(),
        }

    def compare_runs(
        self,
        run_ids: List[str]
    ) -> Dict[str, Any]:
        """
        比较多次评估运行

        Args:
            run_ids: 运行 ID 列表

        Returns:
            比较结果
        """
        if not self.storage:
            return {'error': 'Storage not configured'}

        runs_data = []
        for run_id in run_ids:
            run = self.storage.load_run(run_id)
            if run:
                results = self.storage.load_results(run_id)
                runs_data.append({
                    'run_id': run_id,
                    'name': run.name,
                    'created_at': run.created_at,
                    'config': run.config,
                    'metrics': run.metrics_summary,
                    'query_count': run.query_count,
                })

        # 找出最佳配置
        best_by_metric = {}
        metric_keys = ['precision_at_10', 'recall_at_10', 'mrr', 'ndcg_at_10']

        for key in metric_keys:
            best_run = max(runs_data, key=lambda r: r['metrics'].get(key, 0))
            best_by_metric[key] = {
                'run_id': best_run['run_id'],
                'name': best_run['name'],
                'value': best_run['metrics'].get(key, 0),
            }

        return {
            'runs': runs_data,
            'best_by_metric': best_by_metric,
        }

    def get_run_details(self, run_id: str) -> Optional[Dict[str, Any]]:
        """获取评估运行详情"""
        if not self.storage:
            return None

        run = self.storage.load_run(run_id)
        if not run:
            return None

        results = self.storage.load_results(run_id)

        return {
            'run': run.to_dict(),
            'results': [r.to_dict() for r in results],
        }

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """列出评估运行"""
        if not self.storage:
            return []

        runs = self.storage.list_runs(limit)
        return [r.to_dict() for r in runs]

    def delete_run(self, run_id: str) -> bool:
        """删除评估运行"""
        if not self.storage:
            return False

        return self.storage.delete_run(run_id)


def create_evaluator(
    rag_system=None,
    storage_path: Optional[str] = None,
) -> RAGEvaluator:
    """
    创建 RAG 评估器的便捷函数

    Args:
        rag_system: UnifiedLanceRAG 或兼容的 RAG 系统
        storage_path: 存储路径

    Returns:
        配置好的 RAGEvaluator 实例
    """
    # 创建搜索函数
    def search_fn(query: str, top_k: int, config: Dict) -> List[Dict]:
        if rag_system is None:
            return []

        result = rag_system.search(
            query=query,
            top_k=top_k,
            search_type=config.get('search_type', 'hybrid'),
            use_rerank=config.get('use_rerank', False),
        )
        return result.get('results', [])

    # 创建存储
    storage = EvaluationStorage(db_path=storage_path) if storage_path else EvaluationStorage()

    return RAGEvaluator(
        search_fn=search_fn,
        storage=storage,
    )