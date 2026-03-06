"""
API Routes Package
"""
# Import blueprints from individual modules
from .literature import bp as literature_bp
from .structure import bp as structure_bp
from .qa import bp as qa_bp
from .upload import bp as upload_bp
from .utils import bp as utils_bp
from .config import bp as config_bp
from .feishu import bp as feishu_bp
from .evaluation import bp as evaluation_bp

# Handle optional search module (requires faiss)
try:
    from .search import bp as search_bp
    HAS_SEARCH = True
except (ImportError, ModuleNotFoundError):
    HAS_SEARCH = False
    search_bp = None

__all__ = ['literature_bp', 'structure_bp', 'qa_bp', 'upload_bp', 'utils_bp', 'config_bp', 'feishu_bp', 'search_bp', 'evaluation_bp', 'HAS_SEARCH']
