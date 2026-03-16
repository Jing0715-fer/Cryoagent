# ground_truth.py - Ground Truth 管理
"""
Ground Truth 管理模块

管理检索评估的测试数据集，包括：
- 创建和导入 Ground Truth
- 存储 Ground Truth 到数据库
- 加载和查询 Ground Truth
"""

import json
import logging
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)


@dataclass
class GroundTruthEntry:
    """单个查询的 Ground Truth 条目"""

    query_id: str  # 查询 ID
    query_text: str  # 查询文本
    relevant_ids: List[str]  # 相关文档 ID 列表
    relevance_scores: Optional[Dict[str, float]] = None  # 文档 ID -> 相关性分数
    category: Optional[str] = None  # 查询类别 (如 "literature", "structure")
    notes: Optional[str] = None  # 备注
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'query_id': self.query_id,
            'query_text': self.query_text,
            'relevant_ids': json.dumps(self.relevant_ids),
            'relevance_scores': json.dumps(self.relevance_scores) if self.relevance_scores else None,
            'category': self.category,
            'notes': self.notes,
            'created_at': self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'GroundTruthEntry':
        """从字典创建"""
        return cls(
            query_id=data['query_id'],
            query_text=data['query_text'],
            relevant_ids=json.loads(data['relevant_ids']) if isinstance(data.get('relevant_ids'), str) else data.get('relevant_ids', []),
            relevance_scores=json.loads(data['relevance_scores']) if data.get('relevance_scores') and isinstance(data['relevance_scores'], str) else data.get('relevance_scores'),
            category=data.get('category'),
            notes=data.get('notes'),
            created_at=data.get('created_at', datetime.now().isoformat()),
        )

    def get_relevant_set(self) -> Set[str]:
        """获取相关文档 ID 集合"""
        return set(self.relevant_ids)


class GroundTruthManager:
    """Ground Truth 管理器"""

    def __init__(self, storage=None):
        """
        初始化管理器

        Args:
            storage: 存储后端（EvaluationStorage 实例）
        """
        self.storage = storage
        self._entries: Dict[str, GroundTruthEntry] = {}

    def add_entry(
        self,
        query_text: str,
        relevant_ids: List[str],
        relevance_scores: Optional[Dict[str, float]] = None,
        category: Optional[str] = None,
        notes: Optional[str] = None,
        query_id: Optional[str] = None,
    ) -> GroundTruthEntry:
        """
        添加 Ground Truth 条目

        Args:
            query_text: 查询文本
            relevant_ids: 相关文档 ID 列表
            relevance_scores: 可选的相关性分数映射
            category: 查询类别
            notes: 备注
            query_id: 可选的查询 ID（自动生成如果未提供）

        Returns:
            创建的 GroundTruthEntry
        """
        query_id = query_id or f"q_{uuid.uuid4().hex[:8]}"

        entry = GroundTruthEntry(
            query_id=query_id,
            query_text=query_text,
            relevant_ids=relevant_ids,
            relevance_scores=relevance_scores,
            category=category,
            notes=notes,
        )

        self._entries[query_id] = entry

        # 存储到数据库
        if self.storage:
            self.storage.save_ground_truth(entry)

        logger.info(f"添加 Ground Truth: {query_id} - {query_text[:50]}...")
        return entry

    def get_entry(self, query_id: str) -> Optional[GroundTruthEntry]:
        """获取指定条目"""
        if query_id in self._entries:
            return self._entries[query_id]

        # 从存储加载
        if self.storage:
            entry = self.storage.load_ground_truth(query_id)
            if entry:
                self._entries[query_id] = entry
                return entry

        return None

    def get_all_entries(self) -> List[GroundTruthEntry]:
        """获取所有条目"""
        if self.storage:
            entries = self.storage.load_all_ground_truth()
            self._entries = {e.query_id: e for e in entries}
            return entries

        return list(self._entries.values())

    def get_entries_by_category(self, category: str) -> List[GroundTruthEntry]:
        """按类别获取条目"""
        return [e for e in self.get_all_entries() if e.category == category]

    def update_entry(self, query_id: str, **kwargs) -> Optional[GroundTruthEntry]:
        """更新条目"""
        entry = self.get_entry(query_id)
        if not entry:
            return None

        for key, value in kwargs.items():
            if hasattr(entry, key):
                setattr(entry, key, value)

        if self.storage:
            self.storage.save_ground_truth(entry)

        return entry

    def delete_entry(self, query_id: str) -> bool:
        """删除条目"""
        if query_id in self._entries:
            del self._entries[query_id]

        if self.storage:
            self.storage.delete_ground_truth(query_id)

        return True

    def import_from_json(self, file_path: str) -> int:
        """
        从 JSON 文件导入 Ground Truth

        文件格式：
        [
            {
                "query_text": "...",
                "relevant_ids": ["id1", "id2"],
                "relevance_scores": {"id1": 3.0, "id2": 2.0},
                "category": "literature"
            },
            ...
        ]

        Args:
            file_path: JSON 文件路径

        Returns:
            导入的条目数量
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        count = 0
        for item in data:
            self.add_entry(
                query_text=item['query_text'],
                relevant_ids=item['relevant_ids'],
                relevance_scores=item.get('relevance_scores'),
                category=item.get('category'),
                notes=item.get('notes'),
            )
            count += 1

        logger.info(f"从 {file_path} 导入了 {count} 条 Ground Truth")
        return count

    def export_to_json(self, file_path: str) -> int:
        """导出到 JSON 文件"""
        entries = self.get_all_entries()
        data = [asdict(e) for e in entries]

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"导出 {len(entries)} 条 Ground Truth 到 {file_path}")
        return len(entries)

    def create_sample_dataset(self) -> List[GroundTruthEntry]:
        """
        创建示例数据集

        用于测试和演示

        Returns:
            创建的条目列表
        """
        sample_queries = [
            {
                "query_text": "Vγ9Vδ2 T cell receptor structure",
                "relevant_ids": ["6T0K", "6T0L", "6T0M"],
                "relevance_scores": {"6T0K": 3.0, "6T0L": 2.0, "6T0M": 2.0},
                "category": "structure",
            },
            {
                "query_text": "GPR179 protein cryo-EM analysis",
                "relevant_ids": ["literature_1", "literature_2"],
                "relevance_scores": {"literature_1": 3.0, "literature_2": 2.0},
                "category": "literature",
            },
            {
                "query_text": "Butyrophilin BTN3A1 activation mechanism",
                "relevant_ids": ["4F80", "4F8X", "literature_3"],
                "relevance_scores": {"4F80": 3.0, "4F8X": 2.5, "literature_3": 2.0},
                "category": "mixed",
            },
        ]

        entries = []
        for sq in sample_queries:
            entry = self.add_entry(**sq)
            entries.append(entry)

        return entries