# evaluation.py - 蛋白质评估API路由
"""
蛋白质评估API端点
"""

import os
import sys
from flask import Blueprint, jsonify, request, render_template
import logging

logger = logging.getLogger(__name__)

# 创建蓝图
bp = Blueprint('evaluation', __name__, url_prefix='/api/evaluation')

# 导入评估服务
from core.protein_evaluation import get_evaluation_service


@bp.route('', methods=['GET'])
def list_evaluations():
    """列出所有蛋白质评估"""
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        service = get_evaluation_service()
        result = service.list_evaluations(limit=limit, offset=offset)
        return jsonify(result)
    except Exception as e:
        logger.error(f"列出评估失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/search', methods=['GET'])
def search_evaluations():
    """搜索蛋白质评估"""
    try:
        query = request.args.get('q', '')
        if not query:
            return jsonify({'success': False, 'error': '请提供搜索关键词'})

        service = get_evaluation_service()
        result = service.search_evaluations(query)
        return jsonify(result)
    except Exception as e:
        logger.error(f"搜索评估失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/start', methods=['POST'])
def start_evaluation():
    """开始新的蛋白质评估"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '请求体不能为空'}), 400

        uniprot_id = data.get('uniprot_id', '').strip()
        if not uniprot_id:
            return jsonify({'success': False, 'error': '请提供UniProt ID'}), 400

        gene_name = data.get('gene_name')
        protein_name = data.get('protein_name')

        # Get config options
        config = data.get('config', {})

        service = get_evaluation_service()
        result = service.start_evaluation(
            uniprot_id=uniprot_id,
            gene_name=gene_name,
            protein_name=protein_name,
            config=config
        )

        if result.get('success'):
            return jsonify(result), 202
        else:
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"启动评估失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:evaluation_id>', methods=['GET'])
def get_evaluation(evaluation_id):
    """获取特定评估的详细信息"""
    try:
        service = get_evaluation_service()
        result = service.get_evaluation_status(evaluation_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"获取评估失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:evaluation_id>/status', methods=['GET'])
def get_evaluation_status(evaluation_id):
    """获取评估状态（用于轮询）"""
    try:
        service = get_evaluation_service()
        result = service.get_evaluation_status(evaluation_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"获取评估状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:evaluation_id>', methods=['DELETE'])
def delete_evaluation(evaluation_id):
    """删除评估记录"""
    try:
        service = get_evaluation_service()
        result = service.delete_evaluation(evaluation_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"删除评估失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== HTML页面路由 ==========

@bp.route('/page')
def evaluation_page():
    """蛋白质评估页面"""
    return render_template('evaluation.html')
