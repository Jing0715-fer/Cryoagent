# embedding.py - 嵌入向量管理
"""
嵌入向量管理模块

支持任意 OpenAI 兼容 API 和本地模型
"""

import os
import logging
from typing import List, Optional, Dict, Any, Union
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)


# ============= 嵌入模型配置 =============

@dataclass
class EmbeddingConfig:
    """嵌入模型配置"""
    provider: str  # "openai" | "local" | "jina" | "azure"
    model: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    dimension: int = 1536
    batch_size: int = 32
    max_retries: int = 3
    timeout: int = 60


class EmbeddingManager:
    """
    嵌入向量管理器

    支持多种嵌入模型:
    - OpenAI 兼容 API (deepseek, ollama, etc.)
    - Jina AI
    - Azure OpenAI
    - 本地模型 (sentence-transformers, etc.)
    """

    DEFAULT_CONFIGS = {
        "deepseek-embed": EmbeddingConfig(
            provider="openai",
            model="deepseek-embed",
            api_base="https://api.deepseek.com/v1",
            dimension=1536
        ),
        "text-embedding-3-small": EmbeddingConfig(
            provider="openai",
            model="text-embedding-3-small",
            api_base="https://api.openai.com/v1",
            dimension=1536
        ),
        "text-embedding-3-large": EmbeddingConfig(
            provider="openai",
            model="text-embedding-3-large",
            api_base="https://api.openai.com/v1",
            dimension=3072
        ),
        "all-MiniLM-L6-v2": EmbeddingConfig(
            provider="local",
            model="all-MiniLM-L6-v2",
            dimension=384
        ),
        "bge-base": EmbeddingConfig(
            provider="local",
            model="BAAI/bge-base-en-v1.5",
            dimension=768
        ),
        "bge-large": EmbeddingConfig(
            provider="local",
            model="BAAI/bge-large-en-v1.5",
            dimension=1024
        ),
        "m3e-base": EmbeddingConfig(
            provider="local",
            model="moka-ai/m3e-base",
            dimension=768
        ),
    }

    def __init__(
        self,
        config: Optional[EmbeddingConfig] = None,
        model_name: str = "deepseek-embed",
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        dimension: Optional[int] = None,
        local_model: Optional[Any] = None,
    ):
        """
        初始化嵌入管理器

        Args:
            config: 嵌入模型配置
            model_name: 模型名称
            api_base: API 基础 URL
            api_key: API 密钥
            dimension: 向量维度
            local_model: 本地模型实例
        """
        if config:
            self.config = config
        else:
            # 使用默认配置或自定义配置
            if model_name in self.DEFAULT_CONFIGS:
                self.config = self.DEFAULT_CONFIGS[model_name]
                if api_base:
                    self.config.api_base = api_base
                if api_key:
                    self.config.api_key = api_key
                if dimension:
                    self.config.dimension = dimension
            else:
                # 自定义配置
                self.config = EmbeddingConfig(
                    provider="openai",
                    model=model_name,
                    api_base=api_base or os.environ.get("EMBEDDING_API_BASE", "https://api.deepseek.com/v1"),
                    api_key=api_key or os.environ.get("EMBEDDING_API_KEY"),
                    dimension=dimension or 1536
                )

        self.model_name = model_name
        self._client = None
        self._local_model = local_model
        self._embedding_cache: Dict[str, List[float]] = {}

    @property
    def dimension(self) -> int:
        """获取向量维度"""
        return self.config.dimension

    @property
    def client(self):
        """获取 API 客户端"""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self):
        """创建 API 客户端"""
        if self.config.provider == "local":
            return None

        # 使用 httpx 创建兼容的 HTTP 客户端
        try:
            import httpx
            return httpx.Client(
                base_url=self.config.api_base,
                headers={
                    "Authorization": f"Bearer {self.config.api_key or ''}",
                    "Content-Type": "application/json"
                },
                timeout=self.config.timeout
            )
        except ImportError:
            logger.warning("httpx 未安装，将使用替代方案")
            return None

    def _get_local_model(self):
        """获取本地模型"""
        if self._local_model is None and self.config.provider == "local":
            self._load_local_model()
        return self._local_model

    def _load_local_model(self):
        """加载本地模型"""
        try:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer(self.config.model)
            logger.info(f"已加载本地模型: {self.config.model}")
        except ImportError:
            logger.error("sentence-transformers 未安装，请运行: pip install sentence-transformers")
            raise
        except Exception as e:
            logger.error(f"加载本地模型失败: {e}")
            raise

    def encode(
        self,
        texts: Union[str, List[str]],
        batch_size: Optional[int] = None,
        normalize: bool = True,
        prompt: Optional[str] = None,
        task_type: Optional[str] = None,
    ) -> List[List[float]]:
        """
        编码文本为向量

        Args:
            texts: 单个文本或文本列表
            batch_size: 批处理大小
            normalize: 是否归一化向量
            prompt: 任务提示词
            task_type: 任务类型 (retrieval, classification, etc.)

        Returns:
            向量列表
        """
        if isinstance(texts, str):
            texts = [texts]

        batch_size = batch_size or self.config.batch_size

        # 使用本地模型
        if self.config.provider == "local":
            return self._encode_local(texts, normalize)

        # 使用远程 API
        return self._encode_remote(texts, batch_size, normalize, prompt, task_type)

    def _encode_local(
        self,
        texts: List[str],
        normalize: bool = True
    ) -> List[List[float]]:
        """使用本地模型编码"""
        model = self._get_local_model()
        embeddings = model.encode(
            texts,
            batch_size=self.config.batch_size,
            normalize_embeddings=normalize,
            convert_to_numpy=True
        )
        return embeddings.tolist()

    def _encode_remote(
        self,
        texts: List[str],
        batch_size: int,
        normalize: bool,
        prompt: Optional[str],
        task_type: Optional[str],
    ) -> List[List[float]]:
        """使用远程 API 编码"""
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            # 构建请求
            payload = {
                "model": self.config.model,
                "input": batch,
            }

            if prompt:
                payload["prompt"] = prompt
            if task_type:
                payload["task_type"] = task_type

            # 发送请求
            try:
                response = self.client.post(
                    "/embeddings",
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

                # 提取 embeddings
                for item in result["data"]:
                    embedding = item["embedding"]
                    if normalize:
                        embedding = self._normalize(embedding)
                    all_embeddings.append(embedding)

            except Exception as e:
                logger.error(f"嵌入 API 请求失败: {e}")
                # 返回零向量作为后备
                all_embeddings.extend([[0.0] * self.dimension] * len(batch))

        return all_embeddings

    @staticmethod
    def _normalize(embedding: List[float]) -> List[float]:
        """归一化向量"""
        norm = np.linalg.norm(embedding)
        if norm == 0:
            return embedding
        return [x / norm for x in embedding]

    def encode_with_cache(
        self,
        texts: Union[str, List[str]],
        cache_key: Optional[str] = None,
    ) -> List[List[float]]:
        """
        使用缓存编码

        Args:
            texts: 文本
            cache_key: 缓存键

        Returns:
            向量列表
        """
        if isinstance(texts, str):
            texts = [texts]

        # 检查缓存
        if cache_key:
            cached = []
            uncached_texts = []
            uncached_indices = []

            for i, text in enumerate(texts):
                key = f"{cache_key}:{text}"
                if key in self._embedding_cache:
                    cached.append((i, self._embedding_cache[key]))
                else:
                    uncached_texts.append(text)
                    uncached_indices.append(i)

            # 编码未缓存的文本
            if uncached_texts:
                new_embeddings = self.encode(uncached_texts)
                for idx, emb in zip(uncached_indices, new_embeddings):
                    key = f"{cache_key}:{texts[idx]}"
                    self._embedding_cache[key] = emb

            # 合并结果
            result = [None] * len(texts)
            for i, emb in cached:
                result[i] = emb
            for i, emb in zip(uncached_indices, new_embeddings):
                result[i] = emb

            return result

        return self.encode(texts)

    def get_embedding_cache_size(self) -> int:
        """获取缓存大小"""
        return len(self._embedding_cache)

    def clear_cache(self):
        """清空缓存"""
        self._embedding_cache.clear()
        logger.info("嵌入缓存已清空")

    def compute_similarity(
        self,
        embedding1: List[float],
        embedding2: List[float],
        metric: str = "cosine"
    ) -> float:
        """
        计算两个向量的相似度

        Args:
            embedding1: 向量1
            embedding2: 向量2
            metric: 距离度量 (cosine, dot, euclidean)

        Returns:
            相似度分数
        """
        if metric == "cosine":
            return np.dot(embedding1, embedding2) / (
                np.linalg.norm(embedding1) * np.linalg.norm(embedding2)
            )
        elif metric == "dot":
            return np.dot(embedding1, embedding2)
        elif metric == "euclidean":
            return float(np.linalg.norm(np.array(embedding1) - np.array(embedding2)))
        else:
            raise ValueError(f"不支持的度量: {metric}")

    def batch_compute_similarity(
        self,
        query_embedding: List[float],
        candidate_embeddings: List[List[float]],
        metric: str = "cosine"
    ) -> List[float]:
        """
        批量计算相似度

        Args:
            query_embedding: 查询向量
            candidate_embeddings: 候选向量列表
            metric: 距离度量

        Returns:
            相似度分数列表
        """
        query = np.array(query_embedding)
        candidates = np.array(candidate_embeddings)

        if metric == "cosine":
            # 归一化
            query_norm = query / np.linalg.norm(query)
            candidates_norm = candidates / np.linalg.norm(candidates, axis=1, keepdims=True)
            return np.dot(candidates_norm, query_norm).tolist()
        elif metric == "dot":
            return np.dot(candidates, query).tolist()
        elif metric == "euclidean":
            distances = np.linalg.norm(candidates - query, axis=1)
            # 转换为相似度 (距离越小相似度越高)
            return (1 / (1 + distances)).tolist()
        else:
            raise ValueError(f"不支持的度量: {metric}")


# ============= 单例管理 =============

_embedding_manager_instance: Optional[EmbeddingManager] = None


def get_embedding_manager(
    model_name: str = "deepseek-embed",
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    dimension: Optional[int] = None,
) -> EmbeddingManager:
    """
    获取嵌入管理器单例

    Args:
        model_name: 模型名称
        api_base: API 基础 URL
        api_key: API 密钥
        dimension: 向量维度

    Returns:
        嵌入管理器实例
    """
    global _embedding_manager_instance

    if _embedding_manager_instance is None:
        _embedding_manager_instance = EmbeddingManager(
            model_name=model_name,
            api_base=api_base,
            api_key=api_key,
            dimension=dimension
        )

    return _embedding_manager_instance


def reset_embedding_manager():
    """重置嵌入管理器单例"""
    global _embedding_manager_instance
    if _embedding_manager_instance:
        _embedding_manager_instance.clear_cache()
    _embedding_manager_instance = None
