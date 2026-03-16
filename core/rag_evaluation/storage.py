# storage.py - 评估结果存储
"""
评估结果存储模块

使用 SQLite 存储评估结果和 Ground Truth，支持：
- 评估运行记录
- 单次查询评估结果
- Ground Truth 存储
- 历史查询和比较
"""

import sqlite3
import json
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)


@dataclass
class EvaluationRun:
    """评估运行记录"""

    run_id: str
    name: str
    description: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    metrics_summary: Dict[str, float] = field(default_factory=dict)
    query_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        return {
            'run_id': self.run_id,
            'name': self.name,
            'description': self.description,
            'config': json.dumps(self.config),
            'metrics_summary': json.dumps(self.metrics_summary),
            'query_count': self.query_count,
            'created_at': self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'EvaluationRun':
        return cls(
            run_id=data['run_id'],
            name=data['name'],
            description=data.get('description', ''),
            config=json.loads(data['config']) if isinstance(data.get('config'), str) else data.get('config', {}),
            metrics_summary=json.loads(data['metrics_summary']) if isinstance(data.get('metrics_summary'), str) else data.get('metrics_summary', {}),
            query_count=data.get('query_count', 0),
            created_at=data.get('created_at', datetime.now().isoformat()),
        )


@dataclass
class EvaluationResult:
    """单次查询评估结果"""

    id: int = 0
    run_id: str = ""
    query_id: str = ""
    query_text: str = ""
    retrieved_ids: List[str] = field(default_factory=list)
    relevant_ids: List[str] = field(default_factory=list)

    # 指标
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    mrr: float = 0.0
    ndcg_at_10: float = 0.0

    latency_ms: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        return {
            'run_id': self.run_id,
            'query_id': self.query_id,
            'query_text': self.query_text,
            'retrieved_ids': json.dumps(self.retrieved_ids),
            'relevant_ids': json.dumps(self.relevant_ids),
            'precision_at_5': self.precision_at_5,
            'precision_at_10': self.precision_at_10,
            'recall_at_5': self.recall_at_5,
            'recall_at_10': self.recall_at_10,
            'mrr': self.mrr,
            'ndcg_at_10': self.ndcg_at_10,
            'latency_ms': self.latency_ms,
            'created_at': self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'EvaluationResult':
        return cls(
            id=data.get('id', 0),
            run_id=data['run_id'],
            query_id=data['query_id'],
            query_text=data['query_text'],
            retrieved_ids=json.loads(data['retrieved_ids']) if isinstance(data.get('retrieved_ids'), str) else data.get('retrieved_ids', []),
            relevant_ids=json.loads(data['relevant_ids']) if isinstance(data.get('relevant_ids'), str) else data.get('relevant_ids', []),
            precision_at_5=data.get('precision_at_5', 0.0),
            precision_at_10=data.get('precision_at_10', 0.0),
            recall_at_5=data.get('recall_at_5', 0.0),
            recall_at_10=data.get('recall_at_10', 0.0),
            mrr=data.get('mrr', 0.0),
            ndcg_at_10=data.get('ndcg_at_10', 0.0),
            latency_ms=data.get('latency_ms', 0.0),
            created_at=data.get('created_at', datetime.now().isoformat()),
        )


class EvaluationStorage:
    """评估存储后端"""

    # Schema 定义
    SCHEMA_SQL = """
    -- Ground Truth 表
    CREATE TABLE IF NOT EXISTS ground_truth (
        query_id TEXT PRIMARY KEY,
        query_text TEXT NOT NULL,
        relevant_ids_json TEXT NOT NULL,
        relevance_scores_json TEXT,
        category TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    -- 评估运行表
    CREATE TABLE IF NOT EXISTS evaluation_runs (
        run_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        config_json TEXT,
        metrics_summary_json TEXT,
        query_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    -- 评估结果表
    CREATE TABLE IF NOT EXISTS evaluation_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        query_id TEXT NOT NULL,
        query_text TEXT NOT NULL,
        retrieved_ids_json TEXT,
        relevant_ids_json TEXT,
        precision_at_5 REAL,
        precision_at_10 REAL,
        recall_at_5 REAL,
        recall_at_10 REAL,
        mrr REAL,
        ndcg_at_10 REAL,
        latency_ms REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (run_id) REFERENCES evaluation_runs(run_id)
    );

    -- 搜索日志表
    CREATE TABLE IF NOT EXISTS search_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        query_text TEXT NOT NULL,
        num_results INTEGER,
        latency_ms REAL,
        search_type TEXT,
        session_id TEXT
    );

    -- 索引
    CREATE INDEX IF NOT EXISTS idx_results_run_id ON evaluation_results(run_id);
    CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON search_logs(timestamp);
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化存储

        Args:
            db_path: 数据库文件路径，默认为 data/rag_evaluation.db
        """
        if db_path is None:
            base_dir = Path(__file__).parent.parent.parent
            data_dir = base_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "rag_evaluation.db")

        self.db_path = db_path
        self._conn = None
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row

        # 创建表
        self._conn.executescript(self.SCHEMA_SQL)
        self._conn.commit()

        logger.info(f"评估数据库初始化完成: {self.db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    # ============= Ground Truth 操作 =============

    def save_ground_truth(self, entry) -> bool:
        """保存 Ground Truth 条目"""
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO ground_truth
                (query_id, query_text, relevant_ids_json, relevance_scores_json, category, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.query_id,
                entry.query_text,
                json.dumps(entry.relevant_ids),
                json.dumps(entry.relevance_scores) if entry.relevance_scores else None,
                entry.category,
                entry.notes,
                entry.created_at,
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"保存 Ground Truth 失败: {e}")
            return False

    def load_ground_truth(self, query_id: str):
        """加载单个 Ground Truth"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM ground_truth WHERE query_id = ?",
            (query_id,)
        ).fetchone()

        if row:
            from .ground_truth import GroundTruthEntry
            return GroundTruthEntry.from_dict(dict(row))
        return None

    def load_all_ground_truth(self) -> List:
        """加载所有 Ground Truth"""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM ground_truth ORDER BY created_at DESC").fetchall()

        from .ground_truth import GroundTruthEntry
        return [GroundTruthEntry.from_dict(dict(row)) for row in rows]

    def delete_ground_truth(self, query_id: str) -> bool:
        """删除 Ground Truth"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM ground_truth WHERE query_id = ?", (query_id,))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"删除 Ground Truth 失败: {e}")
            return False

    # ============= 评估运行操作 =============

    def save_run(self, run: EvaluationRun) -> bool:
        """保存评估运行"""
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO evaluation_runs
                (run_id, name, description, config_json, metrics_summary_json, query_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                run.run_id,
                run.name,
                run.description,
                json.dumps(run.config),
                json.dumps(run.metrics_summary),
                run.query_count,
                run.created_at,
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"保存评估运行失败: {e}")
            return False

    def load_run(self, run_id: str) -> Optional[EvaluationRun]:
        """加载评估运行"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM evaluation_runs WHERE run_id = ?",
            (run_id,)
        ).fetchone()

        if row:
            return EvaluationRun.from_dict(dict(row))
        return None

    def list_runs(self, limit: int = 20) -> List[EvaluationRun]:
        """列出评估运行"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM evaluation_runs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()

        return [EvaluationRun.from_dict(dict(row)) for row in rows]

    def delete_run(self, run_id: str) -> bool:
        """删除评估运行及其结果"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM evaluation_results WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM evaluation_runs WHERE run_id = ?", (run_id,))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"删除评估运行失败: {e}")
            return False

    # ============= 评估结果操作 =============

    def save_result(self, result: EvaluationResult) -> int:
        """保存评估结果"""
        conn = self._get_conn()
        try:
            cursor = conn.execute("""
                INSERT INTO evaluation_results
                (run_id, query_id, query_text, retrieved_ids_json, relevant_ids_json,
                 precision_at_5, precision_at_10, recall_at_5, recall_at_10,
                 mrr, ndcg_at_10, latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.run_id,
                result.query_id,
                result.query_text,
                json.dumps(result.retrieved_ids),
                json.dumps(result.relevant_ids),
                result.precision_at_5,
                result.precision_at_10,
                result.recall_at_5,
                result.recall_at_10,
                result.mrr,
                result.ndcg_at_10,
                result.latency_ms,
                result.created_at,
            ))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"保存评估结果失败: {e}")
            return 0

    def load_results(self, run_id: str) -> List[EvaluationResult]:
        """加载评估运行的所有结果"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM evaluation_results WHERE run_id = ? ORDER BY id",
            (run_id,)
        ).fetchall()

        return [EvaluationResult.from_dict(dict(row)) for row in rows]

    # ============= 搜索日志操作 =============

    def log_search(
        self,
        query_text: str,
        num_results: int,
        latency_ms: float,
        search_type: str = "vector",
        session_id: Optional[str] = None,
    ) -> int:
        """记录搜索日志"""
        conn = self._get_conn()
        try:
            cursor = conn.execute("""
                INSERT INTO search_logs
                (timestamp, query_text, num_results, latency_ms, search_type, session_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                query_text,
                num_results,
                latency_ms,
                search_type,
                session_id,
            ))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"记录搜索日志失败: {e}")
            return 0

    def get_search_stats(self, days: int = 7) -> Dict[str, Any]:
        """获取搜索统计"""
        conn = self._get_conn()

        # 总搜索次数
        total_searches = conn.execute("""
            SELECT COUNT(*) as count FROM search_logs
            WHERE timestamp >= datetime('now', ?)
        """, (f'-{days} days',)).fetchone()['count']

        # 平均延迟
        avg_latency = conn.execute("""
            SELECT AVG(latency_ms) as avg FROM search_logs
            WHERE timestamp >= datetime('now', ?)
        """, (f'-{days} days',)).fetchone()['avg'] or 0

        # 平均结果数
        avg_results = conn.execute("""
            SELECT AVG(num_results) as avg FROM search_logs
            WHERE timestamp >= datetime('now', ?)
        """, (f'-{days} days',)).fetchone()['avg'] or 0

        # 按搜索类型统计
        by_type = conn.execute("""
            SELECT search_type, COUNT(*) as count
            FROM search_logs
            WHERE timestamp >= datetime('now', ?)
            GROUP BY search_type
        """, (f'-{days} days',)).fetchall()

        return {
            'total_searches': total_searches,
            'avg_latency_ms': round(avg_latency, 2),
            'avg_results': round(avg_results, 2),
            'by_type': {row['search_type']: row['count'] for row in by_type},
            'period_days': days,
        }

    def close(self):
        """关闭连接"""
        if self._conn:
            self._conn.close()
            self._conn = None