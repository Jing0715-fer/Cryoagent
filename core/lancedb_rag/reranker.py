# reranker.py - 重排序器
"""
重排序器模块

支持 Jina AI 和本地 cross-encoder 模型
"""

import os
import logging
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


# ============= 重排序器类型 =============

class RerankerType(Enum):
    """重排序器类型"""
    JINA = "jina"  # Jina AI
    LOCAL = "local"  # 本地模型
    OPENAI = "openai"  # OpenAI 兼容 API
    COHERE = "cohere"  # Cohere


# ============= 重排序配置 =============

@dataclass
class RerankerConfig:
    """重排序器配置"""
    reranker_type: RerankerType
    model: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    batch_size: int = 32
    max_retries: int = 3
    top_k: int = 10


class Reranker:
    """
    重排序器

    支持多种重排序模型:
    - Jina AI reranker
    - 本地 cross-encoder
    - OpenAI 兼容 API
    - Cohere
    """

    DEFAULT_CONFIGS = {
        "jina-reranker-v1-base-en": RerankerConfig(
            reranker_type=RerankerType.JINA,
            model="jina-reranker-v1-base-en",
            api_base="https://api.jina.ai/v1",
        ),
        "jina-reranker-v1-multilingual": RerankerConfig(
            reranker_type=RerankerType.JINA,
            model="jina-reranker-v1-multilingual",
            api_base="https://api.jina.ai/v1",
        ),
        "cross-encoder-ms-marco": RerankerConfig(
            reranker_type=RerankerType.LOCAL,
            model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        ),
        "cross-encoder-ms-marco-large": RerankerConfig(
            reranker_type=RerankerType.LOCAL,
            model="cross-encoder/ms-marco-MiniLM-L-12-v2",
        ),
    }

    def __init__(
        self,
        config: Optional[RerankerConfig] = None,
        model_name: str = "jina-reranker-v1-base-en",
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """
        初始化重排序器

        Args:
            config: 重排序器配置
            model_name: 模型名称
            api_base: API 基础 URL
            api_key: API 密钥
        """
        if config:
            self.config = config
        else:
            # 使用默认配置或自定义配置
            if model_name in self.DEFAULT_CONFIGS:
                self.config = self.DEFAULT_CONFIGS[model_name]
                if api_key:
                    self.config.api_key = api_key
            else:
                # 自定义配置
                if model_name.startswith("jina-"):
                    self.config = RerankerConfig(
                        reranker_type=RerankerType.JINA,
                        model=model_name,
                        api_base="https://api.jina.ai/v1",
                        api_key=api_key or os.environ.get("JINA_API_KEY"),
                    )
                else:
                    self.config = RerankerConfig(
                        reranker_type=RerankerType.LOCAL,
                        model=model_name,
                    )

        self.model_name = model_name
        self._client = None
        self._local_model = None

    @property
    def client(self):
        """获取 HTTP 客户端"""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self):
        """创建 HTTP 客户端"""
        if self.config.reranker_type == RerankerType.LOCAL:
            return None

        try:
            import httpx
            api_key = self.config.api_key or os.environ.get("JINA_API_KEY")
            return httpx.Client(
                base_url=self.config.api_base or "https://api.jina.ai/v1",
                headers={
                    "Authorization": f"Bearer {api_key or ''}",
                    "Content-Type": "application/json"
                },
                timeout=60
            )
        except ImportError:
            logger.warning("httpx 未安装")
            return None

    def _get_local_model(self):
        """获取本地模型"""
        if self._local_model is None and self.config.reranker_type == RerankerType.LOCAL:
            self._load_local_model()
        return self._local_model

    def _load_local_model(self):
        """加载本地 cross-encoder 模型"""
        try:
            from sentence_transformers import CrossEncoder
            self._local_model = CrossEncoder(self.config.model)
            logger.info(f"已加载本地 cross-encoder 模型: {self.config.model}")
        except ImportError:
            logger.error("sentence-transformers 未安装，请运行: pip install sentence-transformers")
            raise
        except Exception as e:
            logger.error(f"加载本地模型失败: {e}")
            raise

    def rerank(
        self,
        query: str,
        documents: List[Union[str, Dict[str, Any]]],
        top_k: Optional[int] = None,
        batch_size: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        重排序文档

        Args:
            query: 查询文本
            documents: 文档列表（字符串或字典）
            top_k: 返回结果数量
            batch_size: 批处理大小

        Returns:
            重排序后的结果
        """
        if not documents:
            return []

        top_k = top_k or self.config.top_k
        batch_size = batch_size or self.config.batch_size

        # 提取文本
        texts = [self._extract_text(doc) for doc in documents]

        # 根据类型选择重排序方法
        if self.config.reranker_type == RerankerType.LOCAL:
            scores = self._rerank_local(query, texts, batch_size)
        else:
            scores = self._rerank_remote(query, texts, batch_size)

        # 构建结果
        results = []
        for i, (doc, score) in enumerate(zip(documents, scores)):
            if isinstance(doc, dict):
                result = doc.copy()
            else:
                result = {"text": doc}

            result["rerank_score"] = float(score)
            result["original_index"] = i
            results.append(result)

        # 排序
        results.sort(key=lambda x: x["rerank_score"], reverse=True)

        return results[:top_k]

    @staticmethod
    def _extract_text(doc: Union[str, Dict[str, Any]]) -> str:
        """提取文档文本"""
        if isinstance(doc, str):
            return doc
        elif isinstance(doc, dict):
            # 尝试多个可能的字段
            for field in ["text", "content", "abstract", "title", "description"]:
                if field in doc:
                    return doc[field]
            # 返回第一个字符串字段
            for value in doc.values():
                if isinstance(value, str) and len(value) > 10:
                    return value
        return str(doc)

    def _rerank_local(
        self,
        query: str,
        texts: List[str],
        batch_size: int
    ) -> List[float]:
        """使用本地模型重排序"""
        model = self._get_local_model()

        # 创建查询-文档对
        pairs = [[query, text] for text in texts]

        # 批量预测
        scores = model.predict(pairs)

        return scores.tolist() if hasattr(scores, 'tolist') else list(scores)

    def _rerank_remote(
        self,
        query: str,
        texts: List[str],
        batch_size: int
    ) -> List[float]:
        """使用远程 API 重排序"""
        all_scores = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            # 构建请求
            if self.config.reranker_type == RerankerType.JINA:
                payload = {
                    "model": self.config.model,
                    "query": query,
                    "documents": batch,
                }
                endpoint = "/rerank"
            else:
                # OpenAI 兼容格式
                payload = {
                    "model": self.config.model,
                    "query": query,
                    "documents": batch,
                    "top_n": len(batch),
                }
                endpoint = "/reranking"

            try:
                response = self.client.post(endpoint, json=payload)
                response.raise_for_status()
                result = response.json()

                # 提取分数
                if "results" in result:
                    batch_scores = [r["relevance_score"] for r in result["results"]]
                elif "data" in result:
                    batch_scores = [r["relevance_score"] for r in sorted(result["data"], key=lambda x: x["index"])]
                else:
                    batch_scores = [0.0] * len(batch)

                all_scores.extend(batch_scores)

            except Exception as e:
                logger.error(f"重排序 API 请求失败: {e}")
                all_scores.extend([0.0] * len(batch))

        return all_scores

    def compute_similarity(
        self,
        query: str,
        document: str
    ) -> float:
        """
        计算单个查询和文档的相似度

        Args:
            query: 查询文本
            document: 文档文本

        Returns:
            相似度分数
        """
        results = self.rerank(query, [document], top_k=1)
        return results[0]["rerank_score"] if results else 0.0


# ============= 便捷函数 =============

def get_jina_reranker(
    model: str = "jina-reranker-v1-base-en",
    api_key: Optional[str] = None,
) -> Reranker:
    """
    获取 Jina 重排序器

    Args:
        model: 模型名称
        api_key: API 密钥

    Returns:
        Reranker 实例
    """
    return Reranker(
        model_name=model,
        api_key=api_key,
    )


def get_local_reranker(
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
) -> Reranker:
    """
    获取本地重排序器

    Args:
        model: 模型名称

    Returns:
        Reranker 实例
    """
    return Reranker(model_name=model)


# ============= 单例管理 =============

_reranker_instance: Optional[Reranker] = None


def get_reranker(
    model_name: str = "jina-reranker-v1-base-en",
    api_key: Optional[str] = None,
) -> Reranker:
    """
    获取重排序器单例

    Args:
        model_name: 模型名称
        api_key: API 密钥

    Returns:
        Reranker 实例
    """
    global _reranker_instance

    if _reranker_instance is None:
        _reranker_instance = Reranker(
            model_name=model_name,
            api_key=api_key,
        )

    return _reranker_instance


def reset_reranker():
    """重置重排序器单例"""
    global _reranker_instance
    _reranker_instance = None
