# literature_index.py - 修正版

# 1. 先导入标准库
import os, json, logging, re, time, math, hashlib, pickle, threading, uuid, itertools
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Union, Set, Callable
from datetime import datetime
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from enum import Enum
import concurrent.futures
from core.simple_singleton import SimpleSingleton

# 2. 立即设置日志（在最前面）
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)  # 定义 logger

# 3. 然后导入第三方库（条件导入
import numpy as np
from sqlalchemy import or_, and_, text
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
import networkx as nx


# 4. 导入现有模块（使用 logger）
try:
    from core.literature_db import (
        LiteratureEntry, LiteratureStatus, create_literature_session,
        get_literature_entry, search_literature
    )
    HAS_LITERATURE_DB = True
    logger.debug("✅ literature_db 导入成功")
except ImportError as e:
    HAS_LITERATURE_DB = False
    logger.warning(f"literature_db 不可用: {e}")

try:
    from core.literature_parser import StructureIDExtractor
    HAS_PARSER = True
    logger.debug("✅ literature_parser 导入成功")
except ImportError as e:
    HAS_PARSER = False
    logger.warning(f"literature_parser 不可用: {e}")

# 结构管理器（如果存在）
try:
    from core.structure_manager import StructureMetadataFetcher, PDBMetadata, EMDBMetadata
    HAS_STRUCTURE_MANAGER = True
    logger.debug("✅ structure_manager 导入成功")
except ImportError as e:
    HAS_STRUCTURE_MANAGER = False
    logger.warning(f"structure_manager 不可用: {e}")

# 5. 导入 agent_core（现在 logger 已经定义）
try:
    from core.agent_core import (
        get_text_embedding,
        get_batch_embeddings,
        get_embedding_model_info,
        ask_literature_question,
        HAS_AGENT
    )
    HAS_AGENT_CORE = True
    logger.info("✅ agent_core 导入成功，支持AI和嵌入功能")
    
    # 测试嵌入功能是否可用
    try:
        info = get_embedding_model_info()
        logger.info(f"嵌入模型信息: {info}")
    except Exception as e:
        logger.warning(f"嵌入模型信息获取失败: {e}")
        # 但仍然继续，因为其他功能可能可用
        
except ImportError as e:
    HAS_AGENT_CORE = False
    logger.warning(f"agent_core 不可用: {e}")
except Exception as e:
    HAS_AGENT_CORE = False
    logger.warning(f"agent_core 初始化失败: {e}")

# 6. 继续定义类和数据模型...
# ---------- 数据模型 ----------
class EntityType(Enum):
    """实体类型枚举"""
    STRUCTURE = "structure"
    PROTEIN = "protein"
    LITERATURE = "literature"
    AUTHOR = "author"
    JOURNAL = "journal"
    ORGANISM = "organism"
    METHOD = "method"
    KEYWORD = "keyword"
    APPENDIX = "appendix"  # 附录类型

@dataclass
class UnifiedDocument:
    """统一文档表示"""
    doc_id: str
    entity_type: EntityType
    source_id: str  # 原始ID（如PDB ID、文献ID）
    title: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embeddings: Optional[np.ndarray] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，处理枚举序列化"""
        data = asdict(self)
        # 将EntityType枚举转换为字符串
        data['entity_type'] = self.entity_type.value
        # 将numpy数组转换为列表以便JSON序列化
        if self.embeddings is not None:
            data['embeddings'] = self.embeddings.tolist()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UnifiedDocument':
        """从字典创建文档，处理枚举反序列化"""
        # 将字符串转换回EntityType枚举
        if 'entity_type' in data and isinstance(data['entity_type'], str):
            data['entity_type'] = EntityType(data['entity_type'])
        # 将列表转换回numpy数组
        if 'embeddings' in data and isinstance(data['embeddings'], list):
            data['embeddings'] = np.array(data['embeddings'])
        return cls(**data)

@dataclass
class SearchResult:
    """搜索结果"""
    doc_id: str
    entity_type: EntityType
    source_id: str
    title: str
    content: str
    similarity_score: float
    metadata: Dict[str, Any]
    rank: int

# ---------- 向量索引器 ----------
class UnifiedVectorIndexer:
    """统一向量索引器"""
    
    def __init__(self, model_name: Union[str, Dict] = "all-MiniLM-L6-v2", dimension: int = 384):
        # 处理配置字典
        self.config = {}
        
        # 如果 model_name 是字典，提取配置
        if isinstance(model_name, dict):
            self.config = model_name.copy()
            # 从配置中提取模型名称
            if 'model_name' in model_name:
                actual_model_name = model_name['model_name']
            elif 'model' in model_name:
                actual_model_name = model_name['model']
            elif 'embedding_model' in model_name:
                actual_model_name = model_name['embedding_model']  # 新增这一行
            else:
                # 如果字典中没有模型名称，使用默认值
                actual_model_name = "all-MiniLM-L6-v2"
                logger.warning(f"配置字典中没有找到模型名称，使用默认: {actual_model_name}")
        else:
            actual_model_name = str(model_name)
        
        self.model_name = actual_model_name
        self.dimension = dimension
        
        try:
            from core.agent_core import get_text_embedding, get_embedding_model_info
            
            self.embed_func = get_text_embedding
            try:
                model_info = get_embedding_model_info()
                logger.info(f"✅ 使用 agent_core 嵌入模型: {model_info}")
            except Exception as e:
                logger.warning(f"获取嵌入模型信息失败: {e}")
                model_info = {}
                
        except ImportError as e:
            logger.error(f"无法导入 agent_core 嵌入功能: {e}")
            # 回退：生成随机向量
            self.embed_func = lambda text: np.random.randn(self.dimension).astype(np.float32)
        except Exception as e:
            logger.error(f"初始化嵌入功能失败: {e}")
            # 回退：生成随机向量
            self.embed_func = lambda text: np.random.randn(self.dimension).astype(np.float32)
        
        # 向量索引索引
        self.index = None
        self.id_to_doc = {}  # 文档ID到文档的映射
        self.id_to_idx = {}  # 文档ID到向量索引索引的映射
        self.idx_to_id = {}  # 向量索引索引到文档ID的映射
        
        # 结构增强索引
        self.structure_literature_map = {}  # 结构ID -> 文献ID列表
        self.literature_structure_map = {}  # 文献ID -> 结构ID列表
        self.structure_index = {}  # 结构ID -> 结构信息
        
        # 关键词索引
        self.keyword_index = defaultdict(set)  # 关键词 -> 文档ID集合
        self.tfidf_vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
        
        # 从配置中获取缓存目录
        self.cache_dir = Path(self.config.get('cache_dir', 'unified_vector_cache'))
        self.structure_cache_dir = Path(self.config.get('structure_cache_dir', 'structure_cache'))
        
        # 确保目录存在
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.structure_cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载现有数据
        self._load_index_data()
        
        logger.info(f"✅ 统一向量索引器初始化完成 (model: {actual_model_name})")
    
    def _load_index_data(self):
        """加载索引数据"""
        try:
            # 使用绝对路径确保在任何工作目录下都能找到索引文件
            current_dir = Path(__file__).parent
            index_dir = current_dir / "literature_indices"
            logger.info(f"尝试从目录加载索引数据: {index_dir}")
            
            if index_dir.exists():
                logger.info(f"索引目录存在: {index_dir}")
                # 加载统一索引
                index_file = index_dir / "unified_index.json"
                if index_file.exists():
                    logger.info(f"找到统一索引文件: {index_file}")
                    with open(index_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        documents_data = data.get('documents', {})
                        logger.info(f"统一索引文件包含 {len(documents_data)} 个文档")
                        
                        for doc_id, doc_dict in documents_data.items():
                            try:
                                doc = UnifiedDocument.from_dict(doc_dict)
                                self.id_to_doc[doc_id] = doc
                            except Exception as e:
                                logger.error(f"加载文档 {doc_id} 失败: {e}")
                        logger.info(f"✅ 加载统一索引: {len(self.id_to_doc)} 个文档")
                
                # 加载结构映射
                structure_file = index_dir / "structure_mappings.json"
                if structure_file.exists():
                    logger.info(f"找到结构映射文件: {structure_file}")
                    with open(structure_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.structure_literature_map = data.get('structure_literature_map', {})
                        self.literature_structure_map = data.get('literature_structure_map', {})
                        logger.info(f"✅ 加载结构映射: {len(self.structure_literature_map)} 个结构")
                
                # 加载向量索引索引
                    logger.info(f"✅ 加载向量索引索引: {self.index.ntotal} 个向量")
                
                # 加载ID映射
                mapping_file = index_dir / "id_mappings.json"
                if mapping_file.exists():
                    logger.info(f"找到ID映射文件: {mapping_file}")
                    with open(mapping_file, 'r', encoding='utf-8') as f:
                        mappings = json.load(f)
                        self.id_to_idx = mappings.get('id_to_idx', {})
                        self.idx_to_id = {int(v): k for k, v in self.id_to_idx.items()}
                        logger.info(f"✅ 加载ID映射: {len(self.id_to_idx)} 个映射")
            else:
                logger.warning(f"索引目录不存在: {index_dir}")
            
        except Exception as e:
            logger.error(f"加载索引数据失败: {e}")
    
    def _save_index_data(self):
        """保存索引数据"""
        try:
            # 使用绝对路径确保在任何工作目录下都能找到索引文件
            current_dir = Path(__file__).parent
            index_dir = current_dir / "literature_indices"
            index_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"保存索引数据到目录: {index_dir}")
            
            # 保存统一索引（使用自定义序列化）
            documents_data = {}
            for doc_id, doc in self.id_to_doc.items():
                try:
                    documents_data[doc_id] = doc.to_dict()
                except Exception as e:
                    logger.error(f"序列化文档 {doc_id} 失败: {e}")
                    # 尝试基本序列化
                    documents_data[doc_id] = {
                        'doc_id': doc.doc_id,
                        'entity_type': doc.entity_type.value,
                        'source_id': doc.source_id,
                        'title': doc.title,
                        'content': doc.content,
                        'metadata': doc.metadata,
                        'created_at': doc.created_at,
                        'updated_at': doc.updated_at
                    }
            
            with open(index_dir / "unified_index.json", 'w', encoding='utf-8') as f:
                json.dump({
                    'documents': documents_data,
                    'created_at': datetime.now().isoformat(),
                    'version': '2.0'
                }, f, ensure_ascii=False, indent=2)
            
            # 保存结构映射
            with open(index_dir / "structure_mappings.json", 'w', encoding='utf-8') as f:
                json.dump({
                    'structure_literature_map': self.structure_literature_map,
                    'literature_structure_map': self.literature_structure_map,
                    'updated_at': datetime.now().isoformat()
                }, f, ensure_ascii=False, indent=2)
            
            # 保存ID映射
            with open(index_dir / "id_mappings.json", 'w', encoding='utf-8') as f:
                json.dump({
                    'id_to_idx': self.id_to_idx,
                    'idx_to_id': {k: str(v) for k, v in self.idx_to_id.items()},  # 确保值可序列化
                    'updated_at': datetime.now().isoformat()
                }, f, ensure_ascii=False, indent=2)
            
            logger.info(f"✅ 索引数据已保存: {len(self.id_to_doc)} 个文档")
            
        except Exception as e:
            logger.error(f"保存索引数据失败: {e}")
            raise
    
    def embed_text(self, text: str) -> np.ndarray:
        """生成文本向量（使用 agent_core 的嵌入管理器）"""
        try:
            return self.embed_func(text)
        except Exception as e:
            logger.error(f"生成向量失败: {e}")
            # 回退：生成随机向量
            return np.random.randn(self.dimension).astype(np.float32)
    
    def add_document(self, doc: UnifiedDocument) -> str:
        """添加文档到索引"""
        # 生成文档ID
        if not doc.doc_id:
            doc.doc_id = f"{doc.entity_type.value}_{doc.source_id}_{uuid.uuid4().hex[:8]}"
        
        # 生成向量
        if doc.embeddings is None:
            text_for_embedding = f"{doc.title}. {doc.content[:500]}"
            doc.embeddings = self.embed_text(text_for_embedding)
        
        # 添加到内存索引
        self.id_to_doc[doc.doc_id] = doc

        
        # 更新关键词索引
        self._update_keyword_index(doc)
        
        # 更新结构映射（如果是结构或文献）
        if doc.entity_type == EntityType.STRUCTURE:
            self._update_structure_index(doc)
        elif doc.entity_type == EntityType.LITERATURE:
            self._update_literature_structure_mapping(doc)
        
        logger.info(f"✅ 添加文档: {doc.doc_id} ({doc.entity_type.value})")
        return doc.doc_id

    def clear_structure_index(self):
        """清除所有结构索引"""
        try:
            logger.info("开始清除结构索引...")
            
            # 收集所有结构文档ID
            structure_doc_ids = []
            logger.info(f"当前 id_to_doc 大小: {len(self.id_to_doc)}")
            
            # 调试：打印前几个文档的 entity_type
            debug_count = 0
            for doc_id, doc in self.id_to_doc.items():
                logger.debug(f"文档 {doc_id} 的 entity_type: {doc.entity_type}, 类型: {type(doc.entity_type)}")
                debug_count += 1
                if debug_count >= 5:
                    break
            
            for doc_id, doc in self.id_to_doc.items():
                if doc.entity_type == EntityType.STRUCTURE:
                    structure_doc_ids.append(doc_id)
            
            if not structure_doc_ids:
                logger.info("没有需要清除的结构索引")
                # 调试：检查是否有其他类型的文档
                all_entity_types = set()
                for doc in self.id_to_doc.values():
                    all_entity_types.add(str(doc.entity_type))
                logger.info(f"当前所有文档类型: {all_entity_types}")
                return
            
            logger.info(f"找到 {len(structure_doc_ids)} 个结构文档，准备清除...")
            
            # 从内存索引中删除结构文档
            for doc_id in structure_doc_ids:
                if doc_id in self.id_to_doc:
                    del self.id_to_doc[doc_id]
                
                if doc_id in self.id_to_idx:
                    del self.id_to_idx[doc_id]
            
            # 重新构建向量索引索引（只包含非结构文档）
            non_structure_docs = []
            for doc in self.id_to_doc.values():
                if doc.entity_type != EntityType.STRUCTURE:
                    non_structure_docs.append(doc)
            
            # 重新创建向量索引索引
            if non_structure_docs:
                logger.info(f"保留 {len(non_structure_docs)} 个非结构文档，重新构建索引...")
                self.id_to_idx = {}
                self.idx_to_id = {}
                
                for i, doc in enumerate(non_structure_docs):
                    if doc.embeddings is not None:
                        vector = doc.embeddings.reshape(1, -1).astype(np.float32)
                        self.id_to_idx[doc.doc_id] = i
                        self.idx_to_id[i] = doc.doc_id
            else:
                logger.info("没有非结构文档，清空所有索引...")
                self.index = None
                self.id_to_idx = {}
                self.idx_to_id = {}
            
            # 清空结构相关映射
            self.structure_index = {}
            self.structure_literature_map = {}
            self.literature_structure_map = {}
            
            # 重新构建关键词索引（只包含非结构文档）
            self.keyword_index = defaultdict(set)
            for doc in non_structure_docs:
                self._update_keyword_index(doc)
            
            logger.info(f"✅ 结构索引清除完成，删除了 {len(structure_doc_ids)} 个结构文档")
            
        except Exception as e:
            logger.error(f"清除结构索引失败: {e}")
            raise e
    
    def _update_keyword_index(self, doc: UnifiedDocument):
        """更新关键词索引"""
        # 提取关键词
        text = f"{doc.title} {doc.content}"
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        
        # 常见停用词
        stop_words = {'the', 'and', 'for', 'with', 'that', 'this', 'from', 'have', 'which', 'were'}
        
        for word in words:
            if word not in stop_words and len(word) > 2:
                self.keyword_index[word].add(doc.doc_id)
    
    def _update_structure_index(self, doc: UnifiedDocument):
        """更新结构索引"""
        structure_id = doc.source_id
        if structure_id:
            self.structure_index[structure_id] = {
                'doc_id': doc.doc_id,
                'title': doc.title,
                'metadata': doc.metadata
            }
    
    def _update_literature_structure_mapping(self, doc: UnifiedDocument):
        """更新文献-结构映射"""
        literature_id = doc.source_id
        metadata = doc.metadata
        
        # 从元数据中提取结构ID
        structure_ids = []
        
        # 检查结构字段
        if metadata:
            # 优先从明确的字段获取
            if 'pdb_ids' in metadata:
                structure_ids.extend(metadata['pdb_ids'])
            if 'emdb_ids' in metadata:
                structure_ids.extend(metadata['emdb_ids'])
            if 'structure_ids' in metadata:
                structure_ids.extend(metadata['structure_ids'])
            
            # 如果明确的字段为空，尝试从内容中提取
            if not structure_ids:
                content = doc.content
                extracted_ids = self._extract_structure_ids(content)
                if extracted_ids:
                    structure_ids.extend(extracted_ids)
                    # 更新元数据以便后续使用
                    doc.metadata.setdefault('pdb_ids', [])
                    doc.metadata.setdefault('emdb_ids', [])
                    for sid in extracted_ids:
                        if sid.startswith('EMD-'):
                            doc.metadata['emdb_ids'].append(sid)
                        else:
                            doc.metadata['pdb_ids'].append(sid)
        
        # 去重和标准化
        structure_ids = list(set([str(sid).upper().strip() for sid in structure_ids if sid]))
        
        if structure_ids:
            self.literature_structure_map[literature_id] = structure_ids
            
            for struct_id in structure_ids:
                if struct_id not in self.structure_literature_map:
                    self.structure_literature_map[struct_id] = []
                if literature_id not in self.structure_literature_map[struct_id]:
                    self.structure_literature_map[struct_id].append(literature_id)
            
            logger.debug(f"更新结构映射: 文献 {literature_id} -> {len(structure_ids)} 个结构: {structure_ids[:3]}{'...' if len(structure_ids) > 3 else ''}")
    
    def _extract_structure_ids(self, text: str) -> List[str]:
        """从文本中提取结构ID"""
        structure_ids = []
        
        # 提取PDB ID (如 7EWL, 9MD0)
        pdb_pattern = r'\b([1-9][A-Za-z0-9]{3})\b'
        pdb_matches = re.findall(pdb_pattern, text.upper())
        structure_ids.extend([m.upper() for m in pdb_matches])
        
        # 提取EMDB ID (如 EMD-12345)
        emdb_pattern = r'\b(EMD[-\s_]?\d{4,6})\b'
        emdb_matches = re.findall(emdb_pattern, text.upper())
        structure_ids.extend([m.upper().replace(' ', '').replace('_', '-') for m in emdb_matches])
        
        return list(set(structure_ids))
    
    def search(self, query: str, entity_types: List[EntityType] = None, 
               filters: Dict[str, Any] = None, top_k: int = 10) -> List[SearchResult]:
        """统一搜索"""
        start_time = time.time()
        
        try:
            # 提取查询中的结构ID
            structure_queries = self._extract_structure_ids(query)
            
            # 如果有结构查询，优先结构搜索
            if structure_queries:
                structure_results = self._search_by_structures(structure_queries, top_k * 2)
                
                if structure_results:
                    # 合并和排序
                    results = self._merge_search_results(structure_results, [], top_k)
                    
                    # 如果结果不足，补充文本搜索
                    if len(results) < top_k * 2:
                        text_results = self._search_by_text(query, entity_types, filters, top_k * 2 - len(results))
                        results = self._merge_search_results(results, text_results, top_k)
                    
                    # 二次重排
                    reranked_results = self._rerank_results(query, results, top_k)
                    
                    process_time = time.time() - start_time
                    logger.info(f"结构感知搜索完成: {len(reranked_results)} 个结果 ({process_time:.2f}s)")
                    return reranked_results
            
            # 普通文本搜索
            initial_results = self._search_by_text(query, entity_types, filters, top_k * 2)
            
            # 二次重排
            reranked_results = self._rerank_results(query, initial_results, top_k)
            
            process_time = time.time() - start_time
            logger.info(f"文本搜索完成: {len(reranked_results)} 个结果 ({process_time:.2f}s)")
            return reranked_results
            
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return []
    
    def _search_by_text(self, query: str, entity_types: List[EntityType] = None,
                       filters: Dict[str, Any] = None, top_k: int = 10) -> List[SearchResult]:
        """基于文本的搜索"""
        if self.index is None or self.index.ntotal == 0:
            return []
        
        # 生成查询向量
        query_embedding = self.embed_text(query).reshape(1, -1).astype(np.float32)
        
        # 执行搜索 - 搜索更多结果用于后续处理
        k = min(top_k * 4, self.index.ntotal)  # 搜索更多结果用于过滤和重排
        distances, indices = self.index.search(query_embedding, k)
        
        # 处理结果
        results = []
        for i, (distance, idx) in enumerate(zip(distances[0], indices[0])):
            if idx == -1:
                continue
            
            # 获取文档
            doc_id = self.idx_to_id.get(idx)
            if not doc_id:
                continue
            
            doc = self.id_to_doc.get(doc_id)
            if not doc:
                continue
            
            # 实体类型过滤
            if entity_types and doc.entity_type not in entity_types:
                continue
            
            # 其他过滤条件
            if filters and not self._apply_filters(doc, filters):
                continue
            
            # 计算相似度分数（向量索引返回的是点积，需要转换为相似度）
            similarity = float(distance) / 2.0 + 0.5  # 转换为0-1范围
            
            # 截断内容，控制token长度
            content_snippet = doc.content[:150] + "..."  # 更短的内容片段，减少token消耗
            
            results.append(SearchResult(
                doc_id=doc.doc_id,
                entity_type=doc.entity_type,
                source_id=doc.source_id,
                title=doc.title[:150],  # 截断标题，减少token消耗
                content=content_snippet,
                similarity_score=similarity,
                metadata=doc.metadata,
                rank=len(results) + 1
            ))
            
            if len(results) >= top_k * 2:  # 返回更多结果用于二次重排
                break
        
        return results
    
    def _search_by_structures(self, structure_ids: List[str], top_k: int = 10) -> List[SearchResult]:
        """基于结构ID的搜索"""
        results = []
        
        for struct_id in structure_ids[:3]:  # 最多搜索3个结构
            # 查找包含该结构的文献
            literature_ids = self.structure_literature_map.get(struct_id.upper(), [])
            
            for lit_id in literature_ids[:5]:  # 每个结构最多5篇文献
                # 查找文献文档
                for doc_id, doc in self.id_to_doc.items():
                    if (doc.entity_type == EntityType.LITERATURE and 
                        doc.source_id == lit_id):
                        
                        # 检查是否已添加
                        if not any(r.source_id == lit_id for r in results):
                            results.append(SearchResult(
                                doc_id=doc.doc_id,
                                entity_type=doc.entity_type,
                                source_id=doc.source_id,
                                title=doc.title,
                                content=doc.content[:200] + "...",
                                similarity_score=1.0,  # 直接匹配，最高相似度
                                metadata=doc.metadata,
                                rank=len(results) + 1
                            ))
                        
                        if len(results) >= top_k * 2:
                            break
                
                if len(results) >= top_k * 2:
                    break
            
            if len(results) >= top_k * 2:
                break
        
        # 如果有结构文档，也添加
        for struct_id in structure_ids[:3]:
            structure_doc_id = None
            for doc_id, doc in self.id_to_doc.items():
                if doc.entity_type == EntityType.STRUCTURE and doc.source_id == struct_id:
                    structure_doc_id = doc_id
                    break
            
            if structure_doc_id:
                doc = self.id_to_doc[structure_doc_id]
                results.append(SearchResult(
                    doc_id=doc.doc_id,
                    entity_type=doc.entity_type,
                    source_id=doc.source_id,
                    title=doc.title,
                    content=doc.content[:200] + "...",
                    similarity_score=1.0,
                    metadata=doc.metadata,
                    rank=len(results) + 1
                ))
        
        return results
    
    def _expand_context(self, result: SearchResult, all_results: List[SearchResult]) -> Dict[str, Any]:
        """扩展文档上下文信息"""
        expanded_context = {
            'related_structures': [],
            'related_proteins': [],
            'related_literature': [],
            'structural_relationships': []
        }
        
        # 1. 从元数据中提取相关结构
        if result.metadata and ('pdb_ids' in result.metadata or 'emdb_ids' in result.metadata):
            pdb_ids = result.metadata.get('pdb_ids', [])
            emdb_ids = result.metadata.get('emdb_ids', [])
            expanded_context['related_structures'] = pdb_ids + emdb_ids
        
        # 2. 查找相关蛋白质（从内容和元数据中提取）
        content = f"{result.title} {result.content}"
        protein_names = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', content)
        expanded_context['related_proteins'] = list(set(protein_names))[:3]
        
        # 3. 查找相关文献（基于共同结构或关键词）
        related_literature = []
        for other_result in all_results:
            if other_result.doc_id != result.doc_id and other_result.entity_type == EntityType.LITERATURE:
                # 检查是否有共同结构
                other_content = f"{other_result.title} {other_result.content}"
                if any(struct_id in other_content for struct_id in expanded_context['related_structures']):
                    related_literature.append(other_result.source_id)
        expanded_context['related_literature'] = list(set(related_literature))[:3]
        
        return expanded_context
    
    def _rerank_results(self, query: str, results: List[SearchResult], top_k: int = 10) -> List[SearchResult]:
        """二次重排搜索结果"""
        if not results:
            return []
        
        # 1. 生成查询向量
        query_embedding = self.embed_text(query)
        
        # 2. 计算更精确的相似度分数（结合向量相似度和上下文相关性）
        reranked_results = []
        
        for result in results:
            # 获取完整文档内容
            full_doc = self.id_to_doc.get(result.doc_id)
            if full_doc:
                # 生成完整文档的嵌入向量
                full_text = f"{full_doc.title} {full_doc.content}"
                doc_embedding = self.embed_text(full_text)
                
                # 计算更精确的相似度
                # 使用余弦相似度代替点积
                similarity = float(np.dot(query_embedding, doc_embedding) / 
                                  (np.linalg.norm(query_embedding) * np.linalg.norm(doc_embedding) + 1e-8))
                
                # 3. 上下文相关性增强
                # 扩展当前结果的上下文
                expanded_context = self._expand_context(result, results)
                
                # 基于上下文的增强分数
                context_score = 0.0
                
                # 如果有相关结构，增加分数
                if expanded_context['related_structures']:
                    context_score += 0.1 * len(expanded_context['related_structures'])
                
                # 如果有相关文献，增加分数
                if expanded_context['related_literature']:
                    context_score += 0.1 * len(expanded_context['related_literature'])
                
                # 4. 结合相似度和上下文分数
                final_score = similarity + context_score * 0.1
                
                # 创建新的SearchResult对象，更新分数
                reranked_result = SearchResult(
                    doc_id=result.doc_id,
                    entity_type=result.entity_type,
                    source_id=result.source_id,
                    title=result.title,
                    content=result.content,
                    similarity_score=final_score,
                    metadata=result.metadata,
                    rank=0  # 临时rank，后面会重新计算
                )
                reranked_results.append(reranked_result)
        
        # 5. 按最终分数排序
        reranked_results.sort(key=lambda x: x.similarity_score, reverse=True)
        
        # 6. 更新rank
        for i, result in enumerate(reranked_results[:top_k]):
            result.rank = i + 1
        
        return reranked_results[:top_k]
    
    def _merge_search_results(self, primary_results: List[SearchResult], 
                             secondary_results: List[SearchResult], 
                             top_k: int) -> List[SearchResult]:
        """合并搜索结果"""
        # 创建字典去重
        seen_ids = set()
        merged = []
        
        # 添加主要结果
        for result in primary_results:
            if result.doc_id not in seen_ids:
                seen_ids.add(result.doc_id)
                merged.append(result)
        
        # 添加次要结果
        for result in secondary_results:
            if result.doc_id not in seen_ids:
                seen_ids.add(result.doc_id)
                merged.append(result)
        
        # 按相似度排序
        merged.sort(key=lambda x: x.similarity_score, reverse=True)
        
        return merged[:top_k * 2]  # 返回更多结果用于二次重排
    
    def _apply_filters(self, doc: UnifiedDocument, filters: Dict[str, Any]) -> bool:
        """应用过滤条件"""
        for key, value in filters.items():
            if key == 'entity_type':
                if doc.entity_type != value:
                    return False
            elif key == 'source_id':
                if doc.source_id != value:
                    return False
            elif key == 'keywords':
                if isinstance(value, list):
                    # 检查文档内容是否包含关键词
                    content = f"{doc.title} {doc.content}".lower()
                    if not any(keyword.lower() in content for keyword in value):
                        return False
            elif key in doc.metadata:
                if doc.metadata[key] != value:
                    return False
            else:
                # 其他过滤条件
                content = f"{doc.title} {doc.content}".lower()
                if isinstance(value, str) and value.lower() not in content:
                    return False
        
        return True
    
    def search_by_entity_id(self, entity_type: EntityType, source_id: str) -> List[SearchResult]:
        """根据实体ID搜索"""
        results = []
        
        for doc_id, doc in self.id_to_doc.items():
            if doc.entity_type == entity_type and doc.source_id == source_id:
                results.append(SearchResult(
                    doc_id=doc.doc_id,
                    entity_type=doc.entity_type,
                    source_id=doc.source_id,
                    title=doc.title,
                    content=doc.content[:200] + "...",
                    similarity_score=1.0,
                    metadata=doc.metadata,
                    rank=1
                ))
        
        return results
    
    def get_structure_literature_map(self) -> Dict[str, List[str]]:
        """获取结构-文献映射"""
        return self.structure_literature_map.copy()
    
    def get_literature_structure_map(self) -> Dict[str, List[str]]:
        """获取文献-结构映射"""
        return self.literature_structure_map.copy()
    
    def get_document(self, doc_id: str) -> Optional[UnifiedDocument]:
        """获取文档"""
        return self.id_to_doc.get(doc_id)
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取索引统计"""
        stats = {
            'total_documents': len(self.id_to_doc),
            'by_entity_type': defaultdict(int),
            'index_size': self.index.ntotal if self.index else 0,
            'structure_mappings': {
                'total_structures': len(self.structure_literature_map),
                'total_literature': len(self.literature_structure_map),
                'structures_with_literature': sum(1 for v in self.structure_literature_map.values() if v),
                'literature_with_structures': sum(1 for v in self.literature_structure_map.values() if v)
            }
        }
        
        # 按实体类型统计
        for doc in self.id_to_doc.values():
            stats['by_entity_type'][doc.entity_type.value] += 1
        
        return stats

# ---------- 统一文档生成器 ----------
class UnifiedDocumentGenerator:
    """统一文档生成器"""

    def __init__(self, config=None):
        # Chunk 配置 - 从传入的 config 或使用默认值
        if config and hasattr(config, 'chunk_size'):
            self.config = config
        else:
            self.config = type('Config', (), {
                'chunk_size': 500,
                'chunk_overlap': 50
            })()
        logger.info("✅ 统一文档生成器初始化完成")
    
    def _extract_structure_ids_from_literature(self, literature_entry: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        """从文献条目中提取结构ID（返回PDB和EMDB列表）"""
        pdb_ids = []
        emdb_ids = []
        
        # 来源1: cryoem_targets字段（主要来源）
        cryoem_targets = literature_entry.get('cryoem_targets', {})
        if cryoem_targets:
            try:
                # 尝试多种格式解析
                if isinstance(cryoem_targets, str):
                    try:
                        cryoem_targets = json.loads(cryoem_targets)
                    except json.JSONDecodeError:
                        # 如果不是JSON，可能是逗号分隔的字符串
                        if ',' in cryoem_targets:
                            structure_ids = [s.strip().upper() for s in cryoem_targets.split(',') if s.strip()]
                            for sid in structure_ids:
                                if sid.startswith('EMD-'):
                                    emdb_ids.append(sid)
                                elif re.match(r'^[1-9][A-Za-z0-9]{3}$', sid):
                                    pdb_ids.append(sid)
                        else:
                            # 尝试从字符串中提取
                            pdb_pattern = r'\b([1-9][A-Za-z0-9]{3})\b'
                            emdb_pattern = r'\b(EMD[-\s_]?\d{4,6})\b'
                            pdb_ids.extend(re.findall(pdb_pattern, cryoem_targets.upper()))
                            emdb_matches = re.findall(emdb_pattern, cryoem_targets.upper())
                            emdb_ids.extend([m.upper().replace(' ', '').replace('_', '-') for m in emdb_matches])
                
                if isinstance(cryoem_targets, dict):
                    # 标准格式
                    pdb_ids.extend(cryoem_targets.get('pdb_ids', []))
                    emdb_ids.extend(cryoem_targets.get('emdb_ids', []))
                    
                    # 检查其他可能的字段名
                    for key in ['structure_ids', 'structures', 'cryoem_structures']:
                        if key in cryoem_targets:
                            values = cryoem_targets[key]
                            if isinstance(values, list):
                                for sid in values:
                                    sid = str(sid).upper().strip()
                                    if sid.startswith('EMD-'):
                                        emdb_ids.append(sid)
                                    elif re.match(r'^[1-9][A-Za-z0-9]{3}$', sid):
                                        pdb_ids.append(sid)
                            elif isinstance(values, str) and ',' in values:
                                structure_ids = [s.strip().upper() for s in values.split(',') if s.strip()]
                                for sid in structure_ids:
                                    if sid.startswith('EMD-'):
                                        emdb_ids.append(sid)
                                    elif re.match(r'^[1-9][A-Za-z0-9]{3}$', sid):
                                        pdb_ids.append(sid)
                
                elif isinstance(cryoem_targets, list):
                    # 如果是列表，直接处理
                    for sid in cryoem_targets:
                        sid = str(sid).upper().strip()
                        if sid.startswith('EMD-'):
                            emdb_ids.append(sid)
                        elif re.match(r'^[1-9][A-Za-z0-9]{3}$', sid):
                            pdb_ids.append(sid)
                            
            except Exception as e:
                logger.warning(f"从cryoem_targets提取结构ID失败: {e}")
        
        # 来源2: parsed_data字段（备用来源）
        if not pdb_ids and not emdb_ids and 'parsed_data' in literature_entry:
            parsed_data = literature_entry.get('parsed_data', {})
            if isinstance(parsed_data, str):
                try:
                    parsed_data = json.loads(parsed_data)
                except:
                    parsed_data = {}
            
            if isinstance(parsed_data, dict):
                # 尝试从parsed_data的不同字段提取
                extracted_pdb = parsed_data.get('extracted_pdb_ids', [])
                extracted_emdb = parsed_data.get('extracted_emdb_ids', [])
                
                if extracted_pdb or extracted_emdb:
                    pdb_ids.extend(extracted_pdb)
                    emdb_ids.extend(extracted_emdb)
                else:
                    # 尝试其他可能的字段名
                    for key in ['pdb_ids', 'emdb_ids', 'structure_ids']:
                        if key in parsed_data:
                            ids = parsed_data[key]
                            if isinstance(ids, list):
                                for sid in ids:
                                    sid = str(sid).upper().strip()
                                    if sid.startswith('EMD-'):
                                        emdb_ids.append(sid)
                                    elif re.match(r'^[1-9][A-Za-z0-9]{3}$', sid):
                                        pdb_ids.append(sid)
        
        # 来源3: 直接字段（最后尝试）
        if not pdb_ids and not emdb_ids:
            for field in ['structure_ids', 'pdb_ids', 'emdb_ids']:
                if field in literature_entry:
                    ids = literature_entry.get(field, [])
                    if isinstance(ids, list):
                        for sid in ids:
                            sid = str(sid).upper().strip()
                            if field == 'emdb_ids' or sid.startswith('EMD-'):
                                emdb_ids.append(sid)
                            elif field == 'pdb_ids' or re.match(r'^[1-9][A-Za-z0-9]{3}$', sid):
                                pdb_ids.append(sid)
                    elif isinstance(ids, str) and ids.strip():
                        structure_ids = [s.strip().upper() for s in ids.split(',') if s.strip()]
                        for sid in structure_ids:
                            if sid.startswith('EMD-'):
                                emdb_ids.append(sid)
                            elif re.match(r'^[1-9][A-Za-z0-9]{3}$', sid):
                                pdb_ids.append(sid)
        
        # 去重和标准化
        pdb_ids = list(set([str(pid).upper().strip() for pid in pdb_ids if pid and re.match(r'^[1-9][A-Za-z0-9]{3}$', str(pid).upper().strip())]))
        emdb_ids = list(set([str(eid).upper().strip() for eid in emdb_ids if eid and str(eid).upper().startswith('EMD-')]))
        
        return pdb_ids, emdb_ids
    
    def from_literature(self, literature_entry: Dict[str, Any]) -> UnifiedDocument:
        """从文献条目生成统一文档（基础元数据文档）"""
        content_parts = []

        # 标题
        title = literature_entry.get('title', '')
        content_parts.append(f"标题: {title}")

        # 作者
        authors = literature_entry.get('authors', [])
        if authors:
            if isinstance(authors, str):
                content_parts.append(f"作者: {authors}")
            elif isinstance(authors, list):
                author_names = []
                for author in authors[:5]:
                    if isinstance(author, dict):
                        author_names.append(author.get('name', ''))
                    else:
                        author_names.append(str(author))
                content_parts.append(f"作者: {', '.join(author_names)}")

        # 摘要
        abstract = literature_entry.get('abstract', '')
        if abstract:
            content_parts.append(f"摘要: {abstract}")

        # 关键发现
        key_findings = literature_entry.get('key_findings', [])
        if key_findings:
            content_parts.append("关键发现:")
            if isinstance(key_findings, list):
                for i, finding in enumerate(key_findings[:3]):
                    if isinstance(finding, dict):
                        content_parts.append(f"  {i+1}. {finding.get('finding', '')}")
                    else:
                        content_parts.append(f"  {i+1}. {finding}")

        # 提取结构ID
        pdb_ids, emdb_ids = self._extract_structure_ids_from_literature(literature_entry)
        structure_ids = pdb_ids + emdb_ids

        if structure_ids:
            content_parts.append(f"结构ID: {', '.join(structure_ids[:10])}{'...' if len(structure_ids) > 10 else ''}")

        content = "\n".join(content_parts)

        metadata = {
            'year': literature_entry.get('year'),
            'journal': literature_entry.get('journal', ''),
            'doi': literature_entry.get('doi', ''),
            'structure_ids': structure_ids,
            'pdb_ids': pdb_ids,
            'emdb_ids': emdb_ids,
            'publication_date': literature_entry.get('publication_date_full', ''),
            'source': 'unified_index',
            'doc_type': 'metadata'  # 标记为元数据文档
        }

        # 清理元数据中的None值
        metadata = {k: v for k, v in metadata.items() if v is not None}

        return UnifiedDocument(
            doc_id=f"literature_{literature_entry.get('id', '')}",
            entity_type=EntityType.LITERATURE,
            source_id=str(literature_entry.get('id', '')),
            title=title[:200],
            content=content,
            metadata=metadata
        )

        # 2. 如果没有任何章节数据，回退到使用 full_text
        full_text = literature_entry.get('full_text', '')
        if full_text and len(full_text) > 200:
            logger.info(f"[chunk_literature] 文献 {lit_id} 使用完整原文生成 chunks，原文长度: {len(full_text)}")
            text_chunks = self._split_text(full_text, chunk_size=self.config.chunk_size, overlap=self.config.chunk_overlap)
            logger.info(f"[chunk_literature] 文献 {lit_id} 完整原文生成了 {len(text_chunks)} 个 chunks")

            for chunk_idx, chunk_content in enumerate(text_chunks):
                chunk_doc = UnifiedDocument(
                    doc_id=f"literature_{lit_id}_full_chunk_{chunk_id_counter}",
                    entity_type=EntityType.LITERATURE,
                    source_id=str(lit_id),
                    title=f"{title} - 全文第{chunk_idx+1}部分",
                    content=chunk_content,
                    metadata={
                        'year': year,
                        'journal': journal,
                        'chunk_index': chunk_id_counter,
                        'total_chunks': len(text_chunks),
                        'section': 'full_text',
                        'doc_type': 'content_chunk',
                        'chunk_length': len(chunk_content)
                    }
                )
                chunks.append(chunk_doc)
                chunk_id_counter += 1

        logger.debug(f"[chunk_literature] 文献 {lit_id} 生成了 {len(chunks)} 个 chunks")
        return chunks

    def chunk_literature_content(self, literature_entry: Dict[str, Any]) -> List[UnifiedDocument]:
        """
        将文献内容 chunk 后生成多个文档 - 章节感知版本

        改进点：
        1. 优先使用混合章节识别的结果
        2. 确保不跨章节边界分块
        3. 保存章节元数据用于后续过滤
        4. 支持邻居块追踪

        用于 RAG 检索时提供更细粒度的上下文
        """
        lit_id = literature_entry.get('id', '')
        title = literature_entry.get('title', '')
        year = literature_entry.get('year', '')
        journal = literature_entry.get('journal', '')

        chunks = []
        chunk_id_counter = 0

        # 获取章节数据（优先使用新的混合识别结果）
        parsed_data = literature_entry.get('parsed_data', {})
        if isinstance(parsed_data, str):
            try:
                parsed_data = json.loads(parsed_data)
            except:
                parsed_data = {}

        # 检查是否有混合章节识别结果
        hybrid_sections = parsed_data.get('hybrid_sections', {}) if isinstance(parsed_data, dict) else {}
        section_data = parsed_data.get('section_data', {}) if isinstance(parsed_data, dict) else {}

        # 优先使用混合识别的章节
        if hybrid_sections and len(hybrid_sections) > 0:
            logger.info(f"[chunk_literature] 文献 {lit_id} 使用混合章节识别结果: {len(hybrid_sections)} 个章节")
            sections_to_process = hybrid_sections
        elif section_data and len(section_data) > 0:
            logger.info(f"[chunk_literature] 文献 {lit_id} 使用传统章节数据: {len(section_data)} 个章节")
            sections_to_process = section_data
        else:
            sections_to_process = {}

        # 1. 处理章节内容（章节感知分块）
        if sections_to_process:
            for section_name, content in sections_to_process.items():
                if not content or not isinstance(content, str):
                    continue

                # 清理内容
                content = content.strip()
                if len(content) < 50:  # 跳过太短的内容
                    continue

                # 章节感知分块 - 确保不跨边界
                section_chunks = self._chunk_section_content(
                    content=content,
                    section_name=section_name,
                    lit_id=lit_id,
                    title=title,
                    year=year,
                    journal=journal,
                    start_chunk_id=chunk_id_counter
                )

                chunks.extend(section_chunks)
                chunk_id_counter += len(section_chunks)

        # 2. 如果没有任何章节数据，回退到使用 full_text
        if not chunks:
            full_text = literature_entry.get('full_text', '')
            if full_text and len(full_text) > 200:
                logger.info(f"[chunk_literature] 文献 {lit_id} 无章节数据，使用完整原文分块")
                section_chunks = self._chunk_section_content(
                    content=full_text,
                    section_name='full_text',
                    lit_id=lit_id,
                    title=title,
                    year=year,
                    journal=journal,
                    start_chunk_id=chunk_id_counter
                )
                chunks.extend(section_chunks)
                chunk_id_counter += len(section_chunks)

        # 3. 处理摘要（单独处理，标记为 abstract 章节）
        abstract = literature_entry.get('abstract', '')
        if abstract and len(abstract) > 100:
            abstract_chunks = self._chunk_section_content(
                content=abstract,
                section_name='abstract',
                lit_id=lit_id,
                title=title,
                year=year,
                journal=journal,
                start_chunk_id=chunk_id_counter,
                prefix='abstract'
            )
            chunks.extend(abstract_chunks)
            chunk_id_counter += len(abstract_chunks)

        # 4. 更新邻居块信息（用于上下文扩展）
        chunks = self._update_neighbor_info(chunks)

        logger.info(f"[chunk_literature] 文献 {lit_id} 共生成 {len(chunks)} 个章节感知 chunks")
        return chunks

    def _chunk_section_content(
        self,
        content: str,
        section_name: str,
        lit_id: str,
        title: str,
        year: Any,
        journal: str,
        start_chunk_id: int,
        prefix: str = 'full'
    ) -> List[UnifiedDocument]:
        """
        章节感知分块 - 确保分块不跨章节边界

        Args:
            content: 章节内容
            section_name: 章节名称
            lit_id: 文献ID
            title: 文献标题
            year: 发表年份
            journal: 期刊
            start_chunk_id: 起始chunk ID
            prefix: ID前缀

        Returns:
            分块后的文档列表
        """
        chunks = []

        # 如果章节很短，作为一个整体块
        if len(content) <= self.config.chunk_size:
            chunk_doc = UnifiedDocument(
                doc_id=f"literature_{lit_id}_{prefix}_chunk_{start_chunk_id}",
                entity_type=EntityType.LITERATURE,
                source_id=str(lit_id),
                title=f"{title} - {section_name}"[:200],
                content=f"## {section_name}\n{content}" if section_name != 'full_text' else content,
                metadata={
                    'year': year,
                    'journal': journal,
                    'chunk_index': start_chunk_id,
                    'section_chunk_index': 0,
                    'total_chunks': 1,
                    'section': section_name,
                    'doc_type': 'content_chunk',
                    'chunk_length': len(content),
                    'section_total_chunks': 1
                }
            )
            chunks.append(chunk_doc)
            return chunks

        # 长章节按大小分块，但保持在章节边界内
        text_chunks = self._split_text(
            content,
            chunk_size=self.config.chunk_size,
            overlap=self.config.chunk_overlap
        )

        for chunk_idx, chunk_content in enumerate(text_chunks):
            # 构建 chunk 内容（带章节标题）
            if section_name != 'full_text':
                chunk_text = f"## {section_name}\n{chunk_content}"
                chunk_title = f"{title} - {section_name} (part {chunk_idx+1})"
            else:
                chunk_text = chunk_content
                chunk_title = f"{title} - 全文第{chunk_idx+1}部分"

            chunk_doc = UnifiedDocument(
                doc_id=f"literature_{lit_id}_{prefix}_chunk_{start_chunk_id + chunk_idx}",
                entity_type=EntityType.LITERATURE,
                source_id=str(lit_id),
                title=chunk_title[:200],
                content=chunk_text,
                metadata={
                    'year': year,
                    'journal': journal,
                    'chunk_index': start_chunk_id + chunk_idx,
                    'section_chunk_index': chunk_idx,
                    'total_chunks': len(text_chunks),
                    'section': section_name,
                    'doc_type': 'content_chunk',
                    'chunk_length': len(chunk_content),
                    'section_total_chunks': len(text_chunks)
                }
            )
            chunks.append(chunk_doc)

        return chunks

    def _update_neighbor_info(self, chunks: List[UnifiedDocument]) -> List[UnifiedDocument]:
        """
        更新邻居块信息，用于上下文扩展

        为每个块添加其前后邻居的ID信息，方便后续检索时获取相邻块
        """
        if not chunks:
            return chunks

        # 按 chunk_index 排序
        sorted_chunks = sorted(chunks, key=lambda x: x.metadata.get('chunk_index', 0))

        for i, chunk in enumerate(sorted_chunks):
            chunk_index = chunk.metadata.get('chunk_index', i)

            # 找到前一个块（相同文献且相同章节）
            prev_chunk_id = None
            if i > 0:
                prev_chunk = sorted_chunks[i - 1]
                if (prev_chunk.source_id == chunk.source_id and
                    prev_chunk.metadata.get('section') == chunk.metadata.get('section')):
                    prev_chunk_id = prev_chunk.doc_id

            # 找到后一个块（相同文献且相同章节）
            next_chunk_id = None
            if i < len(sorted_chunks) - 1:
                next_chunk = sorted_chunks[i + 1]
                if (next_chunk.source_id == chunk.source_id and
                    next_chunk.metadata.get('section') == chunk.metadata.get('section')):
                    next_chunk_id = next_chunk.doc_id

            # 更新元数据
            chunk.metadata['prev_chunk_id'] = prev_chunk_id
            chunk.metadata['next_chunk_id'] = next_chunk_id
            chunk.metadata['has_neighbors'] = prev_chunk_id is not None or next_chunk_id is not None

        return sorted_chunks

    def _split_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """将文本分割成 chunks（智能分割句子 - 支持中英文）"""
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        chunks = []

        # 按句子分割（支持中英文）
        import re

        # 中英文句子分隔符（包含英文句号）
        sentence_endings = r'(?<=[。！？!?\.])' + r'\s+'
        sentences = re.split(sentence_endings, text)

        # 如果分割结果太少（可能是纯英文），尝试按更细粒度分割
        if len(sentences) <= 1 or (len(text) > chunk_size * 2 and len(sentences) < 3):
            # 按段落+句号分割
            paragraphs = re.split(r'\n\n|(?<=[。\.])\n', text)
            if len(paragraphs) > len(sentences):
                sentences = []
                for para in paragraphs:
                    # 按句号+空格分割英文句子
                    en_sent = re.split(r'(?<=\.)\s+', para)
                    sentences.extend([s.strip() for s in en_sent if s.strip()])

        current_chunk = ""
        current_length = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            sentence_length = len(sentence)

            # 如果单个句子超过 chunk_size，需要进一步分割
            if sentence_length > chunk_size:
                # 先保存当前 chunk
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    # 重叠部分
                    overlap_start = max(0, len(current_chunk) - overlap)
                    current_chunk = current_chunk[overlap_start:]
                    current_length = len(current_chunk)

                # 强制分割长句子
                for i in range(0, sentence_length, chunk_size - overlap):
                    sub_chunk = sentence[i:i + chunk_size]
                    if sub_chunk.strip():
                        chunks.append(sub_chunk.strip())
                current_chunk = ""
                current_length = 0
                continue

            # 检查是否需要开始新 chunk
            if current_length + sentence_length + 1 > chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                # 重叠部分
                overlap_start = max(0, len(current_chunk) - overlap)
                current_chunk = current_chunk[overlap_start:]
                current_length = len(current_chunk)

            # 添加句子
            if current_chunk:
                current_chunk += " " + sentence
                current_length += 1 + sentence_length
            else:
                current_chunk = sentence
                current_length = sentence_length

        # 保存最后一个 chunk
        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks
    
    def from_structure(self, structure_info: Dict[str, Any]) -> UnifiedDocument:
        """从结构信息生成统一文档"""
        structure_id = structure_info.get('id', '')
        title = structure_info.get('title', '')
        
        content_parts = []
        content_parts.append(f"结构ID: {structure_id}")
        content_parts.append(f"标题: {title}")
        
        resolution = structure_info.get('resolution')
        if resolution:
            content_parts.append(f"分辨率: {resolution} Å")
        
        method = structure_info.get('method', '')
        if method:
            content_parts.append(f"方法: {method}")
        
        organism = structure_info.get('organism', '')
        if organism:
            content_parts.append(f"生物体: {organism}")
        
        publication_date = structure_info.get('publication_date', '')
        if publication_date:
            content_parts.append(f"发表日期: {publication_date}")
        
        authors = structure_info.get('authors', [])
        if authors:
            content_parts.append(f"作者: {', '.join(authors[:3])}")
        
        keywords = structure_info.get('keywords', [])
        if keywords:
            content_parts.append(f"关键词: {', '.join(keywords[:5])}")
        
        content = "\n".join(content_parts)
        
        metadata = {
            'resolution': resolution,
            'method': method,
            'organism': organism,
            'publication_date': publication_date,
            'authors': authors,
            'keywords': keywords,
            'type': 'pdb' if not structure_id.startswith('EMD-') else 'emdb'
        }
        
        # 清理元数据中的None值
        metadata = {k: v for k, v in metadata.items() if v is not None}
        
        return UnifiedDocument(
            doc_id=f"structure_{structure_id}",
            entity_type=EntityType.STRUCTURE,
            source_id=structure_id,
            title=f"{structure_id}: {title[:100]}",
            content=content,
            metadata=metadata
        )
    
    def from_protein(self, protein_name: str, protein_info: Dict[str, Any]) -> UnifiedDocument:
        """从蛋白质信息生成统一文档"""
        content_parts = []
        content_parts.append(f"蛋白质: {protein_name}")
        
        uniprot_id = protein_info.get('uniprot_id', '')
        if uniprot_id:
            content_parts.append(f"UniProt ID: {uniprot_id}")
        
        gene_name = protein_info.get('gene_name', '')
        if gene_name:
            content_parts.append(f"基因名称: {gene_name}")
        
        function = protein_info.get('function', '')
        if function:
            content_parts.append(f"功能: {function[:200]}")
        
        structures = protein_info.get('structures', [])
        if structures:
            structure_ids = [s.get('id', '') for s in structures[:5]]
            content_parts.append(f"相关结构: {', '.join(structure_ids)}")
        
        content = "\n".join(content_parts)
        
        metadata = {
            'uniprot_id': uniprot_id,
            'gene_name': gene_name,
            'function': function,
            'structure_count': len(structures)
        }
        
        # 清理元数据中的None值
        metadata = {k: v for k, v in metadata.items() if v is not None}
        
        return UnifiedDocument(
            doc_id=f"protein_{protein_name.lower()}",
            entity_type=EntityType.PROTEIN,
            source_id=protein_name,
            title=f"蛋白质: {protein_name}",
            content=content,
            metadata=metadata
        )

# ---------- 知识图谱构建器 ----------
class KnowledgeGraphBuilder:
    """知识图谱构建器"""
    
    def __init__(self):
        self.graph = nx.Graph()
        self.entity_to_node = {}  # 实体ID到图节点的映射
        self.node_counter = 0
        
        logger.info("✅ 知识图谱构建器初始化完成")
    
    def add_entity(self, entity_id: str, entity_type: str, attributes: Dict[str, Any] = None):
        """添加实体到图谱"""
        if entity_id not in self.entity_to_node:
            node_id = self.node_counter
            self.node_counter += 1
            
            self.graph.add_node(node_id, 
                              id=entity_id,
                              type=entity_type,
                              **{k: v for k, v in (attributes or {}).items() if v is not None})
            
            self.entity_to_node[entity_id] = node_id
            return node_id
        
        return self.entity_to_node[entity_id]
    
    def add_relationship(self, source_id: str, target_id: str, 
                        relationship_type: str, weight: float = 1.0):
        """添加关系到图谱"""
        if source_id not in self.entity_to_node or target_id not in self.entity_to_node:
            return False
        
        source_node = self.entity_to_node[source_id]
        target_node = self.entity_to_node[target_id]
        
        self.graph.add_edge(source_node, target_node, 
                          type=relationship_type, 
                          weight=weight)
        
        return True
    
    def build_from_search_results(self, search_results: List[SearchResult]):
        """从搜索结果构建知识图谱"""
        for result in search_results:
            # 添加实体
            self.add_entity(
                entity_id=result.doc_id,
                entity_type=result.entity_type.value,
                attributes={
                    'title': result.title,
                    'score': result.similarity_score,
                    'source_id': result.source_id
                }
            )
        
        # 添加实体间的关系
        for i, result1 in enumerate(search_results):
            for result2 in search_results[i+1:]:
                # 计算相似度作为关系权重
                if result1.entity_type == result2.entity_type:
                    continue
                
                # 根据实体类型确定关系类型
                rel_type = f"{result1.entity_type.value}_to_{result2.entity_type.value}"
                
                # 计算权重（基于相似度和实体类型）
                weight = (result1.similarity_score + result2.similarity_score) / 2
                
                # 如果是结构-文献关系，检查是否存在实际关联
                if (result1.entity_type == EntityType.STRUCTURE and 
                    result2.entity_type == EntityType.LITERATURE):
                    struct_id = result1.source_id
                    lit_id = result2.source_id
                    
                    # 可以从索引中检查是否存在实际关联
                    # 这里暂时使用相似度作为权重
                    self.add_relationship(result1.doc_id, result2.doc_id, rel_type, weight)
    
    def get_related_entities(self, entity_id: str, max_depth: int = 2) -> List[Dict[str, Any]]:
        """获取相关实体"""
        if entity_id not in self.entity_to_node:
            return []
        
        start_node = self.entity_to_node[entity_id]
        related = []
        
        # 使用BFS查找相关实体
        visited = set([start_node])
        queue = [(start_node, 0)]
        
        while queue:
            node, depth = queue.pop(0)
            
            if depth > max_depth:
                continue
            
            for neighbor in self.graph.neighbors(node):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
                    
                    node_data = self.graph.nodes[neighbor]
                    related.append({
                        'id': node_data.get('id', ''),
                        'type': node_data.get('type', ''),
                        'title': node_data.get('title', ''),
                        'distance': depth + 1
                    })
        
        return sorted(related, key=lambda x: x['distance'])
    
    def get_graph_statistics(self) -> Dict[str, Any]:
        """获取图谱统计"""
        return {
            'total_nodes': self.graph.number_of_nodes(),
            'total_edges': self.graph.number_of_edges(),
            'node_types': Counter([data.get('type', 'unknown') for _, data in self.graph.nodes(data=True)]),
            'edge_types': Counter([data.get('type', 'unknown') for _, _, data in self.graph.edges(data=True)])
        }

class UnifiedRAGSystem:
    def __init__(self, config: Dict[str, Any] = None):
        # 检查是否已经初始化过
        if hasattr(self, '_initialized') and self._initialized:
            logger.info("UnifiedRAGSystem 已经初始化过，跳过重复初始化")
            return
            
        self.config = config or {}
        self._initialized = False
        self._initializing = False

        # 延迟加载组件 - 但确保基本组件立即初始化
        self.vector_indexer = None
        self.document_generator = None
        self.knowledge_graph = None
        self.structure_fetcher = None
        
        # 立即初始化文档生成器
        self.document_generator = UnifiedDocumentGenerator(config=self.config)
        
        # 新增：增量索引支持
        self.index_tracker = None
        self._init_index_tracker()
        
        self._initialized = True
        logger.info("✅ 统一RAG系统初始化完成（支持增量索引）")
        self._diagnose_structure_manager()

    def _diagnose_structure_manager(self):
        """诊断结构管理器状态"""
        try:
            # 检查结构管理器模块是否可用
            if not HAS_STRUCTURE_MANAGER:
                logger.warning("❌ 结构管理器模块未导入 (HAS_STRUCTURE_MANAGER=False)")
                return
            
            # 尝试导入结构管理器
            try:
                from core.structure_manager import StructureMetadataFetcher
                logger.info("✅ 可以导入 StructureMetadataFetcher")
            except ImportError as e:
                logger.error(f"❌ 无法导入 StructureMetadataFetcher: {e}")
                return
            
            # 尝试创建实例
            try:
                self.structure_fetcher = StructureMetadataFetcher({
                    'max_workers': 2,
                    'timeout': 10,
                    'cache_dir': 'structure_cache'
                })
                logger.info("✅ 结构管理器实例创建成功")
            except Exception as e:
                logger.error(f"❌ 结构管理器实例创建失败: {e}")
                self.structure_fetcher = None
        
        except Exception as e:
            logger.error(f"结构管理器诊断失败: {e}") 

    def _ensure_structure_manager(self):
        """确保结构管理器已初始化"""
        if not HAS_STRUCTURE_MANAGER:
            logger.warning("结构管理器模块不可用")
            return False
        
        if self.structure_fetcher is None:
            try:
                from core.structure_manager import StructureMetadataFetcher
                self.structure_fetcher = StructureMetadataFetcher({
                    'max_workers': 2,
                    'timeout': 10,
                    'cache_dir': 'structure_cache'
                })
                logger.info("✅ 延迟初始化结构管理器成功")
                return True
            except Exception as e:
                logger.error(f"❌ 延迟初始化结构管理器失败: {e}")
                return False
        
        return True

    def _init_index_tracker(self):
        """初始化索引跟踪器"""
        try:
            from literature_index_tracker import IndexStateTracker
            self.index_tracker = IndexStateTracker()
        except ImportError:
            logger.warning("索引跟踪器不可用，增量索引功能将受限")
    
    def index_literature_with_tracking(self, literature_data: List[Dict[str, Any]], 
                                      incremental: bool = True) -> Dict[str, Any]:
        """带跟踪的文献索引"""
        if incremental and self.index_tracker:
            logger.info(f"执行增量索引: {len(literature_data)} 篇文献")
            
            # 识别变更
            changes = self._identify_changes(literature_data)
            
            if changes['total_changed'] == 0:
                logger.info("没有变更的文献，跳过索引")
                return {
                    'success': True,
                    'message': '没有需要索引的变更',
                    'changes': changes
                }
            
            # 只索引变更的文献
            literature_to_index = changes['added'] + changes['updated']
            logger.info(f"需要索引: {len(literature_to_index)} 篇文献")
            
            # 执行索引
            result = self.index_literature(literature_to_index)
            
            # 更新跟踪信息
            if result:
                self._update_document_tracking(literature_to_index)
            
            return {
                'success': result,
                'changes': changes,
                'total_indexed': len(literature_to_index)
            }
        else:
            # 全量索引
            logger.info(f"执行全量索引: {len(literature_data)} 篇文献")
            result = self.index_literature(literature_data)
            
            # 更新跟踪信息
            if result and self.index_tracker:
                self._update_document_tracking(literature_data)
            
            return {
                'success': result,
                'index_type': 'full',
                'total_indexed': len(literature_data)
            }
    
    def _identify_changes(self, literature_data: List[Dict[str, Any]]) -> Dict[str, List[Dict]]:
        """识别变更的文献"""
        if not self.index_tracker:
            return {
                'added': literature_data,
                'updated': [],
                'unchanged': [],
                'total_changed': len(literature_data)
            }
        
        added = []
        updated = []
        unchanged = []
        
        for lit_data in literature_data:
            lit_id = str(lit_data.get('id', ''))
            if not lit_id:
                continue
            
            doc_id = f"literature_{lit_id}"
            existing_hash = self.index_tracker.get_document_hash(doc_id)
            
            # 计算当前内容哈希
            content = self._generate_document_content(lit_data)
            content_hash = self._calculate_hash(content)
            
            if existing_hash is None:
                added.append(lit_data)
            elif existing_hash[0] != content_hash:
                updated.append(lit_data)
            else:
                unchanged.append(lit_data)
        
        return {
            'added': added,
            'updated': updated,
            'unchanged': unchanged,
            'total_changed': len(added) + len(updated)
        }
    
    def _update_document_tracking(self, literature_data: List[Dict[str, Any]]):
        """更新文档跟踪信息"""
        if not self.index_tracker:
            return
        
        for lit_data in literature_data:
            lit_id = str(lit_data.get('id', ''))
            if not lit_id:
                continue
            
            doc_id = f"literature_{lit_id}"
            content = self._generate_document_content(lit_data)
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
    
    def _generate_document_content(self, lit_data: Dict[str, Any]) -> str:
        """生成文档内容用于哈希计算"""
        content_parts = []
        content_parts.append(lit_data.get('title', ''))
        content_parts.append(lit_data.get('abstract', ''))
        
        authors = lit_data.get('authors', [])
        if isinstance(authors, list):
            content_parts.append(', '.join([str(a) for a in authors[:5]]))
        elif isinstance(authors, str):
            content_parts.append(authors)
        
        return ' '.join(content_parts)
    
    def _calculate_hash(self, data: str) -> str:
        """计算哈希值"""
        import hashlib
        return hashlib.sha256(data.encode('utf-8')).hexdigest()[:32]
    
    def get_index_health(self) -> Dict[str, Any]:
        """获取索引健康状态"""
        if not self.index_tracker:
            return {'status': 'unknown', 'message': '索引跟踪器不可用'}
        
        try:
            stats = self.vector_indexer.get_statistics() if self.vector_indexer else {}
            index_stats = self.index_tracker.get_index_statistics()
            
            # 评估健康状态
            total_docs = index_stats.get('total_documents', 0)
            recent_indexed = index_stats.get('recently_indexed', 0)
            
            health_status = 'healthy'
            if total_docs == 0:
                health_status = 'empty'
            elif recent_indexed == 0:
                health_status = 'stale'
            
            return {
                'status': health_status,
                'vector_index': stats,
                'tracking_stats': index_stats,
                'recommendations': self._generate_health_recommendations(health_status, stats)
            }
            
        except Exception as e:
            logger.error(f"获取索引健康状态失败: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def _generate_health_recommendations(self, health_status: str, stats: Dict) -> List[str]:
        """生成健康建议"""
        recommendations = []
        
        if health_status == 'empty':
            recommendations.append("索引为空，建议执行全量构建")
        elif health_status == 'stale':
            recommendations.append("索引已过期，建议执行增量更新")
        
        # 检查结构映射
        structure_stats = stats.get('structure_mappings', {})
        if structure_stats.get('total_structures', 0) == 0:
            recommendations.append("未发现结构信息，建议检查结构提取逻辑")
        
        return recommendations   
    # ---------- 结构增强功能 ----------
    
    def search_by_structure(self, structure_query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """根据结构ID搜索文献"""
        # 提取结构ID
        structure_ids = self.vector_indexer._extract_structure_ids(structure_query)
        
        if not structure_ids:
            return []
        
        results = []
        
        for struct_id in structure_ids[:3]:  # 最多搜索3个结构
            # 查找包含该结构的文献
            literature_ids = self.vector_indexer.structure_literature_map.get(struct_id.upper(), [])
            
            for lit_id in literature_ids[:5]:  # 每个结构最多5篇文献
                # 查找文献文档
                for doc_id, doc in self.vector_indexer.id_to_doc.items():
                    if (doc.entity_type == EntityType.LITERATURE and 
                        doc.source_id == lit_id):
                        
                        # 检查是否已添加
                        if not any(r.get('literature_id') == lit_id for r in results):
                            results.append({
                                'literature_id': lit_id,
                                'title': doc.title,
                                'structure_ids': [struct_id],
                                'match_type': 'direct_structure_id',
                                'similarity_score': 1.0
                            })
                        
                        if len(results) >= top_k:
                            break
                
                if len(results) >= top_k:
                    break
            
            if len(results) >= top_k:
                break
        
        return results[:top_k]
    
    def get_literature_with_structures(self, literature_id: str) -> Dict[str, Any]:
        """获取文献及其结构信息"""
        # 查找文献文档
        literature_doc = None
        for doc_id, doc in self.vector_indexer.id_to_doc.items():
            if doc.entity_type == EntityType.LITERATURE and doc.source_id == literature_id:
                literature_doc = doc
                break
        
        if not literature_doc:
            return {'success': False, 'error': '文献不存在'}
        
        # 获取结构ID
        structure_ids = self.vector_indexer.literature_structure_map.get(literature_id, [])
        
        # 获取结构信息
        structures = []
        if structure_ids and self.structure_fetcher:
            pdb_metadata, emdb_metadata = self.structure_fetcher.fetch_all_metadata(structure_ids, use_cache=True)
            
            for struct_id in structure_ids:
                if struct_id in pdb_metadata:
                    meta = pdb_metadata[struct_id]
                    structures.append({
                        'id': struct_id,
                        'title': getattr(meta, 'title', f"PDB {struct_id}"),
                        'resolution': getattr(meta, 'resolution', None),
                        'method': getattr(meta, 'method', 'X-ray crystallography'),
                        'type': 'pdb'
                    })
                elif struct_id in emdb_metadata:
                    meta = emdb_metadata[struct_id]
                    # EMDBMetadata 可能使用不同的属性名
                    method_value = getattr(meta, 'method', getattr(meta, 'technique', 'Cryo-EM'))
                    structures.append({
                        'id': struct_id,
                        'title': getattr(meta, 'title', f"EMDB {struct_id}"),
                        'resolution': getattr(meta, 'resolution', None),
                        'method': method_value,
                        'type': 'emdb'
                    })
        
        return {
            'success': True,
            'literature_id': literature_id,
            'title': literature_doc.title,
            'structure_ids': structure_ids,
            'structures': structures,
            'total_structures': len(structures)
        }
    
    def get_structure_statistics(self) -> Dict[str, Any]:
        """获取结构统计信息"""
        structure_map = self.vector_indexer.structure_literature_map
        
        # 统计不同类型的结构
        pdb_count = 0
        emdb_count = 0
        
        for struct_id in structure_map.keys():
            if struct_id.startswith('EMD-'):
                emdb_count += 1
            elif re.match(r'^[1-9][A-Za-z0-9]{3}$', struct_id):
                pdb_count += 1
        
        # 统计文献-结构关联
        literature_count = len(self.vector_indexer.literature_structure_map)
        
        # 统计最常出现的结构
        structure_freq = sorted(
            [(struct_id, len(lit_ids)) for struct_id, lit_ids in structure_map.items()],
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        return {
            "total_structures": len(structure_map),
            "pdb_count": pdb_count,
            "emdb_count": emdb_count,
            "literature_with_structures": literature_count,
            "top_structures": [
                {'id': struct_id, 'frequency': freq} 
                for struct_id, freq in structure_freq
            ],
            "structure_coverage": f"{literature_count} 篇文献包含结构信息"
        }
    
    def find_related_structures(self, structure_id: str) -> List[Dict[str, Any]]:
        """查找相关结构"""
        if structure_id not in self.vector_indexer.structure_literature_map:
            return []
        
        lit_ids = self.vector_indexer.structure_literature_map[structure_id]
        
        # 获取这些文献中的所有结构
        all_structures = set()
        for lit_id in lit_ids:
            if lit_id in self.vector_indexer.literature_structure_map:
                all_structures.update(self.vector_indexer.literature_structure_map[lit_id])
        
        # 排除查询的结构本身
        all_structures.discard(structure_id)
        
        # 统计出现频率
        structure_freq = {}
        for struct_id in all_structures:
            for lit_id in lit_ids:
                if lit_id in self.vector_indexer.literature_structure_map:
                    if struct_id in self.vector_indexer.literature_structure_map[lit_id]:
                        structure_freq[struct_id] = structure_freq.get(struct_id, 0) + 1
        
        # 转换为列表并排序
        related = []
        for struct_id, freq in sorted(structure_freq.items(), key=lambda x: x[1], reverse=True):
            related.append({
                "structure_id": struct_id,
                "co_occurrence_count": freq,
                "related_literature_count": len(self.vector_indexer.structure_literature_map.get(struct_id, []))
            })
        
        return related[:10]  # 返回前10个相关结构
    
    def batch_update_structure_mappings(self) -> Dict[str, Any]:
        """批量更新结构映射（从数据库重新构建）"""
        if not HAS_LITERATURE_DB:
            return {"success": False, "error": "数据库不可用"}
        
        start_time = time.time()
        
        try:
            session = create_literature_session()
            
            # 获取所有有结构信息的文献
            literature_entries = session.query(LiteratureEntry).filter(
                LiteratureEntry.cryoem_targets.isnot(None)
            ).all()
            
            updated_count = 0
            error_count = 0
            
            for entry in literature_entries:
                try:
                    lit_id = str(entry.id)
                    
                    # 提取结构ID
                    structure_ids = []
                    cryoem_targets = entry.cryoem_targets
                    
                    if cryoem_targets:
                        if isinstance(cryoem_targets, dict):
                            pdb_ids = cryoem_targets.get('pdb_ids', [])
                            emdb_ids = cryoem_targets.get('emdb_ids', [])
                            structure_ids.extend(pdb_ids)
                            structure_ids.extend(emdb_ids)
                        elif isinstance(cryoem_targets, str):
                            try:
                                parsed = json.loads(cryoem_targets)
                                if isinstance(parsed, dict):
                                    pdb_ids = parsed.get('pdb_ids', [])
                                    emdb_ids = parsed.get('emdb_ids', [])
                                    structure_ids.extend(pdb_ids)
                                    structure_ids.extend(emdb_ids)
                            except:
                                # 尝试从字符串中提取
                                extracted_ids = self.vector_indexer._extract_structure_ids(cryoem_targets)
                                structure_ids.extend(extracted_ids)
                    
                    # 更新映射
                    if structure_ids:
                        # 创建临时文档用于更新映射
                        temp_doc = UnifiedDocument(
                            doc_id=f"literature_{lit_id}",
                            entity_type=EntityType.LITERATURE,
                            source_id=lit_id,
                            title=entry.title or "",
                            content=entry.abstract or "",
                            metadata={'structure_ids': structure_ids}
                        )
                        self.vector_indexer._update_literature_structure_mapping(temp_doc)
                        updated_count += 1
                        logger.debug(f"更新文献 {entry.id} 结构映射: {len(structure_ids)} 个结构ID")
                    
                except Exception as e:
                    error_count += 1
                    logger.warning(f"更新文献 {entry.id} 结构映射失败: {e}")
            
            session.close()
            
            # 保存更新
            self.vector_indexer._save_index_data()
            
            process_time = time.time() - start_time
            
            return {
                "success": True,
                "message": f"批量更新完成: {updated_count} 篇文献更新，{error_count} 个错误",
                "updated_count": updated_count,
                "error_count": error_count,
                "total_structures": len(self.vector_indexer.structure_literature_map),
                "process_time": process_time
            }
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"批量更新结构映射失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "process_time": process_time
            }
    def _ensure_initialized(self):
        """确保所有组件已初始化（延迟加载）"""
        if self._initialized and self.vector_indexer is not None:
            return
        
        if self._initializing:
            # 已经在初始化中，等待
            import time
            while self._initializing:
                time.sleep(0.1)
            return
        
        self._initializing = True
        try:
            logger.info("🔄 开始延迟初始化重组件...")
            
            # 初始化向量索引器（可能耗时）
            vector_config = {
                'model_name': self.config.get('model_name', 'all-MiniLM-L6-v2'),
                'cache_dir': self.config.get('cache_dir', 'unified_vector_cache'),
                'structure_cache_dir': self.config.get('structure_cache_dir', 'structure_cache')
            }
            
            # 使用现有的单例或创建新实例
            from .literature_index import UnifiedVectorIndexer
            self.vector_indexer = UnifiedVectorIndexer(model_name=vector_config)
            
            # 结构增强组件
            if HAS_STRUCTURE_MANAGER and not hasattr(self, 'structure_fetcher'):
                try:
                    from core.structure_manager import StructureMetadataFetcher
                    self.structure_fetcher = StructureMetadataFetcher({
                        'max_workers': 2, 
                        'timeout': 10,
                        'cache_dir': 'structure_cache'
                    })
                    logger.info("✅ 结构管理器已初始化")
                except Exception as e:
                    logger.warning(f"结构管理器初始化失败: {e}")
                    self.structure_fetcher = None
            
        finally:
            self._initializing = False
    
    def _extract_structure_ids_from_literature(self, lit_data: Dict[str, Any]) -> List[str]:
        """从文献数据中提取结构ID（增强版）"""
        try:
            # 来源1: cryoem_targets 字段
            structure_ids = []
            cryoem_targets = lit_data.get('cryoem_targets', {})
            
            logger.info(f"处理文献 {lit_data.get('id', 'unknown')}")
            logger.info(f"cryoem_targets 类型: {type(cryoem_targets)}")
            
            if isinstance(cryoem_targets, dict):
                logger.info(f"cryoem_targets 是字典类型")
                # 从多个可能的字段中提取结构ID
                pdb_ids = cryoem_targets.get('pdb_ids', [])
                emdb_ids = cryoem_targets.get('emdb_ids', [])
                structure_ids_field = cryoem_targets.get('structure_ids', [])
                structure_ids.extend(pdb_ids)
                structure_ids.extend(emdb_ids)
                structure_ids.extend(structure_ids_field)
                logger.info(f"从字典提取到 {len(structure_ids)} 个结构ID")
                logger.info(f"pdb_ids: {pdb_ids}")
                logger.info(f"emdb_ids: {emdb_ids}")
                logger.info(f"structure_ids: {structure_ids_field}")
            elif isinstance(cryoem_targets, list):
                logger.info(f"cryoem_targets 是列表类型")
                # 如果是列表，直接处理
                for item in cryoem_targets:
                    if isinstance(item, str):
                        item = item.strip().upper()
                        if item:
                            structure_ids.append(item)
                logger.info(f"从列表提取到 {len(structure_ids)} 个结构ID")
            elif isinstance(cryoem_targets, str):
                logger.info(f"cryoem_targets 是字符串类型")
                try:
                    # 尝试解析JSON字符串
                    logger.info(f"尝试解析JSON字符串")
                    parsed = json.loads(cryoem_targets)
                    logger.info(f"JSON解析成功，类型: {type(parsed)}")
                    if isinstance(parsed, dict):
                        logger.info(f"解析后的是字典类型")
                        pdb_ids = parsed.get('pdb_ids', [])
                        emdb_ids = parsed.get('emdb_ids', [])
                        structure_ids_field = parsed.get('structure_ids', [])
                        structure_ids.extend(pdb_ids)
                        structure_ids.extend(emdb_ids)
                        structure_ids.extend(structure_ids_field)
                        logger.info(f"从解析后的字典提取到 {len(structure_ids)} 个结构ID")
                        logger.info(f"pdb_ids: {pdb_ids}")
                        logger.info(f"emdb_ids: {emdb_ids}")
                        logger.info(f"structure_ids: {structure_ids_field}")
                    elif isinstance(parsed, list):
                        logger.info(f"解析后的是列表类型")
                        # 如果解析后是列表
                        for item in parsed:
                            if isinstance(item, str):
                                item = item.strip().upper()
                                if item:
                                    structure_ids.append(item)
                        logger.info(f"从解析后的列表提取到 {len(structure_ids)} 个结构ID")
                except Exception as e:
                    logger.info(f"JSON解析失败: {e}")
                    # 如果不是JSON，尝试从字符串中提取
                    logger.info(f"直接从字符串提取结构ID")
                    # 提取PDB ID
                    pdb_pattern = r'[1-9][A-Za-z0-9]{3}'
                    pdb_matches = re.findall(pdb_pattern, cryoem_targets.upper())
                    # 提取EMDB ID
                    emdb_pattern = r'EMD[-\s_]?\d{4,6}'
                    emdb_matches = re.findall(emdb_pattern, cryoem_targets.upper())
                    emdb_matches = [m.replace(' ', '').replace('_', '-') for m in emdb_matches]
                    structure_ids.extend(pdb_matches)
                    structure_ids.extend(emdb_matches)
                    logger.info(f"从字符串直接提取到 {len(pdb_matches) + len(emdb_matches)} 个结构ID")
                    logger.info(f"PDB matches: {pdb_matches}")
                    logger.info(f"EMDB matches: {emdb_matches}")
            
            # 来源2: 直接从parsed_data中查找
            parsed_data = lit_data.get('parsed_data', {})
            if isinstance(parsed_data, dict):
                for key in ['structure_ids', 'extracted_pdb_ids', 'extracted_emdb_ids']:
                    if key in parsed_data and parsed_data[key]:
                        ids = parsed_data[key]
                        if isinstance(ids, list):
                            structure_ids.extend(ids)
                            logger.info(f"从parsed_data提取到 {len(ids)} 个结构ID")
            
            # 来源3: 从关键发现和摘要中提取
            content = f"{lit_data.get('key_findings', '')} {lit_data.get('abstract', '')}"
            # 提取PDB ID
            pdb_pattern = r'[1-9][A-Za-z0-9]{3}'
            pdb_matches = re.findall(pdb_pattern, content.upper())
            # 提取EMDB ID
            emdb_pattern = r'EMD[-\s_]?\d{4,6}'
            emdb_matches = re.findall(emdb_pattern, content.upper())
            emdb_matches = [m.replace(' ', '').replace('_', '-') for m in emdb_matches]
            structure_ids.extend(pdb_matches)
            structure_ids.extend(emdb_matches)
            logger.info(f"从内容提取到 {len(pdb_matches) + len(emdb_matches)} 个结构ID")
            
            # 来源4: 从标题中提取
            title = lit_data.get('title', '')
            pdb_matches_title = re.findall(pdb_pattern, title.upper())
            emdb_matches_title = re.findall(emdb_pattern, title.upper())
            emdb_matches_title = [m.replace(' ', '').replace('_', '-') for m in emdb_matches_title]
            structure_ids.extend(pdb_matches_title)
            structure_ids.extend(emdb_matches_title)
            logger.info(f"从标题提取到 {len(pdb_matches_title) + len(emdb_matches_title)} 个结构ID")
            
            logger.info(f"提取到的原始结构ID: {structure_ids}")
            
            # 去重和标准化
            normalized_ids = []
            seen_ids = set()
            
            for sid in structure_ids:
                if not sid:
                    continue
                # 标准化
                sid_str = str(sid).upper().strip()
                
                # 处理不同格式的结构ID
                if sid_str.startswith('EMD'):
                    # 标准化EMDB ID
                    emdb_clean = sid_str.replace('EMD-', 'EMD-').replace('EMD_', 'EMD-').replace('EMD ', 'EMD-')
                    # 确保格式正确
                    if re.match(r'^EMD-\d+$', emdb_clean):
                        if emdb_clean not in seen_ids:
                            normalized_ids.append(emdb_clean)
                            seen_ids.add(emdb_clean)
                            logger.info(f"添加EMDB ID: {emdb_clean}")
                else:
                    # 处理PDB ID
                    pdb_clean = sid_str.replace('-', '').replace('_', '').replace(' ', '')
                    if re.match(r'^[1-9][A-Za-z0-9]{3}$', pdb_clean):
                        if pdb_clean not in seen_ids:
                            normalized_ids.append(pdb_clean)
                            seen_ids.add(pdb_clean)
                            logger.info(f"添加PDB ID: {pdb_clean}")
            
            # 去重
            structure_ids = normalized_ids
            
            logger.info(f"最终提取到 {len(structure_ids)} 个结构ID: {structure_ids}")
            
            if structure_ids:
                logger.info(f"文献 {lit_data.get('id', 'unknown')} 提取到 {len(structure_ids)} 个结构ID: {structure_ids}")
            
            return structure_ids
            
        except Exception as e:
            logger.warning(f"提取结构ID失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def index_literature(self, literature_data: List[Dict[str, Any]], incremental: bool = False, rebuild: bool = False, include_structures: bool = True) -> bool:
        """索引文献数据（支持增量索引和重建）"""
        try:
            # 确保文档生成器已初始化
            if self.document_generator is None:
                self.document_generator = UnifiedDocumentGenerator(config=self.config)
                logger.info("✅ 文档生成器已初始化")
            
            # 如果是重建，先清空索引
            if rebuild:
                logger.info("开始重建索引，清空现有数据...")
                self._clear_index()
            
            if rebuild:
                logger.info(f"开始重建索引 {len(literature_data)} 篇文献")
            elif incremental:
                logger.info(f"开始增量索引 {len(literature_data)} 篇文献")
            else:
                logger.info(f"开始全量索引 {len(literature_data)} 篇文献")
            
            # 收集所有唯一的结构ID
            all_structure_ids = set()
            indexed_count = 0
            
            for lit_data in literature_data:
                try:
                    # 检查是否已经索引过（对于增量索引）
                    lit_id = str(lit_data.get('id', ''))
                    if incremental and lit_id:
                        doc_id = f"literature_{lit_id}"
                        if hasattr(self.vector_indexer, 'id_to_doc') and doc_id in self.vector_indexer.id_to_doc:
                            logger.debug(f"文献 {lit_id} 已索引，跳过")
                            continue
                    
                    # 调试：打印文献数据结构
                    logger.info(f"处理文献 {lit_id}:")
                    logger.info(f"  标题: {lit_data.get('title', 'N/A')}")
                    logger.info(f"  cryoem_targets 类型: {type(lit_data.get('cryoem_targets'))}")
                    cryoem_targets_val = lit_data.get('cryoem_targets', 'N/A')
                    if isinstance(cryoem_targets_val, (dict, list)):
                        import json
                        cryoem_targets_str = json.dumps(cryoem_targets_val)[:200]
                    else:
                        cryoem_targets_str = str(cryoem_targets_val)[:200]
                    logger.info(f"  cryoem_targets 值: {cryoem_targets_str}...")
                    
                    # 生成统一文档（元数据文档）
                    doc = self.document_generator.from_literature(lit_data)

                    # 添加到索引
                    if self.vector_indexer is None:
                        # 如果向量索引器未初始化，先初始化
                        vector_config = {
                            'model_name': self.config.get('model_name', 'all-MiniLM-L6-v2'),
                            'cache_dir': self.config.get('cache_dir', 'unified_vector_cache'),
                            'structure_cache_dir': self.config.get('structure_cache_dir', 'structure_cache')
                        }
                        self.vector_indexer = UnifiedVectorIndexer(model_name=vector_config)

                    doc_id = self.vector_indexer.add_document(doc)
                    indexed_count += 1

                    # 生成并索引文献内容 chunks
                    logger.info(f"开始生成文献 {lit_id} 的内容 chunks...")
                    content_chunks = self.document_generator.chunk_literature_content(lit_data)

                    if content_chunks:
                        logger.info(f"文献 {lit_id} 生成了 {len(content_chunks)} 个 content chunks")
                        for chunk_doc in content_chunks:
                            chunk_id = self.vector_indexer.add_document(chunk_doc)
                            indexed_count += 1
                        logger.info(f"文献 {lit_id} 的 {len(content_chunks)} 个 chunks 已添加到索引")
                    else:
                        logger.debug(f"文献 {lit_id} 没有生成 content chunks（可能没有解析的章节内容）")
                    
                    # 提取结构ID
                    if include_structures:
                        logger.info(f"开始提取文献 {lit_id} 的结构ID...")
                        structure_ids = self._extract_structure_ids_from_literature(lit_data)
                        logger.info(f"文献 {lit_id} 提取结果: {structure_ids}")
                        
                        if structure_ids:
                            all_structure_ids.update(structure_ids)
                            logger.debug(f"文献 {lit_id} 提取到 {len(structure_ids)} 个结构ID: {structure_ids}")
                        
                except Exception as e:
                    logger.error(f"索引文献 {lit_data.get('id', 'unknown')} 失败: {e}")
                    continue
            
            # 如果有结构ID且结构管理器可用，则索引结构
            if include_structures and all_structure_ids:
                logger.info(f"发现 {len(all_structure_ids)} 个结构ID，开始索引结构...")
                logger.debug(f"结构ID列表: {list(all_structure_ids)[:10]}{'...' if len(all_structure_ids) > 10 else ''}")
                self._index_structures(list(all_structure_ids))
            elif not include_structures:
                logger.info("跳过结构索引（按配置）")
            else:
                logger.warning("文献中没有发现结构ID，跳过结构索引")
            
            # 保存索引
            if self.vector_indexer:
                self.vector_indexer._save_index_data()
            
            # 更新元数据
            self._update_index_metadata(indexed_count, len(all_structure_ids) if include_structures else 0)
            
            logger.info(f"✅ 文献索引完成: {indexed_count} 篇文献{'，' + str(len(all_structure_ids)) + ' 个结构' if include_structures and all_structure_ids else ''}")
            return True
            
        except Exception as e:
            logger.error(f"文献索引失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _update_index_metadata(self, literature_count: int, structure_count: int):
        """更新索引元数据"""
        try:
            # 使用索引管理器保存元数据
            from literature_index_manager import LiteratureIndexManager
            manager = LiteratureIndexManager()
            manager.save_index_metadata(literature_count, structure_count)
        except Exception as e:
            logger.warning(f"更新索引元数据失败: {e}")
    
    def _clear_index(self):
        """清空索引"""
        try:
            # 清空内存中的数据
            if hasattr(self, 'vector_indexer') and self.vector_indexer:
                # 清空向量索引器
                self.vector_indexer.id_to_doc = {}
                self.vector_indexer.id_to_idx = {}
                self.vector_indexer.idx_to_id = {}
                self.vector_indexer.structure_literature_map = {}
                self.vector_indexer.literature_structure_map = {}
                self.vector_indexer.structure_index = {}
                self.vector_indexer.keyword_index = defaultdict(set)
                
                # 重新创建向量索引索引
                self.vector_indexer.index = None
            
            logger.info("✅ 索引已清空，准备重建")
        except Exception as e:
            logger.error(f"清空索引失败: {e}")
    
    def _index_structures(self, structure_ids: List[str]):
        """索引结构数据（增强版）"""
        try:
            if not structure_ids:
                logger.info("没有需要索引的结构ID")
                return
            
            # 分离PDB和EMDB ID
            pdb_ids = [sid for sid in structure_ids if sid is not None and not sid.startswith('EMD-')]
            emdb_ids = [sid for sid in structure_ids if sid is not None and sid.startswith('EMD-')]
            
            logger.info(f"准备索引结构: {len(pdb_ids)} 个PDB, {len(emdb_ids)} 个EMDB")
            
            # 尝试确保结构管理器已初始化
            if not self._ensure_structure_manager():
                logger.warning("⚠️ 结构管理器不可用，将创建基本结构文档")
            
            # 如果有结构管理器，获取结构元数据
            if self.structure_fetcher:
                logger.info("使用结构管理器获取结构元数据...")
                
                # 使用新函数获取元数据
                pdb_metadata, emdb_metadata = self._fetch_structure_metadata(pdb_ids, emdb_ids)
                
                # 统计成功获取的数量
                pdb_fetched = len(pdb_metadata)
                emdb_fetched = len(emdb_metadata)
                
                if pdb_fetched > 0 or emdb_fetched > 0:
                    logger.info(f"成功获取 {pdb_fetched} 个PDB 和 {emdb_fetched} 个EMDB 的元数据")
                    
                    # 处理PDB结构
                    indexed_pdb = self._index_pdb_structures(pdb_metadata)
                    
                    # 处理EMDB结构
                    indexed_emdb = self._index_emdb_structures(emdb_metadata)
                    
                    logger.info(f"✅ 结构索引完成: {indexed_pdb} 个PDB, {indexed_emdb} 个EMDB")
                    
                    # 检查是否有未获取元数据的结构
                    total_fetched = pdb_fetched + emdb_fetched
                    total_requested = len(structure_ids)
                    
                    if total_fetched < total_requested:
                        missed_count = total_requested - total_fetched
                        logger.warning(f"⚠️ 有 {missed_count} 个结构未获取到元数据")
                        
                        # 找出哪些结构没有元数据
                        fetched_ids = set(pdb_metadata.keys()) | set(emdb_metadata.keys())
                        missed_ids = set(structure_ids) - fetched_ids
                        
                        if missed_ids:
                            logger.info(f"为 {len(missed_ids)} 个结构创建基本文档...")
                            self._create_basic_structure_docs(list(missed_ids))
                else:
                    logger.warning("⚠️ 未能获取任何结构元数据，创建基本文档...")
                    self._create_basic_structure_docs(structure_ids[:100])
            else:
                # 结构管理器不可用，创建基本结构文档
                logger.warning("结构管理器不可用，创建基本结构文档...")
                self._create_basic_structure_docs(structure_ids[:100])
            
        except Exception as e:
            logger.error(f"结构索引失败: {e}")
            raise e

    def _fetch_structure_metadata(self, pdb_ids: List[str], emdb_ids: List[str]) -> Tuple[Dict, Dict]:
        """获取结构元数据（优先从离线数据库获取）"""
        # 尝试从离线数据库获取结构信息
        try:
            from structure_database import StructureOfflineDatabase
            structure_db = StructureOfflineDatabase()
            
            # 获取所有结构信息
            conn = structure_db.conn
            cursor = conn.cursor()
            
            pdb_metadata = {}
            emdb_metadata = {}
            
            # 获取PDB结构信息
            if pdb_ids:
                placeholders = ','.join(['?'] * len(pdb_ids))
                cursor.execute(f'SELECT * FROM structures WHERE id IN ({placeholders}) AND type = "pdb"', pdb_ids)
                pdb_rows = cursor.fetchall()
                
                for row in pdb_rows:
                    structure_id = row[0]
                    pdb_metadata[structure_id] = {
                        'id': row[0],
                        'type': row[1],
                        'title': row[2],
                        'resolution': row[3],
                        'method': row[4],
                        'deposition_date': row[5],
                        'release_date': row[6],
                        'organism': row[7],
                        'expression_system': row[8],
                        'expression_system_strain': row[9],
                        'gene': row[10],
                        'protein_name': row[11],
                        'authors': row[12],
                        'citation_count': row[13],
                        'related_ids': row[14],
                        'uniprot_ids': row[15]
                    }
            
            # 获取EMDB结构信息
            if emdb_ids:
                placeholders = ','.join(['?'] * len(emdb_ids))
                cursor.execute(f'SELECT * FROM structures WHERE id IN ({placeholders}) AND type = "emdb"', emdb_ids)
                emdb_rows = cursor.fetchall()
                
                for row in emdb_rows:
                    structure_id = row[0]
                    emdb_metadata[structure_id] = {
                        'id': row[0],
                        'type': row[1],
                        'title': row[2],
                        'resolution': row[3],
                        'method': row[4],
                        'deposition_date': row[5],
                        'release_date': row[6],
                        'organism': row[7],
                        'expression_system': row[8],
                        'expression_system_strain': row[9],
                        'gene': row[10],
                        'protein_name': row[11],
                        'authors': row[12],
                        'citation_count': row[13],
                        'related_ids': row[14],
                        'uniprot_ids': row[15]
                    }
            
            logger.info(f"从离线数据库获取元数据: {len(pdb_metadata)} 个PDB, {len(emdb_metadata)} 个EMDB")
            return pdb_metadata, emdb_metadata
            
        except Exception as e:
            logger.warning(f"从离线数据库获取结构元数据失败: {e}")
            logger.info("尝试使用结构管理器获取...")
        
        # 如果离线数据库获取失败，回退到使用结构管理器
        if not self.structure_fetcher:
            return {}, {}
        
        try:
            # 处理可能的空列表
            if not pdb_ids and not emdb_ids:
                return {}, {}
            
            # 调用结构管理器
            pdb_metadata, emdb_metadata = self.structure_fetcher.fetch_all_metadata(
                pdb_ids=pdb_ids if pdb_ids else [],
                emdb_ids=emdb_ids if emdb_ids else [],
                use_cache=True
            )
            
            logger.info(f"成功获取元数据: {len(pdb_metadata)} 个PDB, {len(emdb_metadata)} 个EMDB")
            return pdb_metadata, emdb_metadata
            
        except TypeError as e:
            # 如果是参数错误，可能是方法签名不同
            logger.warning(f"fetch_all_metadata参数错误: {e}")
            logger.info("尝试其他调用方式...")
            
            # 尝试不同的调用方式
            try:
                # 方式1：尝试使用单个参数
                result = self.structure_fetcher.fetch_all_metadata(
                    structure_ids=pdb_ids + emdb_ids,
                    use_cache=True
                )
                # 假设返回格式是 (pdb_metadata, emdb_metadata)
                if isinstance(result, tuple) and len(result) == 2:
                    return result
            except:
                pass
            
            # 方式2：分别获取PDB和EMDB
            pdb_metadata = {}
            emdb_metadata = {}
            
            if pdb_ids:
                try:
                    from core.structure_manager import PDBMetadata
                    for pdb_id in pdb_ids[:10]:  # 限制数量
                        metadata = self.structure_fetcher.get_pdb_info(pdb_id)
                        if metadata:
                            pdb_metadata[pdb_id] = metadata
                except Exception as e:
                    logger.warning(f"获取PDB元数据失败: {e}")
            
            if emdb_ids:
                try:
                    from core.structure_manager import EMDBMetadata
                    for emdb_id in emdb_ids[:10]:  # 限制数量
                        metadata = self.structure_fetcher.get_emdb_info(emdb_id)
                        if metadata:
                            emdb_metadata[emdb_id] = metadata
                except Exception as e:
                    logger.warning(f"获取EMDB元数据失败: {e}")
            
            return pdb_metadata, emdb_metadata
            
        except Exception as e:
            logger.error(f"获取结构元数据失败: {e}")
            return {}, {}

    def _index_pdb_structures(self, pdb_metadata: Dict) -> int:
        """索引PDB结构（修复作者数据处理）"""
        indexed = 0
        
        # 确保向量索引器已初始化
        if not self.vector_indexer:
            self._ensure_initialized()
            if not self.vector_indexer:
                logger.error("向量索引器初始化失败，无法索引结构")
                return 0
        
        for pdb_id, metadata in pdb_metadata.items():
            try:
                # 使用更安全的方式获取属性
                title = self._safe_get_attr(metadata, 'title', f"PDB {pdb_id}")
                resolution = self._safe_get_attr(metadata, 'resolution')
                method = self._safe_get_attr(metadata, 'method', 'X-ray crystallography')
                organism = self._safe_get_attr(metadata, 'organism', 'Unknown')
                deposition_date = self._safe_get_attr(metadata, 'deposition_date')
                authors = self._safe_get_attr(metadata, 'authors', [])
                keywords = self._safe_get_attr(metadata, 'keywords', [])
                
                # 修复：正确处理作者数据（可能是字典列表）
                processed_authors = self._process_authors_data(authors)
                
                # 处理关键词数据
                processed_keywords = self._process_keywords_data(keywords)
                
                structure_info = {
                    'id': pdb_id,
                    'title': title,
                    'resolution': resolution,
                    'method': method,
                    'organism': organism,
                    'publication_date': deposition_date,
                    'authors': processed_authors,  # 使用处理后的作者数据
                    'keywords': processed_keywords  # 使用处理后的关键词数据
                }
                
                doc = self.document_generator.from_structure(structure_info)
                self.vector_indexer.add_document(doc)
                indexed += 1
                logger.debug(f"索引PDB结构 {pdb_id} 成功: {title[:50]}...")
                
            except Exception as e:
                logger.warning(f"索引PDB结构 {pdb_id} 失败: {e}")
                # 创建基本文档作为后备
                self._create_basic_pdb_doc(pdb_id)
        
        return indexed

    def _index_emdb_structures(self, emdb_metadata: Dict) -> int:
        """索引EMDB结构（修复作者数据处理）"""
        indexed = 0
        
        # 确保向量索引器已初始化
        if not self.vector_indexer:
            self._ensure_initialized()
            if not self.vector_indexer:
                logger.error("向量索引器初始化失败，无法索引结构")
                return 0
        
        for emdb_id, metadata in emdb_metadata.items():
            try:
                # 使用安全方式获取所有属性
                title = self._safe_get_attr(metadata, 'title', f"EMDB {emdb_id}")
                resolution = self._safe_get_attr(metadata, 'resolution')
                
                # 方法可能有不同的属性名
                method = self._safe_get_attr(metadata, 'method')
                if not method:
                    method = self._safe_get_attr(metadata, 'technique', 'Cryo-EM')
                
                organism = self._safe_get_attr(metadata, 'organism', 'Unknown')
                deposition_date = self._safe_get_attr(metadata, 'deposition_date')
                authors = self._safe_get_attr(metadata, 'authors', [])
                keywords = self._safe_get_attr(metadata, 'keywords', [])
                
                # 修复：正确处理作者数据
                processed_authors = self._process_authors_data(authors)
                
                # 处理关键词数据
                processed_keywords = self._process_keywords_data(keywords)
                
                structure_info = {
                    'id': emdb_id,
                    'title': title,
                    'resolution': resolution,
                    'method': method,
                    'organism': organism,
                    'publication_date': deposition_date,
                    'authors': processed_authors,  # 使用处理后的作者数据
                    'keywords': processed_keywords  # 使用处理后的关键词数据
                }
                
                doc = self.document_generator.from_structure(structure_info)
                self.vector_indexer.add_document(doc)
                indexed += 1
                logger.debug(f"索引EMDB结构 {emdb_id} 成功: {title[:50]}...")
                
            except Exception as e:
                logger.warning(f"索引EMDB结构 {emdb_id} 失败: {e}")
                # 创建基本文档作为后备
                self._create_basic_emdb_doc(emdb_id)
        
        return indexed

    def _process_authors_data(self, authors_data: Any) -> List[str]:
        """处理作者数据，支持多种格式"""
        if not authors_data:
            return []
        
        processed_authors = []
        
        try:
            if isinstance(authors_data, list):
                for author in authors_data:
                    if isinstance(author, dict):
                        # 字典格式的作者信息
                        author_str = self._extract_author_from_dict(author)
                        if author_str:
                            processed_authors.append(author_str)
                    elif isinstance(author, str):
                        # 字符串格式的作者
                        if author.strip():
                            processed_authors.append(author.strip())
                    else:
                        # 其他格式，尝试转换为字符串
                        try:
                            author_str = str(author)
                            if author_str.strip():
                                processed_authors.append(author_str.strip())
                        except:
                            pass
            elif isinstance(authors_data, str):
                # 字符串格式，可能是逗号分隔的
                if ',' in authors_data:
                    authors_list = [a.strip() for a in authors_data.split(',') if a.strip()]
                    processed_authors.extend(authors_list)
                else:
                    if authors_data.strip():
                        processed_authors.append(authors_data.strip())
            elif isinstance(authors_data, dict):
                # 单个作者字典
                author_str = self._extract_author_from_dict(authors_data)
                if author_str:
                    processed_authors.append(author_str)
            else:
                # 尝试转换为字符串
                try:
                    author_str = str(authors_data)
                    if author_str.strip():
                        processed_authors.append(author_str.strip())
                except:
                    pass
            
            # 限制作者数量并去重
            processed_authors = list(dict.fromkeys(processed_authors))[:20]  # 最多20个作者
            
            return processed_authors
            
        except Exception as e:
            logger.warning(f"处理作者数据失败: {e}")
            return []

    def _extract_author_from_dict(self, author_dict: Dict) -> str:
        """从作者字典中提取作者字符串"""
        try:
            # 优先使用 name 字段
            if 'name' in author_dict and author_dict['name']:
                return str(author_dict['name']).strip()
            
            # 使用 given 和 family 字段组合
            if 'given' in author_dict and 'family' in author_dict:
                given = str(author_dict.get('given', '')).strip()
                family = str(author_dict.get('family', '')).strip()
                if given and family:
                    return f"{given} {family}"
                elif given:
                    return given
                elif family:
                    return family
            
            # 使用 first 和 last 字段组合
            if 'first' in author_dict and 'last' in author_dict:
                first = str(author_dict.get('first', '')).strip()
                last = str(author_dict.get('last', '')).strip()
                if first and last:
                    return f"{first} {last}"
            
            # 尝试其他可能的字段
            possible_fields = ['full_name', 'display_name', 'author', 'initials', 'surname']
            for field in possible_fields:
                if field in author_dict and author_dict[field]:
                    value = str(author_dict[field]).strip()
                    if value:
                        return value
            
            # 如果没有找到合适的字段，返回字典的第一个值
            for key, value in author_dict.items():
                if value and isinstance(value, str):
                    return value.strip()
            
            # 最后尝试转换整个字典
            return str(author_dict)[:100]
            
        except Exception as e:
            logger.debug(f"从字典提取作者失败: {e}")
            return ""

    def _process_keywords_data(self, keywords_data: Any) -> List[str]:
        """处理关键词数据"""
        if not keywords_data:
            return []
        
        processed_keywords = []
        
        try:
            if isinstance(keywords_data, list):
                for keyword in keywords_data:
                    if isinstance(keyword, str) and keyword.strip():
                        processed_keywords.append(keyword.strip())
                    elif keyword is not None:
                        try:
                            keyword_str = str(keyword)
                            if keyword_str.strip():
                                processed_keywords.append(keyword_str.strip())
                        except:
                            pass
            elif isinstance(keywords_data, str):
                # 字符串格式，可能是逗号分隔或分号分隔
                import re
                # 尝试多种分隔符
                delimiters = r'[,;|]'
                parts = re.split(delimiters, keywords_data)
                for part in parts:
                    if part.strip():
                        processed_keywords.append(part.strip())
            else:
                # 尝试转换为字符串列表
                try:
                    if isinstance(keywords_data, dict):
                        # 字典的值作为关键词
                        for value in keywords_data.values():
                            if value and isinstance(value, str):
                                processed_keywords.append(value.strip())
                    else:
                        keyword_str = str(keywords_data)
                        if keyword_str.strip():
                            processed_keywords.append(keyword_str.strip())
                except:
                    pass
            
            # 去重并限制数量
            processed_keywords = list(dict.fromkeys(processed_keywords))[:20]  # 最多20个关键词
            
            return processed_keywords
            
        except Exception as e:
            logger.warning(f"处理关键词数据失败: {e}")
            return []

    def _create_basic_structure_docs(self, structure_ids: List[str], limit: int = 100):
        """创建基本结构文档（后备方案）"""
        indexed = 0
        
        for struct_id in structure_ids[:limit]:  # 限制数量
            try:
                # 判断是PDB还是EMDB
                if struct_id.startswith('EMD-'):
                    self._create_basic_emdb_doc(struct_id)
                else:
                    self._create_basic_pdb_doc(struct_id)
                
                indexed += 1
                
            except Exception as e:
                logger.warning(f"创建基本结构文档 {struct_id} 失败: {e}")
        
        logger.info(f"✅ 创建基本结构文档: {indexed} 个结构")

    def _create_basic_pdb_doc(self, pdb_id: str):
        """创建基本PDB文档"""
        # 确保向量索引器已初始化
        if not self.vector_indexer:
            self._ensure_initialized()
            if not self.vector_indexer:
                logger.error("向量索引器初始化失败，无法创建基本PDB文档")
                return
        
        structure_info = {
            'id': pdb_id,
            'title': f"PDB结构 {pdb_id}",
            'resolution': None,
            'method': 'X-ray crystallography',
            'organism': 'Unknown',
            'publication_date': None,
            'authors': [],
            'keywords': ['PDB']
        }
        
        doc = self.document_generator.from_structure(structure_info)
        self.vector_indexer.add_document(doc)

    def _create_basic_emdb_doc(self, emdb_id: str):
        """创建基本EMDB文档"""
        # 确保向量索引器已初始化
        if not self.vector_indexer:
            self._ensure_initialized()
            if not self.vector_indexer:
                logger.error("向量索引器初始化失败，无法创建基本EMDB文档")
                return
        
        structure_info = {
            'id': emdb_id,
            'title': f"EMDB结构 {emdb_id}",
            'resolution': None,
            'method': 'Cryo-EM',
            'organism': 'Unknown',
            'publication_date': None,
            'authors': [],
            'keywords': ['EMDB']
        }
        
        doc = self.document_generator.from_structure(structure_info)
        self.vector_indexer.add_document(doc)

    def _safe_get_attr(self, obj, attr_name, default=None):
        """安全地获取对象属性"""
        try:
            value = getattr(obj, attr_name, default)
            if value is None:
                return default
            return value
        except Exception:
            return default

    def retrieve(self, query: str, top_k: int = 10,
                 entity_types: List[EntityType] = None,
                 filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """检索相关文档 - 优先返回 content chunks 以提供更丰富的上下文"""
        self._ensure_initialized()
        start_time = time.time()

        try:
            # 执行搜索
            search_results = self.vector_indexer.search(query, entity_types, filters, top_k * 2)

            # 优先排序：content chunks 优先于 metadata 文档
            # 这样可以提供更丰富的上下文给 AI
            prioritized_results = []
            content_chunks = []
            metadata_docs = []

            for r in search_results:
                doc_type = r.metadata.get('doc_type', '') if r.metadata else ''
                if doc_type == 'content_chunk':
                    content_chunks.append(r)
                else:
                    metadata_docs.append(r)

            # 合并：content chunks 优先，然后是 metadata 文档
            prioritized_results = content_chunks + metadata_docs

            # 如果结果太多，限制数量
            if len(prioritized_results) > top_k:
                # 保持优先级：先取完所有 content chunks，再取 metadata docs
                final_results = prioritized_results[:top_k]
            else:
                final_results = prioritized_results

            # 构建知识图谱
            if self.knowledge_graph is not None:
                self.knowledge_graph.build_from_search_results(final_results)

            process_time = time.time() - start_time

            # 提取结构ID
            structure_ids = self.vector_indexer._extract_structure_ids(query)

            # 构建响应
            response = {
                'success': True,
                'query': query,
                'retrieved_documents': [
                    {
                        'doc_id': r.doc_id,
                        'entity_type': r.entity_type.value,
                        'source_id': r.source_id,
                        'title': r.title,
                        'content': r.content,
                        'similarity_score': r.similarity_score,
                        'metadata': r.metadata,
                        'rank': r.rank,
                        'is_content_chunk': r.metadata.get('doc_type', '') == 'content_chunk' if r.metadata else False
                    }
                    for r in final_results
                ],
                'total_results': len(final_results),
                'content_chunks_count': len(content_chunks),
                'detected_structures': structure_ids,
                'process_time': process_time,
                'knowledge_graph_stats': self.knowledge_graph.get_graph_statistics() if self.knowledge_graph else {}
            }

            # 添加结构增强信息
            if structure_ids:
                structure_info = self._get_enhanced_structure_info(structure_ids)
                response['structure_enhancement'] = structure_info

            logger.info(f"✅ 检索完成: {len(final_results)} 个结果 ({process_time:.2f}s), "
                        f"含 {len(content_chunks)} 个 content chunks")
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"检索失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'process_time': process_time
            }
    
    def _get_enhanced_structure_info(self, structure_ids: List[str]) -> Dict[str, Any]:
        """获取增强的结构信息"""
        try:
            if not self.structure_fetcher:
                return {'available': False, 'message': '结构管理器不可用'}
            
            # 获取元数据
            pdb_metadata, emdb_metadata = self.structure_fetcher.fetch_all_metadata(structure_ids, use_cache=True)
            
            structure_info = []
            
            # 处理PDB结构
            for pdb_id, metadata in pdb_metadata.items():
                info = {
                    'id': pdb_id,
                    'type': 'pdb',
                    'title': getattr(metadata, 'title', f"PDB {pdb_id}"),
                    'resolution': getattr(metadata, 'resolution', None),
                    'method': getattr(metadata, 'method', 'X-ray crystallography'),
                    'organism': getattr(metadata, 'organism', 'Unknown'),
                    'publication_date': getattr(metadata, 'deposition_date', None),
                    'authors': getattr(metadata, 'authors', [])
                }
                structure_info.append(info)
            
            # 处理EMDB结构 - 修复：使用安全的方式获取属性
            for emdb_id, metadata in emdb_metadata.items():
                # 安全地获取所有属性
                info = {
                    'id': emdb_id,
                    'type': 'emdb',
                    'title': getattr(metadata, 'title', f"EMDB {emdb_id}"),
                    'resolution': getattr(metadata, 'resolution', None),
                    'method': getattr(metadata, 'method', getattr(metadata, 'technique', 'Cryo-EM')),
                    'organism': getattr(metadata, 'organism', 'Unknown'),
                    'publication_date': getattr(metadata, 'deposition_date', None),
                    'authors': getattr(metadata, 'authors', [])  # 安全获取 authors 属性
                }
                structure_info.append(info)
            
            return {
                'available': True,
                'structures': structure_info,
                'total': len(structure_info),
                'pdb_count': len(pdb_metadata),
                'emdb_count': len(emdb_metadata)
            }
            
        except Exception as e:
            logger.error(f"获取结构信息失败: {e}")
            return {'available': False, 'error': str(e)}
    
    def get_related_documents(self, doc_id: str, max_related: int = 5) -> List[Dict[str, Any]]:
        """获取相关文档"""
        try:
            doc = self.vector_indexer.get_document(doc_id)
            if not doc:
                return []
            
            # 获取知识图谱中的相关实体
            related_entities = self.knowledge_graph.get_related_entities(doc_id, max_depth=1) if self.knowledge_graph else []
            
            related_docs = []
            for entity in related_entities[:max_related]:
                related_doc = self.vector_indexer.get_document(entity['id'])
                if related_doc:
                    related_docs.append({
                        'doc_id': related_doc.doc_id,
                        'entity_type': related_doc.entity_type.value,
                        'title': related_doc.title,
                        'content': related_doc.content[:100],
                        'relationship': f"{doc.entity_type.value} -> {related_doc.entity_type.value}",
                        'distance': entity['distance']
                    })
            
            return related_docs
            
        except Exception as e:
            logger.error(f"获取相关文档失败: {e}")
            return []
    
    def get_system_statistics(self) -> Dict[str, Any]:
        """获取系统统计"""
        stats = {
            'index_statistics': self.vector_indexer.get_statistics(),
            'knowledge_graph': self.knowledge_graph.get_graph_statistics() if self.knowledge_graph else {},
            'capabilities': {
                'vector_search': True,
                'structure_enhancement': HAS_STRUCTURE_MANAGER,
                'knowledge_graph': True,
                'multi_entity_support': True
            }
        }
        
        return stats


# ---------- 索引配置 ----------
@dataclass
class LiteratureIndexConfig:
    """文献索引配置"""
    model_name: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    index_type: str = "flat"  # "flat", "ivf", "hnsw"
    chunk_size: int = 500
    chunk_overlap: int = 50
    max_literature_per_index: int = 10000
    enable_structure_enhancement: bool = True
    enable_knowledge_graph: bool = True

# ---------- 统一文献索引器 ----------
class IntegratedLiteratureIndexer:
    """统一文献索引器（向后兼容）"""
    
    def __init__(self, config: LiteratureIndexConfig = None):
        # 检查是否已经初始化过
        if hasattr(self, '_initialized') and self._initialized:
            logger.info("IntegratedLiteratureIndexer 已经初始化过，跳过重复初始化")
            return
            
        self.config = config or LiteratureIndexConfig()
        
        # 使用单例获取 RAG 系统
        self.rag_system = get_unified_rag_system()
        
        self._initialized = True
        logger.info("✅ 集成文献索引器初始化完成")
    
    def index_literature(self, literature_list: List[Dict[str, Any]], rebuild: bool = False, include_structures: bool = True) -> bool:
        """索引文献（向后兼容）"""
        return self.rag_system.index_literature(literature_list, rebuild=rebuild, include_structures=include_structures)

    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """搜索文献（向后兼容）- 返回 content chunks"""
        try:
            # UnifiedRAGSystem 使用 retrieve 方法，不是 search
            if hasattr(self.rag_system, 'retrieve'):
                from core.literature_index import EntityType
                # 调用 retrieve 方法
                result = self.rag_system.retrieve(
                    query,
                    top_k=top_k,
                    entity_types=[EntityType.LITERATURE]
                )
                # retrieve 返回的是 retrieved_documents，不是 documents
                docs = result.get('retrieved_documents', [])
                logger.info(f"Search found {len(docs)} documents, keys: {result.keys() if isinstance(result, dict) else 'not dict'}")
                return [
                    {
                        'id': doc.get('doc_id', ''),
                        'literature_id': doc.get('source_id', ''),
                        'score': doc.get('similarity_score', 0),
                        'title': doc.get('title', ''),
                        'content': doc.get('content', ''),
                        'entity_type': doc.get('entity_type', ''),
                        'is_content_chunk': doc.get('is_content_chunk', False),
                        'metadata': doc.get('metadata', {})
                    }
                    for doc in docs
                ]
            else:
                logger.warning("UnifiedRAGSystem 没有 retrieve 方法，回退到数据库搜索")
                return self._fallback_search(query, top_k)
        except Exception as e:
            logger.warning(f"搜索失败: {e}")
            return self._fallback_search(query, top_k)

    def _fallback_search(self, query: str, top_k: int = 10) -> List[Dict]:
        """回退到数据库搜索"""
        try:
            from core.literature_db import search_literature
            entries = search_literature(query, limit=top_k)
            return entries
        except Exception as e:
            logger.warning(f"回退搜索也失败: {e}")
            return []
    
    def _index_structures(self, structure_ids: List[str]):
        """索引结构数据（向后兼容）"""
        if hasattr(self.rag_system, '_index_structures'):
            return self.rag_system._index_structures(structure_ids)
        else:
            logger.warning("UnifiedRAGSystem 没有 _index_structures 方法")
            return None
    
    def clear_structure_index(self):
        """清除所有结构索引"""
        try:
            logger.info("开始清除结构索引...")
            
            # 确保向量索引器已初始化
            if not hasattr(self.rag_system, 'vector_indexer') or not self.rag_system.vector_indexer:
                logger.info("向量索引器未初始化，正在初始化...")
                # 初始化向量索引器
                vector_config = {
                    'model_name': getattr(self.config, 'model_name', 'all-MiniLM-L6-v2'),
                    'cache_dir': getattr(self.config, 'cache_dir', 'unified_vector_cache'),
                    'structure_cache_dir': getattr(self.config, 'structure_cache_dir', 'structure_cache')
                }
                from .literature_index import UnifiedVectorIndexer
                self.rag_system.vector_indexer = UnifiedVectorIndexer(model_name=vector_config)
                logger.info("✅ 向量索引器初始化完成")
            
            # 现在清除结构索引
            self.rag_system.vector_indexer.clear_structure_index()
            logger.info("✅ 结构索引清除完成")
                
        except Exception as e:
            logger.error(f"清除结构索引失败: {e}")
            raise e
    
    def search_literature(self, query: str, literature_ids: List[int] = None,
                         top_k: int = 10) -> List[Dict[str, Any]]:
        """搜索文献（向后兼容）"""
        result = self.rag_system.retrieve(query, top_k=top_k)
        
        if result['success']:
            return [
                {
                    'literature_id': doc.get('source_id', ''),
                    'title': doc.get('title', ''),
                    'similarity_score': doc.get('similarity_score', 0),
                    'composite_score': doc.get('similarity_score', 0),
                    'abstract': doc.get('content', ''),
                    'entity_type': doc.get('entity_type', '')
                }
                for doc in result['retrieved_documents']
                if doc.get('entity_type') == 'literature'
            ]
        else:
            return []
    
    def get_index_statistics(self) -> Dict[str, Any]:
        """获取索引统计（向后兼容）"""
        stats = self.rag_system.get_system_statistics()
        
        return {
            'total_documents': stats['index_statistics']['total_documents'],
            'by_entity_type': stats['index_statistics']['by_entity_type'],
            'index_size': stats['index_statistics']['index_size'],
            'structure_enhancement': {
                'enabled': self.config.enable_structure_enhancement,
                'structures': stats['index_statistics']['structure_mappings']['total_structures']
            }
        }

# ---------- 问答系统 ----------
class LiteratureQASystem:
    """文献问答系统（向后兼容）"""
    
    def __init__(self, indexer: IntegratedLiteratureIndexer = None):
        # 检查是否已经初始化过
        if hasattr(self, '_initialized') and self._initialized:
            logger.info("LiteratureQASystem 已经初始化过，跳过重复初始化")
            return
            
        # 如果传入 indexer 为 None，使用单例获取
        if indexer is None:
            from .literature_index import get_integrated_indexer
            self.indexer = get_integrated_indexer()
        else:
            self.indexer = indexer
            
        self.rag_system = self.indexer.rag_system
        
        # 尝试导入AI模块
        try:
            from core.agent_core import ask_literature_question, HAS_AGENT
            self.has_agent = HAS_AGENT
        except ImportError:
            self.has_agent = False
        
        self._initialized = True
        logger.info(f"✅ 文献问答系统初始化完成 (AI: {'可用' if self.has_agent else '不可用'})")
    
    def ask_question(self, question: str, literature_ids: List[int] = None,
                    context: str = None, top_k: int = 5) -> Dict[str, Any]:
        """回答问题（向后兼容）"""
        start_time = time.time()
        
        try:
            # 提取结构查询
            structure_ids = self._extract_structure_ids(question)
            
            # 检索相关文档
            filters = None
            if literature_ids:
                filters = {'source_id': [str(lid) for lid in literature_ids]}
            
            result = self.rag_system.retrieve(question, top_k=top_k, filters=filters)
            
            if not result['success'] or not result['retrieved_documents']:
                return {
                    "success": False,
                    "answer": "没有找到相关的文献信息。",
                    "sources": [],
                    "process_time": time.time() - start_time
                }
            
            # 构建上下文
            context = self._build_context(result['retrieved_documents'], question, structure_ids)
            
            # 生成答案
            if self.has_agent and context:
                answer = self._generate_ai_answer(question, context)
            else:
                answer = self._generate_simple_answer(result['retrieved_documents'], question)
            
            process_time = time.time() - start_time
            
            return {
                "success": True,
                "question": question,
                "answer": answer,
                "sources": [
                    {
                        "title": doc.get('title', ''),
                        "content": doc.get('content', '')[:200],
                        "similarity_score": doc.get('similarity_score', 0)
                    }
                    for doc in result['retrieved_documents']
                ],
                "detected_structures": structure_ids,
                "process_time": process_time
            }
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"问答失败: {e}")
            return {
                "success": False,
                "answer": f"抱歉，回答问题失败: {str(e)}",
                "sources": [],
                "process_time": process_time
            }
    
    def _extract_structure_ids(self, text: str) -> List[str]:
        """提取结构ID"""
        # 使用向量索引器的提取方法
        return self.rag_system.vector_indexer._extract_structure_ids(text)
    
    def _build_context(self, documents: List[Dict], question: str, structure_ids: List[str]) -> str:
        """构建上下文"""
        context_parts = []
        
        context_parts.append(f"用户问题: {question}")
        
        if structure_ids:
            context_parts.append(f"检测到的结构ID: {', '.join(structure_ids)}")
        
        context_parts.append("\n相关文献信息:")
        
        for i, doc in enumerate(documents[:3]):
            title = doc.get('title', '')
            content = doc.get('content', '')
            score = doc.get('similarity_score', 0)
            
            context_parts.append(f"\n[{i+1}] {title} (相关度: {score:.2f})")
            context_parts.append(f"摘要: {content[:300]}")
        
        return "\n".join(context_parts)
    
    def _generate_ai_answer(self, question: str, context: str) -> str:
        """使用AI生成答案"""
        try:
            from core.agent_core import ask_literature_question
            
            prompt = f"{context}\n\n请根据以上文献信息回答问题: {question}"
            result = ask_literature_question(prompt, context)
            
            if isinstance(result, dict) and result.get("success"):
                return result.get("answer", "")
            else:
                return self._generate_simple_answer([], question)
            
        except Exception as e:
            logger.error(f"AI答案生成失败: {e}")
            return self._generate_simple_answer([], question)
    
    def _generate_simple_answer(self, documents: List[Dict], question: str) -> str:
        """生成简单答案"""
        if not documents:
            return "没有找到相关的文献信息。"
        
        answer_parts = []
        answer_parts.append(f"关于问题: {question}")
        answer_parts.append(f"我找到了 {len(documents)} 篇相关文献:")
        
        for i, doc in enumerate(documents[:3]):
            title = doc.get('title', '相关文献')
            content = doc.get('content', '')
            
            answer_parts.append(f"\n{i+1}. **{title}**")
            answer_parts.append(f"   相关内容: {content[:200]}...")
        
        return "\n".join(answer_parts)

# ---------- 增强数据库连接器（用于向后兼容） ----------
class EnhancedDatabaseConnector:
    """增强数据库连接器（向后兼容）"""
    
    def __init__(self, database_url=None):
        self.database_url = database_url
        logger.info("✅ 增强数据库连接器初始化完成（向后兼容）")
    
    def connect(self):
        """连接数据库"""
        logger.info("增强数据库连接器: 连接数据库（向后兼容）")
        return True
    
    def disconnect(self):
        """断开数据库连接"""
        logger.info("增强数据库连接器: 断开数据库连接（向后兼容）")
        return True
    
    def execute_query(self, query, params=None):
        """执行查询"""
        logger.info(f"增强数据库连接器: 执行查询（向后兼容）")
        return []

# ---------- 全局实例 ----------
_UNIFIED_RAG_SYSTEM_INSTANCE = None
_UNIFIED_RAG_SYSTEM_LOCK = threading.Lock()

def get_unified_rag_system(config: Dict[str, Any] = None) -> UnifiedRAGSystem:
    """获取统一RAG系统实例（线程安全单例）"""
    global _UNIFIED_RAG_SYSTEM_INSTANCE
    
    if _UNIFIED_RAG_SYSTEM_INSTANCE is not None:
        return _UNIFIED_RAG_SYSTEM_INSTANCE
    
    with _UNIFIED_RAG_SYSTEM_LOCK:
        if _UNIFIED_RAG_SYSTEM_INSTANCE is None:
            _UNIFIED_RAG_SYSTEM_INSTANCE = UnifiedRAGSystem(config)
        
        return _UNIFIED_RAG_SYSTEM_INSTANCE

_INTEGRATED_INDEXER_INSTANCE = None
_INTEGRATED_INDEXER_LOCK = threading.Lock()

def get_integrated_indexer(config: Dict[str, Any] = None) -> IntegratedLiteratureIndexer:
    """获取集成索引器实例（线程安全单例）"""
    global _INTEGRATED_INDEXER_INSTANCE
    
    if _INTEGRATED_INDEXER_INSTANCE is not None:
        return _INTEGRATED_INDEXER_INSTANCE
    
    with _INTEGRATED_INDEXER_LOCK:
        if _INTEGRATED_INDEXER_INSTANCE is None:
            _INTEGRATED_INDEXER_INSTANCE = IntegratedLiteratureIndexer(config)
        
        return _INTEGRATED_INDEXER_INSTANCE

# 添加获取向量索引器的函数
def get_unified_vector_indexer(config: Dict[str, Any] = None) -> UnifiedVectorIndexer:
    """获取统一向量索引器实例（使用简单单例）"""
    config = config or {}
    return SimpleSingleton.get_instance(UnifiedVectorIndexer, config)


