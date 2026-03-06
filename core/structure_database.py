# structure_database.py - 结构离线数据库模块（最小修改版）
import os, json, logging, time, re, sqlite3, hashlib, threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from datetime import datetime
from dataclasses import asdict, dataclass, field
from enum import Enum
from core.simple_singleton import SimpleSingleton
import time
from functools import lru_cache

import numpy as np
from collections import defaultdict

# 首先设置logger
logger = logging.getLogger(__name__)

try:
    from core.structure_manager import StructureMetadataFetcher
    HAS_STRUCTURE_MANAGER = True
except ImportError as e:
    HAS_STRUCTURE_MANAGER = False
    logger.warning(f"无法导入结构管理器: {e}")

# 然后尝试导入统一向量化系统
try:
    from core.literature_index import (
        UnifiedVectorIndexer,
        UnifiedDocumentGenerator,
        EnhancedDatabaseConnector,
        get_unified_vector_indexer  # 新增导入
    )
    HAS_UNIFIED_VECTOR = True
except ImportError as e:
    HAS_UNIFIED_VECTOR = False
    logger.warning(f"无法导入统一向量化系统: {e}")

# 尝试导入UniProt模块
try:
    from core.uniprot_client import (
        UniProtAPIClient, UniProtNormalizer, UniProtEntry, ProteinTarget,
        get_uniprot_client, get_uniprot_normalizer
    )
    HAS_UNIPROT = True
except ImportError as e:
    HAS_UNIPROT = False
    logger.warning(f"无法导入UniProt模块: {e}")

# ---------- 数据模型 ----------
class StructureType(Enum):
    PDB = "pdb"
    EMDB = "emdb"
    ALPHAFOLD = "alphafold"

@dataclass
class StructureEntry:
    """结构数据库条目"""
    id: str
    type: StructureType
    title: str
    resolution: Optional[float] = None
    method: Optional[str] = None
    deposition_date: Optional[str] = None
    release_date: Optional[str] = None
    organism: Optional[str] = None
    expression_system: Optional[str] = None
    expression_system_strain: Optional[str] = None
    gene: Optional[str] = None
    protein_name: Optional[str] = None
    authors: Optional[List[Dict]] = None
    citation_count: Optional[int] = None
    related_ids: List[str] = field(default_factory=list)  # 相关结构ID
    metadata_json: Optional[str] = None  # 原始元数据JSON
    last_updated: Optional[str] = None
    created_at: Optional[str] = None

@dataclass
class LiteratureStructureMapping:
    """文献-结构映射关系"""
    literature_id: int
    structure_id: str
    structure_type: StructureType
    context: Optional[str] = None  # 在文献中出现的上下文
    page_number: Optional[int] = None
    confidence: float = 1.0
    created_at: Optional[str] = None

@dataclass
class ProteinStructure:
    """蛋白质-结构映射"""
    protein_name: str
    uniprot_id: Optional[str] = None
    gene_name: Optional[str] = None
    pdb_ids: List[str] = field(default_factory=list)
    emdb_ids: List[str] = field(default_factory=list)
    preferred_structure_id: Optional[str] = None
    last_updated: Optional[str] = None

# ---------- 蛋白质名称映射器 ----------
class ProteinNameMapper:
    """蛋白质名称映射器，使用UniProt元数据"""
    
    def __init__(self, uniprot_client=None):
        self.uniprot_client = uniprot_client
        self.protein_name_map = {}  # 蛋白质名称 -> [UniProt ID]
        self.gene_name_map = {}     # 基因名 -> [UniProt ID]
        self.uniprot_structure_map = {}  # UniProt ID -> [结构ID]
        
    def build_mapping_from_structures(self, structures_data):
        """从结构数据构建蛋白质映射"""
        for struct_id, struct_info in structures_data.items():
            if 'uniprot_ids' in struct_info:
                uniprot_ids = struct_info['uniprot_ids']
                protein_name = struct_info.get('protein_name', '')
                gene_name = struct_info.get('gene_name', '')
                
                for uniprot_id in uniprot_ids:
                    # 更新UniProt到结构的映射
                    if uniprot_id not in self.uniprot_structure_map:
                        self.uniprot_structure_map[uniprot_id] = []
                    self.uniprot_structure_map[uniprot_id].append(struct_id)
                
                # 更新蛋白质名称映射
                if protein_name and protein_name != 'Unknown':
                    if protein_name not in self.protein_name_map:
                        self.protein_name_map[protein_name] = []
                    self.protein_name_map[protein_name].extend(uniprot_ids)
                
                # 更新基因名映射
                if gene_name and gene_name != 'Unknown':
                    if gene_name not in self.gene_name_map:
                        self.gene_name_map[gene_name] = []
                    self.gene_name_map[gene_name].extend(uniprot_ids)
        
        # 去重
        for name_map in [self.protein_name_map, self.gene_name_map]:
            for key, values in name_map.items():
                name_map[key] = list(set(values))
    
    def find_structures_by_protein_name(self, protein_name: str) -> List[str]:
        """通过蛋白质名称查找相关结构"""
        all_structure_ids = set()
        
        # 1. 通过蛋白质名称直接查找
        if protein_name in self.protein_name_map:
            for uniprot_id in self.protein_name_map[protein_name]:
                if uniprot_id in self.uniprot_structure_map:
                    all_structure_ids.update(self.uniprot_structure_map[uniprot_id])
        
        # 2. 通过基因名查找
        if protein_name in self.gene_name_map:
            for uniprot_id in self.gene_name_map[protein_name]:
                if uniprot_id in self.uniprot_structure_map:
                    all_structure_ids.update(self.uniprot_structure_map[uniprot_id])
        
        # 3. 模糊匹配（包含关系）
        for protein_key, uniprot_ids in self.protein_name_map.items():
            if protein_name in protein_key or protein_key in protein_name:
                for uniprot_id in uniprot_ids:
                    if uniprot_id in self.uniprot_structure_map:
                        all_structure_ids.update(self.uniprot_structure_map[uniprot_id])
        
        return list(all_structure_ids)
    
    def get_uniprot_ids_for_protein_name(self, protein_name: str) -> List[str]:
        """获取蛋白质名称对应的UniProt ID列表"""
        return self.protein_name_map.get(protein_name, [])
    
    def get_uniprot_ids_for_gene_name(self, gene_name: str) -> List[str]:
        """获取基因名对应的UniProt ID列表"""
        return self.gene_name_map.get(gene_name, [])
    
    def get_structures_for_uniprot_id(self, uniprot_id: str) -> List[str]:
        """获取UniProt ID对应的结构ID列表"""
        return self.uniprot_structure_map.get(uniprot_id, [])
    
    def save_mapping_to_file(self, filepath: str):
        """保存映射到文件"""
        mapping_data = {
            'protein_name_map': self.protein_name_map,
            'gene_name_map': self.gene_name_map,
            'uniprot_structure_map': self.uniprot_structure_map
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(mapping_data, f, ensure_ascii=False, indent=2)
    
    def load_mapping_from_file(self, filepath: str):
        """从文件加载映射"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                mapping_data = json.load(f)
            
            self.protein_name_map = mapping_data.get('protein_name_map', {})
            self.gene_name_map = mapping_data.get('gene_name_map', {})
            self.uniprot_structure_map = mapping_data.get('uniprot_structure_map', {})
            return True
        except Exception as e:
            logger.error(f"加载蛋白质映射失败: {e}")
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取映射统计信息"""
        return {
            'total_protein_names': len(self.protein_name_map),
            'total_gene_names': len(self.gene_name_map),
            'total_uniprot_ids': len(self.uniprot_structure_map),
            'total_structure_links': sum(len(v) for v in self.uniprot_structure_map.values()),
            'avg_structures_per_uniprot': sum(len(v) for v in self.uniprot_structure_map.values()) / max(len(self.uniprot_structure_map), 1),
            'most_common_proteins': sorted(
                [(k, len(v)) for k, v in self.protein_name_map.items()],
                key=lambda x: x[1], reverse=True
            )[:10]
        }

    def get_entities_for_uniprot_id(self, uniprot_id: str) -> List[Dict]:
        """
        获取UniProt ID对应的所有实体（通过数据库查询）
        """
        try:
            # 这里可以使用数据库查询
            # 这是一个示例实现，实际实现可能需要根据具体数据库结构调整
            # 假设我们有一个数据库实例
            if hasattr(self, '_db_instance'):
                return self._db_instance.find_entities_for_uniprot(uniprot_id)
            else:
                logger.warning("数据库实例未初始化")
                return []
        except Exception as e:
            logger.error(f"获取UniProt实体失败 {uniprot_id}: {e}")
            return []

    def get_uniprot_for_entity(self, pdb_id: str, entity_id: str) -> List[Dict]:
        """
        获取实体对应的UniProt ID（通过数据库查询）
        """
        try:
            if hasattr(self, '_db_instance'):
                return self._db_instance.find_uniprot_for_entity(pdb_id, entity_id)
            else:
                logger.warning("数据库实例未初始化")
                return []
        except Exception as e:
            logger.error(f"获取实体UniProt失败 {pdb_id} 实体 {entity_id}: {e}")
            return []

# ---------- 离线数据库管理器 ----------
class StructureOfflineDatabase:
    """结构离线数据库管理器（简化版）"""

    def __init__(self, db_path: str = None, cache_dir: str = "structure_cache"):
        """简化版构造函数"""
        # Use data directory path as default
        if db_path is None:
            import os
            current_dir = os.path.dirname(os.path.abspath(__file__))  # structure_database.py location
            # Go up to flask_app, then use data directory
            data_dir = os.path.join(os.path.dirname(current_dir), 'data')
            db_path = os.path.join(data_dir, 'structure_offline.db')

        # 检查是否已经初始化
        if hasattr(self, '_initialized') and self._initialized:
            return

        print(f"🔄 正在初始化 StructureOfflineDatabase: {db_path}")

        self.db_path = Path(db_path)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

        self._initialized = False

        # 初始化锁和缓存
        self._lock = threading.RLock()

        # 初始化蛋白质映射器
        self.protein_mapper = ProteinNameMapper()

        # 跳过向量化索引器初始化
        self.unified_vector_indexer = None

        # 初始化数据库
        self._init_database_simple()

        self._initialized = True
        print(f"✅ StructureOfflineDatabase 初始化完成: {self.db_path}")

    def _init_database_simple(self):
        """简化版数据库初始化"""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")

            # 创建基本表
            cursor = self.conn.cursor()

            # structures 表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS structures (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT,
                resolution REAL,
                method TEXT,
                deposition_date TEXT,
                release_date TEXT,
                organism TEXT,
                expression_system TEXT,
                expression_system_strain TEXT,
                gene TEXT,
                protein_name TEXT,
                authors TEXT,
                citation_count INTEGER,
                related_ids TEXT,
                uniprot_ids TEXT,
                molecular_weight REAL,
                polymer_count INTEGER,
                group_ids TEXT,
                metadata_json TEXT,
                last_updated TEXT,
                created_at TEXT
            )
            ''')

            # literature_structure_mapping 表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS literature_structure_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                literature_id INTEGER NOT NULL,
                structure_id TEXT NOT NULL,
                structure_type TEXT NOT NULL,
                context TEXT,
                page_number INTEGER,
                confidence REAL DEFAULT 1.0,
                created_at TEXT,
                FOREIGN KEY (structure_id) REFERENCES structures(id)
            )
            ''')

            self.conn.commit()
            print("✅ 数据库表创建完成")

        except Exception as e:
            print(f"❌ 数据库初始化失败: {e}")
            raise

    def ensure_structure_entities_table(self):
        """确保structure_entities表有正确的schema"""
        try:
            cursor = self.conn.cursor()
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='structure_entities'")
            if not cursor.fetchone():
                # 创建新表
                self._create_structure_entities_table()
            else:
                # 添加缺失的字段
                cursor.execute("PRAGMA table_info(structure_entities)")
                existing_columns = {row[1] for row in cursor.fetchall()}
                
                columns_to_add = [
                    ('description', 'TEXT'),
                    ('chain_ids', 'TEXT'),
                    ('asym_ids', 'TEXT'),
                    ('uniprot_ids', 'TEXT'),
                    ('uniprot_ranges', 'TEXT')
                ]
                
                for column_name, column_type in columns_to_add:
                    if column_name not in existing_columns:
                        logger.info(f"添加缺失的字段: {column_name} {column_type}")
                        cursor.execute(f'ALTER TABLE structure_entities ADD COLUMN {column_name} {column_type}')
            
            self.conn.commit()
            logger.info("✅ 确保structure_entities表schema正确")
            
        except Exception as e:
            logger.error(f"确保structure_entities表失败: {e}")
            self.conn.rollback()

    def get_uniprot_for_entity(self, pdb_id: str, entity_id: str) -> List[Dict]:
        """
        获取实体对应的UniProt ID
        
        参数:
            pdb_id: PDB ID
            entity_id: 实体ID
        
        返回:
            UniProt-实体映射列表
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM uniprot_entity_mappings
                WHERE pdb_id = ? AND entity_id = ?
                ORDER BY match_score DESC
            ''', (pdb_id, entity_id))
            
            rows = cursor.fetchall()
            mappings = []
            for row in rows:
                mappings.append(dict(row))
            
            conn.close()
            return mappings
            
        except Exception as e:
            logger.error(f"获取实体UniProt失败 {pdb_id} 实体 {entity_id}: {e}")
            return []

    def get_uniprot_entries_for_pdb(self, pdb_id: str, uniprot_id: str = None) -> List[Dict]:
        """
        获取PDB对应的UniProt条目
        
        参数:
            pdb_id: PDB ID
            uniprot_id: 可选的UniProt ID（如果指定，则只返回该UniProt条目）
        
        返回:
            UniProt条目列表
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if uniprot_id:
                cursor.execute('''
                    SELECT * FROM uniprot_entries
                    WHERE uniprot_id = ? AND pdb_ids LIKE ?
                ''', (uniprot_id, f'%{pdb_id}%'))
            else:
                cursor.execute('''
                    SELECT * FROM uniprot_entries
                    WHERE pdb_ids LIKE ?
                ''', (f'%{pdb_id}%',))
            
            rows = cursor.fetchall()
            entries = []
            for row in rows:
                entries.append(dict(row))
            
            conn.close()
            return entries
            
        except Exception as e:
            logger.error(f"获取PDB的UniProt条目失败 {pdb_id}: {e}")
            return []

    def _check_schema_upgraded(self):
        """检查数据库结构是否已经升级到版本3"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 检查是否有 schema_version 表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
            if not cursor.fetchone():
                conn.close()
                return False
            
            # 检查版本 - 需要版本3
            cursor.execute("SELECT version FROM schema_version ORDER BY updated_at DESC LIMIT 1")
            row = cursor.fetchone()
            conn.close()
            
            if row and row[0] >= 3:  # 升级到版本3
                return True
            
            return False
            
        except:
            return False

    def _mark_schema_upgraded(self):
        """标记数据库结构已升级"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 创建 schema_version 表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS schema_version (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL,
                description TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # 插入当前版本
            cursor.execute('INSERT INTO schema_version (version, description) VALUES (?, ?)', 
                        (2, '重构版：移除metadata_json，添加entities表'))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.warning(f"标记schema版本失败: {e}")
    
    def _init_unified_vector_indexer(self):
        """初始化统一向量索引器（跳过，改为惰性加载）"""
        # 跳过立即初始化，改为使用时再加载
        self.unified_vector_indexer = None
        logger.info("ℹ️ 统一向量索引器将采用惰性加载")
    
    def _init_database_refactored(self):
        """初始化数据库表结构（重构版）"""
        with self._lock:
            try:
                # 【关键修复】使用 self.conn 而不是创建新的连接
                if not hasattr(self, 'conn') or not self.conn:
                    self.db_path.parent.mkdir(parents=True, exist_ok=True)
                    self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                    self.conn.row_factory = sqlite3.Row
                    self.conn.execute("PRAGMA foreign_keys = ON")
                cursor = self.conn.cursor()            
                # 1. 主表：structures（移除metadata_json字段）
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS structures (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT,
                    resolution REAL,
                    method TEXT,
                    deposition_date TEXT,
                    release_date TEXT,
                    organism TEXT,
                    expression_system TEXT,
                    expression_system_strain TEXT,
                    gene TEXT,
                    protein_name TEXT,
                    authors TEXT,  -- 存储JSON字符串
                    citation_count INTEGER,
                    related_ids TEXT,  -- 存储JSON字符串
                    uniprot_ids TEXT,  -- 新增：存储JSON字符串
                    molecular_weight REAL,  -- 新增
                    polymer_count INTEGER,  -- 新增
                    group_ids TEXT,  -- 新增：存储JSON字符串
                    last_updated TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                ''')
                
                # 2. 实体表：structure_entities（新增）
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS structure_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    structure_id TEXT NOT NULL,
                    entity_id TEXT,
                    molecule_type TEXT,
                    molecule_name TEXT,
                    description TEXT,
                    chain_ids TEXT,
                    asym_ids TEXT,
                    in_chains TEXT,
                    sequence TEXT,
                    length INTEGER,
                    weight REAL,
                    number_of_copies INTEGER,
                    source_organism TEXT,
                    expression_host TEXT,
                    taxon_id TEXT,
                    gene_names TEXT,
                    uniprot_ids TEXT,
                    start_residue INTEGER,
                    end_residue INTEGER,
                    uniprot_ranges TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (structure_id) REFERENCES structures (id)
                );
                ''')
                
                # 3. UniProt-结构映射表（修复和增强）
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS uniprot_structure_mapping (
                    uniprot_id TEXT NOT NULL,
                    structure_id TEXT NOT NULL,
                    protein_name TEXT,
                    gene_name TEXT,
                    confidence REAL DEFAULT 1.0,
                    source TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (uniprot_id, structure_id)
                )
                ''')
                
                # 4. 结构关系表
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS structure_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relationship_type TEXT NOT NULL,
                    evidence TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_id, target_id, relationship_type) ON CONFLICT REPLACE
                )
                ''')
                
                # 5. 结构分组表
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS structure_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    structure_id TEXT NOT NULL,
                    group_data TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                ''')
                
                # 6. 文献-结构映射表
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS literature_structure_mapping (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    literature_id INTEGER NOT NULL,
                    structure_id TEXT NOT NULL,
                    structure_type TEXT NOT NULL,
                    context TEXT,
                    page_number INTEGER,
                    confidence REAL DEFAULT 1.0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (structure_id) REFERENCES structures(id),
                    UNIQUE(literature_id, structure_id)
                )
                ''')
                
                # 7. 搜索历史表
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    search_type TEXT,
                    results_count INTEGER,
                    response_time REAL,
                    success BOOLEAN,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                ''')
                
                # 8. 蛋白质-结构映射表
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS protein_structure_mapping (
                    protein_name TEXT PRIMARY KEY,
                    uniprot_id TEXT,
                    gene_name TEXT,
                    pdb_ids TEXT,
                    emdb_ids TEXT,
                    preferred_structure_id TEXT,
                    last_updated TEXT DEFAULT CURRENT_TIMESTAMP
                )
                ''')

                # 9. UniProt-实体映射表（新增）
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS uniprot_entity_mappings (
                    id TEXT PRIMARY KEY,
                    uniprot_id TEXT NOT NULL,
                    pdb_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    match_score REAL DEFAULT 0.0,
                    match_evidence TEXT,
                    entity_info TEXT,
                    uniprot_info TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    source TEXT,
                    FOREIGN KEY (uniprot_id) REFERENCES uniprot_structure_mapping(uniprot_id),
                    FOREIGN KEY (pdb_id) REFERENCES structures(id),
                    UNIQUE(uniprot_id, pdb_id, entity_id)
                )
                ''')

        # 添加字段迁移
                self._ensure_structure_entities_columns()
                self._add_uniprot_ids_to_entities_table()

                # ==================== 索引策略 ====================
                
                # structures 表索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_type ON structures(type)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_organism ON structures(organism)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_gene ON structures(gene)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_protein ON structures(protein_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_resolution ON structures(resolution)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_method ON structures(method)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_deposition_date ON structures(deposition_date)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_release_date ON structures(release_date)')
                
                # structure_entities 表索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_entity_structure ON structure_entities(structure_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_entity_type ON structure_entities(molecule_type)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_entity_organism ON structure_entities(source_organism)')
                
                # uniprot_structure_mapping 表索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_uniprot_id ON uniprot_structure_mapping(uniprot_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_uniprot_structure ON uniprot_structure_mapping(structure_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_uniprot_confidence ON uniprot_structure_mapping(confidence)')
                
                # structure_relationships 表索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_relationship_source ON structure_relationships(source_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_relationship_target ON structure_relationships(target_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_relationship_type ON structure_relationships(relationship_type)')
                
                # structure_groups 表索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_group_id ON structure_groups(group_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_group_structure ON structure_groups(structure_id)')
                
                # literature_structure_mapping 表索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_lit_map_literature ON literature_structure_mapping(literature_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_lit_map_structure ON literature_structure_mapping(structure_id)')
                
                # search_history 表索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_search_query ON search_history(query)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_search_created ON search_history(created_at)')
                
                # protein_structure_mapping 表索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_protein_name ON protein_structure_mapping(protein_name)')

                # UniProt-实体映射表索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_uniprot_entity_uniprot ON uniprot_entity_mappings(uniprot_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_uniprot_entity_pdb ON uniprot_entity_mappings(pdb_id, entity_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_uniprot_entity_score ON uniprot_entity_mappings(match_score)')

                self.conn.commit()
                
                logger.info("✅ 重构版数据库表结构和索引初始化完成")
                
            except Exception as e:
                logger.error(f"数据库初始化失败: {e}")
                if hasattr(self, 'conn') and self.conn:
                    self.conn.rollback()
                raise

    def _ensure_structure_entities_columns(self):
        """确保structure_entities表有所有必要的字段"""
        try:
            if not self.conn:
                logger.error("数据库连接不存在")
                return
                
            cursor = self.conn.cursor()
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='structure_entities'")
            if not cursor.fetchone():
                logger.error("structure_entities表不存在")
                return
            
            # 获取现有字段
            cursor.execute("PRAGMA table_info(structure_entities)")
            existing_columns = {row[1] for row in cursor.fetchall()}
            logger.info(f"现有字段: {existing_columns}")
            
            # 需要添加的字段列表
            columns_to_add = [
                ('description', 'TEXT'),
                ('chain_ids', 'TEXT'),
                ('asym_ids', 'TEXT'),
                ('uniprot_ids', 'TEXT'),
                ('uniprot_ranges', 'TEXT'),
                ('molecule_name', 'TEXT'),
                ('gene_names', 'TEXT'),
                ('source_organism', 'TEXT'),
                ('expression_host', 'TEXT'),
                ('taxon_id', 'TEXT'),
                ('start_residue', 'INTEGER'),
                ('end_residue', 'INTEGER'),
            ]
            
            for column_name, column_type in columns_to_add:
                if column_name not in existing_columns:
                    logger.info(f"添加缺失的字段: {column_name} {column_type}")
                    try:
                        cursor.execute(f'ALTER TABLE structure_entities ADD COLUMN {column_name} {column_type}')
                        logger.info(f"✅ 添加字段 {column_name} 成功")
                    except Exception as e:
                        logger.error(f"添加字段 {column_name} 失败: {e}")
            
            # 重新检查所有字段
            cursor.execute("PRAGMA table_info(structure_entities)")
            final_columns = {row[1] for row in cursor.fetchall()}
            logger.info(f"最终字段: {final_columns}")
            
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"确保structure_entities表字段失败: {e}")
            if self.conn:
                self.conn.rollback()

    def _add_uniprot_ids_to_entities_table(self):
        """为现有entities表添加uniprot_ids字段"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 检查字段是否存在
            cursor.execute("PRAGMA table_info(structure_entities)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'uniprot_ids' not in columns:
                logger.info("为structure_entities表添加uniprot_ids字段...")
                cursor.execute("ALTER TABLE structure_entities ADD COLUMN uniprot_ids TEXT")
                conn.commit()
                logger.info("✅ uniprot_ids字段添加成功")
            else:
                logger.info("uniprot_ids字段已存在")
            
            conn.close()
            
        except Exception as e:
            logger.error(f"添加uniprot_ids字段失败: {e}")
            if 'conn' in locals():
                conn.close()

    def _build_protein_mapping_from_database(self):
        """从数据库构建蛋白质映射"""
        try:
            import time
            start_time = time.time()

            conn = sqlite3.connect(self.db_path, timeout=10.0)
            cursor = conn.cursor()

            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='uniprot_structure_mapping'")
            if not cursor.fetchone():
                logger.info("uniprot_structure_mapping 表不存在，跳过构建蛋白质映射")
                conn.close()
                return

            # 快速检查是否有数据
            cursor.execute('SELECT COUNT(*) FROM uniprot_structure_mapping')
            count = cursor.fetchone()[0]
            logger.info(f"找到 {count} 条 UniProt 映射记录")

            # 获取所有UniProt映射
            cursor.execute('SELECT * FROM uniprot_structure_mapping LIMIT 1000')  # 限制数量
            rows = cursor.fetchall()

            if rows:
                structures_data = {}
                for row in rows:
                    uniprot_id, structure_id, protein_name, gene_name, confidence, source, created_at = row

                    if structure_id not in structures_data:
                        structures_data[structure_id] = {
                            'uniprot_ids': [],
                            'protein_name': protein_name,
                            'gene_name': gene_name
                        }

                    structures_data[structure_id]['uniprot_ids'].append(uniprot_id)

                # 构建映射
                if hasattr(self, 'protein_mapper') and self.protein_mapper:
                    self.protein_mapper.build_mapping_from_structures(structures_data)
                    logger.info(f"从数据库构建蛋白质映射: {len(structures_data)} 个结构")

            conn.close()
            logger.info(f"蛋白质映射构建完成 (耗时: {time.time() - start_time:.2f}s)")

        except Exception as e:
            logger.warning(f"构建蛋白质映射失败: {e}")
    
    def _merge_structure_data(self, structure_data: Dict, metadata: Dict) -> Dict:
        """合并结构数据和元数据"""
        merged = structure_data.copy()
        
        # 从metadata中提取重要字段
        important_fields = [
            'authors', 'related_ids', 'uniprot_ids', 
            'molecular_weight', 'polymer_count', 'group_ids'
        ]
        
        for field in important_fields:
            if field in metadata and not merged.get(field):
                value = metadata[field]
                if isinstance(value, str) and value.strip().startswith(('[', '{')):
                    try:
                        merged[field] = json.loads(value)
                    except:
                        merged[field] = value
                else:
                    merged[field] = value
        
        # 特殊处理authors字段（修复问题）
        if 'authors' in metadata and not merged.get('authors'):
            authors = metadata['authors']
            if isinstance(authors, str) and authors.strip().startswith('[{'):
                try:
                    merged['authors'] = json.loads(authors)
                except:
                    # 尝试修复格式
                    try:
                        # 可能是双重编码的JSON
                        inner_json = json.loads(authors)
                        if isinstance(inner_json, str):
                            merged['authors'] = json.loads(inner_json)
                        else:
                            merged['authors'] = inner_json
                    except:
                        merged['authors'] = []
            elif authors:
                merged['authors'] = authors
        
        return merged
    
    def _update_structure_table(self, structure_id: str, structure_data: Dict):
        """更新structures表"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 准备JSON字段
            authors_json = json.dumps(structure_data.get('authors', []), ensure_ascii=False)
            related_ids_json = json.dumps(structure_data.get('related_ids', []), ensure_ascii=False)
            uniprot_ids_json = json.dumps(structure_data.get('uniprot_ids', []), ensure_ascii=False)
            group_ids_json = json.dumps(structure_data.get('group_ids', []), ensure_ascii=False)
            
            cursor.execute('''
            UPDATE structures SET
                title = COALESCE(?, title),
                resolution = COALESCE(?, resolution),
                method = COALESCE(?, method),
                deposition_date = COALESCE(?, deposition_date),
                release_date = COALESCE(?, release_date),
                organism = COALESCE(?, organism),
                expression_system = COALESCE(?, expression_system),
                expression_system_strain = COALESCE(?, expression_system_strain),
                gene = COALESCE(?, gene),
                protein_name = COALESCE(?, protein_name),
                authors = ?,
                citation_count = COALESCE(?, citation_count),
                related_ids = ?,
                uniprot_ids = ?,
                molecular_weight = COALESCE(?, molecular_weight),
                polymer_count = COALESCE(?, polymer_count),
                group_ids = ?,
                last_updated = ?
            WHERE id = ?
            ''', (
                structure_data.get('title'),
                structure_data.get('resolution'),
                structure_data.get('method'),
                structure_data.get('deposition_date'),
                structure_data.get('release_date'),
                structure_data.get('organism'),
                structure_data.get('expression_system'),
                structure_data.get('expression_system_strain'),
                structure_data.get('gene'),
                structure_data.get('protein_name'),
                authors_json,
                structure_data.get('citation_count'),
                related_ids_json,
                uniprot_ids_json,
                structure_data.get('molecular_weight'),
                structure_data.get('polymer_count'),
                group_ids_json,
                datetime.now().isoformat(),
                structure_id
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"更新structures表失败 {structure_id}: {e}")
    

    def _save_uniprot_mapping(self, uniprot_id: str, structure_id: str, protein_name: str = '', 
                             gene_name: str = '', confidence: float = 1.0, source: str = 'manual'):
        """保存UniProt映射"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT OR REPLACE INTO uniprot_structure_mapping 
            (uniprot_id, structure_id, protein_name, gene_name, confidence, source)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                uniprot_id,
                structure_id,
                protein_name,
                gene_name,
                confidence,
                source
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.warning(f"保存UniProt映射失败 {uniprot_id}->{structure_id}: {e}")
    
    def get_structure(self, structure_id: str, use_cache: bool = True, simplify: bool = True) -> Optional[Dict[str, Any]]:
        """获取结构数据（重构版，从多个表合并）"""
        structure = self._get_structure_merged_refactored(structure_id)
        
        # 如果不需要简化，直接返回
        if not simplify:
            return structure
        
        # 简单清理即可，不需要深度清理
        if structure:
            # 移除不必要的元数据字段
            structure.pop('metadata_json', None)
            return structure
        
        return None

    def format_entity_sequence_display(self, entity: Dict, show_alignment: bool = False, chars_per_line: int = 100) -> str:
        """
        格式化实体序列显示，支持切换单独显示和比对显示
        支持多 UniProt ID 映射比对（针对嵌合蛋白/融合蛋白）
        """
        pdb_seq = entity.get('sequence', '')
        
        if not show_alignment:
            # 模式1：单独显示 (仅显示 PDB 序列)
            start_res = entity.get('start_residue') or 1
            return self.format_sequence_with_residue_numbers(pdb_seq, str(start_res), chars_per_line)
        
        # 模式2：序列比对 (读取 uniprot_ranges 中的新数据结构)
        uniprot_ranges = entity.get('uniprot_ranges', [])
        
        if not uniprot_ranges:
            return "无 UniProt 映射信息，无法进行比对。\n\n" + \
                   self.format_sequence_with_residue_numbers(pdb_seq, '1', chars_per_line)
        
        # 检查是否有新格式的 sequence 数据 (存储在 ranges 内部)
        has_sequences = any(r.get('uniprot_sequence') for r in uniprot_ranges)
        
        if not has_sequences:
            return "⚠️ 映射数据中缺少 `uniprot_sequence` 字段，数据可能未更新。\n\n" + \
                   self.format_sequence_with_residue_numbers(pdb_seq, '1', chars_per_line)
        
        return self._format_aligned_sequences(pdb_seq, uniprot_ranges, chars_per_line)

    def _format_aligned_sequences(self, pdb_seq: str, uniprot_ranges: List[Dict], chars_per_line: int) -> str:
        """
        生成多源序列比对视图字符串
        支持一个实体对应多个 UniProt ID (如 9P1S 这种嵌合蛋白)
        """
        output = []
        output.append("🧬 多源序列比对视图 (Entity vs UniProt Mappings)")
        output.append("=" * 80)

        # 1. 按 UniProt ID 分组
        # 一个 UniProt ID 可能对应多个 PDB 片段 (例如 P29274 对应 Range 0 和 Range 2)
        grouped_ranges = {}
        for r in uniprot_ranges:
            uid = r.get('uniprot_id')
            if uid not in grouped_ranges:
                grouped_ranges[uid] = []
            grouped_ranges[uid].append(r)

        # 2. 遍历每个 UniProt ID 生成独立的比对块
        for uniprot_id, ranges in grouped_ranges.items():
            # 获取该 UniProt ID 的完整序列
            # 假设同一个 ID 在不同 range 中的 sequence 是一样的 (取第一个)
            uniprot_seq = ranges[0].get('uniprot_sequence', '')
            if not uniprot_seq:
                output.append(f"\n⚠️ UniProt {uniprot_id}: 缺少序列数据")
                continue

            output.append(f"\n📍 UniProt ID: {uniprot_id}")
            output.append(f"   UniProt Length: {len(uniprot_seq)}")
            
            # 3. 构建该 UniProt 的完整映射视图数组
            # 初始化：创建一个长度等于 UniProt 序列的数组，默认填充 '-'
            aligned_pdb = ['-'] * len(uniprot_seq)
            match_line = [' '] * len(uniprot_seq)
            
            # 遍历该 UniProt ID 的所有映射片段
            for r in ranges:
                try:
                    # --- 坐标计算 (转换为 0-index) ---
                    unp_start_idx = r.get('unp_start') - 1
                    unp_end_idx = r.get('unp_end') # 切片结束通常是索引+1
                    
                    # PDB 序列的起始和结束索引
                    # pdb_start/end 通常是 1-based 残基编号
                    pdb_start_idx = r.get('pdb_start') - 1
                    pdb_end_idx = r.get('pdb_end') 
                    
                    # 计算理论长度
                    segment_len = unp_end_idx - unp_start_idx
                    
                    # --- 安全检查 ---
                    if pdb_start_idx < 0 or pdb_end_idx > len(pdb_seq):
                         logger.warning(f"PDB range out of bounds for {uniprot_id}: {pdb_start_idx+1}-{pdb_end_idx}")
                         continue
                    
                    # 截取 PDB 片段
                    # Python 切片 [start:end] 包含 start，不包含 end
                    # 残基编号 9 到 217 -> Python 索引 8 到 217
                    pdb_segment = pdb_seq[pdb_start_idx : pdb_end_idx]
                    
                    # --- 填充比对数组 ---
                    # 将 pdb_segment 的字符填入 aligned_pdb 对应 unp_start 的位置
                    # 注意：这里使用 range 遍历片段长度，处理 PDB 长度和 UniProt 长度可能不完全一致的情况
                    for i in range(min(segment_len, len(pdb_segment))):
                        u_idx = unp_start_idx + i
                        
                        if u_idx < len(uniprot_seq):
                            p_char = pdb_segment[i]
                            u_char = uniprot_seq[u_idx]
                            
                            aligned_pdb[u_idx] = p_char
                            
                            # 简单的匹配标记
                            if p_char.upper() == u_char.upper():
                                match_line[u_idx] = '|'
                            else:
                                match_line[u_idx] = '.'
                                
                except Exception as e:
                    logger.warning(f"处理映射片段失败 {uniprot_id}: {e}")
                    continue

            # 4. 渲染该 UniProt ID 的比对文本
            output.append("-" * (chars_per_line + 20))
            total_lines = (len(uniprot_seq) + chars_per_line - 1) // chars_per_line
            
            for i in range(total_lines):
                start = i * chars_per_line
                end = start + chars_per_line
                
                u_sub = uniprot_seq[start:end]
                p_sub = "".join(aligned_pdb[start:end])
                m_sub = "".join(match_line[start:end])
                
                # UniProt 行号 (基于完整序列)
                u_num = start + 1
                
                output.append(f"UniProt ({u_num:4d}): {u_sub}")
                output.append(f"Match        : {m_sub}")
                output.append(f"PDB Segment  : {p_sub}")
                output.append("") # 空行分隔

        output.append("=" * 80)
        return "\n".join(output)
    
    def _get_structure_merged_refactored(self, structure_id: str) -> Optional[Dict[str, Any]]:
        """从数据库获取并合并结构数据（重构版 - 增强版修复）"""
        try:
            # 使用已有的连接，避免每次创建新连接
            _close_conn = False
            if hasattr(self, 'conn') and self.conn:
                conn = self.conn
                cursor = conn.cursor()
            else:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                _close_conn = True

            # 1. 获取核心字段
            cursor.execute('SELECT * FROM structures WHERE id = ?', (structure_id,))
            row = cursor.fetchone()

            if not row:
                if _close_conn:
                    conn.close()
                return None
            
            structure = dict(row)
            
            # 2. 解析JSON字段 (Structure级别)
            json_fields = ['authors', 'related_ids', 'uniprot_ids', 'group_ids']
            for field in json_fields:
                # 确保字段存在，如果不存在则设为 []
                if field not in structure or structure[field] is None:
                    structure[field] = []
                    continue

                try:
                    parsed = json.loads(structure[field])
                    # 如果解析结果为 None (例如 JSON 字符串为 "null")，重置为 []
                    if parsed is None:
                        structure[field] = []
                    else:
                        structure[field] = parsed
                except:
                    structure[field] = []
            
            # 3. 获取entities
            cursor.execute('SELECT * FROM structure_entities WHERE structure_id = ?', (structure_id,))
            entities_rows = cursor.fetchall()

            entities = []
            for entity_row in entities_rows:
                entity = dict(entity_row)
                
                # 解析JSON字段 (Entity级别) - 【关键修复】
                # 增加 uniprot_ranges 等可能缺失的字段，并确保全部初始化为 []
                entity_json_fields = [
                    'molecule_name', 'gene_names', 'in_chains', 
                    'entity_data', 'uniprot_ids', 'uniprot_ranges'
                ]
                
                for field in entity_json_fields:
                    # 检查字段是否存在或为 None
                    raw_value = entity.get(field)
                    
                    if raw_value:
                        try:
                            parsed = json.loads(raw_value)
                            if parsed is None:
                                entity[field] = []
                            else:
                                entity[field] = parsed
                        except:
                            entity[field] = []
                    else:
                        # 【修复】如果字段不存在或为 None，强制设为 []，防止后续 append 报错
                        entity[field] = []
                
                entities.append(entity)

                if 'uniprot_sequence' in entity:
                    del entity['uniprot_sequence']
            
            structure['entities'] = entities
            
            # 4. 获取UniProt映射
            cursor.execute('''
            SELECT uniprot_id, protein_name, gene_name, confidence, source
            FROM uniprot_structure_mapping
            WHERE structure_id = ?
            ''', (structure_id,))
            
            uniprot_mappings = []
            for row in cursor.fetchall():
                uniprot_mappings.append(dict(row))
            
            structure['uniprot_mappings'] = uniprot_mappings
            
            # 5. 获取关系
            cursor.execute('''
            SELECT * FROM structure_relationships 
            WHERE source_id = ? OR target_id = ?
            ''', (structure_id, structure_id))
            
            relationships = []
            for row in cursor.fetchall():
                relationships.append(dict(row))
            
            structure['relationships'] = relationships
            
            # 6. 获取分组
            cursor.execute('''
            SELECT * FROM structure_groups 
            WHERE structure_id = ?
            ''', (structure_id,))
            
            groups = []
            for row in cursor.fetchall():
                try:
                    group_data = json.loads(row['group_data'])
                    if isinstance(group_data, dict):
                        groups.append(group_data)
                except:
                    pass
            
            structure['groups'] = groups

            if _close_conn:
                conn.close()
            
            # 7. 创建统一的metadata_json
            metadata_json = self._create_unified_metadata(structure)
            structure['metadata_json'] = metadata_json
            
            return structure
            
        except Exception as e:
            logger.error(f"获取结构数据失败: {e}")
            return None
          
    def _create_unified_metadata(self, structure: Dict) -> Dict:
        """创建统一的metadata_json - 修复版：确保列表字段始终为列表"""
        
        # 辅助函数：确保值是列表，如果不是则转为列表
        def ensure_list(val):
            if val is None:
                return []
            if isinstance(val, list):
                return val
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except:
                    return [val]
            return [val]

        metadata = {
            'id': structure.get('id'),
            'type': structure.get('type'),
            'title': structure.get('title'),
            'resolution': structure.get('resolution'),
            'method': structure.get('method'),
            'deposition_date': structure.get('deposition_date'),
            'release_date': structure.get('release_date'),
            'organism': structure.get('organism'),
            'expression_system': structure.get('expression_system'),
            'expression_system_strain': structure.get('expression_system_strain'),
            'gene': structure.get('gene'),
            'protein_name': structure.get('protein_name'),
            # 强制转换为列表，防止 None
            'authors': ensure_list(structure.get('authors')),
            'citation_count': structure.get('citation_count'),
            'related_ids': ensure_list(structure.get('related_ids')),
            'uniprot_ids': ensure_list(structure.get('uniprot_ids')),
            'molecular_weight': structure.get('molecular_weight'),
            'polymer_count': structure.get('polymer_count'),
            'entities': ensure_list(structure.get('entities')),
            'uniprot_mappings': ensure_list(structure.get('uniprot_mappings')),
            'relationships': ensure_list(structure.get('relationships')),
            'groups': ensure_list(structure.get('groups')),
            'group_ids': ensure_list(structure.get('group_ids')),
            'last_updated': structure.get('last_updated'),
            'created_at': structure.get('created_at')
        }
        
        # 简单清理：只移除完全为 None 或空字符串的基本字段
        # 保留空列表，因为下游代码可能依赖 list.append()
        cleaned_metadata = {}
        for key, value in metadata.items():
            if value is None or value == '':
                continue
            cleaned_metadata[key] = value
        
        return cleaned_metadata

    def analyze_protein_for_question(self, question: str) -> Dict[str, Any]:
        """
        为问题分析相关的蛋白质信息（供 structure_qa_agent 使用）
        """
        try:
            # 使用已有的 ProteinNameMapper 进行分析
            # 1. 尝试提取蛋白质名称
            protein_names = self.protein_mapper.find_structures_by_protein_name(question)
            
            # 如果直接名称匹配不到，尝试简单的关键词匹配（这里可以扩展更复杂的NLP）
            if not protein_names:
                # 简单的回退：检查 question 是否包含已知的 protein_name_map 的 key
                for name in self.protein_mapper.protein_name_map.keys():
                    if name.lower() in question.lower():
                        protein_names.extend(self.protein_mapper.find_structures_by_protein_name(name))
            
            # 去重
            protein_names = list(set(protein_names))
            
            if not protein_names:
                return {
                    "success": False,
                    "message": "未在问题中识别出已知的蛋白质名称",
                    "protein_names": [],
                    "total_structures": 0
                }
            
            # 2. 汇总结构信息
            total_structures = 0
            structures_info = {}
            
            for protein in protein_names:
                struct_ids = self.protein_mapper.find_structures_by_protein_name(protein)
                # 去重
                struct_ids = list(set(struct_ids))
                total_structures += len(struct_ids)
                
                if struct_ids:
                    structures_info[protein] = {
                        'count': len(struct_ids),
                        'structure_ids': struct_ids[:10] # 只取前10个用于展示
                    }
            
            return {
                "success": True,
                "protein_names": protein_names,
                "total_structures": total_structures,
                "structures_info": structures_info,
                "message": f"找到 {len(protein_names)} 个相关蛋白质，共 {total_structures} 个结构"
            }
            
        except Exception as e:
            logger.error(f"分析蛋白质问题失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "分析过程出错"
            }

    def save_structure(self, structure: Dict[str, Any], structure_type: Any = None) -> bool:
        """保存结构数据（增强版，确保关键字段存在）"""
        try:
            with self._lock:
                structure_id = structure.get('id', '').upper()
                if not structure_id:
                    logger.warning("无法保存结构数据：缺少结构ID")
                    return False
                
                # 确保关键字段存在
                if 'resolution' not in structure:
                    structure['resolution'] = 0.0
                
                if 'method' not in structure:
                    structure['method'] = 'Unknown'
                
                if 'authors' not in structure:
                    structure['authors'] = []
                
                if 'citation_count' not in structure:
                    structure['citation_count'] = 0
                
                # 清理metadata_json字段
                if 'metadata_json' in structure and isinstance(structure['metadata_json'], dict):
                    metadata = structure.pop('metadata_json')
                    # 从metadata中提取缺失的关键字段
                    for key in ['authors', 'citation_count', 'deposition_date', 'release_date',
                            'expression_system_strain', 'citation']:
                        if key not in structure and key in metadata:
                            structure[key] = metadata[key]
                
                # 继续原有的保存逻辑...
                return self._save_structure_refactored(structure, structure_type)
                
        except Exception as e:
            logger.error(f"保存结构数据失败: {e}", exc_info=True)
            return False
    
    def _save_structure_refactored(self, structure: Dict[str, Any], structure_type: Any) -> bool:
        """重构版的保存逻辑 - 修复数据库锁定问题和I/O错误，添加UniProt-实体映射"""
        try:
            structure_id = structure.get('id', '').upper()
            
            if not structure_id:
                return False
            
            # 确定类型字符串
            if isinstance(structure_type, StructureType):
                type_str = structure_type.value
            elif isinstance(structure_type, str):
                type_str = structure_type.lower()
            else:
                if len(structure_id) == 4:
                    type_str = StructureType.PDB.value
                elif structure_id.startswith('EMD-'):
                    type_str = StructureType.EMDB.value
                else:
                    type_str = StructureType.PDB.value
            
            logger.debug(f"保存结构 {structure_id}，类型: {type_str}")
            
            # 使用 with 语句确保连接正确关闭
            with self._lock:
                # 添加重试机制处理I/O错误
                max_retries = 3
                retry_delay = 1  # 秒
                
                for attempt in range(max_retries):
                    try:
                        conn = sqlite3.connect(self.db_path)
                        
                        try:
                            cursor = conn.cursor()
                            
                            # 先检查表结构，确保字段存在
                            cursor.execute("PRAGMA table_info(structures)")
                            columns = [row[1] for row in cursor.fetchall()]
                            
                            # 准备字段和值
                            field_names = []
                            placeholders = []
                            values = []
                            
                            # 必需字段
                            field_names.extend(['id', 'type'])
                            placeholders.extend(['?', '?'])
                            values.extend([structure_id, type_str])
                            
                            # 可选字段
                            optional_fields = [
                                ('title', ''),
                                ('resolution', None),
                                ('method', ''),
                                ('deposition_date', None),
                                ('release_date', None),
                                ('organism', ''),
                                ('expression_system', ''),
                                ('expression_system_strain', ''),
                                ('gene', ''),
                                ('protein_name', ''),
                                ('citation_count', None),
                                ('molecular_weight', None),
                                ('polymer_count', None),
                                ('last_updated', datetime.now().isoformat())
                            ]
                            
                            for field_name, default_value in optional_fields:
                                if field_name in columns:
                                    field_names.append(field_name)
                                    placeholders.append('?')
                                    value = structure.get(field_name, default_value)
                                    values.append(value)
                            
                            # JSON字段
                            json_fields = [
                                ('authors', []),
                                ('related_ids', []),
                                ('uniprot_ids', []),
                                ('group_ids', [])
                            ]
                            
                            for field_name, default_value in json_fields:
                                if field_name in columns:
                                    field_names.append(field_name)
                                    placeholders.append('?')
                                    value = structure.get(field_name, default_value)
                                    if isinstance(value, (list, dict)):
                                        values.append(json.dumps(value, ensure_ascii=False))
                                    else:
                                        values.append('[]')
                            
                            # created_at字段
                            field_names.append('created_at')
                            placeholders.append('COALESCE(?, CURRENT_TIMESTAMP)')
                            values.append(structure.get('created_at'))
                            
                            # 构建SQL
                            field_list = ', '.join(field_names)
                            placeholder_list = ', '.join(placeholders)
                            sql = f"INSERT OR REPLACE INTO structures ({field_list}) VALUES ({placeholder_list})"
                            
                            cursor.execute(sql, values)
                            
                            # 保存entities（使用同一个连接）
                            entities = structure.get('entities', [])
                            if entities:
                                self._save_structure_entities_in_transaction(structure_id, entities, conn)
                            
                            # 保存UniProt映射（使用同一个连接）
                            uniprot_ids = structure.get('uniprot_ids', [])
                            for uniprot_id in uniprot_ids:
                                self._save_uniprot_mapping_in_transaction(
                                    uniprot_id=uniprot_id,
                                    structure_id=structure_id,
                                    protein_name=structure.get('protein_name', ''),
                                    gene_name=structure.get('gene', ''),
                                    confidence=1.0,
                                    source='api',
                                    conn=conn
                                )

                            # 只有当结构类型是PDB且有实体和UniProt ID时才进行映射
                            if type_str == 'pdb' and entities and uniprot_ids:
                                # 生成映射数据列表
                                mappings_to_save = []
                                
                                for entity in entities:
                                    entity_id = entity.get('entity_id')
                                    if not entity_id:
                                        continue
                                    
                                    # 为每个UniProt ID创建映射
                                    for uniprot_id in uniprot_ids:
                                        mapping_data = {
                                            'uniprot_id': uniprot_id,
                                            'pdb_id': structure_id,
                                            'entity_id': str(entity_id),
                                            'match_score': 0.8,
                                            'match_evidence': 'direct_from_pdb_structure',
                                            'entity_info': {
                                                'entity_id': entity_id,
                                                'molecule_type': entity.get('molecule_type', ''),
                                                'molecule_name': entity.get('molecule_name', []),
                                                'gene_names': entity.get('gene_names', []),
                                                'sequence': entity.get('sequence', ''),
                                                'sequence_length': len(entity.get('sequence', ''))
                                            },
                                            'uniprot_info': {
                                                'source_pdb': structure_id,
                                                'protein_name': structure.get('protein_name', ''),
                                                'gene': structure.get('gene', ''),
                                                'organism': structure.get('organism', '')
                                            },
                                            'source': 'structure_save'
                                        }
                                        mappings_to_save.append(mapping_data)
                                
                                # 批量保存映射
                                if mappings_to_save:
                                    try:
                                        self._save_uniprot_entity_mappings_direct(mappings_to_save, conn)
                                        saved_count = len(mappings_to_save)
                                        if saved_count > 0:
                                            logger.debug(f"✅ 保存了 {saved_count} 个UniProt-实体映射")
                                    except Exception as e:
                                        logger.error(f"保存UniProt-实体映射失败: {e}")
                                        saved_count = 0

                                # 提交所有更改
                            conn.commit()
                            logger.info(f"✅ 保存结构到数据库: {structure_id}")
                            return True
                            
                        except sqlite3.OperationalError as e:
                            # 如果是磁盘I/O错误，回滚并重试
                            conn.rollback()
                            
                            error_msg = str(e)
                            if "disk I/O error" in error_msg:
                                if attempt < max_retries - 1:
                                    logger.warning(f"磁盘I/O错误，等待 {retry_delay} 秒后重试: {e}")
                                    time.sleep(retry_delay)
                                    retry_delay *= 2  # 指数退避
                                    
                                    # 在最后一次重试前尝试修复数据库
                                    if attempt == max_retries - 2:
                                        logger.info("多次I/O错误，尝试修复数据库...")
                                        try:
                                            conn.execute('VACUUM')
                                            conn.commit()
                                            logger.info("数据库VACUUM完成")
                                        except:
                                            pass
                                    continue
                                else:
                                    logger.error(f"保存结构失败（最终尝试）: {e}", exc_info=True)
                                    return False
                            else:
                                # 其他操作错误，直接返回失败
                                logger.error(f"数据库操作错误: {e}", exc_info=True)
                                return False
                                
                        except Exception as e:
                            # 发生其他错误时回滚
                            conn.rollback()
                            logger.error(f"保存结构失败: {e}", exc_info=True)
                            return False
                            
                        finally:
                            # 确保连接关闭
                            try:
                                conn.close()
                            except:
                                pass
                                
                    except Exception as outer_e:
                        if attempt < max_retries - 1:
                            logger.warning(f"外层错误，等待 {retry_delay} 秒后重试: {outer_e}")
                            time.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                        else:
                            logger.error(f"保存结构失败（外层错误，最终尝试）: {outer_e}", exc_info=True)
                            return False
                
                return False
                
        except Exception as e:
            logger.error(f"保存结构失败: {e}", exc_info=True)
            return False

    def _save_uniprot_entity_mappings_direct(self, mappings, conn):
        """
        在同一事务中批量保存UniProt-实体映射（修复database is locked问题）
        注意：不要在此函数内部执行 conn.commit()，由调用者统一提交
        """
        try:
            cursor = conn.cursor()
            current_time = datetime.now().isoformat()
            
            for mapping in mappings:
                # 1. 准备数据
                uniprot_id = mapping.get('uniprot_id')
                pdb_id = mapping.get('pdb_id')
                entity_id = mapping.get('entity_id')
                
                # 生成唯一ID
                mapping_id = f"{uniprot_id}_{pdb_id}_{entity_id}"
                
                # 处理JSON字段
                entity_info_json = json.dumps(mapping.get('entity_info', {}), ensure_ascii=False)
                uniprot_info_json = json.dumps(mapping.get('uniprot_info', {}), ensure_ascii=False)
                
                # 2. 执行SQL
                # 关键修复：列名列表中不要包含 "uniprot_entity_mappings." 前缀，也不要有多余的点
                cursor.execute('''
                INSERT OR REPLACE INTO uniprot_entity_mappings 
                (id, uniprot_id, pdb_id, entity_id, match_score, match_evidence, 
                 entity_info, uniprot_info, created_at, updated_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    mapping_id,
                    uniprot_id,
                    pdb_id,
                    entity_id,
                    mapping.get('match_score', 0.0),
                    mapping.get('match_evidence', ''),
                    entity_info_json,
                    uniprot_info_json,
                    mapping.get('created_at', current_time),
                    current_time,
                    mapping.get('source', 'unknown')
                ))
            
            # 注意：这里移除了 conn.commit()，交由外层 _save_structure_refactored 统一提交
            # 这样可以保证结构数据和映射数据在同一个事务中，要么全成功，要么全回滚
            
        except Exception as e:
            logger.error(f"批量保存UniProt-实体映射失败: {e}")
            raise  # 必须抛出异常，以便外层捕获并执行 rollback

    def save_uniprot_entity_mapping(self, mapping_data: Dict) -> bool:
        """
        保存UniProt-实体映射
        
        参数:
            mapping_data: 映射数据字典
        
        返回:
            是否成功
        """
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # 准备数据
                uniprot_id = mapping_data.get('uniprot_id')
                pdb_id = mapping_data.get('pdb_id')
                entity_id = mapping_data.get('entity_id')
                
                if not uniprot_id or not pdb_id or not entity_id:
                    logger.warning("UniProt实体映射缺少必要字段")
                    return False
                
                # 序列化JSON字段
                entity_info = json.dumps(mapping_data.get('entity_info', {}), ensure_ascii=False)
                uniprot_info = json.dumps(mapping_data.get('uniprot_info', {}), ensure_ascii=False)
                
                cursor.execute('''
                INSERT OR REPLACE INTO uniprot_entity_mappings 
                (id, uniprot_id, pdb_id, entity_id, match_score, match_evidence, 
                 entity_info, uniprot_info, created_at, updated_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    mapping_data.get('id', f"{uniprot_id}_{pdb_id}_{entity_id}"),
                    uniprot_id,
                    pdb_id,
                    entity_id,
                    mapping_data.get('match_score', 1.0),
                    mapping_data.get('match_evidence', ''),
                    entity_info,
                    uniprot_info,
                    mapping_data.get('created_at', datetime.now().isoformat()),
                    datetime.now().isoformat(),
                    mapping_data.get('source', 'unknown')
                ))
                
                conn.commit()
                conn.close()
                return True
                
        except Exception as e:
            logger.error(f"保存UniProt实体映射失败: {e}")
            return False
    
    def get_uniprot_entity_mappings_for_pdb(self, pdb_id: str) -> List[Dict]:
        """
        获取PDB的所有UniProt实体映射
        
        参数:
            pdb_id: PDB ID
        
        返回:
            UniProt实体映射列表
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT * FROM uniprot_entity_mappings
            WHERE pdb_id = ?
            ORDER BY match_score DESC
            ''', (pdb_id,))
            
            rows = cursor.fetchall()
            mappings = [dict(row) for row in rows]
            
            conn.close()
            return mappings
            
        except Exception as e:
            logger.error(f"获取UniProt实体映射失败 {pdb_id}: {e}")
            return []

    def find_entities_for_uniprot(self, uniprot_id: str) -> List[Dict]:
        """
        查找UniProt ID对应的所有实体
        
        返回:
            实体映射列表，每个元素包含:
                - pdb_id: PDB ID
                - entity_id: 实体ID
                - match_score: 匹配分数
                - match_evidence: 匹配证据
                - entity_info: 实体详细信息
                - uniprot_info: UniProt详细信息
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT pdb_id, entity_id, match_score, match_evidence, 
                   entity_info, uniprot_info, created_at
            FROM uniprot_entity_mappings
            WHERE uniprot_id = ?
            ORDER BY match_score DESC
            ''', (uniprot_id,))
            
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                result = {
                    'pdb_id': row[0],
                    'entity_id': row[1],
                    'match_score': row[2],
                    'match_evidence': row[3],
                    'entity_info': json.loads(row[4]) if row[4] else {},
                    'uniprot_info': json.loads(row[5]) if row[5] else {},
                    'created_at': row[6]
                }
                results.append(result)
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"查找UniProt实体失败 {uniprot_id}: {e}")
            return []

    def find_uniprot_for_entity(self, pdb_id: str, entity_id: str) -> List[Dict]:
        """
        查找实体对应的UniProt ID
        
        参数:
            pdb_id: PDB ID
            entity_id: 实体ID
            
        返回:
            UniProt映射列表，每个元素包含:
                - uniprot_id: UniProt ID
                - match_score: 匹配分数
                - match_evidence: 匹配证据
                - entity_info: 实体详细信息
                - uniprot_info: UniProt详细信息
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT uniprot_id, match_score, match_evidence, 
                   entity_info, uniprot_info, created_at
            FROM uniprot_entity_mappings
            WHERE pdb_id = ? AND entity_id = ?
            ORDER BY match_score DESC
            ''', (pdb_id, entity_id))
            
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                result = {
                    'uniprot_id': row[0],
                    'match_score': row[1],
                    'match_evidence': row[2],
                    'entity_info': json.loads(row[3]) if row[3] else {},
                    'uniprot_info': json.loads(row[4]) if row[4] else {},
                    'created_at': row[5]
                }
                results.append(result)
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"查找实体UniProt失败 {pdb_id} 实体 {entity_id}: {e}")
            return []

    def _async_save_uniprot_entity_mappings(self, structure_result: Dict) -> None:
        """
        异步保存UniProt-实体映射，避免数据库锁定
        """
        try:
            # 等待一小段时间，确保主事务完成
            import time
            time.sleep(0.5)  # 500ms延迟
            
            # 调用保存方法
            stats = self._save_uniprot_entity_mappings_from_structure_result(structure_result)
            
            if stats.get("success"):
                logger.info(f"✅ 异步保存完成: {stats.get('saved_mappings_count', 0)} 个映射")
            else:
                logger.warning(f"⚠️ 异步保存失败: {stats.get('error')}")
                
        except Exception as e:
            logger.error(f"异步保存UniProt-实体映射失败: {e}")

    def batch_save_uniprot_entity_mappings(self, mappings: List[Dict]) -> Dict[str, Any]:
        """
        批量保存UniProt-实体映射（修复数据库锁定问题）
        """
        try:
            # 如果映射列表为空，直接返回
            if not mappings:
                return {'success': True, 'success_count': 0, 'failed_count': 0, 'total': 0}
            
            success_count = 0
            failed_count = 0
            
            # 记录开始时间，避免无限等待
            import time
            start_time = time.time()
            max_wait_time = 10  # 最大等待10秒
            
            for mapping in mappings:
                try:
                    # 检查是否超时
                    if time.time() - start_time > max_wait_time:
                        logger.warning(f"保存映射超时，跳过剩余 {len(mappings)-failed_count-success_count} 个映射")
                        failed_count += len(mappings) - failed_count - success_count
                        break
                    
                    # 使用更智能的重试策略
                    saved = self._save_with_lock_retry(mapping)
                    
                    if saved:
                        success_count += 1
                    else:
                        failed_count += 1
                        
                except Exception as e:
                    logger.error(f"批量保存单个映射失败: {e}")
                    failed_count += 1
            
            logger.info(f"批量保存UniProt-实体映射完成: 成功={success_count}, 失败={failed_count}")
            
            return {
                'success': success_count > 0,
                'success_count': success_count,
                'failed_count': failed_count,
                'total': len(mappings),
                'success_rate': success_count / max(len(mappings), 1) * 100,
                'wait_time': time.time() - start_time
            }
            
        except Exception as e:
            logger.error(f"批量保存UniProt-实体映射失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'success_count': 0,
                'failed_count': len(mappings)
            }

    def _save_with_lock_retry(self, mapping: Dict, max_retries: int = 2, initial_delay: float = 0.1) -> bool:
        """
        带锁重试的保存方法
        """
        import time
        
        for attempt in range(max_retries):
            try:
                # 尝试保存
                if self.save_uniprot_entity_mapping(mapping):
                    return True
                else:
                    logger.debug(f"保存映射失败 (尝试 {attempt+1}/{max_retries})")
                    
            except sqlite3.OperationalError as e:
                error_msg = str(e)
                if "database is locked" in error_msg:
                    # 数据库锁定，等待后重试
                    wait_time = initial_delay * (2 ** attempt)  # 指数退避
                    logger.debug(f"数据库锁定，等待 {wait_time:.2f}s 后重试")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"数据库操作错误: {e}")
                    return False
                    
            except Exception as e:
                logger.error(f"保存映射异常: {e}")
                return False
        
        # 所有重试都失败
        return False

    def get_uniprot_entity_mapping_stats(self) -> Dict[str, Any]:
        """
        获取UniProt-实体映射统计信息
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            stats = {}
            
            # 总映射数
            cursor.execute('SELECT COUNT(*) FROM uniprot_entity_mappings')
            stats['total_mappings'] = cursor.fetchone()[0]
            
            # 唯一UniProt ID数
            cursor.execute('SELECT COUNT(DISTINCT uniprot_id) FROM uniprot_entity_mappings')
            stats['unique_uniprot_ids'] = cursor.fetchone()[0]
            
            # 唯一PDB ID数
            cursor.execute('SELECT COUNT(DISTINCT pdb_id) FROM uniprot_entity_mappings')
            stats['unique_pdb_ids'] = cursor.fetchone()[0]
            
            # 平均匹配分数
            cursor.execute('SELECT AVG(match_score) FROM uniprot_entity_mappings WHERE match_score > 0')
            stats['avg_match_score'] = cursor.fetchone()[0]
            
            # 高分映射统计（分数>0.8）
            cursor.execute('SELECT COUNT(*) FROM uniprot_entity_mappings WHERE match_score > 0.8')
            stats['high_confidence_mappings'] = cursor.fetchone()[0]
            
            # 来源分布
            cursor.execute('SELECT source, COUNT(*) as count FROM uniprot_entity_mappings GROUP BY source')
            stats['source_distribution'] = dict(cursor.fetchall())
            
            conn.close()
            return stats
            
        except Exception as e:
            logger.error(f"获取UniProt-实体映射统计失败: {e}")
            return {}

    def _save_structure_entities_in_transaction(self, structure_id: str, entities_data, conn):
        """在事务中保存entities（修复嵌套问题）- 移除entity_data字段"""
        try:
            if not entities_data:
                return
            
            cursor = conn.cursor()
            
            # 删除旧的entities
            cursor.execute('DELETE FROM structure_entities WHERE structure_id = ?', (structure_id,))
            
            for entity_item in entities_data:
                # 处理不同格式的entity数据
                if isinstance(entity_item, dict):
                    entity = entity_item
                elif isinstance(entity_item, (int, float)):
                    # 如果是数字，创建简单实体
                    entity = {'entity_id': int(entity_item)}
                else:
                    continue
                
                # 提取基本信息
                entity_id = entity.get('entity_id', 0)
                molecule_type = entity.get('molecule_type', '')
                
                # 处理molecule_name（避免嵌套）
                molecule_name = entity.get('molecule_name', [])
                if isinstance(molecule_name, list):
                    # 只取第一个有意义的名字
                    if molecule_name:
                        molecule_name_json = json.dumps([molecule_name[0]], ensure_ascii=False)
                    else:
                        molecule_name_json = '[]'
                else:
                    molecule_name_json = json.dumps([str(molecule_name)], ensure_ascii=False)
                
                # 处理gene_names
                gene_names = entity.get('gene_names', [])
                if isinstance(gene_names, list):
                    gene_names_json = json.dumps(gene_names, ensure_ascii=False)
                else:
                    gene_names_json = '[]'
                
                # 处理in_chains
                in_chains = entity.get('in_chains', [])
                if isinstance(in_chains, list):
                    in_chains_json = json.dumps(in_chains, ensure_ascii=False)
                else:
                    in_chains_json = '[]'
                
                # 提取source信息
                source = entity.get('source', {})
                source_organism = ''
                expression_host = ''
                
                if isinstance(source, dict):
                    # 优先从顶层获取
                    if 'organism_scientific_name' in entity:
                        source_organism = entity.get('organism_scientific_name', '')
                    else:
                        source_organism = source.get('organism_scientific_name', '')
                    
                    if 'expression_host_scientific_name' in entity:
                        expression_host = entity.get('expression_host_scientific_name', '')
                    else:
                        expression_host = source.get('expression_host_scientific_name', '')
                
                # 提取其他字段
                description = entity.get('description', '')
                if not description and entity.get('synonym'):
                    description = entity.get('synonym', '')
                
                # 提取链信息
                chain_ids = entity.get('chain_ids', [])
                asym_ids = entity.get('asym_ids', [])
                if isinstance(chain_ids, list):
                    chain_ids_json = json.dumps(chain_ids, ensure_ascii=False)
                else:
                    chain_ids_json = '[]'
                
                if isinstance(asym_ids, list):
                    asym_ids_json = json.dumps(asym_ids, ensure_ascii=False)
                else:
                    asym_ids_json = '[]'
                
                # 提取UniProt信息
                uniprot_ids = entity.get('uniprot_ids', [])
                if isinstance(uniprot_ids, list):
                    uniprot_ids_json = json.dumps(uniprot_ids, ensure_ascii=False)
                else:
                    uniprot_ids_json = '[]'
                
                uniprot_ranges = entity.get('uniprot_ranges', [])
                if isinstance(uniprot_ranges, list):
                    uniprot_ranges_json = json.dumps(uniprot_ranges, ensure_ascii=False)
                else:
                    uniprot_ranges_json = '[]'
                
                # 提取残基范围（直接从uniprot_ranges获取）
                start_residue = None
                end_residue = None
                
                # 从uniprot_ranges中获取PDB起始和结束残基
                if uniprot_ranges and isinstance(uniprot_ranges, list):
                    # 收集所有PDB范围
                    pdb_starts = []
                    pdb_ends = []
                    
                    for range_info in uniprot_ranges:
                        if isinstance(range_info, dict):
                            pdb_start = range_info.get('pdb_start')
                            pdb_end = range_info.get('pdb_end')
                            
                            if pdb_start is not None:
                                pdb_starts.append(pdb_start)
                            if pdb_end is not None:
                                pdb_ends.append(pdb_end)
                    
                    # 取最小起始和最大结束
                    if pdb_starts:
                        start_residue = min(pdb_starts)
                    if pdb_ends:
                        end_residue = max(pdb_ends)
                
                # 如果未找到，使用默认值
                if start_residue is None:
                    start_residue = 1
                
                if end_residue is None:
                    sequence = entity.get('sequence', '')
                    if sequence:
                        end_residue = len(sequence)
                    else:
                        end_residue = start_residue

                # 提取 taxon_id（完整步骤）
                taxon_id = ''
                
                # 1. 首先从顶层entity获取
                raw_taxon_id = entity.get('taxon_id', '')
                
                # 2. 如果顶层没有，从source字典中获取
                if (not raw_taxon_id or raw_taxon_id == '') and isinstance(source, dict):
                    raw_taxon_id = source.get('taxon_id', '')
                
                # 3. 处理taxon_id值
                if raw_taxon_id is None:
                    taxon_id = ''
                elif isinstance(raw_taxon_id, str) and raw_taxon_id.upper() == "NULL":
                    taxon_id = ''
                elif isinstance(raw_taxon_id, (int, float)):
                    # 确保taxon_id是字符串
                    taxon_id = str(int(raw_taxon_id))
                elif isinstance(raw_taxon_id, str):
                    # 清理字符串
                    taxon_id = raw_taxon_id.strip()
                else:
                    # 其他类型转换为字符串
                    taxon_id = str(raw_taxon_id)
                
                # 4. 验证taxon_id格式（应该是数字）
                if taxon_id and not taxon_id.isdigit():
                    logger.debug(f"实体 {entity_id} 的taxon_id不是数字格式: {taxon_id}")
                    taxon_id = ''

                # 插入数据
                cursor.execute('''
                INSERT INTO structure_entities 
                (structure_id, entity_id, molecule_type, molecule_name, gene_names, 
                length, weight, number_of_copies, in_chains, sequence, 
                start_residue, end_residue, source_organism, expression_host, 
                uniprot_ids, taxon_id,
                description, chain_ids, asym_ids, uniprot_ranges)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    structure_id,
                    entity_id,
                    molecule_type,
                    molecule_name_json,
                    gene_names_json,
                    entity.get('length'),
                    entity.get('weight'),
                    entity.get('number_of_copies', 1),
                    in_chains_json,
                    entity.get('sequence'),
                    start_residue,
                    end_residue,
                    source_organism,
                    expression_host,
                    uniprot_ids_json,
                    taxon_id,
                    description,
                    chain_ids_json,
                    asym_ids_json,
                    uniprot_ranges_json
                ))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"保存entities失败 {structure_id}: {e}")
            if conn:
                conn.rollback()

    def _save_uniprot_mapping_in_transaction(self, uniprot_id: str, structure_id: str, 
                                            protein_name: str = '', gene_name: str = '', 
                                            confidence: float = 1.0, source: str = 'manual',
                                            conn=None):
        """在事务中保存UniProt映射"""
        try:
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT OR REPLACE INTO uniprot_structure_mapping 
            (uniprot_id, structure_id, protein_name, gene_name, confidence, source)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                uniprot_id,
                structure_id,
                protein_name,
                gene_name,
                confidence,
                source
            ))
            
        except Exception as e:
            logger.warning(f"在事务中保存UniProt映射失败 {uniprot_id}->{structure_id}: {e}")
            # 这里不重新抛出异常，因为UniProt映射失败不应该导致整个事务失败

    # ---------- 以下为原有方法，保持不变 ----------
    
    def rebuild_vector_index(self) -> bool:
        """重建向量索引（通过统一系统）"""
        if not self.unified_vector_indexer:
            logger.warning("统一向量索引器不可用")
            return False
        
        try:
            # 获取所有结构数据
            structures = self._get_all_structures(limit=1000)
            
            if not structures:
                logger.warning("数据库中没有结构数据")
                return False
            
            # 创建文档生成器
            from core.literature_index import UnifiedDocumentGenerator, EnhancedDatabaseConnector
            db_connector = EnhancedDatabaseConnector(structure_db_path=str(self.db_path))
            generator = UnifiedDocumentGenerator(db_connector)
            
            # 创建结构文档
            documents = []
            for structure in structures:
                doc = generator.create_structure_document(structure, source_db="structure")
                if doc:
                    documents.append(doc)
            
            if not documents:
                logger.warning("没有生成有效的文档")
                return False
            
            # 构建索引
            success = self.unified_vector_indexer.build_index(documents)
            
            if success:
                logger.info(f"✅ 向量索引重建完成: {len(documents)} 个文档")
            else:
                logger.error("向量索引重建失败")
            
            return success
            
        except Exception as e:
            logger.error(f"重建向量索引失败: {e}")
            return False
    
    def _get_all_structures(self, limit: int = 1000) -> List[Dict]:
        """获取所有结构数据"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM structures LIMIT ?', (limit,))
            rows = cursor.fetchall()
            
            structures = []
            for row in rows:
                structure = dict(row)
                
                # 解析JSON字段
                for json_field in ['authors', 'related_ids', 'uniprot_ids', 'group_ids']:
                    if structure.get(json_field):
                        try:
                            structure[json_field] = json.loads(structure[json_field])
                        except:
                            structure[json_field] = []
                
                structures.append(structure)
            
            conn.close()
            return structures
            
        except Exception as e:
            logger.error(f"获取所有结构失败: {e}")
            return []
    
    def _ensure_clean_structure_before_save(self, structure: Dict[str, Any]) -> Dict[str, Any]:
        """确保在保存前结构数据是完全干净的"""
        if not structure:
            return {}
        
        cleaned = structure.copy()
        
        # 处理 metadata 字段
        if 'metadata' in cleaned and isinstance(cleaned['metadata'], dict):
            metadata = cleaned.pop('metadata')
            for key, value in metadata.items():
                if key not in cleaned or cleaned[key] is None:
                    cleaned[key] = value
        
        # 处理 metadata_json 字段
        if 'metadata_json' in cleaned:
            metadata_json = cleaned.pop('metadata_json')
            if isinstance(metadata_json, str):
                try:
                    metadata = json.loads(metadata_json)
                    if isinstance(metadata, dict):
                        for key, value in metadata.items():
                            if key not in cleaned or cleaned[key] is None:
                                cleaned[key] = value
                except:
                    pass
            elif isinstance(metadata_json, dict):
                for key, value in metadata_json.items():
                    if key not in cleaned or cleaned[key] is None:
                        cleaned[key] = value
        
        # 修复 entities 字段
        if 'entities' in cleaned:
            entities = cleaned['entities']
            if isinstance(entities, list):
                valid_entities = []
                for item in entities:
                    if isinstance(item, dict) and 'entity_id' in item:
                        valid_entities.append(item)
                
                if valid_entities:
                    cleaned['entities'] = valid_entities
                elif len(entities) > 0 and not isinstance(entities[0], dict):
                    cleaned['entities'] = []
        
        # 清理空值
        cleaned = {k: v for k, v in cleaned.items() 
                if v is not None and v != '' and v != [] and v != {}}
        
        # 添加清理标记
        cleaned['_cleaned_at'] = datetime.now().isoformat()
        cleaned['_clean_version'] = 'refactored'
        
        return cleaned
    
    def _log_search(self, query: str, search_type: str, results_count: int, response_time: float, success: bool):
        """记录搜索历史"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT INTO search_history (query, search_type, results_count, response_time, success)
            VALUES (?, ?, ?, ?, ?)
            ''', (query, search_type, results_count, response_time, success))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"记录搜索历史失败: {e}")
    
    def batch_get_structures(self, structure_ids: List[str], use_cache: bool = True) -> Dict[str, Optional[Dict[str, Any]]]:
        """批量获取结构数据（带缓存优化）"""
        start_time = time.time()
        results = {}
        
        if not structure_ids:
            return results
        
        # 去重
        unique_ids = list(set(struct_id.upper().strip() for struct_id in structure_ids))
        
        logger.info(f"批量获取 {len(unique_ids)} 个结构数据...")
        
        # 第一步：从缓存获取
        cached_results = {}
        uncached_ids = []
        
        if use_cache:
            with self._lock:
                for struct_id in unique_ids:
                    if struct_id in self._structure_cache:
                        ttl = self._structure_cache_ttl.get(struct_id, 0)
                        if time.time() < ttl:
                            cached_results[struct_id] = self._structure_cache[struct_id].copy()
                            self._cache_hits += 1
                        else:
                            # 缓存过期
                            uncached_ids.append(struct_id)
                    else:
                        uncached_ids.append(struct_id)
        else:
            uncached_ids = unique_ids
        
        # 第二步：批量从数据库获取未缓存的数据
        if uncached_ids:
            db_results = {}
            for struct_id in uncached_ids:
                structure = self.get_structure(struct_id, use_cache=False, simplify=True)
                db_results[struct_id] = structure
            
            # 保存到缓存
            if use_cache:
                with self._lock:
                    for struct_id, structure in db_results.items():
                        if structure:
                            self._structure_cache[struct_id] = structure.copy()
                            self._structure_cache_ttl[struct_id] = time.time() + self._cache_ttl_seconds
                            self._cache_saves += 1
            
            # 合并结果
            results.update(db_results)
        
        # 合并缓存结果
        results.update(cached_results)
        
        process_time = time.time() - start_time
        cache_hit_rate = len(cached_results) / len(unique_ids) * 100 if unique_ids else 0
        
        logger.info(f"✅ 批量获取完成: 总数={len(unique_ids)}, "
                   f"缓存命中={len(cached_results)} ({cache_hit_rate:.1f}%), "
                   f"时间={process_time:.2f}s")
        
        return results
    
    def search_structures(self, 
                         query: str = None,
                         structure_type: Optional[StructureType] = None,
                         organism: Optional[str] = None,
                         gene: Optional[str] = None,
                         protein_name: Optional[str] = None,
                         min_resolution: Optional[float] = None,
                         max_resolution: Optional[float] = None,
                         limit: int = 50) -> List[Dict[str, Any]]:
        """搜索结构数据"""
        start_time = time.time()
        
        try:
            # 首先尝试精确搜索
            exact_results = self._exact_search_structures(
                query=query,
                structure_type=structure_type,
                organism=organism,
                gene=gene,
                protein_name=protein_name,
                min_resolution=min_resolution,
                max_resolution=max_resolution,
                limit=limit
            )
            
            response_time = time.time() - start_time
            
            # 记录搜索历史
            self._log_search(
                query or "structured_search",
                "exact",
                len(exact_results),
                response_time,
                len(exact_results) > 0
            )
            
            # 如果统一向量索引器可用，可以尝试语义搜索
            semantic_results = []
            if query and self.unified_vector_indexer and self.unified_vector_indexer.embedding_model:
                # 使用统一系统进行语义搜索
                search_result = self.unified_vector_indexer.semantic_search(
                    query, 
                    top_k=limit, 
                    entity_types=None,
                    min_score=0.3
                )
                
                # 过滤出结构类型的结果
                for result in search_result.get('results', []):
                    if result.get('entity_type') == 'structure':
                        semantic_results.append(result)
            
            # 合并结果
            if exact_results and semantic_results:
                # 合并去重
                all_results = self._merge_search_results(exact_results, semantic_results, limit)
            elif exact_results:
                all_results = exact_results[:limit]
            elif semantic_results:
                # 获取详细的结构数据
                all_results = []
                for result in semantic_results[:limit]:
                    struct_id = result.get('doc_id', '').replace('structure_structure_', '')
                    if struct_id:
                        structure = self.get_structure(struct_id)
                        if structure:
                            structure['similarity_score'] = result.get('similarity_score', 0)
                            all_results.append(structure)
            else:
                all_results = []
            
            logger.info(f"搜索完成: {len(all_results)} 个结果 ({response_time:.2f}s)")
            return all_results[:limit]
            
        except Exception as e:
            logger.error(f"搜索结构数据失败: {e}")
            response_time = time.time() - start_time
            self._log_search(
                query or "unknown",
                "error",
                0,
                response_time,
                False
            )
            return []
    
    def _exact_search_structures(self, 
                                query: str = None,
                                structure_type: Optional[StructureType] = None,
                                organism: Optional[str] = None,
                                gene: Optional[str] = None,
                                protein_name: Optional[str] = None,
                                min_resolution: Optional[float] = None,
                                max_resolution: Optional[float] = None,
                                limit: int = 50) -> List[Dict[str, Any]]:
        """精确搜索结构数据"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 构建查询条件和参数
            conditions = []
            params = []
            
            if structure_type:
                conditions.append("type = ?")
                params.append(structure_type.value)
            
            if organism:
                conditions.append("organism LIKE ?")
                params.append(f"%{organism}%")
            
            if gene:
                conditions.append("gene LIKE ?")
                params.append(f"%{gene}%")
            
            if protein_name:
                conditions.append("protein_name LIKE ?")
                params.append(f"%{protein_name}%")
            
            if min_resolution is not None:
                conditions.append("resolution >= ?")
                params.append(min_resolution)
            
            if max_resolution is not None:
                conditions.append("resolution <= ?")
                params.append(max_resolution)
            
            # 文本搜索（标题、蛋白名、基因等）
            if query:
                search_conditions = [
                    "title LIKE ?",
                    "protein_name LIKE ?",
                    "gene LIKE ?",
                    "organism LIKE ?"
                ]
                search_param = f"%{query}%"
                conditions.append(f"({' OR '.join(search_conditions)})")
                params.extend([search_param] * len(search_conditions))
            
            # 构建SQL
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            sql = f"SELECT * FROM structures WHERE {where_clause} ORDER BY resolution ASC LIMIT ?"
            params.append(limit)
            
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                structure = dict(row)
                
                # 解析JSON字段
                for json_field in ['authors', 'related_ids', 'uniprot_ids', 'group_ids']:
                    if structure.get(json_field):
                        try:
                            structure[json_field] = json.loads(structure[json_field])
                        except:
                            structure[json_field] = []
                
                results.append(structure)
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"精确搜索结构数据失败: {e}")
            return []
    
    def _merge_search_results(self, exact_results: List[Dict], semantic_results: List[Dict], limit: int) -> List[Dict]:
        """合并搜索结果"""
        # 基于结构ID去重
        seen_ids = set()
        merged_results = []
        
        # 先添加精确搜索结果
        for result in exact_results:
            struct_id = result.get('id')
            if struct_id and struct_id not in seen_ids:
                result['search_source'] = 'exact'
                merged_results.append(result)
                seen_ids.add(struct_id)
        
        # 添加语义搜索结果
        for result in semantic_results:
            struct_id = result.get('doc_id', '').replace('structure_structure_', '')
            if struct_id and struct_id not in seen_ids:
                # 获取详细结构数据
                structure = self.get_structure(struct_id)
                if structure:
                    structure['similarity_score'] = result.get('similarity_score', 0)
                    structure['search_source'] = 'semantic'
                    merged_results.append(structure)
                    seen_ids.add(struct_id)
        
        # 按相似度或分辨率排序
        def sort_key(x):
            if 'similarity_score' in x:
                return -x['similarity_score']  # 负号表示降序
            elif 'resolution' in x and x['resolution']:
                return x['resolution']  # 分辨率升序
            else:
                return 0
        
        merged_results.sort(key=sort_key)
        
        return merged_results[:limit]
    
    def hybrid_retrieval(self, 
                        query: str,
                        search_mode: str = "auto",
                        structured_filters: Dict = None,
                        top_k: int = 10) -> Dict[str, Any]:
        """混合检索系统"""
        start_time = time.time()
        
        try:
            # 分析查询类型
            query_analysis = self._analyze_query(query)
            
            # 自动选择搜索模式
            if search_mode == "auto":
                search_mode = self._select_search_mode(query, query_analysis)
            
            exact_results = []
            semantic_results = []
            final_results = []
            
            # 执行精确搜索
            if search_mode in ["exact", "hybrid", "auto"]:
                exact_results = self._execute_exact_search(query, structured_filters, top_k)
            
            # 执行语义搜索（通过统一系统）
            if search_mode in ["semantic", "hybrid"] and self.unified_vector_indexer:
                semantic_results = self._execute_semantic_search(query, structured_filters, top_k * 2)
            
            # 合并和排序结果
            if search_mode == "exact":
                final_results = exact_results
            elif search_mode == "semantic":
                final_results = semantic_results
            else:  # hybrid 或 auto
                final_results = self._merge_results(exact_results, semantic_results, top_k)
            
            response_time = time.time() - start_time
            
            # 记录搜索
            self._log_search(
                query,
                search_mode,
                len(final_results),
                response_time,
                len(final_results) > 0
            )
            
            # 构建响应
            response = {
                "success": len(final_results) > 0,
                "mode_used": search_mode,
                "query": query,
                "query_analysis": query_analysis,
                "results": final_results[:top_k],
                "exact_results": exact_results[:5],
                "semantic_results": semantic_results[:5],
                "response_time": response_time,
                "stats": {
                    "total_results": len(final_results),
                    "exact_count": len(exact_results),
                    "semantic_count": len(semantic_results),
                    "merged_count": len(final_results)
                }
            }
            
            logger.info(f"混合检索完成: 模式={search_mode}, 结果={len(final_results)}, 时间={response_time:.2f}s")
            return response
            
        except Exception as e:
            logger.error(f"混合检索失败: {e}")
            response_time = time.time() - start_time
            self._log_search(query, "error", 0, response_time, False)
            
            return {
                "success": False,
                "mode_used": "error",
                "query": query,
                "error": str(e),
                "results": [],
                "response_time": response_time
            }
    
    def _analyze_query(self, query: str) -> Dict[str, Any]:
        """分析查询类型"""
        analysis = {
            "type": "unknown",
            "has_structure_id": False,
            "has_protein_name": False,
            "has_gene_name": False,
            "has_resolution_query": False,
            "is_natural_language": False,
            "query_length": len(query),
            "words": query.split()
        }
        
        query_lower = query.lower()
        
        # 检查是否是结构ID
        if re.match(r'^[1-9][a-z0-9]{3}$', query_lower):
            analysis["type"] = "structure_id"
            analysis["has_structure_id"] = True
        
        # 检查是否是EMDB ID
        elif re.match(r'^emd-\d+$', query_lower):
            analysis["type"] = "emdb_id"
            analysis["has_structure_id"] = True
        
        # 检查是否包含分辨率相关词汇
        resolution_keywords = ["resolution", "angstrom", "ångström", "å", "high resolution", "low resolution"]
        if any(keyword in query_lower for keyword in resolution_keywords):
            analysis["has_resolution_query"] = True
        
        # 检查是否是短查询（可能是精确查询）
        if len(query.split()) <= 3:
            analysis["type"] = "short_query"
        
        # 检查是否是自然语言查询
        if len(query.split()) > 5 or any(word in query_lower for word in ["what", "how", "which", "find", "search", "looking for"]):
            analysis["type"] = "natural_language"
            analysis["is_natural_language"] = True
        
        return analysis
    
    def _select_search_mode(self, query: str, analysis: Dict) -> str:
        """自动选择搜索模式"""
        # 如果是结构ID或短查询，优先使用精确搜索
        if analysis["has_structure_id"]:
            return "exact"
        
        # 如果是自然语言查询，使用语义搜索
        if analysis["is_natural_language"]:
            return "semantic"
        
        # 其他情况使用混合搜索
        return "hybrid"
    
    def _execute_exact_search(self, query: str, filters: Dict = None, limit: int = 10) -> List[Dict]:
        """执行精确搜索"""
        # 提取可能的蛋白质/基因名称
        protein_name = None
        gene_name = None
        
        # 简单启发式：如果查询看起来像蛋白质或基因名称
        if query and len(query) <= 20 and not query[0].isdigit():
            # 检查是否是已知的蛋白质/基因格式
            if query.isupper() or (query[0].isupper() and query[1:].islower()):
                protein_name = query
            elif query.islower() or (query[0].islower() and query[1:].islower()):
                gene_name = query
        
        # 构建搜索参数
        search_params = {}
        
        if protein_name:
            search_params["protein_name"] = protein_name
        elif gene_name:
            search_params["gene"] = gene_name
        else:
            search_params["query"] = query
        
        # 添加过滤器
        if filters:
            if "structure_type" in filters:
                try:
                    search_params["structure_type"] = StructureType(filters["structure_type"])
                except:
                    pass
            
            for key in ["organism", "min_resolution", "max_resolution"]:
                if key in filters:
                    search_params[key] = filters[key]
        
        # 执行搜索
        return self._exact_search_structures(**search_params, limit=limit)
    
    def _execute_semantic_search(self, query: str, filters: Dict = None, limit: int = 20) -> List[Dict]:
        """执行语义搜索（通过统一系统）"""
        if not self.unified_vector_indexer:
            return []
        
        # 执行语义搜索
        search_result = self.unified_vector_indexer.semantic_search(
            query=query,
            top_k=limit,
            entity_types=None,
            min_score=0.3
        )
        
        # 过滤出结构类型的结果
        structure_results = []
        for result in search_result.get('results', []):
            if result.get('entity_type') == 'structure':
                structure_results.append(result)
        
        # 获取详细的结构数据
        detailed_results = []
        for result in structure_results:
            doc_id = result.get('doc_id', '')
            if doc_id.startswith('structure_structure_'):
                struct_id = doc_id.replace('structure_structure_', '')
                structure = self.get_structure(struct_id)
                if structure:
                    structure["similarity_score"] = result.get("similarity_score", 0)
                    structure["search_source"] = "semantic"
                    detailed_results.append(structure)
        
        return detailed_results
    
    def _merge_results(self, exact_results: List[Dict], semantic_results: List[Dict], top_k: int) -> List[Dict]:
        """合并精确和语义搜索结果"""
        # 去重：基于结构ID
        seen_ids = set()
        merged_results = []
        
        # 首先添加精确搜索结果（高优先级）
        for result in exact_results:
            struct_id = result.get("id")
            if struct_id and struct_id not in seen_ids:
                result["search_source"] = "exact"
                result["similarity_score"] = result.get("similarity_score", 1.0)  # 精确匹配给最高分
                merged_results.append(result)
                seen_ids.add(struct_id)
        
        # 然后添加语义搜索结果
        for result in semantic_results:
            struct_id = result.get("id")
            if struct_id and struct_id not in seen_ids:
                result["search_source"] = "semantic"
                merged_results.append(result)
                seen_ids.add(struct_id)
        
        # 按分数排序
        merged_results.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)
        
        return merged_results[:top_k]
    
    def save_structure_relationship(self, relationship: Dict[str, Any]) -> bool:
        """保存结构关系到数据库（去重版）"""
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # 检查是否已存在相同的关系
                cursor.execute('''
                SELECT id FROM structure_relationships 
                WHERE source_id = ? AND target_id = ? AND relationship_type = ?
                ''', (
                    relationship.get('source_id'),
                    relationship.get('target_id'), 
                    relationship.get('relationship_type')
                ))
                
                existing = cursor.fetchone()
                
                if existing:
                    # 更新现有关系
                    cursor.execute('''
                    UPDATE structure_relationships 
                    SET evidence = ?, created_at = ?
                    WHERE id = ?
                    ''', (
                        relationship.get('evidence'),
                        datetime.now().isoformat(),
                        existing[0]
                    ))
                    action = "更新"
                else:
                    # 插入新关系
                    cursor.execute('''
                    INSERT INTO structure_relationships 
                    (source_id, target_id, relationship_type, evidence, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ''', (
                        relationship.get('source_id'),
                        relationship.get('target_id'),
                        relationship.get('relationship_type'),
                        relationship.get('evidence'),
                        datetime.now().isoformat()
                    ))
                    action = "添加"
                
                conn.commit()
                conn.close()
                
                logger.debug(f"✅ {action}结构关系: {relationship.get('source_id')} -> {relationship.get('target_id')}")
                return True
                
        except Exception as e:
            logger.error(f"保存结构关系失败: {e}")
            return False
    
    def get_structure_relationships(self, structure_id: str = None) -> List[Dict[str, Any]]:
        """获取结构关系"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if structure_id:
                # 获取特定结构的关系
                cursor.execute('''
                SELECT * FROM structure_relationships 
                WHERE source_id = ? OR target_id = ?
                ORDER BY created_at DESC
                ''', (structure_id, structure_id))
            else:
                # 获取所有关系
                cursor.execute('SELECT * FROM structure_relationships ORDER BY created_at DESC')
            
            rows = cursor.fetchall()
            
            relationships = []
            for row in rows:
                relationships.append(dict(row))
            
            conn.close()
            return relationships
            
        except Exception as e:
            logger.error(f"获取结构关系失败: {e}")
            return []
    
    def add_literature_structure_mapping(self, 
                                        literature_id: int, 
                                        structure_id: str,
                                        structure_type: StructureType,
                                        context: str = None,
                                        page_number: int = None,
                                        confidence: float = 1.0) -> bool:
        """添加文献-结构映射关系"""
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                cursor.execute('''
                INSERT OR REPLACE INTO literature_structure_mapping 
                (literature_id, structure_id, structure_type, context, page_number, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (literature_id, structure_id.upper(), structure_type.value, context, page_number, confidence))
                
                conn.commit()
                conn.close()
                
                logger.debug(f"✅ 添加文献-结构映射: 文献ID={literature_id}, 结构ID={structure_id}")
                return True
                
        except Exception as e:
            logger.error(f"添加文献-结构映射失败: {e}")
            return False
    
    def get_structures_for_literature(self, literature_id: int) -> List[Dict[str, Any]]:
        """获取文献相关的所有结构"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT s.*, m.context, m.page_number, m.confidence
            FROM literature_structure_mapping m
            JOIN structures s ON m.structure_id = s.id
            WHERE m.literature_id = ?
            ORDER BY m.confidence DESC
            ''', (literature_id,))
            
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                structure = dict(row)
                
                # 解析JSON字段
                for json_field in ['authors', 'related_ids', 'uniprot_ids', 'group_ids']:
                    if structure.get(json_field):
                        try:
                            structure[json_field] = json.loads(structure[json_field])
                        except:
                            structure[json_field] = []
                
                results.append(structure)
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"获取文献结构失败: {e}")
            return []
    
    def get_literature_for_structure(self, structure_id: str) -> List[int]:
        """获取结构相关的所有文献ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT literature_id FROM literature_structure_mapping 
            WHERE structure_id = ?
            ORDER BY confidence DESC
            ''', (structure_id.upper(),))
            
            rows = cursor.fetchall()
            literature_ids = [row[0] for row in rows]
            
            conn.close()
            return literature_ids
            
        except Exception as e:
            logger.error(f"获取结构相关文献失败: {e}")
            return []
    
    def delete_literature_mappings(self, literature_id: int) -> bool:
        """删除指定文献的所有结构映射"""
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # 删除文献-结构映射
                cursor.execute(
                    "DELETE FROM literature_structure_mapping WHERE literature_id = ?",
                    (literature_id,)
                )
                
                deleted_count = cursor.rowcount
                conn.commit()
                conn.close()
                
                logger.info(f"✅ 删除文献结构映射: 文献ID={literature_id}, 删除{deleted_count}条")
                return True
                
        except Exception as e:
            logger.error(f"删除文献结构映射失败: {e}")
            return False
    
    def delete_specific_mapping(self, literature_id: int, structure_id: str) -> bool:
        """删除特定的文献-结构映射"""
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                cursor.execute(
                    "DELETE FROM literature_structure_mapping WHERE literature_id = ? AND structure_id = ?",
                    (literature_id, structure_id.upper())
                )
                
                conn.commit()
                conn.close()
                return True
                
        except Exception as e:
            logger.error(f"删除特定映射失败: {e}")
            return False
    
    def answer_question(self, question: str, context: str = None) -> Dict[str, Any]:
        """回答关于结构的问题"""
        start_time = time.time()
        
        try:
            logger.info(f"回答结构问题: '{question}'")
            
            # 1. 分析问题
            question_analysis = self._analyze_question(question)
            
            # 2. 根据问题类型选择检索策略
            if question_analysis["type"] == "structure_info":
                # 结构信息查询：使用精确检索
                response = self._answer_structure_info_question(question, question_analysis)
            elif question_analysis["type"] == "comparison":
                # 比较查询：使用混合检索
                response = self._answer_comparison_question(question, question_analysis)
            elif question_analysis["type"] == "search":
                # 搜索查询：使用混合检索
                response = self._answer_search_question(question, question_analysis)
            else:
                # 通用查询：使用混合检索
                response = self._answer_general_question(question, question_analysis)
            
            response["response_time"] = time.time() - start_time
            response["question_analysis"] = question_analysis
            
            logger.info(f"问题回答完成: {response['response_time']:.2f}s")
            return response
            
        except Exception as e:
            logger.error(f"回答问题失败: {e}")
            return {
                "success": False,
                "answer": f"抱歉，回答问题失败: {str(e)}",
                "sources": [],
                "response_time": time.time() - start_time
            }
    
    def _analyze_question(self, question: str) -> Dict[str, Any]:
        """分析问题类型"""
        analysis = {
            "type": "general",
            "has_structure_id": False,
            "has_protein_name": False,
            "has_gene_name": False,
            "has_comparison": False,
            "has_resolution_query": False,
            "key_terms": []
        }
        
        question_lower = question.lower()
        
        # 提取结构ID
        structure_ids = re.findall(r'\b[1-9][a-z0-9]{3}\b', question_lower)
        if structure_ids:
            analysis["has_structure_id"] = True
            analysis["structure_ids"] = structure_ids
            analysis["key_terms"].extend(structure_ids)
        
        # 检查比较词汇
        comparison_words = ["compare", "comparison", "vs", "versus", "difference", "similar", "better", "worse"]
        if any(word in question_lower for word in comparison_words):
            analysis["type"] = "comparison"
            analysis["has_comparison"] = True
        
        # 检查分辨率相关词汇
        resolution_words = ["resolution", "angstrom", "high resolution", "low resolution", "resolution of"]
        if any(word in question_lower for word in resolution_words):
            analysis["has_resolution_query"] = True
        
        # 检查是否是结构信息查询
        info_patterns = [
            r"what is.*structure",
            r"information about.*",
            r"details of.*",
            r"tell me about.*"
        ]
        for pattern in info_patterns:
            if re.search(pattern, question_lower):
                analysis["type"] = "structure_info"
                break
        
        # 检查是否是搜索查询
        search_patterns = [
            r"find.*structure",
            r"search for.*",
            r"look for.*",
            r"structures of.*",
            r"list.*structures"
        ]
        for pattern in search_patterns:
            if re.search(pattern, question_lower):
                analysis["type"] = "search"
                break
        
        # 提取关键词
        words = question_lower.split()
        for word in words:
            if len(word) > 3 and word not in ["what", "where", "when", "which", "how", "about", "structure", "protein"]:
                analysis["key_terms"].append(word)
        
        return analysis
    
    def _answer_structure_info_question(self, question: str, analysis: Dict) -> Dict[str, Any]:
        """回答结构信息问题"""
        if not analysis.get("structure_ids"):
            return {
                "success": False,
                "answer": "请提供具体的结构ID，如7EWL或EMD-12345",
                "sources": []
            }
        
        structure_id = analysis["structure_ids"][0]
        structure = self.get_structure(structure_id)
        
        if not structure:
            return {
                "success": False,
                "answer": f"未找到结构 {structure_id} 的信息",
                "sources": []
            }
        
        # 构建答案
        answer_parts = []
        answer_parts.append(f"**{structure.get('title', 'Unknown')}**")
        
        if structure.get('protein_name'):
            answer_parts.append(f"**蛋白质**: {structure['protein_name']}")
        
        if structure.get('gene'):
            answer_parts.append(f"**基因**: {structure['gene']}")
        
        if structure.get('organism'):
            answer_parts.append(f"**生物体**: {structure['organism']}")
        
        if structure.get('resolution'):
            answer_parts.append(f"**分辨率**: {structure['resolution']} Å")
        
        if structure.get('method'):
            answer_parts.append(f"**方法**: {structure['method']}")
        
        if structure.get('release_date'):
            answer_parts.append(f"**发布日期**: {structure['release_date']}")
        
        answer = "\n".join(answer_parts)
        
        return {
            "success": True,
            "answer": answer,
            "sources": [structure],
            "structure_id": structure_id
        }
    
    def _answer_comparison_question(self, question: str, analysis: Dict) -> Dict[str, Any]:
        """回答比较问题"""
        # 提取比较的结构
        structure_ids = analysis.get("structure_ids", [])
        
        if len(structure_ids) < 2:
            # 如果没有明确的结构ID，尝试使用混合检索
            retrieval_result = self.hybrid_retrieval(question, search_mode="hybrid", top_k=5)
            
            if not retrieval_result["success"]:
                return {
                    "success": False,
                    "answer": "无法找到足够的结构进行比较",
                    "sources": []
                }
            
            structures = retrieval_result["results"]
            
            if len(structures) < 2:
                return {
                    "success": False,
                    "answer": f"只找到了1个相关结构：{structures[0].get('title', 'Unknown')}",
                    "sources": structures
                }
            
            # 比较前两个结构
            struct1 = structures[0]
            struct2 = structures[1]
        else:
            # 获取指定结构
            struct1 = self.get_structure(structure_ids[0])
            struct2 = self.get_structure(structure_ids[1])
            
            if not struct1 or not struct2:
                return {
                    "success": False,
                    "answer": "无法找到指定的结构",
                    "sources": []
                }
        
        # 构建比较答案
        answer_parts = ["**结构比较**:\n"]
        
        # 标题
        answer_parts.append(f"1. **{struct1.get('id', 'Unknown')}**: {struct1.get('title', 'Unknown')}")
        answer_parts.append(f"2. **{struct2.get('id', 'Unknown')}**: {struct2.get('title', 'Unknown')}\n")
        
        # 分辨率比较
        res1 = struct1.get('resolution')
        res2 = struct2.get('resolution')
        
        if res1 and res2:
            if res1 < res2:
                answer_parts.append(f"**分辨率**: {struct1['id']} ({res1} Å) 比 {struct2['id']} ({res2} Å) 更高")
            else:
                answer_parts.append(f"**分辨率**: {struct2['id']} ({res2} Å) 比 {struct1['id']} ({res1} Å) 更高")
        
        # 方法比较
        method1 = struct1.get('method', '')
        method2 = struct2.get('method', '')
        
        if method1 and method2:
            if method1 == method2:
                answer_parts.append(f"**方法**: 两者都使用 {method1}")
            else:
                answer_parts.append(f"**方法**: {struct1['id']} 使用 {method1}, {struct2['id']} 使用 {method2}")
        
        # 生物体比较
        org1 = struct1.get('organism', '')
        org2 = struct2.get('organism', '')
        
        if org1 and org2:
            if org1 == org2:
                answer_parts.append(f"**生物体**: 两者都来自 {org1}")
            else:
                answer_parts.append(f"**生物体**: {struct1['id']} 来自 {org1}, {struct2['id']} 来自 {org2}")
        
        answer = "\n".join(answer_parts)
        
        return {
            "success": True,
            "answer": answer,
            "sources": [struct1, struct2],
            "comparison_type": "structure_comparison"
        }
    
    def _answer_search_question(self, question: str, analysis: Dict) -> Dict[str, Any]:
        """回答搜索问题"""
        # 使用混合检索
        retrieval_result = self.hybrid_retrieval(question, search_mode="hybrid", top_k=10)
        
        if not retrieval_result["success"]:
            return {
                "success": False,
                "answer": "没有找到相关的结构信息",
                "sources": []
            }
        
        structures = retrieval_result["results"]
        
        # 构建答案
        answer_parts = [f"找到了 {len(structures)} 个相关结构：\n"]
        
        for i, structure in enumerate(structures[:5]):
            title = structure.get('title', 'Unknown')
            struct_id = structure.get('id', 'Unknown')
            resolution = structure.get('resolution')
            
            line = f"{i+1}. **{struct_id}**: {title}"
            if resolution:
                line += f" (分辨率: {resolution} Å)"
            
            answer_parts.append(line)
        
        if len(structures) > 5:
            answer_parts.append(f"\n... 还有 {len(structures) - 5} 个结构")
        
        answer = "\n".join(answer_parts)
        
        return {
            "success": True,
            "answer": answer,
            "sources": structures,
            "search_stats": retrieval_result["stats"]
        }
    
    def _answer_general_question(self, question: str, analysis: Dict) -> Dict[str, Any]:
        """回答一般性问题"""
        # 提取关键词
        key_terms = analysis.get("key_terms", [])
        
        if not key_terms:
            return {
                "success": False,
                "answer": "无法理解您的问题，请提供更具体的信息",
                "sources": []
            }
        
        # 使用关键词进行混合检索
        query = " ".join(key_terms[:3])
        retrieval_result = self.hybrid_retrieval(query, search_mode="hybrid", top_k=5)
        
        if not retrieval_result["success"]:
            return {
                "success": False,
                "answer": "没有找到相关信息",
                "sources": []
            }
        
        structures = retrieval_result["results"]
        
        # 构建通用答案
        if structures:
            top_structure = structures[0]
            title = top_structure.get('title', 'Unknown')
            struct_id = top_structure.get('id', 'Unknown')
            
            answer = f"根据您的查询，最相关的结构是 **{struct_id}**: {title}"
            
            if top_structure.get('resolution'):
                answer += f"\n该结构的分辨率为 {top_structure['resolution']} Å"
            
            if top_structure.get('method'):
                answer += f"，使用 {top_structure['method']} 方法解析"
            
            if len(structures) > 1:
                answer += f"\n\n此外，还找到了 {len(structures)-1} 个相关结构"
        else:
            answer = "没有找到完全匹配的结构信息"
        
        return {
            "success": True,
            "answer": answer,
            "sources": structures,
            "query_used": query
        }
    
    def add_protein_structure_mapping(self, 
                                     protein_name: str,
                                     pdb_ids: List[str] = None,
                                     emdb_ids: List[str] = None,
                                     uniprot_id: str = None,
                                     gene_name: str = None,
                                     preferred_structure_id: str = None) -> bool:
        """添加蛋白质-结构映射"""
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                pdb_json = json.dumps(pdb_ids or [], ensure_ascii=False)
                emdb_json = json.dumps(emdb_ids or [], ensure_ascii=False)
                
                cursor.execute('''
                INSERT OR REPLACE INTO protein_structure_mapping 
                (protein_name, uniprot_id, gene_name, pdb_ids, emdb_ids, preferred_structure_id, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (protein_name, uniprot_id, gene_name, pdb_json, emdb_json, preferred_structure_id, datetime.now().isoformat()))
                
                conn.commit()
                conn.close()
                
                logger.debug(f"✅ 添加蛋白质-结构映射: {protein_name} -> {len(pdb_ids or [])} PDB, {len(emdb_ids or [])} EMDB")
                return True
                
        except Exception as e:
            logger.error(f"添加蛋白质-结构映射失败: {e}")
            return False
    
    def get_structures_for_protein(self, protein_name: str) -> Optional[Dict[str, Any]]:
        """获取蛋白质相关的所有结构"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM protein_structure_mapping WHERE protein_name = ?', (protein_name,))
            row = cursor.fetchone()
            
            if row:
                protein_data = dict(row)
                
                # 解析JSON字段
                for json_field in ['pdb_ids', 'emdb_ids']:
                    if protein_data.get(json_field):
                        try:
                            protein_data[json_field] = json.loads(protein_data[json_field])
                        except:
                            protein_data[json_field] = []
                
                # 获取详细结构信息
                all_structure_ids = protein_data.get('pdb_ids', []) + protein_data.get('emdb_ids', [])
                detailed_structures = []
                
                for struct_id in all_structure_ids[:20]:  # 限制数量
                    structure = self.get_structure(struct_id)
                    if structure:
                        detailed_structures.append(structure)
                
                protein_data['detailed_structures'] = detailed_structures
                
                conn.close()
                return protein_data
            
            conn.close()
            return None
            
        except Exception as e:
            logger.error(f"获取蛋白质结构失败: {e}")
            return None
    
    def search_proteins(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """搜索蛋白质"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT * FROM protein_structure_mapping 
            WHERE protein_name LIKE ? OR gene_name LIKE ?
            ORDER BY LENGTH(pdb_ids) + LENGTH(emdb_ids) DESC
            LIMIT ?
            ''', (f"%{query}%", f"%{query}%", limit))
            
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                protein_data = dict(row)
                
                # 解析JSON字段
                for json_field in ['pdb_ids', 'emdb_ids']:
                    if protein_data.get(json_field):
                        try:
                            protein_data[json_field] = json.loads(protein_data[json_field])
                        except:
                            protein_data[json_field] = []
                
                results.append(protein_data)
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"搜索蛋白质失败: {e}")
            return []
    
    def add_uniprot_structure_mapping(self,
                                     uniprot_id: str,
                                     structure_id: str,
                                     protein_name: str = None,
                                     gene_name: str = None,
                                     confidence: float = 1.0,
                                     source: str = "manual") -> bool:
        """添加UniProt-结构映射"""
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                cursor.execute('''
                INSERT OR REPLACE INTO uniprot_structure_mapping 
                (uniprot_id, structure_id, protein_name, gene_name, confidence, source)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (uniprot_id, structure_id.upper(), protein_name, gene_name, confidence, source))
                
                conn.commit()
                conn.close()
                
                # 更新内存中的映射
                if structure_id not in self.protein_mapper.uniprot_structure_map:
                    self.protein_mapper.uniprot_structure_map[structure_id] = []
                if uniprot_id not in self.protein_mapper.uniprot_structure_map[structure_id]:
                    self.protein_mapper.uniprot_structure_map[structure_id].append(uniprot_id)
                
                logger.debug(f"✅ 添加UniProt-结构映射: {uniprot_id} -> {structure_id}")
                return True
                
        except Exception as e:
            logger.error(f"添加UniProt-结构映射失败: {e}")
            return False
    
    def batch_add_uniprot_mappings(self, mappings: List[Tuple[str, str, str, str, float, str]]) -> int:
        """批量添加UniProt映射"""
        success_count = 0
        for mapping in mappings:
            if self.add_uniprot_structure_mapping(*mapping):
                success_count += 1
        return success_count
    
    def find_structures_by_uniprot_id(self, uniprot_id: str) -> List[Dict[str, Any]]:
        """通过UniProt ID查找结构"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT s.*, m.confidence, m.source
            FROM uniprot_structure_mapping m
            JOIN structures s ON m.structure_id = s.id
            WHERE m.uniprot_id = ?
            ORDER BY m.confidence DESC, s.resolution ASC
            ''', (uniprot_id,))
            
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                structure = dict(row)
                
                # 解析JSON字段
                for json_field in ['authors', 'related_ids', 'uniprot_ids', 'group_ids']:
                    if structure.get(json_field):
                        try:
                            structure[json_field] = json.loads(structure[json_field])
                        except:
                            structure[json_field] = []
                
                results.append(structure)
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"通过UniProt ID查找结构失败: {e}")
            return []
    
    def find_uniprot_ids_for_structure(self, structure_id: str) -> List[Dict[str, Any]]:
        """查找结构对应的UniProt ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT uniprot_id, protein_name, gene_name, confidence, source
            FROM uniprot_structure_mapping
            WHERE structure_id = ?
            ORDER BY confidence DESC
            ''', (structure_id.upper(),))
            
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                results.append({
                    'uniprot_id': row[0],
                    'protein_name': row[1],
                    'gene_name': row[2],
                    'confidence': row[3],
                    'source': row[4]
                })
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"查找结构对应的UniProt ID失败: {e}")
            return []
    
    def find_structures_by_protein_name_mapper(self, protein_name: str) -> List[Dict[str, Any]]:
        """通过蛋白质名称映射器查找相关结构"""
        # 使用ProteinNameMapper查找结构ID
        structure_ids = self.protein_mapper.find_structures_by_protein_name(protein_name)
        
        # 获取详细结构信息
        structures = []
        for struct_id in structure_ids[:20]:  # 限制数量
            structure = self.get_structure(struct_id)
            if structure:
                structures.append(structure)
        
        return structures
    
    def get_protein_mapper_statistics(self) -> Dict[str, Any]:
        """获取蛋白质映射器统计信息"""
        return self.protein_mapper.get_statistics()
    
    def save_protein_mapping_to_file(self, filepath: str = "protein_mapping.json"):
        """保存蛋白质映射到文件"""
        self.protein_mapper.save_mapping_to_file(filepath)
    
    def load_protein_mapping_from_file(self, filepath: str = "protein_mapping.json"):
        """从文件加载蛋白质映射"""
        return self.protein_mapper.load_mapping_from_file(filepath)
    
    def get_database_stats(self) -> Dict[str, Any]:
        """获取数据库统计信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            stats = {}
            
            # 结构统计
            cursor.execute('SELECT COUNT(*) FROM structures')
            stats['total_structures'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM structures WHERE type = ?', ('pdb',))
            stats['pdb_count'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM structures WHERE type = ?', ('emdb',))
            stats['emdb_count'] = cursor.fetchone()[0]
            
            # 实体统计
            cursor.execute('SELECT COUNT(*) FROM structure_entities')
            stats['total_entities'] = cursor.fetchone()[0]
            
            # 分辨率统计
            cursor.execute('SELECT MIN(resolution), MAX(resolution), AVG(resolution) FROM structures WHERE resolution > 0')
            min_res, max_res, avg_res = cursor.fetchone()
            stats['resolution'] = {
                'min': min_res,
                'max': max_res,
                'avg': avg_res
            }
            
            # 生物体统计
            cursor.execute('SELECT organism, COUNT(*) as count FROM structures WHERE organism IS NOT NULL AND organism != "Unknown" GROUP BY organism ORDER BY count DESC LIMIT 10')
            stats['top_organisms'] = cursor.fetchall()
            
            # 映射统计
            cursor.execute('SELECT COUNT(*) FROM literature_structure_mapping')
            stats['literature_mappings'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(DISTINCT literature_id) FROM literature_structure_mapping')
            stats['literatures_with_structures'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM protein_structure_mapping')
            stats['protein_mappings'] = cursor.fetchone()[0]
            
            # UniProt映射统计
            cursor.execute('SELECT COUNT(*) FROM uniprot_structure_mapping')
            stats['uniprot_mappings'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(DISTINCT uniprot_id) FROM uniprot_structure_mapping')
            stats['unique_uniprot_ids'] = cursor.fetchone()[0]
            
            # 结构关系统计
            cursor.execute('SELECT COUNT(*) FROM structure_relationships')
            stats['structure_relationships'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT relationship_type, COUNT(*) as count FROM structure_relationships GROUP BY relationship_type')
            stats['relationship_types'] = cursor.fetchall()
            
            # 结构分组统计
            cursor.execute('SELECT COUNT(DISTINCT group_id) FROM structure_groups')
            stats['structure_groups'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT AVG(count) FROM (SELECT group_id, COUNT(*) as count FROM structure_groups GROUP BY group_id)')
            avg_group_size = cursor.fetchone()[0]
            stats['avg_group_size'] = avg_group_size if avg_group_size else 0
            
            # 搜索历史统计
            cursor.execute('SELECT COUNT(*) FROM search_history')
            stats['total_searches'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT AVG(response_time) FROM search_history WHERE success = 1')
            stats['avg_response_time'] = cursor.fetchone()[0]
            
            # 统一向量索引器状态
            stats['has_unified_vector_indexer'] = self.unified_vector_indexer is not None
            
            # 蛋白质映射器统计
            protein_stats = self.protein_mapper.get_statistics()
            stats.update(protein_stats)
            
            conn.close()
            
            logger.info(f"数据库统计: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"获取数据库统计失败: {e}")
            return {}
    
    def get_search_analytics(self) -> Dict[str, Any]:
        """获取搜索分析"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            analytics = {}
            
            # 搜索类型分布
            cursor.execute('''
            SELECT search_type, COUNT(*) as count, AVG(results_count) as avg_results, AVG(response_time) as avg_time
            FROM search_history 
            GROUP BY search_type 
            ORDER BY count DESC
            ''')
            analytics['search_type_distribution'] = cursor.fetchall()
            
            # 成功率
            cursor.execute('SELECT COUNT(*) FROM search_history WHERE success = 1')
            successful = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM search_history')
            total = cursor.fetchone()[0]
            analytics['success_rate'] = successful / total if total > 0 else 0
            
            # 热门查询
            cursor.execute('''
            SELECT query, COUNT(*) as frequency, AVG(results_count) as avg_results
            FROM search_history 
            WHERE query != 'structured_search' AND query != 'unknown'
            GROUP BY query 
            ORDER BY frequency DESC 
            LIMIT 10
            ''')
            analytics['top_queries'] = cursor.fetchall()
            
            # 响应时间趋势
            cursor.execute('''
            SELECT DATE(created_at) as date, AVG(response_time) as avg_time, COUNT(*) as searches
            FROM search_history 
            GROUP BY DATE(created_at) 
            ORDER BY date DESC 
            LIMIT 7
            ''')
            analytics['recent_trends'] = cursor.fetchall()
            
            conn.close()
            return analytics
            
        except Exception as e:
            logger.error(f"获取搜索分析失败: {e}")
            return {}
    
    def export_database(self, export_path: str = "structure_database_export.json") -> bool:
        """导出数据库内容"""
        try:
            export_data = {
                'metadata': {
                    'export_date': datetime.now().isoformat(),
                    'version': '1.0',
                    'has_unified_vector_indexer': self.unified_vector_indexer is not None
                },
                'statistics': self.get_database_stats(),
                'search_analytics': self.get_search_analytics(),
                'structures': [],
                'protein_mappings': [],
                'uniprot_mappings': [],
                'structure_relationships': [],
                'structure_groups': []
            }
            
            # 导出所有结构
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM structures LIMIT 1000')  # 限制导出数量
            rows = cursor.fetchall()
            
            for row in rows:
                structure = dict(row)
                
                # 解析JSON字段
                for json_field in ['authors', 'related_ids', 'uniprot_ids', 'group_ids']:
                    if structure.get(json_field):
                        try:
                            structure[json_field] = json.loads(structure[json_field])
                        except:
                            structure[json_field] = []
                
                export_data['structures'].append(structure)
            
            # 导出蛋白质映射
            cursor.execute('SELECT * FROM protein_structure_mapping LIMIT 500')
            rows = cursor.fetchall()
            
            for row in rows:
                protein_data = dict(row)
                
                # 解析JSON字段
                for json_field in ['pdb_ids', 'emdb_ids']:
                    if protein_data.get(json_field):
                        try:
                            protein_data[json_field] = json.loads(protein_data[json_field])
                        except:
                            protein_data[json_field] = []
                
                export_data['protein_mappings'].append(protein_data)
            
            # 导出UniProt映射
            cursor.execute('SELECT * FROM uniprot_structure_mapping LIMIT 500')
            rows = cursor.fetchall()
            
            for row in rows:
                uniprot_data = {
                    'uniprot_id': row[0],
                    'structure_id': row[1],
                    'protein_name': row[2],
                    'gene_name': row[3],
                    'confidence': row[4],
                    'source': row[5],
                    'created_at': row[6]
                }
                export_data['uniprot_mappings'].append(uniprot_data)
            
            # 导出结构关系
            cursor.execute('SELECT * FROM structure_relationships LIMIT 500')
            rows = cursor.fetchall()
            
            for row in rows:
                relationship = {
                    'source_id': row[1],
                    'target_id': row[2],
                    'relationship_type': row[3],
                    'evidence': row[4],
                    'created_at': row[5]
                }
                export_data['structure_relationships'].append(relationship)
            
            # 导出结构分组
            cursor.execute('SELECT DISTINCT group_id FROM structure_groups LIMIT 100')
            group_rows = cursor.fetchall()
            
            for row in group_rows:
                group_id = row[0]
                cursor.execute('SELECT * FROM structure_groups WHERE group_id = ?', (group_id,))
                group_data_rows = cursor.fetchall()
                
                if group_data_rows:
                    try:
                        group_data = json.loads(group_data_rows[0][3])  # group_data字段
                        export_data['structure_groups'].append(group_data)
                    except:
                        pass
            
            conn.close()
            
            # 保存到文件
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"✅ 数据库导出完成: {export_path}")
            return True
            
        except Exception as e:
            logger.error(f"导出数据库失败: {e}")
            return False
    
    def clear_cache(self, structure_id: str = None):
        """清除缓存"""
        with self._lock:
            if structure_id:
                # 清除特定结构的缓存
                struct_id_upper = structure_id.upper()
                if struct_id_upper in self._structure_cache:
                    del self._structure_cache[struct_id_upper]
                if struct_id_upper in self._structure_cache_ttl:
                    del self._structure_cache_ttl[struct_id_upper]
                logger.debug(f"清除结构缓存: {structure_id}")
            else:
                # 清除所有缓存
                self._structure_cache.clear()
                self._structure_cache_ttl.clear()
                logger.info("清除所有结构缓存")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            total_requests = self._cache_hits + self._cache_misses
            hit_rate = self._cache_hits / total_requests * 100 if total_requests > 0 else 0
            
            return {
                'cache_hits': self._cache_hits,
                'cache_misses': self._cache_misses,
                'cache_saves': self._cache_saves,
                'hit_rate_percent': hit_rate,
                'cache_size': len(self._structure_cache),
                'cache_ttl_seconds': self._cache_ttl_seconds,
                'current_time': time.time()
            }
    
    def vacuum(self):
        """优化数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute('VACUUM')
            conn.close()
            logger.info("✅ 数据库优化完成")
        except Exception as e:
            logger.error(f"数据库优化失败: {e}")
    
    def get_structure_with_relationships(self, structure_id: str) -> Optional[Dict[str, Any]]:
        """获取结构及其所有关系"""
        try:
            # 获取结构信息
            structure = self.get_structure(structure_id)
            if not structure:
                return None
            
            # 获取关系信息
            relationships = self.get_structure_relationships(structure_id)
            if relationships:
                structure['relationships'] = relationships
            
            return structure
            
        except Exception as e:
            logger.error(f"获取结构及其关系失败: {e}")
            return None
    
    def get_related_structures(self, structure_id: str, max_depth: int = 2) -> Dict[str, Any]:
        """获取相关结构（递归查找）"""
        try:
            def find_related(struct_id, visited, depth):
                if depth > max_depth or struct_id in visited:
                    return []
                
                visited.add(struct_id)
                related = []
                
                # 获取直接关系
                relationships = self.get_structure_relationships(struct_id)
                for rel in relationships:
                    other_id = rel['target_id'] if rel['source_id'] == struct_id else rel['source_id']
                    if other_id not in visited:
                        related.append({
                            'structure_id': other_id,
                            'relationship': rel,
                            'depth': depth
                        })
                        # 递归查找
                        if depth < max_depth:
                            deeper_related = find_related(other_id, visited, depth + 1)
                            related.extend(deeper_related)
                
                return related
            
            visited = set()
            related = find_related(structure_id, visited, 1)
            
            # 获取结构详情
            related_structures = []
            for item in related:
                struct_info = self.get_structure(item['structure_id'])
                if struct_info:
                    struct_info['relationship_info'] = item
                    related_structures.append(struct_info)
            
            return {
                'structure_id': structure_id,
                'related_count': len(related_structures),
                'max_depth': max_depth,
                'related_structures': related_structures
            }
            
        except Exception as e:
            logger.error(f"获取相关结构失败: {e}")
            return {'structure_id': structure_id, 'related_count': 0, 'error': str(e)}
    
    def batch_get_or_fetch_structures(self, structure_ids: List[str], use_cache: bool = True, 
                                    force_update: bool = False) -> Dict[str, Any]:
        """
        批量获取或获取结构数据（增强版，使用缓存和单例模式）
        """
        start_time = time.time()
        
        try:
            logger.info(f"批量获取结构数据: {len(structure_ids)} 个结构ID，强制更新={force_update}")
            
            # 去重和规范化结构ID
            unique_ids = []
            pdb_ids = []
            emdb_ids = []
            
            for struct_id in structure_ids:
                if not struct_id:
                    continue
                    
                struct_id_upper = struct_id.upper().strip()
                
                # 跳过重复的
                if struct_id_upper in unique_ids:
                    continue
                    
                unique_ids.append(struct_id_upper)
                
                # 分类
                if len(struct_id_upper) == 4 and struct_id_upper[0].isdigit():
                    pdb_ids.append(struct_id_upper)
                elif struct_id_upper.startswith('EMD-') or (re.match(r'^\d+$', struct_id_upper) and 3 <= len(struct_id_upper) <= 6):
                    emdb_id = f"EMD-{struct_id_upper.replace('EMD-', '')}" if not struct_id_upper.startswith('EMD-') else struct_id_upper
                    emdb_ids.append(emdb_id)
                else:
                    logger.warning(f"无法识别的结构ID格式: {struct_id}")
            
            logger.info(f"分类结果: 唯一ID={len(unique_ids)}, PDB={len(pdb_ids)}, EMDB={len(emdb_ids)}")
            
            # 结果容器
            from_local = []  # 从本地缓存和数据库获取
            from_api = []    # 从API获取的新数据
            failed_ids = []  # 获取失败的ID
            
            # 第一步：如果不强制更新，先尝试从本地获取（缓存 + 数据库）
            if not force_update and use_cache:
                # 批量从缓存/数据库获取
                local_results = self.batch_get_structures(unique_ids, use_cache=True)
                
                # 统计本地获取的结果
                local_found = 0
                for struct_id, structure in local_results.items():
                    if structure:
                        # 标记为本地获取
                        structure['_source'] = 'local_cache'
                        structure['_is_old_data'] = False  # 本地缓存的数据被认为是有效的
                        from_local.append(structure)
                        local_found += 1
                    else:
                        # 本地没有找到，需要从API获取
                        failed_ids.append(struct_id)
                
                logger.info(f"本地获取: {local_found}/{len(unique_ids)} 个结构")
                
                # 如果所有结构都从本地获取到了，直接返回
                if local_found == len(unique_ids):
                    process_time = time.time() - start_time
                    
                    return {
                        'from_local': from_local,
                        'from_api': [],
                        'failed_ids': [],
                        'stats': {
                            'total_requested': len(unique_ids),
                            'from_local': local_found,
                            'from_api': 0,
                            'failed': 0,
                            'success_rate': 100.0,
                            'data_updated': False,
                            'cache_hit_rate': 100.0,
                            'process_time': process_time
                        }
                    }
            else:
                # 强制更新或禁用缓存，全部标记为需要从API获取
                failed_ids = unique_ids.copy()
            
            # 第二步：如果有需要从API获取的结构，尝试获取
            if failed_ids and (force_update or not use_cache):
                logger.info(f"需要从API获取: {len(failed_ids)} 个结构")
                
                # 重新分类需要从API获取的ID
                pdb_to_fetch = []
                emdb_to_fetch = []
                
                for struct_id in failed_ids:
                    if len(struct_id) == 4 and struct_id[0].isdigit():
                        pdb_to_fetch.append(struct_id)
                    elif struct_id.startswith('EMD-'):
                        emdb_to_fetch.append(struct_id)
                
                logger.info(f"API获取分类: PDB={len(pdb_to_fetch)}, EMDB={len(emdb_to_fetch)}")
                
                # 如果有结构管理器可用，尝试从API获取
                if HAS_STRUCTURE_MANAGER and (pdb_to_fetch or emdb_to_fetch):
                    try:
                        # 使用单例获取结构管理器
                        from core.structure_manager import get_structure_metadata_fetcher
                        
                        fetcher = get_structure_metadata_fetcher()
                        
                        # 批量从API获取元数据
                        all_to_fetch = pdb_to_fetch + emdb_to_fetch
                        pdb_metadata, emdb_metadata = fetcher.fetch_all_metadata(
                            all_to_fetch,
                            use_cache=False,  # API调用不使用缓存
                            save_to_offline_db=True,
                            force_update=True,
                            cleanup_old_data=True
                        )
                        
                        # 处理获取到的PDB元数据
                        api_success = 0
                        api_failed = []
                        
                        for pdb_id in pdb_to_fetch:
                            try:
                                if pdb_id in pdb_metadata:
                                    meta = pdb_metadata[pdb_id]
                                    
                                    # 构建结构数据
                                    structure_data = self._convert_pdb_metadata_to_structure(meta, pdb_id)
                                    structure_data['_source'] = 'api_new'
                                    structure_data['_is_old_data'] = False
                                    from_api.append(structure_data)
                                    api_success += 1
                                    
                                    # 从失败列表中移除
                                    if pdb_id in failed_ids:
                                        failed_ids.remove(pdb_id)
                                else:
                                    api_failed.append(pdb_id)
                            except Exception as e:
                                logger.error(f"处理PDB {pdb_id} 元数据失败: {e}")
                                api_failed.append(pdb_id)
                        
                        # 处理获取到的EMDB元数据
                        for emdb_id in emdb_to_fetch:
                            try:
                                if emdb_id in emdb_metadata:
                                    meta = emdb_metadata[emdb_id]
                                    
                                    # 构建结构数据
                                    structure_data = self._convert_emdb_metadata_to_structure(meta, emdb_id)
                                    structure_data['_source'] = 'api_new'
                                    structure_data['_is_old_data'] = False
                                    from_api.append(structure_data)
                                    api_success += 1
                                    
                                    # 从失败列表中移除
                                    if emdb_id in failed_ids:
                                        failed_ids.remove(emdb_id)
                                else:
                                    api_failed.append(emdb_id)
                            except Exception as e:
                                logger.error(f"处理EMDB {emdb_id} 元数据失败: {e}")
                                api_failed.append(emdb_id)
                        
                        # 将API获取失败的结构ID添加到失败列表
                        failed_ids.extend(api_failed)
                        
                        logger.info(f"API获取结果: 成功={api_success}, 失败={len(api_failed)}")
                        
                    except ImportError as e:
                        logger.warning(f"无法导入结构管理器: {e}")
                    except Exception as e:
                        logger.error(f"从API获取结构数据失败: {e}")
            
            # 第三步：合并结果并更新缓存
            final_results = []
            
            # 首先添加本地获取的结果
            final_results.extend(from_local)
            
            # 然后添加API获取的新结果
            final_results.extend(from_api)
            
            # 如果启用了缓存，将API获取的数据保存到缓存
            if use_cache and from_api:
                for structure in from_api:
                    struct_id = structure.get('id')
                    if struct_id:
                        # 更新内存缓存
                        with self._lock:
                            self._structure_cache[struct_id] = structure.copy()
                            self._structure_cache_ttl[struct_id] = time.time() + self._cache_ttl_seconds
            
            # 构建统计信息
            process_time = time.time() - start_time
            total_found = len(from_local) + len(from_api)
            
            stats = {
                'total_requested': len(unique_ids),
                'from_local': len(from_local),
                'from_api': len(from_api),
                'failed': len(failed_ids),
                'success_rate': total_found / max(len(unique_ids), 1) * 100,
                'data_updated': len(from_api) > 0,
                'cache_hit_rate': len(from_local) / max(len(unique_ids), 1) * 100,
                'process_time': process_time,
                'cache_stats': self.get_cache_stats() if use_cache else None
            }
            
            logger.info(f"批量获取完成: 本地={len(from_local)}, API={len(from_api)}, "
                    f"失败={len(failed_ids)}, 时间={process_time:.2f}s")
            
            return {
                'from_local': from_local,
                'from_api': from_api,
                'failed_ids': failed_ids,
                'stats': stats
            }
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"批量获取结构数据失败: {e}", exc_info=True)
            
            return {
                'from_local': [],
                'from_api': [],
                'failed_ids': structure_ids,
                'stats': {
                    'total_requested': len(structure_ids),
                    'from_database': 0,
                    'from_api': 0,
                    'failed': len(structure_ids),
                    'success_rate': 0,
                    'data_updated': False,
                    'error': str(e),
                    'process_time': process_time
                }
            }
    
    def _convert_pdb_metadata_to_structure(self, metadata, pdb_id: str) -> Dict[str, Any]:
        """将PDB元数据转换为结构数据"""
        structure_data = {
            'id': pdb_id,
            'type': 'pdb',
            'title': getattr(metadata, 'title', f"PDB {pdb_id}"),
            'resolution': getattr(metadata, 'resolution', None),
            'method': getattr(metadata, 'method', 'X-ray crystallography'),
            'deposition_date': getattr(metadata, 'deposition_date', None),
            'release_date': getattr(metadata, 'release_date', None),
            'organism': getattr(metadata, 'organism', 'Unknown'),
            'expression_system': getattr(metadata, 'expression_system', ''),
            'expression_system_strain': getattr(metadata, 'expression_system_strain', ''),
            'gene': getattr(metadata, 'gene', ''),
            'protein_name': getattr(metadata, 'protein_name', ''),
            'authors': getattr(metadata, 'authors', []),
            'citation': getattr(metadata, 'citation', ''),
            'citation_count': getattr(metadata, 'citation_count', 0),
            'related_ids': getattr(metadata, 'related_emdb_ids', []),
            'uniprot_ids': getattr(metadata, 'uniprot_ids', [])
        }
        
        # 清理空值
        structure_data = {k: v for k, v in structure_data.items() if v is not None and v != ''}
        
        return structure_data
    
    def _convert_emdb_metadata_to_structure(self, metadata, emdb_id: str) -> Dict[str, Any]:
        """将EMDB元数据转换为结构数据"""
        # 安全地获取属性
        method_value = getattr(metadata, 'method', getattr(metadata, 'technique', 'Cryo-EM'))
        structure_data = {
            'id': emdb_id,
            'type': 'emdb',
            'title': getattr(metadata, 'title', f"EMDB {emdb_id}"),
            'resolution': getattr(metadata, 'resolution', None),
            'method': method_value,
            'deposition_date': getattr(metadata, 'deposition_date', None),
            'release_date': getattr(metadata, 'map_release_date', None),
            'organism': getattr(metadata, 'organism', 'Unknown'),
            'expression_system': getattr(metadata, 'expression_system', ''),
            'expression_system_strain': getattr(metadata, 'expression_system_strain', ''),
            'gene': getattr(metadata, 'gene_name', ''),
            'protein_name': getattr(metadata, 'supramolecule_name', ''),
            'authors': getattr(metadata, 'authors', []),
            'citation': getattr(metadata, 'citation', ''),
            'citation_count': getattr(metadata, 'citation_count', 0),
            'related_ids': getattr(metadata, 'related_pdb_ids', []),
            'uniprot_ids': getattr(metadata, 'uniprot_ids', [])
        }
        
        # 清理空值
        structure_data = {k: v for k, v in structure_data.items() if v is not None and v != ''}
        
        return structure_data

    def upgrade_database_schema(self) -> bool:
        """升级数据库表结构到版本3（删除所有无用表）"""
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # 1. 检查并升级 structures 表（现有逻辑）
                cursor.execute("PRAGMA table_info(structures)")
                columns = [row[1] for row in cursor.fetchall()]
                
                new_columns = [
                    ('uniprot_ids', 'TEXT'),
                    ('molecular_weight', 'REAL'),
                    ('polymer_count', 'INTEGER'),
                    ('group_ids', 'TEXT')
                ]
                
                for column_name, column_type in new_columns:
                    if column_name not in columns:
                        logger.info(f"添加字段 {column_name} 到 structures 表")
                        cursor.execute(f"ALTER TABLE structures ADD COLUMN {column_name} {column_type}")
                
                # 2. 迁移并移除 metadata_json 字段
                if 'metadata_json' in columns:
                    logger.info("检测到 metadata_json 字段，迁移数据并移除该字段")
                    self._migrate_and_remove_metadata_json(cursor)
                
                # 3. 检查并创建 structure_entities 表（现有逻辑）
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='structure_entities'")
                if not cursor.fetchone():
                    logger.info("创建 structure_entities 表")
                    cursor.execute('''
                    CREATE TABLE structure_entities (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        structure_id TEXT NOT NULL,
                        entity_id INTEGER NOT NULL,
                        molecule_type TEXT,
                        molecule_name TEXT,
                        gene_names TEXT,
                        length INTEGER,
                        weight REAL,
                        number_of_copies INTEGER,
                        in_chains TEXT,
                        sequence TEXT,
                        start_residue INTEGER,
                        end_residue INTEGER,
                        source_organism TEXT,
                        expression_host TEXT,
                        entity_data TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (structure_id) REFERENCES structures(id) ON DELETE CASCADE,
                        UNIQUE(structure_id, entity_id)
                    )
                    ''')
                    
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_entity_structure ON structure_entities(structure_id)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_entity_type ON structure_entities(molecule_type)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_entity_organism ON structure_entities(source_organism)')
                
                # 4. 检查并创建 uniprot_structure_mapping 表（现有逻辑）
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='uniprot_structure_mapping'")
                if not cursor.fetchone():
                    logger.info("创建 uniprot_structure_mapping 表")
                    cursor.execute('''
                    CREATE TABLE uniprot_structure_mapping (
                        uniprot_id TEXT NOT NULL,
                        structure_id TEXT NOT NULL,
                        protein_name TEXT,
                        gene_name TEXT,
                        confidence REAL DEFAULT 1.0,
                        source TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (uniprot_id, structure_id)
                    )
                    ''')
                    
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_uniprot_id ON uniprot_structure_mapping(uniprot_id)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_uniprot_structure ON uniprot_structure_mapping(structure_id)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_uniprot_confidence ON uniprot_structure_mapping(confidence)')
                
                # 5. 删除所有无用表
                tables_to_drop = [
                    'structure_metadata',          # 主表
                    'structure_groups',            # 分组表
                    'structure_metadata_backup',   # 备份表
                    'structure_groups_backup'      # 备份表
                ]
                
                for table_name in tables_to_drop:
                    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                    if cursor.fetchone():
                        logger.info(f"删除表: {table_name}")
                        cursor.execute(f'DROP TABLE IF EXISTS {table_name}')
                
                # 6. 清理相关的方法和引用
                # 需要更新 schema_version 表
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
                if not cursor.fetchone():
                    # 创建 schema_version 表
                    cursor.execute('''
                    CREATE TABLE schema_version (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        version INTEGER NOT NULL,
                        description TEXT,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    ''')
                
                # 7. 更新版本号到3
                cursor.execute("DELETE FROM schema_version")  # 清空旧记录
                cursor.execute('''
                INSERT INTO schema_version (version, description) 
                VALUES (?, ?)
                ''', (3, '版本3：删除structure_metadata和structure_groups表，清理冗余数据'))
                
                conn.commit()
                conn.close()
                
                logger.info("✅ 数据库升级到版本3完成，清理了所有无用表")
                return True
                
        except Exception as e:
            logger.error(f"升级数据库失败: {e}", exc_info=True)
            return False

    def _migrate_and_remove_metadata_json(self, cursor):
        """迁移 metadata_json 字段数据并移除该字段"""
        try:
            # 1. 迁移数据到新字段
            self._migrate_metadata_json_field(cursor)
            
            # 2. 移除 metadata_json 字段（SQLite不支持直接删除列，需要重建表）
            self._rebuild_structures_table_without_metadata_json(cursor)
            
        except Exception as e:
            logger.error(f"迁移和移除metadata_json字段失败: {e}")

    def _rebuild_structures_table_without_metadata_json(self, cursor):
        """重建structures表，移除metadata_json字段"""
        try:
            # 1. 创建临时表（不含metadata_json、has_metadata、metadata_hash）
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS structures_new (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT,
                resolution REAL,
                method TEXT,
                deposition_date TEXT,
                release_date TEXT,
                organism TEXT,
                expression_system TEXT,
                expression_system_strain TEXT,
                gene TEXT,
                protein_name TEXT,
                authors TEXT,
                citation_count INTEGER,
                related_ids TEXT,
                uniprot_ids TEXT,
                molecular_weight REAL,
                polymer_count INTEGER,
                group_ids TEXT,
                last_updated TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # 2. 从旧表复制数据（跳过不需要的字段）
            cursor.execute('''
            INSERT INTO structures_new 
            (id, type, title, resolution, method, deposition_date, release_date,
            organism, expression_system, expression_system_strain, gene, protein_name,
            authors, citation_count, related_ids, uniprot_ids, molecular_weight,
            polymer_count, group_ids, last_updated, created_at)
            SELECT 
                id, type, title, resolution, method, deposition_date, release_date,
                organism, expression_system, expression_system_strain, gene, protein_name,
                authors, citation_count, related_ids, uniprot_ids, molecular_weight,
                polymer_count, group_ids, last_updated, created_at
            FROM structures
            ''')
            
            # 3. 删除旧表，重命名新表
            cursor.execute('DROP TABLE structures')
            cursor.execute('ALTER TABLE structures_new RENAME TO structures')
            
            # 4. 重新创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_type ON structures(type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_organism ON structures(organism)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_gene ON structures(gene)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_protein ON structures(protein_name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_resolution ON structures(resolution)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_method ON structures(method)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_deposition_date ON structures(deposition_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_structure_release_date ON structures(release_date)')
            
            logger.info("✅ 重建structures表完成，移除了metadata_json等字段")
            
        except Exception as e:
            logger.error(f"重建structures表失败: {e}")
  
# ---------- 增强结构管理器 ----------
class EnhancedStructureManager:
    """增强的结构管理器，提供更高级的API"""
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, db_path: str = "structure_offline.db", cache_dir: str = "structure_cache"):
        # 防止重复初始化 - 添加实例变量检查
        if hasattr(self, '_initialized') and self._initialized:
            logger.debug(f"EnhancedStructureManager 已经初始化过，跳过重新初始化")
            return

        try:
            logger.info(f"🔄 正在初始化 EnhancedStructureManager: {db_path}")

            # 验证参数类型
            if not isinstance(db_path, str):
                raise TypeError(f"db_path 必须是字符串，但收到: {type(db_path)}")
            if not isinstance(cache_dir, str):
                raise TypeError(f"cache_dir 必须是字符串，但收到: {type(cache_dir)}")

            # 确保目录存在
            import os
            os.makedirs(cache_dir, exist_ok=True)

            # 使用全局单例获取数据库实例
            logger.info(f"🔄 正在获取 StructureOfflineDatabase 单例...")
            self.database = SimpleSingleton.get_instance(StructureOfflineDatabase, db_path, cache_dir)
            logger.info(f"✅ StructureOfflineDatabase 单例获取成功")

            # 标记为已初始化
            self._initialized = True
            logger.info(f"✅ EnhancedStructureManager 初始化完成: {db_path}")

        except Exception as e:
            import traceback
            logger.error(f"EnhancedStructureManager 初始化失败: {e}")
            traceback.print_exc()
            self._initialized = False

        try:
            # 创建 ProteinNameMapper 的实例，挂载到 self 上
            self.protein_mapper = ProteinNameMapper()
            logger.info("✅ ProteinNameMapper 已在 EnhancedStructureManager 中初始化")
        except Exception as e:
            logger.warning(f"ProteinNameMapper 初始化失败: {e}")
            self.protein_mapper = None

    def find_protein_structures(self, protein_name: str) -> Dict[str, Any]:
        """根据蛋白质名称查找相关的结构ID"""
        structure_ids = []
        
        # --- 修复：安全获取 protein_mapper，防止属性缺失报错 ---
        # 使用 getattr 代替直接访问 self.protein_mapper
        mapper = getattr(self, 'protein_mapper', None)
        
        if mapper:
            try:
                structure_ids = self.protein_mapper.find_structures_by_protein_name(protein_name)
            except Exception as e:
                logger.warning(f"通过 ProteinMapper 查找失败: {e}")
        
        # 策略2: 如果映射为空，直接查询数据库表 (兜底)
        if not structure_ids:
            try:
                # 检查表是否存在
                if hasattr(self, 'conn') and self.conn:
                    cursor = self.conn.cursor()
                    cursor.execute('''
                        SELECT structure_id FROM uniprot_structure_mapping
                        WHERE protein_name = ? OR gene_name = ?
                    ''', (protein_name, protein_name))
                    rows = cursor.fetchall()
                    structure_ids = [row[0] for row in rows]
            except Exception as e:
                logger.warning(f"直接查询 uniprot_structure_mapping 失败: {e}")
        
        # 分类 ID
        pdb_ids = []
        emdb_ids = []
        
        for sid in structure_ids:
            sid_upper = str(sid).upper()
            # 判断是否为 EMDB
            if sid_upper.startswith('EMD-'):
                emdb_ids.append(sid_upper)
            # 判断是否为 PDB (标准 PDB 为 4 位，首位数字，其余字母数字)
            elif re.match(r'^[0-9][A-Z0-9]{3}$', sid_upper):
                pdb_ids.append(sid_upper)
            # 兜底：只要长度为4且全是字母数字
            elif len(sid_upper) == 4 and re.match(r'^[A-Z0-9]+$', sid_upper):
                pdb_ids.append(sid_upper)
        
        return {
            "pdb_ids": pdb_ids,
            "emdb_ids": emdb_ids,
            "total": len(pdb_ids) + len(emdb_ids)
        }

    def get_structure(self, structure_id: str, simplify: bool = True) -> Optional[Dict[str, Any]]:
        """获取结构数据"""
        try:
            if hasattr(self, 'database') and self.database:
                return self.database.get_structure(structure_id, simplify=simplify)
            else:
                logger.warning("数据库未初始化，无法获取结构数据")
                return None
        except Exception as e:
            logger.error(f"获取结构数据失败: {e}")
            return None

    def analyze_protein_for_question(self, question: str) -> Dict[str, Any]:
        """
        为问题分析相关的蛋白质信息
        
        参数:
            question: 用户问题文本
            
        返回:
            {
                "success": True/False,
                "protein_names": ["TCR", ...],
                "structures_info": {...},
                "message": "..."
            }
        """
        # 1. 提取蛋白质名称 (优化正则，减少误报)
        # 原正则 \b[A-Z]{2,}\b 会匹配 "AND", "THE" 等单词
        # 改进：要求包含数字，或者是常见的生物学命名风格
        import re
        protein_names = set()
        
        # 策略A: 提取带有数字的 (如 TCR, CD3, EGFR, Vγ9Vδ2 中的 γ9)
        # 匹配模式：大写字母 + 数字 (如 GPR158)
        patterns = [
            r'\b[A-Z]{2,}[0-9]+\b',       # GPR158, CD4
            r'V[αδγεζσν\w]+[0-9]*',        # Vγ9, Vδ2 (包含希腊字母)
            r'[A-Z]{2,}-[A-Z]{2,}',       # IL-2, TNF-α
            r'(?:[A-Z]{2,}|[A-Z]\d{1,3})[A-Z]*\b' # 纯大写缩写，但尽量匹配稍长的组合
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, question, re.IGNORECASE)
            for m in matches:
                # 简单的过滤：排除常见的英文单词
                if m.upper() not in ['THE', 'AND', 'OF', 'IN', 'IS', 'ARE', 'THIS', 'THAT', 'WITH', 'FOR', 'NOT']:
                    # 标准化希腊字母
                    normalized = m.replace('α', 'a').replace('β', 'b').replace('γ', 'g').replace('δ', 'd')
                    protein_names.add(normalized.upper())
        
        # 策略B: 针对常见蛋白名的硬编码匹配 (确保不漏掉)
        # 这样可以匹配 "Vγ9Vδ2 TCR" 中的 TCR
        known_proteins = ['TCR', 'MHC', 'CD3', 'CD4', 'CD8', 'PD1', 'PDL1', 'EGFR', 'HER2', 'GPR']
        for kp in known_proteins:
            if kp.upper() in question.upper():
                protein_names.add(kp)
                
        protein_names = list(protein_names)
        
        # 2. 为每个蛋白质名称查找结构
        structures_info = {}
        for protein in protein_names:
            # 使用刚才添加的方法
            try:
                protein_info = self.find_protein_structures(protein)
                if protein_info and protein_info.get('total', 0) > 0:
                    structures_info[protein] = protein_info
            except Exception as e:
                logger.warning(f"查找 {protein} 结构失败: {e}")
        
        # 3. 构建返回结果
        success = bool(structures_info)
        total_found = sum(info.get('total', 0) for info in structures_info.values())
        
        return {
            "success": success,
            "protein_names": protein_names,
            "structures_info": structures_info,
            "total_structures": total_found,
            "message": f"分析了 {len(protein_names)} 个蛋白质，找到 {total_found} 个相关结构。" if success else "未检测到明确的蛋白质名称或未找到相关结构。"
        }

    def save_relationship(self, relationship: Dict[str, Any]) -> bool:
        """保存结构关系到数据库"""
        return self.database.save_structure_relationship(relationship)
    
    def get_structure_relationships(self, structure_id: str = None) -> List[Dict[str, Any]]:
        """获取结构关系"""
        return self.database.get_structure_relationships(structure_id)

    def save_uniprot_entity_mapping(self, mapping_data: Dict) -> bool:
        """保存UniProt-实体映射（代理方法）"""
        return self.database.save_uniprot_entity_mapping(mapping_data)
    
    def find_entities_for_uniprot(self, uniprot_id: str) -> List[Dict]:
        """查找UniProt ID对应的所有实体（代理方法）"""
        return self.database.find_entities_for_uniprot(uniprot_id)
    
    def find_uniprot_for_entity(self, pdb_id: str, entity_id: str) -> List[Dict]:
        """查找实体对应的UniProt ID（代理方法）"""
        return self.database.find_uniprot_for_entity(pdb_id, entity_id)
    
    def get_uniprot_entity_mapping_stats(self) -> Dict[str, Any]:
        """获取UniProt-实体映射统计信息（代理方法）"""
        return self.database.get_uniprot_entity_mapping_stats()

    def get_structures_for_literature(self, literature_id: int) -> List[Dict[str, Any]]:
        """获取文献相关的所有结构（代理方法）"""
        return self.database.get_structures_for_literature(literature_id)

    def update_structure_metadata(self, structure_id: str, metadata: Dict[str, Any]) -> bool:
        """更新结构元数据（避免重复）"""
        try:
            # 清理metadata，移除冗余的group_info
            cleaned_metadata = metadata.copy()
            
            # 如果group_info中包含完整的primary_structure数据，简化它
            if 'group_info' in cleaned_metadata and isinstance(cleaned_metadata['group_info'], dict):
                group_info = cleaned_metadata['group_info']
                
                # 简化primary_structure，只保留ID
                if 'primary_structure' in group_info and isinstance(group_info['primary_structure'], dict):
                    primary = group_info['primary_structure']
                    if 'id' in primary:
                        # 只保留必要信息
                        group_info['primary_structure'] = {
                            'id': primary['id'],
                            'type': primary.get('type'),
                            'title': primary.get('title', '')[:100]  # 只保留前100个字符
                        }
            
            # 确定结构类型
            if len(structure_id) == 4:
                struct_type = StructureType.PDB
            elif structure_id.startswith('EMD-'):
                struct_type = StructureType.EMDB
            else:
                logger.warning(f"无法确定结构类型: {structure_id}")
                return False
            
            return self.database.save_structure(cleaned_metadata, struct_type)
            
        except Exception as e:
            logger.error(f"更新结构元数据失败: {e}")
            return False
    
    def get_structure_with_all_info(self, structure_id: str) -> Optional[Dict[str, Any]]:
        """获取结构及其所有相关信息"""
        return self.database.get_structure_with_relationships(structure_id)
    
    def find_related_structures(self, structure_id: str, max_depth: int = 2) -> Dict[str, Any]:
        """查找相关结构"""
        return self.database.get_related_structures(structure_id, max_depth)
    
    def hybrid_search(self, query: str, search_mode: str = "auto", top_k: int = 5) -> Dict[str, Any]:
        """
        混合搜索：结合文本和向量搜索
        参数说明：
            query: 搜索查询
            search_mode: 搜索模式 ("auto", "exact", "fuzzy")，当前实现可忽略
            top_k: 返回结果数量
        """
        results = []
        try:
            pass
        except Exception as e:
            logger.error(f"混合搜索失败: {e}")
            
        return {
            "success": True if results else False,
            "results": results,
            "query": query
        }
    
    def answer_question(self, question: str) -> Dict[str, Any]:
        """回答问题"""
        return self.database.answer_question(question)
    
    def get_database_stats(self) -> Dict[str, Any]:
        """获取数据库统计"""
        return self.database.get_database_stats()
    
    def get(self, structure_id: str) -> Optional[Dict[str, Any]]:
        """A generic get method for fetching structure data"""
        return self.get_structure_with_all_info(structure_id)
    
    def batch_get_or_fetch_structures(self, structure_ids, **kwargs):
        """批量获取结构数据 - 代理方法"""
        return self.database.batch_get_or_fetch_structures(structure_ids, **kwargs)
    
    def get_or_fetch_structure(self, structure_id: str, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """获取或获取单个结构数据（自动清理）"""
        try:
            # 规范化结构ID
            struct_id_upper = structure_id.upper()
            
            # 首先尝试从数据库获取
            structure = self.database.get_structure(struct_id_upper)
            
            if structure:
                structure['_source'] = 'database'
                return structure
            
            # 如果数据库中没有，尝试从API获取
            try:
                from core.structure_manager import StructureMetadataFetcher
                
                fetcher = StructureMetadataFetcher()
                
                # 确定类型并获取
                if len(struct_id_upper) == 4:
                    metadata = fetcher.fetch_pdb_metadata(struct_id_upper, use_cache=False)
                    struct_type = 'pdb'
                elif struct_id_upper.startswith('EMD-'):
                    metadata = fetcher.fetch_emdb_metadata(struct_id_upper, use_cache=False)
                    struct_type = 'emdb'
                else:
                    logger.error(f"无法识别的结构ID格式: {structure_id}")
                    return None
                
                if metadata:
                    # 转换为字典
                    if hasattr(metadata, '__dict__'):
                        metadata_dict = metadata.__dict__
                    else:
                        metadata_dict = metadata
                    
                    # 添加必要字段
                    metadata_dict['id'] = struct_id_upper
                    metadata_dict['type'] = struct_type
                    metadata_dict['_source'] = 'api'
                    
                    # 保存到数据库（会触发自动清理）
                    if struct_type == 'pdb':
                        saved = self.database.save_structure(metadata_dict, StructureType.PDB)
                    else:
                        saved = self.database.save_structure(metadata_dict, StructureType.EMDB)
                    
                    if saved:
                        # 重新从数据库获取（确保是清理后的版本）
                        return self.database.get_structure(struct_id_upper)
            
            except ImportError as e:
                logger.warning(f"无法导入StructureMetadataFetcher: {e}")
            except Exception as e:
                logger.error(f"从API获取结构 {struct_id_upper} 失败: {e}")
            
            return None
            
        except Exception as e:
            logger.error(f"获取结构 {structure_id} 失败: {e}")
            return None
        
    def batch_save_structures(self, structure_data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        批量保存结构数据到数据库
        """
        try:
            success_count = 0
            failed_count = 0
            
            for structure_data in structure_data_list:
                try:
                    structure_id = structure_data.get('id')
                    if not structure_id:
                        logger.warning("结构数据缺少ID，跳过")
                        failed_count += 1
                        continue
                    
                    # 确定结构类型
                    if len(structure_id) == 4 and structure_id[0].isdigit():
                        struct_type = StructureType.PDB
                    elif structure_id.startswith('EMD-'):
                        struct_type = StructureType.EMDB
                    else:
                        logger.warning(f"无法确定结构 {structure_id} 的类型")
                        failed_count += 1
                        continue
                    
                    # 保存到数据库
                    saved = self.database.save_structure(structure_data, struct_type)
                    if saved:
                        success_count += 1
                        logger.debug(f"批量保存结构 {structure_id} 成功")
                    else:
                        failed_count += 1
                        logger.warning(f"批量保存结构 {structure_id} 失败")
                        
                except Exception as e:
                    logger.error(f"批量保存单个结构失败: {e}")
                    failed_count += 1
            
            logger.info(f"批量保存完成: 成功={success_count}, 失败={failed_count}")
            
            return {
                'success': True,
                'success_count': success_count,
                'failed_count': failed_count,
                'total': len(structure_data_list),
                'success_rate': success_count / max(len(structure_data_list), 1) * 100
            }
            
        except Exception as e:
            logger.error(f"批量保存结构数据失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'success_count': 0,
                'failed_count': len(structure_data_list),
                'total': len(structure_data_list),
                'success_rate': 0
            }
    
    def get_structure_with_validation(self, structure_id: str) -> Dict[str, Any]:
        """获取结构数据并进行验证"""
        structure = self.get_structure_with_all_info(structure_id)
        
        if not structure:
            return {
                'success': False,
                'structure_id': structure_id,
                'error': 'Structure not found'
            }
        
        # 检查数据质量
        validation_result = self._validate_single_structure(structure)
        
        return {
            'success': True,
            'structure': structure,
            'validation': validation_result,
            'data_sources': structure.get('_data_sources', {})
        }
    
    def _validate_single_structure(self, structure: Dict[str, Any]) -> Dict[str, Any]:
        """验证单个结构数据"""
        issues = []
        
        # 检查重复字段
        for key in list(structure.keys()):
            if key.endswith('_json') and key[:-5] in structure:
                issues.append({
                    'type': 'duplicate_field',
                    'fields': [key, key[:-5]],
                    'description': f'字段 {key[:-5]} 以不同形式重复存储'
                })
        
        # 检查嵌套的 metadata_json
        if 'metadata_json' in structure and isinstance(structure['metadata_json'], dict):
            if 'metadata_json' in structure['metadata_json']:
                issues.append({
                    'type': 'nested_metadata',
                    'description': '检测到多层嵌套的 metadata_json'
                })
        
        return {
            'has_issues': len(issues) > 0,
            'issues': issues,
            'field_count': len(structure),
            'core_field_count': sum(1 for k in structure.keys() 
                                  if k in ['id', 'type', 'title', 'resolution', 'method', 
                                           'organism', 'gene', 'protein_name'])
        }

# ---------- 全局函数 ----------
def create_entity_uniprot_mapping(uniprot_id: str, pdb_id: str, entity_id: str, 
                                  match_score: float = 0.0, match_evidence: str = "",
                                  entity_info: Dict = None, uniprot_info: Dict = None,
                                  source: str = "manual") -> Dict:
    """
    创建UniProt-实体映射数据
    
    参数:
        uniprot_id: UniProt ID
        pdb_id: PDB ID
        entity_id: 实体ID
        match_score: 匹配分数
        match_evidence: 匹配证据
        entity_info: 实体信息
        uniprot_info: UniProt信息
        source: 来源
        
    返回:
        标准化的映射数据字典
    """
    return {
        'uniprot_id': uniprot_id,
        'pdb_id': pdb_id,
        'entity_id': entity_id,
        'match_score': match_score,
        'match_evidence': match_evidence,
        'entity_info': entity_info or {},
        'uniprot_info': uniprot_info or {},
        'source': source,
        'created_at': datetime.now().isoformat()
    }

# 添加匹配算法函数
def match_entity_with_uniprot(entity_data: Dict, uniprot_data: Dict) -> Dict[str, Any]:
    """
    匹配实体与UniProt数据，计算匹配分数
    
    参数:
        entity_data: 实体数据，包含 sequence, molecule_name, gene_names 等
        uniprot_data: UniProt数据，包含 sequence, protein_name, gene_names 等
        
    返回:
        匹配结果，包含 score 和 evidence
    """
    result = {
        'match_score': 0.0,
        'match_evidence': [],
        'details': {}
    }
    
    try:
        # 1. 序列匹配（最高优先级）
        entity_sequence = entity_data.get('sequence', '')
        uniprot_sequence = uniprot_data.get('sequence', '')
        
        if entity_sequence and uniprot_sequence:
            # 简化的序列匹配逻辑
            if entity_sequence in uniprot_sequence:
                result['match_score'] += 0.7
                result['match_evidence'].append(f"序列匹配: 实体序列包含在UniProt序列中")
                result['details']['sequence_match'] = True
                result['details']['sequence_length_ratio'] = len(entity_sequence) / len(uniprot_sequence)
            
            # 序列相似度计算（可选）
            elif len(entity_sequence) > 10:
                import difflib
                similarity = difflib.SequenceMatcher(
                    None, 
                    entity_sequence[:50], 
                    uniprot_sequence[:50]
                ).ratio()
                result['details']['sequence_similarity'] = similarity
                
                if similarity > 0.8:
                    result['match_score'] += 0.6
                    result['match_evidence'].append(f"序列相似度高: {similarity:.2f}")
        
        # 2. 蛋白质名称匹配
        entity_molecule_names = entity_data.get('molecule_name', [])
        if isinstance(entity_molecule_names, str):
            entity_molecule_names = [entity_molecule_names]
        
        uniprot_protein_name = uniprot_data.get('protein_name', '')
        
        if uniprot_protein_name and entity_molecule_names:
            for name in entity_molecule_names:
                if name and isinstance(name, str) and uniprot_protein_name.lower() in name.lower():
                    result['match_score'] += 0.3
                    result['match_evidence'].append(f"蛋白质名称匹配: {name} 包含 {uniprot_protein_name}")
                    result['details']['name_match'] = True
                    break
        
        # 3. 基因名匹配
        entity_gene_names = entity_data.get('gene_names', [])
        uniprot_gene_names = uniprot_data.get('gene_names', [])
        
        if entity_gene_names and uniprot_gene_names:
            # 规范化基因名（转换为小写，去除空格）
            entity_genes = [g.lower().strip() for g in entity_gene_names if isinstance(g, str)]
            uniprot_genes = [g.lower().strip() for g in uniprot_gene_names if isinstance(g, str)]
            
            common_genes = set(entity_genes) & set(uniprot_genes)
            if common_genes:
                gene_score = 0.2 * len(common_genes)
                result['match_score'] += gene_score
                result['match_evidence'].append(f"基因名匹配: {list(common_genes)}")
                result['details']['gene_matches'] = list(common_genes)
                result['details']['gene_match_count'] = len(common_genes)
        
        # 4. 分子类型匹配
        entity_molecule_type = entity_data.get('molecule_type', '').lower()
        if entity_molecule_type in ['protein', 'polypeptide(l)', 'polypeptide(d)']:
            # 如果是蛋白质类型，增加基础分数
            result['match_score'] += 0.1
            result['match_evidence'].append(f"分子类型匹配: {entity_molecule_type}")
        
        # 确保分数在0-1之间
        result['match_score'] = min(result['match_score'], 1.0)
        
        return result
        
    except Exception as e:
        logger.error(f"实体-UniProt匹配失败: {e}")
        result['match_evidence'].append(f"匹配过程出错: {str(e)}")
        return result
    
def get_enhanced_structure_manager(db_path: str = None, cache_dir: str = "structure_cache"):
    """获取增强的结构管理器实例（使用单例）"""
    # Use data directory path as default
    if db_path is None:
        # Get the data directory
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))  # structure_database.py location
        data_dir = os.path.join(os.path.dirname(current_dir), 'data')
        db_path = os.path.join(data_dir, 'structure_offline.db')
    try:
        # 使用全局单例
        manager = SimpleSingleton.get_instance(EnhancedStructureManager, db_path, cache_dir)
        
        if not hasattr(manager, '_initialized') or not manager._initialized:
            # 如果管理器没有正确初始化，重新创建
            SimpleSingleton.clear_instance(EnhancedStructureManager)
            manager = EnhancedStructureManager(db_path, cache_dir)
            SimpleSingleton._instances[EnhancedStructureManager.__name__] = manager
        
        logger.info(f"✅ 获取EnhancedStructureManager单例实例")
        return manager
        
    except Exception as e:
        logger.error(f"获取增强结构管理器失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_uniprot_mappings_for_entity(pdb_id: str, entity_id: str, structure_db=None) -> List[Dict]:
    """
    获取实体对应的UniProt映射信息
    
    参数:
        pdb_id: PDB ID
        entity_id: 实体ID
        structure_db: 结构数据库管理器
        
    返回:
        UniProt映射列表，按匹配分数排序
    """
    try:
        if not structure_db or not pdb_id or not entity_id:
            return []
        
        # 确保entity_id是字符串
        entity_id_str = str(entity_id)
        
        # 使用结构数据库查询
        if hasattr(structure_db.database, 'find_uniprot_for_entity'):
            mappings = structure_db.database.find_uniprot_for_entity(pdb_id, entity_id_str)
            
            # 按匹配分数排序
            sorted_mappings = sorted(
                mappings, 
                key=lambda x: x.get('match_score', 0), 
                reverse=True
            )
            
            return sorted_mappings
        
        return []
    except Exception as e:
        logger.debug(f"获取实体UniProt映射失败 {pdb_id} 实体 {entity_id}: {e}")
        return []
