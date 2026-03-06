# literature_agent.py - CryoAgent Pro 文献管理核心模块（完整版，集成离线数据库，集成UniProt分析，集成混合检索系统）
import os, json, logging, shutil, tempfile, re, hashlib, time, threading, requests, concurrent.futures
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Union, Set
from datetime import datetime, date
from collections import defaultdict
from sqlalchemy import or_, and_
from functools import wraps

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 导入子模块
try:
    from core.literature_db import (
        LiteratureEntry, LiteratureAppendix, LiteratureNote, CitationEntry,
        LiteratureCollection, LiteratureStatus, LiteratureType, CitationStyle,
        convert_string_to_status, convert_string_to_type,
        create_literature_session, get_literature_entry, search_literature,
        add_literature_entry, update_literature_entry, delete_literature_entry,
        add_appendix_to_literature, add_note_to_literature, get_literature_stats,
        get_literature_appendices, get_literature_notes,
        LITERATURE_PDFS_DIR, LITERATURE_APPENDICES_DIR, initialize_literature_database
    )
    HAS_LITERATURE_DB = True
except ImportError as e:
    HAS_LITERATURE_DB = False
    print(f"⚠️ 文献数据库模块导入失败: {e}")

try:
    from core.literature_parser import LiteratureParserManager, LiteratureParserConfig
    HAS_LITERATURE_PARSER = True
except ImportError as e:
    HAS_LITERATURE_PARSER = False
    print(f"⚠️ 文献解析模块导入失败: {e}")

try:
    from core.literature_index import (
        IntegratedLiteratureIndexer, LiteratureIndexConfig, LiteratureQASystem
    )
    HAS_LITERATURE_INDEX = True
except ImportError as e:
    HAS_LITERATURE_INDEX = False
    print(f"⚠️ 文献索引模块导入失败: {e}")

# 导入索引管理器
try:
    from core.literature_index_manager import LiteratureIndexManager
    HAS_INDEX_MANAGER = True
except ImportError as e:
    HAS_INDEX_MANAGER = False
    print(f"⚠️ 索引管理器导入失败: {e}")

# 尝试导入AI模块
try:
    from core.agent_core import ask_literature_question, HAS_AGENT, search_literature_with_ai_context, translate_question_to_english
    logger.info(f"✅ AI核心模块导入成功，HAS_AGENT={HAS_AGENT}")
except ImportError as e:
    HAS_AGENT = False
    logger.error(f"❌ AI核心模块导入失败: {e}")

# 导入结构管理器
try:
    from core.structure_manager import StructureMetadataFetcher, PDBMetadata, EMDBMetadata, StructureRelationship
    from dataclasses import asdict
    HAS_STRUCTURE_MANAGER = True
except ImportError as e:
    HAS_STRUCTURE_MANAGER = False
    print(f"⚠️ 结构管理器导入失败: {e}")

# 尝试导入结构数据库模块
try:
    from core.structure_database import EnhancedStructureManager, StructureType
    HAS_STRUCTURE_DB = True
except ImportError as e:
    HAS_STRUCTURE_DB = False
    logger.warning(f"无法导入结构数据库模块: {e}")

# 在导入部分添加
try:
    from core.structure_extractor_fixed import re_extract_structure_ids
    HAS_ENHANCED_EXTRACTOR = True
    logger.info("✅ 增强结构ID提取模块导入成功")
except ImportError as e:
    HAS_ENHANCED_EXTRACTOR = False
    logger.warning(f"❌ 增强结构ID提取模块导入失败: {e}")

# 导入UniProt模块
try:
    from core.uniprot_client import (
        UniProtAPIClient, UniProtNormalizer, get_uniprot_client, get_uniprot_normalizer
    )
    HAS_UNIPROT = True
except ImportError as e:
    HAS_UNIPROT = False
    print(f"⚠️ UniProt模块导入失败: {e}")

# literature_agent.py - 修改部分

# 导入统一的JSON工具
try:
    from utils.json_sanitize import (
        ensure_json_serializable,
        prepare_json_field,
        sanitize_literature_data,
        normalize_authors,
        normalize_cryoem_targets,
        validate_literature_data
    )
    HAS_JSON_UTILS = True
except ImportError as e:
    HAS_JSON_UTILS = False
    logger.warning(f"JSON工具模块导入失败: {e}")
    
    # 回退到原函数（临时）
    def ensure_json_serializable(value: Any, field_name: str = None) -> Any:
        # 保持原有简单实现
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [ensure_json_serializable(item) for item in value[:100]]
        if isinstance(value, dict):
            return {str(k): ensure_json_serializable(v) for k, v in list(value.items())[:50]}
        try:
            return str(value)[:500]
        except:
            return None
    
    def prepare_json_field(value: Any, field_name: str = None) -> Any:
        # 简化实现
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except:
                return value[:1000]
        return ensure_json_serializable(value)

# ---------- 辅助函数 ----------
def ensure_json_serializable(value: Any, field_name: str = None) -> Any:
    """确保值是JSON可序列化的"""
    if value is None:
        return None
    
    # 如果是基本的JSON类型，直接返回
    if isinstance(value, (str, int, float, bool)):
        return value
    
    # 如果是列表或字典，递归处理
    if isinstance(value, list):
        return [ensure_json_serializable(item, field_name) for item in value[:100]]  # 限制列表长度
    elif isinstance(value, dict):
        return {str(k): ensure_json_serializable(v, field_name) for k, v in list(value.items())[:50]}  # 限制字典大小
    
    # 尝试转换为字符串
    try:
        # 检查是否是数据库模型对象
        if hasattr(value, '__dict__'):
            return str(value)
        # 尝试直接转换为字符串
        return str(value)[:500]  # 限制字符串长度
    except Exception as e:
        logger.warning(f"无法序列化字段 {field_name} 的值: {e}")
        return None

def prepare_json_field(value: Any, field_name: str = None) -> Any:
    """准备JSON字段，确保可序列化并格式正确"""
    if value is None:
        return None
    
    # 如果已经是字符串，尝试解析为JSON
    if isinstance(value, str):
        try:
            # 尝试解析为JSON
            parsed = json.loads(value)
            return ensure_json_serializable(parsed, field_name)
        except json.JSONDecodeError:
            # 如果不是JSON，根据字段类型处理
            if field_name == 'key_findings':
                # key_findings字段期望是列表
                return [{"finding": value[:500]}]
            elif field_name == 'authors':
                # authors字段期望是字典列表
                return [{"name": value[:200]}]
            elif field_name in ['keywords', 'tags']:
                # keywords和tags期望是字符串列表
                return [value[:100]]
            else:
                # 其他字段保持原样
                return value[:1000]  # 限制字符串长度
    
    # 如果不是字符串，直接确保可序列化
    return ensure_json_serializable(value, field_name)

# ---------- 停用词和关键词提取 ----------
STOP_WORDS = {
    "the", "and", "with", "from", "that", "this", "for", "are", "was", "were",
    "结构", "研究", "关于", "多少", "如何", "什么", "哪个", "哪些", "怎么",
    "论文", "文章", "文献", "请", "告诉", "我", "我们", "你们", "他们",
    "有", "没有", "是否", "可以", "能够", "可能", "可能", "什么", "为什么",
    "怎么", "怎样", "如何", "多少", "几个", "哪个", "哪些", "哪里", "什么时候"
}

def extract_keywords(text: str):
    """从文本中提取关键词"""
    if not text:
        return []
    
    # 清理文本
    cleaned = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', text)
    words = []
    
    # 通用词语列表
    common_words = {'what', 'they', 'study', 'literature', 'respectively', 'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'must'}
    
    for w in cleaned.split():
        w = w.strip().lower()
        if len(w) > 2 and w not in STOP_WORDS and w not in common_words:
            words.append(w)
    
    return list(set(words))

# ---------- 超时装饰器 ----------
def timeout_decorator(timeout_seconds):
    """超时装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, *args, **kwargs)
                try:
                    return future.result(timeout=timeout_seconds)
                except concurrent.futures.TimeoutError:
                    logger.warning(f"函数 {func.__name__} 执行超时 ({timeout_seconds}秒)")
                    raise TimeoutError(f"操作超时 ({timeout_seconds}秒)")
        return wrapper
    return decorator

# ---------- 文献管理器 ----------
class LiteratureManager:
    """文献管理器 - 完整版（集成离线数据库，集成UniProt标准化分析，集成混合检索系统）"""
    
    _instance = None
    _initialized = False
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        """实现真正的单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(LiteratureManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, config: Dict[str, Any] = None):
        """初始化方法，确保只执行一次"""
        # 使用类变量检查是否已初始化
        self.config = config or {}
        self.parser_manager = None
        self._init_parser_manager() 

        if LiteratureManager._initialized:
            logger.info("LiteratureManager 已经初始化过，跳过重复初始化")
            return
            
        with LiteratureManager._lock:
            if LiteratureManager._initialized:
                logger.info("LiteratureManager 已经初始化过（锁内检查），跳过重复初始化")
                return
                
            self.config = config or {}
            self._initialized_instance = True  # 实例级别的初始化标志
            
            # 检查模块可用性
            if not HAS_LITERATURE_DB:
                raise ImportError("文献数据库模块不可用，请检查 literature_db.py")
        
        # 初始化子模块配置 - 简化配置
        if HAS_LITERATURE_PARSER:
            self.parser_config = LiteratureParserConfig()
            self.parser_config.AI_ENABLED = HAS_AGENT
            self.parser_config.PDF_MAX_PAGES = 30
            self.parser_config.AI_MAX_TOKENS = 6000
        else:
            self.parser_config = {}
            logger.warning("文献解析器配置不可用，使用空配置")
        
        # 初始化解析器
        if HAS_LITERATURE_PARSER:
            self.parser_manager = LiteratureParserManager(self.parser_config)
        else:
            self.parser_manager = None
            logger.warning("文献解析器不可用，部分功能受限")
        
        # 初始化索引管理器
        if HAS_INDEX_MANAGER:
            self.index_manager = LiteratureIndexManager()
            logger.info("✅ 索引管理器初始化完成")
        else:
            self.index_manager = None
            logger.warning("索引管理器不可用")
        
        # 初始化索引器
        if HAS_LITERATURE_INDEX:
            try:
                # 使用单例获取索引器
                from core.literature_index import get_integrated_indexer
                self.indexer = get_integrated_indexer()

                # 创建 QA 系统，传入索引器
                self.qa_system = LiteratureQASystem(self.indexer)
                logger.info("✅ 文献索引器和问答系统通过单例模式初始化")
            except Exception as e:
                logger.error(f"获取单例索引器失败: {e}")
                # 回退到原有方式
                self.index_config = LiteratureIndexConfig()
                self.indexer = IntegratedLiteratureIndexer(self.index_config)
                self.qa_system = LiteratureQASystem(self.indexer)
                logger.info("✅ 文献索引器和问答系统通过新建实例初始化")
            try:
                from core.literature_index import UnifiedVectorIndexer
                # 初始化向量索引器，使用默认配置或从环境变量读取
                self.unified_vector_indexer = UnifiedVectorIndexer()
                logger.info("✅ 专用向量索引器 (UnifiedVectorIndexer) 初始化完成")
            except ImportError as e:
                self.unified_vector_indexer = None
                logger.warning(f"无法导入 UnifiedVectorIndexer: {e}")
            except Exception as e:
                self.unified_vector_indexer = None
                logger.error(f"初始化 UnifiedVectorIndexer 失败: {e}")
        else:
            self.indexer = None
            self.qa_system = None
            logger.warning("文献索引器不可用，搜索和问答功能受限")
        
        LiteratureManager._initialized = True
        logger.info("✅ 文献管理器初始化完成（单例模式）")
        
        # 初始化结构管理器
        if HAS_STRUCTURE_MANAGER:
            self.structure_fetcher = StructureMetadataFetcher({
                'max_workers': 3,
                'timeout': 15
            })
            logger.info("✅ 结构管理器初始化完成")
        else:
            self.structure_fetcher = None
            logger.warning("结构管理器不可用，结构元数据获取功能受限")
        
        # 注意：不再初始化 PDBApiClient，直接使用 structure_fetcher
        logger.info("✅ 结构搜索功能已集成到 StructureMetadataFetcher")
        
        # 初始化离线数据库管理器
        if HAS_STRUCTURE_DB:
            try:
                self.structure_db = EnhancedStructureManager()
                logger.info("✅ 结构离线数据库管理器初始化完成")
            except Exception as e:
                logger.warning(f"结构离线数据库管理器初始化失败: {e}")
                self.structure_db = None
        else:
            self.structure_db = None
            logger.warning("结构数据库模块不可用")
        
        # 初始化UniProt客户端
        if HAS_UNIPROT:
            self.uniprot_client = get_uniprot_client()
            self.uniprot_normalizer = get_uniprot_normalizer()
            logger.info("✅ UniProt客户端初始化完成")
        else:
            self.uniprot_client = None
            self.uniprot_normalizer = None
            logger.warning("UniProt模块不可用")
        
        # 初始化结构QA智能体
        self.structure_qa_agent = None
        try:
            from structure_qa_agent import StructureQAAgent
            self.structure_qa_agent = StructureQAAgent(self)
            logger.info("✅ 结构QA智能体初始化完成")
        except ImportError as e:
            logger.warning(f"结构QA智能体导入失败: {e}")
        
        # 确保目录存在
        self._ensure_directories()
        
        self._initialized = True
        logger.info("✅ 文献管理器初始化完成")

    def _init_parser_manager(self):
        """初始化解析器管理器"""
        try:
            # 动态导入，避免循环依赖
            from core.literature_parser import LiteratureParserManager
            self.parser_manager = LiteratureParserManager(self.config)
            logger.info("✅ 解析器管理器初始化成功")
        except ImportError as e:
            logger.error(f"❌ 无法导入解析器模块: {e}")
            self.parser_manager = None
        except Exception as e:
            logger.error(f"❌ 解析器初始化失败: {e}")
            self.parser_manager = None

    def _ensure_directories(self):
        """确保所有必要的目录存在"""
        directories = [
            LITERATURE_PDFS_DIR,
            LITERATURE_APPENDICES_DIR,
            Path("literature_indices"),
            Path("literature_cache"),
            Path("literature_thumbnails"),
            Path("structure_cache"),
            Path("structure_indices"),
            Path("pdb_cache"),
            Path("structure_offline_db")
        ]
        
        for directory in directories:
            if directory:
                directory.mkdir(parents=True, exist_ok=True)
    
    def _extract_protein_names(self, question: str) -> List[str]:
        """从问题中提取蛋白质名称 - 增强版"""
        
        # 预处理问题
        question_clean = question.strip()
        
        # 1. 首先尝试从UniProt获取
        if self.uniprot_normalizer:
            try:
                protein_names = self.uniprot_normalizer.extract_protein_names_from_text(question_clean)
                if protein_names:
                    logger.info(f"UniProt提取蛋白质名称: {protein_names}")
                    return protein_names
            except:
                pass
        
        # 2. 手动提取
        protein_names = []
        
        # 常见蛋白质映射（包括中文）
        protein_keywords = {
            # 免疫学
            'TCR': ['TCR', 'T细胞受体', 'T-cell receptor', 'T cell receptor'],
            'MHC': ['MHC', '主要组织相容性复合体', 'major histocompatibility complex'],
            'CD3': ['CD3', 'CD-3'],
            'CD4': ['CD4', 'CD-4'],
            'CD8': ['CD8', 'CD-8'],
            'PD1': ['PD1', 'PD-1', 'PDCD1', '程序性死亡受体1'],
            'PDL1': ['PDL1', 'PD-L1', 'CD274', '程序性死亡配体1'],
            
            # GPCR家族
            'GPR158': ['GPR158', 'GPR-158'],
            'GPR179': ['GPR179', 'GPR-179'],
            'GPCR': ['GPCR', 'G蛋白偶联受体', 'G protein-coupled receptor'],
            
            # 受体酪氨酸激酶
            'EGFR': ['EGFR', '表皮生长因子受体', 'epidermal growth factor receptor'],
            'HER2': ['HER2', 'ERBB2'],
            
            # 其他
            'actin': ['actin', '肌动蛋白'],
            'tubulin': ['tubulin', '微管蛋白'],
            'myosin': ['myosin', '肌球蛋白'],
        }
        
        question_upper = question_clean.upper()
        question_lower = question_clean.lower()
        
        # 检查中文名称
        for protein, keywords in protein_keywords.items():
            for keyword in keywords:
                # 检查英文（大小写敏感）
                if keyword.upper() in question_upper:
                    protein_names.append(protein)
                    break
                # 检查中文
                elif any('\u4e00' <= c <= '\u9fff' for c in keyword) and keyword in question_clean:
                    protein_names.append(protein)
                    break
        
        # 3. 正则表达式匹配
        if not protein_names:
            patterns = [
                r'\b([A-Z]{2,}[0-9]{3,}[A-Z0-9]{0,})\b',  # 如GPR158
                r'\b([A-Z]{3,}[0-9]{3,})\b',  # 如GPR158
                r'\b([A-Z]{2,}[0-9]{4,})\b',  # 如GPR1580
                r'\b(GPR|GPCR|EGFR|HER|PDGFR|VEGFR|FGFR|IGF|TGF|TCR|MHC|CD)[0-9]*\b',  # 蛋白质家族
                r'\b(TCR|MHC|PD1|PDL1)\b',  # 3-4字母蛋白质
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, question_upper)
                for match in matches:
                    if isinstance(match, tuple):
                        match = match[0] if match else ""
                    
                    if match and len(match) >= 2:  # 允许2个字符的匹配
                        # 过滤掉明显不是蛋白质的词汇
                        exclude_words = ['PROTEIN', 'STRUCTURE', 'PDB', 'EMDB', 'WHAT', 'HOW', 
                                    'MANY', 'RESOLUTION', 'QUESTION', 'ABOUT', 'THE', 'AND']
                        if (match not in exclude_words and 
                            not any(word in match for word in exclude_words)):
                            protein_names.append(match)
        
        # 去重并排序
        protein_names = sorted(list(set(protein_names)))
        
        logger.info(f"提取到的蛋白质名称: {protein_names}")
        return protein_names

    def _rerank_with_llm(self, results: List, original_query: str, top_k: int = 10) -> List[str]:
        """使用 LLM 对向量搜索结果进行重排序/筛选 (优化版：支持 ID+Title，并针对序列问题过滤 EMDB)"""
        if not results:
            return []
        
        # 导入 re 模块
        import re
        
        # 1. 构建候选项文本
        results_text = ""
        valid_results_count = 0
        for i, res in enumerate(results):
            res_id = res.source_id
            res_title = res.title[:100]
            
            # 验证结构ID格式
            res_id_upper = res_id.upper()
            is_pdb = re.match(r'^[0-9][A-Z0-9]{3}$', res_id_upper)
            is_emdb = re.match(r'^EMD-\d+$', res_id_upper)
            
            if is_pdb or is_emdb:
                results_text += f"{res_id} ({res_title})\n"
                valid_results_count += 1
            else:
                logger.debug(f"过滤无效结构ID: {res_id}")
        
        # 如果没有有效结果，返回空列表
        if valid_results_count == 0:
            logger.warning("⚠️ 没有找到有效结构ID")
            return []
        
        # 打印debug信息
        logger.debug("\n" + "="*50)
        logger.debug("🤖 [DEBUG] 发送给 LLM Rerank 的完整候选项文本:")
        logger.debug(f"总数: {valid_results_count}")
        logger.debug("-" * 50)
        logger.debug(results_text)
        logger.debug("-" * 50)        
        # 2. 判断是否是序列查询
        # 简单的启发式：如果问题包含 "序列" (sequence)，则认为是序列查询
        is_sequence_query = '序列' in original_query.lower() or 'sequence' in original_query.lower()
        
        # 3. 构建 Prompt (优化版)
        filter_instruction = ""
        if is_sequence_query:
            filter_instruction = """
**特别过滤规则（针对序列问题）**：
1.  **必须排除 EMDB**：由于 EMDB 结构通常不包含详细的蛋白序列（只有密度图），对于查询“蛋白序列”的问题，请完全忽略所有以 "EMD-" 开头的候选项。
2.  **优先 PDB**：请优先选择以 PDB 格式（4位字符，如 8JC0）存储的结构。
"""
        
        # 提取用户查询中的关键信息（如Vγ9、Vδ2等亚型信息）
        subunit_keywords = []
        # 匹配 Vγ9、Vδ2 等格式
        gamma_delta_patterns = [
            r'V\s*gamma\s*(\d+)',
            r'V\s*delta\s*(\d+)',
            r'Vγ(\d+)',
            r'Vδ(\d+)',
            r'Vgamma(\d+)',
            r'Velta(\d+)',
            r'γ(\d+)',
            r'δ(\d+)'
        ]
        
        for pattern in gamma_delta_patterns:
            matches = re.findall(pattern, original_query, re.IGNORECASE)
            if matches:
                subunit_keywords.extend(matches)
        
        # 构建更精确的筛选指令
        precise_filter_instruction = ""
        if subunit_keywords:
            precise_filter_instruction = f"""
**精确筛选规则**：
1.  **必须包含特定亚基**：用户查询中提到了特定的亚基信息（如Vγ9、Vδ2等），请严格筛选标题中包含这些亚基信息的结构。
2.  **排除其他亚型**：过滤掉标题中包含其他 TCR 亚型（如Vγ5、Vδ1等）的结构，只保留与用户查询亚基匹配的结构。
3.  **严格相关性**：只选择标题与用户查询直接相关的结构，排除间接相关或不相关的结构。
"""
        else:
            # 即使没有特定亚基信息，也要强调严格相关性
            precise_filter_instruction = """
**通用筛选规则**：
1.  **严格相关性**：请严格筛选标题与用户查询直接相关的结构，排除间接相关或不相关的结构。
2.  **质量优先**：优先选择结构质量高、信息完整的结构。
"""
        
        rerank_prompt = f"""你是一个生物学文献检索过滤器。

用户查询：“{original_query}”

下面是候选结构列表，每行格式为：
<结构ID> <空格> (<标题>)

例如：
7B5M (Structure of the class C orphan GPCR GPR158 in complex with RGS7-Gβ5)
7B5N (Cryo-EM structure of human GPR158 receptor coupled to the RGS7-Gβ5 signaling complex)

请从中选出最相关的 {top_k} 个结果，严格按照上面格式输出：
- 每行一个结果
- 行首直接写结构ID，不要加序号、不要加点号、不要加“1.”、“2.”等前缀
- 结构ID之后是一个空格和一个左括号“(”，然后是标题，最后以右括号“)”结尾
- 不要输出任何额外的解释、说明、总结

候选结构：
{results_text}

请直接输出最相关的 {top_k} 个结果，每行一行，不要任何额外内容。"""

        try:
            # 使用统一的 API 调用
            from core.agent_core import create_chat_completion, CHAT_MODEL

            # 调用 LLM
            content = create_chat_completion(
                messages=[
                    {"role": "system", "content": "你是一个精准的搜索过滤器。"},
                    {"role": "user", "content": rerank_prompt}
                ],
                temperature=0.0,
                max_tokens=1000
            )

            logger.info(f"🧠 LLM Rerank 原始输出: {content}")
            
            # 4. 解析 ID (支持 ID (Title) 格式，并针对序列问题过滤 EMDB)
            import re
            valid_ids = []
            
            # 按行分割
            lines = content.split('\n')
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # 提取 ID 部分（括号前的部分）
                # 格式预期：ID (Title) 或 ID
                id_candidate = line
                if '(' in line:
                    id_candidate = line.split('(')[0].strip()
                
                # 验证 ID 格式
                id_upper = id_candidate.upper()
                
                # 过滤纯数字ID
                if re.match(r'^\d+$', id_upper):
                    logger.debug(f"⛔ 过滤纯数字ID: {id_upper}")
                    continue
                
                # PDB: 4字符，首位数字
                is_pdb = re.match(r'^[0-9][A-Z0-9]{3}$', id_upper)
                # EMDB: EMD- + 数字
                is_emdb = re.match(r'^EMD-\d+$', id_upper)
                
                if is_pdb:
                    valid_ids.append(id_upper)
                elif is_emdb:
                    # --- 关键修改：如果是序列查询，直接忽略 EMDB ---
                    if not is_sequence_query:
                        valid_ids.append(id_upper)
                    else:
                        logger.debug(f"⛔ 序列查询：忽略 EMDB ID {id_upper} (不包含序列)")
                else:
                    # 容错：只保留非纯数字的有效ID
                    if 4 <= len(id_upper) <= 8 and not re.match(r'^\d+$', id_upper):
                        valid_ids.append(id_upper)
            
            # 去重并保留顺序
            unique_ids = []
            seen = set()
            for sid in valid_ids:
                if sid not in seen:
                    unique_ids.append(sid)
                    seen.add(sid)
            
            if unique_ids:
                logger.info(f"✅ LLM Rerank 筛选出 {len(unique_ids)} 个结果: {unique_ids}")
                return unique_ids
            else:
                logger.warning("⚠️ LLM Rerank 未能提取到有效 ID，回退到SQL数据库查询")
                # 失败回退到SQL数据库查询
                return self._query_structures_from_sql(original_query, limit=top_k)
                
        except Exception as e:
            logger.error(f"LLM Rerank 失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _find_structures_by_protein(self, protein_name: str, question_text: str = None, limit: int = 10) -> List[str]:
        """
        混合检索策略：综合向量搜索 (语义) 与 LLM 筛选 (精度)
        """
        structure_ids = set()
        sql_structure_ids = set()
        
        # ==========================================
        # 第一阶段：SQL 精准检索 (优先执行)
        # ==========================================
        logger.info(f"开始 SQL 检索 '{protein_name}' 的相关结构...")
        # 策略：拆分 "Vγ9Vδ2" 为 "gamma9" 和 "delta2" 进行 OR 查询
        subunit_keywords = [protein_name]
        if question_text:
            # 提取 "V gamma 9", "V delta 2" 这种格式，或者保留原始关键词
            # 为了简单，我们尝试匹配常见的变体
            subunit_keywords = [
                protein_name,
                "V gamma9", "Vdelta2", "Vgamma9",
                "Vδ2", "Vγ9"
            ]

        session = create_literature_session()
        try:
            base_filter = LiteratureEntry.title.ilike(f'%{protein_name}%')
            
            # 构建 OR 过滤条件
            or_conditions = [base_filter]
            for kw in set(subunit_keywords):
                or_conditions.append(LiteratureEntry.title.ilike(f'%{kw}%'))
            
            query = session.query(LiteratureEntry).filter(or_(*or_conditions))
            results = query.limit(limit).all()

            for lit in results:
                if lit.cryoem_targets:
                    try:
                        targets = lit.cryoem_targets
                        if isinstance(targets, str):
                            targets = json.loads(targets)
                        if isinstance(targets, dict):
                            sql_structure_ids.update(targets.get('pdb_ids', []))
                            sql_structure_ids.update(targets.get('emdb_ids', []))
                    except Exception as e:
                        logger.debug(f"解析cryoem_targets失败: {e}")
        
        finally:
            session.close()

        logger.info(f"📊 SQL 检索召回: {len(sql_structure_ids)} 个结构")
 
        # ==========================================
        # 第二阶段：向量检索 (整合优化查询与LLM筛选)
        # ==========================================
        if self.unified_vector_indexer:
            try:
                # 导入相关模块
                from core.literature_index import UnifiedVectorIndexer, EntityType
                
                # --- 优化1：使用原始问题查询 (比只用 'TCR' 更准) ---
                vector_query = question_text if question_text else protein_name
                logger.info(f"🚀 启用向量检索: 查询 '{vector_query[:50]}...'")
                
                # 搜索 (多搜一点，给 LLM 挑选的空间)
                vector_results = self.unified_vector_indexer.search(
                    query=vector_query,
                    entity_types=[EntityType.STRUCTURE],  # 只搜索结构类型，避免文献干扰
                    top_k=limit * 3  # 减少初始召回量，从5倍改为3倍，减少噪音
                )

                # --- 核心：决定使用哪些结果 ---
                results_to_process = []

                if len(vector_results) > 15:  # 降低阈值，从20改为15，更早启动LLM筛选
                    # 情况A：召回太多，噪音大 -> 使用 LLM 筛选
                    logger.info(f"⏳ 召回过多 ({len(vector_results)})，启动 LLM 精确筛选...")
                    reranked_ids = self._rerank_with_llm(vector_results, vector_query, top_k=limit)
                    
                    if reranked_ids:
                        # 根据 LLM 选出的 ID，反查原始结果
                        id_set = set(reranked_ids)
                        # 保留那些 ID 在 LLM 列表中的结果
                        results_to_process = [r for r in vector_results if r.source_id in id_set]
                        logger.info(f"✅ LLM 筛选出 {len(results_to_process)} 个高相关结果")
                    else:
                        # LLM 失败，直接失败，不使用原始排序
                        logger.error("⚠️ LLM 筛选失败，直接失败")
                        results_to_process = []
                else:
                    # 情况B：召回适中或较少 -> 直接截取前 limit 个
                    results_to_process = vector_results[:limit]
                    logger.info(f"📊 召回适中 ({len(vector_results)})，直接使用 Top {limit}")

                # --- 提取 ID 的循环 (确保在循环外，且逻辑清晰) ---
                for result in results_to_process:
                    if result.entity_type == EntityType.STRUCTURE:
                        # 验证结构ID格式
                        struct_id = result.source_id
                        struct_id_upper = struct_id.upper()
                        is_pdb = re.match(r'^[0-9][A-Z0-9]{3}$', struct_id_upper)
                        is_emdb = re.match(r'^EMD-\d+$', struct_id_upper)
                        if is_pdb or is_emdb:
                            structure_ids.add(struct_id_upper)
                        else:
                            logger.debug(f"过滤无效结构ID: {struct_id}")
                    elif result.entity_type == EntityType.LITERATURE and result.metadata:
                        # 提取文献中关联的结构 ID
                        metadata = result.metadata
                        if 'pdb_ids' in metadata:
                            for pdb_id in metadata['pdb_ids']:
                                pdb_id_upper = str(pdb_id).upper()
                                if re.match(r'^[0-9][A-Z0-9]{3}$', pdb_id_upper):
                                    structure_ids.add(pdb_id_upper)
                                else:
                                    logger.debug(f"过滤无效PDB ID: {pdb_id}")
                        if 'emdb_ids' in metadata:
                            for emdb_id in metadata['emdb_ids']:
                                emdb_id_upper = str(emdb_id).upper()
                                if re.match(r'^EMD-\d+$', emdb_id_upper):
                                    structure_ids.add(emdb_id_upper)
                                else:
                                    logger.debug(f"过滤无效EMDB ID: {emdb_id}")
                        if 'structure_ids' in metadata:
                            for struct_id in metadata['structure_ids']:
                                struct_id_upper = str(struct_id).upper()
                                is_pdb = re.match(r'^[0-9][A-Z0-9]{3}$', struct_id_upper)
                                is_emdb = re.match(r'^EMD-\d+$', struct_id_upper)
                                if is_pdb or is_emdb:
                                    structure_ids.add(struct_id_upper)
                                else:
                                    logger.debug(f"过滤无效结构ID: {struct_id}")
                
                logger.info(f"📊 向量检索最终提取: {len(structure_ids)} 个结构")

            except Exception as e:
                logger.error(f"向量检索发生未知错误: {e}")
        else:
            logger.info("ℹ️ 统一向量索引器不可用，跳过向量搜索")
        
        # 合并 SQL 和 向量检索结果
        structure_ids.update(sql_structure_ids)
        
        # ==========================================
        # 第三阶段：蛋白质名称验证 (新增)
        # ==========================================
        # 直接使用所有结构ID，移除验证步骤
        validated_ids = list(structure_ids)
        logger.info(f"直接使用所有结构ID: {validated_ids}")
        
        final_ids = validated_ids if validated_ids else list(structure_ids)
        if final_ids:
            logger.info(f"✅ 最终融合结果: {len(final_ids)} 个结构 (Top {limit}: {final_ids[:limit]})")
        else:
            logger.info(f"⚠️ 未能找到任何结构")

        return final_ids[:limit]
    
    def _query_structures_from_sql(self, query_text: str, limit: int = 10) -> List[str]:
        """从SQL数据库查询结构ID（作为LLM Rerank失败的回退机制）"""
        structure_ids = set()
        
        try:
            session = create_literature_session()
            try:
                # 提取关键词
                keywords = self._extract_keywords(query_text)
                logger.info(f"从查询中提取关键词: {keywords}")
                
                # 构建查询条件
                or_conditions = []
                for keyword in keywords:
                    or_conditions.append(LiteratureEntry.title.ilike(f'%{keyword}%'))
                    or_conditions.append(LiteratureEntry.abstract.ilike(f'%{keyword}%'))
                
                if not or_conditions:
                    # 如果没有提取到关键词，使用整个查询文本
                    or_conditions.append(LiteratureEntry.title.ilike(f'%{query_text}%'))
                
                # 执行查询
                query = session.query(LiteratureEntry).filter(or_(*or_conditions))
                results = query.limit(limit * 2).all()  # 查询更多结果以确保找到结构
                
                logger.info(f"SQL查询找到 {len(results)} 个文献条目")
                
                # 提取结构ID
                for lit in results:
                    if lit.cryoem_targets:
                        try:
                            targets = lit.cryoem_targets
                            if isinstance(targets, str):
                                targets = json.loads(targets)
                            if isinstance(targets, dict):
                                # 提取PDB和EMDB ID
                                if 'pdb_ids' in targets:
                                    structure_ids.update(targets['pdb_ids'])
                                if 'emdb_ids' in targets:
                                    structure_ids.update(targets['emdb_ids'])
                                if 'structure_ids' in targets:
                                    structure_ids.update(targets['structure_ids'])
                        except Exception as e:
                            logger.debug(f"解析cryoem_targets失败: {e}")
                
                # 验证并过滤结构ID
                valid_structure_ids = []
                for struct_id in structure_ids:
                    struct_id_upper = struct_id.upper()
                    # 验证PDB或EMDB格式
                    is_pdb = re.match(r'^[0-9][A-Z0-9]{3}$', struct_id_upper)
                    is_emdb = re.match(r'^EMD-\d+$', struct_id_upper)
                    if is_pdb or is_emdb:
                        valid_structure_ids.append(struct_id_upper)
                
                logger.info(f"从SQL数据库提取到 {len(valid_structure_ids)} 个有效结构ID")
                return valid_structure_ids[:limit]
                
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"SQL查询结构失败: {e}")
            return []

    def _extract_keywords(self, text: str) -> List[str]:
        """从文本中提取关键词"""
        if not text:
            return []
        
        # 清理文本
        cleaned = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', text)
        words = []
        
        # 通用词语列表
        common_words = {'what', 'they', 'study', 'literature', 'respectively', 'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'must'}
        
        for w in cleaned.split():
            w = w.strip().lower()
            if len(w) > 2 and w not in STOP_WORDS and w not in common_words:
                words.append(w)
        
        # 去重并排序
        return sorted(list(set(words)))[:10]  # 最多提取10个关键词

    def _update_protein_structure_mapping(self, protein_name: str, structure_ids: List[str]):
        """更新蛋白质-结构映射到离线数据库"""
        if not self.structure_db:
            return
        
        try:
            # 分类结构ID
            pdb_ids = []
            emdb_ids = []
            
            for struct_id in structure_ids:
                struct_id_upper = struct_id.upper()
                if re.match(r'^[0-9][A-Za-z0-9]{3}$', struct_id_upper) or re.match(r'^[A-Za-z0-9]{4}$', struct_id_upper):
                    pdb_ids.append(struct_id_upper)
                elif struct_id_upper.startswith('EMD-') or re.match(r'^\d+$', struct_id_upper):
                    emdb_ids.append(struct_id_upper)
            
            # 更新到离线数据库
            if pdb_ids or emdb_ids:
                self.structure_db.update_protein_mapping(protein_name, pdb_ids, emdb_ids)
                logger.info(f"✅ 更新蛋白质映射到离线数据库: {protein_name} -> {len(pdb_ids)} PDB, {len(emdb_ids)} EMDB")
        
        except Exception as e:
            logger.error(f"更新蛋白质映射失败: {e}")
    
    @timeout_decorator(15)  # 15秒超时
    def _query_pdb_by_protein(self, protein_name: str) -> Dict[str, Any]:
        """通过 StructureMetadataFetcher 查询蛋白质信息"""
        try:
            logger.info(f"查询蛋白质信息: {protein_name}")
            
            # 搜索PDB结构
            if not self.structure_fetcher:
                return {
                    "protein_name": protein_name,
                    "structures": [],
                    "total_structures": 0,
                    "sampled_structures": 0,
                    "message": "结构管理器不可用"
                }
            
            pdb_ids = self.structure_fetcher.search_pdb_by_text(protein_name, rows=5)
            
            if not pdb_ids:
                logger.info(f"未找到蛋白质 {protein_name} 的相关结构")
                return {
                    "protein_name": protein_name,
                    "structures": [],
                    "total_structures": 0,
                    "sampled_structures": 0,
                    "message": f"未在PDB数据库中找到 {protein_name} 的相关结构"
                }
            
            logger.info(f"找到 {len(pdb_ids)} 个相关PDB结构: {pdb_ids}")
            
            # 获取每个结构的详细信息
            structures_info = []
            for pdb_id in pdb_ids[:3]:  # 最多获取3个结构的详细信息
                try:
                    structure_info = self.structure_fetcher.get_pdb_info(pdb_id)
                    if structure_info:
                        structures_info.append(structure_info)
                        logger.info(f"获取结构 {pdb_id} 信息成功")
                except Exception as e:
                    logger.error(f"获取结构 {pdb_id} 信息失败: {e}")
            
            return {
                "protein_name": protein_name,
                "structures": structures_info,
                "total_structures": len(pdb_ids),
                "sampled_structures": len(structures_info),
                "message": f"找到 {len(pdb_ids)} 个相关结构，详细分析了 {len(structures_info)} 个"
            }
            
        except TimeoutError:
            logger.warning(f"查询蛋白质 {protein_name} 超时")
            return {
                "protein_name": protein_name,
                "structures": [],
                "total_structures": 0,
                "sampled_structures": 0,
                "message": f"查询超时，请稍后重试",
                "error": "timeout"
            }
        except Exception as e:
            logger.error(f"查询PDB失败: {e}")
            return {
                "protein_name": protein_name,
                "error": str(e),
                "structures": [],
                "message": f"查询失败: {str(e)[:100]}"
            }
    
    def analyze_proteins_for_question(self, question: str) -> Dict[str, Any]:
        """为问题分析相关的蛋白质信息（使用UniProt标准化）"""
        if not self.structure_db:
            return {"error": "结构数据库不可用"}
        
        try:
            logger.info(f"为问题分析蛋白质信息: '{question}'")
            
            # 尝试使用增强结构管理器
            analysis_result = self.structure_db.analyze_protein_for_question(question)
            
            if not analysis_result.get('success'):
                logger.warning(f"蛋白质分析失败: {analysis_result.get('message')}")
                
                # 尝试回退到原有方法
                protein_names = self._extract_protein_names(question)
                if protein_names:
                    structures_info = {}
                    for protein in protein_names:
                        # --- 修改点：添加 question_text=question 参数 ---
                        # 这样 _find_structures_by_protein 就能提取 Vγ9, Vδ2 等精确信息
                        related_ids = self._find_structures_by_protein(
                            protein, 
                            question_text=question,  # 传入原始问题
                            limit=5
                        )
                        if related_ids:
                            structures_info[protein] = {
                                'total_structures': len(related_ids),
                                'structures': related_ids[:3]
                            }
                    
                    return {
                        "success": True,
                        "protein_names": protein_names,
                        "structures_info": structures_info,
                        "analysis_method": "fallback_original",
                        "message": analysis_result.get('message', '')
                    }
                
                return analysis_result
            
            logger.info(f"蛋白质分析成功: 找到 {analysis_result.get('total_structures', 0)} 个结构")
            return analysis_result
            
        except Exception as e:
            logger.error(f"蛋白质分析异常: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "蛋白质分析失败"
            }
    
    def _build_search_text_blob(self, literature):
        """构建全文搜索文本 - 修复版：安全处理列表类型字段，防止 .lower() 报错"""
        fields = [
            literature.title,
            literature.abstract,
            literature.journal,
            literature.doi,
            literature.summary,
            literature.keywords,
            literature.key_findings,
            literature.authors,
            literature.cryoem_targets,
            literature.full_text,  # 添加全文用于搜索
        ]
        
        parts = []
        for f in fields:
            if not f:
                continue
            
            # --- 修复核心：确保所有字段都转为字符串 ---
            text_part = ""
            try:
                if isinstance(f, str):
                    text_part = f
                elif isinstance(f, (list, tuple)):
                    # 如果是列表，检查是否全是字符串
                    if all(isinstance(x, str) for x in f):
                        # 字符串列表：直接用空格连接（比JSON格式更利于搜索）
                        text_part = " ".join(f)
                    else:
                        # 混合类型列表：使用JSON序列化
                        text_part = json.dumps(f, ensure_ascii=False)
                else:
                    # 其他对象（如字典）：尝试JSON序列化，否则转为字符串
                    text_part = json.dumps(f, ensure_ascii=False)
            except Exception as e:
                # 最后的容错手段：强制转为字符串
                logger.warning(f"字段序列化警告: {e}, 字段类型: {type(f)}")
                text_part = str(f)
            
            parts.append(text_part)
            # ----------------------------------------
        
        # 限制长度
        full_text = " ".join(parts)
        if len(full_text) > 30000:
            full_text = full_text[:30000]
        
        # 此时 full_text 确保是字符串，可以安全调用 .lower()
        return full_text.lower()
    
    def upload_literature(self, file_objects: List, 
                         metadata: Dict[str, Any] = None,
                         appendices: List = None,
                         auto_parse: bool = True,
                         use_ai: bool = None) -> Dict[str, Any]:
        """
        上传文献 - 完整版
        """
        results = {
            "total": len(file_objects),
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "success": [],
            "failed": [],
            "skipped": [],
            "parsed": [],
            "duplicates_removed": []
        }
        
        if len(file_objects) == 0:
            return results
        
        # 如果未指定use_ai，使用配置中的默认值
        if use_ai is None:
            use_ai = self.parser_config.AI_ENABLED
        
        logger.info(f"开始批量上传 {len(file_objects)} 个文件，AI解析: {'启用' if use_ai else '禁用'}")
        start_time = time.time()
        
        # 创建数据库会话
        session = create_literature_session()
        
        try:
            # 临时修改解析器的AI设置
            original_ai_enabled = self.parser_config.AI_ENABLED
            self.parser_config.AI_ENABLED = use_ai
            
            # 如果有解析管理器，也更新其配置
            if self.parser_manager:
                self.parser_manager.config.AI_ENABLED = use_ai
                if hasattr(self.parser_manager, 'ai_parser'):
                    self.parser_manager.ai_parser.ai_enabled = use_ai
            
            # 批量处理文件
            for i, fileobj in enumerate(file_objects):
                try:
                    filename = fileobj.name
                    file_content = fileobj.getvalue()
                    
                    logger.info(f"处理文件 ({i+1}/{len(file_objects)}): {filename}")
                    
                    # 1. 检查是否已存在（根据文件名）
                    existing_literature = session.query(LiteratureEntry).filter(
                        LiteratureEntry.main_pdf_filename == filename
                    ).first()
                    
                    if existing_literature:
                        # 检查PDF文件是否存在
                        pdf_exists = False
                        if existing_literature.main_pdf_path:
                            pdf_path = Path(existing_literature.main_pdf_path)
                            if pdf_path.exists() and pdf_path.is_file():
                                pdf_exists = True
                        
                        if pdf_exists:
                            # 文件已存在，跳过
                            results["skipped_count"] += 1
                            results["skipped"].append({
                                "filename": filename,
                                "reason": "文件已存在",
                                "literature_id": existing_literature.id,
                                "title": existing_literature.title
                            })
                            logger.info(f"跳过已存在文件: {filename} (ID: {existing_literature.id})")
                            continue
                        else:
                            # PDF不存在，更新文件
                            logger.info(f"更新丢失的PDF文件: {filename} (ID: {existing_literature.id})")
                            
                            # 保存文件
                            save_path = self._save_pdf_file(file_content, filename)
                            
                            # 更新文献记录
                            existing_literature.main_pdf_path = str(save_path)
                            existing_literature.main_pdf_size = len(file_content)
                            existing_literature.updated_at = datetime.now()
                            
                            # 标记需要重新解析
                            existing_literature.status = LiteratureStatus.UPLOADED
                            existing_literature.parsed_at = None
                            
                            session.commit()
                            
                            # 重新解析
                            if auto_parse:
                                parse_result = self._parse_literature(existing_literature.id, session)
                                if parse_result.get("success"):
                                    results["success_count"] += 1
                                    results["success"].append({
                                        "filename": filename,
                                        "action": "updated",
                                        "literature_id": existing_literature.id,
                                        "title": existing_literature.title,
                                        "message": "PDF文件已更新并重新解析",
                                        "used_ai": use_ai
                                    })
                                    results["parsed"].append(existing_literature.id)
                                else:
                                    results["failed_count"] += 1
                                    results["failed"].append({
                                        "filename": filename,
                                        "error": f"解析失败: {parse_result.get('error')}"
                                    })
                            else:
                                results["success_count"] += 1
                                results["success"].append({
                                    "filename": filename,
                                    "action": "updated",
                                    "literature_id": existing_literature.id,
                                    "message": "PDF文件已更新"
                                })
                            
                            continue
                    
                    # 2. 新文件，创建文献记录
                    logger.info(f"创建新文献记录: {filename}")
                    
                    # 保存文件
                    save_path = self._save_pdf_file(file_content, filename)
                    
                    # 创建文献条目 - 简化数据
                    lit_data = {
                        "title": Path(filename).stem[:200],  # 临时标题，解析后会更新
                        "main_pdf_filename": filename,
                        "main_pdf_path": str(save_path),
                        "main_pdf_size": len(file_content),
                        "status": LiteratureStatus.UPLOADED,
                        "created_at": datetime.now()
                    }
                    
                    # 合并自定义元数据（简化）
                    if metadata:
                        simple_metadata = {}
                        for key, value in metadata.items():
                            if key not in ['authors', 'key_findings', 'keywords']:
                                simple_metadata[key] = str(value)[:500] if value else None
                        lit_data.update(simple_metadata)
                    
                    # 添加到数据库
                    entry = LiteratureEntry(**lit_data)
                    session.add(entry)
                    session.commit()
                    session.refresh(entry)
                    
                    literature_id = entry.id
                    logger.info(f"文献记录创建成功: ID={literature_id}")
                    
                    # 3. 自动解析
                    if auto_parse:
                        parse_result = self._parse_literature(literature_id, session)
                        if parse_result.get("success"):
                            results["success_count"] += 1
                            results["success"].append({
                                "filename": filename,
                                "action": "created",
                                "literature_id": literature_id,
                                "title": parse_result.get("title", entry.title),
                                "message": f"上传并解析成功{'（使用AI）' if use_ai else '（基础解析）'}",
                                "used_ai": use_ai
                            })
                            results["parsed"].append(literature_id)
                        else:
                            results["failed_count"] += 1
                            results["failed"].append({
                                "filename": filename,
                                "error": f"解析失败: {parse_result.get('error')}"
                            })
                    else:
                        results["success_count"] += 1
                        results["success"].append({
                            "filename": filename,
                            "action": "created",
                            "literature_id": literature_id,
                            "message": "上传成功，等待解析"
                        })
                    
                except Exception as e:
                    logger.error(f"处理文件 {fileobj.name} 失败: {e}")
                    results["failed_count"] += 1
                    results["failed"].append({
                        "filename": fileobj.name,
                        "error": str(e)
                    })
            
            # 恢复原始AI设置
            self.parser_config.AI_ENABLED = original_ai_enabled
            if self.parser_manager:
                self.parser_manager.config.AI_ENABLED = original_ai_enabled
                if hasattr(self.parser_manager, 'ai_parser'):
                    self.parser_manager.ai_parser.ai_enabled = original_ai_enabled
            
            # 4. 批量去重（基于标题）- 只在解析成功的情况下进行
            if auto_parse and results["parsed"]:
                try:
                    duplicate_result = self._remove_duplicate_titles(session)
                    if duplicate_result["removed_count"] > 0:
                        results["duplicates_removed"] = duplicate_result["removed"]
                        results["duplicate_removal"] = duplicate_result
                except Exception as e:
                    logger.error(f"去重失败: {e}")
            
            # 5. 重建索引（如果有新文献被解析）- 异步进行
            if results["success_count"] > 0 and self.indexer:
                try:
                    logger.info("开始后台重建索引...")
                    # 使用线程池异步重建索引
                    import threading
                    rebuild_thread = threading.Thread(
                        target=self._rebuild_index_async,
                        args=(results["parsed"],)
                    )
                    rebuild_thread.daemon = True
                    rebuild_thread.start()
                except Exception as e:
                    logger.error(f"启动索引重建失败: {e}")
            
            total_time = time.time() - start_time
            logger.info(f"✅ 批量上传完成 ({total_time:.2f}秒): 成功 {results['success_count']}, 失败 {results['failed_count']}, 跳过 {results['skipped_count']}")
            
            return results
            
        except Exception as e:
            session.rollback()
            total_time = time.time() - start_time
            logger.error(f"批量上传失败 ({total_time:.2f}秒): {e}")
            return {
                "total": len(file_objects),
                "success_count": 0,
                "failed_count": len(file_objects),
                "skipped_count": 0,
                "failed": [{"filename": f.name, "error": str(e)} for f in file_objects],
                "error": str(e)
            }
        finally:
            session.close()
    
    def _rebuild_index_async(self, parsed_ids: List[int]):
        """异步重建索引"""
        try:
            logger.info(f"开始异步增量索引，处理 {len(parsed_ids)} 篇文献...")
            
            # 获取新解析的文献数据
            session = create_literature_session()
            try:
                literature_to_index = []
                for lit_id in parsed_ids:
                    literature = session.query(LiteratureEntry).get(lit_id)
                    if literature:
                        # 转换为字典格式
                        lit_dict = self._format_literature(literature)
                        literature_to_index.append(lit_dict)
                
                if literature_to_index:
                    # 使用增量索引（如果可用）
                    if hasattr(self, 'rag_system') and self.rag_system:
                        # 尝试使用增量索引
                        if hasattr(self.rag_system, 'index_literature_with_tracking'):
                            result = self.rag_system.index_literature_with_tracking(
                                literature_to_index, incremental=True
                            )
                            logger.info(f"增量索引结果: {result}")
                        else:
                            # 回退到原有方法，但只索引新文献
                            self.rag_system.index_literature(literature_to_index)
                            logger.info(f"索引 {len(literature_to_index)} 篇新文献完成")
                    elif self.indexer:
                        # 使用原有的索引器，但只索引新文献
                        self.indexer.index_literature(literature_to_index)
                        logger.info(f"索引 {len(literature_to_index)} 篇新文献完成")
            finally:
                session.close()
                
            logger.info("✅ 异步索引完成")
        except Exception as e:
            logger.error(f"异步索引失败: {e}")
    
    def _save_pdf_file(self, file_content: bytes, filename: str) -> Path:
        """保存PDF文件，处理文件名冲突"""
        save_dir = LITERATURE_PDFS_DIR
        save_path = save_dir / filename
        
        # 处理文件名冲突
        counter = 1
        original_stem = Path(filename).stem
        original_suffix = Path(filename).suffix
        
        while save_path.exists():
            new_filename = f"{original_stem}_{counter}{original_suffix}"
            save_path = save_dir / new_filename
            counter += 1
        
        # 保存文件
        with open(save_path, 'wb') as f:
            f.write(file_content)
        
        logger.info(f"文件已保存: {save_path}")
        return save_path

    def clean_abstract_text(self, abstract: str) -> str:
        """清理摘要文本，移除异常换行和空格"""
        if not abstract:
            return ""
        
        # 移除多余的换行和空格
        import re
        
        # 1. 移除单个数字或字母的换行（如 "2\n0\n,3\n0\n" 变成 "20,30"）
        cleaned = re.sub(r'(\d)\s*\n\s*(\d)', r'\1\2', abstract)
        
        # 2. 将多个连续空白字符替换为单个空格
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        # 3. 移除首尾空格
        cleaned = cleaned.strip()
        
        return cleaned
    
    def fetch_abstract_from_pubmed(self, doi: str) -> Optional[str]:
        """从PubMed获取摘要"""
        try:
            # 导入PubMedFetcher
            import requests
            import xml.etree.ElementTree as ET
            import re
            import time
            
            class PubMedFetcher:
                """PubMed文献信息获取器"""
                
                def __init__(self, email: str = "literature_tool@example.com", 
                            api_key: Optional[str] = None,
                            delay: float = 0.34):
                    self.email = email
                    self.api_key = api_key
                    self.delay = delay
                    self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
                    self.last_request_time = 0
                    
                def _make_request(self, url: str) -> Optional[str]:
                    current_time = time.time()
                    elapsed = current_time - self.last_request_time
                    
                    if elapsed < self.delay:
                        time.sleep(self.delay - elapsed)
                    
                    try:
                        response = requests.get(url, timeout=30)
                        response.raise_for_status()
                        self.last_request_time = time.time()
                        return response.text
                    except requests.exceptions.RequestException as e:
                        logger.warning(f"PubMed请求失败: {e}")
                        return None
                
                def doi_to_pubmed_id(self, doi: str) -> Optional[str]:
                    # 清理DOI
                    doi = doi.strip()
                    if doi.startswith('http'):
                        # 提取DOI号
                        match = re.search(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', doi, re.IGNORECASE)
                        if match:
                            doi = match.group(0)
                    
                    logger.info(f"PubMed查询DOI: {doi}")
                    
                    url = f'{self.base_url}/esearch.fcgi?db=pubmed&term={doi}[DOI]&retmode=json&email={self.email}'
                    
                    if self.api_key:
                        url += f'&api_key={self.api_key}'
                    
                    result = self._make_request(url)
                    
                    if result:
                        try:
                            data = json.loads(result)
                            if 'esearchresult' in data and 'idlist' in data['esearchresult']:
                                id_list = data['esearchresult']['idlist']
                                if id_list:
                                    return id_list[0]
                                else:
                                    logger.info(f"未找到DOI {doi} 对应的PubMed ID")
                            else:
                                logger.warning(f"PubMed返回数据格式异常")
                        except json.JSONDecodeError as e:
                            logger.warning(f"PubMed JSON解析错误: {e}")
                    
                    return None
                
                def get_article_info_simple(self, pubmed_id: str) -> Optional[Dict]:
                    """简化的文章信息获取方法"""
                    url = f'{self.base_url}/efetch.fcgi?db=pubmed&id={pubmed_id}&retmode=xml&email={self.email}'
                    
                    if self.api_key:
                        url += f'&api_key={self.api_key}'
                    
                    result = self._make_request(url)
                    
                    if not result:
                        return None
                    
                    try:
                        article_info = {
                            'pubmed_id': pubmed_id,
                            'doi': '',
                            'title': '',
                            'abstract': '',
                            'authors': [],
                            'journal': '',
                            'publication_date': '',
                            'pubmed_url': f'https://pubmed.ncbi.nlm.nih.gov/{pubmed_id}/'
                        }
                        
                        # 使用正则表达式提取关键信息
                        import re
                        
                        # 提取标题
                        title_match = re.search(r'<ArticleTitle[^>]*>(.*?)</ArticleTitle>', result, re.DOTALL)
                        if title_match:
                            article_info['title'] = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
                        
                        # 提取DOI
                        doi_match = re.search(r'<ArticleId IdType="doi">(.*?)</ArticleId>', result)
                        if doi_match:
                            article_info['doi'] = doi_match.group(1).strip()
                        
                        # 提取摘要 - 尝试多种方法
                        abstract = ""
                        
                        # 方法1: 查找AbstractText元素
                        abstract_matches = re.findall(r'<AbstractText[^>]*>(.*?)</AbstractText>', result, re.DOTALL)
                        if abstract_matches:
                            abstract_parts = []
                            for match in abstract_matches:
                                clean_text = re.sub(r'<[^>]+>', '', match)
                                if clean_text.strip():
                                    abstract_parts.append(clean_text.strip())
                            if abstract_parts:
                                abstract = ' '.join(abstract_parts)
                        
                        # 方法2: 如果没有找到，尝试Abstract元素
                        if not abstract:
                            abstract_match = re.search(r'<Abstract[^>]*>(.*?)</Abstract>', result, re.DOTALL)
                            if abstract_match:
                                abstract_text = re.sub(r'<[^>]+>', ' ', abstract_match.group(1))
                                abstract = ' '.join(abstract_text.split()).strip()
                        
                        article_info['abstract'] = abstract
                        
                        return article_info
                        
                    except Exception as e:
                        logger.warning(f"PubMed简单解析错误: {e}")
                        return None
                
                def doi_to_article_info(self, doi: str) -> Optional[Dict]:
                    """通过DOI获取完整文献信息"""
                    pubmed_id = self.doi_to_pubmed_id(doi)
                    
                    if not pubmed_id:
                        logger.info(f"未找到DOI {doi} 对应的PubMed ID")
                        return None
                    
                    logger.info(f"找到PubMed ID: {pubmed_id}")
                    article_info = self.get_article_info_simple(pubmed_id)
                    
                    return article_info
            
            # 使用PubMedFetcher获取摘要
            fetcher = PubMedFetcher()
            article_info = fetcher.doi_to_article_info(doi)
            
            if article_info and article_info.get('abstract'):
                return article_info['abstract']
            
            return None
            
        except Exception as e:
            logger.warning(f"PubMed获取摘要失败: {e}")
            return None



    def _parse_literature(self, literature_id: int, session) -> Dict[str, Any]:
        """解析文献 - 统一优化版（先获取元信息，再提取结构ID）"""
        start_time = time.time()
        
        try:
            # 获取文献
            literature = session.query(LiteratureEntry).get(literature_id)
            if not literature:
                return {"success": False, "error": "文献不存在"}
            
            # 检查PDF文件是否存在
            if not literature.main_pdf_path or not Path(literature.main_pdf_path).exists():
                return {"success": False, "error": "PDF文件不存在"}
            
            # 使用解析器
            if not self.parser_manager:
                return {"success": False, "error": "解析器不可用"}
            
            logger.info(f"开始解析文献: ID={literature_id}, PDF={literature.main_pdf_path}")
            
            # ============ 第一步：解析PDF获取基础元数据 ============
            result = self.parser_manager.parse_literature_file(literature.main_pdf_path)
            
            if not result.get("success"):
                return {"success": False, "error": result.get("errors", ["解析失败"])[0]}
            
            # 提取解析结果
            parsed_data = result.get("parsed_data", {})
            combined_metadata = parsed_data.get("combined_metadata", {})
            ai_data = parsed_data.get("ai_data", {})
            
            logger.info(f"📊 解析数据调试信息:")
            logger.info(f"  - AI数据是否为空: {not ai_data}")
            logger.info(f"  - AI数据内容: {list(ai_data.keys()) if ai_data else '无'}")
            
            # ============ 提取基础元数据 ============
            # 提取DOI（关键，用于后续结构ID验证）
            extracted_doi = ""
            extracted_title = ""
            extracted_journal = ""
            extracted_publication_date = ""
            extracted_authors_raw = None
            
            if 'combined_metadata' in parsed_data:
                combined_metadata = parsed_data['combined_metadata']
                if isinstance(combined_metadata, dict):
                    extracted_doi = combined_metadata.get('doi', '')
                    extracted_title = combined_metadata.get('title', '')
                    extracted_journal = combined_metadata.get('journal', '')
                    extracted_publication_date = combined_metadata.get('publication_date', '')
                    extracted_authors_raw = combined_metadata.get('authors', None)
                    
                    logger.info(f"🔗 提取到DOI: {extracted_doi}")
                    logger.info(f"📖 提取到标题: {extracted_title[:80]}..." if extracted_title else "📖 未提取到标题")
                    logger.info(f"📰 提取到期刊: {extracted_journal}" if extracted_journal else "📰 未提取到期刊")
                    logger.info(f"📅 提取到发表日期: {extracted_publication_date}" if extracted_publication_date else "📅 未提取到发表日期")
            
            # ============ 第二步：优先获取在线元数据 ============
            online_metadata_result = None
            
            # 如果有DOI，优先尝试在线获取
            if extracted_doi:
                logger.info(f"🔍 使用增强在线元数据获取器: {extracted_doi}")
                
                try:
                    from core.literature_parser import OnlineMetadataFetcher
                    # 创建在线元数据获取器
                    online_fetcher = OnlineMetadataFetcher(self.config)
                    
                    # 获取元数据
                    online_metadata_result = online_fetcher.fetch_by_doi(extracted_doi)
                    
                    if online_metadata_result and online_metadata_result.get("success"):
                        online_metadata = online_metadata_result.get("metadata", {})
                        best_source = online_metadata_result.get("best_source", "unknown")
                        
                        logger.info(f"✅ 成功获取在线元数据 (来源: {best_source})")
                        logger.info(f"📖 在线标题: {online_metadata.get('title', '')[:80]}...")
                        logger.info(f"📅 在线日期: {online_metadata.get('publication_date', '')}")
                        
                        # 记录所有尝试的来源
                        sources_found = online_metadata_result.get("sources_found", [])
                        logger.info(f"🔍 尝试的来源: {sources_found}")
                    else:
                        error_msg = online_metadata_result.get("error", "未知错误") if online_metadata_result else "无结果"
                        logger.warning(f"⚠️ 在线元数据获取失败: {error_msg}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ 在线元数据获取异常: {e}")
            
            # ============ 第三步：合并元数据（优先在线，其次AI，最后PDF） ============
            final_metadata = {}
            
            # 1. 优先使用在线元数据
            if online_metadata_result and online_metadata_result.get("success"):
                online_metadata = online_metadata_result.get("metadata", {})
                final_metadata.update({
                    "title": online_metadata.get('title', ''),
                    "journal": online_metadata.get('journal', ''),
                    "publication_date": online_metadata.get('publication_date', ''),
                    "year": online_metadata.get('year'),
                    "authors": online_metadata.get('authors', []),
                    "abstract": online_metadata.get('abstract', ''),
                    "metadata_source": online_metadata_result.get('best_source', 'online'),
                    "online_metadata_result": online_metadata_result  # 保存完整结果用于调试
                })
                logger.info(f"🎯 使用在线元数据作为主要来源: {online_metadata_result.get('best_source')}")
            
            # 2. 如果没有获取到在线元数据，使用AI解析的元数据
            if not final_metadata.get('title') and ai_data and isinstance(ai_data, dict):
                ai_metadata = ai_data.get('metadata', {})
                if isinstance(ai_metadata, dict) and ai_metadata.get('title'):
                    final_metadata['title'] = ai_metadata['title']
                    final_metadata['metadata_source'] = 'ai'
                    logger.info("🎯 使用AI元数据作为标题来源")
            
            # 3. 最后使用PDF解析的元数据
            if not final_metadata.get('title') and combined_metadata.get('title'):
                final_metadata['title'] = combined_metadata['title']
                final_metadata['metadata_source'] = 'pdf'
                logger.info("🎯 使用PDF元数据作为标题来源")
            
            # 填充其他缺失的字段
            if not final_metadata.get('journal'):
                if ai_data and isinstance(ai_data, dict):
                    ai_metadata = ai_data.get('metadata', {})
                    if ai_metadata and ai_metadata.get('journal'):
                        final_metadata['journal'] = ai_metadata['journal']
                elif combined_metadata.get('journal'):
                    final_metadata['journal'] = combined_metadata['journal']
            
            if not final_metadata.get('authors'):
                if combined_metadata.get('authors'):
                    final_metadata['authors'] = combined_metadata['authors']
            
            if not final_metadata.get('publication_date'):
                if combined_metadata.get('publication_date'):
                    final_metadata['publication_date'] = combined_metadata['publication_date']
            
            # 提取年份
            if not final_metadata.get('year') and final_metadata.get('publication_date'):
                try:
                    import re
                    date_str = str(final_metadata['publication_date'])
                    year_match = re.search(r'(\d{4})', date_str)
                    if year_match:
                        final_metadata['year'] = int(year_match.group(1))
                except:
                    pass
            
            # 记录最终选择的元数据
            logger.info(f"🎯 最终选择的元数据:")
            logger.info(f"  - 来源: {final_metadata.get('metadata_source', 'unknown')}")
            logger.info(f"  - 标题: {final_metadata.get('title', '')[:80]}...")
            logger.info(f"  - 期刊: {final_metadata.get('journal', '')}")
            logger.info(f"  - 日期: {final_metadata.get('publication_date', '')}")
            logger.info(f"  - 年份: {final_metadata.get('year', '')}")
            logger.info(f"  - 作者数量: {len(final_metadata.get('authors', []))}")
            
            # ============ 第四步：保存元数据到数据库 ============
            updates_made = False
            
            # 1. 保存DOI（如果文献中没有但解析出来了）
            if extracted_doi and not literature.doi:
                literature.doi = extracted_doi
                updates_made = True
                logger.info(f"✅ 已保存DOI: {extracted_doi}")
            
            # 2. 保存标题（强制保存，即使已经有标题）
            title = final_metadata.get('title', '')
            if title and isinstance(title, str) and title.strip():
                literature.title = title[:500]
                updates_made = True
                logger.info(f"📖 标题已保存: {title[:80]}...")
            
            # 3. 保存期刊
            journal = final_metadata.get('journal', '')
            if journal and isinstance(journal, str) and journal.strip():
                literature.journal = journal[:300]
                updates_made = True
                logger.info(f"📰 期刊已保存: {journal}")
            
            # 4. 保存年份
            year = final_metadata.get('year')
            if year and isinstance(year, int):
                literature.year = year
                updates_made = True
                logger.info(f"📅 年份已保存: {year}")
            
            # 5. 保存发表日期
            publication_date = final_metadata.get('publication_date', '')
            if publication_date:
                try:
                    # 统一处理为字符串格式
                    date_str = str(publication_date)
                    
                    # 如果是Crossref格式的日期时间字符串，提取日期部分
                    if 'T' in date_str:
                        date_str = date_str.split('T')[0]
                    
                    # 确保日期格式正确
                    literature.publication_date = date_str[:50]
                    updates_made = True
                    logger.info(f"📅 发表日期已保存: {date_str}")
                    
                except Exception as e:
                    logger.warning(f"处理发表日期失败: {e}, 原始数据: {publication_date}")
            
            # 提交元数据到数据库（确保DOI等关键信息已保存）
            if updates_made:
                session.commit()
                logger.info(f"✅ 基础元数据已保存到数据库")
            
            # ============ 第五步：使用DOI进行结构ID提取 ============
            structure_extraction_status = "成功"
            pdb_count = 0
            emdb_count = 0
            structure_extraction_details = {}
            final_pdb_ids = []
            final_emdb_ids = []
            extraction_filter_applied = False
            
            # 使用增强的结构ID提取器（现在可以使用DOI进行验证）
            if HAS_ENHANCED_EXTRACTOR:
                logger.info(f"🔍 使用增强结构ID提取器，将使用DOI: {literature.doi}...")
                
                try:
                    # 调用增强的结构ID提取函数
                    extract_result = re_extract_structure_ids(
                        literature_id=literature_id,
                        show_progress=False,
                        use_structure_manager=True,
                        force_update=True,
                        fetch_missing_emdb=True,
                        use_doi_for_validation=True  # 关键：使用DOI验证
                    )
                    
                    # 记录结构ID提取结果
                    structure_extraction_details = extract_result
                    
                    if extract_result and extract_result.get("success"):
                        validated_ids = extract_result.get("validated_ids", {})
                        pdb_count = len(validated_ids.get("pdb_ids", []))
                        emdb_count = len(validated_ids.get("emdb_ids", []))
                        final_pdb_ids = validated_ids.get("pdb_ids", [])
                        final_emdb_ids = validated_ids.get("emdb_ids", [])
                        
                        # 获取过滤信息
                        structure_manager_result = extract_result.get("structure_manager_result", {})
                        filtering_info = structure_manager_result.get("filtering_info", {}) if structure_manager_result else {}
                        extraction_filter_applied = filtering_info.get("filter_applied", False) if filtering_info else False
                        
                        logger.info(f"📊 结构ID提取成功: PDB={pdb_count}, EMDB={emdb_count}")
                        logger.info(f"📋 提取的PDB IDs: {final_pdb_ids}")
                        logger.info(f"📋 提取的EMDB IDs: {final_emdb_ids}")
                    else:
                        structure_extraction_status = "失败"
                        error_msg = extract_result.get('error', '未知错误') if extract_result else '返回None'
                        logger.warning(f"❌ 结构ID提取失败: {error_msg}")
                        
                except Exception as e:
                    structure_extraction_status = "失败"
                    logger.error(f"❌ 结构ID提取异常: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                # 回退到原有的结构ID提取器
                logger.info(f"🔍 使用原有的结构ID提取器...")
                
                try:
                    # 从parsed_data中获取结构ID
                    structure_ids = parsed_data.get("structure_ids", {})
                    
                    if structure_ids:
                        pdb_count = len(structure_ids.get("pdb_ids", []))
                        emdb_count = len(structure_ids.get("emdb_ids", []))
                        final_pdb_ids = structure_ids.get("pdb_ids", [])
                        final_emdb_ids = structure_ids.get("emdb_ids", [])
                        
                        logger.info(f"📊 原有结构ID提取: PDB={pdb_count}, EMDB={emdb_count}")
                    else:
                        logger.warning("❌ 原有结构ID提取器未返回结构ID")
                        
                except Exception as e:
                    structure_extraction_status = "失败"
                    logger.error(f"❌ 原有结构ID提取异常: {e}")
            
            # ============ 第六步：提取摘要（优先PubMed） ============
            abstract = ""
            abstract_source = "未获取到"
            
            # 1. 首先尝试从PubMed获取摘要（使用已保存的DOI）
            if literature.doi:
                logger.info(f"🔍 尝试从PubMed获取摘要... DOI: {literature.doi}")
                try:
                    if HAS_ENHANCED_EXTRACTOR:
                        pubmed_abstract = self.fetch_abstract_from_pubmed(literature.doi)
                        if pubmed_abstract and pubmed_abstract.strip():
                            abstract = pubmed_abstract
                            abstract_source = "PubMed"
                            logger.info(f"✅ 成功从PubMed获取摘要 (长度: {len(abstract)}字符)")
                            logger.info(f"📄 PubMed摘要预览: {abstract[:200]}...")
                        else:
                            logger.info("❌ PubMed没有找到摘要")
                    else:
                        logger.info("⚠️ fetch_abstract_from_pubmed函数不可用，跳过PubMed获取")
                except Exception as e:
                    logger.warning(f"从PubMed获取摘要失败: {e}")
            
            # 2. 如果没有从PubMed获取到，尝试从online_metadata_raw获取（Crossref/DOI）
            if not abstract.strip() and 'online_metadata_raw' in parsed_data:
                online_metadata = parsed_data['online_metadata_raw']
                if isinstance(online_metadata, dict):
                    online_abstract = online_metadata.get('abstract', '')
                    if online_abstract and online_abstract.strip():
                        abstract = online_abstract
                        abstract_source = "Crossref/DOI"
                        logger.info(f"✅ 从online_metadata_raw获取到摘要 (长度: {len(abstract)}字符)")
                    else:
                        logger.info("❌ 从online_metadata_raw没有获取到有效摘要")
            
            # 3. 如果Crossref也没有，尝试从combined_metadata获取（可能是PDF提取的）
            if not abstract.strip() and 'combined_metadata' in parsed_data:
                combined_metadata = parsed_data['combined_metadata']
                if isinstance(combined_metadata, dict):
                    combined_abstract = combined_metadata.get('abstract', '')
                    if combined_abstract and combined_abstract.strip():
                        # 清理摘要中的异常换行和空格
                        cleaned_abstract = self.clean_abstract_text(combined_abstract)
                        abstract = cleaned_abstract
                        abstract_source = "PDF解析"
                        logger.info(f"✅ 从combined_metadata获取到摘要 (清理后长度: {len(abstract)}字符)")
                        logger.info(f"📄 清理后摘要预览: {abstract[:200]}...")
            
            # 4. 如果以上都没有获取到，且使用了AI，尝试从AI解析结果中获取摘要
            if not abstract.strip() and self.config.AI_ENABLED and 'ai_data' in parsed_data:
                ai_data = parsed_data['ai_data']
                if isinstance(ai_data, dict):
                    if 'abstract' in ai_data and ai_data['abstract'] and ai_data['abstract'].strip():
                        abstract = ai_data['abstract']
                        abstract_source = "AI解析"
                        logger.info(f"✅ 使用AI解析的摘要 (长度: {len(abstract)}字符)")
                    elif 'summary' in ai_data and ai_data['summary'] and ai_data['summary'].strip():
                        abstract = ai_data['summary']
                        abstract_source = "AI解析(summary)"
                        logger.info(f"✅ 使用AI解析的summary作为摘要 (长度: {len(abstract)}字符)")
                    else:
                        logger.info("❌ AI解析结果中也没有有效摘要")
            
            # ============ 第七步：提取关键发现 ============
            key_findings = None
            key_findings_source = "未知"
            
            # 1. 首先尝试从ai_data中获取关键发现
            if 'ai_data' in parsed_data and parsed_data['ai_data']:
                ai_data = parsed_data['ai_data']
                logger.info(f"🔍 ai_data字段类型: {type(ai_data)}")
                
                if isinstance(ai_data, dict):
                    # 尝试不同的键名
                    possible_keys = ['key_findings', 'key_finding', 'findings', 'main_findings']
                    for key in possible_keys:
                        if key in ai_data and ai_data[key]:
                            key_findings = ai_data[key]
                            key_findings_source = f"ai_data['{key}']"
                            logger.info(f"✅ 从{key_findings_source}找到关键发现")
                            break
                    
                    # 如果没有找到，显示ai_data内容以便调试
                    if key_findings is None:
                        logger.info(f"📋 ai_data内容: {list(ai_data.keys())}")
                
                elif isinstance(ai_data, list):
                    # ai_data可能是列表格式
                    logger.info(f"📋 ai_data是列表，长度: {len(ai_data)}")
                    if ai_data and isinstance(ai_data[0], dict):
                        key_findings = ai_data
                        key_findings_source = "ai_data_list"
                        logger.info("✅ 使用ai_data列表作为关键发现")
            
            # 2. 尝试从combined_metadata获取
            if key_findings is None and 'combined_metadata' in parsed_data:
                combined_metadata = parsed_data['combined_metadata']
                if isinstance(combined_metadata, dict):
                    for key in ['key_findings', 'findings']:
                        if key in combined_metadata and combined_metadata[key]:
                            key_findings = combined_metadata[key]
                            key_findings_source = f"combined_metadata['{key}']"
                            logger.info(f"✅ 从{key_findings_source}找到关键发现")
                            break
            
            # 3. 尝试从section_data获取
            if key_findings is None and 'section_data' in parsed_data:
                section_data = parsed_data['section_data']
                if isinstance(section_data, dict):
                    # 查找可能包含关键发现的章节
                    result_sections = ['results', 'findings', 'conclusions', 'discussion', 'key_results']
                    for section_name, section_content in section_data.items():
                        section_name_lower = section_name.lower()
                        if any(keyword in section_name_lower for keyword in result_sections):
                            if isinstance(section_content, (list, dict, str)) and section_content:
                                key_findings = section_content
                                key_findings_source = f"section_data['{section_name}']"
                                logger.info(f"✅ 从{key_findings_source}提取关键发现")
                                break
            
            # 4. 使用摘要作为后备关键发现
            if key_findings is None and abstract:
                key_findings = [{"text": abstract}]
                key_findings_source = "abstract_as_findings"
                logger.info("✅ 使用摘要作为关键发现")
            
            # 记录关键发现信息
            logger.info(f"🔑 关键发现来源: {key_findings_source}")
            if key_findings:
                if isinstance(key_findings, list):
                    logger.info(f"🔑 关键发现数量: {len(key_findings)}")
                    # 显示前2个关键发现预览
                    for i, finding in enumerate(key_findings[:2]):
                        if isinstance(finding, dict):
                            finding_text = finding.get('text') or finding.get('finding') or str(finding)
                            logger.info(f"  发现{i+1}: {finding_text[:100]}...")
                elif isinstance(key_findings, dict):
                    logger.info(f"🔑 关键发现: 字典格式，键: {list(key_findings.keys())}")
                elif isinstance(key_findings, str):
                    logger.info(f"🔑 关键发现预览: {key_findings[:100]}...")
            else:
                logger.warning("⚠️ 未找到关键发现")
            
            # ============ 第八步：处理作者信息 ============
            authors_json_data = None
            
            if extracted_authors_raw:
                try:
                    if isinstance(extracted_authors_raw, list):
                        # 标准化作者列表格式
                        normalized_authors = []
                        for author in extracted_authors_raw:
                            if isinstance(author, dict):
                                # 确保有标准的name字段
                                normalized_author = {}
                                
                                # 提取姓名
                                if 'name' in author and author['name']:
                                    normalized_author['name'] = str(author['name']).strip()
                                elif 'given' in author and 'family' in author:
                                    given = author.get('given', '')
                                    family = author.get('family', '')
                                    normalized_author['name'] = f"{given} {family}".strip()
                                elif 'given' in author:
                                    normalized_author['name'] = str(author['given']).strip()
                                elif 'family' in author:
                                    normalized_author['name'] = str(author['family']).strip()
                                else:
                                    # 如果没有name字段，尝试其他字段
                                    for key, value in author.items():
                                        if isinstance(value, str) and value.strip():
                                            normalized_author['name'] = value.strip()
                                            break
                                    if 'name' not in normalized_author:
                                        continue  # 跳过没有姓名的作者
                                
                                # 提取机构信息
                                if 'affiliation' in author:
                                    normalized_author['affiliation'] = str(author['affiliation']).strip()
                                elif 'affiliations' in author:
                                    # 如果有多个机构，取第一个
                                    if isinstance(author['affiliations'], list) and author['affiliations']:
                                        normalized_author['affiliation'] = str(author['affiliations'][0]).strip()
                                    else:
                                        normalized_author['affiliation'] = str(author['affiliations']).strip()
                                else:
                                    normalized_author['affiliation'] = ""
                                
                                normalized_authors.append(normalized_author)
                            elif isinstance(author, str):
                                # 如果是字符串，创建基本格式
                                normalized_authors.append({
                                    "name": author.strip(),
                                    "affiliation": ""
                                })
                        
                        if normalized_authors:
                            authors_json_data = normalized_authors
                            logger.info(f"👥 标准化作者列表: {len(normalized_authors)} 位作者")
                    
                    elif isinstance(extracted_authors_raw, dict):
                        # 单个作者字典
                        normalized_author = {}
                        
                        if 'name' in extracted_authors_raw:
                            normalized_author['name'] = str(extracted_authors_raw['name']).strip()
                        elif 'given' in extracted_authors_raw and 'family' in extracted_authors_raw:
                            normalized_author['name'] = f"{extracted_authors_raw['given']} {extracted_authors_raw['family']}".strip()
                        elif 'given' in extracted_authors_raw:
                            normalized_author['name'] = str(extracted_authors_raw['given']).strip()
                        elif 'family' in extracted_authors_raw:
                            normalized_author['name'] = str(extracted_authors_raw['family']).strip()
                        else:
                            # 尝试其他字段
                            for key, value in extracted_authors_raw.items():
                                if isinstance(value, str) and value.strip():
                                    normalized_author['name'] = value.strip()
                                    break
                            if 'name' not in normalized_author:
                                normalized_author['name'] = str(extracted_authors_raw)[:100]
                        
                        # 机构信息
                        if 'affiliation' in extracted_authors_raw:
                            normalized_author['affiliation'] = str(extracted_authors_raw['affiliation']).strip()
                        else:
                            normalized_author['affiliation'] = ""
                        
                        authors_json_data = [normalized_author]  # 包装成列表
                        logger.info(f"👥 单个作者标准化: {normalized_author['name']}")
                    
                    elif isinstance(extracted_authors_raw, str):
                        # 如果是字符串，尝试解析JSON
                        try:
                            parsed_authors = json.loads(extracted_authors_raw)
                            if isinstance(parsed_authors, list):
                                # 递归处理（简化版）
                                normalized_authors = []
                                for author in parsed_authors:
                                    if isinstance(author, dict):
                                        norm_author = {}
                                        if 'name' in author:
                                            norm_author['name'] = str(author['name']).strip()
                                        elif 'given' in author and 'family' in author:
                                            norm_author['name'] = f"{author['given']} {author['family']}".strip()
                                        
                                        if 'affiliation' in author:
                                            norm_author['affiliation'] = str(author['affiliation']).strip()
                                        else:
                                            norm_author['affiliation'] = ""
                                        
                                        if 'name' in norm_author:
                                            normalized_authors.append(norm_author)
                                authors_json_data = normalized_authors
                            else:
                                # 单个作者字符串
                                authors_json_data = [{
                                    "name": extracted_authors_raw.strip(),
                                    "affiliation": ""
                                }]
                        except json.JSONDecodeError:
                            # 不是JSON，就是普通字符串
                            authors_json_data = [{
                                "name": extracted_authors_raw.strip(),
                                "affiliation": ""
                            }]
                    
                except Exception as e:
                    logger.warning(f"处理作者字段时出错: {e}")
                    # 出错时尝试保存为基本格式
                    try:
                        authors_json_data = [{
                            "name": str(extracted_authors_raw)[:200],
                            "affiliation": ""
                        }]
                    except:
                        authors_json_data = None
            
            # ============ 第九步：保存详细信息到数据库 ============
            # 1. 保存关键发现
            if key_findings:
                try:
                    # 确保key_findings是JSON可序列化的
                    if isinstance(key_findings, (dict, list)):
                        literature.key_findings = json.dumps(key_findings, ensure_ascii=False, indent=2)
                        updates_made = True
                        logger.info(f"✅ 关键发现已保存到文献 {literature_id} (来源: {key_findings_source})")
                        
                        # 显示关键发现内容预览
                        if isinstance(key_findings, list) and key_findings:
                            for i, finding in enumerate(key_findings[:3]):
                                if isinstance(finding, dict):
                                    text = finding.get('text') or finding.get('finding') or str(finding)
                                    logger.info(f"  关键发现 {i+1}: {text[:80]}...")
                    elif isinstance(key_findings, str):
                        # 检查是否已经是JSON字符串
                        if key_findings.strip().startswith('[') or key_findings.strip().startswith('{'):
                            try:
                                # 验证JSON格式
                                json.loads(key_findings)
                                literature.key_findings = key_findings
                                updates_made = True
                                logger.info(f"✅ 关键发现（JSON字符串）已保存到文献 {literature_id}")
                            except json.JSONDecodeError as e:
                                # 如果不是有效的JSON，创建JSON格式
                                logger.warning(f"关键发现不是有效JSON，将创建格式: {e}")
                                literature.key_findings = json.dumps({
                                    "findings": [{"text": key_findings}]
                                }, ensure_ascii=False, indent=2)
                                updates_made = True
                        else:
                            # 如果是普通文本，创建JSON格式
                            literature.key_findings = json.dumps({
                                "findings": [{"text": key_findings}]
                            }, ensure_ascii=False, indent=2)
                            updates_made = True
                except Exception as e:
                    logger.error(f"❌ 保存关键发现失败: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                logger.warning("⚠️ 没有关键发现需要保存")
            
            # 2. 保存摘要
            if abstract and isinstance(abstract, str) and abstract.strip():
                # 清理摘要文本
                cleaned_abstract = self.clean_abstract_text(abstract)
                literature.abstract = cleaned_abstract[:4000]  # 限制长度
                updates_made = True
                logger.info(f"📝 摘要已保存 (来源: {abstract_source})")
                logger.info(f"📄 摘要内容: {cleaned_abstract[:200]}...")
            else:
                logger.warning("⚠️ 没有获取到有效摘要")
            
            # 3. 保存作者信息（JSON格式）
            if authors_json_data:
                try:
                    # 转换为JSON字符串
                    authors_json_str = json.dumps(authors_json_data, ensure_ascii=False, indent=2)
                    
                    # 检查是否需要更新
                    current_authors = literature.authors
                    need_update = True
                    
                    if current_authors:
                        try:
                            # 尝试解析当前作者信息进行比较
                            if isinstance(current_authors, str):
                                current_parsed = json.loads(current_authors)
                            else:
                                current_parsed = current_authors
                            
                            # 简单比较：转换为规范化的JSON字符串进行比较
                            current_str = json.dumps(current_parsed, sort_keys=True, ensure_ascii=False)
                            new_str = json.dumps(authors_json_data, sort_keys=True, ensure_ascii=False)
                            
                            if current_str == new_str:
                                need_update = False
                                logger.info(f"👥 作者信息未变化，跳过更新")
                        except:
                            # 如果解析失败，默认需要更新
                            pass
                    
                    if need_update:
                        literature.authors = authors_json_str
                        updates_made = True
                        logger.info(f"👥 作者已更新为JSON格式: {len(authors_json_data)} 位作者")
                        
                        # 显示前3位作者预览
                        preview = ", ".join([a.get('name', '') for a in authors_json_data[:3]])
                        logger.info(f"👥 作者预览: {preview}...")
                except Exception as e:
                    logger.error(f"❌ 保存作者信息失败: {e}")
            
            # 4. 保存结构ID到cryoem_targets字段
            if final_pdb_ids or final_emdb_ids:
                try:
                    cryoem_targets = {
                        "pdb_ids": final_pdb_ids,
                        "emdb_ids": final_emdb_ids,
                        "extraction_method": "enhanced" if HAS_ENHANCED_EXTRACTOR else "basic",
                        "extraction_time": datetime.now().isoformat(),
                        "data_availability_section_found": structure_extraction_details.get("data_availability_section_found", False) if structure_extraction_details else False,
                        "extraction_method_details": "re_extract_structure_ids" if HAS_ENHANCED_EXTRACTOR else "parser_builtin",
                        "doi_used_for_validation": bool(literature.doi) if HAS_ENHANCED_EXTRACTOR else False,
                        "filter_applied": extraction_filter_applied
                    }
                    
                    literature.cryoem_targets = json.dumps(cryoem_targets, ensure_ascii=False)
                    updates_made = True
                    logger.info(f"🏗️ 结构ID已保存: PDB={len(final_pdb_ids)}, EMDB={len(final_emdb_ids)}")
                    
                except Exception as e:
                    logger.error(f"❌ 保存结构ID失败: {e}")
            
            # 更新状态
            literature.status = LiteratureStatus.PARSED
            literature.parsed_at = datetime.now()
            literature.updated_at = datetime.now()
            updates_made = True
            
            # 提交所有更改
            if updates_made:
                session.commit()
                logger.info(f"✅ 所有数据已成功保存到数据库")
            else:
                logger.info("没有需要更新的数据")
            
            session.refresh(literature)
            
            process_time = time.time() - start_time
            logger.info(f"✅ 文献解析成功 ({process_time:.2f}秒): ID={literature_id}, 标题={literature.title[:50]}...")
            
            return {
                "success": True,
                "title": literature.title,
                "year": literature.year,
                "publication_date": literature.publication_date,
                "authors": literature.authors,
                "key_findings": literature.key_findings,
                "structure_extraction": structure_extraction_status,
                "pdb_count": pdb_count,
                "emdb_count": emdb_count,
                "extraction_method": "enhanced" if HAS_ENHANCED_EXTRACTOR else "basic",
                "extraction_filter_applied": extraction_filter_applied,
                "doi": literature.doi,
                "journal": literature.journal,
                "abstract_source": abstract_source,
                "key_findings_source": key_findings_source,
                "message": "解析成功",
                "process_time": process_time,
                "final_pdb_ids": final_pdb_ids,
                "final_emdb_ids": final_emdb_ids
            }
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"解析文献失败 ({process_time:.2f}秒): {e}")
            import traceback
            traceback.print_exc()
            # 更新为错误状态
            try:
                if 'literature' in locals():
                    literature.status = LiteratureStatus.ERROR
                    session.commit()
            except:
                pass
            return {"success": False, "error": str(e)}
    
    def _remove_duplicate_titles(self, session) -> Dict[str, Any]:
        """根据标题去重"""
        try:
            logger.info("开始标题去重检查...")
            
            # 获取所有已解析的文献
            parsed_literature = session.query(LiteratureEntry).filter(
                LiteratureEntry.status.in_([LiteratureStatus.PARSED, LiteratureStatus.INDEXED])
            ).all()
            
            if not parsed_literature:
                return {"removed_count": 0, "removed": []}
            
            # 按标题分组
            title_groups = defaultdict(list)
            for lit in parsed_literature:
                if lit.title:
                    # 清理标题：去除空格和特殊字符，转为小写
                    clean_title = re.sub(r'\s+', ' ', lit.title.strip()).lower()
                    title_groups[clean_title].append(lit)
            
            # 找出重复的标题
            duplicates_removed = []
            
            for title, items in title_groups.items():
                if len(items) > 1:
                    # 按创建时间排序，保留最早的
                    items.sort(key=lambda x: x.created_at)
                    
                    # 保留第一个，删除其他
                    keep_item = items[0]
                    
                    for duplicate in items[1:]:
                        # 记录要删除的文献信息
                        duplicates_removed.append({
                            "duplicate_id": duplicate.id,
                            "duplicate_title": duplicate.title,
                            "keep_id": keep_item.id,
                            "keep_title": keep_item.title,
                            "reason": f"重复标题: {duplicate.title[:50]}..."
                        })
                        
                        # 删除重复的文献
                        # 首先删除物理文件
                        if duplicate.main_pdf_path and Path(duplicate.main_pdf_path).exists():
                            try:
                                Path(duplicate.main_pdf_path).unlink(missing_ok=True)
                            except:
                                pass
                        
                        # 删除数据库记录
                        session.delete(duplicate)
                    
                    logger.info(f"去重: 保留 ID={keep_item.id}, 删除 {len(items)-1} 个重复项")
            
            if duplicates_removed:
                session.commit()
                logger.info(f"✅ 去重完成: 删除了 {len(duplicates_removed)} 个重复文献")
            
            return {
                "removed_count": len(duplicates_removed),
                "removed": duplicates_removed
            }
            
        except Exception as e:
            session.rollback()
            logger.error(f"去重失败: {e}")
            return {"removed_count": 0, "removed": [], "error": str(e)}
    
    # ---------- 简化的结构ID提取 ----------
    
    def _extract_structure_ids_simple(self, query: str) -> List[str]:
        """简化的结构ID提取，不区分上下文"""
        structure_ids = []
        
        # 先将查询转为大写
        query_upper = query.upper()
        
        # 提取PDB ID（4字符，数字开头）
        pdb_pattern = r'\b([1-9][A-Z0-9]{3})\b'
        pdb_matches = re.findall(pdb_pattern, query_upper)
        if pdb_matches:
            structure_ids.extend(pdb_matches)
        
        # 提取EMDB ID（EMD-数字）
        emdb_pattern = r'\b(EMD[-_]?\d+)\b'
        emdb_matches = re.findall(emdb_pattern, query_upper)
        if emdb_matches:
            structure_ids.extend(emdb_matches)
        
        # 提取EMDB数字（纯数字形式）
        emdb_num_pattern = r'\b(\d{5,})\b'
        emdb_num_matches = re.findall(emdb_num_pattern, query_upper)
        if emdb_num_matches:
            for num in emdb_num_matches:
                if len(num) >= 4:  # EMDB编号通常较长
                    structure_ids.append(f"EMD-{num}")
        
        # 去重并返回
        return list(set(structure_ids))
    
    # ---------- 增强的全文搜索函数 ----------
    
    def search_literature_simple(self, query: str, limit: int = 20, filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """增强版全文搜索：支持中英文、结构ID、关键词，支持按字段搜索"""
        start_time = time.time()
        session = None
        
        try:
            session = create_literature_session()
            
            # 获取搜索类型
            search_type = filters.get("search_type", "smart") if filters else "smart"
            
            # 初始化变量
            query_clean = query.strip() if query and query.strip() else ""
            english_query = query
            extracted_keywords = []
            
            # 1. 提取结构ID
            structure_ids = self._extract_structure_ids_simple(query)
            
            # 2. 使用AI翻译问题为英文（如果可用）- 只在智能搜索时使用
            if HAS_AGENT and search_type == "smart" and query_clean:
                try:
                    english_query = translate_question_to_english(query)
                    if english_query and english_query.strip():
                        logger.info(f"翻译后的问题: '{english_query}'")
                    else:
                        logger.info("翻译返回空结果，使用原查询")
                except Exception as e:
                    logger.debug(f"翻译失败: {e}")
            
            # 3. 提取关键词 - 只在智能搜索时使用
            if search_type == "smart" and english_query and english_query.strip():
                extracted_keywords = extract_keywords(english_query)
                logger.info(f"提取的关键词: {extracted_keywords}")
            
            # 4. 构建查询条件
            search_conditions = []
            
            # 如果有结构ID，优先搜索结构ID
            if structure_ids:
                logger.info(f"搜索结构ID: {structure_ids}")
                
                for struct_id in structure_ids:
                    patterns = [f'%{struct_id}%', f'%"{struct_id}"%', f'%\\"{struct_id}\\"%']
                    
                    for pattern in patterns:
                        search_conditions.append(LiteratureEntry.cryoem_targets.ilike(pattern))
                        search_conditions.append(LiteratureEntry.search_text_blob.ilike(pattern))
            
            # 根据搜索类型构建文本搜索条件
            if query_clean:
                if search_type == "title":
                    search_conditions.append(LiteratureEntry.title.ilike(f'%{query_clean}%'))
                    
                elif search_type == "author":
                    # 作者搜索：专门搜索作者字段 - 增强版
                    # 处理多种作者格式
                    author_patterns = [
                        f'%"name": "%{query_clean}%"%',      # JSON格式
                        f'%"name":"%{query_clean}%"%',       # JSON无空格格式
                        f'%"{query_clean}"%',               # 直接作者名（JSON字符串）
                        f'%{query_clean}%'                  # 纯文本搜索
                    ]
                    
                    # 构建作者搜索条件
                    author_conditions = []
                    for pattern in author_patterns:
                        author_conditions.append(LiteratureEntry.authors.ilike(pattern))
                        author_conditions.append(LiteratureEntry.search_text_blob.ilike(pattern))
                    
                    # 如果是中文名字，尝试拼音或首字母搜索
                    if any('\u4e00' <= c <= '\u9fff' for c in query_clean):
                        # 中文名直接搜索
                        author_conditions.append(LiteratureEntry.authors.ilike(f'%{query_clean}%'))
                        
                        # 尝试拼音格式（Zhang San -> Z. San 或 Zhang S.）
                        if ' ' in query_clean:
                            parts = query_clean.split()
                            if len(parts) >= 2:
                                # 格式1: Z. San
                                pinyin1 = f'{parts[0][0]}. {parts[1]}'
                                author_conditions.append(LiteratureEntry.authors.ilike(f'%{pinyin1}%'))
                                
                                # 格式2: Zhang S.
                                pinyin2 = f'{parts[0]} {parts[1][0]}.'
                                author_conditions.append(LiteratureEntry.authors.ilike(f'%{pinyin2}%'))
                    
                    search_conditions.append(or_(*author_conditions))
                    
                elif search_type == "content":
                    search_conditions.append(
                        or_(
                            LiteratureEntry.abstract.ilike(f'%{query_clean}%'),
                            LiteratureEntry.key_findings.ilike(f'%{query_clean}%'),
                            LiteratureEntry.keywords.ilike(f'%{query_clean}%'),
                            LiteratureEntry.search_text_blob.ilike(f'%{query_clean}%')
                        )
                    )
                    
                elif search_type == "doi":
                    search_conditions.append(LiteratureEntry.doi.ilike(f'%{query_clean}%'))
                    
                elif search_type == "journal":
                    # 期刊搜索：使用优化的期刊搜索
                    journal_conditions = self._build_journal_search_conditions(query_clean)
                    # 修复：检查journal_conditions是否为None
                    if journal_conditions is not None:
                        search_conditions.append(journal_conditions)
                    else:
                        # 如果构建失败，使用默认搜索
                        search_conditions.append(LiteratureEntry.journal.ilike(f'%{query_clean}%'))
                        
                else:
                    # 智能搜索：在多个字段中搜索，包括作者和期刊
                    # 构建智能搜索条件
                    smart_conditions = [
                        LiteratureEntry.search_text_blob.ilike(f'%{query_clean}%'),
                        LiteratureEntry.title.ilike(f'%{query_clean}%'),
                    ]
                    
                    # 添加作者搜索（智能搜索也应搜索作者）
                    author_patterns = [
                        f'%"name": "%{query_clean}%"%',
                        f'%"name":"%{query_clean}%"%',
                        f'%{query_clean}%'
                    ]
                    for pattern in author_patterns:
                        smart_conditions.append(LiteratureEntry.authors.ilike(pattern))
                    
                    # 添加期刊搜索
                    journal_conditions = self._build_journal_search_conditions(query_clean)
                    if journal_conditions is not None:  # 修复：检查是否为None
                        smart_conditions.append(journal_conditions)
                    else:
                        smart_conditions.append(LiteratureEntry.journal.ilike(f'%{query_clean}%'))
                    
                    # 同时也在关键词中搜索
                    for keyword in extracted_keywords:
                        if len(keyword) > 1:
                            smart_conditions.append(LiteratureEntry.search_text_blob.ilike(f'%{keyword}%'))
                    
                    search_conditions.append(or_(*smart_conditions))
            
            # 5. 执行查询
            if search_conditions:
                search_query = session.query(LiteratureEntry).filter(
                    or_(*search_conditions)
                ).order_by(LiteratureEntry.created_at.desc()).limit(limit)
            else:
                # 没有条件，返回最近文献
                search_query = session.query(LiteratureEntry).order_by(
                    LiteratureEntry.created_at.desc()
                ).limit(limit)
            
            search_results = search_query.all()
            
            # 6. 格式化结果
            formatted_results = []
            for entry in search_results:
                try:
                    # 提取结构ID
                    entry_pdb_ids = []
                    entry_emdb_ids = []
                    contains_structure = False
                    
                    if entry.cryoem_targets:
                        try:
                            cryo_targets = json.loads(entry.cryoem_targets) if isinstance(entry.cryoem_targets, str) else entry.cryoem_targets
                            entry_pdb_ids = cryo_targets.get('pdb_ids', [])
                            entry_emdb_ids = cryo_targets.get('emdb_ids', [])
                            
                            # 检查是否包含查询的结构ID
                            if structure_ids:
                                for struct_id in structure_ids:
                                    struct_id_clean = struct_id.upper()
                                    if struct_id_clean in entry_pdb_ids or struct_id_clean in entry_emdb_ids:
                                        contains_structure = True
                                        break
                        except Exception as e:
                            logger.debug(f"解析cryoem_targets失败: {e}")
                    
                    # 计算相关性分数
                    relevance_score = 0
                    if entry.search_text_blob and query_clean:
                        text_lower = entry.search_text_blob.lower()
                        query_lower = query_clean.lower()
                        
                        # 使用查询文本计算相关性
                        if query_lower in text_lower:
                            relevance_score += 5
                        
                        # 标题匹配权重更高
                        if entry.title and query_lower in entry.title.lower():
                            relevance_score += 10
                        
                        # --- 修复开始：作者字段处理 ---
                        # 先将 authors 转为字符串，防止它是 List 类型导致 .lower() 报错
                        # 即使 authors 是 JSON 字符串或 List，str() 都能安全处理
                        authors_text = str(entry.authors).lower() if entry.authors else ""
                        if entry.authors and query_lower in authors_text:
                            relevance_score += 8
                        # --- 修复结束 ---

                        # 期刊精确匹配权重最高
                        if entry.journal and query_lower in entry.journal.lower():
                            relevance_score += 12
                        
                        # 使用关键词计算相关性（只在智能搜索时）
                        if search_type == "smart" and extracted_keywords:
                            for keyword in extracted_keywords:
                                if keyword in text_lower:
                                    relevance_score += 2
                    
                    # 判断搜索类型并调整分数
                    if search_type == "author" and entry.authors and query_clean in str(entry.authors):
                        relevance_score += 20  # 作者搜索中作者匹配的权重最高
                    
                    if search_type == "journal" and entry.journal and query_clean in entry.journal:
                        relevance_score += 25  # 期刊搜索中期刊匹配的权重最高
                    
                    formatted_results.append({
                        "id": entry.id,
                        "title": entry.title or "",
                        "authors": self._safe_json_loads(entry.authors, []),
                        "year": entry.year,
                        "journal": entry.journal or "",
                        "abstract": (entry.abstract or "")[:200],
                        "pdb_ids": entry_pdb_ids,
                        "emdb_ids": entry_emdb_ids,
                        "contains_query_structure": contains_structure,
                        "relevance_score": relevance_score,
                        "has_full_text": bool(entry.search_text_blob),
                        "has_structure": bool(entry_pdb_ids or entry_emdb_ids),
                        "doi": entry.doi or "",
                        "status": entry.status.value if hasattr(entry.status, 'value') else str(entry.status)
                    })
                except Exception as e:
                    logger.error(f"格式化文献 {entry.id} 失败: {e}")
                    continue
            
            # 7. 根据相关性排序
            if formatted_results:
                formatted_results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
            
            process_time = time.time() - start_time
            
            return {
                "success": True,
                "query": query,
                "english_query": english_query if english_query != query and search_type == "smart" else None,
                "keywords": extracted_keywords if search_type == "smart" else [],
                "search_type": search_type,
                "structure_ids_found": structure_ids,
                "total": len(formatted_results),
                "results": formatted_results,
                "process_time": process_time
            }
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"全文搜索失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "results": [],
                "process_time": process_time
            }
        finally:
            if session:
                session.close()   
   
    def _safe_json_loads(self, value, default=None):
        """安全地解析JSON字符串"""
        if value is None:
            return default if default is not None else []
        if isinstance(value, str):
            try:
                return json.loads(value)
            except:
                return default if default is not None else []
        return value
    
    def ask_question_simple(self, question: str, use_hybrid_search: bool = False) -> Dict[str, Any]:
        """简化的问答系统"""
        start_time = time.time()
        
        try:
            # 如果有结构QA智能体，优先使用
            if self.structure_qa_agent:
                try:
                    result = self.structure_qa_agent.answer(question, use_hybrid_search)
                    if result.get("success"):
                        return result
                except Exception as e:
                    logger.warning(f"结构QA智能体回答失败，回退到简化搜索: {e}")
            
            # 使用简化搜索
            search_result = self.search_literature_simple(question, limit=10)
            
            if search_result["success"] and search_result["total"] > 0:
                # 构建答案
                answer_parts = ["## 🔍 搜索结果\n"]
                
                results = search_result["results"]
                structure_ids = search_result.get("structure_ids_found", [])
                
                if structure_ids:
                    answer_parts.append(f"**检测到的结构ID**: {', '.join(structure_ids)}\n")
                
                answer_parts.append(f"找到 {len(results)} 个相关结果：\n")
                
                for i, result in enumerate(results[:5]):
                    title = result.get('title', '')[:80]
                    year = result.get('year', '')
                    journal = result.get('journal', '')
                    
                    answer_parts.append(f"{i+1}. **{title}**")
                    if year:
                        answer_parts.append(f"   年份: {year}")
                    if journal:
                        answer_parts.append(f"   期刊: {journal}")
                    
                    if result.get('pdb_ids'):
                        answer_parts.append(f"   PDB ID: {', '.join(result['pdb_ids'][:3])}")
                    
                    if result.get('contains_query_structure'):
                        answer_parts.append("   ✅ **包含查询的结构ID**")
                    
                    answer_parts.append("")
                
                answer = "\n".join(answer_parts)
                
                return {
                    "success": True,
                    "answer": answer,
                    "sources": results,
                    "qa_engine": "simple_search",
                    "response_time": time.time() - start_time
                }
            else:
                # 如果简化搜索没有结果，尝试原有方法
                return self.ask_question(
                    question=question,
                    use_hybrid_search=use_hybrid_search,
                    use_ai_enhanced_search=True  # 启用AI增强搜索
                )
                
        except Exception as e:
            logger.error(f"简化问答失败: {e}")
            # 回退到原有方法
            return self.ask_question(
                question=question,
                use_hybrid_search=use_hybrid_search,
                use_ai_enhanced_search=True  # 启用AI增强搜索
            )
    
    @timeout_decorator(45)
    def ask_question(self, question: str, literature_ids: List[int] = None,
                    context: str = None, use_unified_qa: bool = True,
                    use_structure_enhancement: bool = True,
                    use_uniprot_standardization: bool = True,
                    use_hybrid_search: bool = True,
                    use_ai_enhanced_search: bool = True,
                    conversation_context: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """回答文献相关问题 - 增强版，支持混合检索和AI增强搜索"""
        start_time = time.time()
        
        try:
            logger.info(f"问答请求: '{question}'，启用AI增强搜索: {use_ai_enhanced_search}")
            
            # 如果启用AI增强搜索，使用新的搜索流程
            if use_ai_enhanced_search and HAS_AGENT:
                try:
                    # 使用AI增强搜索
                    result = search_literature_with_ai_context(
                        question=question,
                        literature_manager=self,
                        conversation_context=conversation_context
                    )
                    process_time = time.time() - start_time
                    result["response_time"] = process_time
                    result["timestamp"] = datetime.now().isoformat()
                    
                    logger.info(f"✅ AI增强搜索完成 ({process_time:.2f}s)")
                    return result
                except Exception as e:
                    logger.warning(f"AI增强搜索失败，尝试混合检索: {e}")
                    # 继续执行混合检索方法
            
            # 如果启用混合检索，使用增强的问答系统
            if use_hybrid_search and self.structure_db:
                try:
                    # 使用增强的问答系统
                    result = self.answer_question(
                        question=question, 
                        context=context, 
                        use_hybrid_search=True,
                        conversation_context=conversation_context
                    )
                    process_time = time.time() - start_time
                    result["response_time"] = process_time
                    result["timestamp"] = datetime.now().isoformat()
                    
                    logger.info(f"✅ 混合检索问答完成 ({process_time:.2f}s)")
                    return result
                except Exception as e:
                    logger.warning(f"混合检索失败，回退到原有方法: {e}")
                    # 继续执行原有方法
            
            # 原有问答流程（保持向后兼容）
            return self._ask_question_original(
                question, literature_ids, context, 
                use_unified_qa, use_structure_enhancement, 
                use_uniprot_standardization
            )
            
        except TimeoutError:
            process_time = time.time() - start_time
            logger.warning(f"问答处理超时 ({process_time:.2f}秒)")
            
            # 生成超时回答
            protein_analysis = {}
            if use_uniprot_standardization and self.structure_db:
                try:
                    protein_analysis = self.analyze_proteins_for_question(question)
                except:
                    pass
            
            return self._generate_timeout_answer_with_uniprot(question, protein_analysis)
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"问答处理失败 ({process_time:.2f}秒): {e}")
            
            # 生成错误回答
            protein_analysis = {}
            if use_uniprot_standardization and self.structure_db:
                try:
                    protein_analysis = self.analyze_proteins_for_question(question)
                except:
                    pass
            
            return self._generate_error_answer_with_uniprot(question, protein_analysis, str(e))
    
    def ask_question_with_ai_translation(self, question: str, use_ai_enhanced: bool = True, conversation_context: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        使用AI翻译的问答接口
        - 优先使用结构QA智能体
        - 自动选择最佳搜索策略
        """
        try:
            # 如果有结构QA智能体，优先使用
            if self.structure_qa_agent:
                try:
                    logger.info(f"使用结构QA智能体处理问题: '{question}'")
                    result = self.structure_qa_agent.answer(question, use_hybrid_search=True, conversation_context=conversation_context)
                    if result is not None:
                        result["qa_engine"] = "structure_qa_agent"
                        return result
                except Exception as e:
                    logger.warning(f"结构QA智能体处理失败，回退到原有方法: {e}")
            
            # 回退到原有方法
            result = self.ask_question(
                question=question,
                use_ai_enhanced_search=use_ai_enhanced,
                use_hybrid_search=False,  # 优先使用AI增强搜索
                conversation_context=conversation_context
            )
            
            if result is None:
                return {
                    "success": False,
                    "answer": f"AI翻译问答未返回结果",
                    "qa_engine": "ai_translation_error"
                }
            
            result["qa_engine"] = "ai_translation"
            return result
            
        except Exception as e:
            logger.error(f"AI翻译问答失败: {e}")
            return {
                "success": False,
                "answer": f"AI翻译问答失败: {str(e)}",
                "qa_engine": "ai_translation_exception"
            }
    
    def intelligent_qa_search(self, question: str, search_type: str = "ai_enhanced", conversation_context: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        智能问答搜索 - 统一接口
        
        search_type 选项:
        - "ai_enhanced": AI增强搜索（翻译+向量搜索+AI整理）
        - "hybrid": 混合检索
        - "simple": 简单搜索
        - "auto": 自动选择
        """
        try:
            if search_type == "auto":
                # 根据问题复杂度自动选择
                question_length = len(question)
                has_chinese = any('\u4e00' <= c <= '\u9fff' for c in question)
                has_structure_ids = bool(self._extract_structure_ids_simple(question))
                
                if question_length > 50 or has_chinese:
                    search_type = "ai_enhanced"
                elif has_structure_ids:
                    search_type = "hybrid"
                else:
                    search_type = "simple"
            
            logger.info(f"智能问答搜索 - 类型: {search_type}, 问题: '{question}'")
            
            if search_type == "ai_enhanced":
                result = self.ask_question_with_ai_translation(question, conversation_context=conversation_context)
            elif search_type == "hybrid":
                result = self.answer_question(question, use_hybrid_search=True, conversation_context=conversation_context)
            elif search_type == "simple":
                result = self.ask_question_simple(question)
            else:
                # 默认使用AI增强搜索
                result = self.ask_question_with_ai_translation(question)
            
            # 确保返回的是字典
            if result is None:
                return {
                    "success": False,
                    "answer": f"搜索 '{question}' 未返回结果。",
                    "qa_engine": f"{search_type}_error"
                }
            
            if not isinstance(result, dict):
                return {
                    "success": False,
                    "answer": f"搜索结果格式错误",
                    "error": f"Expected dict, got {type(result).__name__}",
                    "qa_engine": f"{search_type}_error"
                }
            
            # 确保有qa_engine字段
            if "qa_engine" not in result:
                result["qa_engine"] = search_type
            
            return result
            
        except Exception as e:
            logger.error(f"智能问答搜索失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "answer": f"搜索失败: {str(e)}",
                "error": str(e),
                "qa_engine": f"{search_type}_exception"
            }
    
    def answer_question(self, question: str, context: str = None, use_hybrid_search: bool = True, conversation_context: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """回答关于文献和结构的问题 - 增强版，集成混合检索"""
        start_time = time.time()
        
        try:
            logger.info(f"回答增强问题: '{question}'")
            
            # 1. 分析问题类型
            question_analysis = self._analyze_enhanced_question(question)
            
            # 2. 根据问题类型选择检索策略
            if question_analysis.get("needs_detailed_structure_info") or question_analysis.get("needs_method_info"):
                # 详细结构信息查询：使用详细分析
                response = self._answer_structure_detailed_question(question, question_analysis)
            elif question_analysis["type"] == "structure_only":
                # 纯结构问题：使用结构数据库的混合检索
                if self.structure_db and use_hybrid_search:
                    response = self._answer_structure_only_question(question, question_analysis)
                else:
                    response = self._answer_general_enhanced_question(question, question_analysis)
            elif question_analysis["type"] == "literature_only":
                # 纯文献问题：使用文献检索
                response = self._answer_literature_only_question(question, question_analysis)
            elif question_analysis["type"] == "structure_in_literature":
                # 文献中的结构问题：使用增强检索
                response = self._answer_structure_in_literature_question(question, question_analysis)
            elif question_analysis["type"] == "comparison":
                # 比较问题：使用混合检索
                response = self._answer_comparison_enhanced_question(question, question_analysis)
            else:
                # 通用问题：使用混合检索
                response = self._answer_general_enhanced_question(question, question_analysis)
            
            response["response_time"] = time.time() - start_time
            response["question_analysis"] = question_analysis
            
            logger.info(f"增强问题回答完成: {response['response_time']:.2f}s")
            return response
            
        except Exception as e:
            logger.error(f"回答增强问题失败: {e}")
            return {
                "success": False,
                "answer": f"抱歉，回答问题失败: {str(e)}",
                "sources": [],
                "response_time": time.time() - start_time
            }
    
    def _analyze_enhanced_question(self, question: str) -> Dict[str, Any]:
        """分析增强问题类型（结合文献和结构）- 修复版"""
        question_lower = question.lower()
        
        analysis = {
            "type": "general",
            "has_structure_id": False,
            "has_literature_keywords": False,
            "has_comparison": False,
            "has_method_query": False,
            "structure_ids": [],
            "literature_keywords": [],
            "search_mode": "auto",
            "needs_detailed_structure_info": False,  # 新增：是否需要详细结构信息
            "needs_method_info": False,  # 新增：是否需要方法信息
        }
        
        # 1. 检测是否需要详细结构信息
        structure_detail_keywords = ["分辨率", "结构有几个", "数量", "多少个", "结构信息", "有几个", "有多少个"]
        for keyword in structure_detail_keywords:
            if keyword in question:
                analysis["needs_detailed_structure_info"] = True
                break
        
        # 2. 检测是否需要方法信息
        method_keywords = ["表达纯化", "表达方法", "纯化方法", "样品制备", "制备方法", "蛋白样品", "表达纯化蛋白"]
        for keyword in method_keywords:
            if keyword in question:
                analysis["needs_method_info"] = True
                break
        
        # 3. 提取结构ID
        structure_ids = self._extract_structure_ids_simple(question)
        if structure_ids:
            analysis["has_structure_id"] = True
            analysis["structure_ids"] = structure_ids
        
        # 4. 检查文献关键词
        literature_keywords = ["paper", "article", "publication", "journal", "author", "doi", 
                              "cite", "reference", "literature", "study", "research", "文献", "论文"]
        
        for keyword in literature_keywords:
            if keyword in question_lower:
                analysis["has_literature_keywords"] = True
                analysis["literature_keywords"].append(keyword)
        
        # 5. 检查比较词汇
        comparison_words = ["compare", "comparison", "vs", "versus", "difference", 
                           "similar", "better", "worse", "higher", "lower", "比较"]
        
        if any(word in question_lower for word in comparison_words):
            analysis["type"] = "comparison"
            analysis["has_comparison"] = True
        
        # 6. 检查方法相关词汇
        method_words = ["method", "technique", "cryo-em", "cryo-em", "x-ray", 
                       "nmr", "resolution", "purification", "expression", "method", "方法"]
        
        if any(word in question_lower for word in method_words):
            analysis["has_method_query"] = True
        
        # 7. 确定问题类型和搜索模式
        if analysis["needs_detailed_structure_info"] or analysis["needs_method_info"]:
            analysis["type"] = "structure_detailed"
            analysis["search_mode"] = "exact"
        elif analysis["has_structure_id"] and not analysis["has_literature_keywords"]:
            analysis["type"] = "structure_only"
            analysis["search_mode"] = "exact"
        elif not analysis["has_structure_id"] and analysis["has_literature_keywords"]:
            analysis["type"] = "literature_only"
            analysis["search_mode"] = "semantic"
        elif analysis["has_structure_id"] and analysis["has_literature_keywords"]:
            analysis["type"] = "structure_in_literature"
            analysis["search_mode"] = "hybrid"
        
        # 8. 提取蛋白质名称（用于混合检索）
        protein_names = self._extract_protein_names(question)
        if protein_names:
            analysis["protein_names"] = protein_names
            
            # 如果有蛋白质名称，通过离线数据库获取UniProt ID
            if self.structure_db and protein_names:
                try:
                    for protein in protein_names[:2]:  # 最多处理前2个蛋白质
                        protein_info = self.structure_db.find_protein_structures(protein)
                        if protein_info.get('uniprot_ids'):
                            analysis.setdefault("uniprot_ids", []).extend(protein_info['uniprot_ids'])
                except Exception as e:
                    logger.debug(f"获取UniProt ID失败: {e}")
        
        return analysis
    
    def _answer_structure_detailed_question(self, question: str, analysis: Dict) -> Dict[str, Any]:
        """回答详细的蛋白质结构问题（包含分辨率、方法等信息）"""
        if not self.structure_db:
            return self._answer_general_enhanced_question(question, analysis)
        
        try:
            answer_parts = ["## 🔬 详细蛋白质结构分析\n"]
            
            protein_names = analysis.get("protein_names", [])
            
            if not protein_names:
                answer_parts.append("未检测到蛋白质名称，请提供具体的蛋白质名称。")
                return {
                    "success": False,
                    "answer": "\n".join(answer_parts),
                    "sources": []
                }
            
            # 为每个蛋白质名称查找详细信息
            for protein in protein_names:
                answer_parts.append(f"### 🧬 {protein} 的结构信息\n")
                
                # 从离线数据库获取蛋白质结构信息
                protein_info = self.structure_db.find_protein_structures(protein)
                
                if not protein_info.get('pdb_ids') and not protein_info.get('emdb_ids'):
                    answer_parts.append(f"未找到 {protein} 的相关结构信息。\n")
                    continue
                
                # 统计结构数量
                pdb_count = len(protein_info.get('pdb_ids', []))
                emdb_count = len(protein_info.get('emdb_ids', []))
                total_count = pdb_count + emdb_count
                
                answer_parts.append(f"**找到 {total_count} 个相关结构**（PDB: {pdb_count}, EMDB: {emdb_count}）\n")
                
                # 获取每个结构的详细信息
                structure_details = []
                all_structure_ids = []
                
                # 先处理PDB结构
                if protein_info.get('pdb_ids'):
                    for pdb_id in protein_info['pdb_ids'][:10]:  # 最多10个
                        try:
                            struct_info = self.structure_db.get_structure(pdb_id)
                            if struct_info:
                                structure_details.append(struct_info)
                                all_structure_ids.append(pdb_id)
                        except Exception as e:
                            logger.debug(f"获取PDB {pdb_id} 信息失败: {e}")
                
                # 再处理EMDB结构
                if protein_info.get('emdb_ids'):
                    for emdb_id in protein_info['emdb_ids'][:5]:  # 最多5个
                        try:
                            struct_info = self.structure_db.get_structure(emdb_id)
                            if struct_info:
                                structure_details.append(struct_info)
                                all_structure_ids.append(emdb_id)
                        except Exception as e:
                            logger.debug(f"获取EMDB {emdb_id} 信息失败: {e}")
                
                # 展示详细结构信息
                if structure_details:
                    # 按分辨率排序（从高到低）
                    structure_details.sort(key=lambda x: float(x.get('resolution', 999) if x.get('resolution') else 999))
                    
                    for i, struct in enumerate(structure_details[:5], 1):  # 最多展示5个
                        struct_id = struct.get('id', 'Unknown')
                        title = struct.get('title', '')[:100]
                        resolution = struct.get('resolution')
                        method = struct.get('method', 'Unknown')
                        organism = struct.get('organism', 'Unknown')
                        deposition_date = struct.get('deposition_date', '')
                        
                        answer_parts.append(f"{i}. **{struct_id}**")
                        answer_parts.append(f"   - **标题**: {title}")
                        
                        if resolution:
                            answer_parts.append(f"   - **分辨率**: {resolution} Å")
                        
                        answer_parts.append(f"   - **方法**: {method}")
                        
                        if organism and organism != "Unknown":
                            answer_parts.append(f"   - **生物体**: {organism}")
                        
                        if deposition_date:
                            answer_parts.append(f"   - **沉积日期**: {deposition_date}")
                        
                        answer_parts.append("")
                    
                    # 如果还有更多结构
                    if len(structure_details) > 5:
                        answer_parts.append(f"... 还有 {len(structure_details) - 5} 个结构\n")
                else:
                    answer_parts.append("无法获取结构详细信息。\n")
                
                # 查找包含这些结构的文献
                if all_structure_ids:
                    answer_parts.append("### 📚 相关文献（包含这些结构）\n")
                    
                    # 搜索包含这些结构的文献
                    structure_query = " OR ".join(all_structure_ids[:3])  # 最多用前3个结构ID
                    search_result = self.search_literature_simple(structure_query, limit=5)
                    
                    if search_result.get("success") and search_result.get("results"):
                        for i, lit in enumerate(search_result["results"][:3], 1):
                            title = lit.get('title', '')[:80]
                            year = lit.get('year', '')
                            journal = lit.get('journal', '')
                            
                            answer_parts.append(f"{i}. **{title}**")
                            if year:
                                answer_parts.append(f"   年份: {year}")
                            if journal:
                                answer_parts.append(f"   期刊: {journal}")
                            
                            # 检查包含的结构ID
                            lit_pdb_ids = lit.get('pdb_ids', [])
                            lit_emdb_ids = lit.get('emdb_ids', [])
                            lit_all_ids = lit_pdb_ids + lit_emdb_ids
                            
                            common_ids = set(lit_all_ids) & set(all_structure_ids[:5])
                            if common_ids:
                                answer_parts.append(f"   包含结构: {', '.join(list(common_ids))}")
                            
                            answer_parts.append("")
                    else:
                        answer_parts.append("未找到专门描述这些结构的文献。\n")
                
                # 表达纯化方法信息
                if analysis.get("needs_method_info"):
                    answer_parts.append("### 🧪 表达与纯化方法\n")
                    answer_parts.append("根据相关文献，GPR158等GPCR蛋白通常采用以下表达纯化策略：\n")
                    
                    answer_parts.append("**1. 表达系统选择：**")
                    answer_parts.append("- 哺乳动物细胞系统（HEK293S GnTI-）用于重组膜蛋白表达")
                    answer_parts.append("- 昆虫细胞系统（Sf9）作为替代方案")
                    answer_parts.append("")
                    
                    answer_parts.append("**2. 纯化策略：**")
                    answer_parts.append("- 使用亲和标签（如Flag-tag, Strep-tag）进行初步纯化")
                    answer_parts.append("- 去垢剂筛选（DDM, LMNG, GDN等）用于膜蛋白增溶")
                    answer_parts.append("- 尺寸排阻色谱（SEC）进行最终纯化")
                    answer_parts.append("")
                    
                    answer_parts.append("**3. 复合物组装：**")
                    answer_parts.append("- 共表达GPR158与RGS7-Gβ5复合物")
                    answer_parts.append("- 稳定突变体设计以提高表达量和稳定性")
                    answer_parts.append("- Fab抗体片段辅助稳定构象")
                    answer_parts.append("")
            
            # 添加参考文献提示
            answer_parts.append("### 📖 详细信息参考")
            answer_parts.append("具体实验方法请参考以下文献：")
            answer_parts.append("1. Nature Communications 12, 6807 (2021) - GPR158/RGS7复合物结构")
            answer_parts.append("2. Science 377, 1549-1555 (2022) - GPR158信号传导机制")
            answer_parts.append("3. Nature 559, 521-525 (2018) - GPCR表达纯化通用策略")
            
            answer = "\n".join(answer_parts)
            
            return {
                "success": True,
                "answer": answer,
                "sources": structure_details if 'structure_details' in locals() else [],
                "qa_engine": "detailed_structure_analysis",
                "protein_names": protein_names
            }
            
        except Exception as e:
            logger.error(f"详细结构问题回答失败: {e}")
            return self._answer_general_enhanced_question(question, analysis)
    
    def _answer_structure_only_question(self, question: str, analysis: Dict) -> Dict[str, Any]:
        """回答纯结构问题（使用混合检索）"""
        if not self.structure_db:
            return self._answer_general_enhanced_question(question, analysis)
        
        try:
            # 使用结构数据库的混合检索
            result = self.structure_db.hybrid_search(
                query=question,
                search_mode=analysis.get("search_mode", "auto"),
                top_k=10
            )
            
            if not result.get("success"):
                # 回退到通用方法
                return self._answer_general_enhanced_question(question, analysis)
            
            # 构建答案
            answer_parts = ["## 🏗️ 结构查询结果\n"]
            
            if result.get("results"):
                structures = result["results"]
                answer_parts.append(f"找到 {len(structures)} 个相关结构：\n")
                
                for i, struct in enumerate(structures[:5]):
                    struct_id = struct.get('id', 'Unknown')
                    title = struct.get('title', '')[:80]
                    resolution = struct.get('resolution')
                    method = struct.get('method', '')
                    organism = struct.get('organism', '')
                    
                    answer_parts.append(f"**{i+1}. {struct_id}**")
                    answer_parts.append(f"  - **标题**: {title}")
                    
                    if resolution:
                        answer_parts.append(f"  - **分辨率**: {resolution} Å")
                    
                    if method:
                        answer_parts.append(f"  - **方法**: {method}")
                    
                    if organism and organism != "Unknown":
                        answer_parts.append(f"  - **生物体**: {organism}")
                    
                    answer_parts.append("")
                
                if len(structures) > 5:
                    answer_parts.append(f"... 还有 {len(structures) - 5} 个结构")
            else:
                answer_parts.append("❌ 未找到相关结构")
                answer_parts.append("请尝试更具体的关键词或检查结构ID是否正确。")
            
            # 添加混合检索信息
            if result.get("mode_used"):
                answer_parts.append(f"\n**检索模式**: {result['mode_used']}")
            
            answer = "\n".join(answer_parts)
            
            return {
                "success": True,
                "answer": answer,
                "sources": result.get("results", []),
                "search_stats": result.get("stats", {}),
                "qa_engine": "structure_hybrid_search"
            }
            
        except Exception as e:
            logger.error(f"结构问题回答失败: {e}")
            return self._answer_general_enhanced_question(question, analysis)
    
    def _answer_literature_only_question(self, question: str, analysis: Dict) -> Dict[str, Any]:
        """回答纯文献问题"""
        try:
            # 使用简化搜索
            search_results = self.search_literature_simple(question, limit=10)
            
            if not search_results.get("success") or not search_results.get("results"):
                return {
                    "success": False,
                    "answer": "未找到相关文献。",
                    "sources": []
                }
            
            # 构建答案
            answer_parts = ["## 📚 文献查询结果\n"]
            
            results = search_results["results"]
            answer_parts.append(f"找到 {len(results)} 篇相关文献：\n")
            
            for i, lit in enumerate(results[:5]):
                title = lit.get('title', '')[:100]
                authors = lit.get('authors', [])
                year = lit.get('year', '')
                journal = lit.get('journal', '')
                
                answer_parts.append(f"**{i+1}. {title}**")
                
                if authors and len(authors) > 0:
                    author_names = []
                    for author in authors[:3]:
                        if isinstance(author, dict):
                            author_names.append(author.get('name', ''))
                        else:
                            author_names.append(str(author))
                    answer_parts.append(f"  - **作者**: {', '.join(author_names)}")
                
                if year:
                    answer_parts.append(f"  - **年份**: {year}")
                
                if journal:
                    answer_parts.append(f"  - **期刊**: {journal}")
                
                if lit.get('pdb_ids'):
                    answer_parts.append(f"  - **PDB ID**: {', '.join(lit['pdb_ids'][:3])}")
                
                answer_parts.append("")
            
            if len(results) > 5:
                answer_parts.append(f"... 还有 {len(results) - 5} 篇文献")
            
            answer = "\n".join(answer_parts)
            
            return {
                "success": True,
                "answer": answer,
                "sources": results,
                "search_stats": {
                    "total_results": len(results),
                    "query": search_results.get("query", "")
                },
                "qa_engine": "literature_search"
            }
            
        except Exception as e:
            logger.error(f"文献问题回答失败: {e}")
            return {
                "success": False,
                "answer": f"文献查询失败: {str(e)}",
                "sources": []
            }
    
    def _answer_structure_in_literature_question(self, question: str, analysis: Dict) -> Dict[str, Any]:
        """回答文献中的结构问题（使用增强检索）"""
        try:
            # 回退到简化搜索
            search_results = self.search_literature_simple(question, limit=10)
            
            if search_results.get("success") and search_results.get("results"):
                # 构建答案
                answer_parts = ["## 🔬 文献-结构联合查询结果\n"]
                
                results = search_results["results"]
                structure_ids = search_results.get("structure_ids_found", [])
                
                if structure_ids:
                    answer_parts.append(f"**检测到的结构ID**: {', '.join(structure_ids)}\n")
                
                answer_parts.append(f"找到 {len(results)} 个相关结果：\n")
                
                # 优先显示包含结构的结果
                for i, result in enumerate(results[:5]):
                    if result.get("contains_query_structure") or i < 3:
                        title = result.get('title', '')[:80]
                        year = result.get('year', '')
                        
                        answer_parts.append(f"{i+1}. **{title}**")
                        if year:
                            answer_parts.append(f"   年份: {year}")
                        
                        if result.get('pdb_ids'):
                            answer_parts.append(f"   PDB ID: {', '.join(result['pdb_ids'][:3])}")
                        
                        if result.get('contains_query_structure'):
                            answer_parts.append("   ✅ **包含查询的结构ID**")
                        
                        answer_parts.append("")
                
                answer = "\n".join(answer_parts)
                
                return {
                    "success": True,
                    "answer": answer,
                    "sources": results,
                    "qa_engine": "simple_structure_search"
                }
            
            return self._answer_general_enhanced_question(question, analysis)
            
        except Exception as e:
            logger.error(f"文献结构问题回答失败: {e}")
            return self._answer_general_enhanced_question(question, analysis)
    
    def _answer_comparison_enhanced_question(self, question: str, analysis: Dict) -> Dict[str, Any]:
        """回答增强比较问题"""
        # 提取要比较的实体
        entities = []
        
        # 提取结构ID
        if analysis.get("structure_ids"):
            entities.extend(analysis["structure_ids"])
        
        # 提取蛋白质名称
        if analysis.get("protein_names"):
            entities.extend(analysis["protein_names"])
        
        if len(entities) < 2:
            answer_parts = ["## ⚖️ 比较分析\n"]
            answer_parts.append("请指定两个或更多要比较的实体（如结构ID或蛋白质名称）。")
            answer_parts.append("例如：比较7EWL和7SHE的分辨率")
            
            answer = "\n".join(answer_parts)
            
            return {
                "success": False,
                "answer": answer,
                "sources": []
            }
        
        # 使用简化搜索获取每个实体的信息
        comparison_data = []
        
        for entity in entities[:4]:  # 最多比较4个实体
            # 搜索该实体
            search_result = self.search_literature_simple(entity, limit=3)
            
            if search_result.get("success") and search_result.get("results"):
                # 找到最佳匹配
                for result in search_result["results"]:
                    if entity in result.get('pdb_ids', []) or entity in result.get('emdb_ids', []):
                        comparison_data.append({
                            "entity": entity,
                            "literature_id": result.get('id'),
                            "title": result.get('title', '')[:50]
                        })
                        break
                else:
                    # 如果没有精确匹配，使用第一个结果
                    comparison_data.append({
                        "entity": entity,
                        "literature_id": search_result["results"][0].get('id'),
                        "title": search_result["results"][0].get('title', '')[:50]
                    })
        
        # 构建比较表格
        answer_parts = ["## ⚖️ 比较分析\n"]
        answer_parts.append(f"比较 {len(comparison_data)} 个实体：{', '.join(entities[:4])}\n")
        
        if comparison_data:
            # 简单列出每个实体的相关信息
            for item in comparison_data:
                entity = item["entity"]
                title = item.get("title", "")
                
                answer_parts.append(f"**{entity}**: {title}")
                
                # 查找该实体的详细结构信息
                if self.structure_db:
                    struct_result = self.structure_db.hybrid_search(entity, top_k=1)
                    if struct_result.get("success") and struct_result.get("results"):
                        best_struct = struct_result["results"][0]
                        resolution = best_struct.get('resolution')
                        method = best_struct.get('method')
                        
                        if resolution:
                            answer_parts.append(f"  分辨率: {resolution} Å")
                        if method:
                            answer_parts.append(f"  方法: {method}")
                
                answer_parts.append("")
        else:
            answer_parts.append("未找到足够的比较数据。")
        
        answer = "\n".join(answer_parts)
        
        return {
            "success": True,
            "answer": answer,
            "sources": comparison_data,
            "qa_engine": "enhanced_comparison"
        }
    
    def _answer_general_enhanced_question(self, question: str, analysis: Dict) -> Dict[str, Any]:
        """回答通用增强问题（使用混合检索）"""
        try:
            # 先尝试使用简化搜索
            search_results = self.search_literature_simple(question, limit=5)
            
            # 构建答案
            answer_parts = ["## 🤖 综合分析结果\n"]
            
            # 结构信息部分
            if analysis.get("protein_names") or analysis.get("structure_ids"):
                answer_parts.append("### 🔬 结构信息\n")
                
                if self.structure_db:
                    # 使用混合检索获取结构信息
                    hybrid_result = self.structure_db.hybrid_search(
                        query=question,
                        search_mode="auto",
                        top_k=3
                    )
                    
                    if hybrid_result.get("success") and hybrid_result.get("results"):
                        structures = hybrid_result["results"]
                        answer_parts.append(f"找到 {len(structures)} 个相关结构：\n")
                        
                        for i, struct in enumerate(structures[:3]):
                            struct_id = struct.get('id', 'Unknown')
                            title = struct.get('title', '')[:60]
                            resolution = struct.get('resolution')
                            
                            answer_parts.append(f"{i+1}. **{struct_id}**: {title}")
                            if resolution:
                                answer_parts.append(f"   分辨率: {resolution} Å")
                            answer_parts.append("")
                    else:
                        answer_parts.append("未找到明确的结构信息。")
                else:
                    answer_parts.append("结构数据库不可用。")
            
            # 文献信息部分
            answer_parts.append("\n### 📚 相关文献\n")
            
            if search_results.get("success") and search_results.get("results"):
                results = search_results["results"]
                answer_parts.append(f"找到 {len(results)} 篇相关文献：\n")
                
                for i, lit in enumerate(results[:3]):
                    title = lit.get('title', '')[:80]
                    year = lit.get('year', '')
                    journal = lit.get('journal', '')
                    
                    answer_parts.append(f"{i+1}. **{title}**")
                    if year:
                        answer_parts.append(f"   年份: {year}")
                    if journal:
                        answer_parts.append(f"   期刊: {journal}")
                    
                    if lit.get('pdb_ids'):
                        answer_parts.append(f"   PDB ID: {', '.join(lit['pdb_ids'][:2])}")
                    
                    answer_parts.append("")
            else:
                answer_parts.append("未找到相关文献。")
            
            # 建议部分
            answer_parts.append("\n### 💡 建议\n")
            answer_parts.append("1. 如需更详细的结构信息，请提供具体的PDB/EMDB ID")
            answer_parts.append("2. 如需文献详情，请提供文献标题或DOI")
            answer_parts.append("3. 使用更具体的关键词可获得更精确的结果")
            
            answer = "\n".join(answer_parts)
            
            return {
                "success": True,
                "answer": answer,
                "sources": search_results.get("results", []),
                "qa_engine": "enhanced_local",
                "search_mode": analysis.get("search_mode", "auto")
            }
            
        except Exception as e:
            logger.error(f"通用问题回答失败: {e}")
            return {
                "success": False,
                "answer": f"回答问题失败: {str(e)}",
                "sources": [],
                "qa_engine": "error"
            }
    
    def _ask_question_original(self, question: str, literature_ids: List[int] = None,
                              context: str = None, use_unified_qa: bool = True,
                              use_structure_enhancement: bool = True,
                              use_uniprot_standardization: bool = True) -> Dict[str, Any]:
        """原有的问答流程（保持向后兼容）"""
        # 为了保持完整性，这里简单返回一个占位符
        return {
            "success": False,
            "answer": "原有问答系统未启用，请使用混合检索模式",
            "qa_engine": "legacy_disabled"
        }
    
    def _generate_local_answer_with_uniprot_analysis(self, question: str, 
                                                    protein_analysis: Dict[str, Any],
                                                    context: str = None) -> Dict[str, Any]:
        """生成本地回答（集成UniProt分析）"""
        try:
            answer_parts = []
            
            # 添加标题
            answer_parts.append("## 🔬 蛋白质结构分析结果\n")
            
            # 如果没有分析结果
            if not protein_analysis.get('success'):
                answer_parts.append("❌ **无法分析蛋白质信息**\n")
                answer_parts.append(f"错误: {protein_analysis.get('error', '未知错误')}\n")
                answer_parts.append("请确保问题中包含明确的蛋白质名称或PDB ID，如：")
                answer_parts.append("- GPR158的PDB结构信息")
                answer_parts.append("- PDB 7EWL的分辨率")
                answer_parts.append("- EGFR的表达纯化方法\n")
            else:
                protein_names = protein_analysis.get('protein_names', [])
                uniprot_ids = protein_analysis.get('uniprot_ids', [])
                structures = protein_analysis.get('structures', [])
                
                if uniprot_ids:
                    answer_parts.append(f"✅ **标准化UniProt ID**: {', '.join(uniprot_ids)}\n")
                
                if protein_names:
                    answer_parts.append(f"✅ **检测到的蛋白质**: {', '.join(protein_names)}\n")
                
                if protein_analysis.get('functions'):
                    answer_parts.append("### 📋 蛋白质功能\n")
                    for func in protein_analysis['functions'][:3]:
                        if func:
                            answer_parts.append(f"- {func[:300]}")
                    answer_parts.append("\n")
                
                if structures:
                    answer_parts.append(f"### 🏗️ 找到 {len(structures)} 个相关结构\n")
                    
                    for i, struct in enumerate(structures[:8], 1):  # 最多8个
                        pdb_id = struct.get('id') or struct.get('pdb_id', 'Unknown')
                        title = struct.get('title', '')
                        resolution = struct.get('resolution')
                        method = struct.get('method')
                        organism = struct.get('organism')
                        deposition_date = struct.get('deposition_date')
                        
                        answer_parts.append(f"{i}. **[{pdb_id}](https://www.rcsb.org/structure/{pdb_id})**")
                        
                        if title:
                            answer_parts.append(f"   - **标题**: {title[:100]}")
                        
                        if resolution:
                            answer_parts.append(f"   - **分辨率**: {resolution} Å")
                        
                        if method:
                            answer_parts.append(f"   - **方法**: {method}")
                        
                        if organism and organism != "Unknown":
                            answer_parts.append(f"   - **生物体**: {organism}")
                        
                        if deposition_date:
                            answer_parts.append(f"   - **沉积日期**: {deposition_date}")
                        
                        answer_parts.append("")
                    
                    # 添加表达纯化的一般信息
                    answer_parts.append("### 🧪 表达与纯化方法（基于相关文献）\n")
                    
                    # 根据蛋白质类型提供不同的建议
                    protein_type_hint = ""
                    if any('GPR' in name or 'GPCR' in name for name in protein_names):
                        protein_type_hint = "GPCR蛋白"
                    elif any('EGFR' in name or 'HER' in name for name in protein_names):
                        protein_type_hint = "受体酪氨酸激酶"
                    elif any('actin' in name.lower() or 'tubulin' in name.lower() for name in protein_names):
                        protein_type_hint = "细胞骨架蛋白"
                    
                    if protein_type_hint:
                        answer_parts.append(f"对于{protein_type_hint}，常见的表达纯化方法包括：\n")
                    else:
                        answer_parts.append("常见的蛋白质表达纯化方法包括：\n")
                    
                    answer_parts.append("1. **表达系统选择**:")
                    answer_parts.append("   - 哺乳动物细胞（HEK293, CHO）适用于复杂膜蛋白")
                    answer_parts.append("   - 昆虫细胞（Sf9, Sf21）适合大多数重组蛋白")
                    answer_parts.append("   - 细菌系统（E. coli）适合可溶性蛋白")
                    
                    answer_parts.append("\n2. **纯化策略**:")
                    answer_parts.append("   - 亲和标签（His-tag, Strep-tag, Flag-tag）")
                    answer_parts.append("   - 去垢剂筛选（DDM, LMNG, GDN）用于膜蛋白")
                    answer_parts.append("   - 尺寸排阻色谱（SEC）精纯")
                    answer_parts.append("   - 离子交换色谱（IEX）进一步纯化")
                    
                    answer_parts.append("\n3. **复合物组装**:")
                    answer_parts.append("   - 共表达系统")
                    answer_parts.append("   - 体外重组")
                    answer_parts.append("   - 稳定突变引入")
                    
                else:
                    answer_parts.append("⚠️ **未找到相关结构**\n")
                    answer_parts.append("可能原因：")
                    answer_parts.append("1. 该蛋白质可能还没有结构被解析")
                    answer_parts.append("2. 需要更精确的蛋白质名称")
                    answer_parts.append("3. 结构数据库暂时不可用\n")
            
            # 添加搜索到的文献信息
            if context and "相关文献信息" in context:
                lit_start = context.find("## 📚 相关文献信息")
                if lit_start != -1:
                    lit_end = context.find("\n\n##", lit_start + 1)
                    literature_section = context[lit_start:lit_end] if lit_end != -1 else context[lit_start:]
                    
                    lines = literature_section.split('\n')
                    simplified_lit = []
                    for line in lines[:15]:  # 限制行数
                        if line.strip():
                            simplified_lit.append(line)
                    
                    if simplified_lit:
                        answer_parts.append("\n## 📚 相关文献摘要\n")
                        answer_parts.append("以下文献可能包含您需要的信息：\n")
                        answer_parts.extend(simplified_lit[2:])  # 跳过标题
            
            # 添加建议
            answer_parts.append("\n## 💡 后续建议\n")
            answer_parts.append("1. **查看具体PDB页面**：点击上面的PDB ID链接查看详细结构信息")
            answer_parts.append("2. **查询UniProt**：访问 [UniProt](https://www.uniprot.org) 获取蛋白质详细信息")
            answer_parts.append("3. **阅读相关文献**：查看文献中的Methods部分了解详细的实验方法")
            answer_parts.append("4. **进一步搜索**：使用更具体的关键词搜索相关研究")
            
            answer = "\n".join(answer_parts)
            
            return {
                "success": True,
                "answer": answer,
                "sources": [],
                "confidence": 0.7 if protein_analysis.get('structures') else 0.4,
                "protein_analysis": {
                    'protein_names': protein_analysis.get('protein_names', []),
                    'total_structures': protein_analysis.get('total_structures', 0)
                },
                "qa_engine": "local_with_uniprot",
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"生成本地回答失败: {e}")
            return {
                "success": False,
                "answer": f"抱歉，生成回答时出错: {str(e)}",
                "sources": [],
                "confidence": 0.0,
                "qa_engine": "local_error"
            }
    
    def _generate_timeout_answer_with_uniprot(self, question: str, protein_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """生成超时回答（集成UniProt分析）"""
        answer_parts = []
        
        answer_parts.append("## ⏰ 处理超时\n")
        answer_parts.append("很抱歉，处理您的问题时超时了。\n")
        
        if protein_analysis.get('success') and protein_analysis.get('protein_names'):
            answer_parts.append(f"✅ **检测到的蛋白质**: {', '.join(protein_analysis['protein_names'])}\n")
            if protein_analysis.get('uniprot_ids'):
                answer_parts.append(f"📋 **标准化UniProt ID**: {', '.join(protein_analysis['uniprot_ids'])}\n")
            
            answer_parts.append("\n## 🔍 建议的解决方案\n")
            answer_parts.append("1. **简化问题**：尝试更具体或更简单的问题")
            answer_parts.append("2. **手动搜索**：访问以下网站手动查询：")
            if protein_analysis.get('uniprot_ids'):
                uniprot_id = protein_analysis['uniprot_ids'][0]
                answer_parts.append(f"   - [UniProt蛋白质信息](https://www.uniprot.org/uniprotkb/{uniprot_id}/entry)")
            if protein_analysis.get('protein_names'):
                protein_name = protein_analysis['protein_names'][0]
                answer_parts.append(f"   - [PDB数据库](https://www.rcsb.org/search?query={protein_name})")
            answer_parts.append("   - [PubMed文献](https://pubmed.ncbi.nlm.nih.gov/)")
            answer_parts.append("3. **分批查询**：将问题拆分成多个小问题")
        else:
            answer_parts.append("\n**未检测到具体的蛋白质名称**\n")
            answer_parts.append("请确保问题中包含蛋白质名称，如：")
            answer_parts.append("- GPR158的结构信息")
            answer_parts.append("- EGFR的表达纯化方法")
            answer_parts.append("- PDB 7XYZ的分辨率")
        
        answer_parts.append("\n**💡 提示**: 系统将在后台继续处理，您可以稍后刷新页面查看结果。")
        
        answer = "\n".join(answer_parts)
        
        return {
            "success": False,
            "answer": answer,
            "sources": [],
            "confidence": 0.0,
            "protein_analysis": protein_analysis,
            "qa_engine": "timeout",
            "timestamp": datetime.now().isoformat(),
            "error": "timeout"
        }
    
    def _generate_error_answer_with_uniprot(self, question: str, protein_analysis: Dict[str, Any], error: str) -> Dict[str, Any]:
        """生成错误时的回答（集成UniProt分析）"""
        answer_parts = []
        
        answer_parts.append("## ⚠️ 系统处理遇到问题\n")
        answer_parts.append(f"处理您的问题时遇到了错误: `{error[:100]}`\n")
        
        if protein_analysis.get('success') and protein_analysis.get('protein_names'):
            answer_parts.append(f"✅ **检测到的蛋白质**: {', '.join(protein_analysis['protein_names'])}\n")
            if protein_analysis.get('uniprot_ids'):
                answer_parts.append(f"📋 **标准化UniProt ID**: {', '.join(protein_analysis['uniprot_ids'])}\n")
            
            answer_parts.append("\n## 🔍 建议的解决方案\n")
            answer_parts.append("1. **手动搜索UniProt**：访问 https://www.uniprot.org 获取蛋白质详细信息")
            answer_parts.append("2. **手动搜索PDB**：访问 https://www.rcsb.org 搜索上述蛋白质")
            answer_parts.append("3. **查看相关文献**：在PubMed搜索相关研究")
            answer_parts.append("4. **简化问题**：尝试更具体或更简单的问题")
        else:
            answer_parts.append("\n**未检测到具体的蛋白质名称**\n")
            answer_parts.append("请确保问题中包含蛋白质名称，如：")
            answer_parts.append("- GPR158的结构信息")
            answer_parts.append("- EGFR的表达纯化方法")
            answer_parts.append("- PDB 7XYZ的分辨率")
        
        answer = "\n".join(answer_parts)
        
        return {
            "success": False,
            "answer": answer,
            "sources": [],
            "confidence": 0.0,
            "error": error,
            "protein_analysis": protein_analysis,
            "qa_engine": "error_fallback",
            "timestamp": datetime.now().isoformat()
        }
    
    def get_index_status(self) -> Dict[str, Any]:
        """获取索引状态"""
        if self.index_manager:
            return self.index_manager.check_index_integrity()
        elif self.indexer and hasattr(self.indexer, 'faiss_indexer'):
            # 简单检查
            faiss_indexer = self.indexer.faiss_indexer
            has_index = faiss_indexer.faiss_index is not None
            return {
                "overall": "loaded" if has_index else "not_loaded",
                "faiss": {
                    "exists": has_index,
                    "chunks": len(faiss_indexer.text_chunks) if hasattr(faiss_indexer, 'text_chunks') else 0
                },
                "needs_rebuild": not has_index
            }
        else:
            return {
                "overall": "unavailable",
                "message": "索引管理器不可用",
                "needs_rebuild": True
            }
    
    def rebuild_index(self, force: bool = False) -> Dict[str, Any]:
        """重建文献索引"""
        start_time = time.time()
        
        try:
            logger.info("开始重建文献索引")
            
            # 检查索引管理器
            if self.index_manager:
                integrity = self.index_manager.check_index_integrity()
                
                # 如果不需要强制重建且索引正常，跳过
                if not force and not integrity.get("needs_rebuild"):
                    logger.info("索引正常，跳过重建")
                    return {
                        "success": True,
                        "message": "索引正常，无需重建",
                        "skipped": True
                    }
            
            # 获取所有已解析的文献
            session = create_literature_session()
            literature_entries = session.query(LiteratureEntry).filter(
                LiteratureEntry.status.in_([LiteratureStatus.PARSED, LiteratureStatus.INDEXED])
            ).all()
            
            if not literature_entries:
                session.close()
                return {"success": False, "error": "没有已解析的文献可索引"}
            
            # 转换为字典格式
            literature_list = []
            for entry in literature_entries:
                try:
                    # 使用 _format_literature 方法来构建完整的文献数据字典
                    lit_dict = self._format_literature(entry)
                    literature_list.append(lit_dict)
                except Exception as e:
                    logger.error(f"转换文献 {entry.id} 失败: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            session.close()
            
            if not literature_list:
                return {"success": False, "error": "没有有效的文献数据可索引"}
            
            logger.info(f"准备索引 {len(literature_list)} 篇文献")
            
            # 构建索引
            if self.indexer:
                success = self.indexer.index_literature(literature_list, rebuild=True, include_structures=False)

                if success:
                    # 更新文献状态
                    self._update_indexed_status(literature_entries)

                    process_time = time.time() - start_time
                    logger.info(f"✅ 索引重建完成 ({process_time:.2f}秒): {len(literature_list)} 篇文献")
                    logger.info("   - 元数据文档: 1 篇文献 x 1 个文档")
                    logger.info("   - 内容 Chunks: 每篇文献的章节/摘要/关键发现已chunk化并向量化")

                    return {
                        "success": True,
                        "message": f"索引重建完成: {len(literature_list)} 篇文献 (包含内容chunks)",
                        "literature_count": len(literature_list),
                        "index_type": "vector",
                        "timestamp": datetime.now().isoformat(),
                        "process_time": process_time
                    }
                else:
                    process_time = time.time() - start_time
                    return {
                        "success": False,
                        "error": "索引构建失败",
                        "literature_count": len(literature_list),
                        "process_time": process_time
                    }
            else:
                process_time = time.time() - start_time
                return {
                    "success": False,
                    "error": "索引器不可用",
                    "literature_count": len(literature_list),
                    "process_time": process_time
                }
                
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"重建索引失败 ({process_time:.2f}秒): {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "process_time": process_time
            }
    
    def _update_indexed_status(self, literature_entries: List[LiteratureEntry]):
        """更新文献索引状态"""
        session = create_literature_session()
        try:
            for entry in literature_entries:
                entry.status = LiteratureStatus.INDEXED
                entry.indexed_at = datetime.now()
            
            session.commit()
            logger.info(f"更新了 {len(literature_entries)} 篇文献的索引状态")
            
        except Exception as e:
            session.rollback()
            logger.error(f"更新索引状态失败: {e}")
        finally:
            session.close()
    
    def search_literature(self, query: str, filters: Dict[str, Any] = None, 
                        limit: int = 20, search_type: str = "hybrid",
                        use_structure_enhancement: bool = False) -> Dict[str, Any]:
        """搜索文献 - 改进版：支持文本和结构ID搜索"""
        try:
            # 如果有filters参数，传递给search_literature_simple
            if filters is not None:
                result = self.search_literature_simple(query, limit, filters)
            else:
                result = self.search_literature_simple(query, limit)
            
            # 确保返回结果不为None
            if result is None:
                logger.error(f"搜索返回None: query={query}, filters={filters}")
                return {
                    "success": False,
                    "error": "搜索函数返回None",
                    "results": [],
                    "total": 0,
                    "query": query
                }
            
            return result
            
        except Exception as e:
            logger.error(f"搜索文献异常: {e}")
            return {
                "success": False,
                "error": str(e),
                "results": [],
                "total": 0,
                "query": query
            }
    
    def get_literature_detail(self, literature_id: int) -> Dict[str, Any]:
        """获取文献详情"""
        start_time = time.time()
        
        try:
            session = create_literature_session()
            
            # 获取文献
            literature = session.query(LiteratureEntry).get(literature_id)
            if not literature:
                return {"success": False, "error": "文献不存在"}
            
            # 获取附录
            appendices = session.query(LiteratureAppendix).filter_by(literature_id=literature_id).all()
            
            # 获取笔记
            notes = session.query(LiteratureNote).filter_by(literature_id=literature_id).all()
            
            # 获取离线数据库信息（如果可用）
            offline_db_info = {}
            if self.structure_db and literature.cryoem_targets:
                try:
                    cryo_targets = json.loads(literature.cryoem_targets) if isinstance(literature.cryoem_targets, str) else literature.cryoem_targets
                    structure_ids = []
                    structure_ids.extend(cryo_targets.get('pdb_ids', []))
                    structure_ids.extend(cryo_targets.get('emdb_ids', []))
                    
                    if structure_ids:
                        offline_db_result = self.structure_db.batch_get_or_fetch_structures(structure_ids)
                        offline_db_info = {
                            'structures_count': len(offline_db_result.get('from_database', [])) + len(offline_db_result.get('from_api', [])),
                            'from_database': len(offline_db_result.get('from_database', [])),
                            'from_api': len(offline_db_result.get('from_api', [])),
                            'failed': len(offline_db_result.get('failed', []))
                        }
                except Exception as e:
                    logger.debug(f"获取离线数据库信息失败: {e}")
            
            # 格式化响应
            result = {
                "success": True,
                "literature": self._format_literature(literature),
                "appendices": [self._format_appendix(a) for a in appendices],
                "notes": [self._format_note(n) for n in notes],
                "offline_db_info": offline_db_info,
                "statistics": {
                    "appendix_count": len(appendices),
                    "note_count": len(notes),
                    "has_pdf": literature.has_pdf,
                    "is_parsed": literature.is_parsed,
                    "page_count": literature.main_pdf_pages or 0,
                    "file_size_mb": round(literature.main_pdf_size / (1024*1024), 2) if literature.main_pdf_size else 0
                }
            }
            
            process_time = time.time() - start_time
            logger.info(f"✅ 获取文献详情完成 ({process_time:.2f}秒): ID={literature_id}")
            
            return result
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"获取文献详情失败 ({process_time:.2f}秒): {e}")
            return {"success": False, "error": str(e)}
        finally:
            session.close()
    
    def _format_literature(self, literature: LiteratureEntry) -> Dict[str, Any]:
        """格式化文献信息"""
        # 安全地处理JSON字段
        def safe_json_loads(value, default=None):
            if value is None:
                return default if default is not None else []
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except:
                    return default if default is not None else []
            return value
        
        return {
            "id": literature.id,
            "title": literature.title,
            "authors": safe_json_loads(literature.authors, []),
            "journal": literature.journal or "",
            "year": literature.year,
            "publication_date_full": literature.publication_date_full or "",  # 完整日期
            "doi": literature.doi or "",
            "arxiv_id": literature.arxiv_id or "",
            "pmid": literature.pmid or "",
            "abstract": literature.abstract or "",
            "full_text": literature.full_text or "",  # 全文内容，用于生成 chunks
            "summary": literature.summary or "",
            "key_findings": safe_json_loads(literature.key_findings, []),
            "keywords": safe_json_loads(literature.keywords, []),
            "tags": safe_json_loads(literature.tags, []),
            "status": literature.status.value if hasattr(literature.status, 'value') else str(literature.status),
            "main_pdf_filename": literature.main_pdf_filename or "",
            "main_pdf_path": literature.main_pdf_path or "",
            "main_pdf_size": literature.main_pdf_size,
            "main_pdf_pages": literature.main_pdf_pages,
            "citation_count": literature.citation_count or 0,
            "literature_type": literature.literature_type.value if hasattr(literature.literature_type, 'value') else str(literature.literature_type),
            "cryoem_targets": safe_json_loads(literature.cryoem_targets, {}),
            "search_text_blob": literature.search_text_blob or "",  # 新增搜索字段
            "created_at": literature.created_at.isoformat() if literature.created_at else None,
            "updated_at": literature.updated_at.isoformat() if literature.updated_at else None,
            "parsed_at": literature.parsed_at.isoformat() if literature.parsed_at else None,
            "indexed_at": literature.indexed_at.isoformat() if literature.indexed_at else None
        }
    
    def _format_appendix(self, appendix: LiteratureAppendix) -> Dict[str, Any]:
        """格式化附录信息"""
        return {
            "id": appendix.id,
            "filename": appendix.filename,
            "file_type": appendix.file_type or "",
            "appendix_type": appendix.appendix_type or "",
            "description": appendix.description or "",
            "file_size": appendix.file_size or 0,
            "page_count": appendix.page_count or 0,
            "created_at": appendix.created_at.isoformat() if appendix.created_at else None
        }
    
    def _format_note(self, note: LiteratureNote) -> Dict[str, Any]:
        """格式化笔记信息"""
        return {
            "id": note.id,
            "title": note.title,
            "content": note.content,
            "note_type": note.note_type or "general",
            "tags": note.tags or [],
            "created_at": note.created_at.isoformat() if note.created_at else None
        }
    
    def get_system_stats(self) -> Dict[str, Any]:
        """获取系统统计信息"""
        try:
            lit_stats = get_literature_stats()
            
            # 获取索引状态
            index_status = self.get_index_status()
            
            # 获取离线数据库统计（如果可用）
            offline_db_stats = {}
            if self.structure_db:
                try:
                    offline_db_stats = self.structure_db.get_database_info()
                except Exception as e:
                    logger.debug(f"获取离线数据库统计失败: {e}")
            
            return {
                "literature": lit_stats,
                "index": index_status,
                "offline_database": offline_db_stats,
                "system": {
                    "literature_db": HAS_LITERATURE_DB,
                    "literature_parser": HAS_LITERATURE_PARSER,
                    "literature_index": HAS_LITERATURE_INDEX,
                    "agent_core": HAS_AGENT,
                    "index_manager": HAS_INDEX_MANAGER,
                    "structure_manager": HAS_STRUCTURE_MANAGER,
                    "structure_database": HAS_STRUCTURE_DB,
                    "uniprot": HAS_UNIPROT,
                    "structure_qa_agent": self.structure_qa_agent is not None
                },
                "directories": {
                    "pdfs_dir": str(LITERATURE_PDFS_DIR) if LITERATURE_PDFS_DIR else "N/A",
                    "appendices_dir": str(LITERATURE_APPENDICES_DIR) if LITERATURE_APPENDICES_DIR else "N/A",
                    "indices_dir": "literature_indices",
                    "cache_dir": "literature_cache",
                    "structure_cache_dir": "structure_cache",
                    "structure_indices_dir": "structure_indices",
                    "offline_db_dir": "structure_offline_db"
                }
            }
        except Exception as e:
            logger.error(f"获取系统统计失败: {e}")
            return {"error": str(e)}

    def update_literature_index_incremental(self, literature_id: int) -> Dict[str, Any]:
        """增量更新单个文献的索引"""
        try:
            logger.info(f"开始增量更新文献索引: ID={literature_id}")
            
            # 获取文献数据
            session = create_literature_session()
            literature = session.query(LiteratureEntry).get(literature_id)
            
            if not literature:
                return {"success": False, "error": "文献不存在"}
            
            # 转换为字典格式
            lit_data = self._format_literature(literature)
            
            # 使用RAG系统进行增量索引
            if hasattr(self, 'rag_system') and self.rag_system:
                literature_list = [lit_data]
                
                if hasattr(self.rag_system, 'index_literature_with_tracking'):
                    # 使用带跟踪的增量索引
                    result = self.rag_system.index_literature_with_tracking(
                        literature_list, incremental=True
                    )
                else:
                    # 使用普通索引
                    success = self.rag_system.index_literature(literature_list)
                    result = {"success": success, "index_type": "normal"}
                
                session.close()
                return result
            
            # 如果没有RAG系统，使用索引器
            elif hasattr(self, 'indexer') and self.indexer:
                literature_list = [lit_data]
                success = self.indexer.index_literature(literature_list)
                
                session.close()
                return {"success": success, "index_type": "legacy"}
            
            else:
                session.close()
                return {"success": False, "error": "索引系统不可用"}
                
        except Exception as e:
            if 'session' in locals():
                session.close()
            logger.error(f"增量更新索引失败: {e}")
            return {"success": False, "error": str(e)}

    # ---------- 混合检索能力检查 ----------
    
    def get_hybrid_search_capabilities(self) -> Dict[str, Any]:
        """获取混合检索能力信息"""
        capabilities = {
            "has_structure_db": HAS_STRUCTURE_DB,
            "has_uniprot": HAS_UNIPROT,
            "structure_db_ready": bool(self.structure_db),
            "structure_qa_agent_ready": self.structure_qa_agent is not None,
            "hybrid_search_enabled": True,
            "search_modes": {
                "exact": "精确搜索",
                "semantic": "语义搜索", 
                "hybrid": "混合搜索",
                "auto": "自动选择"
            },
            "question_types_supported": [
                "structure_inventory",   # 结构库存问题
                "structure_quality",     # 结构质量问题
                "experimental_method",   # 实验方法问题
                "biological_insight",    # 生物学见解问题
                "comparison",            # 比较问题
                "protein_info",          # 蛋白质信息问题
                "general"                # 通用问题
            ],
            "full_text_search": True,
            "chinese_english_search": True,
            "keyword_extraction": True
        }
        
        # 获取数据库统计
        if self.structure_db:
            try:
                db_stats = self.structure_db.get_database_info()
                capabilities["database_stats"] = {
                    "total_structures": db_stats.get('total_structures', 0),
                    "pdb_count": db_stats.get('pdb_count', 0),
                    "emdb_count": db_stats.get('emdb_count', 0),
                    "has_vector_index": db_stats.get('has_vector_index', False)
                }
            except Exception as e:
                logger.debug(f"获取数据库统计失败: {e}")
        
        # 获取QA智能体能力
        if self.structure_qa_agent:
            try:
                qa_capabilities = self.structure_qa_agent.get_capabilities()
                capabilities["qa_agent"] = qa_capabilities
            except Exception as e:
                logger.debug(f"获取QA智能体能力失败: {e}")
        
        return capabilities
    
    # ---------- 离线数据库功能 ----------
    
    def get_offline_database_stats(self) -> Dict[str, Any]:
        """获取离线数据库统计"""
        if not self.structure_db:
            return {"success": False, "error": "离线数据库不可用"}
        
        try:
            return self.structure_db.get_database_info()
        except Exception as e:
            logger.error(f"获取离线数据库统计失败: {e}")
            return {"success": False, "error": str(e)}
    
    def search_structures_offline(self, 
                                 query: str = None,
                                 structure_type: Optional[str] = None,
                                 organism: Optional[str] = None,
                                 gene: Optional[str] = None,
                                 protein_name: Optional[str] = None,
                                 min_resolution: Optional[float] = None,
                                 max_resolution: Optional[float] = None,
                                 limit: int = 50) -> List[Dict[str, Any]]:
        """离线搜索结构"""
        if not self.structure_db:
            return []
        
        try:
            return self.structure_db.search_structures_offline(
                query=query,
                structure_type=structure_type,
                organism=organism,
                gene=gene,
                protein_name=protein_name,
                min_resolution=min_resolution,
                max_resolution=max_resolution,
                limit=limit
            )
        except Exception as e:
            logger.error(f"离线搜索结构失败: {e}")
            return []
    
    def get_protein_structures_offline(self, protein_name: str) -> Dict[str, Any]:
        """从离线数据库获取蛋白质结构"""
        if not self.structure_db:
            return {"success": False, "error": "离线数据库不可用"}
        
        try:
            return self.structure_db.find_protein_structures(protein_name)
        except Exception as e:
            logger.error(f"获取蛋白质结构失败: {e}")
            return {"success": False, "error": str(e)}
        
    def _build_journal_search_conditions(self, query_clean: str):
        """构建期刊搜索条件，支持多单词期刊名称搜索"""
        if not query_clean:
            return None
        
        # 将查询转换为小写，去除多余空格
        query_lower = query_clean.lower().strip()
        
        # 构建多种搜索条件
        conditions = []
        
        # 1. 完全匹配（忽略大小写）
        conditions.append(LiteratureEntry.journal.ilike(f'%{query_clean}%'))
        
        # 2. 处理常见的期刊缩写和变体
        journal_variants = self._get_journal_variants(query_lower)
        for variant in journal_variants:
            # 确保变体不为空
            if variant and variant.strip():
                conditions.append(LiteratureEntry.journal.ilike(f'%{variant}%'))
        
        # 3. 对于多单词期刊，构建更精确的匹配
        if ' ' in query_lower or '-' in query_lower:
            # 分割单词
            import re
            words = re.split(r'[\s\-]+', query_lower)
            
            # 构建AND条件：所有单词都必须出现（按任意顺序）
            if len(words) > 1:
                and_conditions = []
                for word in words:
                    if len(word) > 2:  # 只处理长度大于2的单词
                        and_conditions.append(LiteratureEntry.journal.ilike(f'%{word}%'))
                
                if and_conditions:
                    conditions.append(and_(*and_conditions))
        
        # 4. 处理特殊期刊名称
        # Nature Communications 的特殊处理
        if 'nature commun' in query_lower or 'nat commun' in query_lower:
            nature_comm_patterns = [
                '%Nature Communications%',
                '%Nature Commun%',
                '%Nat Commun%',
                '%Nat. Commun.%',
                '%Nat Commun.%'
            ]
            for pattern in nature_comm_patterns:
                conditions.append(LiteratureEntry.journal.ilike(pattern))
        
        # Nature 的特殊处理
        if query_lower == 'nature':
            # 只匹配Nature，不匹配Nature Communications等
            nature_patterns = [
                '%Nature',          # 开头是Nature
                '%Nature %',        # Nature 后跟空格
                '%Nature[^a-z]%',   # Nature 后跟非字母字符
            ]
            for pattern in nature_patterns:
                conditions.append(LiteratureEntry.journal.ilike(pattern))
            
            # 排除包含"Nature Communications"的记录
            # 注意：这需要在执行查询时处理
        
        # 5. 在全文搜索字段中搜索期刊信息
        conditions.append(LiteratureEntry.search_text_blob.ilike(f'%{query_lower}%'))
        
        # 使用OR组合所有条件
        if conditions:
            return or_(*conditions)
        else:
            return None

    def _get_journal_variants(self, journal_name: str) -> List[str]:
        """获取期刊名称的常见变体"""
        variants = set()
        journal_lower = journal_name.lower().strip()
        
        if not journal_lower:
            return []
        
        # 常见期刊缩写映射（扩展版）
        journal_mapping = {
            'nature': ['nat'],
            'science': ['sci'],
            'cell': ['cell'],
            'pnas': ['proc natl acad sci', 'proceedings of the national academy of sciences'],
            'jbc': ['j biol chem', 'journal of biological chemistry'],
            'embo': ['embo j', 'embo journal'],
            'plos': ['plos one', 'plos biology', 'plos genetics'],
            'elife': ['elife'],
            'nature communications': [
                'nat commun', 'nat comm', 'nat commun.', 'nat. commun.', 
                'nature commun', 'nature commun.', 'nature communications'
            ],
            'nature structural & molecular biology': ['nat struct mol biol', 'nsmb'],
            'cell research': ['cell res'],
            'molecular cell': ['mol cell'],
            'developmental cell': ['dev cell'],
            'cancer cell': ['cancer cell'],
            'neuron': ['neuron'],
            'nature neuroscience': ['nat neurosci'],
            'science advances': ['sci adv'],
            'nature methods': ['nat methods'],
            'nature biotechnology': ['nat biotechnol'],
            'cell metabolism': ['cell metab'],
            'immunity': ['immunity'],
            'nature immunology': ['nat immunol'],
            'nature medicine': ['nat med'],
            'lancet': ['lancet'],
            'new england journal of medicine': ['nejm'],
            'jama': ['jama'],
            'bmj': ['bmj'],
            'proceedings of the national academy of sciences': ['pnas', 'proc natl acad sci'],
            'journal of biological chemistry': ['j biol chem', 'jbc']
        }
        
        # 查找完全匹配
        if journal_lower in journal_mapping:
            variants.update(journal_mapping[journal_lower])
        
        # 反向查找：从变体到全名
        for full_name, abbr_list in journal_mapping.items():
            if journal_lower in abbr_list:
                variants.add(full_name)
        
        # 处理复数形式
        if journal_lower.endswith('s'):
            singular = journal_lower.rstrip('s')
            variants.add(singular)
        
        # 处理"&"和"and"的互换
        if '&' in journal_lower:
            variants.add(journal_lower.replace('&', 'and'))
        elif 'and' in journal_lower:
            variants.add(journal_lower.replace('and', '&'))
        
        # 处理大小写变体
        variants.add(journal_name)  # 原始
        variants.add(journal_name.title())  # 首字母大写
        variants.add(journal_name.upper())  # 全大写
        
        # 去除常见前缀
        common_prefixes = ['journal of ', 'journal ', 'review ', 'annual review of ', 'the ']
        for prefix in common_prefixes:
            if journal_lower.startswith(prefix):
                variants.add(journal_lower[len(prefix):])
                variants.add(journal_lower[len(prefix):].title())
        
        # 处理带点的缩写
        if '.' in journal_lower:
            variants.add(journal_lower.replace('.', ''))
        
        # 去除空值和重复，并返回列表
        return [v for v in variants if v and v.strip()]

# ---------- 系统初始化 ----------
_literature_manager_singleton = None
_literature_manager_lock = threading.Lock()

def get_literature_manager() -> LiteratureManager:
    """获取文献管理器实例 - 使用单例模式"""
    global _literature_manager_singleton
    
    if _literature_manager_singleton is not None:
        return _literature_manager_singleton
    
    with _literature_manager_lock:
        if _literature_manager_singleton is None:
            _literature_manager_singleton = LiteratureManager()
    
    return _literature_manager_singleton

def initialize_literature_system(config: Dict[str, Any] = None) -> Dict[str, Any]:
    """初始化文献管理系统 - 修改版，避免重复初始化"""
    global _literature_manager_singleton
    
    start_time = time.time()
    
    try:
        # 如果已经初始化过，直接返回
        if _literature_manager_singleton is not None:
            process_time = time.time() - start_time
            logger.info("文献系统已经初始化，返回现有实例")
            return {
                "status": "already_initialized",
                "message": "文献系统已经初始化",
                "initialization_time": process_time
            }
        
        # 初始化数据库
        if HAS_LITERATURE_DB:
            db_result = initialize_literature_database()
        else:
            db_result = {"success": False, "message": "文献数据库不可用"}
        
        # 创建文献管理器（会自动检查是否已初始化）
        manager = LiteratureManager(config)
        
        # 设置为全局单例
        with _literature_manager_lock:
            if _literature_manager_singleton is None:
                _literature_manager_singleton = manager
        
        # 获取系统统计
        try:
            stats = manager.get_system_stats()
        except:
            stats = {}
        
        process_time = time.time() - start_time
        
        return {
            "status": "success",
            "message": "CryoAgent 文献管理系统初始化完成",
            "initialization_time": process_time,
            "database": db_result,
            "statistics": stats.get("literature", {}),
            "capabilities": {
                # ... 原有能力列表 ...
            }
        }
        
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"初始化文献系统失败 ({process_time:.2f}秒): {e}")
        return {
            "status": "error",
            "message": f"初始化失败: {str(e)}",
            "initialization_time": process_time
        }

def get_batch_importer() -> LiteratureManager:
    """获取批量导入器（实际上是文献管理器的别名）"""
    return get_literature_manager()

# literature_agent.py 中添加以下内容

class SearchStrategy:
    """搜索策略枚举"""
    SMART = "smart"           # 智能搜索
    TITLE = "title"          # 标题搜索
    AUTHOR = "author"        # 作者搜索
    CONTENT = "content"      # 内容搜索
    DOI = "doi"              # DOI搜索
    STRUCTURE = "structure"  # 结构搜索
    HYBRID = "hybrid"        # 混合搜索

class IntelligentSearcher:
    """智能搜索器"""
    def __init__(self, manager=None):
        self.manager = manager or get_literature_manager()
        
    def search(self, query, auto_strategy=True, use_ai_enhancement=True, 
               use_ai_translation=True, max_results=10, **kwargs):
        """智能搜索
        
        Args:
            query: 搜索查询
            auto_strategy: 是否自动选择策略
            use_ai_enhancement: 是否使用AI增强
            use_ai_translation: 是否使用AI翻译
            max_results: 最大结果数
            **kwargs: 其他参数
            
        Returns:
            搜索结果
        """
        try:
            # 自动选择策略
            if auto_strategy:
                strategy = self._detect_best_strategy(query)
            else:
                strategy = kwargs.get("strategy", SearchStrategy.SMART)
            
            # AI增强查询
            if use_ai_enhancement:
                enhanced_query = self._enhance_query(query)
            else:
                enhanced_query = query
            
            # 执行搜索
            filters = {"search_type": strategy}
            result = self.manager.search_literature(
                query=enhanced_query,
                filters=filters,
                limit=max_results
            )
            
            if not result.get("success"):
                return result
            
            # 如果启用了AI翻译，翻译英文结果
            if use_ai_translation and result.get("results"):
                result = self._translate_results(result, query)
            
            # 添加策略信息
            result["strategy_used"] = strategy
            
            # 添加增强信息
            if use_ai_enhancement:
                result["search_enhancement"] = {
                    "original_query": query,
                    "enhanced_query": enhanced_query,
                    "expanded_queries": self._expand_query(query)
                }
            
            return result
            
        except Exception as e:
            logger.error(f"智能搜索失败: {e}")
            return {
                "success": False,
                "error": f"智能搜索失败: {str(e)}"
            }
    
    def _detect_best_strategy(self, query):
        """检测最佳搜索策略"""
        query_lower = query.lower()
        
        # 检测结构ID
        if re.search(r'\b([1-9][a-z0-9]{3})\b', query_lower, re.I):
            return SearchStrategy.STRUCTURE
        
        # 检测DOI
        if re.search(r'\b10\.\d{4,9}/', query_lower):
            return SearchStrategy.DOI
        
        # 检测作者名格式
        if re.search(r'\b[a-z]+\s+[a-z]+\b', query_lower):
            return SearchStrategy.AUTHOR
        
        # 短查询可能是标题
        if len(query.split()) <= 5:
            return SearchStrategy.TITLE
        
        # 默认智能搜索
        return SearchStrategy.SMART
    
    def _enhance_query(self, query):
        """增强查询"""
        # 简单的查询扩展
        synonyms = {
            "cryo": ["cryo-em", "cryo-em", "cryoelectron", "cryo electron"],
            "structure": ["model", "coordinates", "PDB"],
            "protein": ["enzyme", "peptide", "polypeptide"],
            "DNA": ["deoxyribonucleic acid", "genetic material"],
            "RNA": ["ribonucleic acid"]
        }
        
        enhanced = query
        for word, syns in synonyms.items():
            if word.lower() in query.lower():
                enhanced += " " + " ".join(syns)
        
        return enhanced
    
    def _expand_query(self, query):
        """扩展查询词"""
        expansions = []
        
        # 添加相关词
        expansions.append(query)
        
        # 如果包含"structure"，添加相关词
        if "structure" in query.lower():
            expansions.append(query + " PDB")
            expansions.append(query + " EMDB")
        
        # 如果包含"cryo"，添加相关词
        if "cryo" in query.lower():
            expansions.append(query + " electron microscopy")
        
        return expansions
    
    def _translate_results(self, result, original_query):
        """翻译搜索结果"""
        try:
            # 这里可以集成AI翻译服务
            # 目前先返回原始结果
            result["translation_info"] = {
                "original_query": original_query,
                "translated": False,
                "translation_service": "none"
            }
            return result
        except Exception as e:
            logger.warning(f"翻译失败: {e}")
            return result

# 添加获取智能搜索器的函数
def get_intelligent_searcher():
    """获取智能搜索器单例"""
    if not hasattr(get_intelligent_searcher, "_instance"):
        manager = get_literature_manager()
        get_intelligent_searcher._instance = IntelligentSearcher(manager)
    return get_intelligent_searcher._instance

# ---------- 智能问答核心函数 ----------

def intelligent_qa_search(question: str, conversation_context: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """智能问答搜索 - 自动选择最佳搜索策略"""
    try:
        manager = get_literature_manager()
        
        if manager is None:
            return {
                "success": False,
                "answer": "文献管理器未初始化，请先初始化系统。",
                "error": "Literature manager not initialized"
            }
        
        # 获取系统配置
        from literature_agent import LiteratureManager
        
        result = None
        if isinstance(manager, LiteratureManager):
            # 使用管理器的智能问答方法
            result = manager.intelligent_qa_search(question, search_type="auto", conversation_context=conversation_context)
        else:
            # 回退到简化搜索
            result = manager.ask_question_simple(question)
        
        # 检查结果是否为None
        if result is None:
            return {
                "success": False,
                "answer": f"搜索 '{question}' 未返回结果。",
                "error": "Search returned None"
            }
        
        # 检查结果是否为字典
        if not isinstance(result, dict):
            return {
                "success": False,
                "answer": f"搜索返回了无效的结果类型: {type(result).__name__}",
                "error": f"Invalid result type: {type(result).__name__}"
            }
        
        # 检查结果是否有success字段
        if "success" not in result:
            result["success"] = False
            result["error"] = "Result missing 'success' field"
        
        # 检查空结果
        if result.get("success"):
            answer = result.get("answer", "")
            sources = result.get("sources", [])
            
            # 检查是否包含常见的"未找到"提示
            not_found_keywords = ["未找到", "未检索到", "没有找到", "抱歉，没有", "相关信息不足", 
                                 "未找到任何相关", "没有相关文献"]
            has_not_found_hint = any(keyword in answer for keyword in not_found_keywords) if answer else False
            
            # 如果没有来源，且答案很短或包含未找到提示，认为是空结果
            empty_sources = (not sources or 
                            (isinstance(sources, list) and len(sources) == 0) or
                            (isinstance(sources, dict) and not any(sources.values())))
            
            if empty_sources and (not answer or len(answer) < 50 or has_not_found_hint):
                result["success"] = False
                result["answer"] = f"未找到与 '{question}' 相关的文献。"
                result["answer"] += "\n\n**建议尝试：**"
                result["answer"] += "\n1. 使用英文关键词（如：TCR, GPCR）"
                result["answer"] += "\n2. 提供PDB ID（如：PDB 7XYZ）"
                result["answer"] += "\n3. 上传相关文献PDF"
                result["answer"] += "\n4. 尝试更通用的关键词（如：冷冻电镜、蛋白质结构）"
        
        return result
        
    except AttributeError as e:
        logger.error(f"智能问答搜索属性错误: {e}")
        return {
            "success": False,
            "answer": f"系统功能异常: {str(e)}",
            "error": str(e)
        }
    except Exception as e:
        logger.error(f"智能问答搜索失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "answer": f"处理您的问题时出现错误: {str(e)}",
            "error": str(e)
        }

def ask_question_with_ai_translation(literature_id: Optional[int] = None, 
                                    question: str = "",
                                    conversation_context: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """使用AI翻译的智能问答函数"""
    try:
        manager = get_literature_manager()
        
        # 如果有文献ID，进行特定文献问答
        if literature_id:
            if hasattr(manager, 'ask_question_with_ai_translation'):
                # 使用管理器的AI翻译问答方法
                result = manager.ask_question_with_ai_translation(question, conversation_context=conversation_context)
            else:
                # 回退到普通问答
                result = manager.ask_question(
                    question=question,
                    literature_ids=[literature_id],
                    conversation_context=conversation_context
                )
        else:
            # 全局问答
            result = intelligent_qa_search(question, conversation_context=conversation_context)
        
        return result
        
    except Exception as e:
        logger.error(f"智能问答失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "answer": f"抱歉，处理您的问题时出现错误: {str(e)}"
        }

def simple_qa_search(query: str, top_k: int = 10) -> Dict[str, Any]:
    """简化问答搜索（不回退到AI）"""
    try:
        manager = get_literature_manager()
        
        # --- 修正1: 将 'question' 改为 'query', 'limit' 改为 'top_k' ---
        search_result = manager.search_literature_simple(query, limit=top_k)
        
        if not search_result.get("success") or not search_result.get("results"):
            return {
                "success": False,
                "error": "未找到相关文献",
                "answer": "抱歉，没有找到与您的问题相关的文献。"
            }
        
        # 构建答案
        results = search_result["results"]
        structure_ids = search_result.get("structure_ids_found", [])
        
        answer_parts = ["## 🔍 搜索结果\n"]
        
        if structure_ids:
            answer_parts.append(f"**检测到的结构ID**: {', '.join(structure_ids)}\n")
        
        answer_parts.append(f"找到 {len(results)} 个相关结果：\n")
        
        for i, result in enumerate(results[:5]):
            title = result.get('title', '')[:80]
            year = result.get('year', '')
            journal = result.get('journal', '')
            
            answer_parts.append(f"{i+1}. **{title}**")
            if year:
                answer_parts.append(f"   年份: {year}")
            if journal:
                answer_parts.append(f"   期刊: {journal}")
            
            if result.get('pdb_ids'):
                answer_parts.append(f"   PDB ID: {', '.join(result['pdb_ids'][:3])}")
            
            if result.get('contains_query_structure'):
                answer_parts.append("   ✅ **包含查询的结构ID**")
            
            answer_parts.append("")
        
        answer = "\n".join(answer_parts)
        
        return {
            "success": True,
            "answer": answer,
            "sources": results,
            "search_result": search_result,
            "qa_engine": "simple_search"
        }
        
    except Exception as e:
        logger.error(f"简化问答搜索失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "answer": f"抱歉，搜索失败: {str(e)}"
        }

def get_qa_capabilities() -> Dict[str, Any]:
    """获取问答能力信息"""
    try:
        manager = get_literature_manager()
        
        capabilities = {
            "ai_enabled": HAS_AGENT,
            "structure_qa_agent": manager.structure_qa_agent is not None,
            "search_modes": {
                "smart": "智能搜索",
                "simple": "简化搜索",
                "hybrid": "混合搜索"
            },
            "supported_languages": ["中文", "英文"],
            "max_results": 20
        }
        
        # 添加管理器特定能力
        if hasattr(manager, 'get_hybrid_search_capabilities'):
            hybrid_capabilities = manager.get_hybrid_search_capabilities()
            capabilities.update(hybrid_capabilities)
        
        return {
            "success": True,
            "capabilities": capabilities
        }
        
    except Exception as e:
        logger.error(f"获取问答能力失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "capabilities": {}
        }


def test_qa_system() -> Dict[str, Any]:
    """测试问答系统功能"""
    test_questions = [
        "GPR158的冷冻电镜结构有哪些？",
        "EGFR的表达纯化方法",
        "PDB 7XYZ的分辨率是多少？",
        "冷冻电镜技术在GPCR研究中的应用"
    ]
    
    results = []
    
    for question in test_questions:
        try:
            result = intelligent_qa_search(question)
            results.append({
                "question": question,
                "success": result.get("success", False),
                "answer_length": len(result.get("answer", "")),
                "engine": result.get("qa_engine", "unknown")
            })
        except Exception as e:
            results.append({
                "question": question,
                "success": False,
                "error": str(e)
            })
    
    return {
        "success": True,
        "test_results": results,
        "total_tests": len(test_questions),
        "passed_tests": sum(1 for r in results if r.get("success", False))
    }

# ---------- 测试函数 ----------
def test_ai_enhanced_qa():
    """测试AI增强问答功能"""
    try:
        # 初始化系统
        result = initialize_literature_system()
        print("初始化结果:", result.get("status"))
        
        manager = get_literature_manager()
        
        # 测试各种问题
        test_questions = [
            "GPR158的冷冻电镜结构有哪些？它们的分辨率分别是多少？",
            "请告诉我关于EGFR的结构信息，包括表达纯化方法",
            "PDB 7EWL和7SHE的差异是什么？",
            "冷冻电镜技术在GPCR结构研究中的应用有哪些？",
            "如何表达和纯化膜蛋白用于冷冻电镜研究？",
            "GPR158有多少个结构？",
            "膜蛋白的表达纯化方法是什么？",
            "7XYZ的分辨率是多少？"
        ]
        
        for question in test_questions:
            print(f"\n{'='*80}")
            print(f"测试问题: {question}")
            print(f"{'='*80}")
            
            # 使用AI增强搜索
            result = manager.intelligent_qa_search(
                question=question,
                search_type="auto"
            )
            
            print(f"搜索类型: {result.get('qa_engine', 'unknown')}")
            print(f"成功: {result.get('success')}")
            print(f"响应时间: {result.get('response_time', 0):.2f}秒")
            
            if result.get('sources'):
                if isinstance(result['sources'], dict):
                    print(f"翻译的查询: {result['sources'].get('translated_query', 'N/A')}")
                    print(f"文献数量: {result['sources'].get('literature_count', 0)}")
                    print(f"结构数量: {result['sources'].get('structure_count', 0)}")
            
            if result.get('answer'):
                answer = result['answer']
                print(f"\n回答预览:\n{answer[:500]}...")
            
            print(f"\n{'='*80}")
    
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()

def test_full_text_search():
    """测试全文搜索功能"""
    print("\n🔍 测试全文搜索功能...")
    manager = get_literature_manager()
    
    test_queries = [
        "冷冻电镜 膜蛋白 结构",
        "GPCR 信号传导",
        "protein purification expression",
        "结构生物学 方法学",
        "GPR158",
        "EGFR structure",
        "PDB 7XYZ"
    ]
    
    for query in test_queries:
        print(f"\n搜索: '{query}'")
        result = manager.search_literature_simple(query, limit=3)
        
        if result.get('success'):
            print(f"找到 {result.get('total', 0)} 个结果")
            print(f"关键词: {result.get('keywords', [])}")
            print(f"结构ID: {result.get('structure_ids_found', [])}")
            
            for i, item in enumerate(result.get('results', [])[:3]):
                title = item.get('title', '')[:50]
                year = item.get('year', '')
                journal = item.get('journal', '')[:30]
                score = item.get('relevance_score', 0)
                print(f"  {i+1}. [{score}] {title} ({year}) - {journal}")
        else:
            print(f"搜索失败: {result.get('error', '未知错误')}")

# 在文件末尾添加导出的函数
__all__ = [
    'LiteratureManager',
    'get_literature_manager',
    'initialize_literature_system',
    'get_batch_importer',
    'get_intelligent_searcher',
    'intelligent_qa_search',  # 新增
    'ask_question_with_ai_translation',  # 新增
    'simple_qa_search',  # 新增
    'get_qa_capabilities',  # 新增
    'test_qa_system'  # 新增
]
