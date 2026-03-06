"""
飞书文档服务 - 获取、解析和向量化飞书文档
"""
import os
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

# 设置日志
logger = logging.getLogger(__name__)

# 飞书文档块类型映射
BLOCK_TYPE_MAP = {
    "text": "text",
    "paragraph": "paragraph",
    "heading1": "heading1",
    "heading2": "heading2",
    "heading3": "heading3",
    "quote": "quote",
    "code": "code",
    "image": "image",
    "table": "table",
    "divider": "divider",
    "blockquote": "quote",
    "callout": "callout",
    "blank": "blank"
}

# 文档内容保存目录
FEISHU_DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "feishu_documents")

# 飞书文档索引目录
FEISHU_INDICES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "feishu_indices")


class FeishuDocumentService:
    """飞书文档服务"""

    def __init__(self, feishu_client=None, config: Optional[Dict[str, Any]] = None):
        """
        初始化文档服务

        Args:
            feishu_client: FeishuClient实例，可以为None（仅本地文档搜索）
            config: 配置字典
        """
        self.client = feishu_client
        self.config = config or {}

        # 确保目录存在
        os.makedirs(FEISHU_DOCS_DIR, exist_ok=True)
        os.makedirs(FEISHU_INDICES_DIR, exist_ok=True)

        # 初始化RAG系统
        self._init_rag_system()

    def _init_rag_system(self):
        """初始化RAG系统"""
        try:
            from literature_index import UnifiedRAGSystem, UnifiedDocument, EntityType

            self.rag_system = UnifiedRAGSystem()
            self.entity_type = EntityType.LITERATURE  # 飞书文档使用LITERATURE类型，通过metadata区分
            self._indexed_doc_ids = set()
            # 加载已索引的文档ID
            self._load_indexed_docs()
            logger.info("飞书文档服务RAG系统初始化完成")
        except ImportError as e:
            logger.warning(f"无法导入RAG系统: {e}")
            self.rag_system = None
            self.entity_type = None

    def _load_indexed_docs(self):
        """从unified_index.json加载已索引的飞书文档ID"""
        try:
            import json
            index_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                      'literature_indices', 'unified_index.json')
            if os.path.exists(index_path):
                with open(index_path, 'r') as f:
                    data = json.load(f)
                docs = data.get('documents', {})
                for doc_id, doc in docs.items():
                    metadata = doc.get('metadata', {})
                    if metadata.get('is_feishu'):
                        self._indexed_doc_ids.add(doc_id)
                logger.info(f"已加载 {len(self._indexed_doc_ids)} 个已索引飞书文档")
        except Exception as e:
            logger.warning(f"加载已索引文档失败: {e}")

    def fetch_document(self, doc_token: str, folder_name: str = None) -> Dict[str, Any]:
        """
        获取飞书文档并解析

        Args:
            doc_token: 文档的token
            folder_name: 来源文件夹名称

        Returns:
            解析后的文档数据

        Raises:
            Exception: 获取或解析失败
        """
        # 获取文档元信息
        doc_info = self.client.get_document_info(doc_token)

        # 获取文档内容
        doc_content = self.client.get_document_content(doc_token)

        # 解析文档
        parsed_doc = self._parse_document(doc_info, doc_content, folder_name)

        return parsed_doc

    def _parse_document(self, doc_info: Dict[str, Any], doc_content: Dict[str, Any], folder_name: str = None) -> Dict[str, Any]:
        """
        解析飞书文档JSON格式

        Args:
            doc_info: 文档元信息
            doc_content: 文档内容（纯文本）
            folder_name: 来源文件夹名称

        Returns:
            解析后的文档字典
        """
        # 提取标题
        title = doc_info.get("name", "未命名文档")

        # 获取纯文本内容
        text_content = doc_content.get("content", "")

        # 构建文档对象
        doc_data = {
            "doc_id": f"feishu_{doc_info.get('token', uuid.uuid4().hex[:8])}",
            "source_id": doc_info.get("token", ""),
            "title": title,
            "content": text_content,
            "raw_content": doc_content,
            "metadata": {
                "source": "feishu",
                "doc_type": doc_info.get("type", "doc"),
                "created_time": doc_info.get("created_time", ""),
                "updated_time": doc_info.get("updated_time", ""),
                "fetched_at": datetime.now().isoformat(),
                "folder_name": folder_name
            }
        }

        return doc_data

    def _extract_text_from_blocks(self, blocks: List[Dict[str, Any]]) -> str:
        """
        从文档块中提取文本内容

        Args:
            blocks: 文档块列表

        Returns:
            提取的文本内容
        """
        text_parts = []

        for block in blocks:
            block_type = block.get("type", "text")
            block_text = self._extract_block_text(block, block_type)
            if block_text:
                text_parts.append(block_text)

        return "\n\n".join(text_parts)

    def _extract_block_text(self, block: Dict[str, Any], block_type: str) -> str:
        """
        从单个块中提取文本

        Args:
            block: 文档块
            block_type: 块类型

        Returns:
            块中的文本内容
        """
        text = ""

        if block_type in ["text", "paragraph", "heading1", "heading2", "heading3"]:
            # 获取文本内容
            element = block.get(block_type, {})
            elements = element.get("elements", [])
            for elem in elements:
                if "text" in elem:
                    text += elem["text"].get("content", "")
                elif "mention" in elem:
                    text += elem["mention"].get("name", "")

        elif block_type == "quote":
            # 引用块
            quote = block.get("quote", {})
            elements = quote.get("elements", [])
            for elem in elements:
                if "text" in elem:
                    text += elem["text"].get("content", "")

        elif block_type == "code":
            # 代码块
            code = block.get("code", {})
            text = code.get("content", "")

        elif block_type == "callout":
            # 提示块
            callout = block.get("callout", {})
            elements = callout.get("elements", [])
            for elem in elements:
                if "text" in elem:
                    text += elem["text"].get("content", "")

        elif block_type == "table":
            # 表格块
            table = block.get("table", {})
            rows = table.get("cells", [])
            for row in rows:
                row_text = " | ".join(cell.get("text", {}).get("content", "") for cell in row)
                text += row_text + "\n"

        return text.strip()

    def fetch_documents_batch(self, doc_tokens: List[str]) -> List[Dict[str, Any]]:
        """
        批量获取文档

        Args:
            doc_tokens: 文档token列表

        Returns:
            解析后的文档列表
        """
        documents = []
        for token in doc_tokens:
            try:
                doc = self.fetch_document(token)
                documents.append(doc)
            except Exception as e:
                logger.error(f"获取文档 {token} 失败: {e}")

        return documents

    def save_to_local(self, doc_data: Dict[str, Any]) -> str:
        """
        保存文档到本地文件系统

        Args:
            doc_data: 文档数据

        Returns:
            保存的文件路径
        """
        # 生成文件名
        safe_title = "".join(c for c in doc_data["title"] if c.isalnum() or c in " -_").strip()[:50]
        filename = f"{doc_data['doc_id']}_{safe_title}.json"
        filepath = os.path.join(FEISHU_DOCS_DIR, filename)

        # 保存文档
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(doc_data, f, ensure_ascii=False, indent=2)

        logger.info(f"文档已保存到: {filepath}")
        return filepath

    def vectorize_and_index(self, doc_data: Dict[str, Any]) -> bool:
        """
        将文档向量化并添加到索引

        Args:
            doc_data: 文档数据

        Returns:
            是否成功
        """
        try:
            # 尝试使用RAG系统
            if self.rag_system is None:
                # 延迟导入并初始化RAG系统
                from literature_index import UnifiedRAGSystem

                self.rag_system = UnifiedRAGSystem()

            # 创建统一文档对象 - 使用LITERATURE类型，因为EntityType没有FEISHU
            from literature_index import UnifiedDocument, EntityType

            doc = UnifiedDocument(
                doc_id=doc_data.get("doc_id", f"feishu_{uuid.uuid4().hex[:8]}"),
                entity_type=EntityType.LITERATURE,  # 使用LITERATURE类型
                source_id=doc_data.get("source_id", ""),
                title=doc_data.get("title", ""),
                content=doc_data.get("content", ""),
                metadata={
                    **doc_data.get("metadata", {}),
                    "feishu_doc_id": doc_data.get("doc_id"),
                    "is_feishu": True  # 标记为飞书文档
                }
            )

            # 添加到索引
            self.rag_system.add_document(doc)

            # 保存文档
            self.save_to_local(doc_data)

            logger.info(f"文档 '{doc_data['title']}' 已向量化并索引")
            return True

        except Exception as e:
            logger.error(f"向量化文档失败: {e}")
            # 如果RAG系统不可用，至少保存文档
            self.save_to_local(doc_data)
            return False

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        在飞书文档知识库中搜索

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            搜索结果列表
        """
        try:
            # 直接从unified_index.json搜索飞书文档
            import json
            import re

            index_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                'literature_indices', 'unified_index.json'
            )

            if not os.path.exists(index_path):
                logger.warning(f"索引文件不存在: {index_path}")
                return []

            with open(index_path, 'r') as f:
                index_data = json.load(f)

            docs = index_data.get('documents', {})

            # 搜索关键词
            query_lower = query.lower()
            # 提取可能的中英文关键词
            keywords = [query_lower]
            # 提取英文关键词
            english_words = re.findall(r'[a-zA-Z]{3,}', query)
            keywords.extend([w.lower() for w in english_words])

            matched_docs = []
            for doc_id, doc in docs.items():
                metadata = doc.get('metadata', {})
                if not metadata.get('is_feishu'):
                    continue

                # 使用folder_name作为标题（因为title可能为空）
                title = doc.get('title', '') or metadata.get('folder_name', '飞书文档')
                content = doc.get('content', '')

                # 计算匹配分数 - 搜索title, content和folder_name
                folder_name = metadata.get('folder_name', '')
                text_lower = f"{title} {content} {folder_name}".lower()
                score = 0
                for kw in keywords:
                    if kw in text_lower:
                        score += 1
                        # folder_name和title匹配权重更高
                        if kw in folder_name.lower() or kw in title.lower():
                            score += 2

                if score > 0:
                    matched_docs.append({
                        'doc_id': doc_id,
                        'title': title,
                        'content': content[:3000],  # 限制内容长度
                        'metadata': metadata,
                        'score': score
                    })

            # 按分数排序
            matched_docs.sort(key=lambda x: x.get('score', 0), reverse=True)
            return matched_docs[:top_k]

        except Exception as e:
            logger.error(f"飞书文档搜索失败: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_document_list(self) -> List[Dict[str, Any]]:
        """
        获取本地保存的飞书文档列表

        Returns:
            文档列表
        """
        documents = []
        if not os.path.exists(FEISHU_DOCS_DIR):
            return documents

        for filename in os.listdir(FEISHU_DOCS_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(FEISHU_DOCS_DIR, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        doc = json.load(f)
                        documents.append({
                            "doc_id": doc.get("doc_id"),
                            "title": doc.get("title"),
                            "source_id": doc.get("source_id"),
                            "metadata": doc.get("metadata", {})
                        })
                except Exception as e:
                    logger.error(f"读取文档 {filename} 失败: {e}")

        return documents

    def ensure_all_indexed(self) -> bool:
        """
        确保所有本地飞书文档都已索引

        Returns:
            是否成功
        """
        try:
            if self.rag_system is None:
                from literature_index import UnifiedRAGSystem
                self.rag_system = UnifiedRAGSystem()

            # 确保vector_indexer已初始化
            if self.rag_system.vector_indexer is None:
                logger.info("初始化vector_indexer...")
                self.rag_system._ensure_initialized()

            # 获取本地文档列表
            local_docs = self.get_document_list()
            logger.info(f"发现 {len(local_docs)} 个本地飞书文档")

            if not local_docs:
                logger.info("没有本地飞书文档需要索引")
                return True

            # 重新加载已索引文档
            self._load_indexed_docs()

            indexed_count = 0
            failed_count = 0

            for doc_info in local_docs:
                doc_id = doc_info.get('doc_id', '')
                if doc_id in self._indexed_doc_ids:
                    logger.info(f"文档已索引: {doc_id}")
                    indexed_count += 1
                    continue

                # 读取完整文档内容
                doc_data = self._load_doc_from_file(doc_id)
                if not doc_data:
                    logger.warning(f"无法加载文档: {doc_id}")
                    failed_count += 1
                    continue

                # 添加到索引
                try:
                    from literature_index import UnifiedDocument, EntityType

                    doc = UnifiedDocument(
                        doc_id=doc_data.get("doc_id", doc_id),
                        entity_type=EntityType.LITERATURE,
                        source_id=doc_data.get("source_id", ""),
                        title=doc_data.get("title", ""),
                        content=doc_data.get("content", ""),
                        metadata={
                            **doc_data.get("metadata", {}),
                            "feishu_doc_id": doc_data.get("doc_id"),
                            "is_feishu": True
                        }
                    )

                    self.rag_system.vector_indexer.add_document(doc)
                    self._indexed_doc_ids.add(doc_id)
                    indexed_count += 1
                    logger.info(f"已索引飞书文档: {doc_data.get('title', doc_id)[:50]}")
                except Exception as e:
                    logger.error(f"索引文档失败 {doc_id}: {e}")
                    failed_count += 1

            # 保存索引数据
            if indexed_count > 0 and self.rag_system and self.rag_system.vector_indexer:
                try:
                    self.rag_system.vector_indexer._save_index_data()
                    logger.info("飞书文档索引已保存")
                except Exception as e:
                    logger.error(f"保存索引失败: {e}")

            logger.info(f"飞书文档索引完成: 成功 {indexed_count}, 失败 {failed_count}")
            return failed_count == 0

        except Exception as e:
            logger.error(f"确保文档索引失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _load_doc_from_file(self, doc_id: str) -> Dict[str, Any]:
        """
        从本地文件加载飞书文档

        Args:
            doc_id: 文档ID

        Returns:
            文档数据
        """
        if not os.path.exists(FEISHU_DOCS_DIR):
            return {}

        for filename in os.listdir(FEISHU_DOCS_DIR):
            if filename.startswith(doc_id) or filename.endswith(".json"):
                filepath = os.path.join(FEISHU_DOCS_DIR, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    logger.error(f"读取文档失败: {e}")

        return {}

    def delete_document(self, doc_id: str) -> bool:
        """
        删除本地文档

        Args:
            doc_id: 文档ID

        Returns:
            是否成功
        """
        if not os.path.exists(FEISHU_DOCS_DIR):
            return False

        for filename in os.listdir(FEISHU_DOCS_DIR):
            if filename.startswith(doc_id):
                filepath = os.path.join(FEISHU_DOCS_DIR, filename)
                try:
                    os.remove(filepath)
                    logger.info(f"已删除文档: {filepath}")
                    return True
                except Exception as e:
                    logger.error(f"删除文档失败: {e}")

        return False
