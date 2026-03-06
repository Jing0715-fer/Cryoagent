"""
Structure Information API Routes
"""
import os
import json
import time
import sys
from datetime import datetime
from flask import jsonify, request, Blueprint
import logging
logger = logging.getLogger(__name__)

bp = Blueprint('structure', __name__, url_prefix='/api/structure')

# 使用主数据库路径 - 使用 flask_app/data 目录
# __file__ = flask_app/routes/structure.py
# dirname(__file__) = flask_app/routes
# dirname(dirname(__file__)) = flask_app
FLASK_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(FLASK_APP_DIR, 'data')
MAIN_DB_PATH = os.path.join(DATA_DIR, 'structure_offline.db')

from core.structure_database import StructureOfflineDatabase, StructureType
from core.structure_database import get_enhanced_structure_manager
from core.structure_manager import StructureMetadataFetcher as StructureManager


def fetch_complete_metadata(structure_id: str, fetch_uniprot: bool = False) -> dict:
    """
    Fetch complete metadata for a structure (PDB or EMDB)

    Args:
        structure_id: Structure ID (e.g., '7A5I' or 'EMD-12345')
        fetch_uniprot: Whether to include UniProt data

    Returns:
        Dictionary with metadata (title, method, resolution, etc.)
    """
    structure_manager = StructureManager()
    struct_id_upper = structure_id.upper()

    # Check if EMDB
    if struct_id_upper.startswith('EMDB-') or struct_id_upper.startswith('EMD-'):
        emdb_id = structure_id.upper().replace('EMD-', 'EMDB-')
        metadata = structure_manager.fetch_emdb_metadata(emdb_id)
        if metadata:
            return {
                'title': getattr(metadata, 'title', None),
                'method': getattr(metadata, 'method', None),
                'resolution': getattr(metadata, 'resolution', None),
            }
        return {}
    else:
        # PDB
        pdb_id = structure_id.upper()
        metadata = structure_manager.fetch_pdb_metadata(pdb_id, fetch_uniprot=fetch_uniprot)
        if metadata:
            return {
                'title': getattr(metadata, 'title', None),
                'method': getattr(metadata, 'method', None),
                'resolution': getattr(metadata, 'resolution', None),
            }
        return {}


# 模块级别单例
_main_db = None


def get_main_db():
    """获取主数据库实例（单例）"""
    global _main_db
    if _main_db is None:
        _main_db = StructureOfflineDatabase(db_path=MAIN_DB_PATH)
    return _main_db


@bp.route('/<path:structure_id>', methods=['GET'])
def get_structure_detail(structure_id):
    """Get structure detail by ID"""
    try:
        db = get_main_db()
        structure = db.get_structure(structure_id)

        if not structure:
            return jsonify({'error': 'Structure not found'}), 404

        # Handle both dict and object returns
        s = structure if isinstance(structure, dict) else structure.__dict__

        return jsonify({
            'id': s.get('id'),
            'type': s.get('type'),
            'title': s.get('title'),
            'resolution': s.get('resolution'),
            'method': s.get('method'),
            'organism': s.get('organism'),
            'expression_system': s.get('expression_system'),
            'gene': s.get('gene'),
            'protein_name': s.get('protein_name'),
            'authors': s.get('authors'),
            'citation_count': s.get('citation_count'),
            'related_ids': s.get('related_ids'),
            'metadata': s.get('metadata_json')
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/literature/<int:lit_id>', methods=['GET'])
def get_structures_by_literature(lit_id):
    """
    Get structures associated with a literature entry
    Returns paired PDB/EMDB structures with links - 相同信息不重复显示
    """
    try:
        import sqlite3
        import re
        import json

        logger.info(f"[structure/literature] Querying structures for lit_id={lit_id}")

        conn = sqlite3.connect(MAIN_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 获取更完整的结构数据
        cursor.execute('''
            SELECT s.*, m.context, m.page_number, m.confidence, m.id as mapping_id
            FROM literature_structure_mapping m
            JOIN structures s ON m.structure_id = s.id
            WHERE m.literature_id = ?
            ORDER BY m.confidence DESC
        ''', (lit_id,))

        rows = cursor.fetchall()
        conn.close()

        # 如果没有映射到structures表，尝试从literature表的cryoem_targets获取
        if not rows:
            logger.info(f"[structure/literature] No mapping found, checking cryoem_targets field")
            try:
                from core.literature_db import get_literature_entry
                entry = get_literature_entry(lit_id)
                if entry and hasattr(entry, 'cryoem_targets') and entry.cryoem_targets:
                    cryoem_targets = entry.cryoem_targets
                    structures = []
                    # 从cryoem_targets中提取PDB/EMDB IDs并返回
                    if isinstance(cryoem_targets, dict):
                        pdb_ids = cryoem_targets.get('pdb_ids', [])
                        emdb_ids = cryoem_targets.get('emdb_ids', [])
                        for pdb_id in pdb_ids:
                            structures.append({
                                'id': pdb_id.upper(),
                                'structure_id': pdb_id.upper(),
                                'type': 'PDB',
                                'pdb_id': pdb_id.upper(),
                                'title': f'PDB Structure {pdb_id.upper()}',
                                'method': 'Cryo-EM',
                                'source': 'cryoem_targets'
                            })
                        for emdb_id in emdb_ids:
                            structures.append({
                                'id': emdb_id.upper(),
                                'structure_id': emdb_id.upper(),
                                'type': 'EMDB',
                                'emdb_id': emdb_id.upper(),
                                'title': f'EMDB Structure {emdb_id.upper()}',
                                'method': 'Cryo-EM',
                                'source': 'cryoem_targets'
                            })
                    if structures:
                        return jsonify({'structures': structures, 'source': 'cryoem_targets'})
            except Exception as e:
                logger.error(f"[structure/literature] Error reading cryoem_targets: {e}")

            return jsonify({'structures': []})

        def extract_protein_name(title):
            """从标题中提取蛋白质名称"""
            if not title:
                return ''
            # 匹配GPR家族
            gpr = re.search(r'\b(GPR[0-9]+[A-Z]?)\b', title, re.IGNORECASE)
            if gpr:
                return gpr.group(1).upper()
            # 匹配 "structure of X"
            match = re.search(r'structure\s+of\s+([A-Z][A-Za-z0-9]+)', title, re.IGNORECASE)
            if match:
                return match.group(1)
            return ''

        # 按文献ID分组结构 - 保存完整的结构信息
        structures_by_literature = {}
        for row in rows:
            s = dict(row)
            struct_type = (s.get('type') or '').upper()
            title = s.get('title') or ''
            protein_name = extract_protein_name(title)

            # 解析 related_ids 和其他JSON字段
            try:
                related_ids = json.loads(s.get('related_ids') or '[]')
            except:
                related_ids = []

            # 解析 uniprot_ids
            try:
                uniprot_ids = json.loads(s.get('uniprot_ids') or '[]')
            except:
                uniprot_ids = []

            # 获取实体序列（如果有）
            entity_sequence = s.get('sequence') or ''

            item = {
                'id': s.get('id'),
                'type': struct_type,
                'title': title,
                'resolution': s.get('resolution'),
                'method': s.get('method'),
                'organism': s.get('organism'),
                'protein_name': s.get('protein_name') or protein_name,
                'deposition_date': s.get('deposition_date'),
                'expression_system': s.get('expression_system'),
                'context': s.get('context'),
                'confidence': s.get('confidence'),
                'related_ids': related_ids,
                'uniprot_ids': uniprot_ids,
                'sequence': entity_sequence
            }

            structures_by_literature.setdefault(lit_id, []).append(item)

        lit_structs = structures_by_literature.get(lit_id, [])

        # PDB和EMDB列表
        pdbs = [s for s in lit_structs if s['type'] == 'PDB']
        emdbs = [s for s in lit_structs if s['type'] == 'EMDB']

        # 配对逻辑：按索引顺序配对，只配对一次
        results = []
        paired_pdb_indices = set()
        paired_emdb_indices = set()

        max_len = max(len(pdbs), len(emdbs)) if pdbs or emdbs else 0

        for i in range(max_len):
            pdb = pdbs[i] if i < len(pdbs) else None
            emdb = emdbs[i] if i < len(emdbs) else None

            if not pdb and not emdb:
                continue

            # 记录已配对的索引
            if pdb:
                paired_pdb_indices.add(i)
            if emdb:
                paired_emdb_indices.add(i)

            # 构建配对结果
            pair = {
                'id': f"{pdb['id']}-{emdb['id']}" if pdb and emdb else (pdb['id'] if pdb else emdb['id']),
                'title': pdb['title'] if pdb else emdb['title'],
                'resolution': pdb['resolution'] if pdb else emdb['resolution'],
                'method': pdb['method'] if pdb else emdb['method'],
                'organism': pdb['organism'] if pdb else emdb['organism'],
                'protein_name': pdb['protein_name'] if pdb else emdb['protein_name'],
                'deposition_date': pdb.get('deposition_date') if pdb else emdb.get('deposition_date'),
                'context': pdb.get('context') if pdb else emdb.get('context'),
                'confidence': pdb.get('confidence') if pdb else emdb.get('confidence'),
                'uniprot_ids': pdb.get('uniprot_ids', []) if pdb else emdb.get('uniprot_ids', []),
                'sequence': pdb.get('sequence', '') if pdb else emdb.get('sequence', ''),
            }

            # 添加 PDB 和 EMDB 详细信息
            if pdb:
                pair['pdb'] = {
                    'id': pdb['id'],
                    'title': pdb['title'],
                    'resolution': pdb['resolution'],
                    'method': pdb['method'],
                    'organism': pdb['organism'],
                    'protein_name': pdb['protein_name'],
                    'url': f"/structure/{pdb['id']}"
                }
            else:
                pair['pdb'] = None

            if emdb:
                emdb_id = emdb['id'].replace('EMD-', '').replace('EMDB:', '')
                pair['emdb'] = {
                    'id': emdb['id'],
                    'title': emdb['title'],
                    'resolution': emdb['resolution'],
                    'method': emdb['method'],
                    'organism': emdb['organism'],
                    'protein_name': emdb['protein_name'],
                    'url': f"https://www.ebi.ac.uk/emdb/EMD-{emdb_id}"
                }
            else:
                pair['emdb'] = None

            results.append(pair)

        # 添加剩余的未配对结构（只添加未配对的）
        if len(pdbs) > len(emdbs):
            for i in range(len(pdbs)):
                if i in paired_pdb_indices:
                    continue  # 跳过已配对的
                pdb = pdbs[i]
                results.append({
                    'id': pdb['id'],
                    'title': pdb['title'],
                    'resolution': pdb['resolution'],
                    'method': pdb['method'],
                    'organism': pdb['organism'],
                    'protein_name': pdb['protein_name'],
                    'deposition_date': pdb.get('deposition_date'),
                    'context': pdb.get('context'),
                    'confidence': pdb.get('confidence'),
                    'uniprot_ids': pdb.get('uniprot_ids', []),
                    'sequence': pdb.get('sequence', ''),
                    'pdb': {
                        'id': pdb['id'],
                        'title': pdb['title'],
                        'resolution': pdb['resolution'],
                        'method': pdb['method'],
                        'organism': pdb['organism'],
                        'protein_name': pdb['protein_name'],
                        'url': f"/structure/{pdb['id']}"
                    },
                    'emdb': None
                })
        elif len(emdbs) > len(pdbs):
            for i in range(len(emdbs)):
                if i in paired_emdb_indices:
                    continue  # 跳过已配对的
                emdb = emdbs[i]
                emdb_id = emdb['id'].replace('EMD-', '').replace('EMDB:', '')
                results.append({
                    'id': emdb['id'],
                    'title': emdb['title'],
                    'resolution': emdb['resolution'],
                    'method': emdb['method'],
                    'organism': emdb['organism'],
                    'protein_name': emdb['protein_name'],
                    'deposition_date': emdb.get('deposition_date'),
                    'context': emdb.get('context'),
                    'confidence': emdb.get('confidence'),
                    'uniprot_ids': emdb.get('uniprot_ids', []),
                    'sequence': emdb.get('sequence', ''),
                    'pdb': None,
                    'emdb': {
                        'id': emdb['id'],
                        'title': emdb['title'],
                        'resolution': emdb['resolution'],
                        'method': emdb['method'],
                        'organism': emdb['organism'],
                        'protein_name': emdb['protein_name'],
                        'url': f"https://www.ebi.ac.uk/emdb/EMD-{emdb_id}"
                    }
                })

        logger.info(f"[structure/literature] Returning {len(results)} paired structures")
        return jsonify({'structures': results, 'paired': True})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/batch', methods=['POST'])
def batch_get_structures():
    """Batch fetch multiple structures"""
    try:
        data = request.json
        structure_ids = data.get('ids', [])

        if not structure_ids:
            return jsonify({'error': 'No structure IDs provided'}), 400

        db = get_main_db()
        structures = db.batch_get_or_fetch_structures(structure_ids)

        result = {}
        for s_id, structure in structures.items():
            # Handle both dict and object returns
            s = structure if isinstance(structure, dict) else structure.__dict__
            type_val = s.get('type')
            if isinstance(type_val, str):
                type_display = type_val
            elif hasattr(type_val, 'value'):
                type_display = type_val.value
            else:
                type_display = str(type_val)
            result[s_id] = {
                'id': s.get('id'),
                'type': type_display,
                'title': s.get('title'),
                'resolution': s.get('resolution'),
                'method': s.get('method')
            }

        return jsonify({'structures': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/search', methods=['POST'])
def search_structures():
    """Search structures by protein name or keyword with pagination"""
    try:
        data = request.json or {}
        query = data.get('query', '').strip()
        limit = data.get('limit', 48)
        page = data.get('page', 1)
        offset = (page - 1) * limit
        logger.info(f"[structure/search] query='{query}', page={page}, limit={limit}")

        db = get_main_db()

        if not query:
            # Return all structures with pagination
            all_structs = db._get_all_structures(limit=10000)  # Get all for pagination
            total = len(all_structs)

            # Paginate
            paginated_structs = all_structs[offset:offset + limit]

            structures = []
            for s in paginated_structs:
                structures.append({
                    'id': s.get('id'),
                    'type': s.get('type'),
                    'title': s.get('title'),
                    'resolution': s.get('resolution'),
                    'method': s.get('method')
                })

            logger.info(f"[structure/search] Found {total} structures, returning {len(structures)} (page {page})")

            return jsonify({
                'structures': structures,
                'count': len(structures),
                'total': total,
                'page': page,
                'limit': limit,
                'total_pages': (total + limit - 1) // limit
            })
        else:
            # Search with pagination - try multiple search methods
            results = []

            # Method 1: Try protein mapper search
            try:
                results = db.find_structures_by_protein_name_mapper(query)
            except Exception as e:
                logger.warning(f"Protein mapper search failed: {e}")

            # Method 2: If no results, search by title or ID directly in database
            if not results:
                try:
                    import sqlite3
                    conn = sqlite3.connect(db.db_path)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    # Search by ID or title (case-insensitive)
                    search_pattern = f"%{query}%"
                    cursor.execute("""
                        SELECT id, type, title, resolution, method
                        FROM structures
                        WHERE UPPER(id) LIKE UPPER(?) OR UPPER(title) LIKE UPPER(?)
                        LIMIT 100
                    """, (search_pattern, search_pattern))
                    rows = cursor.fetchall()
                    conn.close()

                    if rows:
                        for row in rows:
                            results.append({
                                'id': row['id'],
                                'type': row['type'],
                                'title': row['title'],
                                'resolution': row['resolution'],
                                'method': row['method']
                            })
                except Exception as e:
                    logger.warning(f"Direct DB search failed: {e}")

            total = len(results)
            paginated_results = results[offset:offset + limit]

            structures = []
            for st in paginated_results:
                if st:
                    if isinstance(st, dict):
                        st_data = st
                    else:
                        st_data = st.__dict__
                    type_val = st_data.get('type')
                    if isinstance(type_val, str):
                        type_display = type_val
                    elif hasattr(type_val, 'value'):
                        type_display = type_val.value
                    else:
                        type_display = str(type_val)
                    structures.append({
                        'id': st_data.get('id'),
                        'type': type_display,
                        'title': st_data.get('title'),
                        'resolution': st_data.get('resolution'),
                        'method': st_data.get('method')
                    })

        return jsonify({
            'structures': structures,
            'count': len(structures),
            'total': total,
            'page': page,
            'limit': limit,
            'total_pages': (total + limit - 1) // limit
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/refresh/all', methods=['POST'])
def refresh_all_structures():
    """
    Refresh metadata for all structures in the database
    """
    try:
        import sqlite3
        # fetch_complete_metadata is defined at module level

        flask_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(os.path.dirname(flask_dir), 'data')
        db_path = os.path.join(data_dir, 'structure_offline.db')

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get all structure IDs
        cursor.execute('SELECT id FROM structures')
        rows = cursor.fetchall()
        structure_ids = [row['id'] for row in rows]

        conn.close()

        if not structure_ids:
            return jsonify({'success': True, 'message': 'No structures to refresh', 'count': 0})

        results = {'success': 0, 'failed': 0, 'errors': []}

        logger.info(f"[structure/refresh/all] Starting refresh for {len(structure_ids)} structures")

        for i, structure_id in enumerate(structure_ids):
            try:
                logger.info(f"[structure/refresh/all] {i+1}/{len(structure_ids)}: {structure_id}")

                # Fetch metadata
                metadata = fetch_complete_metadata(structure_id, fetch_uniprot=True)

                # Update database
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE structures SET
                        title = ?,
                        method = ?,
                        resolution = ?,
                        organism = ?,
                        release_date = ?,
                        deposition_date = ?,
                        authors = ?,
                        entities = ?,
                        uniprot_ids = ?,
                        last_updated = ?
                    WHERE id = ?
                ''', (
                    metadata.get('title', ''),
                    metadata.get('method', ''),
                    metadata.get('resolution'),
                    metadata.get('organism', ''),
                    metadata.get('release_date', ''),
                    metadata.get('deposition_date', ''),
                    metadata.get('authors', '[]'),
                    metadata.get('entities', '[]'),
                    metadata.get('uniprot_mappings', '[]'),
                    datetime.now().isoformat(),
                    structure_id
                ))

                conn.commit()
                conn.close()

                results['success'] += 1

                # Rate limiting
                time.sleep(0.5)

            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f"{structure_id}: {str(e)}")
                logger.error(f"[structure/refresh/all] Error refreshing {structure_id}: {e}")

        return jsonify({
            'success': True,
            'message': f'Refreshed {results["success"]}/{len(structure_ids)} structures',
            'count': len(structure_ids),
            'results': results
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
def refresh_structure_metadata(structure_id):
    """
    Refresh structure metadata from RCSB/PDBe APIs

    This endpoint fetches complete metadata from online APIs and updates
    the offline database with enriched information including:
    - Complete title
    - Resolution (from multiple sources)
    - Experimental method
    - Authors
    - Entity information (sequences, chains)
    - UniProt mappings
    """
    try:
        structure_id = structure_id.upper()
        logger.info(f"[structure/refresh] Refreshing metadata for {structure_id}")

        # Import the enhanced fetcher
        # fetch_complete_metadata is defined at module level

        # Fetch complete metadata
        metadata = fetch_complete_metadata(structure_id, fetch_uniprot=True)
        logger.info(f"[structure/refresh] Fetched metadata: title={metadata.get('title', '')[:50]}...")

        # Update database
        flask_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(os.path.dirname(flask_dir), 'data')
        db_path = os.path.join(data_dir, 'structure_offline.db')

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Check if structure exists
        cursor.execute('SELECT id FROM structures WHERE id = ?', (structure_id,))
        exists = cursor.fetchone()

        if exists:
            # Update existing structure
            cursor.execute('''
                UPDATE structures SET
                    title = ?,
                    method = ?,
                    resolution = ?,
                    organism = ?,
                    release_date = ?,
                    deposition_date = ?,
                    authors = ?,
                    entities = ?,
                    uniprot_ids = ?,
                    last_updated = ?
                WHERE id = ?
            ''', (
                metadata.get('title', ''),
                metadata.get('method', ''),
                metadata.get('resolution'),
                metadata.get('organism', ''),
                metadata.get('release_date', ''),
                metadata.get('deposition_date', ''),
                metadata.get('authors', '[]'),
                metadata.get('entities', '[]'),
                metadata.get('uniprot_mappings', '[]'),
                metadata.get('last_updated', ''),
                structure_id
            ))
            logger.info(f"[structure/refresh] Updated {structure_id} in database")
        else:
            # Insert new structure
            cursor.execute('''
                INSERT INTO structures (id, type, title, method, resolution, organism, release_date, deposition_date, authors, entities, uniprot_ids, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                structure_id,
                'pdb',
                metadata.get('title', ''),
                metadata.get('method', ''),
                metadata.get('resolution'),
                metadata.get('organism', ''),
                metadata.get('release_date', ''),
                metadata.get('deposition_date', ''),
                metadata.get('authors', '[]'),
                metadata.get('entities', '[]'),
                metadata.get('uniprot_mappings', '[]'),
                metadata.get('last_updated', '')
            ))
            logger.info(f"[structure/refresh] Inserted {structure_id} into database")

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'structure_id': structure_id,
            'metadata': {
                'title': metadata.get('title', ''),
                'method': metadata.get('method', ''),
                'resolution': metadata.get('resolution'),
                'release_date': metadata.get('release_date', ''),
                'entity_count': len(json.loads(metadata.get('entities', '[]'))),
                'uniprot_mapping_count': len(json.loads(metadata.get('uniprot_mappings', '[]')))
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/<path:structure_id>/detail', methods=['GET'])
def get_structure_detail_enhanced(structure_id):
    """
    Get enhanced structure detail including entities and sequences
    """
    try:
        structure_id = structure_id.upper()
        db = get_main_db()

        # Get basic structure info
        structure = db.get_structure(structure_id)
        if not structure:
            return jsonify({'error': 'Structure not found'}), 404

        # Handle dict vs object
        if isinstance(structure, dict):
            s = structure
        else:
            s = structure.__dict__

        # Parse JSON fields
        entities = []
        entities_data = s.get('entities')
        if entities_data:
            try:
                entities = json.loads(entities_data) if isinstance(entities_data, str) else entities_data
            except:
                entities = []

        uniprot_mappings = []
        uniprot_data = s.get('uniprot_ids')
        if uniprot_data:
            try:
                uniprot_mappings = json.loads(uniprot_data) if isinstance(uniprot_data, str) else uniprot_data
            except:
                uniprot_mappings = []

        authors = []
        authors_data = s.get('authors')
        if authors_data:
            try:
                authors = json.loads(authors_data) if isinstance(authors_data, str) else authors_data
            except:
                authors = []

        return jsonify({
            'id': s.get('id'),
            'type': s.get('type'),
            'title': s.get('title'),
            'resolution': s.get('resolution'),
            'method': s.get('method'),
            'organism': s.get('organism'),
            'expression_system': s.get('expression_system'),
            'gene': s.get('gene'),
            'protein_name': s.get('protein_name'),
            'release_date': s.get('release_date'),
            'authors': authors,
            'entities': entities,
            'uniprot_mappings': uniprot_mappings,
            'molecular_weight': s.get('molecular_weight'),
            'polymer_count': s.get('polymer_count'),
            'last_updated': s.get('last_updated')
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/<path:structure_id>/sequences', methods=['GET'])
def get_structure_sequences(structure_id):
    """
    Get all sequences for a structure (for sequence comparison)
    """
    try:
        structure_id = structure_id.upper()
        db = get_main_db()

        structure = db.get_structure(structure_id)
        if not structure:
            return jsonify({'error': 'Structure not found'}), 404

        # Parse entities for sequences
        entities = []
        if structure.entities:
            try:
                entities_data = json.loads(structure.entities) if isinstance(structure.entities, str) else structure.entities
                for entity in entities_data:
                    if entity.get('sequence'):
                        entities.append({
                            'entity_id': entity.get('entity_id'),
                            'description': entity.get('description', ''),
                            'sequence': entity.get('sequence', ''),
                            'length': len(entity.get('sequence', '')),
                            'chains': [c.get('chain_id') for c in entity.get('chains', [])],
                            'molecule_type': entity.get('molecule_type', '')
                        })
            except Exception as e:
                pass

        return jsonify({
            'pdb_id': structure_id,
            'entities': entities
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/sequences/compare', methods=['POST'])
def compare_sequences():
    """
    Compare sequences from multiple structures

    Request body:
    {
        "structures": [
            {"pdb_id": "6TTU", "entity_id": "1"},
            {"pdb_id": "3DVA", "entity_id": "1"}
        ]
    }
    """
    try:
        data = request.json or {}
        structures = data.get('structures', [])

        if len(structures) < 2:
            return jsonify({'error': 'Need at least 2 structures to compare'}), 400

        db = get_main_db()
        results = []

        for item in structures:
            pdb_id = item.get('pdb_id', '').upper()
            entity_id = item.get('entity_id', '')
            # Convert entity_id to int for comparison (DB stores as int)
            try:
                entity_id_int = int(entity_id) if entity_id else None
            except:
                entity_id_int = None

            structure = db.get_structure(pdb_id)
            # 处理字典和对象两种返回类型
            if structure:
                # 获取 entities 数据
                entities_data = None
                if isinstance(structure, dict):
                    entities_data = structure.get('entities')
                else:
                    entities_data = getattr(structure, 'entities', None)

                if entities_data:
                    try:
                        entities_data = json.loads(entities_data) if isinstance(entities_data, str) else entities_data
                        if isinstance(entities_data, str):
                            entities_data = json.loads(entities_data)
                    except Exception as e:
                        print(f"解析entities失败: {e}")
                        entities_data = None

                    if entities_data:
                        for entity in entities_data:
                            entity_id_val = entity.get('entity_id')
                            # Compare both int and string forms
                            if entity_id_int is None or entity_id_val == entity_id_int or str(entity_id_val) == str(entity_id):
                                if entity.get('sequence'):
                                    results.append({
                                        'pdb_id': pdb_id,
                                        'entity_id': entity_id_val,
                                        'description': entity.get('description', ''),
                                        'sequence': entity.get('sequence', ''),
                                        'length': len(entity.get('sequence', ''))
                                    })
                                    break

        # Calculate sequence similarities
        comparisons = []
        if len(results) >= 2:
            for i in range(len(results)):
                for j in range(i + 1, len(results)):
                    seq1 = results[i].get('sequence', '').upper()
                    seq2 = results[j].get('sequence', '').upper()

                    # Simple identity calculation
                    min_len = min(len(seq1), len(seq2))
                    matches = sum(1 for a, b in zip(seq1[:min_len], seq2[:min_len]) if a == b)
                    identity = (matches / min_len * 100) if min_len > 0 else 0

                    comparisons.append({
                        'seq1': results[i]['pdb_id'],
                        'seq2': results[j]['pdb_id'],
                        'identity': round(identity, 2),
                        'aligned_length': min_len,
                        'matches': matches
                    })

        return jsonify({
            'sequences': results,
            'comparisons': comparisons
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/sequences/compare-uniprot', methods=['POST'])
def compare_with_uniprot():
    """
    Compare PDB structure sequence with UniProt sequence

    Request body:
    {
        "pdb_id": "7EWL",
        "entity_id": "1",
        "uniprot_id": "Q5T848"
    }
    """
    try:
        data = request.json or {}
        pdb_id = data.get('pdb_id', '').upper()
        entity_id = data.get('entity_id', '1')
        uniprot_id = data.get('uniprot_id', '').strip()

        if not pdb_id or not uniprot_id:
            return jsonify({'error': '需要提供 pdb_id 和 uniprot_id'}), 400

        db = get_main_db()

        # Get PDB sequence
        pdb_sequence = ''
        structure = db.get_structure(pdb_id)
        if structure:
            # 处理字典和对象两种返回类型
            entities_data = None
            if isinstance(structure, dict):
                entities_data = structure.get('entities')
            else:
                entities_data = getattr(structure, 'entities', None)

            if entities_data:
                try:
                    entities_data = json.loads(entities_data) if isinstance(entities_data, str) else entities_data
                    if isinstance(entities_data, str):
                        entities_data = json.loads(entities_data)
                    # Convert entity_id to int for comparison
                    try:
                        entity_id_int = int(entity_id) if entity_id else None
                    except:
                        entity_id_int = None
                    for entity in entities_data:
                        entity_id_val = entity.get('entity_id')
                        # Compare both int and string forms
                        if entity_id_int is None or entity_id_val == entity_id_int or str(entity_id_val) == str(entity_id):
                            if entity.get('sequence'):
                                pdb_sequence = entity.get('sequence', '').upper()
                                break
                except Exception as e:
                    print(f"解析entities失败: {e}")

        if not pdb_sequence:
            return jsonify({'error': f'无法获取 {pdb_id} 的序列'}), 400

        # Get UniProt sequence directly from REST API
        uniprot_sequence = ''
        try:
            import requests
            # Use UniProt REST API to get protein sequence
            url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}.fasta"
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                # Parse FASTA format
                lines = response.text.strip().split('\n')
                # Skip header line starting with >
                uniprot_sequence = ''.join(line for line in lines[1:] if not line.startswith('>'))
                uniprot_sequence = uniprot_sequence.upper()
            else:
                logger.warning(f"UniProt API returned {response.status_code} for {uniprot_id}")
        except Exception as e:
            logger.warning(f"获取UniProt序列失败: {e}")

        if not uniprot_sequence:
            return jsonify({'error': f'无法获取 UniProt {uniprot_id} 的序列'}), 400

        # Get ALL UniProt mapping ranges for this entity
        # First check entity's uniprot_ranges (has both P29274 and P0ABE7)
        mapping_ranges = []

        # Get entities data from structure
        entities_data = None
        if structure:
            if isinstance(structure, dict):
                entities_data = structure.get('entities')
            else:
                entities_data = getattr(structure, 'entities', None)

        # Find the entity and its uniprot_ranges
        entity_uniprot_ranges = []
        if entities_data:
            try:
                entities_data = json.loads(entities_data) if isinstance(entities_data, str) else entities_data
                if isinstance(entities_data, str):
                    entities_data = json.loads(entities_data)
                entity_id_int = int(entity_id) if entity_id else None
                logger.info(f"[compare_uniprot] entity_id={entity_id}, entity_id_int={entity_id_int}")
                for entity in entities_data:
                    entity_id_val = entity.get('entity_id')
                    logger.info(f"[compare_uniprot] Checking entity_id_val={entity_id_val}")
                    if entity_id_int is not None and (entity_id_val == entity_id_int or str(entity_id_val) == str(entity_id)):
                        # Found the entity - get its uniprot_ranges
                        entity_uniprot_ranges = entity.get('uniprot_ranges', [])
                        logger.info(f"[compare_uniprot] Found entity, ranges count: {len(entity_uniprot_ranges)}")
                        break
            except Exception as e:
                logger.warning(f"解析entities失败: {e}")

        # Use entity's uniprot_ranges if available
        print(f"DEBUG: entity_uniprot_ranges has {len(entity_uniprot_ranges)} items")
        if entity_uniprot_ranges:
            for mapping in entity_uniprot_ranges:
                if mapping.get('uniprot_id', '').upper() == uniprot_id.upper():
                    if mapping.get('pdb_start') and mapping.get('pdb_end') and mapping.get('unp_start') and mapping.get('unp_end'):
                        mapping_ranges.append({
                            'pdb_start': int(mapping.get('pdb_start', 1)),
                            'pdb_end': int(mapping.get('pdb_end', len(pdb_sequence))),
                            'unp_start': int(mapping.get('unp_start', 1)),
                            'unp_end': int(mapping.get('unp_end', len(uniprot_sequence)))
                        })
        else:
            # Fallback to structure's uniprot_ids
            if structure:
                uniprot_ids_data = None
                if isinstance(structure, dict):
                    uniprot_ids_data = structure.get('uniprot_ids')
                else:
                    uniprot_ids_data = getattr(structure, 'uniprot_ids', None)

                if uniprot_ids_data:
                    try:
                        # Handle double-encoded JSON
                        uniprot_mappings = json.loads(uniprot_ids_data) if isinstance(uniprot_ids_data, str) else uniprot_ids_data
                        if isinstance(uniprot_mappings, str):
                            uniprot_mappings = json.loads(uniprot_mappings)
                        for mapping in uniprot_mappings:
                            if mapping.get('uniprot_id', '').upper() == uniprot_id.upper():
                                # Check if this mapping matches the entity
                                mapping_entity_id = mapping.get('entity_id')
                                if str(mapping_entity_id) == str(entity_id) or mapping_entity_id == entity_id:
                                    if mapping.get('start') and mapping.get('end'):
                                        # Check if we have UniProt positions (unp_start/unp_end) or use PDB positions
                                        unp_start = mapping.get('unp_start') or mapping.get('start')
                                        unp_end = mapping.get('unp_end') or mapping.get('end')
                                        mapping_ranges.append({
                                            'pdb_start': int(mapping.get('start', 1)),
                                            'pdb_end': int(mapping.get('end', len(pdb_sequence))),
                                            'unp_start': int(unp_start),
                                            'unp_end': int(unp_end)
                                        })
                    except Exception as e:
                        logger.warning(f"解析uniprot_mappings失败: {e}")

        # Sort by PDB position
        mapping_ranges.sort(key=lambda x: x['pdb_start'])
        logger.info(f"[compare_uniprot] Before dedup: {len(mapping_ranges)} ranges: {mapping_ranges}")
        print(f"DEBUG: Before dedup - {len(mapping_ranges)} ranges: {mapping_ranges}")

        # Remove duplicate mapping ranges (same start/end pairs)
        unique_ranges = []
        seen = set()
        for r in mapping_ranges:
            key = (r['pdb_start'], r['pdb_end'], r['unp_start'], r['unp_end'])
            if key not in seen:
                seen.add(key)
                unique_ranges.append(r)
        mapping_ranges = unique_ranges
        logger.info(f"[compare_uniprot] After dedup: {len(mapping_ranges)} ranges")

        # Extract corresponding sequence segments based on unique mapping ranges
        pdb_segments = []
        uniprot_segments = []

        for mapping_range in mapping_ranges:
            p_start = mapping_range['pdb_start'] - 1
            p_end = mapping_range['pdb_end']
            u_start = mapping_range['unp_start'] - 1
            u_end = mapping_range['unp_end']

            if p_start < len(pdb_sequence) and p_end <= len(pdb_sequence):
                pdb_segments.append(pdb_sequence[p_start:p_end])
            if u_start < len(uniprot_sequence) and u_end <= len(uniprot_sequence):
                uniprot_segments.append(uniprot_sequence[u_start:u_end])

        # Join segments - these are the mapped residues only (317 aa)
        pdb_segment = ''.join(pdb_segments)
        uniprot_segment = ''.join(uniprot_segments)

        # DON'T use Biopython - the mapped segments are already aligned by position!
        # Just compare them position by position
        aligned_pdb = pdb_segment
        aligned_uniprot = uniprot_segment
        identity = 0
        matches = 0

        # Calculate identity by comparing position by position (excluding gaps)
        if pdb_segment and uniprot_segment:
            min_len = min(len(pdb_segment), len(uniprot_segment))
            if min_len > 0:
                # Only count matches where both are NOT gaps
                matches = sum(1 for a, b in zip(pdb_segment[:min_len], uniprot_segment[:min_len]) if a == b and a != '-' and b != '-')
                total_compared = sum(1 for a, b in zip(pdb_segment[:min_len], uniprot_segment[:min_len]) if a != '-' and b != '-')
                if total_compared > 0:
                    identity = (matches / total_compared * 100)

        aligned_length = len(aligned_pdb)

        # Create full alignment: iterate through all UniProt positions
        # For each position, find if it's in a mapped range
        full_pdb_chars = []
        full_uniprot_chars = []

        # Sort mapping ranges
        sorted_ranges = sorted(mapping_ranges, key=lambda x: x['unp_start'])

        # Add N-terminal gaps based on first mapping's PDB start position
        # The first mapped PDB position tells us where the actual protein starts
        n_terminal_gaps = 0
        if sorted_ranges:
            first_pdb_start = sorted_ranges[0].get('pdb_start', 1)
            first_unp_start = sorted_ranges[0].get('unp_start', 1)
            # If PDB starts at position 9 but UniProt starts at 1, we need gaps for UniProt 1 to (PDB_start - 1)
            n_terminal_gaps = max(0, first_pdb_start - first_unp_start)

        # Get PDB entity's resolved residue range
        pdb_start_res = 1
        pdb_end_res = len(pdb_sequence)
        logger.info(f"[compare_uniprot] Looking for entity range, len(pdb_sequence)={len(pdb_sequence)}")
        if structure:
            # Try to get from entity first
            entities_data = structure.get('entities') if isinstance(structure, dict) else None
            logger.info(f"[compare_uniprot] entities_data type: {type(entities_data)}")
            if entities_data:
                try:
                    if isinstance(entities_data, str):
                        entities_data = json.loads(entities_data)
                    logger.info(f"[compare_uniprot] entities count: {len(entities_data)}")
                    entity_id_int = int(entity_id) if entity_id else None
                    for entity in entities_data:
                        entity_id_val = entity.get('entity_id')
                        logger.info(f"[compare_uniprot] Checking entity {entity_id_val}")
                        if entity_id_int is not None and (entity_id_val == entity_id_int or str(entity_id_val) == str(entity_id)):
                            pdb_start_res = entity.get('start_residue', 1)
                            pdb_end_res = entity.get('end_residue', len(pdb_sequence))
                            logger.info(f"[compare_uniprot] Entity found: start_res={pdb_start_res}, end_res={pdb_end_res}")
                            break
                except Exception as e:
                    logger.warning(f"[compare_uniprot] Error getting entity range: {e}")
        logger.info(f"[compare_uniprot] Using pdb_start_res={pdb_start_res}, pdb_end_res={pdb_end_res}")

        # Build full alignment with both sequences displayed fully
        # Approach: iterate through all positions in order, showing gaps where needed

        # Find max positions
        max_mapped_pdb = max([r['pdb_end'] for r in sorted_ranges], default=0)
        max_mapped_unp = max([r['unp_end'] for r in sorted_ranges], default=0)
        max_pdb = len(pdb_sequence)
        max_unp = len(uniprot_sequence)
        logger.info(f"[compare_uniprot] max_mapped_pdb={max_mapped_pdb}, max_mapped_unp={max_mapped_unp}, max_pdb={max_pdb}, pdb_seq_len={len(pdb_sequence)}")

        # Create mapping lookups
        unp_to_pdb = {}  # unp_pos -> pdb_pos
        pdb_to_unp = {}  # pdb_pos -> unp_pos
        for mapping in sorted_ranges:
            for offset in range(mapping['pdb_end'] - mapping['pdb_start'] + 1):
                pdb_pos = mapping['pdb_start'] + offset
                unp_pos = mapping['unp_start'] + offset
                unp_to_pdb[unp_pos] = pdb_pos
                pdb_to_unp[pdb_pos] = unp_pos

        # Track what's been output
        full_pdb_chars = []
        full_uniprot_chars = []

        # Phase 1: Iterate through all PDB positions (1 to max_pdb)
        # For each PDB position, find if it maps to UniProt
        for pdb_pos in range(1, max_pdb + 1):
            unp_pos = pdb_to_unp.get(pdb_pos)
            if unp_pos:
                # PDB position maps to UniProt - show both residues
                if pdb_pos <= len(pdb_sequence) and unp_pos <= len(uniprot_sequence):
                    full_pdb_chars.append(pdb_sequence[pdb_pos - 1])
                    full_uniprot_chars.append(uniprot_sequence[unp_pos - 1])
            else:
                # PDB position doesn't map to UniProt (e.g., 776-781) - show gap in UniProt
                if pdb_pos <= len(pdb_sequence):
                    full_pdb_chars.append(pdb_sequence[pdb_pos - 1])
                    full_uniprot_chars.append('-')

        # Phase 2: Add any UniProt positions that extend beyond PDB
        # (C-terminal extensions in UniProt that aren't in the resolved structure)
        for unp_pos in range(max_mapped_unp + 1, max_unp + 1):
            full_pdb_chars.append('-')
            full_uniprot_chars.append(uniprot_sequence[unp_pos - 1])

        full_aligned_pdb = ''.join(full_pdb_chars)
        full_aligned_uniprot = ''.join(full_uniprot_chars)

        return jsonify({
            'sequences': [
                {
                    'pdb_id': pdb_id,
                    'entity_id': entity_id,
                    'sequence': pdb_sequence,
                    'segment': pdb_segment,
                    'aligned': aligned_pdb,
                    'full_aligned': full_aligned_pdb,
                    'length': len(pdb_sequence),
                    'segment_start': mapping_ranges[0]['pdb_start'] if mapping_ranges else 1,
                    'segment_end': mapping_ranges[-1]['pdb_end'] if mapping_ranges else len(pdb_sequence)
                },
                {
                    'uniprot_id': uniprot_id,
                    'sequence': uniprot_sequence,
                    'segment': ''.join(uniprot_segments),
                    'aligned': aligned_uniprot,
                    'full_aligned': full_aligned_uniprot,
                    'length': len(uniprot_sequence),
                    'segment_start': mapping_ranges[0]['unp_start'] if mapping_ranges else 1,
                    'segment_end': mapping_ranges[-1]['unp_end'] if mapping_ranges else len(uniprot_sequence)
                }
            ],
            'comparisons': [
                {
                    'seq1': f'{pdb_id} (Entity {entity_id})',
                    'seq2': f'UniProt {uniprot_id}',
                    'identity': round(identity, 2),
                    'aligned_length': aligned_length,
                    'matches': matches,
                    'mapping_ranges': mapping_ranges
                }
            ]
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/refresh/<path:structure_id>', methods=['POST'])
def refresh_single_structure(structure_id):
    """
    Refresh metadata for a single structure from RCSB/PDBe APIs
    """
    try:
        # fetch_complete_metadata is defined at module level
        import sqlite3

        structure_id = structure_id.upper()
        logger.info(f"[structure/refresh] Refreshing metadata for {structure_id}")

        flask_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(os.path.dirname(flask_dir), 'data')
        db_path = os.path.join(data_dir, 'structure_offline.db')

        # Fetch metadata
        metadata = fetch_complete_metadata(structure_id, fetch_uniprot=True)
        logger.info(f"[structure/refresh] Fetched: resolution={metadata.get('resolution')}")

        # Update database
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Check if structure exists
        cursor.execute('SELECT id FROM structures WHERE id = ?', (structure_id,))
        exists = cursor.fetchone()

        resolution = metadata.get('resolution')
        if resolution is not None:
            try:
                resolution = float(resolution)
            except (ValueError, TypeError):
                resolution = None

        if exists:
            cursor.execute('''
                UPDATE structures SET
                    title = ?,
                    method = ?,
                    resolution = ?,
                    organism = ?,
                    release_date = ?,
                    deposition_date = ?,
                    authors = ?,
                    entities = ?,
                    uniprot_ids = ?,
                    has_metadata = 1,
                    last_updated = ?
                WHERE id = ?
            ''', (
                metadata.get('title', '')[:500],
                metadata.get('method', ''),
                resolution,
                metadata.get('organism', ''),
                metadata.get('release_date', ''),
                metadata.get('deposition_date', ''),
                json.dumps(metadata.get('authors', [])),
                json.dumps(metadata.get('entities', [])),
                json.dumps(metadata.get('uniprot_mappings', [])),
                datetime.now().isoformat(),
                structure_id
            ))
            logger.info(f"[structure/refresh] Updated {structure_id}")
        else:
            cursor.execute('''
                INSERT INTO structures (id, type, title, method, resolution, organism, release_date, deposition_date, authors, entities, uniprot_ids, has_metadata, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ''', (
                structure_id,
                'pdb',
                metadata.get('title', '')[:500],
                metadata.get('method', ''),
                resolution,
                metadata.get('organism', ''),
                metadata.get('release_date', ''),
                metadata.get('deposition_date', ''),
                json.dumps(metadata.get('authors', [])),
                json.dumps(metadata.get('entities', [])),
                json.dumps(metadata.get('uniprot_mappings', [])),
                datetime.now().isoformat()
            ))
            logger.info(f"[structure/refresh] Inserted {structure_id}")

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'structure_id': structure_id,
            'metadata': {
                'title': metadata.get('title', '')[:100],
                'method': metadata.get('method', ''),
                'resolution': resolution,
                'release_date': metadata.get('release_date', '')
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/literature/<int:lit_id>/refresh', methods=['POST'])
def refresh_literature_structures(lit_id):
    """
    Refresh metadata for all structures associated with a literature entry
    """
    try:
        # fetch_complete_metadata is defined at module level
        import sqlite3

        flask_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(os.path.dirname(flask_dir), 'data')
        db_path = os.path.join(data_dir, 'structure_offline.db')

        # Get all structure IDs for this literature
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT DISTINCT s.id, s.type, s.resolution
            FROM literature_structure_mapping m
            JOIN structures s ON m.structure_id = s.id
            WHERE m.literature_id = ?
        ''', (lit_id,))

        structures = cursor.fetchall()
        conn.close()

        if not structures:
            return jsonify({'success': True, 'message': 'No structures found', 'refreshed': 0})

        refreshed = 0
        errors = []

        for row in structures:
            struct_id = row['id']
            try:
                if row['resolution'] is None:
                    # Only refresh if no resolution data
                    metadata = fetch_complete_metadata(struct_id, fetch_uniprot=False)
                    resolution = metadata.get('resolution')

                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute('''
                        UPDATE structures SET
                            title = ?,
                            method = ?,
                            resolution = ?,
                            has_metadata = 1,
                            last_updated = ?
                        WHERE id = ?
                    ''', (
                        metadata.get('title', '')[:500] if metadata.get('title') else None,
                        metadata.get('method', ''),
                        resolution,
                        datetime.now().isoformat(),
                        struct_id
                    ))
                    conn.commit()
                    conn.close()
                    refreshed += 1
                    time.sleep(0.3)  # Rate limiting

            except Exception as e:
                errors.append(f"{struct_id}: {str(e)}")

        return jsonify({
            'success': True,
            'message': f'Refreshed {refreshed}/{len(structures)} structures',
            'refreshed': refreshed,
            'total': len(structures),
            'errors': errors
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/uniprot/batch', methods=['POST'])
def get_uniprot_batch():
    """
    Batch fetch UniProt metadata for multiple UniProt IDs
    """
    try:
        data = request.get_json()
        uniprot_ids = data.get('uniprot_ids', [])

        if not uniprot_ids:
            return jsonify({'error': 'No UniProt IDs provided'}), 400

        import requests

        results = {}
        for uid in uniprot_ids[:20]:  # Limit to 20 at a time
            try:
                # Fetch from UniProt REST API
                url = f"https://rest.uniprot.org/uniprotkb/{uid}.json"
                response = requests.get(url, timeout=15)

                if response.status_code == 200:
                    data = response.json()

                    # Extract relevant fields
                    entry = {
                        'uniprot_id': uid,
                        'entry_name': data.get('primaryAccession'),
                        'protein_name': '',
                        'gene_names': [],
                        'organism': '',
                        'organism_id': None,
                        'sequence_length': 0,
                        'mass': 0,
                        'pdb_ids': [],
                        'function': '',
                        'keywords': []
                    }

                    # Protein name
                    if data.get('proteinDescription'):
                        rec = data['proteinDescription'].get('recommendedName', {})
                        if rec:
                            entry['protein_name'] = rec.get('fullName', {}).get('value', '')

                    # Gene names
                    if data.get('genes'):
                        for gene in data['genes']:
                            if gene.get('geneName'):
                                entry['gene_names'].append(gene['geneName'].get('value', ''))

                    # Organism
                    if data.get('organism'):
                        entry['organism'] = data['organism'].get('scientificName', '')
                        entry['organism_id'] = data['organism'].get('taxonId')

                    # Sequence info
                    if data.get('sequence'):
                        entry['sequence_length'] = data['sequence'].get('length', 0)
                        entry['mass'] = data['sequence'].get('molWeight', 0)

                    # PDB cross-references
                    if data.get('uniProtKBMappedReferences'):
                        for ref in data['uniProtKBMappedReferences']:
                            if ref.get('database') == 'PDB':
                                pdb_id = ref.get('properties', {}).get('pdbAccession')
                                if pdb_id:
                                    entry['pdb_ids'].append(pdb_id.upper())

                    # Keywords - filter out empty ones
                    if data.get('keywords'):
                        keywords_list = []
                        for k in data.get('keywords', [])[:15]:
                            # UniProt format: {'id': 'KW-xxx', 'category': '...', 'name': '...'}
                            kw_name = k.get('name') if isinstance(k, dict) else None
                            if kw_name:
                                keywords_list.append(kw_name)
                        entry['keywords'] = keywords_list

                    # Function
                    if data.get('comments'):
                        for comment in data['comments']:
                            if comment.get('type') == 'FUNCTION':
                                entry['function'] = comment.get('texts', [{}])[0].get('value', '')[:500]
                                break

                    results[uid.upper()] = entry
                else:
                    results[uid.upper()] = {'error': f'HTTP {response.status_code}'}

            except Exception as e:
                results[uid.upper()] = {'error': str(e)}

        return jsonify({
            'success': True,
            'results': results
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
