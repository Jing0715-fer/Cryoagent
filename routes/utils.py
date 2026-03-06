"""
Utility API Routes
"""
from flask import jsonify, Blueprint
from flask_login import current_user

bp = Blueprint('utils', __name__, url_prefix='/api')

from core.literature_db import get_literature_stats, get_all_keywords
from core.alignment_engine import ProfessionalAlignmentEngine


def get_current_user_id():
    """获取当前登录用户的ID，未登录返回None"""
    if current_user.is_authenticated:
        return current_user.id
    return None


def get_structure_count():
    """Get structure count from structure database"""
    try:
        import sqlite3
        import os
        from pathlib import Path

        # Get absolute path to data directory
        base_dir = Path(__file__).parent.parent
        db_path = base_dir / 'data' / 'structure_offline.db'

        print(f"[DEBUG] get_structure_count: base_dir={base_dir}, db_path={db_path}, exists={db_path.exists()}")

        if not db_path.exists():
            return 0

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM structures')
        count = cursor.fetchone()[0]
        conn.close()
        print(f"[DEBUG] get_structure_count: returning {count}")
        return count
    except Exception as e:
        import logging
        logging.warning(f"Failed to get structure count: {e}")
        print(f"[DEBUG] get_structure_count error: {e}")
        return 0


def get_vector_count():
    """Get vector file count"""
    try:
        from pathlib import Path

        # Get absolute path to data directory
        base_dir = Path(__file__).parent.parent
        lancedb_dir = base_dir / 'data' / 'lancedb'

        count = 0
        if lancedb_dir.exists():
            # Count lance directories (each is a vector index)
            count = len([d for d in lancedb_dir.iterdir() if d.is_dir() and d.name.endswith('.lance')])

        return count
    except Exception as e:
        import logging
        logging.warning(f"Failed to get vector count: {e}")
        return 0


@bp.route('/stats', methods=['GET'])
def get_stats():
    """Get system statistics"""
    try:
        # Get literature stats
        user_id = get_current_user_id()
        lit_stats = get_literature_stats(user_id)

        # Get structure count
        structure_count = get_structure_count()

        # Get vector file count
        vector_count = get_vector_count()

        return jsonify({
            'total_count': lit_stats.get('total_count', 0),
            'parsed_count': lit_stats.get('parsed_count', 0),
            'structure_count': structure_count,
            'vector_count': vector_count,
            'with_structure_count': lit_stats.get('with_structure_count', 0),
            'with_pdf': lit_stats.get('with_pdf', 0),
            'with_vector_embeddings': lit_stats.get('with_vector_embeddings', 0),
            'parsing_ratio': lit_stats.get('parsing_ratio', 0),
            'embedding_ratio': lit_stats.get('embedding_ratio', 0),
            'year_stats': lit_stats.get('year_stats', []),
            'journal_stats': lit_stats.get('journal_stats', []),
            'database_size': lit_stats.get('database_size', 0)
        })
    except Exception as e:
        # Return default stats if database is unavailable
        import logging
        logging.warning(f"Stats API fallback: {e}")
        return jsonify({
            'total_count': 0,
            'parsed_count': 0,
            'structure_count': 0,
            'vector_count': 0,
            'with_structure_count': 0,
            'with_pdf': 0,
            'with_vector_embeddings': 0,
            'parsing_ratio': 0,
            'embedding_ratio': 0,
            'year_stats': [],
            'journal_stats': [],
            'database_size': 0
        })


@bp.route('/keywords', methods=['GET'])
def get_keywords():
    """Get all available keywords/tags"""
    try:
        keywords = get_all_keywords()
        return jsonify({'keywords': keywords})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/alignment', methods=['POST'])
def run_alignment():
    """
    Run sequence alignment
    """
    try:
        from flask import request
        data = request.json
        sequence1 = data.get('sequence1', '')
        sequence2 = data.get('sequence2', '')
        alignment_type = data.get('type', 'global')  # global, local, semiglobal

        if not sequence1 or not sequence2:
            return jsonify({'error': 'Both sequences are required'}), 400

        engine = ProfessionalAlignmentEngine()

        if alignment_type == 'global':
            result = engine.align_with_biopython(sequence1, sequence2, 'global')
        elif alignment_type == 'local':
            result = engine.align_with_biopython(sequence1, sequence2, 'local')
        else:
            result = engine.align_with_biopython(sequence1, sequence2, 'global')

        return jsonify({
            'aligned_seq1': result.get('aligned_seq1', ''),
            'aligned_seq2': result.get('aligned_seq2', ''),
            'score': result.get('score', 0),
            'identity': result.get('identity', 0),
            'similarity': result.get('similarity', 0)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'cryoagent-pro-flask'
    })


# ========== QA Chat History Endpoints ==========

@bp.route('/qa/history', methods=['GET'])
def get_qa_history():
    """获取QA聊天历史列表"""
    try:
        from flask import request
        literature_id = request.args.get('literature_id', type=int)
        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)

        from core.literature_db import get_qa_chat_history
        user_id = get_current_user_id()
        history_list = get_qa_chat_history(literature_id=literature_id, limit=limit, offset=offset, user_id=user_id)

        return jsonify({
            'success': True,
            'items': [h.to_dict() for h in history_list],
            'total': len(history_list)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/qa/history/<int:history_id>', methods=['GET'])
def get_qa_history_detail(history_id):
    """获取单条QA聊天记录详情"""
    try:
        from core.literature_db import get_qa_chat_history_by_id
        user_id = get_current_user_id()
        history = get_qa_chat_history_by_id(history_id, user_id)
        if not history:
            return jsonify({'error': '记录不存在'}), 404
        return jsonify({
            'success': True,
            'data': history.to_dict()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/qa/history/<int:history_id>', methods=['DELETE'])
def delete_qa_history(history_id):
    """删除QA聊天记录"""
    try:
        from core.literature_db import delete_qa_chat_history
        user_id = get_current_user_id()
        success = delete_qa_chat_history(history_id, user_id)
        return jsonify({
            'success': success,
            'message': '删除成功' if success else '记录不存在'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
