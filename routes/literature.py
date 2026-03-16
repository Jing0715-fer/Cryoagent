"""
Literature Management API Routes
"""
import threading
import time as time_module
from flask import jsonify, request, Blueprint
from flask_login import current_user, login_required
from pathlib import Path

bp = Blueprint('literature', __name__, url_prefix='/api/literature')

from core.literature_db import (
    search_literature,
    get_literature_entry,
    delete_literature_entry,
    update_literature_entry,
    get_literature_stats,
    LiteratureStatus,
    replace_literature_parsed_data,
    clear_and_reparse_literature
)


def get_current_user_id():
    """获取当前登录用户的ID，未登录返回None"""
    if current_user.is_authenticated:
        return current_user.id
    return None


def require_login():
    """强制要求登录"""
    if not current_user.is_authenticated:
        from flask import jsonify
        return jsonify({'error': '请先登录', 'code': 'NOT_LOGGED_IN'}), 401


@bp.route('', methods=['GET'])
@login_required
def get_literature_list():
    """Get literature list with pagination and filtering"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    query = request.args.get('query', '')
    author = request.args.get('author', '')
    journal = request.args.get('journal', '')
    year_from = request.args.get('year_from', type=int)
    year_to = request.args.get('year_to', type=int)
    status = request.args.get('status')
    has_cryoem = request.args.get('has_cryoem', '').lower() == 'true'
    has_embeddings = request.args.get('has_embeddings', '').lower() == 'true'
    tags = request.args.get('tags', '')

    # Debug log
    print(f"[Literature Filter] year_from={year_from}, year_to={year_to}, query={query}")

    try:
        user_id = get_current_user_id()
        result = search_literature(
            query=query,
            author=author,
            journal=journal,
            year_from=year_from,
            year_to=year_to,
            status=LiteratureStatus(status) if status else None,
            has_cryoem_targets=has_cryoem if has_cryoem else None,
            has_vector_embeddings=has_embeddings if has_embeddings else None,
            tags=[t.strip() for t in tags.split(',')] if tags else None,
            limit=per_page * page,
            user_id=user_id
        )

        # Pagination
        start = (page - 1) * per_page
        items = result[start:start + per_page]

        # Convert to dict format
        literature_list = []
        for entry in items:
            if hasattr(entry, 'to_dict'):
                literature_list.append(entry.to_dict())
            else:
                literature_list.append(entry)

        return jsonify({
            'items': literature_list,
            'total': len(result),
            'page': page,
            'per_page': per_page,
            'pages': (len(result) + per_page - 1) // per_page
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:lit_id>', methods=['GET'])
@login_required
def get_literature_detail(lit_id):
    """Get single literature entry detail"""
    try:
        user_id = get_current_user_id()
        entry = get_literature_entry(lit_id, user_id)
        if not entry:
            return jsonify({'error': 'Literature entry not found'}), 404

        if hasattr(entry, 'to_dict'):
            data = entry.to_dict()
        else:
            data = entry

        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:lit_id>', methods=['DELETE'])
@login_required
def delete_literature(lit_id):
    """Delete a literature entry"""
    try:
        result = delete_literature_entry(lit_id)
        return jsonify({'success': result is not None, 'message': 'Deleted successfully' if result else 'Entry not found'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:lit_id>/pdf-path', methods=['GET'])
@login_required
def get_pdf_path(lit_id):
    """Get PDF file path for a literature entry"""
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        entry = get_literature_entry(lit_id)
        if not entry:
            return jsonify({'error': 'Literature entry not found'}), 404

        # Get PDF path from entry
        pdf_path = entry.main_pdf_path if hasattr(entry, 'main_pdf_path') else None

        if not pdf_path or not Path(pdf_path).exists():
            # Try to construct path from filename in uploads directory
            pdf_filename = entry.main_pdf_filename if hasattr(entry, 'main_pdf_filename') else None
            if pdf_filename:
                import os
                # First try uploads directory (where new files are saved)
                base_dir = Path(__file__).parent.parent
                upload_dir = base_dir / 'uploads'
                pdf_path = str(upload_dir / pdf_filename) if upload_dir.exists() else None

                # Fallback to literature/pdfs directory
                if not pdf_path or not Path(pdf_path).exists():
                    from core.literature_db import LITERATURE_PDFS_DIR
                    if LITERATURE_PDFS_DIR:
                        pdf_path = str(LITERATURE_PDFS_DIR / pdf_filename)

        return jsonify({
            'pdf_path': pdf_path,
            'pdf_filename': getattr(entry, 'main_pdf_filename', None)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:lit_id>/pdf', methods=['GET'])
@login_required
def serve_pdf(lit_id):
    """Serve PDF file for a literature entry"""
    try:
        from flask import send_file, abort
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        entry = get_literature_entry(lit_id)
        if not entry:
            abort(404)

        # Get PDF path from entry
        pdf_path = entry.main_pdf_path if hasattr(entry, 'main_pdf_path') else None

        if not pdf_path or not Path(pdf_path).exists():
            # Try to construct path from filename in uploads directory
            pdf_filename = entry.main_pdf_filename if hasattr(entry, 'main_pdf_filename') else None
            if pdf_filename:
                # First try uploads directory (where new files are saved)
                base_dir = Path(__file__).parent.parent
                upload_dir = base_dir / 'uploads'
                pdf_path = str(upload_dir / pdf_filename) if upload_dir.exists() else None

                # Fallback to literature/pdfs directory
                if not pdf_path or not Path(pdf_path).exists():
                    from core.literature_db import LITERATURE_PDFS_DIR
                    if LITERATURE_PDFS_DIR:
                        pdf_path = str(LITERATURE_PDFS_DIR / pdf_filename)

        if not pdf_path or not Path(pdf_path).exists():
            abort(404)

        return send_file(pdf_path, mimetype='application/pdf', as_attachment=False)
    except Exception as e:
        print(f"Error serving PDF: {e}")
        abort(404)


@bp.route('/extract-fulltext-single', methods=['POST'])
@login_required
def extract_fulltext_single():
    """Extract fulltext from a single PDF"""
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        data = request.json or {}
        lit_id = data.get('lit_id')

        if not lit_id:
            return jsonify({'error': '缺少文献ID'}), 400

        # Get entry
        entry = get_literature_entry(lit_id)
        if not entry:
            return jsonify({'error': '文献不存在'}), 404

        # Get PDF path from entry
        pdf_path = entry.main_pdf_path if hasattr(entry, 'main_pdf_path') else None
        if not pdf_path or not Path(pdf_path).exists():
            pdf_filename = entry.main_pdf_filename if hasattr(entry, 'main_pdf_filename') else None
            if pdf_filename:
                # First try uploads directory (where new files are saved)
                base_dir = Path(__file__).parent.parent
                upload_dir = base_dir / 'uploads'
                pdf_path = str(upload_dir / pdf_filename) if upload_dir.exists() else None

                # Fallback to literature/pdfs directory
                if not pdf_path or not Path(pdf_path).exists():
                    from core.literature_db import LITERATURE_PDFS_DIR
                    if LITERATURE_PDFS_DIR:
                        pdf_path = str(LITERATURE_PDFS_DIR / pdf_filename)

        if not pdf_path or not Path(pdf_path).exists():
            return jsonify({'error': 'PDF文件不存在'}), 404

        # Extract text using pymupdf
        import fitz
        doc = fitz.open(str(pdf_path))
        full_text = ""
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            full_text += f"--- Page {page_num + 1} ---\n{text}\n\n"
        doc.close()

        if full_text:
            # Update database
            from core.literature_db import create_literature_session, LiteratureEntry
            session = create_literature_session()
            lit_entry = session.get(LiteratureEntry, lit_id)
            if lit_entry:
                # Save to both full_text column and parsed_data
                lit_entry.full_text = full_text

                # Also update parsed_data
                parsed_data = getattr(lit_entry, 'parsed_data', None) or {}
                if isinstance(parsed_data, str):
                    import json
                    try:
                        parsed_data = json.loads(parsed_data)
                    except:
                        parsed_data = {}
                parsed_data['full_text'] = full_text
                lit_entry.parsed_data = parsed_data
                session.commit()
            session.close()

            return jsonify({
                'success': True,
                'lit_id': lit_id,
                'char_count': len(full_text)
            })
        else:
            return jsonify({'error': 'PDF内容为空'}), 400

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:lit_id>', methods=['PUT'])
@login_required
def update_literature(lit_id):
    """Update a literature entry"""
    try:
        data = request.json
        result = update_literature_entry(lit_id, data)
        return jsonify({'success': result is not None, 'data': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# 重新解析任务存储
reparse_tasks = {}  # {lit_id: {'status': 'running'|'completed'|'error', 'result': {}, 'start_time': timestamp}}

def _run_reparse_background(lit_id):
    """后台运行重新解析"""
    try:
        print(f"[Background] 开始重新解析文献 ID={lit_id}")
        result = clear_and_reparse_literature(lit_id)
        reparse_tasks[lit_id] = {
            'status': 'completed' if result.get('success') else 'error',
            'result': result,
            'start_time': reparse_tasks[lit_id].get('start_time', time_module.time())
        }
        print(f"[Background] 重新解析完成 ID={lit_id}, success={result.get('success')}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        reparse_tasks[lit_id] = {
            'status': 'error',
            'result': {'success': False, 'error': str(e)},
            'start_time': reparse_tasks[lit_id].get('start_time', time_module.time())
        }
        print(f"[Background] 重新解析失败 ID={lit_id}, error={e}")


@bp.route('/<int:lit_id>/reparse', methods=['POST'])
@login_required
def reparse_literature(lit_id):
    """Reparse a literature entry (异步)"""
    try:
        # 检查是否已有任务在运行
        if lit_id in reparse_tasks:
            task = reparse_tasks[lit_id]
            if task['status'] == 'running':
                # 检查是否超时(5分钟)
                if time_module.time() - task.get('start_time', 0) > 300:
                    # 超时，重新启动
                    pass
                else:
                    return jsonify({
                        'success': True,
                        'message': '重新解析已在进行中',
                        'status': 'running'
                    })

        # 启动后台任务
        reparse_tasks[lit_id] = {
            'status': 'running',
            'result': {},
            'start_time': time_module.time()
        }

        # 在后台线程中运行
        thread = threading.Thread(target=_run_reparse_background, args=(lit_id,))
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'message': '重新解析已启动',
            'status': 'started'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:lit_id>/reparse/progress', methods=['GET'])
@login_required
def get_reparse_progress(lit_id):
    """Get reparse progress for a literature entry"""
    try:
        from core.literature_db import create_literature_session, LiteratureEntry
        session = create_literature_session()
        entry = session.query(LiteratureEntry).get(lit_id)
        if not entry:
            return jsonify({'error': '文献不存在'}), 404

        # 检查后台任务状态
        if lit_id in reparse_tasks:
            task = reparse_tasks[lit_id]
            status = task.get('status', 'unknown')
            elapsed = time_module.time() - task.get('start_time', time_module.time())

            if status == 'running':
                # 估算进度 (假设需要60秒)
                progress = min(int(elapsed / 60 * 100), 90)
                return jsonify({
                    'progress': progress,
                    'stage': 'parsing',
                    'message': f'正在解析中... ({int(elapsed)}秒)'
                })
            elif status == 'completed':
                result = task.get('result', {})
                return jsonify({
                    'progress': 100,
                    'stage': 'completed',
                    'message': result.get('message', '解析完成')
                })
            elif status == 'error':
                result = task.get('result', {})
                return jsonify({
                    'progress': 0,
                    'stage': 'error',
                    'message': result.get('error', '解析失败')
                })

        # 没有任务，检查数据库状态
        return jsonify({
            'progress': 100,
            'stage': 'completed',
            'message': '解析完成'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/stats', methods=['GET'])
@login_required
def get_stats():
    """Get literature statistics"""
    try:
        user_id = get_current_user_id()
        stats = get_literature_stats(user_id)
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== 附录相关路由 ====================

@bp.route('/<int:lit_id>/appendices', methods=['GET'])
@login_required
def get_appendices(lit_id):
    """获取文献的所有附录"""
    try:
        from core.literature_db import create_literature_session, LiteratureAppendix, LiteratureEntry

        session = create_literature_session()
        entry = session.query(LiteratureEntry).filter(LiteratureEntry.id == lit_id).first()
        if not entry:
            session.close()
            return jsonify({'error': '文献不存在'}), 404

        appendices = session.query(LiteratureAppendix).filter(
            LiteratureAppendix.literature_id == lit_id
        ).order_by(LiteratureAppendix.created_at.desc()).all()

        result = []
        for a in appendices:
            result.append({
                'id': a.id,
                'filename': a.filename,
                'file_type': a.file_type,
                'file_size': a.file_size,
                'appendix_type': a.appendix_type,
                'description': a.description,
                'has_vector_embeddings': a.is_parsed,
                'created_at': a.created_at.isoformat() if a.created_at else None
            })

        session.close()
        return jsonify({'success': True, 'appendices': result})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:lit_id>/appendix/upload', methods=['POST'])
@login_required
def upload_appendix(lit_id):
    """上传附录"""
    try:
        from core.literature_db import create_literature_session, LiteratureAppendix, LiteratureEntry
        import os
        from pathlib import Path
        from werkzeug.utils import secure_filename

        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '没有文件'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': '文件名为空'}), 400

        # 获取表单数据
        appendix_type = request.form.get('appendix_type', 'other')
        description = request.form.get('description', '')

        # 创建目录 - 新结构: literature/pdfs/{literature_id}/
        base_dir = Path(__file__).parent.parent
        appendix_dir = base_dir / 'literature' / 'pdfs' / str(lit_id)
        appendix_dir.mkdir(parents=True, exist_ok=True)

        # 保存文件 - 使用 appendix_ 前缀
        filename = secure_filename(file.filename)
        appendix_filename = f"appendix_{filename}"
        file_path = appendix_dir / appendix_filename
        file.save(str(file_path))

        # 获取文件大小
        file_size = file_path.stat().st_size

        # 获取文件类型
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

        # 保存到数据库
        session = create_literature_session()
        entry = session.query(LiteratureEntry).filter(LiteratureEntry.id == lit_id).first()
        if not entry:
            session.close()
            os.remove(str(file_path))
            return jsonify({'success': False, 'error': '文献不存在'}), 404

        appendix = LiteratureAppendix(
            literature_id=lit_id,
            filename=appendix_filename,  # 使用带前缀的文件名
            file_path=str(file_path),
            file_size=file_size,
            file_type=ext,
            appendix_type=appendix_type,
            description=description
        )
        session.add(appendix)
        session.commit()
        # 在关闭session前获取id
        appendix_id = appendix.id
        session.close()

        return jsonify({'success': True, 'appendix_id': appendix_id})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:lit_id>/appendix/<int:appendix_id>', methods=['DELETE'])
@login_required
def delete_appendix(lit_id, appendix_id):
    """删除附录"""
    try:
        from core.literature_db import create_literature_session, LiteratureAppendix
        import os
        from pathlib import Path

        session = create_literature_session()
        appendix = session.query(LiteratureAppendix).filter(
            LiteratureAppendix.id == appendix_id,
            LiteratureAppendix.literature_id == lit_id
        ).first()

        if not appendix:
            session.close()
            return jsonify({'success': False, 'error': '附录不存在'}), 404

        # 删除文件
        if appendix.file_path and Path(appendix.file_path).exists():
            os.remove(appendix.file_path)

        # 删除数据库记录
        session.delete(appendix)
        session.commit()
        session.close()

        return jsonify({'success': True})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:lit_id>/appendix/<int:appendix_id>/preview', methods=['GET'])
@login_required
def preview_appendix(lit_id, appendix_id):
    """预览附录"""
    try:
        from core.literature_db import create_literature_session, LiteratureAppendix

        session = create_literature_session()
        appendix = session.query(LiteratureAppendix).filter(
            LiteratureAppendix.id == appendix_id,
            LiteratureAppendix.literature_id == lit_id
        ).first()

        if not appendix:
            session.close()
            return jsonify({'success': False, 'error': '附录不存在'}), 404

        if not Path(appendix.file_path).exists():
            session.close()
            return jsonify({'success': False, 'error': '文件不存在'}), 404

        session.close()

        # 返回预览URL
        preview_url = f'/api/literature/{lit_id}/appendix/{appendix_id}/download'
        return jsonify({'success': True, 'preview_url': preview_url})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:lit_id>/appendix/<int:appendix_id>/download', methods=['GET'])
@login_required
def download_appendix(lit_id, appendix_id):
    """下载/预览附录"""
    try:
        from flask import send_file
        from core.literature_db import create_literature_session, LiteratureAppendix

        session = create_literature_session()
        appendix = session.query(LiteratureAppendix).filter(
            LiteratureAppendix.id == appendix_id,
            LiteratureAppendix.literature_id == lit_id
        ).first()

        if not appendix:
            session.close()
            return jsonify({'error': '附录不存在'}), 404

        if not Path(appendix.file_path).exists():
            session.close()
            return jsonify({'error': '文件不存在'}), 404

        session.close()

        # 根据文件类型设置content-type
        mime_types = {
            'pdf': 'application/pdf',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'zip': 'application/zip'
        }
        content_type = mime_types.get(appendix.file_type, 'application/octet-stream')

        return send_file(
            appendix.file_path,
            mimetype=content_type,
            as_attachment=False,
            download_name=appendix.filename
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:lit_id>/appendix/<int:appendix_id>/vectorize', methods=['POST'])
@login_required
def vectorize_appendix(lit_id, appendix_id):
    """向量化附录"""
    try:
        from core.literature_db import create_literature_session, LiteratureAppendix
        from core.literature_parser import PDFParser
        from core.agent_core import EmbeddingManager
        from datetime import datetime

        session = create_literature_session()
        appendix = session.query(LiteratureAppendix).filter(
            LiteratureAppendix.id == appendix_id,
            LiteratureAppendix.literature_id == lit_id
        ).first()

        if not appendix:
            session.close()
            return jsonify({'success': False, 'error': '附录不存在'}), 404

        if appendix.file_type != 'pdf':
            session.close()
            return jsonify({'success': False, 'error': '目前只支持PDF文件的向量化'}), 400

        if not Path(appendix.file_path).exists():
            session.close()
            return jsonify({'success': False, 'error': '文件不存在'}), 404

        # 解析PDF
        try:
            parser = PDFParser()
            result = parser.parse_pdf(appendix.file_path)
            text = result.get('text', '')

            if not text or len(text.strip()) < 10:
                session.close()
                return jsonify({'success': False, 'error': '无法提取文本内容'}), 400

            # 更新提取的文本
            appendix.extracted_text = text
            appendix.page_count = result.get('metadata', {}).get('page_count', 0)

            # 生成向量
            try:
                embedding_manager = EmbeddingManager()
                embedding = embedding_manager.get_text_embedding(text)

                if embedding:
                    # 保存向量到数据库
                    import json
                    appendix.embedding = json.dumps(embedding.tolist())
                    appendix.is_parsed = True
                    appendix.parsed_at = datetime.now()

            except Exception as emb_err:
                print(f"生成向量失败: {emb_err}")
                # 继续保存文本，不保存向量

            session.commit()
            session.close()

            return jsonify({'success': True, 'message': '向量化完成'})

        except Exception as parse_err:
            session.rollback()
            session.close()
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'error': f'解析失败: {str(parse_err)}'}), 500

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================
# 索引进度跟踪
# ============================================
_index_progress = {
    'status': 'idle',  # idle, running, completed, error
    'message': '',
    'current': 0,
    'total': 0,
    'progress_pct': 0,
    'error': None
}

@bp.route('/index/progress', methods=['GET'])
def get_index_progress():
    """获取索引重建进度"""
    return jsonify(_index_progress)

# ============================================
# 索引重建 API
# ============================================

@bp.route('/index/rebuild', methods=['POST'])
@login_required
def rebuild_index_api():
    """重建文献索引（支持 LanceDB）"""
    try:
        from core.literature_agent import LiteratureManager
        import threading

        agent = LiteratureManager()

        def run_rebuild():
            global _index_progress
            try:
                _index_progress = {
                    'status': 'running',
                    'message': '开始重建索引...',
                    'current': 0,
                    'total': 100,
                    'progress_pct': 0,
                    'error': None
                }
                result = agent.rebuild_index(force=True)
                _index_progress = {
                    'status': 'completed',
                    'message': '索引重建完成',
                    'current': 100,
                    'total': 100,
                    'progress_pct': 100,
                    'error': None
                }
                print(f"索引重建完成: {result}")
            except Exception as e:
                _index_progress = {
                    'status': 'error',
                    'message': '索引重建失败',
                    'current': 0,
                    'total': 100,
                    'progress_pct': 0,
                    'error': str(e)
                }
                print(f"索引重建失败: {e}")

        # 异步执行索引重建
        thread = threading.Thread(target=run_rebuild)
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'message': '索引重建任务已在后台启动',
            'task_id': 'rebuild_index'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

