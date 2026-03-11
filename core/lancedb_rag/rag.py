# rag.py - 统一检索入口
"""
统一检索入口模块

整合所有检索功能，提供统一的 API
"""

import os
import logging
from typing import List, Dict, Any, Optional, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime
import json

logger = logging.getLogger(__name__)

from .client import LanceDBClient, get_lancedb_client, TableConfig
from .embedding import EmbeddingManager, get_embedding_manager
from .bm25 import BM25Index, create_bm25_index
from .hybrid import HybridSearchEngine, HybridSearchConfig, FusionStrategy
from .reranker import Reranker, get_reranker
from .session import SessionMemory, create_session_memory
from .adaptive import AdaptiveRetrieval, AdaptiveConfig, QueryType

# ============= 检索结果格式 =============

@dataclass
class SearchResult:
    """检索结果"""
    id: str
    score: float
    document: Dict[str, Any]
    source: str  # "literature" | "structure"
    rerank_score: Optional[float] = None


@dataclass
class RAGConfig:
    """RAG 系统配置"""
    # LanceDB 配置
    db_path: Optional[str] = None
    vector_dim: int = 1536

    # 嵌入模型配置
    embedding_model: str = "deepseek-embed"
    embedding_api_base: Optional[str] = None
    embedding_api_key: Optional[str] = None

    # 重排序配置
    reranker_model: str = "jina-reranker-v1-base-en"
    reranker_api_key: Optional[str] = None
    use_rerank: bool = True

    # 搜索配置
    default_top_k: int = 10
    fusion_strategy: FusionStrategy = FusionStrategy.RRF
    vector_weight: float = 0.5
    bm25_weight: float = 0.5

    # 会话配置
    use_session: bool = True
    max_history: int = 10

    # 自适应配置
    use_adaptive: bool = True


class UnifiedLanceRAG:
    """
    统一 RAG 检索系统

    整合向量搜索、BM25、混合搜索、重排序、会话记忆等功能
    """

    def __init__(
        self,
        config: Optional[RAGConfig] = None,
        lancedb_client: Optional[LanceDBClient] = None,
        embedding_manager: Optional[EmbeddingManager] = None,
        reranker: Optional[Reranker] = None,
        session_memory: Optional[SessionMemory] = None,
    ):
        """
        初始化统一 RAG 系统

        Args:
            config: RAG 配置
            lancedb_client: LanceDB 客户端
            embedding_manager: 嵌入管理器
            reranker: 重排序器
            session_memory: 会话记忆
        """
        self.config = config or RAGConfig()

        # 初始化各组件
        self._init_components(
            lancedb_client,
            embedding_manager,
            reranker,
            session_memory
        )

        # 索引缓存
        self._literature_bm25: Optional[BM25Index] = None
        self._structure_bm25: Optional[BM25Index] = None
        self._literature_table = None
        self._structure_table = None

    def _init_components(
        self,
        lancedb_client: Optional[LanceDBClient],
        embedding_manager: Optional[EmbeddingManager],
        reranker: Optional[Reranker],
        session_memory: Optional[SessionMemory]
    ):
        """初始化各组件"""
        # LanceDB 客户端
        if lancedb_client:
            self.db_client = lancedb_client
        else:
            self.db_client = get_lancedb_client(
                db_path=self.config.db_path,
                vector_dim=self.config.vector_dim,
            )

        # 嵌入管理器
        if embedding_manager:
            self.embedding_manager = embedding_manager
        else:
            self.embedding_manager = get_embedding_manager(
                model_name=self.config.embedding_model,
                api_base=self.config.embedding_api_base,
                api_key=self.config.embedding_api_key,
                dimension=self.config.vector_dim,
            )

        # 重排序器
        if reranker:
            self.reranker = reranker
        elif self.config.use_rerank:
            self.reranker = get_reranker(
                model_name=self.config.reranker_model,
                api_key=self.config.reranker_api_key,
            )
        else:
            self.reranker = None

        # 会话记忆
        if session_memory:
            self.session_memory = session_memory
        elif self.config.use_session:
            self.session_memory = create_session_memory(
                max_history=self.config.max_history
            )
            # 设置嵌入函数用于相似查询检索
            self.session_memory.set_embedding_fn(
                lambda x: self.embedding_manager.encode(x)[0]
            )
        else:
            self.session_memory = None

        # 自适应检索
        if self.config.use_adaptive:
            self.adaptive_retrieval = AdaptiveRetrieval(
                config=AdaptiveConfig(
                    query_type_detection=True,
                    dynamic_top_k=True,
                ),
                reranker=self.reranker,
            )
        else:
            self.adaptive_retrieval = None

        # 混合搜索引擎
        self.hybrid_engine = HybridSearchEngine(
            config=HybridSearchConfig(
                vector_weight=self.config.vector_weight,
                bm25_weight=self.config.bm25_weight,
                fusion_strategy=self.config.fusion_strategy,
                top_k=self.config.default_top_k,
            )
        )

    def initialize_tables(self, overwrite: bool = False):
        """初始化数据库表"""
        self.db_client.create_all_tables(overwrite=overwrite)
        self._literature_table = self.db_client.open_table("literature")
        self._structure_table = self.db_client.open_table("structure")

    # ============= 文档操作 =============

    def add_literature(
        self,
        documents: List[Dict[str, Any]],
        batch_size: int = 32,
    ) -> int:
        """
        添加文献文档

        Args:
            documents: 文献文档列表
            batch_size: 批处理大小

        Returns:
            添加的文档数量
        """
        if not self._literature_table:
            self.initialize_tables()

        # 生成嵌入
        texts = [self._prepare_text(doc) for doc in documents]
        embeddings = self.embedding_manager.encode(texts, batch_size=batch_size)

        # 准备数据
        records = []
        for doc, embedding in zip(documents, embeddings):
            record = self._prepare_literature_record(doc, embedding)
            records.append(record)

        # 插入数据
        self._literature_table.add(records)

        logger.info(f"已添加 {len(records)} 条文献记录")
        return len(records)

    def add_literature_chunks(
        self,
        literature_entry: Dict[str, Any],
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 32,
    ) -> int:
        """
        将文献分块后存储到 LanceDB

        使用现有的 UnifiedDocumentGenerator 分块逻辑，
        为每个 chunk 生成 embedding 并存储。

        Args:
            literature_entry: 文献数据，包含 full_text, sections, abstract 等
            chunk_size: 分块大小（字符），默认 500
            chunk_overlap: 重叠大小（字符），默认 50
            batch_size: 批处理大小，默认 32

        Returns:
            添加的 chunk 数量
        """
        if not self._literature_table:
            self.initialize_tables()

        # 动态导入避免循环依赖
        from core.literature_index import UnifiedDocumentGenerator

        # 使用现有的分块逻辑
        generator = UnifiedDocumentGenerator()
        # 设置 chunk 配置
        generator.config = type('Config', (), {
            'chunk_size': chunk_size,
            'chunk_overlap': chunk_overlap
        })()

        # 生成 chunks
        chunks = generator.chunk_literature_content(literature_entry)

        if not chunks:
            logger.warning(f"文献 {literature_entry.get('id')} 未生成任何 chunks")
            return 0

        # 准备文本用于 embedding
        texts = [chunk.content for chunk in chunks]

        # 批量生成 embeddings
        embeddings = self.embedding_manager.encode(texts, batch_size=batch_size)

        # 准备 LanceDB 记录
        records = []
        for chunk, embedding in zip(chunks, embeddings):
            record = {
                "id": chunk.doc_id,
                "doc_id": chunk.source_id,
                "title": chunk.title[:500] if chunk.title else "",
                "abstract": "",  # chunks 没有单独的 abstract
                "full_text": chunk.content,
                "entity_type": "literature",
                "section": chunk.metadata.get("section", ""),
                "chunk_index": chunk.metadata.get("chunk_index", 0),
                "doc_type": chunk.metadata.get("doc_type", "content_chunk"),
                "chunk_length": chunk.metadata.get("chunk_length", len(chunk.content)),
                "year": chunk.metadata.get("year", 0),
                "journal": chunk.metadata.get("journal", ""),
                "doi": literature_entry.get("doi", ""),
                "authors": literature_entry.get("authors", []),
                "keywords": literature_entry.get("keywords", []),
                "metadata": json.dumps(chunk.metadata),
                "embedding": embedding,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            }
            records.append(record)

        # 插入 LanceDB
        self._literature_table.add(records)

        logger.info(f"已添加 {len(records)} 条文献 chunk 记录 (文献 ID: {literature_entry.get('id')})")
        return len(records)

    def add_structure(
        self,
        documents: List[Dict[str, Any]],
        batch_size: int = 32,
    ) -> int:
        """
        添加结构文档

        Args:
            documents: 结构文档列表
            batch_size: 批处理大小

        Returns:
            添加的文档数量
        """
        if not self._structure_table:
            self.initialize_tables()

        # 生成嵌入
        texts = [self._prepare_text(doc) for doc in documents]
        embeddings = self.embedding_manager.encode(texts, batch_size=batch_size)

        # 准备数据
        records = []
        for doc, embedding in zip(documents, embeddings):
            record = self._prepare_structure_record(doc, embedding)
            records.append(record)

        # 插入数据
        self._structure_table.add(records)

        logger.info(f"已添加 {len(records)} 条结构记录")
        return len(records)

    def _prepare_text(self, doc: Dict[str, Any]) -> str:
        """准备文档文本"""
        parts = []
        for field in ["title", "abstract", "description", "keywords"]:
            if doc.get(field):
                parts.append(str(doc[field]))
        return " ".join(parts) if parts else ""

    def _prepare_literature_record(
        self,
        doc: Dict[str, Any],
        embedding: List[float]
    ) -> Dict[str, Any]:
        """准备文献记录"""
        return {
            "id": doc.get("id", ""),
            "doc_id": doc.get("doc_id", doc.get("id", "")),  # 支持 chunk 文档
            "doi": doc.get("doi", ""),
            "arxiv_id": doc.get("arxiv_id", ""),
            "pmid": doc.get("pmid", ""),
            "title": doc.get("title", ""),
            "abstract": doc.get("abstract", ""),
            "full_text": doc.get("full_text", ""),
            "authors": doc.get("authors", []),
            "journal": doc.get("journal", ""),
            "year": doc.get("year", 0),
            "keywords": doc.get("keywords", []),
            "entity_type": "literature",
            "methods": doc.get("methods", ""),
            "results": doc.get("results", ""),
            "introduction": doc.get("introduction", ""),
            "discussion": doc.get("discussion", ""),
            "conclusions": doc.get("conclusions", ""),
            "metadata": json.dumps(doc.get("metadata", {})),
            # Chunk 支持字段
            "chunk_index": doc.get("chunk_index", 0),
            "section": doc.get("section", ""),
            "doc_type": doc.get("doc_type", "metadata"),
            "chunk_length": doc.get("chunk_length", 0),
            "embedding": embedding,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }

    def _prepare_structure_record(
        self,
        doc: Dict[str, Any],
        embedding: List[float]
    ) -> Dict[str, Any]:
        """准备结构记录"""
        return {
            "id": doc.get("id", ""),
            "structure_type": doc.get("structure_type", "pdb"),
            "title": doc.get("title", ""),
            "description": doc.get("description", ""),
            "methods": doc.get("methods", ""),
            "resolution": doc.get("resolution", 0.0),
            "organism": doc.get("organism", ""),
            "expression_system": doc.get("expression_system", ""),
            "gene": doc.get("gene", ""),
            "protein_name": doc.get("protein_name", ""),
            "authors": doc.get("authors", []),
            "keywords": doc.get("keywords", []),
            "literature_ids": doc.get("literature_ids", []),
            "entity_type": "structure",
            "metadata": json.dumps(doc.get("metadata", {})),
            "embedding": embedding,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }

    # ============= 检索功能 =============

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        search_type: str = "hybrid",  # "vector" | "bm25" | "hybrid"
        include_literature: bool = True,
        include_structure: bool = True,
        use_rerank: bool = True,
        use_adaptive: bool = False,
        session_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        统一检索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            search_type: 搜索类型
            include_literature: 是否包含文献
            include_structure: 是否包含结构
            use_rerank: 是否使用重排序
            use_adaptive: 是否使用自适应检索
            session_id: 会话 ID
            filters: 过滤条件

        Returns:
            检索结果
        """
        top_k = top_k or self.config.default_top_k

        # 如果使用自适应检索
        if use_adaptive and self.adaptive_retrieval:
            return self._adaptive_search(
                query=query,
                top_k=top_k,
                include_literature=include_literature,
                include_structure=include_structure,
                use_rerank=use_rerank,
                session_id=session_id,
                filters=filters,
            )

        # 收集所有结果
        all_results = []

        # 文献检索
        if include_literature:
            lit_results = self._search_literature(
                query=query,
                search_type=search_type,
                top_k=top_k,
                filters=filters,
            )
            for r in lit_results:
                r["source"] = "literature"
            all_results.extend(lit_results)

        # 结构检索
        if include_structure:
            struct_results = self._search_structure(
                query=query,
                search_type=search_type,
                top_k=top_k,
                filters=filters,
            )
            for r in struct_results:
                r["source"] = "structure"
            all_results.extend(struct_results)

        # 排序
        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

        # 重排序
        if use_rerank and self.reranker and all_results:
            all_results = self._rerank_results(query, all_results, top_k)

        # 截取 top_k
        results = all_results[:top_k]

        # 会话记忆
        if session_id and self.session_memory:
            self.session_memory.add_entry(
                session_id=session_id,
                query=query,
                response="",  # 稍后填充
                retrieved_docs=results,
                query_type="hybrid" if include_literature and include_structure else "literature" if include_literature else "structure",
            )

        return {
            "query": query,
            "results": results,
            "total": len(results),
            "search_type": search_type,
        }

    def _search_literature(
        self,
        query: str,
        search_type: str,
        top_k: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """检索文献"""
        if not self._literature_table:
            return []

        # 生成查询嵌入
        query_embedding = self.embedding_manager.encode(query)[0]

        # 向量搜索
        if search_type in ["vector", "hybrid"]:
            try:
                results = self._literature_table.search(query_embedding)\
                    .limit(top_k * 2)\
                    .to_list()

                # 应用过滤
                if filters:
                    results = self._apply_filters(results, filters)

                return [
                    {
                        "id": r.get("id"),
                        "score": r.get("_distance", 0),
                        "document": r,
                    }
                    for r in results
                ]
            except Exception as e:
                logger.error(f"向量搜索失败: {e}")

        return []

    def _search_structure(
        self,
        query: str,
        search_type: str,
        top_k: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """检索结构"""
        if not self._structure_table:
            return []

        # 生成查询嵌入
        query_embedding = self.embedding_manager.encode(query)[0]

        # 向量搜索
        if search_type in ["vector", "hybrid"]:
            try:
                results = self._structure_table.search(query_embedding)\
                    .limit(top_k * 2)\
                    .to_list()

                # 应用过滤
                if filters:
                    results = self._apply_filters(results, filters)

                return [
                    {
                        "id": r.get("id"),
                        "score": r.get("_distance", 0),
                        "document": r,
                    }
                    for r in results
                ]
            except Exception as e:
                logger.error(f"向量搜索失败: {e}")

        return []

    def _apply_filters(
        self,
        results: List[Dict[str, Any]],
        filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """应用过滤条件"""
        filtered = []
        for r in results:
            match = True
            for key, value in filters.items():
                if key not in r or r[key] != value:
                    match = False
                    break
            if match:
                filtered.append(r)
        return filtered

    def _rerank_results(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """重排序结果"""
        if not self.reranker:
            return results[:top_k]

        try:
            docs = [r["document"] for r in results]

            # Get more results than top_k to ensure we have enough after reranking
            reranked = self.reranker.rerank(
                query=query,
                documents=docs,
                top_k=min(top_k * 2, len(docs)),  # Get more to account for potential issues
            )

            # 直接使用reranked的结果，而不是修改原始结果
            # This avoids index mapping issues by using the reranked results directly
            new_results = []
            for r in reranked:
                # Get the original result that corresponds to this reranked result
                orig_idx = r.get("original_index", 0)
                if orig_idx < len(results):
                    orig = results[orig_idx].copy()
                    orig["rerank_score"] = r.get("rerank_score", 0)
                    orig["score"] = r.get("rerank_score", orig.get("score", 0))
                    new_results.append(orig)

            # Sort by rerank_score
            new_results.sort(key=lambda x: x.get("rerank_score", x.get("score", 0)), reverse=True)

            return new_results[:top_k]

        except Exception as e:
            logger.error(f"重排序失败: {e}")

        return results[:top_k]

    def retrieve_chunks(
        self,
        query: str,
        top_k: int = 10,
        doc_id: Optional[str] = None,
        sections: Optional[List[str]] = None,
        use_rerank: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        检索相关内容块

        专门用于检索 chunk 级别的文献内容，提供更细粒度的上下文。

        Args:
            query: 查询文本
            top_k: 返回结果数量
            doc_id: 可选，限定来源文档 ID
            sections: 可选，限定章节列表 (如 ["methods", "results"])
            use_rerank: 是否使用重排序

        Returns:
            包含 chunk 内容、来源文献信息、相关性分数的结果列表
        """
        if not self._literature_table:
            self.initialize_tables()

        # 生成查询 embedding
        query_embedding = self.embedding_manager.encode(query)[0]

        # 向量检索
        try:
            search_builder = self._literature_table.search(query_embedding)

            # 添加过滤条件
            if doc_id:
                # LanceDB 的 where 子句
                search_builder = search_builder.where(f"doc_id = '{doc_id}'")

            if sections:
                # 构建 OR 条件
                section_conditions = " OR ".join([f"section = '{s}'" for s in sections])
                if doc_id:
                    search_builder = search_builder.where(f"doc_id = '{doc_id}' AND ({section_conditions})")
                else:
                    search_builder = search_builder.where(section_conditions)

            results = search_builder.limit(top_k * 3).to_list()

        except Exception as e:
            logger.error(f"Chunk 检索失败: {e}")
            return []

        # 格式化结果
        formatted_results = []
        for r in results:
            # 只返回 content_chunk 类型的文档
            if r.get("doc_type") != "content_chunk":
                continue

            formatted_results.append({
                "id": r.get("id"),
                "doc_id": r.get("doc_id"),
                "chunk_index": r.get("chunk_index", 0),
                "section": r.get("section", ""),
                "title": r.get("title", ""),
                "content": r.get("full_text", ""),
                "score": r.get("_distance", 0),
                "year": r.get("year"),
                "journal": r.get("journal", ""),
            })

        # 重排序
        if use_rerank and self.reranker and formatted_results:
            try:
                # 准备重排序文档
                docs_for_rerank = [{"content": r["content"], "id": r["id"]} for r in formatted_results]
                reranked = self.reranker.rerank(
                    query=query,
                    documents=docs_for_rerank,
                    top_k=top_k,
                )

                # 重新排序结果
                reranked_results = []
                for rr in reranked:
                    orig_id = rr.get("document", {}).get("id") or rr.get("id")
                    for orig in formatted_results:
                        if orig["id"] == orig_id:
                            orig["rerank_score"] = rr.get("rerank_score", 0)
                            orig["score"] = rr.get("rerank_score", orig["score"])
                            reranked_results.append(orig)
                            break

                formatted_results = reranked_results[:top_k]

            except Exception as e:
                logger.warning(f"重排序失败: {e}")
                formatted_results = formatted_results[:top_k]

        return formatted_results[:top_k]

    def _adaptive_search(
        self,
        query: str,
        top_k: int,
        include_literature: bool,
        include_structure: bool,
        use_rerank: bool,
        session_id: Optional[str],
        filters: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """自适应搜索"""
        # 使用自适应检索
        result = self.adaptive_retrieval.search(
            query=query,
            documents=[],  # 将从数据库获取
            force_type=None,
        )

        # 这里需要实现从 LanceDB 获取文档的逻辑
        # 简化版本直接返回

        return {
            "query": query,
            "results": result.get("results", []),
            "total": len(result.get("results", [])),
            "query_type": result.get("query_type", "general"),
            "strategy": result.get("strategy", {}),
        }

    # ============= 批量操作 =============

    def index_documents(
        self,
        literature_docs: Optional[List[Dict[str, Any]]] = None,
        structure_docs: Optional[List[Dict[str, Any]]] = None,
        batch_size: int = 32,
    ) -> Dict[str, int]:
        """
        批量索引文档

        Args:
            literature_docs: 文献文档列表
            structure_docs: 结构文档列表
            batch_size: 批处理大小

        Returns:
            索引统计
        """
        stats = {"literature": 0, "structure": 0}

        if literature_docs:
            stats["literature"] = self.add_literature(literature_docs, batch_size)

        if structure_docs:
            stats["structure"] = self.add_structure(structure_docs, batch_size)

        return stats

    # ============= 会话管理 =============

    def get_session_history(
        self,
        session_id: str,
        max_entries: int = 10,
    ) -> List[Dict[str, Any]]:
        """获取会话历史"""
        if self.session_memory:
            return self.session_memory.get_history(session_id, max_entries)
        return []

    def get_session_context(
        self,
        session_id: str,
    ) -> str:
        """获取会话上下文"""
        if self.session_memory:
            return self.session_memory.get_context(session_id)
        return ""

    def clear_session(self, session_id: str):
        """清除会话"""
        if self.session_memory:
            self.session_memory.clear_session(session_id)

    # ============= 统计信息 =============

    def get_stats(self) -> Dict[str, Any]:
        """获取系统统计信息"""
        stats = {
            "config": {
                "embedding_model": self.config.embedding_model,
                "reranker_model": self.config.reranker_model if self.reranker else None,
                "fusion_strategy": self.config.fusion_strategy.value,
            }
        }

        # 表统计
        if self._literature_table:
            try:
                stats["literature_count"] = self._literature_table.count_rows()
            except:
                stats["literature_count"] = 0

        if self._structure_table:
            try:
                stats["structure_count"] = self._structure_table.count_rows()
            except:
                stats["structure_count"] = 0

        # 会话统计
        if self.session_memory:
            stats["session_stats"] = self.session_memory.get_stats()

        return stats


# ============= 单例管理 =============

_rag_instance: Optional[UnifiedLanceRAG] = None


def get_unified_rag(config: Optional[RAGConfig] = None) -> UnifiedLanceRAG:
    """
    获取统一 RAG 系统单例

    Args:
        config: RAG 配置

    Returns:
        UnifiedLanceRAG 实例
    """
    global _rag_instance

    if _rag_instance is None:
        _rag_instance = UnifiedLanceRAG(config=config)

    return _rag_instance


def reset_unified_rag():
    """重置统一 RAG 系统"""
    global _rag_instance
    _rag_instance = None


def create_rag(
    embedding_model: str = "deepseek-embed",
    reranker_model: str = "jina-reranker-v1-base-en",
    fusion_strategy: FusionStrategy = FusionStrategy.RRF,
    **kwargs
) -> UnifiedLanceRAG:
    """
    创建 RAG 系统的便捷函数

    Args:
        embedding_model: 嵌入模型
        reranker_model: 重排序模型
        fusion_strategy: 融合策略
        **kwargs: 其他配置

    Returns:
        UnifiedLanceRAG 实例
    """
    config = RAGConfig(
        embedding_model=embedding_model,
        reranker_model=reranker_model,
        fusion_strategy=fusion_strategy,
        **kwargs
    )
    return UnifiedLanceRAG(config=config)
