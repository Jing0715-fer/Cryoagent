# lancedb_rag - LanceDB RAG 系统
"""
LanceDB RAG (Retrieval-Augmented Generation) 系统

提供多种混合搜索模式:
- 向量相似度搜索
- BM25 全文搜索
- 混合融合检索
- 交叉编码重排序
- 会话记忆
- 自适应检索
"""

from .client import LanceDBClient
from .embedding import EmbeddingManager
from .bm25 import BM25Index
from .hybrid import HybridSearchEngine
from .reranker import Reranker
from .session import SessionMemory
from .adaptive import AdaptiveRetrieval
from .rag import UnifiedLanceRAG, RAGConfig

__all__ = [
    'LanceDBClient',
    'EmbeddingManager',
    'BM25Index',
    'HybridSearchEngine',
    'Reranker',
    'SessionMemory',
    'AdaptiveRetrieval',
    'UnifiedLanceRAG',
    'RAGConfig',
]

__version__ = '1.0.0'
