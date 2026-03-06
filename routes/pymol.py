"""
PyMOL API Routes
蛋白质结构深度分析接口
"""
import os
import json
import uuid
from flask import jsonify, request, Blueprint, send_file, Response
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('pymol', __name__, url_prefix='/api/pymol')

# 工作目录
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pymol_data')
os.makedirs(WORKSPACE_DIR, exist_ok=True)


def _get_wrapper():
    """获取 PyMOL 封装实例"""
    from core.pymol_wrapper import get_pymol_wrapper
    return get_pymol_wrapper()


@bp.route('/status', methods=['GET'])
def check_status():
    """
    检查 PyMOL 可用性
    """
    try:
        from core.pymol_wrapper import check_pymol_availability
        status = check_pymol_availability()
        return jsonify(status)
    except Exception as e:
        logger.error(f"Error checking PyMOL status: {e}")
        return jsonify({
            "available": False,
            "error": str(e)
        }), 500


@bp.route('/analyze', methods=['POST'])
def analyze_structure():
    """
    执行结构分析
    Request body:
    {
        "pdb_id": "1ABC",
        "analysis_type": "info|secondary_structure|surface|contacts"
    }
    """
    try:
        data = request.get_json()
        pdb_id = data.get('pdb_id', '').strip()
        analysis_type = data.get('analysis_type', 'info')

        if not pdb_id:
            return jsonify({'error': 'PDB ID is required'}), 400

        wrapper = _get_wrapper()

        if not wrapper.is_available():
            return jsonify({
                'error': 'PyMOL is not available',
                'hint': 'Install with: pip install pymol-open-source'
            }), 503

        # 执行分析
        result = wrapper.analyze_structure(pdb_id, analysis_type)

        return jsonify({
            'success': True,
            'pdb_id': pdb_id,
            'analysis_type': analysis_type,
            'result': result
        })

    except Exception as e:
        logger.error(f"Analysis error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/rmsd', methods=['POST'])
def calculate_rmsd():
    """
    计算两个结构的 RMSD
    Request body:
    {
        "pdb_id1": "1ABC",
        "pdb_id2": "2DEF"
    }
    """
    try:
        data = request.get_json()
        pdb_id1 = data.get('pdb_id1', '').strip()
        pdb_id2 = data.get('pdb_id2', '').strip()

        if not pdb_id1 or not pdb_id2:
            return jsonify({'error': 'Both PDB IDs are required'}), 400

        wrapper = _get_wrapper()

        if not wrapper.is_available():
            return jsonify({
                'error': 'PyMOL is not available',
                'hint': 'Install with: pip install pymol-open-source'
            }), 503

        result = wrapper.calculate_rmsd(pdb_id1, pdb_id2)

        return jsonify({
            'success': True,
            'result': result
        })

    except Exception as e:
        logger.error(f"RMSD calculation error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/align', methods=['POST'])
def align_structures():
    """
    对齐两个结构
    Request body:
    {
        "pdb_id1": "1ABC",
        "pdb_id2": "2DEF"
    }
    """
    try:
        data = request.get_json()
        pdb_id1 = data.get('pdb_id1', '').strip()
        pdb_id2 = data.get('pdb_id2', '').strip()

        if not pdb_id1 or not pdb_id2:
            return jsonify({'error': 'Both PDB IDs are required'}), 400

        wrapper = _get_wrapper()

        if not wrapper.is_available():
            return jsonify({
                'error': 'PyMOL is not available',
                'hint': 'Install with: pip install pymol-open-source'
            }), 503

        result = wrapper.align_structures(pdb_id1, pdb_id2)

        return jsonify({
            'success': True,
            'result': result
        })

    except Exception as e:
        logger.error(f"Alignment error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/secondary-structure', methods=['POST'])
def analyze_secondary_structure():
    """
    分析二级结构
    Request body:
    {
        "pdb_id": "1ABC"
    }
    """
    try:
        data = request.get_json()
        pdb_id = data.get('pdb_id', '').strip()

        if not pdb_id:
            return jsonify({'error': 'PDB ID is required'}), 400

        wrapper = _get_wrapper()

        if not wrapper.is_available():
            return jsonify({
                'error': 'PyMOL is not available',
                'hint': 'Install with: pip install pymol-open-source'
            }), 503

        result = wrapper.analyze_secondary_structure(pdb_id)

        return jsonify({
            'success': True,
            'result': result
        })

    except Exception as e:
        logger.error(f"Secondary structure analysis error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/image', methods=['POST'])
def generate_image():
    """
    生成结构图像
    Request body:
    {
        "pdb_id": "1ABC",
        "style": "cartoon|sticks|spheres|surface",
        "color": "rainbow|chain|structure|hydrophobicity",
        "width": 800,
        "height": 600,
        "format": "png"
    }
    """
    try:
        data = request.get_json()
        pdb_id = data.get('pdb_id', '').strip()
        style = data.get('style', 'cartoon')
        color = data.get('color', 'rainbow')
        width = data.get('width', 800)
        height = data.get('height', 600)
        output_format = data.get('format', 'png')

        if not pdb_id:
            return jsonify({'error': 'PDB ID is required'}), 400

        wrapper = _get_wrapper()

        if not wrapper.is_available():
            return jsonify({
                'error': 'PyMOL is not available',
                'hint': 'Install with: pip install pymol-open-source'
            }), 503

        # 生成图像
        image_path = wrapper.generate_image(
            pdb_id, style, color, width, height, output_format
        )

        if not image_path:
            return jsonify({'error': 'Failed to generate image'}), 500

        return jsonify({
            'success': True,
            'image_path': image_path,
            'image_url': f'/api/pymol/download?path={os.path.basename(image_path)}'
        })

    except Exception as e:
        logger.error(f"Image generation error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/session', methods=['POST'])
def save_session():
    """
    保存 PyMOL session 文件
    Request body:
    {
        "pdb_id": "1ABC",
        "session_name": "my_session"
    }
    """
    try:
        data = request.get_json()
        pdb_id = data.get('pdb_id', '').strip()
        session_name = data.get('session_name', pdb_id)

        if not pdb_id:
            return jsonify({'error': 'PDB ID is required'}), 400

        wrapper = _get_wrapper()

        if not wrapper.is_available():
            return jsonify({
                'error': 'PyMOL is not available',
                'hint': 'Install with: pip install pymol-open-source'
            }), 503

        # 保存 session
        session_path = wrapper.save_session(pdb_id, session_name)

        if not session_path:
            return jsonify({'error': 'Failed to save session'}), 500

        return jsonify({
            'success': True,
            'session_path': session_path,
            'session_url': f'/api/pymol/download?path={os.path.basename(session_path)}'
        })

    except Exception as e:
        logger.error(f"Session save error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/download', methods=['GET'])
def download_file():
    """
    下载生成的文件（图像或 session）
    Query params:
        path: 文件名
    """
    try:
        filename = request.args.get('path', '')
        if not filename:
            return jsonify({'error': 'Path is required'}), 400

        # 安全检查 - 只允许特定目录
        safe_path = os.path.join(WORKSPACE_DIR, os.path.basename(filename))

        if not os.path.exists(safe_path):
            return jsonify({'error': 'File not found'}), 404

        # 根据扩展名确定 MIME 类型
        ext = os.path.splitext(safe_path)[1].lower()
        if ext == '.png':
            mimetype = 'image/png'
        elif ext == '.pse':
            mimetype = 'application/octet-stream'
        else:
            mimetype = 'application/octet-stream'

        return send_file(safe_path, mimetype=mimetype, as_attachment=True)

    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/complete-analysis', methods=['POST'])
def complete_analysis():
    """
    完整结构分析 - 结合图像和 session
    Request body:
    {
        "pdb_id": "1ABC",
        "include_image": true,
        "include_session": true,
        "image_style": "cartoon",
        "image_color": "rainbow"
    }
    """
    try:
        data = request.get_json()
        pdb_id = data.get('pdb_id', '').strip()

        if not pdb_id:
            return jsonify({'error': 'PDB ID is required'}), 400

        wrapper = _get_wrapper()

        if not wrapper.is_available():
            return jsonify({
                'error': 'PyMOL is not available',
                'hint': 'Install with: pip install pymol-open-source'
            }), 503

        # 获取结构信息
        info_result = wrapper.get_structure_info(pdb_id)

        # 二级结构分析
        ss_result = wrapper.analyze_secondary_structure(pdb_id)

        # 响应数据
        response = {
            'success': True,
            'pdb_id': pdb_id,
            'structure_info': info_result,
            'secondary_structure': ss_result,
        }

        # 生成图像
        if data.get('include_image', True):
            style = data.get('image_style', 'cartoon')
            color = data.get('image_color', 'rainbow')
            image_path = wrapper.generate_image(pdb_id, style, color)
            if image_path:
                response['image_path'] = image_path

        # 保存 session
        if data.get('include_session', True):
            session_path = wrapper.save_session(pdb_id)
            if session_path:
                response['session_path'] = session_path

        return jsonify(response)

    except Exception as e:
        logger.error(f"Complete analysis error: {e}")
        return jsonify({'error': str(e)}), 500
