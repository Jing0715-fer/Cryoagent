# routes/rag_evaluation.py - RAG 评估 API 路由
"""
RAG 评估 API 路由

提供 REST API 端点：
- Ground Truth 管理
- 执行评估
- 查看评估历史
- 监控统计
"""

import logging
from flask import Blueprint, request, jsonify, current_app
from typing import Dict, Any

from core.rag_evaluation import (
    RAGEvaluator,
    EvaluationConfig,
    GroundTruthManager,
    EvaluationStorage,
    SearchMonitor,
)
from core.rag_evaluation.evaluator import create_evaluator
from core.rag_evaluation.monitor import get_search_monitor

logger = logging.getLogger(__name__)

bp = Blueprint('rag_evaluation', __name__, url_prefix='/api/rag/evaluation')

# 全局实例
_storage: EvaluationStorage = None
_ground_truth_manager: GroundTruthManager = None
_evaluator: RAGEvaluator = None
_monitor: SearchMonitor = None


def get_storage() -> EvaluationStorage:
    """获取存储实例"""
    global _storage
    if _storage is None:
        _storage = EvaluationStorage()
    return _storage


def get_ground_truth_manager() -> GroundTruthManager:
    """获取 Ground Truth 管理器"""
    global _ground_truth_manager
    if _ground_truth_manager is None:
        _ground_truth_manager = GroundTruthManager(get_storage())
    return _ground_truth_manager


def get_evaluator() -> RAGEvaluator:
    """获取评估器"""
    global _evaluator
    if _evaluator is None:
        # 尝试使用 LanceDB RAG 系统
        try:
            from core.lancedb_rag import get_unified_rag
            rag = get_unified_rag()
            _evaluator = create_evaluator(rag_system=rag, storage_path=None)
        except Exception as e:
            logger.error(f"创建评估器失败: {e}")
            raise
    return _evaluator


def get_monitor() -> SearchMonitor:
    """获取监控器"""
    global _monitor
    if _monitor is None:
        _monitor = get_search_monitor(storage=get_storage())
    return _monitor


# ============= Ground Truth API =============

@bp.route('/ground-truth', methods=['GET'])
def list_ground_truth():
    """列出所有 Ground Truth"""
    try:
        manager = get_ground_truth_manager()
        entries = manager.get_all_entries()

        return jsonify({
            'success': True,
            'data': [e.to_dict() for e in entries],
            'total': len(entries),
        })
    except Exception as e:
        logger.error(f"获取 Ground Truth 列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/ground-truth', methods=['POST'])
def add_ground_truth():
    """添加 Ground Truth"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        required_fields = ['query_text', 'relevant_ids']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing field: {field}'}), 400

        manager = get_ground_truth_manager()
        entry = manager.add_entry(
            query_text=data['query_text'],
            relevant_ids=data['relevant_ids'],
            relevance_scores=data.get('relevance_scores'),
            category=data.get('category'),
            notes=data.get('notes'),
        )

        return jsonify({
            'success': True,
            'data': entry.to_dict(),
        }), 201
    except Exception as e:
        logger.error(f"添加 Ground Truth 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/ground-truth/<query_id>', methods=['GET'])
def get_ground_truth(query_id: str):
    """获取单个 Ground Truth"""
    try:
        manager = get_ground_truth_manager()
        entry = manager.get_entry(query_id)

        if not entry:
            return jsonify({'success': False, 'error': 'Not found'}), 404

        return jsonify({
            'success': True,
            'data': entry.to_dict(),
        })
    except Exception as e:
        logger.error(f"获取 Ground Truth 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/ground-truth/<query_id>', methods=['DELETE'])
def delete_ground_truth(query_id: str):
    """删除 Ground Truth"""
    try:
        manager = get_ground_truth_manager()
        success = manager.delete_entry(query_id)

        return jsonify({
            'success': success,
        })
    except Exception as e:
        logger.error(f"删除 Ground Truth 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/ground-truth/sample', methods=['POST'])
def create_sample_dataset():
    """创建示例数据集"""
    try:
        manager = get_ground_truth_manager()
        entries = manager.create_sample_dataset()

        return jsonify({
            'success': True,
            'data': [e.to_dict() for e in entries],
            'total': len(entries),
        })
    except Exception as e:
        logger.error(f"创建示例数据集失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============= 评估 API =============

@bp.route('/run', methods=['POST'])
def run_evaluation():
    """执行评估"""
    try:
        data = request.get_json() or {}

        config = EvaluationConfig(
            top_k=data.get('top_k', 10),
            search_type=data.get('search_type', 'hybrid'),
            use_rerank=data.get('use_rerank', False),
            run_name=data.get('name', ''),
        )

        evaluator = get_evaluator()
        result = evaluator.evaluate_dataset(config=config)

        return jsonify({
            'success': True,
            'data': {
                'run_id': result['run_id'],
                'metrics': result['metrics'].to_dict(),
                'query_count': len(result['results']),
            },
        })
    except Exception as e:
        logger.error(f"执行评估失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/run/<run_id>', methods=['GET'])
def get_evaluation_run(run_id: str):
    """获取评估运行详情"""
    try:
        evaluator = get_evaluator()
        details = evaluator.get_run_details(run_id)

        if not details:
            return jsonify({'success': False, 'error': 'Not found'}), 404

        return jsonify({
            'success': True,
            'data': details,
        })
    except Exception as e:
        logger.error(f"获取评估运行失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/runs', methods=['GET'])
def list_evaluation_runs():
    """列出评估运行"""
    try:
        limit = request.args.get('limit', 20, type=int)
        evaluator = get_evaluator()
        runs = evaluator.list_runs(limit)

        return jsonify({
            'success': True,
            'data': runs,
            'total': len(runs),
        })
    except Exception as e:
        logger.error(f"列出评估运行失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/run/<run_id>', methods=['DELETE'])
def delete_evaluation_run(run_id: str):
    """删除评估运行"""
    try:
        evaluator = get_evaluator()
        success = evaluator.delete_run(run_id)

        return jsonify({
            'success': success,
        })
    except Exception as e:
        logger.error(f"删除评估运行失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/compare', methods=['POST'])
def compare_runs():
    """比较评估运行"""
    try:
        data = request.get_json()
        run_ids = data.get('run_ids', [])

        if len(run_ids) < 2:
            return jsonify({'success': False, 'error': 'Need at least 2 runs to compare'}), 400

        evaluator = get_evaluator()
        result = evaluator.compare_runs(run_ids)

        return jsonify({
            'success': True,
            'data': result,
        })
    except Exception as e:
        logger.error(f"比较评估运行失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============= 监控 API =============

@bp.route('/monitor/stats', methods=['GET'])
def get_monitor_stats():
    """获取监控统计"""
    try:
        days = request.args.get('days', 7, type=int)
        monitor = get_monitor()

        # 获取内存中的统计
        mem_stats = monitor.get_stats()

        # 获取数据库中的统计
        storage = get_storage()
        db_stats = storage.get_search_stats(days)

        return jsonify({
            'success': True,
            'data': {
                'memory': mem_stats,
                'database': db_stats,
            },
        })
    except Exception as e:
        logger.error(f"获取监控统计失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/monitor/hourly', methods=['GET'])
def get_hourly_stats():
    """获取每小时统计"""
    try:
        hours = request.args.get('hours', 24, type=int)
        monitor = get_monitor()
        stats = monitor.get_hourly_stats(hours)

        return jsonify({
            'success': True,
            'data': stats,
        })
    except Exception as e:
        logger.error(f"获取每小时统计失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/monitor/anomalies', methods=['GET'])
def detect_anomalies():
    """检测异常"""
    try:
        monitor = get_monitor()
        anomalies = monitor.detect_anomalies()

        return jsonify({
            'success': True,
            'data': anomalies,
        })
    except Exception as e:
        logger.error(f"检测异常失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/monitor/popular', methods=['GET'])
def get_popular_queries():
    """获取热门查询"""
    try:
        limit = request.args.get('limit', 10, type=int)
        monitor = get_monitor()
        queries = monitor.get_popular_queries(limit)

        return jsonify({
            'success': True,
            'data': queries,
        })
    except Exception as e:
        logger.error(f"获取热门查询失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============= 单查询测试 API =============

@bp.route('/test', methods=['POST'])
def test_single_query():
    """测试单个查询"""
    try:
        data = request.get_json()
        if not data or 'query' not in data:
            return jsonify({'success': False, 'error': 'Query required'}), 400

        query = data['query']
        relevant_ids = data.get('relevant_ids', [])
        top_k = data.get('top_k', 10)

        evaluator = get_evaluator()
        result = evaluator.evaluate_single(
            query_text=query,
            relevant_ids=relevant_ids,
            config=EvaluationConfig(top_k=top_k),
        )

        return jsonify({
            'success': True,
            'data': {
                'query': query,
                'retrieved_ids': result['retrieved_ids'],
                'metrics': result['metrics'].to_dict(),
                'latency_ms': result['latency_ms'],
            },
        })
    except Exception as e:
        logger.error(f"测试查询失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def register_routes(app):
    """注册路由到 Flask 应用"""
    app.register_blueprint(bp)
    logger.info("RAG 评估 API 路由已注册")