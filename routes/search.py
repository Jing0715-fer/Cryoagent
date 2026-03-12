"""
Search API Routes
"""
from flask import jsonify, request, Blueprint
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('search', __name__, url_prefix='/api/search')

from core.literature_db import search_literature, LiteratureStatus
from core.literature_index import EntityType
from core.agent_core import search_literature_with_ai_context
from core.search_factory import get_search_engine, search_vector, get_search_engine_type


@bp.route('/literature', methods=['GET'])
def search_literature_api():
    """
    Unified literature search endpoint
    Supports query parameters for filtering
    """
    try:
        query = request.args.get('query', '')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        author = request.args.get('author', '')
        journal = request.args.get('journal', '')
        year_from = request.args.get('year_from', type=int)
        year_to = request.args.get('year_to', type=int)
        tags = request.args.get('tags', '')

        status = request.args.get('status')
        has_cryoem = request.args.get('has_cryoem', '')
        has_embeddings = request.args.get('has_embeddings', '')

        results = search_literature(
            query=query,
            author=author,
            journal=journal,
            year_from=year_from,
            year_to=year_to,
            status=LiteratureStatus(status) if status else None,
            has_cryoem_targets=has_cryoem if has_cryoem else None,
            has_vector_embeddings=has_embeddings if has_embeddings else None,
            tags=[t.strip() for t in tags.split(',')] if tags else None,
            limit=per_page * page
        )

        # Pagination
        start = (page - 1) * per_page
        items = results[start:start + per_page]

        literature_list = []
        for entry in items:
            if hasattr(entry, 'to_dict'):
                literature_list.append(entry.to_dict())
            else:
                literature_list.append(entry)

        return jsonify({
            'items': literature_list,
            'total': len(results),
            'page': page,
            'per_page': per_page
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/vector', methods=['POST'])
def vector_search():
    """
    Vector similarity search endpoint
    Uses LanceDB engine
    """
    try:
        data = request.json
        query = data.get('query', '')
        top_k = data.get('top_k', 10)
        search_type = data.get('search_type', 'vector')  # For LanceDB: vector, bm25, hybrid

        if not query:
            return jsonify({'error': 'Query is required'}), 400

        # Get configured search engine (LanceDB)
        engine_type = get_search_engine_type()
        logger.info(f"Vector search using {engine_type} engine")

        # Perform search using unified interface
        results = search_vector(
            query=query,
            top_k=top_k,
            entity_filter=EntityType.LITERATURE,
            search_type=search_type
        )

        return jsonify({
            'results': results,
            'engine': engine_type,
            'search_type': search_type
        })
    except Exception as e:
        logger.error(f"Vector search error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/ai', methods=['POST'])
def ai_search_api():
    """
    AI-enhanced search with semantic understanding
    """
    try:
        data = request.json
        question = data.get('question', '')
        top_k = data.get('top_k', 5)

        if not question:
            return jsonify({'error': 'Question is required'}), 400

        results = search_literature_with_ai_context(
            query=question,
            top_k=top_k
        )

        return jsonify({
            'answer': results.get('answer', ''),
            'literature': results.get('literature', []),
            'structures': results.get('structures', [])
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
