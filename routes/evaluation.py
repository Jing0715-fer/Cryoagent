# evaluation.py - 蛋白质评估API路由
"""
蛋白质评估API端点
"""

import os
import sys
import re
from flask import Blueprint, jsonify, request, render_template
import logging
import config

logger = logging.getLogger(__name__)

# 创建蓝图
bp = Blueprint('evaluation', __name__, url_prefix='/api/evaluation')

# 导入评估服务
from core.protein_evaluation import get_evaluation_service
from core.batch_evaluation import get_batch_evaluation_service


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


@bp.route('/<int:evaluation_id>/prompt', methods=['GET'])
def get_evaluation_prompt(evaluation_id):
    """获取评估使用的prompt"""
    try:
        service = get_evaluation_service()
        result = service.get_evaluation_status(evaluation_id)
        if result.get('success'):
            evaluation = result.get('evaluation', {})
            prompt = evaluation.get('prompt', '')
            return jsonify({
                'success': True,
                'prompt': prompt
            })
        return jsonify({'success': False, 'error': result.get('error', '评估不存在')}), 404
    except Exception as e:
        logger.error(f"获取prompt失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== HTML页面路由 ==========

@bp.route('/page')
def evaluation_page():
    """蛋白质评估页面"""
    return render_template('evaluation.html')


# ========== 批量评估 API 端点 ==========

@bp.route('/batch-start', methods=['POST'])
def start_batch_evaluation():
    """开始批量蛋白质评估"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '请求体不能为空'}), 400

        uniprot_ids = data.get('uniprot_ids', [])
        if not uniprot_ids:
            # 尝试从文本输入解析
            uniprot_input = data.get('uniprot_ids_text', '')
            if uniprot_input:
                uniprot_ids = re.split(r'[,;\s\n]+', uniprot_input)
                uniprot_ids = [uid.strip().upper() for uid in uniprot_ids if uid.strip()]

        if not uniprot_ids or len(uniprot_ids) < 2:
            return jsonify({'success': False, 'error': '请提供至少2个UniProt ID'}), 400

        name = data.get('name')
        config_opt = data.get('config', {})

        service = get_batch_evaluation_service()
        result = service.start_batch_evaluation(
            uniprot_ids=uniprot_ids,
            name=name,
            config=config_opt
        )

        if result.get('success'):
            return jsonify(result), 202
        else:
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"启动批量评估失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/batch', methods=['GET'])
def list_batch_evaluations():
    """获取批量评估列表"""
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        service = get_batch_evaluation_service()
        result = service.list_batch_evaluations(limit=limit, offset=offset)
        return jsonify(result)
    except Exception as e:
        logger.error(f"获取批量评估列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/batch/<int:batch_id>', methods=['GET'])
def get_batch_evaluation(batch_id):
    """获取批量评估详情"""
    try:
        service = get_batch_evaluation_service()
        result = service.get_batch_evaluation_status(batch_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"获取批量评估详情失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/batch/<int:batch_id>/status', methods=['GET'])
def get_batch_evaluation_status(batch_id):
    """获取批量评估进度"""
    try:
        service = get_batch_evaluation_service()
        result = service.get_batch_evaluation_status(batch_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"获取批量评估状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/batch/<int:batch_id>', methods=['DELETE'])
def delete_batch_evaluation(batch_id):
    """删除批量评估"""
    try:
        service = get_batch_evaluation_service()
        result = service.delete_batch_evaluation(batch_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"删除批量评估失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 提示模板管理 ==========

@bp.route('/templates', methods=['GET'])
def get_templates():
    """获取单个蛋白评估模板"""
    from core.literature_db import get_all_prompt_templates, get_default_prompt_template, create_prompt_template

    templates = get_all_prompt_templates('single')
    default_template = get_default_prompt_template('single')

    # 如果没有模板，自动创建默认模板
    if not templates:
        default_content = """请分析以下蛋白质数据，评估其结构研究价值和潜在研究方向：

蛋白质信息：{protein_info}

PDB结构数据：{pdb_data}

同源搜索结果：{blast_results}

请提供：
1. 蛋白质功能概述
2. 结构研究现状评估
3. PDB覆盖度分析
4. 研究价值和建议"""
        template = create_prompt_template(
            name='默认分析模板',
            content=default_content,
            description='系统默认分析模板',
            is_default=True,
            template_type='single'
        )
        if template:
            templates = [template]
            default_template = template
            default_content = template.content
        else:
            default_content = ""

    return jsonify({
        'success': True,
        'templates': [t.to_dict() for t in templates],
        'default_id': default_template.id if default_template else None,
        'default_content': default_content
    })


@bp.route('/templates', methods=['POST'])
def create_template():
    """创建新模板"""
    from core.literature_db import create_prompt_template

    data = request.get_json()
    name = data.get('name')
    content = data.get('content')
    description = data.get('description', '')
    is_default = data.get('is_default', False)

    if not name or not content:
        return jsonify({'success': False, 'message': '模板名称和内容不能为空'}), 400

    template = create_prompt_template(name, content, description, is_default, 'single')
    if template:
        return jsonify({'success': True, 'template': template.to_dict()})
    return jsonify({'success': False, 'message': '创建模板失败'}), 500


@bp.route('/templates/<int:template_id>', methods=['PUT'])
def update_template(template_id):
    """更新模板"""
    from core.literature_db import update_prompt_template

    data = request.get_json()
    updates = {}

    if 'name' in data:
        updates['name'] = data['name']
    if 'content' in data:
        updates['content'] = data['content']
    if 'description' in data:
        updates['description'] = data['description']
    if 'is_default' in data:
        updates['is_default'] = data['is_default']

    if not updates:
        return jsonify({'success': False, 'message': '没有要更新的内容'}), 400

    if update_prompt_template(template_id, updates):
        return jsonify({'success': True, 'message': '模板已更新'})
    return jsonify({'success': False, 'message': '更新失败'}), 500


@bp.route('/templates/<int:template_id>', methods=['DELETE'])
def delete_template(template_id):
    """删除模板"""
    from core.literature_db import delete_prompt_template

    if delete_prompt_template(template_id):
        return jsonify({'success': True, 'message': '模板已删除'})
    return jsonify({'success': False, 'message': '删除失败'}), 500


@bp.route('/templates/<int:template_id>/set-default', methods=['POST'])
def set_default_template(template_id):
    """设置默认模板"""
    from core.literature_db import set_default_prompt_template

    if set_default_prompt_template(template_id):
        return jsonify({'success': True, 'message': '已设为默认模板'})
    return jsonify({'success': False, 'message': '设置失败'}), 500


# ========== 批量分析模板管理 ==========

@bp.route('/batch-templates', methods=['GET'])
def get_batch_templates():
    """获取批量分析模板"""
    from core.literature_db import get_all_prompt_templates, get_default_prompt_template, create_prompt_template

    templates = get_all_prompt_templates('batch')
    default_template = get_default_prompt_template('batch')

    # 如果没有模板，创建默认
    if not templates:
        default_content = """请分析以下蛋白质的相互作用关系和功能特征：

蛋白质列表：{uniprot_ids}

相互作用数据：{interaction_data}

各蛋白质单独评估报告：
{individual_reports}

请提供：
1. 这些蛋白质之间的相互作用网络分析
2. 功能相关性分析
3. 结构研究价值评估
4. 潜在的研究方向建议"""
        template = create_prompt_template(
            name='默认批量分析模板',
            content=default_content,
            description='系统默认批量关系分析模板',
            is_default=True,
            template_type='batch'
        )
        if template:
            templates = [template]
            default_template = template
            default_content = template.content
        else:
            default_content = ""

    return jsonify({
        'success': True,
        'templates': [t.to_dict() for t in templates],
        'default_id': default_template.id if default_template else None,
        'default_content': default_content
    })


@bp.route('/batch-templates', methods=['POST'])
def create_batch_template():
    """创建批量分析模板"""
    from core.literature_db import create_prompt_template

    data = request.get_json()
    name = data.get('name')
    content = data.get('content')
    description = data.get('description', '')
    is_default = data.get('is_default', False)

    if not name or not content:
        return jsonify({'success': False, 'message': '模板名称和内容不能为空'}), 400

    template = create_prompt_template(name, content, description, is_default, 'batch')
    if template:
        return jsonify({'success': True, 'template': template.to_dict()})
    return jsonify({'success': False, 'message': '创建模板失败'}), 500


@bp.route('/batch-templates/<int:template_id>', methods=['PUT'])
def update_batch_template(template_id):
    """更新批量分析模板"""
    from core.literature_db import update_prompt_template

    data = request.get_json()
    updates = {}

    if 'name' in data:
        updates['name'] = data['name']
    if 'content' in data:
        updates['content'] = data['content']
    if 'description' in data:
        updates['description'] = data['description']
    if 'is_default' in data:
        updates['is_default'] = data['is_default']

    if not updates:
        return jsonify({'success': False, 'message': '没有要更新的内容'}), 400

    if update_prompt_template(template_id, updates):
        return jsonify({'success': True, 'message': '模板已更新'})
    return jsonify({'success': False, 'message': '更新失败'}), 500


@bp.route('/batch-templates/<int:template_id>', methods=['DELETE'])
def delete_batch_template(template_id):
    """删除批量分析模板"""
    from core.literature_db import delete_prompt_template

    if delete_prompt_template(template_id):
        return jsonify({'success': True, 'message': '模板已删除'})
    return jsonify({'success': False, 'message': '删除失败'}), 500


@bp.route('/batch-templates/<int:template_id>/set-default', methods=['POST'])
def set_default_batch_template(template_id):
    """设置默认批量分析模板"""
    from core.literature_db import set_default_prompt_template

    if set_default_prompt_template(template_id):
        return jsonify({'success': True, 'message': '已设为默认模板'})
    return jsonify({'success': False, 'message': '设置失败'}), 500


# ========== 批量删除 API ==========
@bp.route('/batch-delete', methods=['POST'])
def batch_delete_evaluations():
    """批量删除评估记录"""
    try:
        data = request.get_json()
        ids = data.get('ids', [])

        if not ids:
            return jsonify({'success': False, 'error': '未提供要删除的ID'}), 400

        service = get_evaluation_service()
        success_count = 0

        for evaluation_id in ids:
            result = service.delete_evaluation(evaluation_id)
            if result.get('success'):
                success_count += 1

        return jsonify({
            'success': True,
            'message': f'成功删除 {success_count} 条记录',
            'deleted_count': success_count
        })

    except Exception as e:
        logger.error(f"批量删除失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
