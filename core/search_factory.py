"""
Search Engine Factory

Provides a unified interface for vector search using either FAISS or LanceDB.
Dynamically selects the search engine based on application configuration.
"""

import os
import logging
from typing import Optional, List, Dict, Any, Union
from flask import current_app

from .literature_index import UnifiedVectorIndexer, EntityType
from .lancedb_rag import UnifiedLanceRAG, RAGConfig

logger = logging.getLogger(__name__)

# Singleton instances for search engines
_faiss_indexer: Optional[UnifiedVectorIndexer] = None
_lance_rag: Optional[UnifiedLanceRAG] = None


def get_faiss_indexer() -> UnifiedVectorIndexer:
    """Get or create the FAISS-based UnifiedVectorIndexer singleton."""
    global _faiss_indexer
    if _faiss_indexer is None:
        logger.info("Initializing FAISS-based UnifiedVectorIndexer...")
        _faiss_indexer = UnifiedVectorIndexer()
    return _faiss_indexer


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
    Get the configured search engine based on VECTOR_ENGINE setting.

    Returns:
        Either UnifiedVectorIndexer (FAISS) or UnifiedLanceRAG (LanceDB)

    Raises:
        RuntimeError: If called outside of Flask application context
    """
    # Get vector engine from config, default to 'faiss'
    if current_app:
        vector_engine = current_app.config.get('VECTOR_ENGINE', 'faiss')
    else:
        # Fallback to environment variable if outside app context
        vector_engine = os.environ.get('VECTOR_ENGINE', 'faiss')

    logger.debug(f"Using vector engine: {vector_engine}")

    if vector_engine == 'lancedb':
        return get_lance_rag()
    else:
        return get_faiss_indexer()


def reset_search_engines():
    """Reset all search engine singletons. Useful for testing or reconfiguration."""
    global _faiss_indexer, _lance_rag
    _faiss_indexer = None
    _lance_rag = None
    logger.info("Search engine singletons reset")


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
    Unified vector search function that works with both FAISS and LanceDB.

    Args:
        query: Search query text
        top_k: Number of results to return
        entity_filter: Filter by entity type (for FAISS)
        search_type: Search type - "vector", "bm25", or "hybrid" (for LanceDB)

    Returns:
        List of search results with consistent format
    """
    engine = get_search_engine()

    if isinstance(engine, UnifiedLanceRAG):
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
                'distance': r.get('score', 0),  # Original distance score
                'document': r.get('document', {}),
                'source': r.get('source', 'unknown'),
            })
        return results

    else:
        # FAISS search - convert entity_filter to entity_types if provided
        entity_types = None
        if entity_filter:
            # entity_filter is a single EntityType, convert to list
            if hasattr(entity_filter, '__iter__') and not isinstance(entity_filter, str):
                entity_types = list(entity_filter)
            else:
                entity_types = [entity_filter]
        return engine.search(query, top_k=top_k, entity_types=entity_types)


def get_search_engine_type() -> str:
    """Get the currently configured search engine type."""
    if current_app:
        return current_app.config.get('VECTOR_ENGINE', 'faiss')
    return os.environ.get('VECTOR_ENGINE', 'faiss')
