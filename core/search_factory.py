"""
Search Engine Factory

Provides a unified interface for vector search using LanceDB.
"""

import os
import logging
from typing import Optional, List, Dict, Any, Union
from flask import current_app

from .lancedb_rag import UnifiedLanceRAG, RAGConfig
from .literature_index import EntityType

logger = logging.getLogger(__name__)

# Singleton instance for LanceDB search engine
_lance_rag: Optional[UnifiedLanceRAG] = None


def get_lance_rag() -> UnifiedLanceRAG:
    """Get or create the LanceDB-based UnifiedLanceRAG singleton."""
    global _lance_rag
    if _lance_rag is None:
        logger.info("Initializing LanceDB-based UnifiedLanceRAG...")

        # Get configuration from app config or environment
        vector_dim = 384  # Default dimension for all-MiniLM-L6-v2
        if current_app:
            vector_dim = current_app.config.get('LANCEDB_VECTOR_DIM', 384)

        db_path = None
        if current_app:
            db_path = current_app.config.get('LANCEDB_PATH')

        # Get rerank setting from config
        use_rerank = False
        if current_app:
            use_rerank = current_app.config.get('USE_RERANK', False)
        logger.info(f"USE_RERANK config: {use_rerank}")

        config = RAGConfig(
            db_path=db_path,
            vector_dim=vector_dim,
            embedding_model="all-MiniLM-L6-v2",  # Use local embedding model
            default_top_k=10,
            use_rerank=use_rerank,
            use_session=False,  # Disable session for simple search
            use_adaptive=False,  # Disable adaptive retrieval for simple search
        )
        _lance_rag = UnifiedLanceRAG(config=config)
        _lance_rag.initialize_tables()

    return _lance_rag


def get_search_engine():
    """
    Get the configured search engine (always LanceDB).

    Returns:
        UnifiedLanceRAG: LanceDB-based search engine

    Raises:
        RuntimeError: If called outside of Flask application context
    """
    return get_lance_rag()


def reset_search_engines():
    """Reset LanceDB search engine singleton. Useful for testing or reconfiguration."""
    global _lance_rag
    _lance_rag = None
    logger.info("LanceDB search engine singleton reset")


def is_lancedb_available() -> bool:
    """Check if LanceDB tables exist and have data."""
    try:
        rag = get_lance_rag()
        stats = rag.get_stats()
        lit_count = stats.get('literature_count', 0)
        struct_count = stats.get('structure_count', 0)
        return lit_count > 0 or struct_count > 0
    except Exception as e:
        logger.warning(f"LanceDB availability check failed: {e}")
        return False


def search_vector(
    query: str,
    top_k: int = 10,
    entity_filter: Optional[EntityType] = None,
    search_type: str = "vector"
) -> List[Dict[str, Any]]:
    """
    Unified vector search function using LanceDB.

    Args:
        query: Search query text
        top_k: Number of results to return
        entity_filter: Filter by entity type (EntityType.LITERATURE or EntityType.STRUCTURE)
        search_type: Search type - "vector", "bm25", or "hybrid"

    Returns:
        List of search results with consistent format
    """
    engine = get_search_engine()

    # LanceDB search
    include_literature = entity_filter is None or entity_filter == EntityType.LITERATURE
    include_structure = entity_filter is None or entity_filter == EntityType.STRUCTURE

    # Get rerank setting from config
    use_rerank = current_app.config.get('USE_RERANK', False) if current_app else False

    result = engine.search(
        query=query,
        top_k=top_k,
        search_type=search_type,
        include_literature=include_literature,
        include_structure=include_structure,
        use_rerank=use_rerank,
    )

    # Convert to consistent format
    results = []
    for r in result.get('results', []):
        results.append({
            'id': r.get('id'),
            'score': r.get('rerank_score') or r.get('score', 0),
            'distance': r.get('score', 0),
            'document': r.get('document', {}),
            'source': r.get('source', 'unknown'),
        })
    return results


def get_search_engine_type() -> str:
    """Get the currently configured search engine type (always lancedb)."""
    return 'lancedb'