# file: literature_index_tracker.py (修复版本)
"""
索引状态跟踪模块 - 记录索引构建状态和版本控制
修复版本：修复SQLite语法错误
"""
import os, json, logging, hashlib, time, sqlite3, threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)

# ---------- 索引状态枚举 ----------
class IndexStatus(Enum):
    """索引状态枚举"""
    PENDING = "pending"
    BUILDING = "building"
    COMPLETED = "completed"
    FAILED = "failed"
    UPDATING = "updating"
    STALE = "stale"

class IndexType(Enum):
    """索引类型枚举"""
    FULL = "full"
    INCREMENTAL = "incremental"
    STRUCTURE_ONLY = "structure_only"
    VECTOR_ONLY = "vector_only"

# ---------- 数据模型 ----------
@dataclass
class IndexBuildRecord:
    """索引构建记录"""
    id: int = None
    index_type: IndexType = IndexType.FULL
    status: IndexStatus = IndexStatus.PENDING
    start_time: datetime = None
    end_time: datetime = None
    total_documents: int = 0
    new_documents: int = 0
    updated_documents: int = 0
    deleted_documents: int = 0
    structure_count: int = 0
    error_message: str = None
    duration_seconds: float = 0.0
    version: str = "2.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        data['index_type'] = self.index_type.value
        data['status'] = self.status.value
        data['start_time'] = self.start_time.isoformat() if self.start_time else None
        data['end_time'] = self.end_time.isoformat() if self.end_time else None
        return data

@dataclass
class DocumentChangeRecord:
    """文档变更记录"""
    document_id: str
    source_id: str
    entity_type: str
    action: str  # 'added', 'updated', 'deleted'
    old_hash: str = None
    new_hash: str = None
    change_time: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

# ---------- 索引状态跟踪器 ----------
class IndexStateTracker:
    """索引状态跟踪器"""
    
    _instance = None
    _initialized = False
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(IndexStateTracker, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, db_path: str = None):
        """初始化方法，确保只执行一次"""
        if IndexStateTracker._initialized:
            logger.info("IndexStateTracker 已经初始化过，跳过重复初始化")
            return

        # Use data directory if no path provided
        if db_path is None:
            data_dir = Path(__file__).parent.parent / "data"
            db_path = data_dir / "literature_index.db"

        with IndexStateTracker._lock:
            if IndexStateTracker._initialized:
                return

            self.db_path = Path(db_path)
            self.engine = None
            self.SessionLocal = None
            
            self._init_database()
            
            IndexStateTracker._initialized = True
            logger.info(f"✅ 索引状态跟踪器初始化完成: {db_path}")
    
    def _init_database(self):
        """初始化数据库 - 修复SQLite语法错误"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # 1. 索引构建记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS index_build_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    index_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    total_documents INTEGER DEFAULT 0,
                    new_documents INTEGER DEFAULT 0,
                    updated_documents INTEGER DEFAULT 0,
                    deleted_documents INTEGER DEFAULT 0,
                    structure_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    duration_seconds REAL DEFAULT 0.0,
                    version TEXT DEFAULT '2.0',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 2. 文档哈希表（用于检测变更）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS document_hashes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL UNIQUE,
                    source_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_hash TEXT NOT NULL,
                    last_indexed TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 3. 变更记录表（审计日志）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS change_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    old_hash TEXT,
                    new_hash TEXT,
                    change_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            ''')
            
            # 4. 索引统计表（定期快照）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS index_statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_documents INTEGER DEFAULT 0,
                    total_vectors INTEGER DEFAULT 0,
                    structure_count INTEGER DEFAULT 0,
                    literature_count INTEGER DEFAULT 0,
                    protein_count INTEGER DEFAULT 0,
                    avg_index_time REAL DEFAULT 0.0,
                    index_coverage REAL DEFAULT 0.0
                )
            ''')
            
            conn.commit()
            
            # 5. 创建索引（分开执行，避免SQLite语法错误）
            self._create_indexes(cursor)
            
            logger.info("✅ 索引状态数据库初始化完成")
            
        except Exception as e:
            logger.error(f"初始化数据库失败: {e}")
            raise
        finally:
            conn.close()
    
    def _create_indexes(self, cursor):
        """创建索引（单独执行）"""
        try:
            # 为document_hashes表创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_document_id ON document_hashes(document_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_source_id ON document_hashes(source_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_entity_type ON document_hashes(entity_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_indexed ON document_hashes(last_indexed)')
            
            # 为change_records表创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cr_document_id ON change_records(document_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cr_change_time ON change_records(change_time)')
            
        except Exception as e:
            logger.error(f"创建索引失败: {e}")
            raise
    
    def _get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)
    
    def start_build(self, index_type: IndexType = IndexType.FULL) -> int:
        """开始构建索引，返回记录ID"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO index_build_records 
                (index_type, status, start_time, version)
                VALUES (?, ?, ?, ?)
            ''', (index_type.value, IndexStatus.BUILDING.value, 
                  datetime.now().isoformat(), '2.0'))
            
            record_id = cursor.lastrowid
            conn.commit()
            
            logger.info(f"✅ 开始构建索引: {record_id} ({index_type.value})")
            return record_id
            
        except Exception as e:
            logger.error(f"开始构建索引失败: {e}")
            raise
        finally:
            conn.close()
    
    def complete_build(self, record_id: int, record: IndexBuildRecord) -> bool:
        """完成构建索引"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE index_build_records 
                SET status = ?, end_time = ?, 
                    total_documents = ?, new_documents = ?,
                    updated_documents = ?, deleted_documents = ?,
                    structure_count = ?, duration_seconds = ?
                WHERE id = ?
            ''', (
                record.status.value,
                datetime.now().isoformat(),
                record.total_documents,
                record.new_documents,
                record.updated_documents,
                record.deleted_documents,
                record.structure_count,
                record.duration_seconds,
                record_id
            ))
            
            conn.commit()
            logger.info(f"✅ 完成构建索引: {record_id} ({record.status.value})")
            return True
            
        except Exception as e:
            logger.error(f"完成构建索引失败: {e}")
            return False
        finally:
            conn.close()
    
    def update_document_hash(self, document_id: str, source_id: str, 
                           entity_type: str, content: str, metadata: Dict) -> bool:
        """更新文档哈希"""
        # 计算哈希
        content_hash = self._calculate_hash(content)
        metadata_hash = self._calculate_hash(json.dumps(metadata, sort_keys=True))
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # 检查是否存在
            cursor.execute(
                'SELECT content_hash FROM document_hashes WHERE document_id = ?',
                (document_id,)
            )
            existing = cursor.fetchone()
            
            if existing:
                old_hash = existing[0]
                # 如果哈希值不同，说明文档已更新
                if old_hash != content_hash:
                    # 更新哈希
                    cursor.execute('''
                        UPDATE document_hashes 
                        SET content_hash = ?, metadata_hash = ?, last_indexed = ?
                        WHERE document_id = ?
                    ''', (content_hash, metadata_hash, datetime.now().isoformat(), document_id))
                    
                    # 记录变更
                    self.record_change(DocumentChangeRecord(
                        document_id=document_id,
                        source_id=source_id,
                        entity_type=entity_type,
                        action='updated',
                        old_hash=old_hash,
                        new_hash=content_hash,
                        metadata={'source_id': source_id, 'entity_type': entity_type}
                    ))
                    logger.debug(f"文档已更新: {document_id}")
                    conn.commit()
                    return True
                else:
                    # 哈希相同，文档未变更
                    cursor.execute('''
                        UPDATE document_hashes 
                        SET last_indexed = ?
                        WHERE document_id = ?
                    ''', (datetime.now().isoformat(), document_id))
                    conn.commit()
                    return False
            else:
                # 新文档
                cursor.execute('''
                    INSERT INTO document_hashes 
                    (document_id, source_id, entity_type, content_hash, metadata_hash, last_indexed)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    document_id,
                    source_id,
                    entity_type,
                    content_hash,
                    metadata_hash,
                    datetime.now().isoformat()
                ))
                
                # 记录变更
                self.record_change(DocumentChangeRecord(
                    document_id=document_id,
                    source_id=source_id,
                    entity_type=entity_type,
                    action='added',
                    new_hash=content_hash,
                    metadata={'source_id': source_id, 'entity_type': entity_type}
                ))
                logger.debug(f"新文档添加: {document_id}")
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"更新文档哈希失败: {e}")
            return False
        finally:
            conn.close()
    
    def record_change(self, change: DocumentChangeRecord) -> bool:
        """记录文档变更"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            metadata_json = json.dumps(change.metadata, ensure_ascii=False)
            
            cursor.execute('''
                INSERT INTO change_records 
                (document_id, source_id, entity_type, action, 
                 old_hash, new_hash, change_time, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                change.document_id,
                change.source_id,
                change.entity_type,
                change.action,
                change.old_hash,
                change.new_hash,
                change.change_time.isoformat(),
                metadata_json
            ))
            
            conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"记录文档变更失败: {e}")
            return False
        finally:
            conn.close()
    
    def get_document_hash(self, document_id: str) -> Optional[Tuple[str, str]]:
        """获取文档哈希"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT content_hash, last_indexed FROM document_hashes WHERE document_id = ?',
                (document_id,)
            )
            result = cursor.fetchone()
            return result if result else None
        finally:
            conn.close()
    
    def get_unindexed_documents(self, since_days: int = 7) -> List[Dict[str, Any]]:
        """获取未索引的文档（最近N天内）"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            since_date = (datetime.now() - timedelta(days=since_days)).isoformat()
            
            cursor.execute('''
                SELECT document_id, source_id, entity_type, last_indexed
                FROM document_hashes 
                WHERE last_indexed IS NULL OR last_indexed < ?
                ORDER BY last_indexed ASC NULLS FIRST
                LIMIT 1000
            ''', (since_date,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'document_id': row[0],
                    'source_id': row[1],
                    'entity_type': row[2],
                    'last_indexed': row[3]
                })
            
            return results
            
        finally:
            conn.close()
    
    def get_recent_changes(self, hours: int = 24) -> List[Dict[str, Any]]:
        """获取最近的变更记录"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            since_time = (datetime.now() - timedelta(hours=hours)).isoformat()
            
            cursor.execute('''
                SELECT 
                    document_id, source_id, entity_type, action,
                    old_hash, new_hash, change_time
                FROM change_records
                WHERE change_time > ?
                ORDER BY change_time DESC
                LIMIT 100
            ''', (since_time,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'document_id': row[0],
                    'source_id': row[1],
                    'entity_type': row[2],
                    'action': row[3],
                    'old_hash': row[4],
                    'new_hash': row[5],
                    'change_time': row[6]
                })
            
            return results
            
        finally:
            conn.close()
    
    def get_build_history(self, limit: int = 10) -> List[IndexBuildRecord]:
        """获取构建历史"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    id, index_type, status, start_time, end_time,
                    total_documents, new_documents, updated_documents,
                    deleted_documents, structure_count, error_message,
                    duration_seconds, version
                FROM index_build_records
                ORDER BY start_time DESC
                LIMIT ?
            ''', (limit,))
            
            records = []
            for row in cursor.fetchall():
                record = IndexBuildRecord(
                    id=row[0],
                    index_type=IndexType(row[1]),
                    status=IndexStatus(row[2]),
                    start_time=datetime.fromisoformat(row[3]) if row[3] else None,
                    end_time=datetime.fromisoformat(row[4]) if row[4] else None,
                    total_documents=row[5],
                    new_documents=row[6],
                    updated_documents=row[7],
                    deleted_documents=row[8],
                    structure_count=row[9],
                    error_message=row[10],
                    duration_seconds=row[11],
                    version=row[12]
                )
                records.append(record)
            
            return records
            
        finally:
            conn.close()
    
    def get_index_statistics(self) -> Dict[str, Any]:
        """获取索引统计"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # 总文档数
            cursor.execute('SELECT COUNT(*) FROM document_hashes')
            total_docs = cursor.fetchone()[0]
            
            # 按实体类型统计
            cursor.execute('''
                SELECT entity_type, COUNT(*) as count
                FROM document_hashes
                GROUP BY entity_type
            ''')
            entity_stats = {row[0]: row[1] for row in cursor.fetchall()}
            
            # 最近索引的文档
            cursor.execute('''
                SELECT COUNT(*) 
                FROM document_hashes 
                WHERE last_indexed > ?
            ''', ((datetime.now() - timedelta(days=1)).isoformat(),))
            recent_indexed = cursor.fetchone()[0]
            
            # 构建统计
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_builds,
                    AVG(duration_seconds) as avg_duration,
                    MAX(end_time) as last_build
                FROM index_build_records
                WHERE status = 'completed'
            ''')
            build_stats = cursor.fetchone()
            
            return {
                'total_documents': total_docs,
                'entity_statistics': entity_stats,
                'recently_indexed': recent_indexed,
                'index_freshness': f"{recent_indexed}/{total_docs}" if total_docs > 0 else "N/A",
                'build_statistics': {
                    'total_builds': build_stats[0] or 0,
                    'avg_duration_seconds': round(build_stats[1], 2) if build_stats[1] else 0,
                    'last_build': build_stats[2] or None
                }
            }
            
        finally:
            conn.close()
    
    def cleanup_old_records(self, days: int = 30) -> int:
        """清理旧记录"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            
            # 清理变更记录
            cursor.execute('DELETE FROM change_records WHERE change_time < ?', (cutoff_date,))
            change_deleted = cursor.rowcount
            
            # 清理构建记录（保留最近100条）
            cursor.execute('''
                DELETE FROM index_build_records 
                WHERE id NOT IN (
                    SELECT id FROM index_build_records 
                    ORDER BY start_time DESC 
                    LIMIT 100
                ) AND start_time < ?
            ''', (cutoff_date,))
            build_deleted = cursor.rowcount
            
            conn.commit()
            
            logger.info(f"清理旧记录: {change_deleted} 条变更记录, {build_deleted} 条构建记录")
            return change_deleted + build_deleted
            
        finally:
            conn.close()
    
    def _calculate_hash(self, data: str) -> str:
        """计算哈希值"""
        return hashlib.sha256(data.encode('utf-8')).hexdigest()[:32]
    
    def get_index_coverage(self) -> Dict[str, Any]:
        """获取索引覆盖率（与数据库比较）"""
        try:
            from core.literature_db import create_literature_session, LiteratureEntry
            
            session = create_literature_session()
            total_literature = session.query(LiteratureEntry).count()
            session.close()
            
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(DISTINCT source_id) 
                FROM document_hashes 
                WHERE entity_type = 'literature'
            ''')
            indexed_literature = cursor.fetchone()[0]
            
            coverage = (indexed_literature / total_literature * 100) if total_literature > 0 else 0
            
            return {
                'total_literature': total_literature,
                'indexed_literature': indexed_literature,
                'coverage_percentage': round(coverage, 2),
                'missing_count': total_literature - indexed_literature,
                'status': 'complete' if coverage > 95 else 'partial' if coverage > 50 else 'low'
            }
            
        except Exception as e:
            logger.warning(f"获取索引覆盖率失败: {e}")
            return {'error': str(e)}

# ---------- 增量索引管理器 ----------
class IncrementalIndexManager:
    """增量索引管理器"""
    
    def __init__(self, tracker: IndexStateTracker = None):
        self.tracker = tracker or IndexStateTracker()
        logger.info("✅ 增量索引管理器初始化完成")
    
    def identify_changes(self, literature_data: List[Dict[str, Any]]) -> Dict[str, List[Dict]]:
        """识别变更的文献"""
        logger.info(f"识别文献变更: {len(literature_data)} 篇文献")
        
        added = []
        updated = []
        unchanged = []
        
        for lit_data in literature_data:
            lit_id = str(lit_data.get('id', ''))
            if not lit_id:
                continue
            
            # 生成文档ID（与统一索引器一致）
            doc_id = f"literature_{lit_id}"
            
            # 获取内容用于哈希计算
            content_parts = []
            title = lit_data.get('title', '')
            abstract = lit_data.get('abstract', '')
            authors = lit_data.get('authors', [])
            
            content_parts.append(title)
            content_parts.append(abstract)
            if isinstance(authors, list):
                content_parts.append(', '.join([str(a) for a in authors[:5]]))
            elif isinstance(authors, str):
                content_parts.append(authors)
            
            content = ' '.join(content_parts)
            metadata = {
                'year': lit_data.get('year'),
                'journal': lit_data.get('journal', ''),
                'doi': lit_data.get('doi', '')
            }
            
            # 检查文档状态
            existing_hash = self.tracker.get_document_hash(doc_id)
            
            if existing_hash is None:
                # 新文档
                added.append(lit_data)
                logger.debug(f"新文献: {lit_id}")
            else:
                # 检查是否更新
                content_hash = self.tracker._calculate_hash(content)
                if existing_hash[0] != content_hash:
                    updated.append(lit_data)
                    logger.debug(f"更新文献: {lit_id}")
                else:
                    unchanged.append(lit_data)
        
        logger.info(f"变更识别完成: {len(added)} 新增, {len(updated)} 更新, {len(unchanged)} 未变更")
        
        return {
            'added': added,
            'updated': updated,
            'unchanged': unchanged,
            'total_changed': len(added) + len(updated)
        }
    
    def build_incremental_index(self, rag_system, literature_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """构建增量索引"""
        start_time = time.time()
        record_id = None
        
        try:
            # 开始增量构建记录
            record_id = self.tracker.start_build(IndexType.INCREMENTAL)
            
            # 识别变更
            changes = self.identify_changes(literature_data)
            
            if changes['total_changed'] == 0:
                logger.info("没有变更的文献，跳过索引")
                
                record = IndexBuildRecord(
                    id=record_id,
                    index_type=IndexType.INCREMENTAL,
                    status=IndexStatus.COMPLETED,
                    start_time=datetime.fromtimestamp(start_time),
                    end_time=datetime.now(),
                    total_documents=0,
                    new_documents=0,
                    updated_documents=0,
                    deleted_documents=0,
                    structure_count=0,
                    duration_seconds=time.time() - start_time
                )
                
                self.tracker.complete_build(record_id, record)
                
                return {
                    'success': True,
                    'message': '没有需要索引的变更',
                    'changes': changes,
                    'duration_seconds': time.time() - start_time
                }
            
            # 只索引新增和更新的文献
            literature_to_index = changes['added'] + changes['updated']
            
            # 构建索引 - 这里需要确保 rag_system 有 index_literature 方法
            result = rag_system.index_literature(literature_to_index)
            
            # 更新文档哈希（标记为已索引）
            for lit_data in literature_to_index:
                lit_id = str(lit_data.get('id', ''))
                if not lit_id:
                    continue
                
                doc_id = f"literature_{lit_id}"
                
                # 生成内容用于哈希计算
                content_parts = []
                title = lit_data.get('title', '')
                abstract = lit_data.get('abstract', '')
                authors = lit_data.get('authors', [])
                
                content_parts.append(title)
                content_parts.append(abstract)
                if isinstance(authors, list):
                    content_parts.append(', '.join([str(a) for a in authors[:5]]))
                elif isinstance(authors, str):
                    content_parts.append(authors)
                
                content = ' '.join(content_parts)
                metadata = {
                    'year': lit_data.get('year'),
                    'journal': lit_data.get('journal', ''),
                    'doi': lit_data.get('doi', '')
                }
                
                self.tracker.update_document_hash(
                    document_id=doc_id,
                    source_id=lit_id,
                    entity_type='literature',
                    content=content,
                    metadata=metadata
                )
            
            # 获取索引统计
            stats = {}
            if hasattr(rag_system, 'vector_indexer') and rag_system.vector_indexer:
                stats = rag_system.vector_indexer.get_statistics()
            
            # 完成构建记录
            record = IndexBuildRecord(
                id=record_id,
                index_type=IndexType.INCREMENTAL,
                status=IndexStatus.COMPLETED if result else IndexStatus.FAILED,
                start_time=datetime.fromtimestamp(start_time),
                end_time=datetime.now(),
                total_documents=len(literature_to_index),
                new_documents=len(changes['added']),
                updated_documents=len(changes['updated']),
                deleted_documents=0,
                structure_count=stats.get('structure_mappings', {}).get('total_structures', 0),
                duration_seconds=time.time() - start_time
            )
            
            self.tracker.complete_build(record_id, record)
            
            return {
                'success': result,
                'changes': changes,
                'total_indexed': len(literature_to_index),
                'duration_seconds': time.time() - start_time,
                'record_id': record_id,
                'statistics': stats
            }
            
        except Exception as e:
            logger.error(f"增量索引构建失败: {e}")
            
            if record_id:
                record = IndexBuildRecord(
                    id=record_id,
                    index_type=IndexType.INCREMENTAL,
                    status=IndexStatus.FAILED,
                    start_time=datetime.fromtimestamp(start_time),
                    end_time=datetime.now(),
                    error_message=str(e),
                    duration_seconds=time.time() - start_time
                )
                self.tracker.complete_build(record_id, record)
            
            return {
                'success': False,
                'error': str(e),
                'duration_seconds': time.time() - start_time
            }
    
    def schedule_incremental_update(self, rag_system, check_interval_hours: int = 24) -> Dict[str, Any]:
        """调度增量更新（从数据库获取最新文献）"""
        try:
            from core.literature_db import create_literature_session, LiteratureEntry
            
            # 获取最后构建时间
            history = self.tracker.get_build_history(limit=1)
            last_build_time = history[0].end_time if history and history[0].end_time else datetime.min
            
            session = create_literature_session()
            
            # 查询新增和更新的文献（基于数据库时间戳）
            new_literature = session.query(LiteratureEntry).filter(
                LiteratureEntry.created_at > last_build_time
            ).all()
            
            updated_literature = session.query(LiteratureEntry).filter(
                LiteratureEntry.updated_at > last_build_time,
                LiteratureEntry.created_at <= last_build_time
            ).all()
            
            session.close()
            
            # 转换为字典格式
            literature_data = []
            for entry in new_literature + updated_literature:
                lit_data = {
                    'id': entry.id,
                    'title': entry.title,
                    'abstract': entry.abstract,
                    'authors': entry.authors,
                    'year': entry.year,
                    'journal': entry.journal,
                    'doi': entry.doi,
                    'cryoem_targets': entry.cryoem_targets
                }
                literature_data.append(lit_data)
            
            logger.info(f"发现 {len(literature_data)} 篇新增/更新的文献")
            
            if not literature_data:
                return {
                    'success': True,
                    'message': '没有新增或更新的文献',
                    'total_changed': 0
                }
            
            # 执行增量索引
            return self.build_incremental_index(rag_system, literature_data)
            
        except Exception as e:
            logger.error(f"调度增量更新失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_index_health(self) -> Dict[str, Any]:
        """获取索引健康状况"""
        try:
            stats = self.tracker.get_index_statistics()
            coverage = self.tracker.get_index_coverage()
            history = self.tracker.get_build_history(limit=5)
            
            # 评估健康状态
            total_docs = stats.get('total_documents', 0)
            recent_indexed = stats.get('recently_indexed', 0)
            coverage_pct = coverage.get('coverage_percentage', 0) if isinstance(coverage, dict) else 0
            
            health_status = 'healthy'
            if total_docs == 0:
                health_status = 'empty'
            elif recent_indexed == 0:
                health_status = 'stale'
            elif coverage_pct < 50:
                health_status = 'incomplete'
            elif coverage_pct < 90:
                health_status = 'partial'
            
            return {
                'status': health_status,
                'total_documents': total_docs,
                'recently_indexed': recent_indexed,
                'index_coverage': coverage,
                'statistics': stats,
                'recent_builds': [r.to_dict() for r in history],
                'recommendations': self._generate_recommendations(health_status, stats, coverage)
            }
            
        except Exception as e:
            logger.error(f"获取索引健康状况失败: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def _generate_recommendations(self, health_status: str, stats: Dict, coverage: Dict) -> List[str]:
        """生成建议"""
        recommendations = []
        
        if health_status == 'empty':
            recommendations.append("索引为空，建议执行全量构建")
        elif health_status == 'stale':
            recommendations.append("索引已过期，建议执行增量更新")
        elif health_status == 'incomplete':
            recommendations.append("索引覆盖率不足，建议执行全量构建")
        elif health_status == 'partial':
            recommendations.append("索引覆盖率较低，建议执行增量更新")
        
        # 基于统计数据的建议
        total_docs = stats.get('total_documents', 0)
        if total_docs > 10000:
            recommendations.append("文档数量较大，建议定期清理旧记录")
        
        avg_duration = stats.get('build_statistics', {}).get('avg_duration_seconds', 0)
        if avg_duration > 300:  # 超过5分钟
            recommendations.append("平均构建时间较长，建议优化索引策略")
        
        return recommendations

# ---------- 集成到现有系统 ----------
class EnhancedUnifiedRAGSystem:
    """增强的统一RAG系统（支持增量索引）"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        # 延迟导入，避免循环依赖
        self.rag_system = None
        self.index_tracker = IndexStateTracker()
        self.incremental_manager = IncrementalIndexManager(self.index_tracker)
        
        logger.info("✅ 增强RAG系统初始化完成（支持增量索引）")
    
    def _ensure_rag_system(self):
        """确保RAG系统已初始化"""
        if self.rag_system is None:
            from literature_index import UnifiedRAGSystem
            self.rag_system = UnifiedRAGSystem(self.config)
    
    def index_literature(self, literature_data: List[Dict[str, Any]], 
                        incremental: bool = True) -> Dict[str, Any]:
        """索引文献（支持增量）"""
        self._ensure_rag_system()
        
        if incremental:
            logger.info(f"执行增量索引: {len(literature_data)} 篇文献")
            return self.incremental_manager.build_incremental_index(self.rag_system, literature_data)
        else:
            logger.info(f"执行全量索引: {len(literature_data)} 篇文献")
            # 全量索引前清理跟踪记录
            self.index_tracker.cleanup_old_records(days=0)  # 清理所有旧记录
            
            start_time = time.time()
            record_id = self.index_tracker.start_build(IndexType.FULL)
            
            try:
                result = self.rag_system.index_literature(literature_data)
                
                # 更新文档哈希
                for lit_data in literature_data:
                    lit_id = str(lit_data.get('id', ''))
                    if not lit_id:
                        continue
                    
                    doc_id = f"literature_{lit_id}"
                    
                    # 生成内容用于哈希计算
                    content_parts = []
                    title = lit_data.get('title', '')
                    abstract = lit_data.get('abstract', '')
                    authors = lit_data.get('authors', [])
                    
                    content_parts.append(title)
                    content_parts.append(abstract)
                    if isinstance(authors, list):
                        content_parts.append(', '.join([str(a) for a in authors[:5]]))
                    elif isinstance(authors, str):
                        content_parts.append(authors)
                    
                    content = ' '.join(content_parts)
                    metadata = {
                        'year': lit_data.get('year'),
                        'journal': lit_data.get('journal', ''),
                        'doi': lit_data.get('doi', '')
                    }
                    
                    self.index_tracker.update_document_hash(
                        document_id=doc_id,
                        source_id=lit_id,
                        entity_type='literature',
                        content=content,
                        metadata=metadata
                    )
                
                # 获取统计信息
                stats = {}
                if hasattr(self.rag_system, 'vector_indexer') and self.rag_system.vector_indexer:
                    stats = self.rag_system.vector_indexer.get_statistics()
                
                # 完成构建记录
                record = IndexBuildRecord(
                    id=record_id,
                    index_type=IndexType.FULL,
                    status=IndexStatus.COMPLETED if result else IndexStatus.FAILED,
                    start_time=datetime.fromtimestamp(start_time),
                    end_time=datetime.now(),
                    total_documents=len(literature_data),
                    new_documents=len(literature_data),  # 全量构建都是新文档
                    updated_documents=0,
                    deleted_documents=0,
                    structure_count=stats.get('structure_mappings', {}).get('total_structures', 0),
                    duration_seconds=time.time() - start_time
                )
                
                self.index_tracker.complete_build(record_id, record)
                
                return {
                    'success': result,
                    'index_type': 'full',
                    'total_indexed': len(literature_data),
                    'duration_seconds': time.time() - start_time,
                    'record_id': record_id,
                    'statistics': stats
                }
                
            except Exception as e:
                logger.error(f"全量索引失败: {e}")
                
                record = IndexBuildRecord(
                    id=record_id,
                    index_type=IndexType.FULL,
                    status=IndexStatus.FAILED,
                    start_time=datetime.fromtimestamp(start_time),
                    end_time=datetime.now(),
                    error_message=str(e),
                    duration_seconds=time.time() - start_time
                )
                self.index_tracker.complete_build(record_id, record)
                
                return {
                    'success': False,
                    'error': str(e),
                    'duration_seconds': time.time() - start_time
                }
    
    def retrieve(self, *args, **kwargs):
        """检索（透传给原系统）"""
        self._ensure_rag_system()
        return self.rag_system.retrieve(*args, **kwargs)
    
    def schedule_update(self, interval_hours: int = 24):
        """调度增量更新"""
        self._ensure_rag_system()
        return self.incremental_manager.schedule_incremental_update(self.rag_system, interval_hours)
    
    def get_index_health(self):
        """获取索引健康状态"""
        return self.incremental_manager.get_index_health()
    
    def get_build_history(self, limit: int = 10):
        """获取构建历史"""
        return self.index_tracker.get_build_history(limit)
    
    def cleanup(self, days: int = 30):
        """清理旧记录"""
        return self.index_tracker.cleanup_old_records(days)
    
    def get_system_statistics(self):
        """获取系统统计（向后兼容）"""
        self._ensure_rag_system()
        return self.rag_system.get_system_statistics()
    
    def search_by_structure(self, *args, **kwargs):
        """根据结构ID搜索文献（向后兼容）"""
        self._ensure_rag_system()
        return self.rag_system.search_by_structure(*args, **kwargs)
    
    def get_literature_with_structures(self, *args, **kwargs):
        """获取文献及其结构信息（向后兼容）"""
        self._ensure_rag_system()
        return self.rag_system.get_literature_with_structures(*args, **kwargs)

# ---------- 简化的增量索引API ----------
class SimpleIncrementalIndexer:
    """简化的增量索引器（用于快速集成）"""
    
    @staticmethod
    def enable_incremental_indexing(rag_system) -> 'EnhancedUnifiedRAGSystem':
        """为现有RAG系统启用增量索引"""
        return EnhancedUnifiedRAGSystem()
    
    @staticmethod
    def check_for_updates(rag_system, literature_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """检查更新"""
        tracker = IndexStateTracker()
        manager = IncrementalIndexManager(tracker)
        changes = manager.identify_changes(literature_data)
        
        return {
            'has_changes': changes['total_changed'] > 0,
            'changes': changes,
            'recommendation': 'incremental' if changes['total_changed'] < len(literature_data) / 2 else 'full'
        }

# ---------- 测试函数 ----------
def test_incremental_index():
    """测试增量索引"""
    print("=== 测试增量索引系统 ===\n")
    
    try:
        # 初始化系统
        system = EnhancedUnifiedRAGSystem()
        
        # 测试数据
        test_literature = [
            {
                'id': '1001',
                'title': '测试文献1',
                'abstract': '这是测试文献的摘要内容',
                'authors': ['作者1', '作者2'],
                'year': 2024,
                'journal': '测试期刊'
            },
            {
                'id': '1002',
                'title': '测试文献2',
                'abstract': '另一个测试文献的摘要',
                'authors': ['作者3'],
                'year': 2024,
                'journal': '测试期刊'
            }
        ]
        
        # 第一次索引（全量）
        print("1. 第一次全量索引:")
        result1 = system.index_literature(test_literature, incremental=False)
        print(f"   结果: {result1.get('success', False)}, 耗时: {result1.get('duration_seconds', 0):.2f}s")
        
        # 第二次索引（增量，相同数据）
        print("\n2. 第二次增量索引（相同数据）:")
        result2 = system.index_literature(test_literature, incremental=True)
        print(f"   结果: {result2.get('success', False)}")
        print(f"   变更: {result2.get('changes', {}).get('total_changed', 0)} 个变更")
        
        # 第三次索引（增量，新数据）
        print("\n3. 第三次增量索引（新增数据）:")
        new_literature = [
            {
                'id': '1003',
                'title': '新测试文献',
                'abstract': '新增文献的摘要内容',
                'authors': ['作者4'],
                'year': 2024,
                'journal': '新期刊'
            }
        ]
        result3 = system.index_literature(new_literature, incremental=True)
        print(f"   结果: {result3.get('success', False)}")
        print(f"   新增文档: {result3.get('changes', {}).get('added', [])}")
        
        # 获取健康状态
        print("\n4. 索引健康状态:")
        health = system.get_index_health()
        print(f"   状态: {health.get('status', 'unknown')}")
        print(f"   总文档数: {health.get('total_documents', 0)}")
        
        # 获取构建历史
        print("\n5. 构建历史:")
        history = system.get_build_history()
        for record in history:
            print(f"   ID:{record.id} {record.index_type.value} - {record.status.value} "
                  f"({record.duration_seconds:.2f}s)")
        
        # 测试检索功能
        print("\n6. 测试检索功能:")
        search_result = system.retrieve("测试文献", top_k=2)
        print(f"   检索到 {len(search_result.get('retrieved_documents', []))} 个结果")
        
        print("\n✅ 增量索引测试完成")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()

def quick_test():
    """快速测试数据库初始化"""
    print("=== 快速测试数据库初始化 ===\n")
    
    try:
        # 测试数据库初始化
        tracker = IndexStateTracker("test_index.db")
        print("✅ 数据库初始化成功")
        
        # 测试开始构建
        record_id = tracker.start_build(IndexType.FULL)
        print(f"✅ 开始构建记录: {record_id}")
        
        # 测试完成构建
        record = IndexBuildRecord(
            id=record_id,
            index_type=IndexType.FULL,
            status=IndexStatus.COMPLETED,
            start_time=datetime.now(),
            end_time=datetime.now(),
            total_documents=100,
            new_documents=100,
            duration_seconds=10.5
        )
        tracker.complete_build(record_id, record)
        print("✅ 完成构建记录")
        
        # 测试更新文档哈希
        tracker.update_document_hash(
            document_id="test_doc_1",
            source_id="1001",
            entity_type="literature",
            content="测试内容",
            metadata={"year": 2024}
        )
        print("✅ 更新文档哈希")
        
        # 测试获取统计
        stats = tracker.get_index_statistics()
        print(f"✅ 获取统计: {stats.get('total_documents', 0)} 个文档")
        
        # 清理测试文件
        import os
        if os.path.exists("test_index.db"):
            os.remove("test_index.db")
            print("✅ 清理测试文件")
        
        print("\n✅ 所有测试通过！")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # 先运行快速测试
    quick_test()
    
    # 如果需要完整测试，可以取消下面的注释
    # test_incremental_index()