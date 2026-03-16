"""
File Upload API Routes
"""
import os
import shutil
import uuid
import time
from flask import jsonify, request, Blueprint
from flask_login import current_user, login_required
from datetime import datetime

bp = Blueprint('upload', __name__, url_prefix='/api/upload')

# In-memory log storage for progress tracking
upload_logs = {}

# Try to import optional dependencies
try:
    from werkzeug.utils import secure_filename
    from core.literature_parser import LiteratureParserManager
    from core.literature_db import add_literature_entry, create_literature_session, LiteratureEntry
    PARSER_AVAILABLE = True
except ImportError as e:
    PARSER_AVAILABLE = False
    LiteratureParserManager = None
    add_literature_entry = None
    print(f"⚠️ Upload dependencies warning: {e}")

# LanceDB indexing
try:
    from core.literature_index import get_unified_rag_system
    LANCEDB_AVAILABLE = True
except ImportError:
    LANCEDB_AVAILABLE = False
    print("⚠️ LanceDB not available for chunk indexing")


def get_current_user_id():
    """获取当前登录用户的ID，未登录返回None"""
    if current_user.is_authenticated:
        return current_user.id
    return None


def add_log(upload_id, message, level='info'):
    """Add a log message to the upload session"""
    if upload_id not in upload_logs:
        upload_logs[upload_id] = []
    upload_logs[upload_id].append({
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'level': level,
        'message': message
    })
    # Keep only last 1000 logs per upload
    if len(upload_logs[upload_id]) > 1000:
        upload_logs[upload_id] = upload_logs[upload_id][-1000:]


def clear_logs(upload_id):
    """Clear logs for an upload session"""
    if upload_id in upload_logs:
        del upload_logs[upload_id]


def allowed_file(filename):
    """Check if file extension is allowed"""
    ALLOWED_EXTENSIONS = {'pdf'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('', methods=['POST'])
@login_required
def upload_files():
    """
    Upload PDF files for literature parsing
    """
    # Generate upload ID for tracking
    upload_id = uuid.uuid4().hex[:8]
    upload_logs[upload_id] = []

    try:
        if 'files[]' not in request.files:
            return jsonify({'error': 'No files provided'}), 400

        if not PARSER_AVAILABLE:
            return jsonify({'error': 'PDF parsing module not available. Please install pdfplumber.'}), 503

        files = request.files.getlist('files[]')
        results = []
        total_files = len(files)

        add_log(upload_id, f"开始上传 {total_files} 个文件...", 'info')

        for idx, file in enumerate(files):
            add_log(upload_id, f"处理文件 {idx + 1}/{total_files}: {file.filename if hasattr(file, 'filename') else 'unknown'}", 'info')

            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                add_log(upload_id, f"保存文件: {filename}", 'info')

                # Add unique ID to prevent conflicts
                filename = secure_filename(file.filename)

                # Parse the file first to get the literature_id
                add_log(upload_id, f"保存文件并解析...", 'info')

                # Temporary save to parse
                temp_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads')
                os.makedirs(temp_folder, exist_ok=True)
                temp_unique_name = f"{uuid.uuid4().hex}_{filename}"
                temp_filepath = os.path.join(temp_folder, temp_unique_name)
                file.save(temp_filepath)

                add_log(upload_id, f"文件已保存到临时位置，正在解析...", 'info')

                # Parse the file
                parser = LiteratureParserManager()
                parse_result = parser.parse_literature_file(temp_filepath)

                add_log(upload_id, f"解析完成，正在提取结构信息...", 'info')

                # 保存到数据库
                literature_id = None
                if parse_result and parse_result.get('success'):
                    # 构建文献数据
                    parsed_data = parse_result.get('parsed_data', {})
                    combined_metadata = parsed_data.get('combined_metadata', {})

                    # 处理年份字段 - PubMed返回year，其他来源可能返回publication_year
                    pub_year = combined_metadata.get('year') or combined_metadata.get('publication_year')
                    if pub_year and isinstance(pub_year, str) and pub_year.isdigit():
                        pub_year = int(pub_year)

                    literature_data = {
                        'title': combined_metadata.get('title', filename),
                        'abstract': combined_metadata.get('abstract', ''),
                        'doi': combined_metadata.get('doi', ''),
                        'journal': combined_metadata.get('journal', ''),
                        'authors': combined_metadata.get('authors', []),
                        'year': pub_year,  # 同时设置year和publication_year
                        'publication_year': pub_year,
                        'publication_date': combined_metadata.get('publication_date'),
                        'keywords': combined_metadata.get('keywords', []),
                        'disciplines': combined_metadata.get('disciplines', []),
                        'status': 'parsed',
                        'literature_type': combined_metadata.get('literature_type', 'article'),
                        'main_pdf_filename': filename,
                        'main_pdf_path': temp_filepath,  # 临时路径，稍后会更新
                        'sections_json': parsed_data.get('sections_json', {}),
                        'cryoem_targets': parsed_data.get('structure_ids', {}),
                        'key_findings': parsed_data.get('key_findings', []),
                        'structure_metadata': parsed_data.get('structure_metadata', {}),
                    }

                    # 记录日志
                    add_log(upload_id, f"📝 保存字段: title='{literature_data.get('title', '')[:50]}...', year={pub_year}, journal='{literature_data.get('journal', '')}'", 'info')

                    # 保存到数据库
                    doi = literature_data.get('doi', '')

                    # 先检查是否已存在
                    literature_id = None
                    if doi:
                        try:
                            session = create_literature_session()
                            existing = session.query(LiteratureEntry).filter_by(doi=doi).first()
                            if existing:
                                literature_id = existing.id
                                add_log(upload_id, f"⚠️ 文献已存在: ID={literature_id}, DOI={doi}", 'warning')

                                # Move file to final location for existing entry
                                try:
                                    from pathlib import Path
                                    base_dir = Path(__file__).parent.parent
                                    final_dir = base_dir / 'literature' / 'pdfs' / str(literature_id)
                                    final_dir.mkdir(parents=True, exist_ok=True)
                                    final_path = final_dir / 'main.pdf'

                                    # Move from temp to final location
                                    shutil.move(str(temp_filepath), str(final_path))
                                    add_log(upload_id, f"📁 PDF moved to: {final_path}", 'info')

                                    # Update database with final path
                                    existing.main_pdf_path = str(final_path)
                                    existing.main_pdf_filename = 'main.pdf'
                                    session.commit()
                                    add_log(upload_id, f"📝 Database updated with new path", 'info')
                                except Exception as move_err:
                                    add_log(upload_id, f"⚠️ Could not move PDF to final location: {move_err}", 'warning')
                            session.close()
                        except Exception as e:
                            add_log(upload_id, f"检查文献是否存在时出错: {e}", 'error')

                    # 如果不存在，添加新文献
                    if not literature_id:
                        user_id = get_current_user_id()
                        success, entry = add_literature_entry(literature_data, user_id)
                        if success:
                            literature_id = entry.id if hasattr(entry, 'id') else None
                            add_log(upload_id, f"✅ 文献已保存到数据库: ID={literature_id}", 'success')

                            # Move file to final location: literature/pdfs/{literature_id}/main.pdf
                            try:
                                from pathlib import Path
                                base_dir = Path(__file__).parent.parent
                                final_dir = base_dir / 'literature' / 'pdfs' / str(literature_id)
                                final_dir.mkdir(parents=True, exist_ok=True)
                                final_path = final_dir / 'main.pdf'

                                # Move from temp to final location
                                shutil.move(str(temp_filepath), str(final_path))
                                add_log(upload_id, f"📁 PDF moved to: {final_path}", 'info')

                                # Update database with final path
                                from core.literature_db import create_literature_session, LiteratureEntry
                                session = create_literature_session()
                                lit_entry = session.query(LiteratureEntry).get(literature_id)
                                if lit_entry:
                                    lit_entry.main_pdf_path = str(final_path)
                                    lit_entry.main_pdf_filename = 'main.pdf'
                                    session.commit()
                                    add_log(upload_id, f"📝 Database updated with new path", 'info')
                                session.close()
                            except Exception as move_err:
                                add_log(upload_id, f"⚠️ Could not move PDF to final location: {move_err}", 'warning')

                            # 创建结构映射关系
                            try:
                                structure_ids = parsed_data.get('structure_ids', {})
                                if structure_ids:
                                    from core.literature_db import StructureSyncManager
                                    sync_manager = StructureSyncManager()
                                    sync_manager.update_structure_mappings(literature_id, structure_ids)
                                    pdb_count = len(structure_ids.get('pdb_ids', []))
                                    emdb_count = len(structure_ids.get('emdb_ids', []))
                                    add_log(upload_id, f"✅ 结构映射已创建: {pdb_count}个PDB, {emdb_count}个EMDB", 'success')
                            except Exception as e:
                                add_log(upload_id, f"⚠️ 创建结构映射失败: {e}", 'error')

                            # 索引到 LanceDB（分块存储）
                            if LANCEDB_AVAILABLE:
                                try:
                                    add_log(upload_id, f"📊 正在索引到 LanceDB...", 'info')
                                    rag = get_unified_rag()

                                    # 构建完整的文献数据用于分块
                                    full_literature_data = {
                                        'id': literature_id,
                                        'title': literature_data.get('title', ''),
                                        'abstract': literature_data.get('abstract', ''),
                                        'full_text': parsed_data.get('full_text', ''),
                                        'year': literature_data.get('year'),
                                        'journal': literature_data.get('journal', ''),
                                        'doi': literature_data.get('doi', ''),
                                        'authors': literature_data.get('authors', []),
                                        'keywords': literature_data.get('keywords', []),
                                        'parsed_data': parsed_data.get('sections_json', {}),
                                    }

                                    # 索引分块到 LanceDB
                                    chunk_count = rag.add_literature_chunks(full_literature_data)
                                    add_log(upload_id, f"✅ LanceDB 索引完成: {chunk_count} 个 chunks", 'success')
                                except Exception as e:
                                    add_log(upload_id, f"⚠️ LanceDB 索引失败: {e}", 'error')
                        else:
                            add_log(upload_id, f"⚠️ 文献保存失败: DOI={doi}", 'error')

                    # Log extracted data
                    title = combined_metadata.get('title', filename)
                    add_log(upload_id, f"📄 标题: {title[:60]}{'...' if len(title) > 60 else ''}", 'info')

                    authors = combined_metadata.get('authors', [])
                    if authors:
                        author_count = len(authors) if isinstance(authors, list) else 0
                        add_log(upload_id, f"👥 作者: {author_count}人", 'info')

                    structure_ids = parsed_data.get('structure_ids', {})
                    if structure_ids:
                        pdb_ids = structure_ids.get('pdb_ids', [])
                        emdb_ids = structure_ids.get('emdb_ids', [])
                        if pdb_ids:
                            add_log(upload_id, f"🔬 PDB IDs: {', '.join(pdb_ids[:5])}{'...' if len(pdb_ids) > 5 else ''}", 'info')
                        if emdb_ids:
                            add_log(upload_id, f"🧊 EMDB IDs: {', '.join(emdb_ids[:5])}{'...' if len(emdb_ids) > 5 else ''}", 'info')

                else:
                    add_log(upload_id, f"❌ 解析失败: {parse_result.get('error', '未知错误') if parse_result else '解析返回为空'}", 'error')
                    # Clean up temp file on failure
                    try:
                        if os.path.exists(temp_filepath):
                            os.remove(temp_filepath)
                            add_log(upload_id, f"🗑️ 临时文件已清理", 'info')
                    except Exception as cleanup_err:
                        add_log(upload_id, f"⚠️ 临时文件清理失败: {cleanup_err}", 'warning')

                results.append({
                    'filename': filename,
                    'success': parse_result is not None and parse_result.get('success'),
                    'literature_id': literature_id,
                    'title': parse_result.get('parsed_data', {}).get('combined_metadata', {}).get('title', filename) if parse_result else None
                })
            else:
                add_log(upload_id, f"❌ 无效文件类型: {file.filename if hasattr(file, 'filename') else 'unknown'}", 'error')
                results.append({
                    'filename': file.filename if hasattr(file, 'filename') else 'unknown',
                    'success': False,
                    'error': 'Invalid file type. Only PDF files are allowed.'
                })

        # Add completion log
        success_count = sum(1 for r in results if r.get('success'))
        add_log(upload_id, f"🎉 上传完成: {success_count}/{total_files} 个文件成功", 'success' if success_count == total_files else 'warning')

        return jsonify({
            'results': results,
            'upload_id': upload_id,
            'logs': upload_logs.get(upload_id, [])
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        add_log(upload_id, f"❌ 上传出错: {str(e)}", 'error')
        return jsonify({'error': str(e), 'upload_id': upload_id, 'logs': upload_logs.get(upload_id, [])}), 500


@bp.route('/<filename>', methods=['DELETE'])
def delete_uploaded_file(filename):
    """Delete an uploaded file"""
    try:
        upload_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads')
        filepath = os.path.join(upload_folder, secure_filename(filename))
        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({'success': True, 'message': 'File deleted'})
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/status/<task_id>', methods=['GET'])
def get_upload_status(task_id):
    """Get upload/processing status"""
    return jsonify({
        'task_id': task_id,
        'status': 'completed',
        'progress': 100
    })


@bp.route('/logs/<upload_id>', methods=['GET'])
def get_upload_logs(upload_id):
    """Get upload logs by upload ID"""
    logs = upload_logs.get(upload_id, [])
    return jsonify({
        'upload_id': upload_id,
        'logs': logs,
        'count': len(logs)
    })


@bp.route('/check', methods=['GET'])
def check_dependencies():
    """Check if upload dependencies are available"""
    return jsonify({
        'parser_available': PARSER_AVAILABLE,
        'message': 'PDF parsing available' if PARSER_AVAILABLE else 'PDF parsing unavailable'
    })
