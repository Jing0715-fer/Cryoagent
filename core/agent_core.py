# agent_core.py - CryoAgent Pro - 支持文献和结构数据的AI核心模块（性能优化版）
import os, json, logging, re, hashlib, time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from datetime import datetime
from functools import lru_cache
import numpy as np

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- 统一配置加载 ----------
# Since core is inside flask_app, look for config in parent directory
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ai_config.json')


def load_ai_config():
    """Load AI configuration from UI config file"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load config from {CONFIG_FILE}: {e}")
    return {}


def get_ai_config():
    """获取AI配置 - 优先使用UI配置文件，fallback到环境变量"""
    config = load_ai_config()

    # 如果配置文件中有完整的配置，直接使用
    if config.get('api_key'):
        return config

    # 否则尝试从环境变量读取（向后兼容）
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY")
    api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    chat_model = os.getenv("CHAT_MODEL", "deepseek-chat")

    return {
        'api_provider': 'openai',
        'api_base': api_base,
        'api_key': api_key,
        'chat_model': chat_model
    }


# 初始化配置
AI_CONFIG = get_ai_config()

# 提取配置值
API_PROVIDER = AI_CONFIG.get('api_provider', 'openai')
API_BASE = AI_CONFIG.get('api_base', 'https://api.deepseek.com')
API_KEY = AI_CONFIG.get('api_key', '')
CHAT_MODEL = AI_CONFIG.get('chat_model', 'deepseek-chat')

# 检查是否配置成功
if not API_KEY:
    logger.warning("⚠️ AI API Key 未配置，AI功能将受限")


def get_unified_client():
    """获取统一的AI客户端"""
    from openai import OpenAI

    if API_PROVIDER == 'anthropic':
        import anthropic
        import os

        # MiniMax 需要设置正确的base_url
        if 'minimaxi' in API_BASE.lower():
            # 使用 base_url 参数而不是环境变量
            return anthropic.Anthropic(
                api_key=API_KEY,
                base_url=API_BASE,
                timeout=30.0
            )
        else:
            return anthropic.Anthropic(api_key=API_KEY, timeout=30.0)
    else:
        return OpenAI(api_key=API_KEY, base_url=API_BASE, timeout=30.0)


def create_chat_completion(messages, temperature=0.3, max_tokens=None, timeout=20, json_mode=False):
    """统一的聊天完成接口 - 支持 OpenAI 和 Anthropic"""
    try:
        if API_PROVIDER == 'anthropic':
            # Anthropic 格式转换
            client = get_unified_client()
            system_msg = None
            user_msgs = []

            for msg in messages:
                if msg['role'] == 'system':
                    system_msg = msg['content']
                else:
                    user_msgs.append(msg['content'])

            user_content = '\n'.join(user_msgs)

            # Anthropic 必须有 max_tokens
            if not max_tokens:
                max_tokens = 1024

            kwargs = {
                'model': CHAT_MODEL,
                'messages': [{"role": "user", "content": user_content}],
                'temperature': temperature,
                'max_tokens': max_tokens,
                'timeout': timeout
            }
            if system_msg:
                kwargs['system'] = system_msg

            response = client.messages.create(**kwargs)

            # 正确处理响应（可能包含 ThinkingBlock）
            for block in response.content:
                if hasattr(block, 'text'):
                    return block.text
            return ""
        else:
            # OpenAI 格式
            client = get_unified_client()
            kwargs = {
                'model': CHAT_MODEL,
                'messages': messages,
                'temperature': temperature,
                'timeout': timeout
            }
            if max_tokens:
                kwargs['max_tokens'] = max_tokens
            if json_mode:
                kwargs['response_format'] = {"type": "json_object"}

            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
    except Exception as e:
        logger.error(f"API调用失败: {e}")
        raise


# 初始化客户端（向后兼容）
deepseek_client = None
if API_KEY:
    try:
        from openai import OpenAI
        deepseek_client = OpenAI(api_key=API_KEY, base_url=API_BASE, timeout=30.0)
    except Exception as e:
        logger.error(f"Failed to initialize client: {e}")

# ---------- 关键修正：先定义变量，再尝试导入 ----------
# 1. 先给 HAS_LLAMA_INDEX 一个默认值
HAS_LLAMA_INDEX = False

# 2. 尝试导入 LlamaIndex
try:
    from llama_index.core import Settings, Document, VectorStoreIndex, StorageContext, load_index_from_storage
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.core.schema import TextNode
    from llama_index.llms.openai import OpenAI as LlamaOpenAI

    HAS_LLAMA_INDEX = True  # 导入成功，更新为 True
    logger.info("✅ LlamaIndex可用")

    # 只有在导入成功后才进行配置（使用新的配置系统）
    if API_KEY:
        Settings.llm = LlamaOpenAI(
            api_key=API_KEY,
            base_url=API_BASE,
            model=CHAT_MODEL,
            temperature=0.1,
            timeout=30.0
        )
        logger.info("✅ LlamaIndex配置完成")
    else:
        logger.warning("⚠️ API Key未配置，LlamaIndex功能受限")

except ImportError:
    # 保持 HAS_LLAMA_INDEX = False（默认值）
    logger.warning("⚠️ 未安装LlamaIndex，部分高级功能受限")
except Exception as e:
    logger.warning(f"⚠️ LlamaIndex导入或配置失败: {e}")
    HAS_LLAMA_INDEX = False  # 确保变量被设置

# ---------- 嵌入模型管理器 ----------
class ContextEnricher:
    """上下文增强器：在构建 Prompt 前挖掘隐藏的实验细节"""
    
    def __init__(self, literature_manager=None):
        self.literature_manager = literature_manager
        self.experiment_params_db = {}  # 存储已知的实验参数 (如 Buffer pH)
        # 常见实验参数关键词库
        self.param_keywords = [
            'hepes', 'ph 7.5', 'ph 8.0', 'tris', 'mops', 
            'kda', 'edta', 'egta', 'nacl', 'mgcl2', 'cacl2',
            'temperature', '37c', 'room temp', '4c', 'dtt', 
            'voltage', '100v', '180v', '240v', 
            'centrifuge', '15000g', '12000rpm', '18000rpm',
            'size exclusion', 'superdex 75', 'superdex 200', 
            'tag', 'his6', 'strep', 'flag', 'myc'
        ]
    
    def extract_methods_parameters(self, full_text: str) -> Dict[str, Any]:
        """从全文中提取实验参数"""
        params = {}
        
        # 查找具体的数值模式
        patterns = [
            r'(?:\s*)?(?:buffer|缓冲液)\s*(?:=|：)\s*([\d\.]+\s*[mM|uM]*)(?:ph\s*[\d\.]+\s*)',  # Buffer pH
            r'(\d+\s*)(?:°C|celsius)\s*',  # 温度
            r'(\d+\s*)(?:V|v)(?:\s*)',  # 电压
            r'(\d+)(?:,000|000)\s*(?:g|rpm|G)\b',  # 离心
            r'(?:size\s*exclusion\s*|分子筛)\s*(?:\d+\s*kDa|kDa|MW\s*:?\s*)',  # 分子筛
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, full_text, re.IGNORECASE)
            if matches:
                key = pattern.strip('(?:\\s|buffer|缓冲液|°C|celsius|V|v|g|rpm|G|kDa|MW|size exclusion|分子筛').lower().strip()
                params[key] = params.get(key, []) + [m.group(1) for m in matches]
        
        # 归一化重复的参数名
        for key, values in params.items():
            params[key] = list(set(values))  # 去重并保留原始顺序
        
        logger.info(f"从文本中提取到 {len(params)} 个实验参数: {list(params.keys())}")
        return params
    
    def enrich_literature_context(self, literature_data: Dict) -> str:
        """为文献上下文添加已知实验参数"""
        # 这里可以从 literature_data 的 custom_fields 或其他扩展字段读取预存的参数
        # 暂时硬编码一些示例
        known_params = self.experiment_params_db.get(literature_data.get('id'), {})
        if known_params:
            param_text = "\n\n【已知实验参数补充】\n"
            for key, values in known_params.items():
                param_text += f"- {key}: {', '.join(map(str, values))}\n"
            return param_text
        return ""

class StructureDeepMiner:
    """结构深度挖掘器：深入解析 entities 表，提取链组成和相互作用"""
    
    def __init__(self, structure_db=None):
        # 修正：优先使用传入的 structure_db，如果没有则尝试内部初始化
        if structure_db:
            self.structure_db = structure_db
        else:
            try:
                from structure_database import EnhancedStructureManager
                self.structure_db = EnhancedStructureManager()
                logger.info("✅ 结构离线数据库管理器在内部初始化完成")
            except Exception as e:
                logger.warning(f"结构离线数据库管理器初始化失败: {e}")
                self.structure_db = None
    
    def analyze_chain_composition(self, entities: List[Dict]) -> str:
        """分析链的组成和比例 - 强制输出所有链（无序列也列出）"""
        if not entities:
            return ""
        
        # --- 修改：统计所有实体（不管有没有序列） ---
        total_entities = len(entities)
        total_aa_count = 0
        chain_info = []
        
        for idx, ent in enumerate(entities, start=1): # 从1开始编号
            sequence = ent.get('sequence', '')
            
            # 处理 List 类型的 sequence
            if isinstance(sequence, list):
                sequence = "".join(sequence)
            
            # --- 修改：不再因为有序列才处理 ---
            # 即使 sequence 是空的，也要处理
            
            chain_ids = ent.get('chain_ids')
            if isinstance(chain_ids, list) and len(chain_ids) > 0:
                chain_id = str(chain_ids[0])
            elif isinstance(chain_ids, str):
                chain_id = chain_ids
            else:
                # 如果连 chain_id 都没有，给一个临时编号
                chain_id = f"Entity_{idx}"
            
            mol_name = ent.get('molecule_name', 'Unknown')
            if isinstance(mol_name, list):
                mol_name = ", ".join(str(m) for m in mol_name)
            elif not isinstance(mol_name, str):
                mol_name = str(mol_name)
            
            if sequence:
                seq_len = len(sequence)
                total_aa_count += seq_len
                # 展示完整序列
                chain_info.append(f"[{idx}] Chain {chain_id} ({mol_name}): {sequence} ({seq_len} aa)")
            else:
                # --- 修复：没有序列的情况 ---
                # 明确标注“无序列”，防止 LLM 以为该链不存在
                chain_info.append(f"[{idx}] Chain {chain_id} ({mol_name}): [无序列数据 / No sequence]")

        if not chain_info:
            return ""
        
        # 构建“强制全部”的引导语
        analysis_text = "\n\n【链组成分析 - 全部实体列表】\n"
        analysis_text += f"**重要**：检测到 {total_entities} 个实体。以下是完整列表：\n"
        analysis_text += "\n".join(chain_info)
        
        if total_aa_count > 0:
            analysis_text += f"\n\n说明：其中 {len([c for c in chain_info if '[无序列' not in c])} 个实体包含序列信息。"

        return analysis_text
    
    def extract_interaction_interfaces(self, entities: List[Dict]) -> str:
        """提取可能的相互作用界面 - 修复版：处理 molecule_name 为 list 的情况"""
        if not entities:
            return ""
        
        interface_text = "\n\n【相互作用界面分析】\n"
        
        # 分析链的类型（受体、配体、辅助因子等）
        receptors = []
        ligands = []
        aux_factors = []
        
        for ent in entities:
            # --- 修复：安全获取并转换 molecule_name ---
            # 数据库中可能存储为 list (如 ['TCR'])，需要处理
            mol_name = ent.get('molecule_name', 'Unknown')
            if isinstance(mol_name, list):
                # 如果是列表，用逗号连接
                mol_name = ", ".join(str(m) for m in mol_name)
            elif not isinstance(mol_name, str):
                mol_name = str(mol_name)
            
            mol_name_upper = mol_name.upper()
            
            # --- 修复：安全获取 chain_id ---
            chain_ids = ent.get('chain_ids')
            if isinstance(chain_ids, list) and len(chain_ids) > 0:
                chain_id = str(chain_ids[0])
            elif isinstance(chain_ids, str):
                chain_id = chain_ids
            else:
                chain_id = "?"
            
            # 分类逻辑
            if 'RECEPTOR' in mol_name_upper or 'TCR' in mol_name_upper or 'B2M' in mol_name_upper:
                receptors.append(f"{chain_id} ({mol_name})")
            elif 'LIGAND' in mol_name_upper or 'PEPTIDE' in mol_name_upper or 'CD3' in mol_name_upper or 'B2M' in mol_name_upper:
                ligands.append(f"{chain_id} ({mol_name})")
            else:
                aux_factors.append(f"{chain_id} ({mol_name})")
        
        if receptors:
            interface_text += f"- 受体链: {', '.join(receptors)}\n"
        if ligands:
            interface_text += f"- 配体链: {', '.join(ligands)}\n"
        if aux_factors:
            interface_text += f"- 辅助因子: {', '.join(aux_factors)}\n"
        
        return interface_text

class EmbeddingManager:
    """嵌入模型管理器"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.model_name = self.config.get('embedding_model', 'all-MiniLM-L6-v2')
        self.dimension = self.config.get('embedding_dimension', 384)
        self.use_api = self.config.get('use_api_for_embedding', False)
        self.enable_api_embedding = self.config.get('enable_api_embedding', False)
        
        self.model = None
        
        # 如果是本地模型，尝试加载
        if not self.use_api:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"正在加载本地嵌入模型: {self.model_name}")
                self.model = SentenceTransformer(self.model_name)
                logger.info(f"✅ 本地嵌入模型加载成功: {self.model_name}")
            except ImportError as e:
                logger.warning(f"无法加载sentence-transformers: {e}")
                self.model = None
            except Exception as e:
                logger.error(f"加载嵌入模型失败: {e}")
                self.model = None
        
        logger.info(f"嵌入管理器初始化完成: 模型={self.model_name}, 维度={self.dimension}")
    
    def embed_text(self, text: str) -> np.ndarray:
        """获取文本嵌入向量"""
        try:
            if self.use_api and self.enable_api_embedding:
                # 使用API获取嵌入
                return self._embed_with_api(text)
            elif self.model:
                # 使用本地模型
                return self.model.encode(text)
            else:
                # 回退：生成随机向量
                logger.warning("使用随机向量作为回退")
                return np.random.randn(self.dimension).astype(np.float32)
        except Exception as e:
            logger.error(f"生成文本嵌入失败: {e}")
            return np.random.randn(self.dimension).astype(np.float32)
    
    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[np.ndarray]:
        """批量获取嵌入向量"""
        try:
            if self.use_api and self.enable_api_embedding:
                # 批量使用API（注意：这里可能需要调整）
                embeddings = []
                for text in texts:
                    embeddings.append(self._embed_with_api(text))
                return embeddings
            elif self.model:
                # 使用本地模型批量处理
                return self.model.encode(texts, batch_size=batch_size)
            else:
                # 回退：生成随机向量
                return [np.random.randn(self.dimension).astype(np.float32) for _ in texts]
        except Exception as e:
            logger.error(f"批量生成嵌入失败: {e}")
            return [np.random.randn(self.dimension).astype(np.float32) for _ in texts]
    
    def _embed_with_api(self, text: str) -> np.ndarray:
        """使用API获取嵌入（需要实现）"""
        # 这里需要根据实际的API实现
        # 暂时返回随机向量
        logger.warning("API嵌入功能未完全实现")
        return np.random.randn(self.dimension).astype(np.float32)
    
    def get_model_info(self) -> Dict[str, Any]:
        """获取嵌入模型信息"""
        return {
            'model_name': self.model_name,
            'dimension': self.dimension,
            'use_api': self.use_api,
            'enable_api_embedding': self.enable_api_embedding,
            'model_loaded': self.model is not None,
            'has_api_embedding': self.enable_api_embedding
        }
# ---------- 嵌入模型配置 ----------
EMBEDDING_CONFIG = {
    'embedding_model': os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
    'embedding_dimension': int(os.getenv("EMBEDDING_DIMENSION", "384")),
    'use_api_for_embedding': os.getenv("USE_API_FOR_EMBEDDING", "false").lower() == "true",
    'enable_api_embedding': os.getenv("ENABLE_API_EMBEDDING", "false").lower() == "true"
}

# 初始化嵌入管理器
embedding_manager = EmbeddingManager(EMBEDDING_CONFIG)

# ---------- 导出函数 ----------
def get_text_embedding(text: str) -> np.ndarray:
    """获取文本嵌入向量（外部调用接口）"""
    return embedding_manager.embed_text(text)

def get_batch_embeddings(texts: List[str], batch_size: int = 32) -> List[np.ndarray]:
    """批量获取嵌入向量"""
    return embedding_manager.embed_batch(texts, batch_size)

def get_embedding_model_info() -> Dict[str, Any]:
    """获取嵌入模型信息"""
    return embedding_manager.get_model_info()

# ---------- 导出其他重要变量 ----------
# 确保 HAS_AGENT 也被正确定义
HAS_AGENT = True

# ---------- 翻译功能 ----------

def translate_question_to_english(question: str) -> str:
    """
    将中文问题翻译成英文，用于向量搜索
    """
    if not question.strip():
        return question
    
    # 检测是否主要是中文
    def is_mostly_chinese(text):
        chinese_chars = len([c for c in text if '\u4e00' <= c <= '\u9fff'])
        return chinese_chars / max(len(text), 1) > 0.3
    
    # 如果主要是中文，翻译成英文
    if is_mostly_chinese(question):
        try:
            # 使用DeepSeek进行翻译
            system_prompt = """You are a professional translator specialized in scientific literature and protein structure research.
Translate Chinese questions into English for vector search in a literature database.

Requirements:
1. Keep protein names, PDB/EMDB IDs, and technical terms in English
2. Maintain the original meaning and intent
3. Make it suitable for vector similarity search
4. Keep it concise and clear"""

            content = create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Translate this question to English: {question}"}
                ],
                temperature=0.1,
                max_tokens=200
            )

            english_question = content.strip()
            logger.info(f"翻译结果: '{question}' -> '{english_question}'")
            return english_question
            
        except Exception as e:
            logger.error(f"翻译问题失败: {e}")
            # 如果翻译失败，返回原始问题
            return question
    else:
        # 如果主要是英文，直接返回
        return question

# ---------- AI增强搜索函数 ----------
# ========== Prompt 策略定义系统 ==========

# 1. 定义不同意图对应的 System Prompt
PROMPT_STRATEGIES = {

    # 类型A：结构参数查询
    "structure_quality": """你是一个专注于结构生物学数据解析的专家。
你的唯一任务是：根据提供的【结构数据库详情】回答用户关于结构参数的问题。

**回答规则**：
1. **必须用中文回答**，仅蛋白质名称、结构ID、技术缩写保留英文
2. **绝对准确**：只使用数据库中提供的数值（分辨率、B因子、R值等）。不要推测或参考摘要。
3. **格式清晰**：
   - 结构1: PDB ID/EMDB ID | 标题 | 分辨率 | 方法
   - 结构2: PDB ID/EMDB ID | 标题 | 分辨率 | 方法
4. **无需推理**：不要解释"为什么"这个分辨率高，只列出数据即可。
5. **对比分析**：如果问区别，请基于分辨率、方法、亚基数量进行客观对比。
6. **禁止**：不要编造不存在的 PDB ID 或分辨率值。
""",

    # 类型B：实验流程/方法总结
    "experimental_procedure": """你是一个实验生物学方法学助手。
你的任务是：根据【文献原文深度检索】中的 Methods 章节，详细总结实验流程。

**回答规则**：
1. **必须用中文回答**，仅蛋白质名称、结构ID、技术缩写保留英文
2. **按步骤总结**：请以清晰的步骤列表回答。
   - 1. 样品制备（来源、表达系统、载体）
   - 2. 纯化过程（色谱柱类型、缓冲液配方）
   - 3. 样品制备（负染浓度、电压、温度、冰冻时间）
   - 4. 数据收集（设备型号、软件、处理参数）
3. **提取参数**：务必列出具体的数值（如 4°C, 100 mM NaCl, 300 kV）。这些参数往往是回答的重点。
4. **逻辑顺序**：保持与原文 Methods 章节一致的先后顺序。
5. **来源标注**：引用具体的"原文片段"编号或关键词以佐证你的总结。
6. **禁止**：不要引用摘要中的结论，只关注方法细节。
""",

    # 类型C：分子实体与序列
    "molecular_entity": """你是一位资深的分子生物学家。
你的任务是：根据提供的【结构深度挖掘】详细描述分子实体信息。

**强制性回答要求（必须严格遵守）**：
1. **必须用中文回答**，仅蛋白质/基因名称、结构ID、技术缩写保留英文
2. **必须列出所有实体（绝对禁止遗漏）**：
   - 请务必列出【链组成分析】中标记的**每一个**实体（链），序号从 [1] 到 [N]。
   - 即使某个实体标记为"[无序列数据]"，你必须在回答中提及它，说明"该实体无序列"。
   - **如果数据库检测到 6 个实体，你必须输出 6 个实体，不能只输出 2 个**。
   - **必须包含所有链，无论它们是否被认为是TCR的核心组成部分**。
   - **默认行为**：当用户询问蛋白序列时，默认包含所有相关实体的序列，无需用户特别说明。
3. **完整序列展示**：
   - 对于每一条链，如果存在序列，请提供完整的氨基酸序列（一字符代码）。
   - 不要截断序列。
4. **格式要求**：
   - 请按照数据库中[序号]的顺序，逐一列出每条链。
   - 每条链都必须有独立的标题和序列展示。

**禁止**：
- **绝对禁止遗漏**任何在【链组成分析】中出现的实体。
- **禁止**只选择与TCR直接相关的链而忽略其他链（如CD3亚基）。
- 禁止只回答"由两个主要亚基组成"而不列出具体列表。
- **禁止**在回答中使用"主要"、"核心"等选择性词汇，必须列出所有实体。
- **禁止**根据通用知识或假设来省略实体，必须严格基于提供的【结构深度挖掘】信息。
""",

    # 类型D：生物机制与功能
    "biological_mechanism": """你是一个结构生物机制分析师。
你的任务是：综合【结构数据库详情】、【文献发现与方法学】以及【原文片段】解释生物学机制。

**回答规则**：
1. **必须用中文回答**，仅蛋白质/基因名称、结构ID、技术缩写保留英文
2. **结合证据**：不要只凭空谈。结构数据（如相互作用界面）和生物学发现（如功能丧失）结合。
3. **推理链**：解释"结构A（如二聚体）如何导致功能B（如无活性）"。
4. **专业性**：使用术语（如"变构效应"、"别构调节"、"空间位阻"）。
5. **基于上下文**：解释必须基于提供的文献，不要使用你的通用知识（除非文献明确提到）。
6. **格式**：使用"发现 -> 结构基础 -> 功能推论"的逻辑结构。
""",

    # 默认：一般性搜索
    "general_search": """你是一个科研助手。
你的任务是：基于【摘要】和【关键发现】提供全面的回答。

**回答规则**：
1. **必须用中文回答**，仅蛋白质/基因名称、结构ID、技术缩写保留英文
2. **简洁全面**：覆盖摘要的主要内容。
3. **逻辑结构**：引言 -> 发现 -> 结论。
4. **引用**：使用"文献X指出..."的句式。
5. **客观**：避免过于主观的评价。
"""
}

# 2. 意图匹配逻辑（基于关键词和上下文）
def classify_question_intent(question: str, structure_ids_found: list) -> str:
    """
    简单的意图分类器
    """
    q_lower = question.lower()
    
    # 1. 实验方法 (优先级最高，因为通常问题最详细)
    method_keywords = ['怎么', '如何', '步骤', '制备', '表达', '纯化', '实验', '流程', '方法', '制备过程', '步骤', '怎么做']
    if any(kw in q_lower for kw in method_keywords):
        return "experimental_procedure"
    
    # 2. 分子实体 (序列、链、突变)
    entity_keywords = ['序列', 'sequence', '链', 'chain', '突变', 'mutation', '氨基酸', 'aa', 'domain', '多肽', '配体']
    if any(kw in q_lower for kw in entity_keywords):
        return "molecular_entity"
    
    # 3. 结构参数
    quality_keywords = ['分辨率', 'resolution', 'b factor', 'r值', '质量', 'map', '方法', '参数', '多少埃', '多高', '精度']
    if any(kw in q_lower for kw in quality_keywords):
        return "structure_quality"
    
    # 4. 机制功能
    mechanism_keywords = ['机制', '为什么', '原理', '作用', '功能', '信号', '结合', '如何激活', '为什么不能', '区别', '不同']
    if any(kw in q_lower for kw in mechanism_keywords):
        return "biological_mechanism"
    
    # 默认
    return "general_search"

def search_literature_with_ai_context(
    question: str, 
    literature_manager=None, 
    structure_db=None,  # --- 修改1: 新增参数 ---
    index_manager=None,
    enable_fulltext_rag: bool = True,
    enable_rerank: bool = True,
    conversation_context: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """
    重构版：智能文献检索与上下文构建 (支持独立 structure_db)
    """
    try:
        from literature_agent import simple_qa_search
    except ImportError:
        simple_qa_search = None
        logger.warning("无法导入 simple_qa_search")
        
    logger = logging.getLogger(__name__)
    start_time = time.time()
    
    # --- 新增：提前处理会话上下文 ---
    enhanced_question = question
    context_entities = {}
    
    if conversation_context:
        logger.info(f"🔄 从会话历史中提取上下文，共 {len(conversation_context)} 条消息")
        
        # 提取最近的几条消息作为上下文
        recent_context = conversation_context[-5:]  # 最多使用最近5条消息
        context_text = []
        
        for msg in recent_context:
            if msg.get("content"):
                context_text.append(msg.get("content", ""))
        
        if context_text:
            # 构建增强的问题，包含历史上下文
            context_summary = " ".join(context_text)
            enhanced_question = f"{question} (参考上下文: {context_summary[:500]}...)"
            logger.info(f"📝 增强后的问题: {enhanced_question[:200]}...")
    
    # --- 修改2: 初始化 structure_db (优先级：参数传入 > 内部导入) ---
    if not structure_db:
        try:
            # 尝试导入 EnhancedStructureManager (假设这是您的结构数据库类名)
            from structure_database import EnhancedStructureManager
            structure_db = EnhancedStructureManager()
            logger.info("✅ 内部初始化结构数据库")
        except ImportError:
            logger.warning("⚠️ 无法导入 structure_database，结构深度分析功能将受限。")
            structure_db = None
        except Exception as e:
            logger.error(f"❌ 初始化结构数据库失败: {e}")
            structure_db = None
    
    # 1. 初始化辅助器
    context_enricher = ContextEnricher(literature_manager)
    # 使用局部变量 structure_db
    structure_miner = StructureDeepMiner(structure_db) if structure_db else None
    
    # 2. 翻译和预处理问题
    english_question = translate_question_to_english(enhanced_question)  # 使用增强的问题
    question_lower = english_question.lower()
    
    # 3. 提取有意义的关键词
    from literature_agent import extract_keywords
    raw_keywords = extract_keywords(english_question)
    logger.info(f"提取的关键词: {raw_keywords}")
    
    # 过滤有意义的关键词（移除通用词语）
    meaningful_keywords = []
    common_words = {'what', 'they', 'study', 'literature', 'respectively', 'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'must', 'each', 'investigate', 'every', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'what', 'which', 'who', 'whom', 'whose', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'either', 'neither', 'few', 'many', 'more', 'most', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'should', 'now', 'these', 'those'}
    
    for keyword in raw_keywords:
        if keyword not in common_words and len(keyword) > 2:
            meaningful_keywords.append(keyword)
    
    logger.info(f"过滤后的有意义关键词: {meaningful_keywords}")
    
    # 3. 意图分类（增强版）
    intent_type = "general_search"  # 默认
    
    if any(kw in question_lower for kw in ['怎么', '如何', '步骤', 'process', '制备', '表达', '纯化', '实验', '流程', '方法', '制备过程']):
        intent_type = "experimental_procedure"
        logger.info(f"🎯 意图识别: 实验流程")
    
    elif any(kw in question_lower for kw in ['序列', 'sequence', '链', 'chain', '突变', 'mutation', 'domain', '结构域']):
        intent_type = "molecular_entity"
        logger.info(f"🧬 意图识别: 分子实体")
    
    elif any(kw in question_lower for kw in ['分辨率', 'resolution', '方法', 'method', '参数', '多少埃', '精度', 'r值', 'b因子', 'rmsd', 'quality']):
        intent_type = "structure_quality"
        logger.info(f"📊 意图识别: 结构质量")
    
    elif any(kw in question_lower for kw in ['机制', '为什么', '原理', '作用', '功能', '信号', '结合', '如何激活', '为何不能', '区别', '不同', '差异', '变构']):
        intent_type = "biological_mechanism"
        logger.info(f"⚙️ 意图识别: 生物学机制")
    
    # 添加详细日志，记录意图分类结果和使用的system_prompt
    logger.info(f"🔍 意图分类详情:")
    logger.info(f"   问题: {question}")
    logger.info(f"   增强问题: {enhanced_question[:100]}...")
    logger.info(f"   识别的意图类型: {intent_type}")
    # 修复f-string中不能包含反斜杠的问题
    prompt = PROMPT_STRATEGIES.get(intent_type, {})
    prompt_first_line = prompt.split('\n')[0][:100] if prompt else ''
    logger.info(f"   使用的系统提示词: {prompt_first_line}...")
    
    # 4. 获取详细文献信息 & 结构ID
    all_literature = []
    detailed_literature = []
    all_structure_ids_to_fetch = set()
    needs_fallback_search = True
    vector_search_performed = False
    
    try:
        # 4.1 对于结构质量和分子实体类型的问题，优先使用向量搜索
        if (intent_type == "structure_quality" or intent_type == "molecular_entity") and literature_manager and hasattr(literature_manager, 'unified_vector_indexer'):
            logger.info(f"🚀 对于 {intent_type} 类型问题，优先使用向量搜索")
            
            # 构建向量搜索查询
            vector_query = " ".join(meaningful_keywords)
            logger.info(f"🔍 执行向量搜索: 查询 '{vector_query}'")
            
            # 执行向量搜索
            try:
                # 搜索多种实体类型，包括结构和文献
                vector_results = literature_manager.unified_vector_indexer.search(
                    query=vector_query,
                    entity_types=['structure', 'literature'],  # 搜索结构和文献
                    top_k=15  # 获取足够的结果进行rerank
                )
                
                vector_search_performed = True
                if vector_results and vector_results.get('results'):
                    vector_items = vector_results.get('results', [])
                    logger.info(f"✅ 向量搜索完成，找到 {len(vector_items)} 个结果")
                    
                    # 分类结果
                    structure_ids = []
                    literature_ids = []
                    for item in vector_items:
                        item_id = item.get('id')
                        if not item_id:
                            continue
                        
                        # 根据实体类型分类
                        entity_type = item.get('entity_type', 'unknown')
                        if entity_type == 'structure':
                            structure_ids.append(item_id)
                        elif entity_type == 'literature':
                            literature_ids.append(item_id)
                    
                    # 处理结构ID
                    unique_structure_ids = list(set(structure_ids))[:10]  # 最多10个结构
                    if unique_structure_ids:
                        logger.info(f"🎯 向量搜索筛选出 {len(unique_structure_ids)} 个结构ID: {unique_structure_ids[:5]}...")
                        all_structure_ids_to_fetch.update(unique_structure_ids)
                        needs_fallback_search = False
                        
                        # 为了保持流程一致，添加一些文献信息（如果有）
                        for struct_id in unique_structure_ids[:3]:
                            all_literature.append({"id": f"struct_{struct_id}", "source": "vector_search"})
                    
                    # 处理文献ID
                    unique_literature_ids = list(set(literature_ids))[:6]  # 最多6篇文献
                    if unique_literature_ids:
                        logger.info(f"📚 向量搜索筛选出 {len(unique_literature_ids)} 篇文献: {unique_literature_ids[:3]}...")
                        for lit_id in unique_literature_ids:
                            all_literature.append({"id": lit_id, "source": "vector_search"})
                        needs_fallback_search = False
                else:
                    logger.info("⚠️ 向量搜索无结果，回退到常规搜索")
            except Exception as e:
                logger.error(f"向量搜索失败: {e}")
                needs_fallback_search = True
        
        # 4.2 基础搜索
        if needs_fallback_search and simple_qa_search:
            search_results = simple_qa_search(english_question, top_k=6)
            
            if search_results and search_results.get("success"):
                lit_ids = [r.get('id') for r in search_results.get("results", [])]
                unique_lit_ids = list(set(lit_ids))[:6]
                
                if unique_lit_ids:
                    logger.info(f"基础搜索找到 {len(unique_lit_ids)} 篇文献")
                    for lit_id in unique_lit_ids:
                        all_literature.append({"id": lit_id, "source": "basic_search"})
                    # 如果找到了文献，就不需要回退搜索了
                    needs_fallback_search = False
        
        # 4.3 直接搜索（如果基础搜索失败）
        if needs_fallback_search and literature_manager:
            try:
                # 直接使用 literature_manager 进行搜索
                search_result = literature_manager.search_literature_simple(english_question, limit=6)
                
                if search_result and search_result.get("success"):
                    lit_ids = [r.get('id') for r in search_result.get("results", [])]
                    unique_lit_ids = list(set(lit_ids))[:6]
                    
                    if unique_lit_ids:
                        logger.info(f"直接搜索找到 {len(unique_lit_ids)} 篇文献")
                        
                        # 添加直接搜索结果到文献列表
                        for lit_id in unique_lit_ids:
                            all_literature.append({"id": lit_id, "source": "direct_search"})
                        
                        # 如果已经执行了向量搜索，需要合并结果并进行AI验证
                        if vector_search_performed:
                            logger.info("🔄 合并向量搜索和直接搜索结果，进行AI验证...")
                            
                            # 这里可以添加AI验证逻辑，评估文献与问题的相关性
                            # 例如，使用LLM评估每篇文献与问题的相关性
                            
                            # 暂时简化处理，确保至少有一些结果
                            needs_fallback_search = False
                        else:
                            # 如果没有执行向量搜索，直接使用搜索结果
                            needs_fallback_search = False
            except Exception as e:
                logger.error(f"直接搜索发生异常: {e}")
                needs_fallback_search = True

        # 如果仍需要回退搜索，使用有意义的关键词进行搜索
        if needs_fallback_search and literature_manager and meaningful_keywords:
            try:
                logger.info(f"使用有意义的关键词进行搜索: {meaningful_keywords}")
                
                # 构建关键词组合查询
                keyword_queries = []
                # 单个关键词查询
                for keyword in meaningful_keywords:
                    keyword_queries.append(keyword)
                # 两个关键词组合查询
                for i in range(len(meaningful_keywords)):
                    for j in range(i + 1, len(meaningful_keywords)):
                        keyword_queries.append(f"{meaningful_keywords[i]} {meaningful_keywords[j]}")
                
                # 执行关键词搜索
                all_keyword_results = []
                for query in keyword_queries[:5]:  # 限制查询数量
                    try:
                        search_result = literature_manager.search_literature_simple(query, limit=4)
                        if search_result and search_result.get("success"):
                            all_keyword_results.extend(search_result.get("results", []))
                    except Exception as e:
                        logger.error(f"关键词搜索 '{query}' 发生异常: {e}")
                
                # 去重并排序
                if all_keyword_results:
                    # 去重
                    unique_results = {}
                    for result in all_keyword_results:
                        if result.get('id'):
                            unique_results[result['id']] = result
                    
                    # 按相关性排序
                    sorted_results = sorted(unique_results.values(), 
                                          key=lambda x: x.get('relevance_score', 0), 
                                          reverse=True)
                    
                    # 取前6个
                    top_results = sorted_results[:6]
                    unique_lit_ids = [r.get('id') for r in top_results if r.get('id')]
                    
                    if unique_lit_ids:
                            logger.info(f"关键词搜索找到 {len(unique_lit_ids)} 篇文献")
                            for lit_id in unique_lit_ids:
                                all_literature.append({"id": lit_id, "source": "keyword_search"})
                            # 如果找到了文献，就不需要回退搜索了
                            needs_fallback_search = False
            except Exception as e:
                logger.error(f"关键词搜索发生异常: {e}")
                needs_fallback_search = True

    except Exception as e:
        logger.error(f"基础搜索发生异常: {e}")
        needs_fallback_search = True

    # --- 回退逻辑 ---
    if needs_fallback_search:
        logger.info("⚠️ 基础搜索无结果，触发结构回退搜索...")
        
        if literature_manager and hasattr(literature_manager, '_find_structures_by_protein'):
            try:
                # 提取蛋白质名称
                protein_names = literature_manager._extract_protein_names(enhanced_question)
                
                # 修改点：增加 limit 从 10 到 20
                for protein in protein_names:
                    logger.info(f"正在为 '{protein}' 执行混合检索...")
                    hybrid_ids = literature_manager._find_structures_by_protein(
                        protein,
                        question_text=enhanced_question,
                        limit=20  # <--- 修改为 20
                    )
                    all_structure_ids_to_fetch.update(hybrid_ids)
                
                logger.info(f"🔧 混合检索最终找到 {len(all_structure_ids_to_fetch)} 个结构ID: {list(all_structure_ids_to_fetch)}")

            except Exception as e:
                logger.warning(f"回退搜索失败: {e}")
                import traceback
                traceback.print_exc()
    
    # 5. 获取详细文献信息
    validated_literature = []
    for lit_info in all_literature[:6]:
        try:
            lit_id = lit_info.get("id")
            if not lit_id:
                continue
            
            # 跳过向量搜索生成的结构ID占位符
            if isinstance(lit_id, str) and lit_id.startswith("struct_"):
                logger.info(f"跳过向量搜索生成的结构ID占位符: {lit_id}")
                continue
            # 确保 lit_id 是字符串类型
            lit_id_str = str(lit_id)
            
            # 5.1 获取文献详情
            lit_detail = literature_manager.get_literature_detail(lit_id_str)
            if lit_detail.get("success"):
                lit_data = lit_detail["literature"]
                lit_data["source"] = lit_info.get("source", "unknown")
                
                # 添加过滤：确保这是真正的文献，不是结构信息
                # 检查标题是否看起来像结构信息
                title = lit_data.get("title", "").lower()
                if title and ("cryo-em structure" in title or "structure of" in title) and len(title) < 50:
                    logger.info(f"跳过可能是结构信息的条目: {title}")
                    continue
                
                # 检查是否有摘要或正文内容
                abstract = lit_data.get("abstract", "")
                text_content = lit_data.get("text_content", "")
                if not abstract and not text_content:
                    logger.info(f"跳过缺少摘要和正文的条目: {title}")
                    continue
                
                # 5.2 LLM验证：检查文献是否与问题相关
                logger.info(f"🤖 LLM验证文献: {title[:50]}...")
                
                # 构建验证提示词
                validation_prompt = f"""
你是一位专业的文献相关性评估专家。请严格判断以下文献是否与用户问题直接相关。

用户问题：{question}

文献信息：
标题: {lit_data.get("title", "")}
摘要: {abstract[:200]}...
关键词: {", ".join(meaningful_keywords)}

评估标准：
- 文献必须直接涉及问题中的核心生物实体（如特定蛋白质、结构等）
- 文献内容必须能够直接回答用户的问题
- 文献必须包含与问题相关的具体信息（如结构、分辨率、功能等）
- 间接相关或仅提及相关概念的文献不应被视为相关
- 即使文献涉及相关领域，但不直接关于问题中的核心实体的，也应视为不相关

请回答：
- 如果文献与问题直接相关，请回答 "RELEVANT"
- 如果文献与问题不相关或仅间接相关，请回答 "IRRELEVANT"

只需输出一个单词，不要添加任何其他内容。
"""
                
                # 调用LLM进行验证
                try:
                    import httpx
                    import json
                    
                    # 检查DEEPSEEK_KEY是否存在
                    if not DEEPSEEK_KEY:
                        logger.warning("⚠️ DEEPSEEK_KEY 未设置，跳过LLM验证")
                        # 如果API密钥未设置，默认认为文献相关，继续处理
                        logger.info(f"⚠️ API密钥未设置，默认通过验证: {title[:50]}...")
                    else:
                        headers = {
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {DEEPSEEK_KEY}"
                        }
                        
                        payload = {
                            "model": "deepseek-chat",
                            "messages": [
                                {"role": "user", "content": validation_prompt}
                            ],
                            "max_tokens": 10,
                            "temperature": 0.0
                        }
                        
                        logger.info(f"🔧 发送LLM验证请求...")
                        response = httpx.post(
                            "https://api.deepseek.com/chat/completions",
                            headers=headers,
                            json=payload,
                            timeout=30.0
                        )
                        
                        logger.info(f"✅ LLM验证请求完成，状态码: {response.status_code}")
                        if response.status_code == 200:
                            result = response.json()
                            validation_result = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip().upper()
                            
                            logger.info(f"📊 LLM验证结果: {validation_result}")
                            if validation_result != "RELEVANT":
                                logger.info(f"❌ 文献验证失败: {title[:50]}...")
                                continue
                            else:
                                logger.info(f"✅ 文献验证通过: {title[:50]}...")
                        else:
                            logger.warning(f"LLM验证请求失败: {response.status_code}, 响应: {response.text[:100]}...")
                            # 如果请求失败，默认认为文献相关，继续处理
                            logger.info(f"⚠️ 请求失败，默认通过验证: {title[:50]}...")
                except Exception as e:
                    logger.error(f"LLM验证失败: {e}")
                    import traceback
                    traceback.print_exc()
                    # 如果LLM验证失败，默认认为文献相关，继续处理
                    logger.info(f"⚠️ 验证异常，默认通过验证: {title[:50]}...")
                
                # 5.3 深度挖掘
                deep_analysis = {}
                
                # 挖掘实验参数
                full_text_content = lit_data.get("text_content")
                if not full_text_content and enable_fulltext_rag and index_manager:
                    rag_results = index_manager.retrieve(
                        query=f"methods experimental parameters {lit_id}",
                        top_k=5,
                        literature_ids=[lit_id],
                        filters={"content_type": "methods"}
                    )
                    if rag_results and rag_results.get("success"):
                        full_text_content = " ".join([r.get('content', '') for r in rag_results.get("results", [])])
                        logger.info(f"通过 RAG 获取了文献 {lit_id} 的 Methods 片段（约 {len(full_text_content)} 字符）")
                
                if full_text_content:
                    extracted_params = context_enricher.extract_methods_parameters(full_text_content)
                    if extracted_params:
                        deep_analysis["experimental_parameters"] = extracted_params
                        logger.info(f"提取到实验参数: {list(extracted_params.keys())}")
                
                # 深度挖掘结构实体 (确保 structure_db 存在)
                if lit_data.get("cryoem_targets") and structure_db:
                    try:
                        import json
                        targets = lit_data["cryoem_targets"]
                        if isinstance(targets, str):
                            targets = json.loads(targets)
                        
                        pdb_ids = targets.get('pdb_ids', [])
                        if pdb_ids:
                            for pdb_id in pdb_ids[:3]:
                                try:
                                    # --- 修复2: 使用局部变量 structure_db ---
                                    struct_info = None
                                    if hasattr(structure_db, 'get_structure'):
                                        struct_info = structure_db.get_structure(pdb_id, simplify=False)
                                    else:
                                        logger.warning(f"EnhancedStructureManager 没有 get_structure 方法，跳过结构分析: {pdb_id}")
                                    
                                    if struct_info and struct_info.get('entities'):
                                        entities = struct_info.get('entities')
                                        
                                        # 挖掘链组成
                                        if structure_miner:
                                            chain_analysis = structure_miner.analyze_chain_composition(entities)
                                            if chain_analysis:
                                                deep_analysis["chain_composition"] = chain_analysis
                                                logger.info(f"深度分析 PDB {pdb_id} 的链组成")
                                        
                                        # 挖掘相互作用界面
                                        if structure_miner:
                                            interface_analysis = structure_miner.extract_interaction_interfaces(entities)
                                            if interface_analysis:
                                                deep_analysis["interaction_interfaces"] = interface_analysis
                                                logger.info(f"深度分析 PDB {pdb_id} 的相互作用界面")
                                except Exception as se:
                                    logger.warning(f"深度挖掘结构 {pdb_id} 失败: {se}")
                    except Exception as je:
                        logger.warning(f"解析结构目标失败: {je}")
                
                if deep_analysis:
                    lit_data["deep_analysis"] = deep_analysis
                
                validated_literature.append(lit_data)
                
                if lit_data.get("cryoem_targets"):
                    try:
                        import json
                        targets = lit_data["cryoem_targets"]
                        if isinstance(targets, str):
                            targets = json.loads(targets)
                        if isinstance(targets, dict):
                            all_structure_ids_to_fetch.update(targets.get('pdb_ids', []))
                    except Exception as e:
                        logger.warning(f"解析结构ID失败: {e}")
        except Exception as e:
            logger.error(f"获取详细文献信息失败: {e}")
    
    # 检查是否有通过验证的文献
    if not validated_literature:
        logger.info("⚠️ 所有文献都未通过验证，执行回退搜索...")
        
        if literature_manager and hasattr(literature_manager, '_find_structures_by_protein'):
            try:
                # 提取蛋白质名称
                protein_names = literature_manager._extract_protein_names(enhanced_question)
                
                # 修改点：增加 limit 从 10 到 20
                for protein in protein_names:
                    logger.info(f"正在为 '{protein}' 执行混合检索...")
                    hybrid_ids = literature_manager._find_structures_by_protein(
                        protein,
                        question_text=enhanced_question,
                        limit=20  # <--- 修改为 20
                    )
                    all_structure_ids_to_fetch.update(hybrid_ids)
                
                logger.info(f"🔧 混合检索最终找到 {len(all_structure_ids_to_fetch)} 个结构ID: {list(all_structure_ids_to_fetch)}")
                
            except Exception as e:
                logger.warning(f"回退搜索失败: {e}")
                import traceback
                traceback.print_exc()
    else:
        logger.info(f"✅ 共有 {len(validated_literature)} 篇文献通过验证")
        detailed_literature = validated_literature

    # 6. 批量获取结构数据 (修复版)
    structure_details_map = {}
    
    if all_structure_ids_to_fetch and structure_db:
        try:
            expanded_ids_to_fetch = list(all_structure_ids_to_fetch)
            # --- 修复3: 使用局部变量 structure_db ---
            fetch_result = structure_db.batch_get_or_fetch_structures(
                structure_ids=list(expanded_ids_to_fetch),
                force_update=False
            )
            
            raw_data = fetch_result.get("from_local", {})
            if isinstance(raw_data, list):
                for item in raw_data:
                    if isinstance(item, dict) and item.get('id'):
                        structure_details_map[item['id']] = item
            elif isinstance(raw_data, dict):
                structure_details_map.update(raw_data)
            
            logger.info(f"✅ 批量获取结构数据: {len(structure_details_map)} 个")
            
            # EMDB 补充逻辑 (确保 structure_db 存在)
            if intent_type == "molecular_entity":
                extra_pdb_ids = set()
                for struct_id, struct_info in structure_details_map.items():
                    if struct_id.startswith('EMD-') and not struct_info.get('entities'):
                        related_ids = struct_info.get('related_ids', [])
                        pdb_candidates = related_ids + struct_info.get('metadata', {}).get('pdb_ids', [])
                        for pdb in pdb_candidates:
                            if pdb and (pdb.upper().startswith('P') or len(pdb) == 4):
                                extra_pdb_ids.add(str(pdb).upper())
                
                if extra_pdb_ids:
                    logger.info(f"🔧 检测到 EMDB 缺失序列，尝试补充获取相关 PDB: {extra_pdb_ids}")
                    try:
                        # --- 修复4: 使用局部变量 structure_db ---
                        extra_result = structure_db.batch_get_or_fetch_structures(
                            structure_ids=list(extra_pdb_ids),
                            force_update=False
                        )
                        extra_data = extra_result.get("from_local", {})
                        if isinstance(extra_data, dict):
                            structure_details_map.update(extra_data)
                        elif isinstance(extra_data, list):
                            for item in extra_data:
                                if isinstance(item, dict):
                                    structure_details_map[item['id']] = item
                        logger.info(f"✅ 补充获取 PDB 数据完成: {len(extra_pdb_ids)} 个")
                    except Exception as e:
                        logger.error(f"补充获取 PDB 失败: {e}")
            
        except Exception as e:
            logger.error(f"批量获取结构数据失败: {e}")
    
    # 7. 构建上下文
    context_parts = []
    
    if structure_details_map:
        context_parts.append("\n\n### 🧬 结构深度挖掘与实体分析\n")
        context_parts.append("以下是相关结构的详细信息、链组成以及相互作用界面分析：\n")
        
        # 添加日志：显示每个结构的序列数量
        logger.info("📊 各结构序列信息统计：")
        for pdb_id, struct_info in structure_details_map.items():
            entities = struct_info.get('entities', [])
            # 统计有多少个实体包含序列信息
            sequence_count = 0
            total_entities = len(entities)
            for ent in entities:
                seq = ent.get('sequence', '')
                if seq and len(seq) > 0:
                    sequence_count += 1
            logger.info(f"   {pdb_id}: 共 {total_entities} 个实体，其中 {sequence_count} 个包含序列信息")
        
        for pdb_id, struct_info in structure_details_map.items():
            title = struct_info.get('title', 'N/A')[:60]
            res = struct_info.get('resolution')
            
            context_parts.append(f"\n#### 结构 ID: {pdb_id}\n")
            context_parts.append(f"- **标题**: {title}\n")
            context_parts.append(f"- **分辨率**: {res} Å\n")
            
            if structure_miner and struct_info.get('entities'):
                entities = struct_info.get('entities')
                chain_analysis = structure_miner.analyze_chain_composition(entities)
                if chain_analysis:
                    context_parts.append(f"{chain_analysis}\n")
                
                interface_analysis = structure_miner.extract_interaction_interfaces(entities)
                if interface_analysis:
                    context_parts.append(f"{interface_analysis}\n")
            
            context_parts.append("\n---\n")
    else:
        context_parts.append("\n\n### ⚠️ 未找到相关结构数据\n")
    
    # 7.2 文献摘要与发现
    if detailed_literature:
        context_parts.append("\n### 📚 文献摘要与核心发现\n")
        for lit in detailed_literature:
            if isinstance(lit, dict):
                lit_id = lit.get("id", '')
                title = lit.get('title', 'N/A')
                
                context_parts.append(f"\n**文献**: {title}\n")
                
                abstract = lit.get('abstract', '')
                if abstract:
                    context_parts.append(f"**摘要**: {abstract[:1200]}...\n")
                
                findings = lit.get('key_findings', '')
                if findings:
                    context_parts.append("**关键发现**:\n")
                    if isinstance(findings, str):
                        try:
                            f_list = json.loads(findings)
                            if isinstance(f_list, list):
                                for f in f_list[:5]:
                                    if isinstance(f, dict):
                                        desc = f.get('finding', '')
                                        context_parts.append(f"- {desc}\n")
                                    else:
                                        context_parts.append(f"- {f}\n")
                        except:
                            pass
                context_parts.append("\n")
    
    # 7.3 为通用搜索添加RAG检索
    if intent_type == "general_search" and enable_fulltext_rag and index_manager and meaningful_keywords:
        context_parts.append("\n### 📖 文献原文深度检索\n")
        context_parts.append("以下是从文献原文中检索到的相关内容：\n")
        
        # 构建RAG查询
        rag_query = " ".join(meaningful_keywords)
        logger.info(f"🔍 为通用搜索执行RAG检索: 查询 '{rag_query}'")
        
        # 执行RAG检索
        try:
            rag_results = index_manager.retrieve(
                query=rag_query,
                top_k=5,
                literature_ids=[l.get("id") for l in detailed_literature if l.get("id")],
                filters={"content_type": "abstract"}
            )
            
            if rag_results and rag_results.get("success"):
                rag_items = rag_results.get("results", [])
                logger.info(f"✅ RAG检索完成，找到 {len(rag_items)} 个相关片段")
                
                for i, item in enumerate(rag_items[:3], 1):
                    content = item.get('content', '')
                    literature_id = item.get('literature_id', '')
                    if content and literature_id:
                        context_parts.append(f"\n**片段 {i}** (文献 ID: {literature_id}):\n")
                        context_parts.append(f"{content[:800]}...\n")
            else:
                logger.info("⚠️ RAG检索无结果")
                context_parts.append("\n未找到相关原文片段。\n")
        except Exception as e:
            logger.error(f"RAG检索失败: {e}")
            context_parts.append("\n原文检索失败。\n")
    
    # 7.4 为结构质量类型添加RAG检索
    if intent_type == "structure_quality" and enable_fulltext_rag and index_manager and meaningful_keywords:
        context_parts.append("\n### 📊 结构质量数据深度检索\n")
        context_parts.append("以下是从结构数据库中检索到的详细质量参数：\n")
        
        # 构建RAG查询
        rag_query = " ".join(meaningful_keywords) + " resolution method quality structure"
        logger.info(f"🔍 为结构质量执行RAG检索: 查询 '{rag_query}'")
        
        # 执行RAG检索
        try:
            rag_results = index_manager.retrieve(
                query=rag_query,
                top_k=5,
                filters={"content_type": "structure"}
            )
            
            if rag_results and rag_results.get("success"):
                rag_items = rag_results.get("results", [])
                logger.info(f"✅ RAG检索完成，找到 {len(rag_items)} 个相关结构质量数据")
                
                for i, item in enumerate(rag_items[:3], 1):
                    content = item.get('content', '')
                    structure_id = item.get('structure_id', '') or item.get('id', '')
                    if content and structure_id:
                        context_parts.append(f"\n**结构 {i}** (ID: {structure_id}):\n")
                        context_parts.append(f"{content[:600]}...\n")
            else:
                logger.info("⚠️ RAG检索无结果")
                context_parts.append("\n未找到相关结构质量数据。\n")
        except Exception as e:
            logger.error(f"RAG检索失败: {e}")
            context_parts.append("\n结构质量数据检索失败。\n")
            
    # 8. 使用之前定义的完整 Prompt 策略
    # 注意：这里不再重新定义，使用第402行定义的完整策略，确保包含所有强制要求
    
    system_prompt = PROMPT_STRATEGIES.get(intent_type, PROMPT_STRATEGIES["general_search"])
    
    # 9. 拼接完整上下文
    full_context = "\n".join(context_parts)
    
    # 10. 构建消息
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": f"【上下文】：\n{full_context}"}
    ]
    
    # 添加会话历史作为上下文
    if conversation_context:
        logger.info(f"🔄 从会话历史中提取上下文，共 {len(conversation_context)} 条消息")
        
        # 提取最近的几条消息作为上下文
        recent_context = conversation_context[-5:]  # 最多使用最近5条消息
        for msg in recent_context:
            if msg.get("type") == "question":
                messages.append({"role": "user", "content": msg.get("content", "")})
            elif msg.get("type") == "answer":
                messages.append({"role": "assistant", "content": msg.get("content", "")})
    
    # 添加当前问题
    messages.append({"role": "user", "content": question})
    
    # 添加详细日志，记录发送给LLM的消息结构
    logger.info(f"📤 发送给LLM的消息结构:")
    logger.info(f"   系统提示词长度: {len(system_prompt)} 字符")
    logger.info(f"   上下文长度: {len(full_context)} 字符")
    logger.info(f"   用户问题: {question}")
    logger.info(f"   消息总数: {len(messages)}")
    if conversation_context:
        logger.info(f"   从上文获取信息: 已包含 {len(recent_context)} 条历史消息")
    else:
        logger.info(f"   从上文获取信息: 无")
    
    # 11. 调用 LLM
    try:
        content = create_chat_completion(
            messages=messages,
            temperature=0.3,
            timeout=60
        )

        if content:
            answer = content
            sources = []
            if detailed_literature:
                # 只添加与最终答案相关的文献
                sources = [{"id": l.get("id"), "title": l.get("title", "N/A"), "authors": l.get("authors", []), "type": "literature"} for l in detailed_literature]
            if structure_details_map:
                for pdb_id in structure_details_map.keys():
                    struct_info = structure_details_map[pdb_id]
                    # 创建结构来源
                    structure_source = {
                        "id": pdb_id,
                        "title": struct_info.get("title", ""),
                        "type": "structure"
                    }
                    
                    # 尝试从结构ID映射到文献
                    mapped_literature = []
                    logger.info(f"尝试从结构ID {pdb_id} 映射到文献")
                    
                    # 1. 检查结构信息中是否有文献相关字段
                    if "literature_ids" in struct_info:
                        literature_ids = struct_info["literature_ids"]
                        if isinstance(literature_ids, list):
                            logger.info(f"结构信息中包含文献ID: {literature_ids}")
                            for lit_id in literature_ids:
                                # 尝试从详细文献中找到对应的文献
                                for lit in detailed_literature:
                                    if lit.get("id") == lit_id:
                                        mapped_literature.append(lit)
                                        logger.info(f"找到匹配的文献: {lit.get('title')}")
                                        break
                    
                    # 2. 如果没有找到映射的文献，尝试通过结构ID搜索相关文献
                    if not mapped_literature and literature_manager and hasattr(literature_manager, 'search_literature_simple'):
                        try:
                            # 使用结构ID作为搜索词，使用更简单的搜索参数
                            logger.info(f"通过结构ID {pdb_id} 搜索相关文献")
                            # 使用 title 搜索类型，直接匹配，不进行翻译
                            search_result = literature_manager.search_literature_simple(pdb_id, limit=2, filters={"search_type": "title"})
                            if search_result and search_result.get("success"):
                                search_literature = search_result.get("results", [])
                                logger.info(f"搜索到 {len(search_literature)} 篇相关文献")
                                
                                # 过滤和排序搜索结果，只保留最相关的文献
                                # 优先选择在 cryoem_targets 中包含结构ID的文献
                                cryoem_priority_literature = []
                                
                                for lit in search_literature:
                                    # 检查结构ID是否完整出现在文献的关键字段中
                                    lit_id = lit.get("id")
                                    
                                    # 首先检查 pdb_ids 和 emdb_ids 字段（这些是从 cryoem_targets 中提取的）
                                    has_cryoem_match = False
                                    
                                    # 检查 pdb_ids 字段
                                    pdb_ids = lit.get("pdb_ids", [])
                                    if isinstance(pdb_ids, list) and pdb_id in pdb_ids:
                                        has_cryoem_match = True
                                    
                                    # 检查 emdb_ids 字段
                                    emdb_ids = lit.get("emdb_ids", [])
                                    if not has_cryoem_match and isinstance(emdb_ids, list) and pdb_id in emdb_ids:
                                        has_cryoem_match = True
                                    
                                    # 作为后备，检查 cryoem_targets 字段
                                    if not has_cryoem_match:
                                        lit_cryoem = lit.get("cryoem_targets", "")
                                        if lit_cryoem:
                                            # 使用更宽松的匹配方式
                                            cryoem_str = str(lit_cryoem)
                                            if pdb_id in cryoem_str:
                                                has_cryoem_match = True
                                    
                                    # 根据匹配类型添加到不同列表
                                    if has_cryoem_match and lit_id:
                                        # 优先添加在 cryoem_targets 中匹配的文献
                                        cryoem_priority_literature.append(lit)
                                
                                # 去重，只保留唯一的文献
                                unique_literature = []
                                seen_ids = set()
                                for lit in cryoem_priority_literature:
                                    lit_id = lit.get("id")
                                    if lit_id and lit_id not in seen_ids:
                                        seen_ids.add(lit_id)
                                        unique_literature.append(lit)
                                
                                # 如果有匹配的文献，使用过滤后的结果
                                if unique_literature:
                                    mapped_literature = unique_literature[:1]  # 只保留1篇最相关的（cryoem_targets 优先）
                                    if mapped_literature:
                                        logger.info(f"添加新映射的文献: {mapped_literature[0].get('title')}")
                                else:
                                    # 如果没有文献在 cryoem_targets 中包含结构ID，记录日志但不进行映射
                                    logger.info(f"未找到在 cryoem_targets 中包含结构ID {pdb_id} 的文献")
                            else:
                                logger.info(f"搜索结果为空或失败: {search_result}")
                        except Exception as e:
                            logger.warning(f"通过结构ID搜索文献失败: {e}")
                    
                    # 3. 不再通过标题搜索，只通过 cryoem_targets 映射文献
                    # if not mapped_literature and literature_manager and hasattr(literature_manager, 'search_literature_simple'):
                    #     try:
                    #         struct_title = struct_info.get("title", "")
                    #         if struct_title:
                    #             logger.info(f"通过结构标题 '{struct_title}' 搜索相关文献")
                    #             search_result = literature_manager.search_literature_simple(struct_title, limit=2)
                    #             if search_result and search_result.get("success"):
                    #                 search_literature = search_result.get("results", [])
                    #                 logger.info(f"通过标题搜索到 {len(search_literature)} 篇相关文献")
                    #                 # 只添加1篇最相关的文献
                    #                 for lit in search_literature[:1]:
                    #                     lit_id = lit.get("id")
                    #                     if lit_id:
                    #                         existing = any(l.get("id") == lit_id for l in detailed_literature)
                    #                         if not existing:
                    #                             mapped_literature.append(lit)
                    #                             logger.info(f"添加通过标题映射的文献: {lit.get('title')}")
                    #     except Exception as e:
                    #         logger.warning(f"通过结构标题搜索文献失败: {e}")
                    
                    # 添加映射的文献信息
                    if mapped_literature:
                        logger.info(f"结构 {pdb_id} 成功映射到 {len(mapped_literature)} 篇文献")
                        structure_source["mapped_literature"] = mapped_literature
                        
                        # 将映射的文献添加到 sources 中，确保UI能显示这些文献
                        for lit in mapped_literature:
                            lit_id = lit.get("id")
                            if lit_id:
                                # 检查文献是否已经在 sources 中
                                existing = any(s.get("id") == lit_id and s.get("type") == "literature" for s in sources)
                                if not existing:
                                    sources.append({
                                        "id": lit_id,
                                        "title": lit.get("title", "N/A"),
                                        "authors": lit.get("authors", []),
                                        "type": "literature"
                                    })
                    else:
                        logger.info(f"结构 {pdb_id} 未找到映射的文献")
                    
                    sources.append(structure_source)
            
            return {
                "success": True,
                "answer": answer,
                "sources": sources,
                "context_used": {"intent_type": intent_type, "has_deep_analysis": bool(structure_details_map), "has_rag": enable_fulltext_rag},
                "qa_engine": "enhanced_search",
                "latency": time.time() - start_time
            }
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        return {
            "success": False,
            "answer": f"处理失败: {str(e)}",
            "sources": [],
            "qa_engine": "llm_error",
            "latency": time.time() - start_time
        }

    # 如果所有搜索都失败，使用LLM生成友好的回复
    logger.info("⚠️ 所有搜索都失败，使用LLM生成友好回复")
    
    # 构建消息
    messages = [
        {"role": "system", "content": "你是一位资深的分子生物学家。当没有找到相关信息时，请友好地告知用户信息不足，无法给出详细答案，并提供一些建议。"},
        {"role": "user", "content": f"用户问: '{question}'，但系统没有找到相关的文献或结构数据。请友好地回复用户。"}
    ]
    
    try:
        content = create_chat_completion(
            messages=messages,
            temperature=0.3,
            timeout=30
        )

        if content:
            answer = content
            return {
                "success": True,
                "answer": answer,
                "sources": [],
                "qa_engine": "no_results_ai",
                "latency": time.time() - start_time
            }
    except Exception as e:
        logger.error(f"生成无结果回复失败: {e}")
    
    # 如果LLM调用也失败，返回默认友好回复
    return {
        "success": True,
        "answer": "抱歉，没有找到与您的问题相关的文献或结构数据。请尝试使用更具体的关键词，或者检查是否有相关的文献已添加到系统中。您也可以提供更多背景信息，以便我更好地理解您的问题。",
        "sources": [],
        "qa_engine": "no_results",
        "latency": time.time() - start_time
    }
    
# ---------- 核心AI功能 ----------

def parse_text_with_llm(text_content: str) -> Dict[str, Any]:
    """
    专门为文献库优化的LLM解析函数
    从原始文献文本中提取结构化元数据、关键发现等信息
    """
    import time
    
    # 智能截断策略：确保关键部分被保留
    truncated_text = text_content
    if len(text_content) > 50000:
        logger.info(f"文本过长 ({len(text_content)}字符)，进行智能截断...")
        
        # 提取关键部分
        sections = {}
        
        # 1. 查找摘要部分
        abstract_start = text_content.lower().find("abstract")
        if abstract_start != -1:
            abstract_end = find_section_end(text_content, abstract_start)
            if abstract_end > abstract_start:
                sections["abstract"] = text_content[abstract_start:abstract_end]
        
        # 2. 查找结论/讨论部分
        conclusion_keywords = ["discussion", "conclusion", "summary", "discussion and conclusions"]
        for keyword in conclusion_keywords:
            conclusion_start = text_content.lower().find(keyword)
            if conclusion_start != -1:
                conclusion_end = find_section_end(text_content, conclusion_start)
                if conclusion_end > conclusion_start:
                    sections["conclusion"] = text_content[conclusion_start:conclusion_end]
                    break
        
        # 3. 查找数据可用性部分
        data_keywords = ["data availability", "data and materials availability", "accession codes"]
        for keyword in data_keywords:
            data_start = text_content.lower().find(keyword)
            if data_start != -1:
                data_end = find_section_end(text_content, data_start)
                if data_end > data_start:
                    sections["data_availability"] = text_content[data_start:data_end]
                    break
        
        # 4. 查找方法部分（可能包含结构信息）
        methods_keywords = ["methods", "materials and methods", "experimental procedures"]
        for keyword in methods_keywords:
            methods_start = text_content.lower().find(keyword)
            if methods_start != -1:
                methods_end = find_section_end(text_content, methods_start)
                if methods_end > methods_start:
                    sections["methods"] = text_content[methods_start:methods_end]
                    break
        
        # 5. 查找结果部分
        results_start = text_content.lower().find("results")
        if results_start != -1:
            results_end = find_section_end(text_content, results_start)
            if results_end > results_start:
                sections["results"] = text_content[results_start:results_end]
        
        # 构建智能截断文本
        truncated_parts = []
        
        # 添加标题（前1000字符通常包含标题、作者、摘要）
        truncated_parts.append(text_content[:1000])
        
        # 添加关键部分
        for section_name in ["abstract", "methods", "results", "conclusion", "data_availability"]:
            if section_name in sections:
                truncated_parts.append(f"\n\n--- {section_name.upper()} ---\n")
                truncated_parts.append(sections[section_name])
        
        # 如果关键部分太短，添加更多上下文
        total_length = sum(len(part) for part in truncated_parts)
        if total_length < 20000:
            # 添加开头更多内容
            truncated_parts.insert(0, text_content[:10000])
        
        truncated_text = "".join(truncated_parts)
        
        # 最终截断
        truncated_text = truncated_text[:50000]
        
        logger.info(f"智能截断完成：原文本 {len(text_content)}字符 -> 截断后 {len(truncated_text)}字符")
        logger.info(f"保留的关键部分：{list(sections.keys())}")
    
    # 增强系统提示 - 去除日期和冷冻电镜靶点要求
    system_prompt = """你是一个专业的文献解析助手。请从提供的文献文本中提取关键信息。

需要提取的字段如下：
- title: 文献标题（字符串）
- authors: 作者列表（格式：[{"name": "作者名", "affiliation": "机构"}], 或简单字符串列表）
- journal: 期刊/会议名称（字符串）
- doi: DOI标识符（字符串）
- keywords: 关键词列表（字符串列表）
- abstract: 摘要（字符串）
- key_findings: 关键发现列表（**必须用中文描述**，仅蛋白质名称、结构ID、技术方法等专有名词保留英文）
- research_method: 研究方法（字符串）
- citation_count: 引用次数（整数，如能提取）
- impact_factor: 影响因子（浮点数，如能提取）

注意事项：
1. **关键发现(key_findings)必须用中文撰写**，仅以下情况使用英文：
   - 蛋白质、基因名称（如 Brd4、VHL）
   - 结构ID（如 PDB ID 8RWZ）
   - 公认的英文缩写（如 CRBN、PROTAC、ubiquitination）
   - 化学分子名称
   - 其他无中文对应的专有名词
2. 普通概念必须用中文（如"揭示了"、"研究表明"、"关键机制"等）
3. 如果找不到某个字段，请设为 null 或空值
4. 优先从文本中准确提取，避免猜测
5. 作者信息尽量结构化，包含姓名和机构
6. 关键词应来自文献本身，不要自己生成
7. 保持字段名称与上述列表完全一致
8. **特别提醒：不提取出版日期，日期信息将由外部来源（如Crossref）提供**
9. **特别提醒：不提取冷冻电镜靶点信息，这是简化的通用文献解析功能"""
    
    user_prompt = f"""请解析以下文献文本内容：

{truncated_text}

请提取上述所有字段信息，并以JSON格式返回。"""

    try:
        start_time = time.time()
        logger.info(f"开始调用LLM API，截断文本长度: {len(truncated_text)}字符")

        # 使用统一API调用
        content = create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            max_tokens=4096,  # 增加 max_tokens 以确保 JSON 完整输出
            timeout=180,
            json_mode=True
        )

        elapsed = time.time() - start_time
        logger.info(f"✅ LLM API调用成功，耗时: {elapsed:.2f}秒")
        
        # 清理内容
        content = content.replace("```json", "").replace("```", "").strip()
        
        try:
            data = json.loads(content)
            data = _standardize_literature_data(data)
            
            # 记录提取的信息
            if data.get("title"):
                logger.info(f"📖 AI解析出的标题: {data['title'][:100]}")
            
            if data.get("authors") and len(data["authors"]) > 0:
                author_count = len(data["authors"])
                author_names = []
                for author in data["authors"][:3]:  # 只显示前3个作者
                    if isinstance(author, dict):
                        author_names.append(author.get("name", ""))
                    else:
                        author_names.append(str(author))
                logger.info(f"👥 AI解析出的作者 ({author_count}人): {', '.join(author_names)}")
            
            if data.get("journal"):
                logger.info(f"📰 AI解析出的期刊: {data['journal'][:50]}")
                
            return data
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            # 记录更详细的日志
            logger.error(f"原始响应内容前500字符: {content[:500]}")
            logger.error(f"原始响应内容位置 {e.pos} 附近: {content[max(0, e.pos-50):e.pos+50]}")

            # 尝试多种修复策略
            fixed_content = _fix_incomplete_json(content)
            if fixed_content:
                try:
                    data = json.loads(fixed_content)
                    data = _standardize_literature_data(data)
                    logger.info("✅ JSON修复成功")
                    return data
                except Exception as fix_err:
                    logger.error(f"JSON修复失败: {fix_err}")
            else:
                logger.error("JSON修复返回空")

            # 尝试提取JSON部分
            json_match = re.search(r'\{[\s\S]*\}', content, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    data = _standardize_literature_data(data)
                    logger.info("✅ 正则提取JSON成功")
                    return data
                except Exception as re_err:
                    logger.error(f"正则提取JSON失败: {re_err}")

            # 回退
            logger.warning("尝试回退方法从文本提取...")
            data = _fallback_extract_from_text(content)
            if data:
                logger.info("✅ 回退提取成功")
            else:
                logger.error("回退提取也失败")

            # 回退
            data = _fallback_extract_from_text(content)
            return data
            
    except Exception as e:
        elapsed = time.time() - start_time if 'start_time' in locals() else 0
        logger.error(f"❌ LLM解析API调用失败 ({elapsed:.2f}秒): {e}")
        
        # 即使失败也返回空数据，而不是抛出异常
        return _get_empty_literature_data()

def find_section_end(text: str, start_pos: int) -> int:
    """查找章节结束位置"""
    # 查找下一个章节标题
    section_keywords = [
        "abstract", "introduction", "methods", "results", "discussion", 
        "conclusion", "references", "acknowledgements", "data availability",
        "author contributions", "competing interests"
    ]
    
    text_lower = text.lower()
    end_pos = len(text)
    
    for keyword in section_keywords:
        pos = text_lower.find(keyword, start_pos + 10)  # 跳过当前标题
        if pos != -1 and pos < end_pos:
            end_pos = pos
    
    return end_pos

def _standardize_literature_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """标准化文献数据 - 简化版，去除冷冻电镜靶点处理"""
    standardized = {}
    
    # 字段映射和转换
    field_mappings = {
        "title": str,
        "journal": str,
        "doi": str,
        "abstract": str,
        "research_method": str
    }
    
    for field, converter in field_mappings.items():
        if field in data:
            try:
                standardized[field] = converter(data[field]) if data[field] is not None else ""
            except:
                standardized[field] = ""
    
    # 特殊处理作者
    if "authors" in data:
        authors = data["authors"]
        if isinstance(authors, list):
            standardized["authors"] = authors
        elif isinstance(authors, str):
            # 尝试分割字符串
            if ";" in authors:
                authors_list = [a.strip() for a in authors.split(";")]
            elif "," in authors:
                authors_list = [a.strip() for a in authors.split(",")]
            else:
                authors_list = [authors.strip()]
            
            # 转换为结构化格式
            structured_authors = []
            for author in authors_list:
                if "{" in author and "}" in author:
                    try:
                        author_dict = json.loads(author)
                        structured_authors.append(author_dict)
                    except:
                        structured_authors.append({"name": author, "affiliation": ""})
                else:
                    structured_authors.append({"name": author, "affiliation": ""})
            standardized["authors"] = structured_authors
    else:
        standardized["authors"] = []
    
    # 特殊处理关键词
    if "keywords" in data:
        keywords = data["keywords"]
        if isinstance(keywords, list):
            standardized["keywords"] = [str(k).strip() for k in keywords]
        elif isinstance(keywords, str):
            if ";" in keywords:
                standardized["keywords"] = [k.strip() for k in keywords.split(";")]
            elif "," in keywords:
                standardized["keywords"] = [k.strip() for k in keywords.split(",")]
            else:
                standardized["keywords"] = [keywords.strip()]
        else:
            standardized["keywords"] = []
    else:
        standardized["keywords"] = []
    
    # 特殊处理关键发现
    if "key_findings" in data:
        findings = data["key_findings"]
        if isinstance(findings, list):
            standardized["key_findings"] = [
                str(f).strip() for f in findings if str(f).strip()
            ]
        elif isinstance(findings, str):
            if ";" in findings:
                standardized["key_findings"] = [f.strip() for f in findings.split(";")]
            elif "," in findings:
                standardized["key_findings"] = [f.strip() for f in findings.split(",")]
            else:
                standardized["key_findings"] = [findings.strip()]
        else:
            standardized["key_findings"] = []
    else:
        standardized["key_findings"] = []
    
    # 处理数字字段
    for num_field in ["citation_count", "impact_factor"]:
        if num_field in data:
            try:
                if isinstance(data[num_field], (int, float)):
                    standardized[num_field] = data[num_field]
                elif isinstance(data[num_field], str):
                    num_match = re.search(r'[\d.]+', data[num_field])
                    if num_match:
                        standardized[num_field] = float(num_match.group()) if "." in num_match.group() else int(num_match.group())
                    else:
                        standardized[num_field] = None
                else:
                    standardized[num_field] = None
            except:
                standardized[num_field] = None
    
    # 添加时间戳
    standardized["parsed_at"] = datetime.now().isoformat()
    
    return standardized

def _fix_incomplete_json(content: str) -> Optional[str]:
    """
    尝试修复不完整的JSON字符串
    处理 LLM 返回的截断 JSON，特别是 "Unterminated string" 错误
    """
    if not content:
        return None

    original_content = content

    for attempt in range(3):
        try:
            json.loads(content)
            return content  # 解析成功
        except json.JSONDecodeError as e:
            error_msg = str(e)

            if "Unterminated string" in error_msg:
                # 找到错误位置
                err_pos = e.pos
                # 从错误位置向前找，找到完整的字段结束
                # 模式：... "key": "value" , 或 ... "key": "value" }
                # 未完成的模式：... "key": "value with incomplete

                # 找到错误位置的上一行结束位置
                line_start = content.rfind('\n', 0, err_pos) + 1
                prefix = content[:line_start]
                suffix = content[err_pos:]

                # 在 prefix 中找到最后一个闭合的引号（值的结束）
                # 查找模式: "...", 或 "...", 或 "...",}
                # 需要找到 "value" 结束后的下一个引号

                # 从错误位置向前扫描，找到最后一个 "xxx": "yyy" 模式
                # 其中 yyy 是完整字符串

                # 策略：直接找到最后一个闭合的引号对
                # 然后添加闭合的括号

                # 找到最后一个完整的 "field": "value" 或 "field": ["array"]
                # 我们通过从后向前扫描来找到合理的结束位置

                # 首先尝试：在最后一个 } 或 ] 处截断
                last_possible = -1
                for i in range(err_pos - 1, -1, -1):
                    c = content[i]
                    if c == '}' or c == ']':
                        # 尝试截断到这里
                        try:
                            test = content[:i + 1]
                            json.loads(test)
                            last_possible = i + 1
                            break
                        except:
                            continue

                if last_possible > 0:
                    content = content[:last_possible]
                    # 添加缺失的闭合括号
                    open_braces = content.count('{')
                    close_braces = content.count('}')
                    if open_braces > close_braces:
                        content = content + '}' * (open_braces - close_braces)
                    open_brackets = content.count('[')
                    close_brackets = content.count(']')
                    if open_brackets > close_brackets:
                        content = content + ']' * (open_brackets - close_brackets)
                    continue

                # 如果找不到，使用更激进的方法
                # 在错误行中找到最后一个闭合引号
                current_line_start = content.rfind('\n', 0, err_pos) + 1
                current_line = content[current_line_start:err_pos]

                # 计算当前行的引号数量
                quotes_in_line = current_line.count('"')
                if quotes_in_line % 2 == 1:
                    # 奇数个引号，说明有一个未闭合的字符串
                    # 找到最后一个引号的位置
                    last_quote_pos = current_line.rfind('"')
                    if last_quote_pos >= 0:
                        # 截断到该引号之后
                        new_line_end = current_line_start + last_quote_pos + 1
                        content = content[:new_line_end] + '"' + content[err_pos:]
                        # 移除可能的尾部逗号
                        content = re.sub(r',\s*([}\]])', r'\1', content)
                        continue

            elif "Expecting" in error_msg or "extra data" in error_msg:
                err_pos = e.pos
                # 只保留到错误位置
                content = content[:err_pos]
                # 修复括号匹配
                open_braces = content.count('{')
                close_braces = content.count('}')
                if open_braces > close_braces:
                    content = content + '}' * (open_braces - close_braces)
                open_brackets = content.count('[')
                close_brackets = content.count(']')
                if open_brackets > close_brackets:
                    content = content + ']' * (open_brackets - close_brackets)
                continue

    # 最终策略：从后向前扫描找到有效的 JSON 结束位置
    for i in range(len(content) - 1, -1, -1):
        char = content[i]
        if char == '}' or char == ']':
            try:
                test_content = content[:i + 1]
                json.loads(test_content)
                content = test_content
                break
            except:
                continue

    # 修复括号匹配
    open_braces = content.count('{')
    close_braces = content.count('}')
    if open_braces > close_braces:
        content = content + '}' * (open_braces - close_braces)

    open_brackets = content.count('[')
    close_brackets = content.count(']')
    if open_brackets > close_brackets:
        content = content + ']' * (open_brackets - close_brackets)

    # 移除末尾逗号
    content = re.sub(r',(\s*[}\]])', r'\1', content)

    return content if content != original_content else None

def _fallback_extract_from_text(text: str) -> Dict[str, Any]:
    """从文本中回退提取信息"""
    data = _get_empty_literature_data()
    
    lines = text.split('\n')
    
    # 尝试提取标题
    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith("Title:") or line.startswith("标题:") or line.startswith("Title :"):
            data["title"] = line.split(":", 1)[1].strip()
            break
        elif i == 0 and len(line) > 10 and len(line) < 200:
            data["title"] = line
    
    # 尝试提取作者
    for line in lines:
        if "Author" in line or "作者" in line or line.startswith("By ") or line.startswith("Authors:") or line.startswith("Authors :"):
            if ":" in line:
                authors_str = line.split(":", 1)[1].strip()
            else:
                authors_str = line.replace("Authors", "").replace("Author", "").replace("作者", "").strip()
            if authors_str:
                data["authors"] = [{"name": authors_str, "affiliation": ""}]
            break
    
    # 尝试提取期刊
    for line in lines:
        if "Journal" in line or "期刊" in line or "Published in" in line or "Journal:" in line or "Journal :" in line:
            if ":" in line:
                data["journal"] = line.split(":", 1)[1].strip()
            break
    
    # 提取DOI
    for line in lines:
        if "DOI" in line or "doi:" in line.lower():
            if ":" in line:
                data["doi"] = line.split(":", 1)[1].strip()
            break
    
    # 提取摘要
    abstract_started = False
    abstract_lines = []
    for line in lines:
        if "Abstract" in line or "摘要" in line or "Summary" in line:
            abstract_started = True
            continue
        
        if abstract_started:
            if line.strip() == "" or "Introduction" in line or "Keywords" in line or "KEYWORDS" in line or "Key words" in line:
                break
            abstract_lines.append(line)
    
    if abstract_lines:
        data["abstract"] = " ".join(abstract_lines)
    
    # 提取关键词
    for line in lines:
        if "Keywords" in line or "关键词" in line or "Key words" in line or "KEYWORDS" in line:
            if ":" in line:
                keywords_str = line.split(":", 1)[1].strip()
                data["keywords"] = [k.strip() for k in keywords_str.split(";") if k.strip()]
            break
    
    return data

def _get_empty_literature_data() -> Dict[str, Any]:
    """返回空的文献数据结构"""
    return {
        "title": "",
        "authors": [],
        "journal": "",
        "doi": "",
        "keywords": [],
        "abstract": "",
        "key_findings": [],
        "research_method": "",
        "citation_count": None,
        "impact_factor": None,
        "parsed_at": datetime.now().isoformat()
    }

# ---------- 文献专用QA函数 ----------

def ask_literature_question(query: str, context_text: str = None, conversation_context: list = None, literature_context: list = None, use_rag: bool = True) -> Dict[str, Any]:
    """
    专门为文献库设计的问答函数
    """
    system_prompt = """你是专业的文献研究助手。请根据提供的文献内容回答问题。

要求：
1. **必须用中文回答**，仅以下情况使用英文：
   - 蛋白质、基因名称（如 Brd4、VHL、Brd4BD2）
   - 结构ID（如 PDB 8RWZ、EMDB）
   - 技术方法英文缩写（如 Cryo-EM、ubiquitination）
   - 化学分子/药物名称
2. 普通概念必须用中文（如"该研究揭示了"、"结果表明"、"关键机制是"等）
3. 回答要基于事实，引用具体的发现、数据或结论
4. 如果上下文信息不足，请说明需要更多信息
5. 保持回答简洁、专业、准确
6. 如果是方法学问题，请详细说明技术细节"""
    
    messages = [
        {"role": "system", "content": system_prompt}
    ]
    
    if context_text:
        messages.append({
            "role": "system", 
            "content": f"【文献上下文】：\n{context_text[:3000]}"  # 减少上下文长度
        })
    
    messages.append({"role": "user", "content": query})

    try:
        content = create_chat_completion(
            messages=messages,
            temperature=0.3,
            timeout=20
        )

        answer = content

        return {
            "success": True,
            "answer": answer,
            "timestamp": datetime.now().isoformat(),
            "model": CHAT_MODEL,
            "context_used": bool(context_text)
        }

    except Exception as e:
        logger.error(f"文献问答失败: {e}")
        return {
            "success": False,
            "answer": f"抱歉，回答问题失败: {str(e)}",
            "error": str(e)
        }


if __name__ == "__main__":
    # 测试文献解析
    test_text = """
    Title: Cryo-EM structure of the SARS-CoV-2 spike glycoprotein
    Authors: Wrapp D, Wang N, Corbett KS, Goldsmith JA, Hsieh CL, Abiona O, Graham BS, McLellan JS
    Journal: Science
    Date: 2020-03-13
    DOI: 10.1126/science.abb2507
    Keywords: SARS-CoV-2; spike protein; cryo-EM; structure; vaccine design
    
    Abstract:
    The emergence of SARS-CoV-2 has resulted in a global pandemic. The spike (S) glycoprotein, which forms a trimer on the viral surface, mediates viral entry into host cells and is a major target for vaccine development.
    
    Key Findings:
    1. The SARS-CoV-2 spike glycoprotein exhibits a prefusion conformation.
    2. The receptor-binding domain (RBD) displays both "up" and "down" conformations.
    3. SARS-CoV-2 S binds human ACE2 with ~10-20 fold higher affinity than SARS-CoV S.
    """
    
    result = parse_text_with_llm(test_text)
    print("文献解析结果:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # 测试问答
    print("\n测试问答...")
    answer = ask_literature_question("这篇文献的主要发现是什么？", test_text)
    print(f"回答: {answer['answer'][:200]}...")