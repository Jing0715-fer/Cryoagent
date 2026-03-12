"""
Flask Application Configuration
"""
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Flask configuration
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'cryoagent-pro-dev-key')
    DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'

    # Database paths - use data directory
    _base_dir = os.path.dirname(os.path.abspath(__file__))
    _data_dir = os.path.join(_base_dir, 'data')
    LITERATURE_DB = os.path.join(_data_dir, 'literature.db')
    LITERATURE_INDEX_DB = os.path.join(_data_dir, 'literature_index.db')
    STRUCTURE_DB = os.path.join(_data_dir, 'structure_offline.db')

    # Cache directories
    LITERATURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'literature')
    LITERATURE_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'literature_cache')
    STRUCTURE_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'structure_cache')
    LITERATURE_INDICES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'literature_indices')

    # Upload configuration
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB
    ALLOWED_EXTENSIONS = {'pdf'}

    # API configuration
    CHAT_MODEL = os.environ.get('CHAT_MODEL', 'deepseek-chat')
    EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'deepseek-embed')
    EMBEDDING_DIMENSION = int(os.environ.get('EMBEDDING_DIMENSION', '1536'))

    # Vector search engine configuration ('lancedb')
    VECTOR_ENGINE = os.environ.get('VECTOR_ENGINE', 'lancedb')

    # LanceDB RAG configuration
    LANCEDB_PATH = os.environ.get('LANCEDB_PATH', os.path.join(_data_dir, 'lancedb'))
    LANCEDB_VECTOR_DIM = int(os.environ.get('LANCEDB_VECTOR_DIM', '384'))

    # Reranker configuration
    RERANKER_MODEL = os.environ.get('RERANKER_MODEL', 'jina-reranker-v1-base-en')
    RERANKER_API_KEY = os.environ.get('JINA_API_KEY')
    USE_RERANK = os.environ.get('USE_RERANK', 'True').lower() == 'true'

    # Hybrid search configuration
    FUSION_STRATEGY = os.environ.get('FUSION_STRATEGY', 'rrf')
    VECTOR_WEIGHT = float(os.environ.get('VECTOR_WEIGHT', '0.5'))
    BM25_WEIGHT = float(os.environ.get('BM25_WEIGHT', '0.5'))

    # Session configuration
    USE_SESSION = os.environ.get('USE_SESSION', 'True').lower() == 'true'
    MAX_HISTORY = int(os.environ.get('MAX_HISTORY', '10'))

    # Adaptive retrieval
    USE_ADAPTIVE = os.environ.get('USE_ADAPTIVE', 'True').lower() == 'true'

    @classmethod
    def get_upload_folder(cls):
        os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)
        return cls.UPLOAD_FOLDER
