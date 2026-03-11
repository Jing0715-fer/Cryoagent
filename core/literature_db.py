# literature_db.py - CryoAgent Pro 文献管理数据库模型（完整修复版）
import os, json, time, re, sqlite3, logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from enum import Enum

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, Float, ForeignKey, JSON, Enum as SQLEnum, func, text
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
try:
    from flask_login import UserMixin
    HAS_FLASK_LOGIN = True
except ImportError:
    HAS_FLASK_LOGIN = False
    # 定义一个简单的 UserMixin 回退
    class UserMixin:
        """Flask-Login 用户Mixin回退"""
        def get_id(self):
            return str(self.id)
        @property
        def is_active(self):
            return getattr(self, '_is_active', True)
        @property
        def is_authenticated(self):
            return True
        @property
        def is_anonymous(self):
            return False
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.ext.hybrid import hybrid_property

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------- 项目目录配置 ----------
# 数据目录 - 使用 flask_app/data/ 目录
BASE_DIR = Path(__file__).parent.parent.absolute()
DATA_DIR = BASE_DIR / "data"
LITERATURE_DIR = BASE_DIR / "literature"
LITERATURE_PDFS_DIR = LITERATURE_DIR / "pdfs"
LITERATURE_APPENDICES_DIR = LITERATURE_DIR / "appendices"
LITERATURE_THUMBNAILS_DIR = LITERATURE_DIR / "thumbnails"

# 确保所有目录存在
for dir_path in [LITERATURE_DIR, LITERATURE_PDFS_DIR, LITERATURE_APPENDICES_DIR, LITERATURE_THUMBNAILS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

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
    
    # 定义简化的回退函数
    def prepare_json_field(value: Any, field_name: str = None) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except:
                return value
        return value

# ---------- 枚举定义 ----------
class LiteratureStatus(Enum):
    """文献状态枚举"""
    UPLOADED = "uploaded"           # 已上传
    PARSING = "parsing"             # 解析中
    PARSED = "parsed"               # 已解析
    INDEXED = "indexed"             # 已索引
    ERROR = "error"                 # 错误

class LiteratureType(Enum):
    """文献类型枚举"""
    JOURNAL_ARTICLE = "journal_article"     # 期刊文章
    CONFERENCE_PAPER = "conference_paper"   # 会议论文
    BOOK_CHAPTER = "book_chapter"           # 书籍章节
    PREPRINT = "preprint"                   # 预印本
    THESIS = "thesis"                       # 学位论文
    TECHNICAL_REPORT = "technical_report"   # 技术报告
    OTHER = "other"                         # 其他

class CitationStyle(Enum):
    """引用格式枚举"""
    APA = "apa"
    MLA = "mla"
    CHICAGO = "chicago"
    HARVARD = "harvard"
    VANCOUVER = "vancouver"
    NATURE = "nature"
    SCIENCE = "science"
    IEEE = "ieee"

# ---------- 数据库模型定义 ----------
DB_PATH = DATA_DIR / "literature.db"
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# ---------- 用户认证模型 ----------
class User(UserMixin, Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)

    # 用户信息
    display_name = Column(String(100), nullable=True)
    avatar_url = Column(String(500), nullable=True)

    # 状态
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)

    # 时间戳
    created_at = Column(DateTime, default=datetime.now)
    last_login = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}')>"

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'display_name': self.display_name,
            'avatar_url': self.avatar_url,
            'is_active': self.is_active,
            'is_admin': self.is_admin,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }


class LiteratureEntry(Base):
    """文献主表"""
    __tablename__ = "literature_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 用户关联 (用于数据隔离)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True)

    # 基本标识信息
    doi = Column(String(255), nullable=True, unique=True, index=True)
    arxiv_id = Column(String(100), nullable=True, unique=True, index=True)
    pmid = Column(String(50), nullable=True, unique=True, index=True)
    pmcid = Column(String(50), nullable=True, unique=True, index=True)
    custom_id = Column(String(100), nullable=True, unique=True, index=True)
    
    # 文献元数据
    title = Column(String(500), nullable=False, index=True)
    authors = Column(JSON, default=list)  # 存储作者列表
    journal = Column(String(300), nullable=True, index=True)
    publisher = Column(String(200), nullable=True)
    publication_date = Column(String(50), nullable=True)
    year = Column(Integer, nullable=True, index=True)
    volume = Column(String(50), nullable=True)
    issue = Column(String(50), nullable=True)
    pages = Column(String(100), nullable=True)
    
    # 新增日期相关字段
    publication_date_full = Column(String(50), nullable=True)  # 完整日期 YYYY-MM-DD
    publication_year = Column(Integer, nullable=True)  # 年份
    publication_month = Column(Integer, nullable=True)  # 月份
    publication_day = Column(Integer, nullable=True)  # 日
    date_confidence = Column(Float, default=0.0)  # 日期置信度 0-1.0
    
    # 新增冷冻电镜相关字段
    cryoem_targets = Column(JSON, nullable=True)  # 冷冻电镜靶点信息
    
    # 文献分类
    literature_type = Column(SQLEnum(LiteratureType), default=LiteratureType.JOURNAL_ARTICLE)
    keywords = Column(JSON, default=list)  # 关键词列表
    disciplines = Column(JSON, default=list)  # 学科领域
    tags = Column(JSON, default=list)  # 用户标签
    
    # 文件信息
    main_pdf_filename = Column(String(500), nullable=True)
    main_pdf_path = Column(String(500), nullable=True)
    main_pdf_size = Column(Integer, nullable=True)  # 文件大小（字节）
    main_pdf_pages = Column(Integer, nullable=True)  # 页数
    
    # 解析内容
    abstract = Column(Text, nullable=True)
    full_text = Column(Text, nullable=True)  # 全文内容（可选存储）
    summary = Column(Text, nullable=True)  # AI生成的摘要
    key_findings = Column(JSON, nullable=True)  # 关键发现列表，改为JSON类型
    methods = Column(Text, nullable=True)  # 方法学描述
    results = Column(Text, nullable=True)  # 结果描述
    
    # 新增章节存储字段（RAG优化）
    introduction = Column(Text, nullable=True)           # 引言部分
    discussion = Column(Text, nullable=True)            # 讨论部分
    conclusions = Column(Text, nullable=True)           # 结论部分
    data_availability = Column(Text, nullable=True)     # 数据可用性部分
    
    # 完整的章节JSON存储（便于整体管理和更新）
    sections_json = Column(JSON, nullable=True)         # 所有章节的JSON格式 {"abstract": "...", "introduction": "..."}
    
    # ✅ 新增：统一全文搜索字段
    search_text_blob = Column(Text, nullable=True)
    
    # RAG优化字段
    has_vector_embeddings = Column(Boolean, default=False)  # 标记是否已生成向量嵌入
    embedding_model = Column(String(100), nullable=True)    # 使用的嵌入模型
    embedding_dimensions = Column(Integer, nullable=True)   # 嵌入维度
    last_embedded_at = Column(DateTime, nullable=True)      # 上次嵌入时间
    
    # 章节向量存储元数据
    section_embeddings = Column(JSON, nullable=True)        # 各章节的向量元数据 {"abstract": {"embedding_id": "x", "version": "1"}, ...}
    
    # 引用信息
    citation_count = Column(Integer, default=0)
    references = Column(JSON, default=list)  # 参考文献列表
    cited_by = Column(JSON, default=list)  # 被引用列表
    
    # 影响因子
    impact_factor = Column(Float, nullable=True)  # 期刊影响因子
    
    # 状态与元数据
    status = Column(SQLEnum(LiteratureStatus), default=LiteratureStatus.UPLOADED)
    parsing_method = Column(String(50), nullable=True)  # 解析方法：pdf_parse, ai_extract等
    confidence_score = Column(Float, default=0.0)  # 解析置信度
    
    # 关联信息
    related_structures = Column(JSON, default=list)  # 关联的结构ID列表
    related_scripts = Column(JSON, default=list)  # 关联的脚本ID列表

    # 结构元信息（从PDBe API获取的详细元数据）
    structure_metadata = Column(JSON, nullable=True)  # 结构详细元信息 {"pdb_metadata": {...}, "emdb_metadata": {...}}

    # 时间戳
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    parsed_at = Column(DateTime, nullable=True)
    indexed_at = Column(DateTime, nullable=True)
    
    # 关系
    appendices = relationship("LiteratureAppendix", back_populates="literature", cascade="all, delete-orphan")
    citations = relationship("CitationEntry", back_populates="literature", cascade="all, delete-orphan")
    notes = relationship("LiteratureNote", back_populates="literature", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<LiteratureEntry(id={self.id}, title={self.title[:30]})>"
    
    @hybrid_property
    def has_pdf(self):
        return bool(self.main_pdf_filename)
    
    @hybrid_property
    def has_appendices(self):
        return len(self.appendices) > 0
    
    @hybrid_property
    def is_parsed(self):
        return self.status in [LiteratureStatus.PARSED, LiteratureStatus.INDEXED]
    
    @hybrid_property
    def citation_formatted(self):
        """生成格式化引用"""
        if not self.authors or not self.title:
            return self.title or "Untitled"
        
        # 简单APA格式
        authors_str = ", ".join([a.get('name', '') for a in self.authors[:3]])
        if len(self.authors) > 3:
            authors_str += " et al."
        
        year_str = f" ({self.year})" if self.year else ""
        journal_str = f". {self.journal}" if self.journal else ""
        
        return f"{authors_str}{year_str}. {self.title}{journal_str}."

    def _safe_isoformat(self, obj):
        """安全地将datetime对象转换为ISO格式字符串"""
        if obj is None:
            return None
        if isinstance(obj, str):
            return obj
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        return str(obj)

    def _format_authors(self):
        """格式化作者列表为可读字符串"""
        authors = self.authors
        if not authors:
            return 'Unknown'

        # If already a list of dicts
        if isinstance(authors, list):
            return ', '.join(a.get('name', str(a)) for a in authors)

        # If it's a JSON string
        if isinstance(authors, str):
            import json
            if authors.startswith('['):
                try:
                    authors_list = json.loads(authors)
                    if isinstance(authors_list, list):
                        return ', '.join(a.get('name', str(a)) for a in authors_list)
                except:
                    pass

        return authors

    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "title": self.title,
            "authors": self._format_authors(),
            "journal": self.journal,
            "year": self.year,
            "publication_date": self._safe_isoformat(self.publication_date),
            "publication_date_full": self.publication_date_full,
            "publication_year": self.publication_year,
            "publication_month": self.publication_month,
            "publication_day": self.publication_day,
            "doi": self.doi,
            "abstract": self.abstract,
            "summary": self.summary,
            "key_findings": self.key_findings,
            "cryoem_targets": self.cryoem_targets,
            "keywords": self.keywords,
            "tags": self.tags,
            "status": self.status.value if self.status else None,
            "literature_type": self.literature_type.value if self.literature_type else None,
            "created_at": self._safe_isoformat(self.created_at),
            "updated_at": self._safe_isoformat(self.updated_at),
            "parsed_at": self._safe_isoformat(self.parsed_at),
            "indexed_at": self._safe_isoformat(self.indexed_at),
            "impact_factor": self.impact_factor,
            "citation_count": self.citation_count,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "publisher": self.publisher,
            "confidence_score": self.confidence_score,
            "date_confidence": self.date_confidence,
            # 新增章节字段
            "introduction": self.introduction,
            "methods": self.methods,
            "results": self.results,
            "discussion": self.discussion,
            "conclusions": self.conclusions,
            "data_availability": self.data_availability,
            "sections_json": self.sections_json,
            # ✅ 新增搜索字段
            "search_text_blob": self.search_text_blob,
            # RAG相关字段
            "has_vector_embeddings": self.has_vector_embeddings,
            "embedding_model": self.embedding_model,
            "embedding_dimensions": self.embedding_dimensions,
            "last_embedded_at": self._safe_isoformat(self.last_embedded_at),
            "section_embeddings": self.section_embeddings
        }

class LiteratureAppendix(Base):
    """文献附录表"""
    __tablename__ = "literature_appendices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    literature_id = Column(Integer, ForeignKey('literature_entries.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True)

    # 附录信息
    filename = Column(String(500), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True)
    file_type = Column(String(50), nullable=True)  # pdf, docx, xlsx, zip等
    description = Column(String(500), nullable=True)
    appendix_type = Column(String(100), nullable=True)  # supplementary_data, methods, code, figures等
    
    # 内容信息
    extracted_text = Column(Text, nullable=True)
    page_count = Column(Integer, nullable=True)
    contains_figures = Column(Boolean, default=False)
    contains_tables = Column(Boolean, default=False)
    contains_code = Column(Boolean, default=False)
    
    # 解析状态
    is_parsed = Column(Boolean, default=False)
    parsed_at = Column(DateTime, nullable=True)

    # 向量信息
    embedding = Column(Text, nullable=True)  # JSON格式存储向量
    embedding_model = Column(String(100), nullable=True)
    embedding_dimensions = Column(Integer, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关系
    literature = relationship("LiteratureEntry", back_populates="appendices")
    
    def __repr__(self):
        return f"<LiteratureAppendix(id={self.id}, filename='{self.filename}', type={self.appendix_type})>"

class CitationEntry(Base):
    """引用条目表"""
    __tablename__ = "citation_entries"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    literature_id = Column(Integer, ForeignKey('literature_entries.id', ondelete='CASCADE'), nullable=False)
    
    # 引用信息
    citation_key = Column(String(100), nullable=True, index=True)
    citation_text = Column(Text, nullable=False)
    citation_style = Column(SQLEnum(CitationStyle), default=CitationStyle.APA)
    raw_bibtex = Column(Text, nullable=True)
    
    # 使用信息
    used_in_notes = Column(JSON, default=list)  # 在哪些笔记中使用
    last_cited = Column(DateTime, nullable=True)
    citation_count = Column(Integer, default=0)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关系
    literature = relationship("LiteratureEntry", back_populates="citations")
    
    def __repr__(self):
        return f"<CitationEntry(id={self.id}, key='{self.citation_key}', style={self.citation_style.value})>"

class LiteratureNote(Base):
    """文献笔记表"""
    __tablename__ = "literature_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    literature_id = Column(Integer, ForeignKey('literature_entries.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True)

    # 笔记内容
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    note_type = Column(String(50), default="general")  # general, summary, critique, methodology, results, etc.
    
    # 关联信息
    tags = Column(JSON, default=list)
    page_references = Column(JSON, default=list)  # 关联的页码
    figure_references = Column(JSON, default=list)  # 关联的图表
    
    # 元数据
    is_public = Column(Boolean, default=False)  # 是否公开分享
    word_count = Column(Integer, default=0)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关系
    literature = relationship("LiteratureEntry", back_populates="notes")
    
    def __repr__(self):
        return f"<LiteratureNote(id={self.id}, title='{self.title[:30]}...', type={self.note_type})>"


class QAChatHistory(Base):
    """文献QA聊天历史表"""
    __tablename__ = "qa_chat_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    literature_id = Column(Integer, ForeignKey('literature_entries.id', ondelete='CASCADE'), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True)

    # Session信息
    session_id = Column(String(64), nullable=True, index=True)  # 会话ID，用于关联同一会话的多轮对话

    # 对话内容
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)

    # 关联信息
    model_used = Column(String(100), nullable=True)  # 使用的AI模型
    sources = Column(JSON, default=list)  # 参考来源列表
    result_json = Column(Text, nullable=True)  # 完整的工具结果JSON

    # 元数据
    question_type = Column(String(50), nullable=True)  # 问题类型: literature, structure, sequence, general

    # 时间戳
    created_at = Column(DateTime, default=datetime.now, index=True)

    # 关系
    literature = relationship("LiteratureEntry", back_populates=None)

    def __repr__(self):
        return f"<QAChatHistory(id={self.id}, question='{self.question[:30]}...')>"

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'literature_id': self.literature_id,
            'session_id': self.session_id,
            'question': self.question,
            'answer': self.answer,
            'model_used': self.model_used,
            'sources': self.sources,
            'result_json': self.result_json,
            'question_type': self.question_type,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class LiteratureCollection(Base):
    """文献收藏集"""
    __tablename__ = "literature_collections"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 用户关联 (用于数据隔离)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True)

    # 收藏集信息
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    is_public = Column(Boolean, default=False)
    tags = Column(JSON, default=list)
    
    # 包含的文献
    literature_ids = Column(JSON, default=list)  # 文献ID列表
    literature_count = Column(Integer, default=0)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def __repr__(self):
        return f"<LiteratureCollection(id={self.id}, name='{self.name}', count={self.literature_count})>"


class ProteinEvaluation(Base):
    """蛋白质评估主表"""
    __tablename__ = "protein_evaluations"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 基本信息
    uniprot_id = Column(String(20), nullable=False, index=True)
    gene_name = Column(String(100))
    protein_name = Column(Text)

    # 评估状态
    evaluation_status = Column(String(20), default='pending')  # pending, processing, completed, failed

    # 进度跟踪
    progress = Column(Integer, default=0)  # 0-100
    current_step = Column(String(50))  # 当前执行步骤
    error_message = Column(Text)  # 错误信息（如有）

    # 关联数据（JSON存储）
    pdb_data = Column(JSON)  # PDB元数据
    uniprot_data = Column(JSON)  # Uniprot元数据
    blast_results = Column(JSON)  # Blast结果
    ai_analysis = Column(JSON)  # AI分析结果
    report = Column(Text)  # 最终报告

    # 向量嵌入（RAG用）
    embedding = Column(JSON)

    # 飞书文档
    feishu_doc_url = Column(String(500))
    feishu_doc_id = Column(String(100))

    # 时间戳
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<ProteinEvaluation(id={self.id}, uniprot_id='{self.uniprot_id}', status='{self.evaluation_status}')>"

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'uniprot_id': self.uniprot_id,
            'gene_name': self.gene_name,
            'protein_name': self.protein_name,
            'evaluation_status': self.evaluation_status,
            'progress': self.progress,
            'current_step': self.current_step,
            'error_message': self.error_message,
            'pdb_data': self.pdb_data,
            'uniprot_data': self.uniprot_data,
            'blast_results': self.blast_results,
            'ai_analysis': self.ai_analysis,
            'report': self.report,
            'feishu_doc_url': self.feishu_doc_url,
            'feishu_doc_id': self.feishu_doc_id,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


# ---------- 数据库初始化与迁移 ----------
def initialize_literature_database():
    """初始化文献数据库 - 修复索引创建问题"""
    logger.info("🚀 初始化文献数据库...")

    # 创建所有表
    Base.metadata.create_all(engine)

    # 检查并添加缺失的字段
    check_and_add_missing_columns()

    # 执行数据库迁移 - 添加user_id列（如果不存在）
    migrate_add_user_id_columns()

    # 尝试创建索引，如果失败则继续
    index_statements = [
        "CREATE INDEX IF NOT EXISTS idx_literature_title ON literature_entries(title);",
        "CREATE INDEX IF NOT EXISTS idx_literature_authors ON literature_entries(authors);",
        "CREATE INDEX IF NOT EXISTS idx_literature_journal ON literature_entries(journal);",
        "CREATE INDEX IF NOT EXISTS idx_literature_year ON literature_entries(year);",
        "CREATE INDEX IF NOT EXISTS idx_literature_status ON literature_entries(status);",
        "CREATE INDEX IF NOT EXISTS idx_literature_publication_year ON literature_entries(publication_year);",
        "CREATE INDEX IF NOT EXISTS idx_literature_impact_factor ON literature_entries(impact_factor);",
        "CREATE INDEX IF NOT EXISTS idx_literature_has_vector_embeddings ON literature_entries(has_vector_embeddings);",
        # ✅ 新增搜索字段索引
        "CREATE INDEX IF NOT EXISTS idx_literature_search_blob ON literature_entries(search_text_blob);"
    ]
    
    with engine.connect() as conn:
        for statement in index_statements:
            try:
                conn.execute(text(statement))
                conn.commit()
                logger.debug(f"执行成功: {statement[:50]}...")
            except Exception as e:
                logger.warning(f"执行索引语句失败 {statement[:50]}...: {e}")
                # 尝试使用不同的连接重试
                try:
                    conn.rollback()
                    time.sleep(0.1)  # 短暂延迟
                    conn.execute(text(statement))
                    conn.commit()
                    logger.info(f"重试成功: {statement[:50]}...")
                except Exception as e2:
                    logger.error(f"重试也失败: {statement[:50]}...: {e2}")
                    # 继续执行其他索引创建
    
    logger.info("✅ 文献数据库初始化完成")
    
    return {
        "status": "success",
        "message": "文献数据库初始化完成",
        "tables": ["literature_entries", "literature_appendices", "citation_entries", "literature_notes", "literature_collections"],
        "paths": {
            "literature_dir": str(LITERATURE_DIR),
            "pdfs_dir": str(LITERATURE_PDFS_DIR),
            "appendices_dir": str(LITERATURE_APPENDICES_DIR),
            "database": str(DB_PATH)
        }
    }

# ---------- 枚举转换辅助函数 ----------
def convert_string_to_status(value) -> LiteratureStatus:
    """Robust conversion: accepts enum, uppercase/lowercase strings."""
    if isinstance(value, LiteratureStatus):
        return value
    if isinstance(value, str):
        # 先尝试通过枚举值匹配（枚举值是小写的）
        value_lower = value.lower()
        for status in LiteratureStatus:
            if status.value == value_lower:
                return status
        
        # 再尝试通过枚举名称匹配（枚举名称是大写的）
        try:
            return LiteratureStatus[value.upper()]
        except KeyError:
            allowed_values = [status.value for status in LiteratureStatus]
            raise ValueError(f"Invalid LiteratureStatus: {value}. "
                             f"Allowed values: {allowed_values}")
    raise ValueError(f"Invalid status type: {type(value)}")

def convert_string_to_type(type_str: str) -> LiteratureType:
    """将字符串转换为LiteratureType枚举"""
    if isinstance(type_str, LiteratureType):
        return type_str
    if isinstance(type_str, str):
        type_lower = type_str.lower().replace('-', '_')
        # 通过枚举值匹配
        for lit_type in LiteratureType:
            if lit_type.value == type_lower:
                return lit_type
        # 默认值
        return LiteratureType.JOURNAL_ARTICLE
    raise ValueError(f"Invalid type: {type_str}")

def parse_publication_date(date_str: str) -> Tuple[Optional[datetime], Optional[str], Optional[int], Optional[int], Optional[int], float]:
    """解析出版日期字符串，返回各个日期组件和置信度"""
    if not date_str:
        return None, None, None, None, None, 0.0
    
    date_str = date_str.strip()
    date_formats = [
        ("%Y-%m-%d", 1.0),        # YYYY-MM-DD
        ("%Y/%m/%d", 0.9),        # YYYY/MM/DD
        ("%d/%m/%Y", 0.8),        # DD/MM/YYYY
        ("%m/%d/%Y", 0.8),        # MM/DD/YYYY
        ("%B %d, %Y", 0.7),       # January 1, 2024
        ("%b %d, %Y", 0.7),       # Jan 1, 2024
        ("%Y-%m", 0.6),           # YYYY-MM (只有年和月)
        ("%Y/%m", 0.6),           # YYYY/MM
        ("%Y", 0.5),              # YYYY (只有年)
    ]
    
    # 先尝试完整解析
    for fmt, confidence in date_formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            year = dt.year
            month = dt.month if fmt not in ["%Y-%m", "%Y/%m", "%Y"] else dt.month if hasattr(dt, 'month') else None
            day = dt.day if fmt not in ["%Y-%m", "%Y/%m", "%Y", "%Y-%m", "%Y/%m"] else None
            
            # 格式化完整日期字符串
            if month and day:
                date_full = f"{year:04d}-{month:02d}-{day:02d}"
            elif month:
                date_full = f"{year:04d}-{month:02d}"
            else:
                date_full = f"{year:04d}"
            
            return dt, date_full, year, month, day, confidence
        except ValueError:
            continue
    
    # 如果没有匹配的格式，尝试提取年份
    year_match = re.search(r'\b(19|20)\d{2}\b', date_str)
    if year_match:
        year = int(year_match.group())
        # 尝试提取月份
        month_match = re.search(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|march|april|may|june|july|august|september|october|november|december)\b', date_str.lower())
        month_dict = {
            'jan': 1, 'january': 1,
            'feb': 2, 'february': 2,
            'mar': 3, 'march': 3,
            'apr': 4, 'april': 4,
            'may': 5,
            'jun': 6, 'june': 6,
            'jul': 7, 'july': 7,
            'aug': 8, 'august': 8,
            'sep': 9, 'september': 9,
            'oct': 10, 'october': 10,
            'nov': 11, 'november': 11,
            'dec': 12, 'december': 12
        }
        
        month = None
        day = None
        
        if month_match:
            month_name = month_match.group().lower()
            month = month_dict.get(month_name)
            # 尝试提取日
            day_match = re.search(r'\b\d{1,2}\b', date_str[month_match.end():])
            if day_match:
                day = int(day_match.group())
        
        date_full = f"{year:04d}"
        if month:
            date_full += f"-{month:02d}"
            if day:
                date_full += f"-{day:02d}"
        
        confidence = 0.3  # 较低置信度
        return None, date_full, year, month, day, confidence
    
    return None, None, None, None, None, 0.0

# ---------- 结构同步管理器 ----------
class StructureSyncManager:
    """结构同步管理器 - 处理文献与结构数据库之间的同步"""
    
    def __init__(self):
        self._initialized = False
        self._structure_manager = None
        self.logger = logging.getLogger(__name__ + ".StructureSyncManager")
    
    def _initialize(self):
        """延迟初始化结构管理器"""
        if self._initialized:
            return True

        try:
            # 尝试导入增强结构管理器
            from core.structure_database import get_enhanced_structure_manager
            self._structure_manager = get_enhanced_structure_manager()
            self._initialized = True
            self.logger.info("✅ 结构同步管理器初始化完成")
            return True
        except ImportError as e:
            self.logger.warning(f"无法导入结构管理器: {e}")
            return False
        except Exception as e:
            self.logger.error(f"结构管理器初始化失败: {e}")
            return False
    
    def is_available(self):
        """检查结构同步是否可用"""
        return self._initialized and self._structure_manager is not None
    
    def extract_structure_ids(self, cryoem_targets):
        """从cryoem_targets中提取结构ID"""
        if not cryoem_targets:
            return []
        
        structure_ids = []
        
        try:
            # 处理不同格式的cryoem_targets
            if isinstance(cryoem_targets, str):
                try:
                    data = json.loads(cryoem_targets)
                except:
                    # 如果是逗号分隔的字符串
                    parts = [p.strip() for p in cryoem_targets.split(',')]
                    structure_ids.extend(parts)
                    return structure_ids
            
            if isinstance(cryoem_targets, dict):
                # 字典格式：{"pdb_ids": ["7EWL"], "emdb_ids": ["EMD-12345"]}
                if 'pdb_ids' in cryoem_targets:
                    structure_ids.extend([id for id in cryoem_targets['pdb_ids'] if id])
                if 'emdb_ids' in cryoem_targets:
                    structure_ids.extend([id for id in cryoem_targets['emdb_ids'] if id])
                # 直接结构ID字段
                if 'structure_ids' in cryoem_targets:
                    structure_ids.extend([id for id in cryoem_targets['structure_ids'] if id])
            
            elif isinstance(cryoem_targets, list):
                # 列表格式：["7EWL", "EMD-12345"]
                for item in cryoem_targets:
                    if isinstance(item, str):
                        structure_ids.append(item)
                    elif isinstance(item, dict):
                        # 列表中包含字典，提取id字段
                        if 'id' in item:
                            structure_ids.append(item['id'])
                        elif 'pdb_id' in item:
                            structure_ids.append(item['pdb_id'])
                        elif 'emdb_id' in item:
                            structure_ids.append(item['emdb_id'])
        except Exception as e:
            self.logger.error(f"提取结构ID失败: {e}")
        
        # 清理和标准化ID
        cleaned_ids = []
        for id_str in structure_ids:
            if id_str:
                # 转换为大写并移除空格
                id_clean = str(id_str).strip().upper()
                if id_clean:
                    cleaned_ids.append(id_clean)
        
        return list(set(cleaned_ids))  # 去重
    
    def update_structure_mappings(self, literature_id: int, cryoem_targets, old_targets=None):
        """更新文献-结构映射"""
        if not self._initialize():
            self.logger.warning("结构同步管理器未初始化，跳过更新")
            return False
        
        try:
            # 提取新旧结构ID
            new_ids = self.extract_structure_ids(cryoem_targets)
            old_ids = self.extract_structure_ids(old_targets) if old_targets else []
            
            self.logger.info(f"更新文献-结构映射: 文献ID={literature_id}, 新结构={new_ids}, 旧结构={old_ids}")
            
            # 计算需要添加和删除的ID
            ids_to_add = [id for id in new_ids if id not in old_ids]
            ids_to_remove = [id for id in old_ids if id not in new_ids]
            
            # 删除旧映射
            for structure_id in ids_to_remove:
                try:
                    # 调用结构管理器删除映射
                    success = self._delete_structure_mapping(literature_id, structure_id)
                    if success:
                        self.logger.debug(f"删除结构映射: 文献ID={literature_id}, 结构ID={structure_id}")
                except Exception as e:
                    self.logger.error(f"删除结构映射失败 {structure_id}: {e}")
            
            # 添加新映射
            for structure_id in ids_to_add:
                try:
                    # 确定结构类型
                    structure_type = self._determine_structure_type(structure_id)
                    
                    # 调用结构管理器添加映射
                    success = self._add_structure_mapping(literature_id, structure_id, structure_type)
                    if success:
                        self.logger.debug(f"添加结构映射: 文献ID={literature_id}, 结构ID={structure_id}, 类型={structure_type}")
                        
                        # 可选：确保结构数据存在于数据库
                        self._ensure_structure_in_database(structure_id, structure_type)
                except Exception as e:
                    self.logger.error(f"添加结构映射失败 {structure_id}: {e}")
            
            self.logger.info(f"✅ 结构映射更新完成: 添加{len(ids_to_add)}个, 删除{len(ids_to_remove)}个")
            return True
            
        except Exception as e:
            self.logger.error(f"更新结构映射失败: {e}")
            return False
    
    def _determine_structure_type(self, structure_id: str):
        """确定结构类型"""
        structure_id = str(structure_id).strip().upper()
        
        # PDB ID: 4个字符，第一个是数字
        if len(structure_id) == 4 and structure_id[0].isdigit():
            from core.structure_database import StructureType
            return StructureType.PDB
        
        # EMDB ID: EMD-数字
        if structure_id.startswith('EMD-') or (structure_id.startswith('EMD') and len(structure_id) > 3):
            from core.structure_database import StructureType
            return StructureType.EMDB
        
        # AlphaFold ID: AF-...
        if structure_id.startswith('AF-'):
            from core.structure_database import StructureType
            return StructureType.ALPHAFOLD
        
        # 默认PDB
        from core.structure_database import StructureType
        return StructureType.PDB
    
    def _add_structure_mapping(self, literature_id: int, structure_id: str, structure_type):
        """添加结构映射"""
        try:
            # 使用结构管理器的方法
            return self._structure_manager.database.add_literature_structure_mapping(
                literature_id=literature_id,
                structure_id=structure_id,
                structure_type=structure_type,
                context=f"从文献ID={literature_id}自动映射",
                confidence=0.9
            )
        except Exception as e:
            self.logger.error(f"调用结构管理器添加映射失败: {e}")
            return False
    
    def _delete_structure_mapping(self, literature_id: int, structure_id: str):
        """删除结构映射"""
        try:
            # 直接操作数据库
            db_path = self._structure_manager.database.db_path
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            cursor.execute(
                "DELETE FROM literature_structure_mapping WHERE literature_id = ? AND structure_id = ?",
                (literature_id, structure_id.upper())
            )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"删除结构映射失败: {e}")
            return False
    
    def _ensure_structure_in_database(self, structure_id: str, structure_type):
        """确保结构数据存在于数据库"""
        try:
            # 检查结构是否已存在
            existing = self._structure_manager.database.get_structure(structure_id)
            if existing:
                return True
            
            # 如果不存在，尝试获取结构数据
            self.logger.info(f"结构 {structure_id} 不在数据库中，尝试获取...")
            
            # 使用结构管理器获取结构数据
            structure_data = self._structure_manager.get_or_fetch_structure(
                structure_id, 
                use_cache=True
            )
            
            if structure_data:
                self.logger.info(f"✅ 成功获取结构数据: {structure_id}")
                return True
            else:
                self.logger.warning(f"无法获取结构数据: {structure_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"确保结构在数据库中失败: {e}")
            return False
    
    def delete_all_literature_mappings(self, literature_id: int):
        """删除文献的所有结构映射"""
        if not self._initialize():
            return False
        
        try:
            # 直接操作数据库
            db_path = self._structure_manager.database.db_path
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            cursor.execute(
                "DELETE FROM literature_structure_mapping WHERE literature_id = ?",
                (literature_id,)
            )
            
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            self.logger.info(f"✅ 删除文献所有结构映射: 文献ID={literature_id}, 删除{deleted_count}条映射")
            return True
            
        except Exception as e:
            self.logger.error(f"删除文献所有结构映射失败: {e}")
            return False

# 全局结构同步管理器实例
_structure_sync_manager = None

def get_structure_sync_manager():
    """获取结构同步管理器实例"""
    global _structure_sync_manager
    if _structure_sync_manager is None:
        _structure_sync_manager = StructureSyncManager()
    return _structure_sync_manager

# ---------- CRUD操作函数 ----------
def create_literature_session():
    """创建数据库会话"""
    return SessionLocal()


# ---------- 用户管理函数 ----------
def create_user(username: str, email: str, password_hash: str, display_name: str = None) -> Tuple[bool, Any]:
    """创建新用户"""
    session = create_literature_session()
    try:
        # 检查用户名和邮箱是否已存在
        existing_user = session.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()
        if existing_user:
            return False, "用户名或邮箱已存在"

        user = User(
            username=username,
            email=email,
            password_hash=password_hash,
            display_name=display_name or username
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return True, user
    except Exception as e:
        session.rollback()
        logger.error(f"创建用户失败: {e}")
        return False, str(e)
    finally:
        session.close()


def get_user_by_username(username: str) -> Optional[User]:
    """根据用户名获取用户"""
    session = create_literature_session()
    try:
        return session.query(User).filter(User.username == username).first()
    finally:
        session.close()


def get_user_by_id(user_id: int) -> Optional[User]:
    """根据ID获取用户"""
    session = create_literature_session()
    try:
        return session.query(User).filter(User.id == user_id).first()
    finally:
        session.close()


def get_user_by_email(email: str) -> Optional[User]:
    """根据邮箱获取用户"""
    session = create_literature_session()
    try:
        return session.query(User).filter(User.email == email).first()
    finally:
        session.close()


def update_user_last_login(user_id: int) -> bool:
    """更新用户最后登录时间"""
    session = create_literature_session()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        if user:
            user.last_login = datetime.now()
            session.commit()
            return True
        return False
    except Exception as e:
        session.rollback()
        logger.error(f"更新用户登录时间失败: {e}")
        return False
    finally:
        session.close()


def add_literature_entry(data: Dict[str, Any], user_id: int = None) -> Tuple[bool, Any]:
    """添加文献条目"""
    session = create_literature_session()
    try:
        # 检查是否已存在
        if data.get('doi'):
            # 只检查同一用户的文献
            q = session.query(LiteratureEntry).filter_by(doi=data['doi'])
            if user_id is not None:
                q = q.filter(LiteratureEntry.user_id == user_id)
            existing = q.first()
            if existing:
                logger.warning(f"文献已存在: DOI={data['doi']}")
                return False, existing

        if HAS_JSON_UTILS:
            validation_result = validate_literature_data(data, required_fields=['title'])
            if not validation_result['valid']:
                logger.warning(f"文献数据验证失败: {validation_result['errors']}")

            # 使用清洗后的数据
            sanitized_data = validation_result['sanitized_data']
        else:
            # 回退到手动处理
            sanitized_data = data.copy()
        
        # 处理枚举值
        if 'status' in sanitized_data:
            sanitized_data['status'] = convert_string_to_status(sanitized_data['status'])
        
        if 'literature_type' in sanitized_data:
            sanitized_data['literature_type'] = convert_string_to_type(sanitized_data['literature_type'])
        
        # 处理日期字段（保持不变）
        date_fields_processed = False
        if 'publication_date_full' in sanitized_data and sanitized_data['publication_date_full']:
            # ... 日期处理代码不变 ...
        
            # 处理JSON字段 - 使用统一工具或回退
            json_fields = ['authors', 'keywords', 'disciplines', 'tags', 'references', 'cited_by',
                        'related_structures', 'related_scripts', 'cryoem_targets', 'key_findings',
                        'sections_json', 'section_embeddings', 'search_text_blob',
                        'structure_ids', 'structure_metadata']
        
        if HAS_JSON_UTILS:
            # 使用统一工具处理JSON字段
            for field in json_fields:
                if field in sanitized_data:
                    sanitized_data[field] = prepare_json_field(sanitized_data[field], field)
        else:
            # 回退到原有处理逻辑（但简化）
            for field in json_fields:
                if field in sanitized_data:
                    value = sanitized_data[field]
                    if isinstance(value, str):
                        try:
                            sanitized_data[field] = json.loads(value)
                        except:
                            # 简化处理：转换为适当的格式
                            if field in ['key_findings', 'sections_json', 'section_embeddings', 'cryoem_targets']:
                                sanitized_data[field] = {}
                            elif field == 'authors':
                                sanitized_data[field] = [{"name": value}]
                            else:
                                sanitized_data[field] = [value]
        
        # 特殊处理作者和结构ID字段
        if 'authors' in sanitized_data and HAS_JSON_UTILS:
            sanitized_data['authors'] = normalize_authors(sanitized_data['authors'])
        
        if 'cryoem_targets' in sanitized_data and HAS_JSON_UTILS:
            sanitized_data['cryoem_targets'] = normalize_cryoem_targets(sanitized_data['cryoem_targets'])
        
        # 创建新条目
        if user_id is not None:
            sanitized_data['user_id'] = user_id
        entry = LiteratureEntry(**sanitized_data)
        session.add(entry)
        session.commit()
        session.refresh(entry)
        
        logger.info(f"✅ 添加文献: ID={entry.id}, 标题='{entry.title[:50]}...'")
        
        # 同步结构数据（保持不变）
        if sanitized_data.get('cryoem_targets'):
            sync_manager = get_structure_sync_manager()
            if sync_manager.is_available():
                sync_manager.update_structure_mappings(entry.id, sanitized_data['cryoem_targets'])
        
        return True, entry
        
    except Exception as e:
        session.rollback()
        logger.error(f"❌ 添加文献失败: {e}")
        import traceback
        traceback.print_exc()
        return False, str(e)
    finally:
        session.close()

def get_literature_entry(literature_id: int, user_id: int = None) -> Optional[LiteratureEntry]:
    """根据ID获取文献"""
    session = create_literature_session()
    try:
        q = session.query(LiteratureEntry).filter(LiteratureEntry.id == literature_id)
        if user_id is not None:
            q = q.filter(LiteratureEntry.user_id == user_id)
        entry = q.first()
        return entry
    finally:
        session.close()

def get_literature_entry_as_dict(literature_id: int, user_id: int = None) -> Optional[Dict[str, Any]]:
    """根据ID获取文献并转换为字典"""
    entry = get_literature_entry(literature_id, user_id)
    if entry:
        return entry.to_dict()
    return None

def search_literature(
    query: str = None,
    author: str = None,
    journal: str = None,
    year_from: int = None,
    year_to: int = None,
    tags: List[str] = None,
    status: str = None,
    has_cryoem_targets: bool = None,
    has_vector_embeddings: bool = None,
    limit: int = 50,
    user_id: int = None
) -> List[LiteratureEntry]:
    """搜索文献 - 支持标题、作者、期刊、结构ID、DOI等多维度搜索"""
    session = create_literature_session()
    try:
        # 先获取所有文献（带筛选条件）
        q = session.query(LiteratureEntry)

        # 用户数据隔离
        if user_id is not None:
            q = q.filter(LiteratureEntry.user_id == user_id)

        if author:
            q = q.filter(LiteratureEntry.authors.ilike(f'%{author}%'))

        if journal:
            q = q.filter(LiteratureEntry.journal.ilike(f'%{journal}%'))

        # 年份筛选 - 使用 coalesce 处理 NULL 值
        # 同时检查 year 和 publication_year 两个字段
        from sqlalchemy import func, or_
        year_filter_conditions = []

        if year_from:
            # 检查 year 字段
            year_cond_from = func.coalesce(LiteratureEntry.year, 0) >= year_from
            # 检查 publication_year 字段
            pub_year_cond_from = func.coalesce(LiteratureEntry.publication_year, 0) >= year_from
            year_filter_conditions.append(or_(year_cond_from, pub_year_cond_from))

        if year_to:
            # 检查 year 字段
            year_cond_to = func.coalesce(LiteratureEntry.year, 9999) <= year_to
            # 检查 publication_year 字段
            pub_year_cond_to = func.coalesce(LiteratureEntry.publication_year, 9999) <= year_to
            year_filter_conditions.append(or_(year_cond_to, pub_year_cond_to))

        # 应用年份筛选条件
        if year_filter_conditions:
            q = q.filter(or_(*year_filter_conditions))

        if tags:
            for tag in tags:
                q = q.filter(LiteratureEntry.tags.ilike(f'%{tag}%'))

        if status:
            try:
                status_enum = convert_string_to_status(status)
                q = q.filter(LiteratureEntry.status == status_enum)
            except ValueError:
                q = q.filter(LiteratureEntry.status == status)

        if has_cryoem_targets is not None:
            if has_cryoem_targets:
                q = q.filter(LiteratureEntry.cryoem_targets.isnot(None))
            else:
                q = q.filter(LiteratureEntry.cryoem_targets.is_(None))

        if has_vector_embeddings is not None:
            q = q.filter(LiteratureEntry.has_vector_embeddings == has_vector_embeddings)

        # 获取基础结果 - 处理 NULL 年份，使用两个年份字段
        from sqlalchemy import desc, or_
        coalesced_year = func.coalesce(LiteratureEntry.year, LiteratureEntry.publication_year, 0)
        all_results = q.order_by(desc(coalesced_year), LiteratureEntry.created_at.desc()).all()

        # 如果没有查询，直接返回
        if not query:
            return all_results[:limit]

        query_lower = query.lower().strip()
        query_upper = query.upper()

        # 判断是否为结构ID
        pdb_match = len(query_upper) == 4 and query_upper[0].isdigit()
        emdb_match = query_lower.startswith('emd') or query_lower.startswith('emdb')

        filtered_results = []
        for entry in all_results:
            matched = False

            # 1. 匹配结构ID (PDB/EMDB)
            if pdb_match:
                targets = entry.cryoem_targets
                if targets and isinstance(targets, dict):
                    pdb_ids = targets.get('pdb_ids', [])
                    if any(query_upper == pid.upper() for pid in pdb_ids):
                        matched = True

            # 2. 匹配EMDB ID
            if not matched and emdb_match:
                targets = entry.cryoem_targets
                if targets and isinstance(targets, dict):
                    emdb_ids = targets.get('emdb_ids', [])
                    # 规范化查询
                    query_norm = query_upper
                    if query_norm.startswith('EMD-'):
                        pass
                    elif query_norm.startswith('EMDB'):
                        query_norm = 'EMD-' + query_norm.replace('EMDB', '')
                    else:
                        query_norm = 'EMD-' + query_norm
                    for eid in emdb_ids:
                        if query_norm == eid.upper() or query_norm.replace('EMD-', '') == eid.upper().replace('EMD-', ''):
                            matched = True
                            break

            # 3. 匹配文本字段
            if not matched:
                # authors 可能是列表或字符串
                authors_str = ''
                if isinstance(entry.authors, list):
                    authors_str = ' '.join(str(a) for a in entry.authors)
                else:
                    authors_str = str(entry.authors or '')

                text_fields = [
                    str(entry.title or ''),
                    str(entry.abstract or ''),
                    str(entry.journal or ''),
                    authors_str,
                    str(entry.keywords or ''),
                    str(entry.doi or ''),
                    str(entry.search_text_blob or '')
                ]
                for field in text_fields:
                    if query_lower in field.lower():
                        matched = True
                        break

            if matched:
                filtered_results.append(entry)

        return filtered_results[:limit]

    finally:
        session.close()

def search_literature_as_dict(
    query: str = None,
    author: str = None,
    journal: str = None,
    year_from: int = None,
    year_to: int = None,
    tags: List[str] = None,
    status: str = None,
    has_cryoem_targets: bool = None,
    has_vector_embeddings: bool = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """搜索文献并返回字典列表"""
    entries = search_literature(
        query=query,
        author=author,
        journal=journal,
        year_from=year_from,
        year_to=year_to,
        tags=tags,
        status=status,
        has_cryoem_targets=has_cryoem_targets,
        has_vector_embeddings=has_vector_embeddings,
        limit=limit
    )
    
    return [entry.to_dict() for entry in entries]

def update_literature_entry(literature_id: int, updates: Dict[str, Any]) -> bool:
    """更新文献条目"""
    session = create_literature_session()
    try:
        entry = session.query(LiteratureEntry).get(literature_id)
        if not entry:
            return False
        
        # 记录旧的cryoem_targets用于同步
        old_cryoem_targets = None
        if 'cryoem_targets' in updates:
            old_cryoem_targets = entry.cryoem_targets
        
        # 处理枚举值 - 使用转换函数
        if 'status' in updates:
            updates['status'] = convert_string_to_status(updates['status'])
        
        if 'literature_type' in updates:
            updates['literature_type'] = convert_string_to_type(updates['literature_type'])
        
        # 特殊处理字段
        processed_updates = {}
        for key, value in updates.items():
            if hasattr(entry, key):
                # 处理日期字段
                if key == 'publication_date_full':
                    # 如果有完整日期字符串，解析它
                    if value:
                        dt, date_full, year, month, day, confidence = parse_publication_date(value)
                        
                        if dt:
                            processed_updates['publication_date'] = dt
                        processed_updates['publication_date_full'] = date_full
                        processed_updates['year'] = year
                        processed_updates['publication_year'] = year
                        processed_updates['publication_month'] = month
                        processed_updates['publication_day'] = day
                        # 如果有提供置信度则使用，否则使用解析得到的置信度
                        if 'date_confidence' in updates:
                            processed_updates['date_confidence'] = updates['date_confidence']
                        else:
                            processed_updates['date_confidence'] = confidence
                    else:
                        processed_updates[key] = None
                
                # 处理 publication_date 字段
                elif key == 'publication_date':
                    if isinstance(value, str):
                        # 尝试解析日期字符串
                        dt, date_full, year, month, day, confidence = parse_publication_date(value)
                        
                        if dt:
                            processed_updates[key] = dt
                        else:
                            processed_updates[key] = None
                        
                        # 同时更新其他日期字段
                        processed_updates['publication_date_full'] = date_full
                        processed_updates['year'] = year
                        processed_updates['publication_year'] = year
                        processed_updates['publication_month'] = month
                        processed_updates['publication_day'] = day
                        if 'date_confidence' not in processed_updates and 'date_confidence' not in updates:
                            processed_updates['date_confidence'] = confidence
                    elif isinstance(value, datetime):
                        processed_updates[key] = value
                        # 更新其他日期字段
                        processed_updates['publication_date_full'] = value.strftime("%Y-%m-%d")
                        processed_updates['year'] = value.year
                        processed_updates['publication_year'] = value.year
                        processed_updates['publication_month'] = value.month
                        processed_updates['publication_day'] = value.day
                    else:
                        processed_updates[key] = None
                
                # 处理JSON字段
                elif key in ['authors', 'keywords', 'disciplines', 'tags', 'references', 'cited_by', 
                            'related_structures', 'related_scripts', 'cryoem_targets', 'key_findings',
                            'sections_json', 'section_embeddings', 'search_text_blob']:
                    if isinstance(value, str):
                        try:
                            # 尝试解析JSON字符串
                            processed_updates[key] = json.loads(value)
                        except:
                            # 如果不是JSON，保存为列表或字典
                            if key in ['key_findings', 'sections_json', 'section_embeddings', 'search_text_blob']:
                                processed_updates[key] = value  # search_text_blob是纯文本
                            elif key == 'authors':
                                processed_updates[key] = [{"name": value}]
                            else:
                                processed_updates[key] = [value]
                    else:
                        processed_updates[key] = value
                
                # 处理其他字段
                else:
                    processed_updates[key] = value
        
        # 应用更新
        for key, value in processed_updates.items():
            setattr(entry, key, value)
        
        entry.updated_at = datetime.now()
        session.commit()
        
        logger.info(f"✅ 更新文献: ID={literature_id}")
        
        # 同步结构数据
        if 'cryoem_targets' in updates:
            sync_manager = get_structure_sync_manager()
            if sync_manager.is_available():
                sync_manager.update_structure_mappings(
                    literature_id, 
                    updates['cryoem_targets'],
                    old_cryoem_targets
                )
        
        return True
        
    except Exception as e:
        session.rollback()
        logger.error(f"❌ 更新文献失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()

def delete_literature_entry(literature_id: int) -> Dict[str, Any]:
    """删除文献条目（返回详细信息）"""
    session = create_literature_session()
    try:
        entry = session.query(LiteratureEntry).get(literature_id)
        if not entry:
            return {"success": False, "error": "文献不存在"}
        
        # 记录要删除的文件
        deleted_files = []
        
        # 删除物理文件
        if entry.main_pdf_path and Path(entry.main_pdf_path).exists():
            try:
                Path(entry.main_pdf_path).unlink(missing_ok=True)
                deleted_files.append(entry.main_pdf_path)
            except Exception as e:
                logger.error(f"删除PDF文件失败 {entry.main_pdf_path}: {e}")
        
        # 删除附录文件
        for appendix in entry.appendices:
            if appendix.file_path and Path(appendix.file_path).exists():
                try:
                    Path(appendix.file_path).unlink(missing_ok=True)
                    deleted_files.append(appendix.file_path)
                except Exception as e:
                    logger.error(f"删除附录文件失败 {appendix.file_path}: {e}")
        
        # 同步删除结构映射
        sync_manager = get_structure_sync_manager()
        if sync_manager.is_available():
            sync_manager.delete_all_literature_mappings(literature_id)
        
        # 删除数据库记录（级联删除会自动处理相关记录）
        session.delete(entry)
        session.commit()
        
        logger.info(f"✅ 删除文献: ID={literature_id}, 标题='{entry.title[:50]}...'")
        logger.info(f"✅ 删除文件: {len(deleted_files)} 个文件")
        
        return {
            "success": True,
            "literature_id": literature_id,
            "title": entry.title,
            "deleted_files": deleted_files,
            "deleted_file_count": len(deleted_files),
            "deleted_structure_mappings": True,
            "message": f"成功删除文献 '{entry.title[:50]}...' 及其 {len(deleted_files)} 个文件"
        }
        
    except Exception as e:
        session.rollback()
        logger.error(f"❌ 删除文献失败: {e}")
        return {"success": False, "error": str(e)}
    finally:
        session.close()

def get_literature_stats(user_id: int = None) -> Dict[str, Any]:
    """获取文献统计信息"""
    session = create_literature_session()
    try:
        # 构建基础查询
        base_query = session.query(LiteratureEntry)
        if user_id is not None:
            base_query = base_query.filter(LiteratureEntry.user_id == user_id)

        total = base_query.count()
        parsed = base_query.filter(
            LiteratureEntry.status.in_([LiteratureStatus.PARSED, LiteratureStatus.INDEXED])
        ).count()
        with_pdf = base_query.filter(LiteratureEntry.main_pdf_filename.isnot(None)).count()
        with_appendices = base_query.filter(LiteratureEntry.appendices.any()).count()
        with_embeddings = base_query.filter(LiteratureEntry.has_vector_embeddings == True).count()
        
        # 按年份统计
        year_q = session.query(
            LiteratureEntry.publication_year,
            func.count(LiteratureEntry.id).label('count')
        ).filter(LiteratureEntry.publication_year.isnot(None))
        if user_id is not None:
            year_q = year_q.filter(LiteratureEntry.user_id == user_id)
        year_stats = year_q.group_by(LiteratureEntry.publication_year).all()

        # 按期刊统计
        journal_q = session.query(
            LiteratureEntry.journal,
            func.count(LiteratureEntry.id).label('count')
        ).filter(LiteratureEntry.journal.isnot(None))
        if user_id is not None:
            journal_q = journal_q.filter(LiteratureEntry.user_id == user_id)
        journal_stats = journal_q.group_by(LiteratureEntry.journal).all()

        # 冷冻电镜相关统计
        cryoem_q = session.query(
            func.count(LiteratureEntry.id).label('count')
        ).filter(LiteratureEntry.cryoem_targets.isnot(None))
        if user_id is not None:
            cryoem_q = cryoem_q.filter(LiteratureEntry.user_id == user_id)
        cryoem_stats = cryoem_q.scalar()

        # 影响因子统计
        impact_q = session.query(
            func.avg(LiteratureEntry.impact_factor).label('avg_impact'),
            func.max(LiteratureEntry.impact_factor).label('max_impact'),
            func.min(LiteratureEntry.impact_factor).label('min_impact')
        ).filter(LiteratureEntry.impact_factor.isnot(None))
        if user_id is not None:
            impact_q = impact_q.filter(LiteratureEntry.user_id == user_id)
        impact_stats = impact_q.first()

        # 章节统计
        sections_with_content = {}
        section_fields = ['abstract', 'introduction', 'methods', 'results', 'discussion', 'conclusions', 'data_availability', 'search_text_blob']
        for field in section_fields:
            section_q = session.query(LiteratureEntry).filter(
                getattr(LiteratureEntry, field).isnot(None),
                getattr(LiteratureEntry, field) != ''
            )
            if user_id is not None:
                section_q = section_q.filter(LiteratureEntry.user_id == user_id)
            count = section_q.count()
            sections_with_content[field] = count
        
        return {
            "total_count": total,
            "parsed_count": parsed,
            "with_pdf": with_pdf,
            "with_appendices": with_appendices,
            "with_structure_count": cryoem_stats or 0,
            "with_vector_embeddings": with_embeddings,
            "parsing_ratio": parsed/total if total > 0 else 0,
            "embedding_ratio": with_embeddings/total if total > 0 else 0,
            "avg_impact_factor": float(impact_stats[0]) if impact_stats[0] else None,
            "max_impact_factor": float(impact_stats[1]) if impact_stats[1] else None,
            "min_impact_factor": float(impact_stats[2]) if impact_stats[2] else None,
            "year_stats": [{"year": y, "count": c} for y, c in year_stats],
            "journal_stats": [{"journal": j, "count": c} for j, c in journal_stats if j],
            "sections_with_content": sections_with_content,
            "database_size": DB_PATH.stat().st_size if DB_PATH.exists() else 0
        }

    finally:
        session.close()


def get_all_keywords() -> list:
    """
    Get all unique keywords/tags from literature entries
    Returns a list of unique keywords
    """
    session = create_session()
    try:
        # Get keywords from keywords field
        keywords_result = session.query(LiteratureEntry.keywords).filter(
            LiteratureEntry.keywords.isnot(None),
            LiteratureEntry.keywords != ''
        ).all()

        all_keywords = set()
        for (kw_str,) in keywords_result:
            if kw_str:
                try:
                    # Try to parse as JSON array
                    kw_list = json.loads(kw_str)
                    if isinstance(kw_list, list):
                        all_keywords.update(kw_list)
                except json.JSONDecodeError:
                    # Treat as comma-separated string
                    for kw in kw_str.split(','):
                        kw = kw.strip()
                        if kw:
                            all_keywords.add(kw)

        return sorted(list(all_keywords))
    finally:
        session.close()

# ---------- 附录管理函数 ----------
def add_appendix_to_literature(literature_id: int, file_data: Dict[str, Any]) -> Tuple[bool, Any]:
    """为文献添加附录"""
    session = create_literature_session()
    try:
        literature = session.query(LiteratureEntry).get(literature_id)
        if not literature:
            return False, "文献不存在"
        
        appendix = LiteratureAppendix(
            literature_id=literature_id,
            **file_data
        )
        
        session.add(appendix)
        session.commit()
        session.refresh(appendix)
        
        logger.info(f"✅ 添加附录: 文献ID={literature_id}, 附录ID={appendix.id}")
        return True, appendix
        
    except Exception as e:
        session.rollback()
        logger.error(f"❌ 添加附录失败: {e}")
        return False, str(e)
    finally:
        session.close()

def get_literature_appendices(literature_id: int) -> List[LiteratureAppendix]:
    """获取文献的所有附录"""
    session = create_literature_session()
    try:
        literature = session.query(LiteratureEntry).get(literature_id)
        if literature:
            return literature.appendices
        return []
    finally:
        session.close()

# ---------- 笔记管理函数 ----------
def add_note_to_literature(literature_id: int, note_data: Dict[str, Any]) -> Tuple[bool, Any]:
    """为文献添加笔记"""
    session = create_literature_session()
    try:
        literature = session.query(LiteratureEntry).get(literature_id)
        if not literature:
            return False, "文献不存在"
        
        note = LiteratureNote(
            literature_id=literature_id,
            **note_data
        )
        
        session.add(note)
        session.commit()
        session.refresh(note)
        
        logger.info(f"✅ 添加笔记: 文献ID={literature_id}, 笔记ID={note.id}")
        return True, note
        
    except Exception as e:
        session.rollback()
        logger.error(f"❌ 添加笔记失败: {e}")
        return False, str(e)
    finally:
        session.close()

def get_literature_notes(literature_id: int, user_id: int = None) -> List[LiteratureNote]:
    """获取文献的所有笔记"""
    session = create_literature_session()
    try:
        q = session.query(LiteratureNote).filter(LiteratureNote.literature_id == literature_id)
        if user_id is not None:
            q = q.filter(LiteratureNote.user_id == user_id)
        return q.all()
    finally:
        session.close()


# ========== QA Chat History Functions ==========

def save_qa_chat_history(
    question: str,
    answer: str,
    literature_id: Optional[int] = None,
    model_used: Optional[str] = None,
    sources: Optional[List[Dict]] = None,
    question_type: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[int] = None,
    result_json: Optional[str] = None
) -> Optional[QAChatHistory]:
    """保存QA聊天记录"""
    session = create_literature_session()
    try:
        history = QAChatHistory(
            literature_id=literature_id,
            user_id=user_id,
            question=question,
            answer=answer,
            model_used=model_used,
            sources=sources or [],
            question_type=question_type,
            session_id=session_id,
            result_json=result_json
        )
        session.add(history)
        session.commit()
        session.refresh(history)
        logger.info(f"保存QA聊天记录成功: ID={history.id}, session={session_id}")
        return history
    except Exception as e:
        logger.error(f"保存QA聊天记录失败: {e}")
        session.rollback()
        return None
    finally:
        session.close()


def get_qa_chat_history(
    literature_id: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
    session_id: Optional[str] = None,
    user_id: int = None
) -> List[QAChatHistory]:
    """获取QA聊天历史"""
    session = create_literature_session()
    try:
        query = session.query(QAChatHistory)
        if literature_id:
            query = query.filter(QAChatHistory.literature_id == literature_id)
        if session_id:
            query = query.filter(QAChatHistory.session_id == session_id)
        if user_id is not None:
            query = query.filter(QAChatHistory.user_id == user_id)
        query = query.order_by(QAChatHistory.created_at.desc())
        query = query.offset(offset).limit(limit)
        return query.all()
    finally:
        session.close()


def get_qa_chat_history_by_session(session_id: str, user_id: int = None) -> List[QAChatHistory]:
    """获取指定session的所有聊天历史（按时间正序）"""
    session = create_literature_session()
    try:
        q = session.query(QAChatHistory).filter(QAChatHistory.session_id == session_id)
        if user_id is not None:
            q = q.filter(QAChatHistory.user_id == user_id)
        return q.order_by(QAChatHistory.created_at.asc()).all()
    finally:
        session.close()


def get_qa_chat_history_by_id(history_id: int, user_id: int = None) -> Optional[QAChatHistory]:
    """根据ID获取单条QA聊天记录"""
    session = create_literature_session()
    try:
        q = session.query(QAChatHistory).filter(QAChatHistory.id == history_id)
        if user_id is not None:
            q = q.filter(QAChatHistory.user_id == user_id)
        return q.first()
    finally:
        session.close()


def delete_qa_chat_history(history_id: int, user_id: int = None) -> bool:
    """删除QA聊天记录"""
    session = create_literature_session()
    try:
        q = session.query(QAChatHistory).filter(QAChatHistory.id == history_id)
        if user_id is not None:
            q = q.filter(QAChatHistory.user_id == user_id)
        history = q.first()
        if history:
            session.delete(history)
            session.commit()
            logger.info(f"删除QA聊天记录成功: ID={history_id}")
            return True
        return False
    except Exception as e:
        logger.error(f"删除QA聊天记录失败: {e}")
        session.rollback()
        return False
    finally:
        session.close()


# ========== QA History Wrapper Functions (for Agent) ==========

def save_qa_history(
    question: str,
    answer: str,
    session_id: Optional[str] = None,
    user_id: Optional[int] = None,
    result_json: Optional[str] = None
) -> Optional[QAChatHistory]:
    """保存问答历史（Agent用）"""
    # 解析 result_json 获取额外信息
    sources = None
    question_type = None
    model_used = None

    if result_json:
        import json
        try:
            result_data = json.loads(result_json)
            sources = result_data.get('sources', [])
            question_type = result_data.get('type')
            # 从 tool_results 中获取模型信息
            tool_results = result_data.get('tool_results', [])
            if tool_results:
                model_used = tool_results[0].get('model') if tool_results else None
        except (json.JSONDecodeError, TypeError):
            pass

    return save_qa_chat_history(
        question=question,
        answer=answer,
        session_id=session_id,
        user_id=user_id,
        sources=sources,
        question_type=question_type,
        model_used=model_used,
        result_json=result_json
    )


def get_qa_history(
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """获取问答历史（Agent用）"""
    history = get_qa_chat_history(
        user_id=user_id,
        session_id=session_id,
        limit=limit
    )
    return [h.to_dict() for h in history]


def get_user_id_by_string(user_id_str: str) -> Optional[int]:
    """将字符串用户ID转换为整数ID"""
    if not user_id_str:
        return None
    try:
        # 尝试直接转换
        return int(user_id_str)
    except (ValueError, TypeError):
        pass
    # 尝试从数据库获取用户
    user = get_user_by_username(user_id_str)
    if user:
        return user.id
    return None


# ========== Protein Evaluation Functions ==========

def create_protein_evaluation(uniprot_id: str, gene_name: str = None, protein_name: str = None) -> Optional[ProteinEvaluation]:
    """创建蛋白质评估记录"""
    session = create_literature_session()
    try:
        evaluation = ProteinEvaluation(
            uniprot_id=uniprot_id.upper(),
            gene_name=gene_name,
            protein_name=protein_name,
            evaluation_status='pending',
            progress=0,
            started_at=datetime.now()
        )
        session.add(evaluation)
        session.commit()
        session.refresh(evaluation)
        logger.info(f"创建蛋白质评估成功: ID={evaluation.id}, UniProt={uniprot_id}")
        return evaluation
    except Exception as e:
        logger.error(f"创建蛋白质评估失败: {e}")
        session.rollback()
        return None
    finally:
        session.close()


def get_protein_evaluation(evaluation_id: int) -> Optional[ProteinEvaluation]:
    """获取蛋白质评估记录"""
    session = create_literature_session()
    try:
        return session.query(ProteinEvaluation).filter(ProteinEvaluation.id == evaluation_id).first()
    finally:
        session.close()


def get_protein_evaluation_by_uniprot(uniprot_id: str) -> Optional[ProteinEvaluation]:
    """通过UniProt ID获取蛋白质评估记录"""
    session = create_literature_session()
    try:
        return session.query(ProteinEvaluation).filter(
            ProteinEvaluation.uniprot_id == uniprot_id.upper()
        ).order_by(ProteinEvaluation.created_at.desc()).first()
    finally:
        session.close()


def get_all_protein_evaluations(limit: int = 50, offset: int = 0) -> List[ProteinEvaluation]:
    """获取所有蛋白质评估记录"""
    session = create_literature_session()
    try:
        return session.query(ProteinEvaluation).order_by(
            ProteinEvaluation.created_at.desc()
        ).offset(offset).limit(limit).all()
    finally:
        session.close()


def update_protein_evaluation(evaluation_id: int, updates: Dict[str, Any]) -> bool:
    """更新蛋白质评估记录"""
    session = create_literature_session()
    try:
        evaluation = session.query(ProteinEvaluation).filter(ProteinEvaluation.id == evaluation_id).first()
        if not evaluation:
            return False

        for key, value in updates.items():
            if hasattr(evaluation, key):
                setattr(evaluation, key, value)

        evaluation.updated_at = datetime.now()
        session.commit()
        logger.info(f"更新蛋白质评估成功: ID={evaluation_id}")
        return True
    except Exception as e:
        logger.error(f"更新蛋白质评估失败: {e}")
        session.rollback()
        return False
    finally:
        session.close()


def delete_protein_evaluation(evaluation_id: int) -> bool:
    """删除蛋白质评估记录"""
    session = create_literature_session()
    try:
        evaluation = session.query(ProteinEvaluation).filter(ProteinEvaluation.id == evaluation_id).first()
        if evaluation:
            session.delete(evaluation)
            session.commit()
            logger.info(f"删除蛋白质评估成功: ID={evaluation_id}")
            return True
        return False
    except Exception as e:
        logger.error(f"删除蛋白质评估失败: {e}")
        session.rollback()
        return False
    finally:
        session.close()


def search_protein_evaluations(query: str, limit: int = 20) -> List[ProteinEvaluation]:
    """搜索蛋白质评估记录"""
    session = create_literature_session()
    try:
        search_pattern = f"%{query}%"
        return session.query(ProteinEvaluation).filter(
            (ProteinEvaluation.uniprot_id.like(search_pattern)) |
            (ProteinEvaluation.gene_name.like(search_pattern)) |
            (ProteinEvaluation.protein_name.like(search_pattern))
        ).order_by(ProteinEvaluation.created_at.desc()).limit(limit).all()
    finally:
        session.close()


# 在 literature_db.py 中添加辅助函数
def _ensure_json_serializable(value):
    """确保值是JSON可序列化的"""
    if value is None:
        return None
    if isinstance(value, (list, dict, str, int, float, bool)):
        return value
    # 尝试转换为字符串
    try:
        return str(value)
    except:
        return None

def add_literature_entry(data: Dict[str, Any]) -> Tuple[bool, Any]:
    """添加文献条目 - 修复JSON字段处理"""
    session = create_literature_session()
    try:
        # 检查是否已存在
        if data.get('doi'):
            existing = session.query(LiteratureEntry).filter_by(doi=data['doi']).first()
            if existing:
                logger.warning(f"文献已存在: DOI={data['doi']}")
                return False, existing
        
        # 处理枚举值 - 使用转换函数
        if 'status' in data:
            data['status'] = convert_string_to_status(data['status'])
        
        if 'literature_type' in data:
            data['literature_type'] = convert_string_to_type(data['literature_type'])
        
        # 处理日期字段
        date_fields_processed = False
        if 'publication_date_full' in data and data['publication_date_full']:
            # 如果有完整日期字符串，解析它
            dt, date_full, year, month, day, confidence = parse_publication_date(data['publication_date_full'])
            
            # 更新数据
            if dt:
                data['publication_date'] = dt
            data['publication_date_full'] = date_full
            data['year'] = year
            data['publication_year'] = year
            data['publication_month'] = month
            data['publication_day'] = day
            if 'date_confidence' not in data:
                data['date_confidence'] = confidence
            date_fields_processed = True
        
        # 如果没有完整日期但有原始日期字段，也尝试解析
        if not date_fields_processed and 'publication_date' in data and data['publication_date']:
            if isinstance(data['publication_date'], str):
                dt, date_full, year, month, day, confidence = parse_publication_date(data['publication_date'])
                if dt:
                    data['publication_date'] = dt
                data['publication_date_full'] = date_full
                data['year'] = year
                data['publication_year'] = year
                data['publication_month'] = month
                data['publication_day'] = day
                if 'date_confidence' not in data:
                    data['date_confidence'] = confidence
        
        # 处理JSON字段 - 修复版本
        json_fields = ['authors', 'keywords', 'disciplines', 'tags', 'references', 'cited_by',
                      'related_structures', 'related_scripts', 'cryoem_targets', 'key_findings',
                      'sections_json', 'section_embeddings', 'search_text_blob',
                      'structure_ids', 'structure_metadata']

        for field in json_fields:
            if field in data:
                # 确保值是JSON可序列化的
                field_value = data[field]
                if isinstance(field_value, str):
                    try:
                        # 尝试解析JSON字符串
                        data[field] = json.loads(field_value)
                    except json.JSONDecodeError:
                        # 如果不是JSON，根据字段类型处理
                        if field in ['key_findings', 'sections_json', 'section_embeddings']:
                            # 这些字段应该是字典
                            data[field] = {}
                        elif field == 'authors':
                            # authors可以是字典列表
                            data[field] = [{"name": field_value}]
                        elif field == 'search_text_blob':
                            # search_text_blob是纯文本
                            data[field] = field_value
                        else:
                            data[field] = [field_value]
                elif isinstance(field_value, (list, dict)):
                    # 已经是列表或字典，确保内容可序列化
                    data[field] = field_value
                else:
                    # 其他类型转换为字符串列表
                    data[field] = [str(field_value)]
                
                # 最终检查，确保是JSON可序列化的
                data[field] = _ensure_json_serializable(data[field])
        
        # 创建新条目
        entry = LiteratureEntry(**data)
        session.add(entry)
        session.commit()
        session.refresh(entry)
        
        logger.info(f"✅ 添加文献: ID={entry.id}, 标题='{entry.title[:50]}...'")
        
        # 同步结构数据
        if data.get('cryoem_targets'):
            sync_manager = get_structure_sync_manager()
            if sync_manager.is_available():
                sync_manager.update_structure_mappings(entry.id, data['cryoem_targets'])
        
        return True, entry
        
    except Exception as e:
        session.rollback()
        logger.error(f"❌ 添加文献失败: {e}")
        import traceback
        traceback.print_exc()
        return False, str(e)
    finally:
        session.close()

# ---------- RAG相关函数 ----------
def get_literature_for_embedding(limit: int = 100) -> List[Dict[str, Any]]:
    """获取需要生成嵌入的文献"""
    session = create_literature_session()
    try:
        # 获取已解析但尚未生成嵌入的文献
        from sqlalchemy import and_
        entries = session.query(LiteratureEntry).filter(
            and_(
                LiteratureEntry.status.in_([LiteratureStatus.PARSED, LiteratureStatus.INDEXED]),
                LiteratureEntry.has_vector_embeddings == False
            )
        ).limit(limit).all()
        
        return [entry.to_dict() for entry in entries]
        
    finally:
        session.close()

def update_literature_embedding_status(literature_id: int, 
                                      embedding_model: str,
                                      embedding_dimensions: int,
                                      section_embeddings: Dict = None) -> bool:
    """更新文献嵌入状态"""
    update_data = {
        "has_vector_embeddings": True,
        "embedding_model": embedding_model,
        "embedding_dimensions": embedding_dimensions,
        "last_embedded_at": datetime.now()
    }
    
    if section_embeddings:
        update_data["section_embeddings"] = section_embeddings
    
    return update_literature_entry(literature_id, update_data)

# ---------- 结构同步相关函数 ----------
def sync_all_literature_structures() -> Dict[str, Any]:
    """同步所有文献的结构映射"""
    sync_manager = get_structure_sync_manager()
    if not sync_manager.is_available():
        return {
            "success": False,
            "error": "结构同步管理器不可用",
            "synced": 0,
            "total": 0
        }
    
    try:
        session = create_literature_session()
        
        # 获取所有有cryoem_targets的文献
        entries = session.query(LiteratureEntry).filter(
            LiteratureEntry.cryoem_targets.isnot(None)
        ).all()
        
        total_count = len(entries)
        success_count = 0
        failed_count = 0
        
        logger.info(f"开始同步所有文献结构映射: {total_count} 个文献")
        
        for entry in entries:
            try:
                # 同步结构映射
                success = sync_manager.update_structure_mappings(
                    entry.id,
                    entry.cryoem_targets
                )
                
                if success:
                    success_count += 1
                    logger.debug(f"同步成功: 文献ID={entry.id}")
                else:
                    failed_count += 1
                    logger.warning(f"同步失败: 文献ID={entry.id}")
                    
            except Exception as e:
                failed_count += 1
                logger.error(f"同步文献 {entry.id} 时出错: {e}")
        
        session.close()
        
        return {
            "success": True,
            "total_literature": total_count,
            "synced": success_count,
            "failed": failed_count,
            "message": f"同步完成: 成功 {success_count}, 失败 {failed_count}, 总计 {total_count}"
        }
        
    except Exception as e:
        logger.error(f"同步所有文献结构映射失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "synced": 0,
            "total": 0
        }

def sync_specific_literature_structures(literature_ids: List[int]) -> Dict[str, Any]:
    """同步指定文献的结构映射"""
    sync_manager = get_structure_sync_manager()
    if not sync_manager.is_available():
        return {
            "success": False,
            "error": "结构同步管理器不可用",
            "synced": 0,
            "total": 0
        }
    
    try:
        session = create_literature_session()
        
        results = []
        success_count = 0
        failed_count = 0
        
        logger.info(f"开始同步指定文献结构映射: {len(literature_ids)} 个文献")
        
        for lit_id in literature_ids:
            try:
                entry = session.query(LiteratureEntry).get(lit_id)
                if not entry:
                    results.append({
                        "literature_id": lit_id,
                        "success": False,
                        "error": "文献不存在"
                    })
                    failed_count += 1
                    continue
                
                if not entry.cryoem_targets:
                    results.append({
                        "literature_id": lit_id,
                        "success": True,
                        "message": "没有cryoem_targets数据，跳过"
                    })
                    success_count += 1
                    continue
                
                # 同步结构映射
                success = sync_manager.update_structure_mappings(
                    lit_id,
                    entry.cryoem_targets
                )
                
                if success:
                    results.append({
                        "literature_id": lit_id,
                        "success": True,
                        "structure_ids": sync_manager.extract_structure_ids(entry.cryoem_targets)
                    })
                    success_count += 1
                else:
                    results.append({
                        "literature_id": lit_id,
                        "success": False,
                        "error": "同步失败"
                    })
                    failed_count += 1
                    
            except Exception as e:
                results.append({
                    "literature_id": lit_id,
                    "success": False,
                    "error": str(e)
                })
                failed_count += 1
                logger.error(f"同步文献 {lit_id} 时出错: {e}")
        
        session.close()
        
        return {
            "success": True,
            "total": len(literature_ids),
            "synced": success_count,
            "failed": failed_count,
            "results": results,
            "summary": f"同步完成: 成功 {success_count}, 失败 {failed_count}"
        }
        
    except Exception as e:
        logger.error(f"同步指定文献结构映射失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "total": len(literature_ids),
            "synced": 0,
            "failed": len(literature_ids)
        }

def get_literature_with_structures() -> List[Dict[str, Any]]:
    """获取所有有结构映射的文献"""
    sync_manager = get_structure_sync_manager()
    if not sync_manager.is_available():
        return []
    
    try:
        session = create_literature_session()
        
        # 获取所有有cryoem_targets的文献
        entries = session.query(LiteratureEntry).filter(
            LiteratureEntry.cryoem_targets.isnot(None)
        ).all()
        
        result = []
        for entry in entries:
            structure_ids = sync_manager.extract_structure_ids(entry.cryoem_targets)
            if structure_ids:
                result.append({
                    "literature_id": entry.id,
                    "title": entry.title,
                    "structure_ids": structure_ids,
                    "structure_count": len(structure_ids),
                    "cryoem_targets": entry.cryoem_targets
                })
        
        session.close()
        return result
        
    except Exception as e:
        logger.error(f"获取有结构映射的文献失败: {e}")
        return []

def get_structure_literature_mapping() -> Dict[str, List[int]]:
    """获取结构到文献的映射关系"""
    sync_manager = get_structure_sync_manager()
    if not sync_manager.is_available():
        return {}
    
    try:
        # 使用结构管理器获取映射
        mapping = {}
        
        # 获取所有有结构映射的文献
        literature_list = get_literature_with_structures()
        
        for lit_info in literature_list:
            for struct_id in lit_info["structure_ids"]:
                if struct_id not in mapping:
                    mapping[struct_id] = []
                mapping[struct_id].append(lit_info["literature_id"])
        
        return mapping
        
    except Exception as e:
        logger.error(f"获取结构-文献映射失败: {e}")
        return {}

def validate_structure_sync() -> Dict[str, Any]:
    """验证结构同步状态"""
    sync_manager = get_structure_sync_manager()
    
    status = {
        "structure_sync_available": sync_manager.is_available(),
        "sync_manager_initialized": sync_manager._initialized,
        "has_structure_manager": sync_manager._structure_manager is not None
    }
    
    if sync_manager.is_available():
        try:
            # 检查数据库连接
            stats = sync_manager._structure_manager.get_database_info()
            status["structure_database_stats"] = stats
            
            # 检查映射数量
            literature_with_structs = get_literature_with_structures()
            status["literature_with_structures"] = len(literature_with_structs)
            
            # 检查总映射数
            mapping = get_structure_literature_mapping()
            total_mappings = sum(len(v) for v in mapping.values())
            status["total_structure_mappings"] = total_mappings
            status["unique_structures"] = len(mapping)
            
        except Exception as e:
            status["validation_error"] = str(e)
    
    return status

# ---------- 完全替换功能 ----------
def replace_literature_parsed_data(literature_id: int, parsed_data: Dict[str, Any]) -> bool:
    """
    完全替换文献的解析数据（保留用户手动添加的元数据）
    
    此函数用于重新解析文献时，用新的解析数据完全替换旧的解析数据，
    但保留用户手动添加的字段（如tags、notes等）
    
    Args:
        literature_id: 文献ID
        parsed_data: 从解析器获得的新数据
        
    Returns:
        成功与否
    """
    from core.literature_db import create_literature_session, LiteratureEntry, convert_string_to_status
    import json
    from datetime import datetime
    
    session = create_literature_session()
    try:
        entry = session.query(LiteratureEntry).get(literature_id)
        if not entry:
            logger.error(f"文献不存在: ID={literature_id}")
            return False
        
        logger.info(f"开始完全替换解析数据: ID={literature_id}")
        
        # 1. 记录原有的摘要和重要内容（用于调试）
        original_abstract = entry.abstract
        logger.debug(f"原有摘要长度: {len(original_abstract) if original_abstract else 0}")
        
        # 2. 提取需要更新的字段
        update_fields = {
            # 基础元数据
            'title', 'authors', 'journal', 'year', 'publication_date',
            'volume', 'issue', 'pages', 'publisher', 'doi',
            
            # 解析内容
            'abstract', 'summary', 'key_findings', 'methods', 'results',
            
            # 章节字段
            'introduction', 'discussion', 'conclusions', 'data_availability',
            'sections_json',
            
            # 新增搜索字段
            'search_text_blob',
            
            # 结构ID
            'cryoem_targets',
            
            # 状态信息
            'status', 'parsing_method', 'confidence_score', 'parsed_at',
        }
        
        # 3. 处理combined_metadata（如果存在）
        combined_metadata = parsed_data.get("combined_metadata", {})
        
        # 4. 检查数据来源，优先使用有效的摘要
        abstract_sources = []
        
        # 来源1: combined_metadata 中的 abstract
        if combined_metadata.get('abstract'):
            abstract_sources.append(('combined_metadata', combined_metadata['abstract']))
        
        # 来源2: section_data 中的 abstract
        section_data = parsed_data.get("section_data", {})
        if section_data.get('abstract'):
            abstract_sources.append(('section_data', section_data['abstract']))
        
        # 来源3: sections_json 中的 abstract
        sections_json = combined_metadata.get('sections_json')
        if isinstance(sections_json, dict) and sections_json.get('abstract'):
            abstract_sources.append(('sections_json', sections_json['abstract']))
        elif isinstance(sections_json, str):
            try:
                sections_dict = json.loads(sections_json)
                if isinstance(sections_dict, dict) and sections_dict.get('abstract'):
                    abstract_sources.append(('sections_json_str', sections_dict['abstract']))
            except:
                pass
        
        logger.info(f"找到摘要来源: {[source[0] for source in abstract_sources]}")
        
        # 5. 选择最好的摘要（优先选择非空、较长的摘要）
        best_abstract = None
        if abstract_sources:
            # 按长度排序，选择最长的摘要
            abstract_sources.sort(key=lambda x: len(x[1]) if x[1] else 0, reverse=True)
            best_abstract = abstract_sources[0][1]
            logger.info(f"选择摘要来源: {abstract_sources[0][0]}, 长度: {len(best_abstract)}")
        
        # 6. 逐个字段更新
        for field in update_fields:
            if field in combined_metadata:
                value = combined_metadata[field]
                
                # 特殊字段处理
                if field == 'status':
                    try:
                        value = convert_string_to_status(value)
                    except:
                        value = LiteratureStatus.PARSED
                
                elif field == 'publication_date':
                    # 处理日期字段
                    if isinstance(value, str):
                        dt, date_full, year, month, day, confidence = parse_publication_date(value)
                        value = dt
                        
                        if year:
                            combined_metadata['year'] = year
                            combined_metadata['publication_year'] = year
                        
                        if date_full:
                            combined_metadata['publication_date_full'] = date_full
                        
                        if month:
                            combined_metadata['publication_month'] = month
                        
                        if day:
                            combined_metadata['publication_day'] = day
                    
                    elif isinstance(value, (int, float)):
                        try:
                            value = datetime.fromtimestamp(value)
                        except (ValueError, OSError):
                            value = None
                
                elif field == 'abstract':
                    # 特殊处理摘要：使用我们找到的最好摘要
                    if best_abstract:
                        value = best_abstract
                    elif value and isinstance(value, str) and value.strip():
                        # 如果combined_metadata中有有效的摘要，使用它
                        value = value.strip()
                    else:
                        # 如果新摘要是空的，但原有摘要存在且较长，保留原有摘要
                        if original_abstract and len(original_abstract) > 50:
                            logger.warning(f"新摘要为空或太短，保留原有摘要（长度: {len(original_abstract)}）")
                            value = original_abstract
                        else:
                            value = value or ""
                
                elif field in ['authors', 'keywords', 'key_findings', 'cryoem_targets', 'sections_json', 'search_text_blob']:
                    # 确保JSON字段被正确序列化
                    if isinstance(value, str):
                        try:
                            value = json.loads(value)
                        except:
                            if field in ['key_findings', 'sections_json', 'cryoem_targets']:
                                value = {}
                            elif field == 'authors':
                                value = [{"name": value}]
                            elif field == 'search_text_blob':
                                value = value  # search_text_blob是纯文本
                            else:
                                value = [value]
                
                # 设置字段值
                setattr(entry, field, value)
        
        # 7. 更新章节字段（如果section_data存在）
        for section_field in ['abstract', 'introduction', 'methods', 'results', 
                             'discussion', 'conclusions', 'data_availability', 'search_text_blob']:
            if section_field in section_data:
                value = section_data[section_field]
                # 对于摘要字段，我们已经在上面的特殊处理中设置了
                if section_field == 'abstract' and best_abstract:
                    # 我们已经使用了最好的摘要，跳过设置
                    continue
                elif isinstance(value, str) and value.strip():
                    # 对于其他章节，只更新非空值
                    setattr(entry, section_field, value.strip())
                elif value and not isinstance(value, str):
                    # 如果不是字符串类型，直接设置
                    setattr(entry, section_field, value)
        
        # 8. 更新结构ID（从structure_ids获取）
        # 注意：解析器返回的是structure_ids，不是structure_info
        structure_ids = parsed_data.get("structure_ids", {})
        if structure_ids:
            logger.info(f"更新结构ID: {structure_ids.get('pdb_ids', [])} PDB, {structure_ids.get('emdb_ids', [])} EMDB")
            entry.cryoem_targets = structure_ids
        
        # 9. 更新时间和状态
        entry.parsed_at = datetime.now()
        entry.updated_at = datetime.now()
        entry.status = LiteratureStatus.PARSED
        
        # 10. 记录更新后的摘要状态
        updated_abstract = entry.abstract
        logger.info(f"更新后摘要长度: {len(updated_abstract) if updated_abstract else 0}")
        
        if original_abstract and not updated_abstract:
            logger.error(f"⚠️ 摘要丢失！原有摘要被清空")
        elif original_abstract and updated_abstract and len(updated_abstract) < len(original_abstract) / 2:
            logger.warning(f"⚠️ 摘要可能不完整: 原有长度={len(original_abstract)}, 新长度={len(updated_abstract)}")
        
        # 11. 提交更改
        session.commit()
        
        logger.info(f"✅ 完全替换解析数据成功: ID={literature_id}")
        return True
        
    except Exception as e:
        session.rollback()
        logger.error(f"❌ 替换解析数据失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()

def clear_and_reparse_literature(literature_id: int, pdf_path: str = None) -> Dict[str, Any]:
    """
    清除并重新解析文献（完整工作流）
    
    Args:
        literature_id: 文献ID
        pdf_path: PDF文件路径（如果为None，则使用数据库中的路径）
        
    Returns:
        操作结果
    """
    from core.literature_db import get_literature_entry
    from core.literature_parser import LiteratureParserManager, LiteratureParserConfig
    
    try:
        # 1. 获取文献信息
        entry = get_literature_entry(literature_id)
        if not entry:
            return {"success": False, "error": "文献不存在"}
        
        # 2. 确定PDF路径
        if not pdf_path and entry.main_pdf_path:
            pdf_path = entry.main_pdf_path
        elif not pdf_path:
            return {"success": False, "error": "未提供PDF路径且数据库中没有存储路径"}
        
        # 3. 创建解析管理器
        config = LiteratureParserConfig()
        config.CLEAR_BEFORE_REPARSE = True  # 确保清除旧数据
        parser_manager = LiteratureParserManager(config)
        
        # 4. 重新解析
        logger.info(f"开始重新解析文献: ID={literature_id}")
        parse_result = parser_manager.parse_literature_file(pdf_path, force_reparse=True)
        
        if not parse_result.get("success"):
            return {"success": False, "error": f"解析失败: {parse_result.get('errors', [])}"}
        
        # 5. 完全替换数据库中的数据
        parsed_data = parse_result.get("parsed_data", {})
        success = replace_literature_parsed_data(literature_id, parsed_data)
        
        if success:
            # 获取结构ID用于返回
            structure_ids = parsed_data.get("structure_ids", {})
            return {
                "success": True,
                "literature_id": literature_id,
                "message": f"文献 '{entry.title[:50]}...' 已成功重新解析并更新",
                "structure_ids": structure_ids.get("pdb_ids", []) + structure_ids.get("emdb_ids", []),
                "pdb_count": len(structure_ids.get("pdb_ids", [])),
                "emdb_count": len(structure_ids.get("emdb_ids", []))
            }
        else:
            return {"success": False, "error": "数据库更新失败"}
        
    except Exception as e:
        logger.error(f"❌ 重新解析失败: {e}")
        return {"success": False, "error": str(e)}

# ---------- 初始化入口 ----------
if __name__ == "__main__":
    # 初始化数据库
    result = initialize_literature_database()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # 测试结构同步
    print("\n" + "="*50)
    print("测试结构同步功能")
    print("="*50)
    
    # 验证同步状态
    sync_status = validate_structure_sync()
    print("同步状态:", json.dumps(sync_status, indent=2, ensure_ascii=False))
    
    if sync_status.get("structure_sync_available"):
        print("✅ 结构同步功能可用")
        
        # 测试添加文献并自动同步结构
        test_data = {
            "title": "Test Structure Sync Article",
            "authors": [{"name": "Test Author"}],
            "cryoem_targets": {
                "pdb_ids": ["7EWL", "7SHE"],
                "emdb_ids": ["EMD-12345"]
            }
        }
        
        print("\n测试添加文献并自动同步结构...")
        success, entry = add_literature_entry(test_data)
        
        if success:
            print(f"✅ 添加文献成功: ID={entry.id}")
            
            # 测试更新文献结构
            print("\n测试更新文献结构...")
            update_data = {
                "cryoem_targets": {
                    "pdb_ids": ["7EWL", "6LU7"],  # 移除7SHE，添加6LU7
                    "emdb_ids": ["EMD-12345"]
                }
            }
            
            update_success = update_literature_entry(entry.id, update_data)
            if update_success:
                print("✅ 更新文献结构成功")
            
            # 测试删除文献
            print("\n测试删除文献并清理结构映射...")
            delete_result = delete_literature_entry(entry.id)
            print(f"删除结果: {delete_result.get('success', False)}")
            
        else:
            print("❌ 添加文献失败")
    else:
        print("⚠️ 结构同步功能不可用")


def migrate_add_user_id_columns():
    """迁移数据库 - 为现有表添加user_id列"""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        # 需要添加user_id列的表
        tables_to_migrate = [
            'literature_entries',
            'literature_appendices',
            'literature_notes',
            'qa_chat_history',
            'literature_collections'
        ]

        with engine.connect() as conn:
            for table_name in tables_to_migrate:
                # 检查表是否存在
                if table_name not in inspector.get_table_names():
                    logger.warning(f"表 {table_name} 不存在，跳过")
                    continue

                # 检查列是否存在
                columns = [col['name'] for col in inspector.get_columns(table_name)]
                if 'user_id' not in columns:
                    try:
                        # 添加user_id列
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE"))
                        conn.commit()
                        logger.info(f"✅ 已为表 {table_name} 添加 user_id 列")
                    except Exception as e:
                        logger.warning(f"为表 {table_name} 添加 user_id 列失败: {e}")
                        conn.rollback()

            # 检查users表是否存在，不存在则创建
            if 'users' not in inspector.get_table_names():
                logger.info("users 表不存在，将通过 Base.metadata.create_all 创建")

    except Exception as e:
        logger.error(f"数据库迁移出错: {e}")


def check_and_add_missing_columns():
    """检查并添加缺失的数据库字段"""
    try:
        from sqlalchemy import inspect
        
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('literature_entries')]
        
        # 预期的列
        expected_columns = {
            'search_text_blob': 'TEXT'
        }
        
        for column_name, column_type in expected_columns.items():
            if column_name not in columns:
                logger.info(f"添加缺失的字段: {column_name}")
                with engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE literature_entries ADD COLUMN {column_name} {column_type}"))
                    conn.commit()
                    
    except Exception as e:
        logger.warning(f"检查字段时出错: {e}")