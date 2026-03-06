#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Flask API Server for CryoAgent Pro
运行方式: python app.py
"""
import os
import sys

# 确保 flask_app 目录在 Python 路径中
app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

from flask import Flask, jsonify, render_template, redirect, url_for
from flask_cors import CORS
from flask_login import login_required, current_user
import logging
import sqlite3
import json as json_mod
import requests

# Import configuration
from config import Config

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建 Flask 应用
app = Flask(__name__, template_folder='templates')
app.config.from_object(Config)

# Load user configuration (ai_config.json) and override defaults
from routes.config import load_config as load_ai_config
_ai_config = load_ai_config()
if _ai_config.get('vector_engine'):
    app.config['VECTOR_ENGINE'] = _ai_config['vector_engine']
    logger.info(f"Loaded VECTOR_ENGINE from config: {app.config['VECTOR_ENGINE']}")

# Load reranker setting
if _ai_config.get('reranker_enabled') is not None:
    app.config['USE_RERANK'] = _ai_config['reranker_enabled']
    logger.info(f"Loaded USE_RERANK from config: {app.config['USE_RERANK']}")

# Load Jina API key to environment if configured
if _ai_config.get('jina_api_key'):
    os.environ['JINA_API_KEY'] = _ai_config['jina_api_key']
    logger.info("Loaded JINA_API_KEY from config")

app.config['SERVER_NAME'] = 'localhost:5000'
app.config['APPLICATION_ROOT'] = '/'
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cryoagent-pro-secret-key-change-in-production')
CORS(app)

# 打印模板路径以便调试
print(f"Template folder: {app.template_folder}")

# 初始化Flask-Login
from routes.auth import init_login_manager
init_login_manager(app)

# 添加当前用户到模板上下文
from flask_login import current_user
@app.context_processor
def inject_user():
    return dict(current_user=current_user)

# 注册蓝图
from routes import literature, search, structure, qa, upload, feishu, config as route_config, utils as route_utils
from routes import alignment, kg, evaluation
from routes import auth
from routes import qa_agent
from routes import skills
from routes import pymol

# 注册所有蓝图
app.register_blueprint(auth.bp)
app.register_blueprint(literature.bp, url_prefix='/api/literature')
app.register_blueprint(search.bp, url_prefix='/api/search')
app.register_blueprint(structure.bp, url_prefix='/api/structure')
app.register_blueprint(qa.bp, url_prefix='/api/qa')
app.register_blueprint(upload.bp, url_prefix='/api/upload')
app.register_blueprint(feishu.bp, url_prefix='/api/feishu')
app.register_blueprint(route_config.bp)
app.register_blueprint(route_utils.bp, url_prefix='/api/utils')
app.register_blueprint(alignment.bp, url_prefix='/api/alignment')
app.register_blueprint(kg.bp, url_prefix='/api/kg')
app.register_blueprint(evaluation.bp, url_prefix='/api/evaluation')
app.register_blueprint(qa_agent.bp, url_prefix='/api/qa/agent')
app.register_blueprint(skills.bp)
app.register_blueprint(pymol.bp, url_prefix='/api/pymol')

# HTML页面路由 - 需要登录
@app.route('/')
def index():
    """主页面 - 允许访客访问"""
    return render_template('qa.html')

@app.route('/literature')
def literature_page():
    """文献页面 - 允许访客访问"""
    return render_template('literature.html')

@app.route('/literature/<int:lit_id>')
@login_required
def literature_detail_page(lit_id):
    return render_template('literature_detail.html', lit_id=lit_id)

@app.route('/structures')
@login_required
def structures_page():
    return render_template('structures.html')

@app.route('/structure/<pdb_id>')
@login_required
def structure_detail_page(pdb_id):
    """Get structure detail page with data"""
    try:
        from flask_app.routes.structure import get_main_db

        db = get_main_db()
        structure = db.get_structure(pdb_id)

        # If not in offline DB, try to fetch from RCSB API
        if not structure:
            pdb_id_upper = pdb_id.upper()
            logger.info(f"Structure {pdb_id} not in offline DB, fetching from RCSB...")
            rcsb_url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id_upper}"
            try:
                rcsb_resp = requests.get(rcsb_url, timeout=15)
                if rcsb_resp.status_code == 200:
                    rcsb_data = rcsb_resp.json()
                    # Convert RCSB data to structure format
                    struct_dict = {
                        'pdb_id': pdb_id_upper,
                        'title': rcsb_data.get('title', ''),
                        'experimental_method': rcsb_data.get('exptl_method', ''),
                        'resolution': None,
                        'uniprot_ids': [],
                        'citations': [],
                        'source': 'rcsb'
                    }
                    # Get resolution
                    if rcsb_data.get('rcsb_entry_info'):
                        res = rcsb_data['rcsb_entry_info'].get('resolution_combined')
                        if res and isinstance(res, list) and len(res) > 0:
                            struct_dict['resolution'] = res[0]
                    # Get primary citation
                    primary_cit = rcsb_data.get('rcsb_primary_citation', {})
                    if primary_cit:
                        struct_dict['citations'] = [{
                            'title': primary_cit.get('title', ''),
                            'journal': primary_cit.get('journal_abbrev', ''),
                            'year': primary_cit.get('year'),
                            'authors': primary_cit.get('rcsb_authors', [])
                        }]
                    structure = struct_dict
                    logger.info(f"Successfully fetched {pdb_id} from RCSB")
                else:
                    return f"Structure {pdb_id} not found", 404
            except Exception as e:
                logger.error(f"Failed to fetch from RCSB: {e}")
                return f"Structure {pdb_id} not found", 404

        # Convert to dict if needed
        if hasattr(structure, '__dict__'):
            structure = structure.__dict__

        # Group uniprot_ids by unique UniProt ID
        uniprot_ids = structure.get('uniprot_ids', [])
        if isinstance(uniprot_ids, str):
            try:
                uniprot_ids = json_mod.loads(uniprot_ids)
            except:
                uniprot_ids = []

        # Group by unique UniProt ID and fetch protein names
        unique_uniprots = {}
        uniprot_id_list = []

        for mapping in uniprot_ids[:50]:  # Limit to 50
            # Handle both string format and dict format
            if isinstance(mapping, str):
                # String format: 'G9G864' -> convert to dict
                uid = mapping.upper()
                if uid not in unique_uniprots:
                    unique_uniprots[uid] = {
                        'uniprot_id': mapping,
                        'chains': [],
                        'ranges': [],
                        'protein_name': ''
                    }
                    uniprot_id_list.append(uid)
                continue
            if not isinstance(mapping, dict):
                continue
            if mapping.get('uniprot_id'):
                uid = mapping['uniprot_id'].upper()
                if uid not in unique_uniprots:
                    unique_uniprots[uid] = {
                        'uniprot_id': mapping['uniprot_id'],
                        'chains': [],
                        'ranges': [],
                        'protein_name': ''
                    }
                    uniprot_id_list.append(uid)

                entry = unique_uniprots[uid]
                if mapping.get('chain_id') and mapping['chain_id'] not in entry['chains']:
                    entry['chains'].append(mapping['chain_id'])
                range_str = f"{mapping.get('start', '')}-{mapping.get('end', '')}"
                if range_str not in entry['ranges']:
                    entry['ranges'].append(range_str)

        # Fetch UniProt protein names - 优先从离线数据库查询，只有查不到时才调用API
        if uniprot_id_list:
            try:
                # 先尝试从离线数据库的 uniprot_structure_mapping 表获取蛋白质名称
                struct_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'structure_offline.db')
                uniprot_conn = sqlite3.connect(struct_db_path)
                uniprot_cursor = uniprot_conn.cursor()

                # 批量查询蛋白质名称
                placeholders = ','.join(['?'] * len(uniprot_id_list[:50]))
                query = f'SELECT uniprot_id, protein_name FROM uniprot_structure_mapping WHERE uniprot_id IN ({placeholders})'
                uniprot_cursor.execute(query, [uid.upper() for uid in uniprot_id_list[:50]])
                db_results = {row[0].upper(): row[1] for row in uniprot_cursor.fetchall()}
                uniprot_conn.close()

                # 将数据库中的蛋白质名称填入 unique_uniprots
                for uid in uniprot_id_list:
                    if uid.upper() in db_results and db_results[uid.upper()]:
                        unique_uniprots[uid]['protein_name'] = db_results[uid.upper()]

                # 检查哪些UniProt ID还需要从API获取
                uniprots_needing_fetch = [
                    uid for uid in uniprot_id_list[:10]
                    if unique_uniprots[uid]['protein_name'] == ''
                ]

                # 只有当有UniProt ID需要获取蛋白质名称时才调用API
                if uniprots_needing_fetch:
                    logger.info(f"Fetching protein names for {len(uniprots_needing_fetch)} UniProt IDs from API")
                    for uid in uniprots_needing_fetch:
                        url = f"https://rest.uniprot.org/uniprotkb/{uid}.json"
                        resp = requests.get(url, timeout=10)
                        if resp.status_code == 200:
                            data = resp.json()
                            if data.get('proteinDescription'):
                                rec = data['proteinDescription'].get('recommendedName', {})
                                if rec:
                                    unique_uniprots[uid]['protein_name'] = rec.get('fullName', {}).get('value', '')[:50]
            except Exception as e:
                print(f"Failed to fetch UniProt names: {e}")

        structure['unique_uniprots'] = unique_uniprots

        # Also build structure.uniprot_ids in dict format for template compatibility
        # The template expects list of dicts with entity_id and uniprot_id
        structure_uniprot_ids = []
        entities = structure.get('entities', [])
        for entity in entities:
            entity_id = entity.get('entity_id')
            entity_uniprots = entity.get('uniprot_ids', [])
            for uid in entity_uniprots:
                structure_uniprot_ids.append({
                    'entity_id': entity_id,
                    'uniprot_id': uid
                })
        structure['uniprot_ids'] = structure_uniprot_ids

        # Parse authors if it's a JSON string
        authors = structure.get('authors', [])
        if isinstance(authors, str):
            try:
                structure['authors'] = json_mod.loads(authors)
            except:
                structure['authors'] = []

        # If authors are empty, try to get from linked literature
        if not structure.get('authors') or len(structure.get('authors', [])) == 0:
            try:
                # Use structure_offline.db which has the literature_structure_mapping table
                struct_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'structure_offline.db')
                lit_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'literature.db')

                # First get the linked literature IDs from structure_offline.db
                struct_conn = sqlite3.connect(struct_db_path)
                struct_cursor = struct_conn.cursor()
                struct_cursor.execute('SELECT literature_id FROM literature_structure_mapping WHERE structure_id = ?', (pdb_id.upper(),))
                lit_rows = struct_cursor.fetchall()
                struct_conn.close()

                if lit_rows:
                    # Then get authors from literature.db
                    lit_conn = sqlite3.connect(lit_db_path)
                    lit_cursor = lit_conn.cursor()

                    lit_id = lit_rows[0][0]
                    lit_cursor.execute('SELECT id, title, authors FROM literature_entries WHERE id = ?', (lit_id,))
                    lit_row = lit_cursor.fetchone()

                    if lit_row:
                        lit_authors = lit_row[2]
                        if lit_authors:
                            try:
                                structure['authors'] = json_mod.loads(lit_authors)
                                print(f"Got authors from literature {lit_row[0]}: {lit_row[1][:30]}...")
                            except:
                                structure['authors'] = []

                    lit_conn.close()
            except Exception as e:
                print(f"Error getting authors from literature: {e}")

        # Build related_structures - find paired EMDB from database
        emdb_ids = []

        # Use structure_relationships table for accurate PDB-EMDB mapping
        try:
            # Use data directory in flask_app
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'structure_offline.db')
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Find EMDB associated with this PDB from structure_relationships
            cursor.execute('''
                SELECT target_id FROM structure_relationships
                WHERE source_id = ? AND relationship_type = 'pdb_to_emdb'
            ''', (pdb_id.upper(),))

            for row in cursor.fetchall():
                emdb_ids.append(row[0])

            conn.close()
        except Exception as e:
            print(f"Error finding related structures: {e}")

        # Build related_structures structure
        structure['related_structures'] = {
            'emdb_ids': emdb_ids
        }

        # Get stats for sidebar
        try:
            from core.literature_db import get_literature_stats
            stats = get_literature_stats()
        except Exception as e:
            print(f"Error getting stats: {e}")
            stats = {'total_count': 0, 'parsed_count': 0, 'with_structure_count': 0}

        return render_template('structure_detail.html', pdb_id=pdb_id, structure=structure, stats=stats)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Error loading structure: {str(e)}", 500

@app.route('/qa')
@login_required
def qa_page():
    return render_template('qa.html')

@app.route('/settings')
@login_required
def settings_page():
    """Redirect to /config for unified configuration page"""
    from flask import redirect, url_for
    return redirect(url_for('config.config_page'))

# Config page is handled by blueprint at /api/config/

@app.route('/feishu/documents')
@login_required
def feishu_documents_page():
    return render_template('feishu_documents.html')

@app.route('/themes')
@login_required
def themes_page():
    return render_template('themes.html')

@app.route('/alignment')
@login_required
def alignment_page():
    return render_template('alignment.html')

@app.route('/knowledge-graph')
@login_required
def knowledge_graph_page():
    return render_template('knowledge_graph.html')

@app.route('/evaluation')
@login_required
def evaluation_page():
    return render_template('evaluation.html')

@app.route('/api/')
def api_index():
    return jsonify({
        'available_endpoints': [
            '/api/literature',
            '/api/search',
            '/api/structure',
            '/api/qa',
            '/api/upload',
            '/api/feishu',
            '/api/config',
            '/api/alignment',
            '/api/kg',
            '/api/evaluation',
            '/api/pymol'
        ]
    })

if __name__ == '__main__':
    print("Starting CryoAgent Pro Flask Application...")
    print("=" * 47)
    print("Server running at: http://localhost:5000")
    print("API endpoints available at: http://localhost:5000/api/")
    print("")
    print("Press Ctrl+C to stop")
    print("=" * 47)

    app.run(host='0.0.0.0', port=5000, debug=True)
