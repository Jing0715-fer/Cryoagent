# session.py - 会话记忆
"""
会话记忆模块

管理对话历史和上下文信息
"""

import logging
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import hashlib
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============= 会话配置 =============

@dataclass
class SessionConfig:
    """会话配置"""
    max_history: int = 10  # 最大历史记录数
    max_tokens: int = 4000  # 最大 token 数
    session_ttl: int = 3600  # 会话过期时间（秒）
    similarity_threshold: float = 0.7  # 相似度阈值
    include_in_context: bool = True  # 是否包含在上下文中


@dataclass
class SessionEntry:
    """会话条目"""
    session_id: str
    query: str
    response: str
    timestamp: datetime
    retrieved_docs: List[Dict[str, Any]] = field(default_factory=list)
    query_type: str = "general"
    metadata: Dict[str, Any] = field(default_factory=dict)


class SessionMemory:
    """
    会话记忆管理器

    管理对话历史，支持:
    - 多会话管理
    - 历史记录存储
    - 上下文压缩
    - 相似查询检索
    """

    def __init__(
        self,
        config: Optional[SessionConfig] = None,
        storage: Optional[Any] = None,
    ):
        """
        初始化会话记忆管理器

        Args:
            config: 会话配置
            storage: 存储后端（可选）
        """
        self.config = config or SessionConfig()
        self.storage = storage

        # 内存存储
        self.sessions: Dict[str, List[SessionEntry]] = defaultdict(list)
        self.session_timestamps: Dict[str, datetime] = {}

        # 嵌入函数（用于相似查询检索）
        self._embedding_fn: Optional[Callable] = None

    def set_embedding_fn(self, embedding_fn: Callable[[str], List[float]]):
        """
        设置嵌入函数

        Args:
            embedding_fn: 嵌入函数
        """
        self._embedding_fn = embedding_fn

    def add_entry(
        self,
        session_id: str,
        query: str,
        response: str,
        retrieved_docs: Optional[List[Dict[str, Any]]] = None,
        query_type: str = "general",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        添加会话条目

        Args:
            session_id: 会话 ID
            query: 查询
            response: 响应
            retrieved_docs: 检索到的文档
            query_type: 查询类型
            metadata: 额外元数据
        """
        entry = SessionEntry(
            session_id=session_id,
            query=query,
            response=response,
            timestamp=datetime.now(),
            retrieved_docs=retrieved_docs or [],
            query_type=query_type,
            metadata=metadata or {},
        )

        # 添加到会话
        self.sessions[session_id].append(entry)
        self.session_timestamps[session_id] = datetime.now()

        # 修剪历史
        self._prune_session(session_id)

        # 持久化（如果支持）
        if self.storage:
            self._persist_entry(entry)

    def _prune_session(self, session_id: str):
        """修剪会话历史"""
        session = self.sessions[session_id]

        # 按数量修剪
        if len(session) > self.config.max_history:
            self.sessions[session_id] = session[-self.config.max_history:]

        # 按时间修剪
        cutoff_time = datetime.now() - timedelta(seconds=self.config.session_ttl)
        self.sessions[session_id] = [
            e for e in self.sessions[session_id]
            if e.timestamp > cutoff_time
        ]

        # 更新时间戳
        if self.sessions[session_id]:
            self.session_timestamps[session_id] = self.sessions[session_id][-1].timestamp
        else:
            del self.sessions[session_id]
            del self.session_timestamps[session_id]

    def get_history(
        self,
        session_id: str,
        max_entries: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取会话历史

        Args:
            session_id: 会话 ID
            max_entries: 最大条目数

        Returns:
            历史记录列表
        """
        if session_id not in self.sessions:
            return []

        history = self.sessions[session_id]
        max_entries = max_entries or self.config.max_history

        return [
            {
                "query": e.query,
                "response": e.response,
                "timestamp": e.timestamp.isoformat(),
                "query_type": e.query_type,
            }
            for e in history[-max_entries:]
        ]

    def get_context(
        self,
        session_id: str,
        include_docs: bool = True,
    ) -> str:
        """
        获取会话上下文

        Args:
            session_id: 会话 ID
            include_docs: 是否包含检索到的文档

        Returns:
            格式化的上下文字符串
        """
        history = self.get_history(session_id)

        if not history:
            return ""

        context_parts = []
        context_parts.append("## 对话历史\n")

        for i, entry in enumerate(history):
            context_parts.append(f"### 问题 {i + 1}: {entry['query']}")
            context_parts.append(f"**回答**: {entry['response']}\n")

            if include_docs and 'retrieved_docs' in entry:
                context_parts.append("**参考文档**:")
                for doc in entry.get('retrieved_docs', [])[:3]:
                    title = doc.get('title', 'Unknown')
                    context_parts.append(f"- {title}")

            context_parts.append("")

        return "\n".join(context_parts)

    def find_similar_queries(
        self,
        query: str,
        session_id: Optional[str] = None,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        查找相似查询

        Args:
            query: 查询
            session_id: 限制的会话 ID
            top_k: 返回数量

        Returns:
            相似查询列表
        """
        if not self._embedding_fn:
            return []

        # 获取查询嵌入
        query_embedding = self._embedding_fn(query)

        # 收集所有历史查询
        candidates = []
        sessions_to_search = (
            {session_id: self.sessions[session_id]}
            if session_id and session_id in self.sessions
            else self.sessions
        )

        for sid, entries in sessions_to_search.items():
            for entry in entries:
                candidates.append({
                    "session_id": sid,
                    "query": entry.query,
                    "response": entry.response,
                    "timestamp": entry.timestamp,
                })

        if not candidates:
            return []

        # 计算相似度
        results = []
        for candidate in candidates:
            cand_embedding = self._embedding_fn(candidate["query"])
            similarity = self._cosine_similarity(query_embedding, cand_embedding)

            if similarity >= self.config.similarity_threshold:
                results.append({
                    **candidate,
                    "similarity": similarity,
                })

        # 排序并返回 top_k
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """计算余弦相似度"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)

    def get_relevant_context(
        self,
        query: str,
        session_id: str,
        max_contexts: int = 3,
    ) -> str:
        """
        获取与当前查询相关的上下文

        Args:
            query: 当前查询
            session_id: 会话 ID
            max_contexts: 最大上下文数量

        Returns:
            相关上下文字符串
        """
        similar = self.find_similar_queries(query, session_id, top_k=max_contexts)

        if not similar:
            return ""

        context_parts = ["## 相关历史\n"]

        for item in similar:
            context_parts.append(f"**历史问题**: {item['query']}")
            context_parts.append(f"**历史回答**: {item['response'][:200]}...")
            context_parts.append("")

        return "\n".join(context_parts)

    def clear_session(self, session_id: str):
        """清除会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self.session_timestamps:
            del self.session_timestamps[session_id]

    def clear_all(self):
        """清除所有会话"""
        self.sessions.clear()
        self.session_timestamps.clear()

    def _persist_entry(self, entry: SessionEntry):
        """持久化会话条目"""
        try:
            data = {
                "session_id": entry.session_id,
                "query": entry.query,
                "response": entry.response,
                "timestamp": entry.timestamp.isoformat(),
                "retrieved_docs": json.dumps(entry.retrieved_docs),
                "query_type": entry.query_type,
                "metadata": json.dumps(entry.metadata),
            }
            # 存储到后端
            if hasattr(self.storage, 'add'):
                self.storage.add(data)
        except Exception as e:
            logger.warning(f"持久化会话失败: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取会话统计"""
        total_entries = sum(len(entries) for entries in self.sessions.values())

        return {
            "total_sessions": len(self.sessions),
            "total_entries": total_entries,
            "session_details": {
                sid: len(entries)
                for sid, entries in self.sessions.items()
            }
        }


# ============= 便捷函数 =============

def create_session_memory(
    max_history: int = 10,
    session_ttl: int = 3600,
) -> SessionMemory:
    """
    创建会话记忆管理器

    Args:
        max_history: 最大历史记录数
        session_ttl: 会话过期时间

    Returns:
        SessionMemory 实例
    """
    config = SessionConfig(
        max_history=max_history,
        session_ttl=session_ttl,
    )
    return SessionMemory(config=config)
