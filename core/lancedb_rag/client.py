# client.py - LanceDB 客户端管理
"""
LanceDB 客户端管理模块

提供 LanceDB 数据库的连接管理、schema 定义和基础操作
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from datetime import datetime
import json

try:
    import lancedb
    try:
        from lancedb.rafs import StorageOptions
    except ImportError:
        StorageOptions = None
    LANCEDB_AVAILABLE = True
except ImportError:
    LANCEDB_AVAILABLE = False
    StorageOptions = None
    logging.warning("LanceDB 未安装，请运行: pip install lancedb")

logger = logging.getLogger(__name__)


# ============= Schema 定义 =============

LITERATURE_SCHEMA = {
    "id": "string",
    "doi": "string",
    "arxiv_id": "string",
    "pmid": "string",
    "title": "string",
    "abstract": "string",
    "full_text": "string",
    "authors": "list<string>",
    "journal": "string",
    "year": "int",
    "keywords": "list<string>",
    "entity_type": "string",  # "literature"
    "methods": "string",
    "results": "string",
    "introduction": "string",
    "discussion": "string",
    "conclusions": "string",
    "metadata": "string",  # JSON 字符串
    "created_at": "timestamp",
    "updated_at": "timestamp",
    # Chunk 支持字段
    "doc_id": "string",          # 来源文档 ID
    "chunk_index": "int",        # chunk 索引
    "section": "string",         # 来源章节 (abstract, introduction, methods, etc.)
    "doc_type": "string",        # 文档类型: "metadata" | "content_chunk"
    "chunk_length": "int",       # chunk 长度
    # 向量字段在创建表时动态添加
}

STRUCTURE_SCHEMA = {
    "id": "string",
    "structure_type": "string",  # "pdb" | "emdb" | "alphafold"
    "title": "string",
    "description": "string",
    "methods": "string",
    "resolution": "float",
    "organism": "string",
    "expression_system": "string",
    "gene": "string",
    "protein_name": "string",
    "authors": "list<string>",
    "keywords": "list<string>",
    "literature_ids": "list<string>",
    "entity_type": "string",  # "structure"
    "metadata": "string",  # JSON 字符串
    "created_at": "timestamp",
    "updated_at": "timestamp",
}

SESSION_MEMORY_SCHEMA = {
    "session_id": "string",
    "query": "string",
    "response": "string",
    "timestamp": "timestamp",
    "retrieved_docs": "string",  # JSON 字符串
    "query_type": "string",  # "literature" | "structure" | "general"
}


@dataclass
class TableConfig:
    """表配置"""
    name: str
    schema: Dict[str, str]
    vector_column: str = "embedding"
    vector_dim: int = 1536


class LanceDBClient:
    """LanceDB 客户端管理类"""

    DEFAULT_TABLES = {
        "literature": TableConfig(
            name="literature",
            schema=LITERATURE_SCHEMA,
            vector_column="embedding",
            vector_dim=1536
        ),
        "structure": TableConfig(
            name="structure",
            schema=STRUCTURE_SCHEMA,
            vector_column="embedding",
            vector_dim=1536
        ),
        "session_memory": TableConfig(
            name="session_memory",
            schema=SESSION_MEMORY_SCHEMA,
            vector_column=None,
            vector_dim=0
        ),
    }

    def __init__(
        self,
        db_path: Optional[str] = None,
        vector_dim: int = 1536,
        storage_options: "Optional[Any]" = None,
    ):
        """
        初始化 LanceDB 客户端

        Args:
            db_path: 数据库路径，默认使用 data/lancedb
            vector_dim: 向量维度
            storage_options: LanceDB 存储选项
        """
        if not LANCEDB_AVAILABLE:
            raise ImportError("LanceDB 未安装，请运行: pip install lancedb")

        self.db_path = db_path or self._get_default_db_path()
        self.vector_dim = vector_dim
        self.storage_options = storage_options
        self._db = None
        self._tables = {}

    @staticmethod
    def _get_default_db_path() -> str:
        """获取默认数据库路径"""
        base_dir = Path(__file__).parent.parent.parent
        data_dir = base_dir / "data" / "lancedb"
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir)

    def connect(self) -> "LanceDBClient":
        """连接到 LanceDB 数据库"""
        if self._db is None:
            self._db = lancedb.connect(
                self.db_path,
                storage_options=self.storage_options
            )
            logger.info(f"已连接到 LanceDB: {self.db_path}")
        return self

    def disconnect(self):
        """断开连接"""
        self._db = None
        self._tables = {}
        logger.info("已断开 LanceDB 连接")

    @property
    def db(self):
        """获取数据库连接"""
        if self._db is None:
            self.connect()
        return self._db

    def create_table(
        self,
        table_config: TableConfig,
        overwrite: bool = False
    ) -> Any:
        """
        创建表

        Args:
            table_config: 表配置
            overwrite: 是否覆盖已存在的表

        Returns:
            表对象
        """
        table_name = table_config.name

        # Get table names - handle different API versions
        table_list = self.db.list_tables()
        if hasattr(table_list, 'tables'):
            table_names = table_list.tables
        else:
            table_names = list(table_list)

        # 检查表是否存在
        if table_name in table_names and not overwrite:
            logger.info(f"表 {table_name} 已存在")
            return self.db.open_table(table_name)

        # 如果需要覆盖，先删除
        if table_name in table_names and overwrite:
            self.db.drop_table(table_name)
            logger.info(f"表 {table_name} 已删除")

        # 构建 schema
        schema_dict = table_config.schema.copy()

        # 如果有向量字段，添加向量列
        if table_config.vector_column and table_config.vector_dim > 0:
            schema_dict[table_config.vector_column] = f"vector({table_config.vector_dim})"

        # 转换 schema 字典为 PyArrow Schema
        try:
            import pyarrow as pa
            fields = []
            for field_name, field_type in schema_dict.items():
                # 处理 vector 类型
                if field_type.startswith("vector("):
                    dim = int(field_type.split("(")[1].split(")")[0])
                    fields.append(pa.field(field_name, pa.list_(pa.float32(), dim)))
                elif field_type == "int":
                    fields.append(pa.field(field_name, pa.int64()))
                elif field_type == "float":
                    fields.append(pa.field(field_name, pa.float64()))
                elif field_type == "timestamp":
                    fields.append(pa.field(field_name, pa.timestamp('us')))
                elif field_type == "list<string>":
                    fields.append(pa.field(field_name, pa.list_(pa.string())))
                else:
                    fields.append(pa.field(field_name, pa.string()))
            pa_schema = pa.schema(fields)
        except ImportError:
            logger.error("PyArrow 未安装")
            raise ImportError("PyArrow 未安装，请运行: pip install pyarrow")

        # 创建表
        try:
            table = self.db.create_table(
                table_name,
                schema=pa_schema
            )
            logger.info(f"表 {table_name} 已创建")
            self._tables[table_name] = table
            return table
        except Exception as e:
            logger.error(f"创建表 {table_name} 失败: {e}")
            raise

    def open_table(self, table_name: str) -> Any:
        """
        打开表

        Args:
            table_name: 表名

        Returns:
            表对象
        """
        if table_name not in self._tables:
            self._tables[table_name] = self.db.open_table(table_name)
        return self._tables[table_name]

    def get_or_create_table(
        self,
        table_config: TableConfig,
        overwrite: bool = False
    ) -> Any:
        """
        获取或创建表

        Args:
            table_config: 表配置
            overwrite: 是否覆盖已存在的表

        Returns:
            表对象
        """
        # Get table names - handle different API versions
        table_list = self.db.list_tables()
        if hasattr(table_list, 'tables'):
            table_names = table_list.tables
        else:
            table_names = list(table_list)

        if table_config.name in table_names:
            if overwrite:
                self.delete_table(table_config.name)
                return self.create_table(table_config)
            return self.open_table(table_config.name)
        return self.create_table(table_config)

    def create_all_tables(self, overwrite: bool = False):
        """创建所有默认表"""
        for table_config in self.DEFAULT_TABLES.values():
            self.get_or_create_table(table_config, overwrite=overwrite)

    def delete_table(self, table_name: str):
        """删除表"""
        try:
            self.db.drop_table(table_name)
            if table_name in self._tables:
                del self._tables[table_name]
            logger.info(f"表 {table_name} 已删除")
        except Exception as e:
            logger.error(f"删除表 {table_name} 失败: {e}")
            raise

    def list_tables(self) -> List[str]:
        """列出所有表"""
        table_list = self.db.list_tables()
        if hasattr(table_list, 'tables'):
            return table_list.tables
        return list(table_list)

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        table_list = self.db.list_tables()
        if hasattr(table_list, 'tables'):
            table_names = table_list.tables
        else:
            table_names = list(table_list)
        return table_name in table_names

    def create_vector_index(
        self,
        table_name: str,
        column: str = "embedding",
        index_type: str = "IVF_PQ",
        metric: str = "cosine",
        **kwargs
    ):
        """
        创建向量索引

        Args:
            table_name: 表名
            column: 向量列名
            index_type: 索引类型 (IVF_PQ, IVF_HNSW, etc.)
            metric: 距离度量 (cosine, l2, dot)
            **kwargs: 其他索引参数
        """
        table = self.open_table(table_name)

        # 构建索引选项
        index_params = {
            "type": index_type,
            "metric": metric,
            **kwargs
        }

        try:
            table.create_index(
                column=column,
                index=index_params
            )
            logger.info(f"表 {table_name} 的向量索引已创建")
        except Exception as e:
            logger.warning(f"创建向量索引失败: {e}")

    def create_fts_index(
        self,
        table_name: str,
        columns: List[str]
    ):
        """
        创建全文搜索索引

        Args:
            table_name: 表名
            columns: 要索引的文本列
        """
        table = self.open_table(table_name)

        try:
            for column in columns:
                table.create_fts_index(column)
            logger.info(f"表 {table_name} 的 FTS 索引已创建: {columns}")
        except Exception as e:
            logger.warning(f"创建 FTS 索引失败: {e}")


# ============= 单例管理 =============

_client_instance: Optional[LanceDBClient] = None


def get_lancedb_client(
    db_path: Optional[str] = None,
    vector_dim: int = 1536,
    connect: bool = True
) -> LanceDBClient:
    """
    获取 LanceDB 客户端单例

    Args:
        db_path: 数据库路径
        vector_dim: 向量维度
        connect: 是否立即连接

    Returns:
        LanceDB 客户端实例
    """
    global _client_instance

    if _client_instance is None:
        _client_instance = LanceDBClient(
            db_path=db_path,
            vector_dim=vector_dim
        )
        if connect:
            _client_instance.connect()

    return _client_instance


def reset_lancedb_client():
    """重置 LanceDB 客户端单例"""
    global _client_instance
    if _client_instance:
        _client_instance.disconnect()
    _client_instance = None
