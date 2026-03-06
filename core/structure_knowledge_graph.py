# structure_knowledge_graph.py - 结构知识图谱系统（增强版：集成UniProt，专注靶点信息）
import os, json, logging, time, re, math
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set, Union
from datetime import datetime
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from enum import Enum
import networkx as nx
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt
import hashlib
import random
import warnings
warnings.filterwarnings('ignore')

# 尝试导入UniProt模块
try:
    from core.uniprot_client import (
        UniProtAPIClient, UniProtNormalizer, UniProtEntry,
        get_uniprot_client, get_uniprot_normalizer
    )
    HAS_UNIPROT = True
except ImportError as e:
    HAS_UNIPROT = False
    logger = logging.getLogger(__name__)
    logger.warning(f"无法导入UniProt模块: {e}")

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------- 数据类型定义 ----------
class NodeType(Enum):
    """节点类型枚举"""
    STRUCTURE = "structure"      # 结构节点（PDB/EMDB）
    LITERATURE = "literature"    # 文献节点
    PROTEIN = "protein"          # 蛋白质节点
    ORGANISM = "organism"        # 生物体节点
    AUTHOR = "author"            # 作者节点
    METHOD = "method"            # 方法节点（冷冻电镜/X射线等）
    RESOLUTION = "resolution"    # 分辨率节点
    UNIPROT = "uniprot"          # UniProt节点

class EdgeType(Enum):
    """边类型枚举"""
    CONTAINS = "contains"            # 文献包含结构
    REFERENCES = "references"        # 结构被文献引用
    CO_OCCURS = "co_occurs"         # 结构共现
    SIMILAR = "similar"             # 结构相似
    RELATED = "related"             # 相关结构
    SAME_PROTEIN = "same_protein"   # 相同蛋白质
    SAME_ORGANISM = "same_organism" # 相同生物体
    AUTHORED = "authored"           # 作者撰写文献
    USED_METHOD = "used_method"     # 使用的方法
    HAS_RESOLUTION = "has_resolution" # 具有的分辨率
    MAPS_TO_UNIPROT = "maps_to_uniprot" # 映射到UniProt
    SAME_FAMILY = "same_family"     # 相同蛋白质家族
    FUNCTIONALLY_SIMILAR = "functionally_similar" # 功能相似

@dataclass
class GraphNode:
    """知识图谱节点"""
    id: str
    node_type: NodeType
    label: str
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def __hash__(self):
        return hash((self.id, self.node_type))
    
    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "type": self.node_type.value,
            "label": self.label,
            "properties": self.properties
        }

@dataclass
class GraphEdge:
    """知识图谱边"""
    source: str
    target: str
    edge_type: EdgeType
    weight: float = 1.0
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def __hash__(self):
        return hash((self.source, self.target, self.edge_type))
    
    def to_dict(self):
        """转换为字典"""
        return {
            "source": self.source,
            "target": self.target,
            "type": self.edge_type.value,
            "weight": self.weight,
            "properties": self.properties
        }

@dataclass
class StructureFeature:
    """结构特征向量"""
    structure_id: str
    features: Dict[str, float]
    
    def to_vector(self, feature_names: List[str]) -> np.ndarray:
        """转换为特征向量"""
        vector = []
        for name in feature_names:
            vector.append(self.features.get(name, 0.0))
        return np.array(vector)

# ---------- UniProt增强的蛋白质家族分类器 ----------
class EnhancedProteinFamilyClassifier:
    """增强的蛋白质家族分类器（集成UniProt，专注靶点信息）"""
    
    def __init__(self):
        # 蛋白质家族关键词定义（基于蛋白质功能和结构）- 精确版
        self.protein_family_patterns = {
            "gpcr": {
                "keywords": [
                    "g protein-coupled receptor", "g protein coupled receptor",
                    "gpc receptor", "7tm receptor", "seven transmembrane",
                    "class a gpc", "class b gpc", "class c gpc",
                    "adrenergic receptor", "dopamine receptor", "serotonin receptor",
                    "opioid receptor", "chemokine receptor", "rhodopsin",
                    "metabotropic glutamate receptor", "muscarinic receptor",
                    "histamine receptor", "prostanoid receptor", "gpr"
                ],
                "required_words": ["gpc", "receptor", "7tm"],  # 必须包含其中一个
                "exclude_words": ["tyrosine kinase", "cytokine receptor", "enzyme", "kinase", "atpase", "phosphatase"]
            },
            "ion_channel": {
                "keywords": [
                    "ion channel", "potassium channel", "sodium channel", 
                    "calcium channel", "chloride channel", "trp channel",
                    "voltage-gated channel", "ligand-gated channel", 
                    "k channel", "na channel", "ca channel", "cl channel",
                    "channel protein", "porin", "aquaporin", "mechanosensitive channel"
                ],
                "required_words": ["channel"],
                "exclude_words": ["water channel", "transporter", "pump", "receptor"]
            },
            "enzyme": {
                "keywords": [
                    "kinase", "polymerase", "transferase", "hydrolase", 
                    "ligase", "lyase", "isomerase", "oxidoreductase",
                    "protease", "phosphatase", "dehydrogenase", "synthase",
                    "phosphorylase", "reductase", "oxygenase", "catalytic",
                    "enzymatic", "atpase", "gtpase", "ribonuclease", "dna polymerase"
                ],
                "required_words": ["ase", "catalytic", "enzyme"],  # 酶通常以"ase"结尾或包含这些词
                "exclude_words": ["receptor", "channel", "transporter", "structural"]
            },
            "transporter": {
                "keywords": [
                    "transporter", "carrier", "symporter", "antiporter",
                    "abc transporter", "atp-binding cassette", "solute carrier",
                    "uptake", "efflux", "pump", "exchanger", "transport protein",
                    "membrane transport", "sodium-glucose transporter", "glucose transporter"
                ],
                "required_words": ["transporter", "carrier", "pump"],
                "exclude_words": ["ion channel", "receptor", "enzyme"]
            },
            "cytoskeleton": {
                "keywords": [
                    "cytoskeleton", "actin", "tubulin", "microtubule",
                    "centriole", "centrosome", "central apparatus", "axoneme",
                    "cilia", "flagella", "dynein", "kinesin", "myosin",
                    "intermediate filament", "microfilament", "filament", "centrin",
                    "spindle", "mitotic", "cytoskeletal"
                ],
                "required_words": ["cytoskeleton", "actin", "tubulin", "dynein", "kinesin", "myosin"],
                "exclude_words": ["receptor", "enzyme", "channel"]
            },
            "virus": {
                "keywords": [
                    "virus", "viral", "capsid", "spike", "envelope",
                    "coronavirus", "influenza", "hiv", "sars-cov-2",
                    "viral protein", "viral particle", "virion", "viral capsid",
                    "viral envelope", "viral polymerase", "viral protease"
                ],
                "required_words": ["virus", "viral"],
                "exclude_words": ["antiviral", "host"]
            },
            "antibody": {
                "keywords": [
                    "antibody", "fab", "fc", "cdr", "antigen",
                    "immunoglobulin", "scfv", "nanobody", "single-chain",
                    "heavy chain", "light chain", "variable region", "constant region",
                    "antigen-binding", "complementarity-determining region"
                ],
                "required_words": ["antibody", "fab", "fc", "immunoglobulin", "nanobody"],
                "exclude_words": ["receptor", "enzyme", "channel", "structural"]
            },
            "membrane_protein": {
                "keywords": [
                    "membrane protein", "integral membrane protein",
                    "transmembrane", "membrane-spanning", "lipid bilayer",
                    "membrane anchor", "membrane-associated"
                ],
                "required_words": ["membrane protein", "transmembrane", "membrane-spanning"],
                "exclude_words": ["ion channel", "transporter", "gpcr", "receptor", "enzyme"]
            },
            "transcription_factor": {
                "keywords": [
                    "transcription factor", "dna-binding", "rna polymerase",
                    "promoter", "enhancer", "repressor", "activator",
                    "transcriptional regulator", "dna-binding domain",
                    "transcription activator", "transcription repressor"
                ],
                "required_words": ["transcription factor", "dna-binding", "transcriptional"],
                "exclude_words": ["receptor", "enzyme", "channel"]
            }
        }
        
        # 缓存分类结果
        self.classification_cache = {}
        
        # UniProt客户端
        self.uniprot_client = None
        self.uniprot_normalizer = None
        self.uniprot_cache = {}
        
        if HAS_UNIPROT:
            try:
                from core.uniprot_client import get_uniprot_client, get_uniprot_normalizer
                self.uniprot_client = get_uniprot_client()
                self.uniprot_normalizer = get_uniprot_normalizer()
                logger.info("✅ UniProt客户端初始化完成")
            except Exception as e:
                logger.warning(f"UniProt客户端初始化失败: {e}")
        
        logger.info("✅ 增强蛋白质家族分类器初始化（专注靶点信息）")
    
    def extract_protein_name_from_title(self, title: str) -> str:
        """改进的蛋白质名称提取算法"""
        if not title:
            return ""
        
        # 移除常见的描述性词语 - 更全面的列表
        patterns_to_remove = [
            r"cryo[\-\s]?em structure of",
            r"crystal structure of", 
            r"solution structure of",
            r"atomic structure of",
            r"structure of the",
            r"structural basis of",
            r"structural insights into",
            r"structure and mechanism of",
            r"structure and function of",
            r"the structure of",
            r"structural characterization of",
            r"insights into the structure of",
            r"structural elucidation of",
            r"structural analysis of",
            r"high-resolution structure of",
            r"molecular structure of",
            r"detailed structure of"
        ]
        
        clean_title = title.lower()
        for pattern in patterns_to_remove:
            clean_title = re.sub(pattern, "", clean_title, flags=re.IGNORECASE)
        
        # 提取带数字的蛋白质名称（如GPR158, EGFR1）
        protein_patterns = [
            r'\b([A-Z]{2,}[0-9]{2,}[A-Z0-9]*)\b',  # GPR158, ABCB1
            r'\b([A-Z]{3,}[0-9]{3,})\b',           # GPR158
            r'\b([A-Z]+[0-9]+[A-Z]*)\b',           # p53, Akt1
            r'\b([A-Z][a-z]+[A-Z][a-z]+)\b',       # CamelCase names
            r'\b(?:[A-Z][a-z]+)+\b',               # Multi-word names
        ]
        
        for pattern in protein_patterns:
            matches = re.findall(pattern, title)
            if matches:
                # 过滤掉常见的非蛋白质词汇
                exclude_words = [
                    'Structure', 'Human', 'Mouse', 'Rat', 'Cryo', 'Electron',
                    'Microscopy', 'Resolution', 'Complex', 'Binding', 'Domain',
                    'Crystal', 'Solution', 'Atomic', 'Molecular', 'Insights',
                    'Mechanism', 'Function', 'Basis', 'Characterization',
                    'Elucidation', 'Analysis', 'The', 'And', 'Of', 'Into',
                    'From', 'With', 'For', 'By', 'Using', 'Reveals', 'Shows'
                ]
                
                for match in matches:
                    if isinstance(match, tuple):
                        match = match[0]
                    
                    if match and len(match) > 2:
                        # 检查是否是蛋白质样名称
                        is_protein_like = (
                            not any(exclude.lower() in match.lower() for exclude in exclude_words) and
                            len(match) >= 3 and
                            not match.lower().endswith(('ase', 'in', 'oid', 'ion', 'ment', 'ity', 'ness'))  # 常见后缀
                        )
                        if is_protein_like:
                            return match
        
        # 如果没找到，尝试提取标题中的第一个名词短语
        words = clean_title.split()
        if len(words) > 0:
            # 返回第一个看起来像蛋白质的词
            for word in words:
                if len(word) >= 4 and word[0].islower():
                    continue  # 跳过小写开头的
                if word not in ['and', 'the', 'with', 'for', 'from', 'into', 'onto', 'using', 'by']:
                    # 检查是否可能是蛋白质名称
                    if len(word) >= 4 and not word.endswith(('tion', 'ment', 'ness', 'ity', 'ance', 'ence')):
                        return word.title()
        
        return ""
    
    def _classify_by_protein_name_heuristic(self, protein_name: str) -> List[str]:
        """基于蛋白质名称的启发式分类 - 改进版"""
        name_upper = protein_name.upper()
        
        # GPCR家族 - 更精确的匹配
        if (name_upper.startswith("GPR") or 
            name_upper.startswith("GPCR") or 
            name_upper.endswith("R") and len(name_upper) >= 4):
            
            # 检查是否是已知的GPCR
            gpcr_names = ["GPR", "GPCR", "ADGR", "ADRA", "ADRB", "DRD", "HTR", 
                         "OPRM", "OPRD", "CXCR", "CCR", "FPR", "NTSR", "SSTR",
                         "PTHR", "VIPR", "GIPR", "GLPR", "GHRHR", "MC"]
            if any(gpcr_name in name_upper for gpcr_name in gpcr_names):
                return ["gpcr"]
        
        # 离子通道
        channel_keywords = ["CHANNEL", "SLC", "TRP", "KCN", "SCN", "CACN", "CLCN", "AQP", "ANO"]
        if any(keyword in name_upper for keyword in channel_keywords):
            return ["ion_channel"]
        
        # 转运蛋白
        if (name_upper.startswith("SLC") or 
            "TRANSPORTER" in name_upper or 
            name_upper.startswith("ABC")):
            return ["transporter"]
        
        # 激酶和其他酶
        if (name_upper.endswith("KINASE") or 
            name_upper.endswith("ASE") or 
            (name_upper.endswith("K") and len(name_upper) >= 3 and name_upper not in ["ACK", "ASK"])):
            
            # 排除非酶的情况
            if not any(non_enzyme in name_upper for non_enzyme in ["CHANNEL", "RECEPTOR", "TRANSPORTER", "ACTIN", "TUBULIN"]):
                return ["enzyme"]
        
        # 转录因子
        if name_upper.endswith("TF") or "FACTOR" in name_upper:
            return ["transcription_factor"]
        
        # 细胞骨架蛋白
        if (name_upper.startswith("ACT") or 
            name_upper.startswith("TUB") or 
            name_upper.startswith("MYH") or 
            name_upper.startswith("DY") or  # dynein
            name_upper.startswith("KIF") or  # kinesin
            "DYNEIN" in name_upper or 
            "KINESIN" in name_upper or
            "MYOSIN" in name_upper):
            return ["cytoskeleton"]
        
        # 病毒蛋白
        if "VIRAL" in name_upper or name_upper.endswith("VIR") or "CAPSID" in name_upper:
            return ["virus"]
        
        # 抗体
        if name_upper.startswith("IG") or name_upper.endswith("AB") or "ANTIBODY" in name_upper:
            return ["antibody"]
        
        return []
    
    def classify_with_uniprot(self, structure_id: str, metadata: Dict[str, Any]) -> List[str]:
        """使用UniProt信息进行增强分类 - 改进版"""
        logger.debug(f"开始分类结构: {structure_id}")
        
        # 首先尝试从UniProt获取最准确的分类
        if not structure_id.startswith('EMD') and HAS_UNIPROT and self.uniprot_client:
            uniprot_info = self._get_uniprot_info(structure_id)
            if uniprot_info and uniprot_info.get('protein_families'):
                # 使用UniProt的蛋白质家族信息
                families = self._classify_from_uniprot_families(uniprot_info['protein_families'])
                if families and families != ["unknown"]:
                    logger.debug(f"{structure_id}: UniProt分类 -> {families}")
                    return families
        
        # 如果UniProt没有信息，使用基础分类
        base_families = self.classify_from_metadata(metadata)
        
        # 对于EMDB结构，尝试通过蛋白质名称查找
        if structure_id.startswith('EMD'):
            protein_name = self.extract_protein_name_from_title(metadata.get("title", ""))
            if protein_name and protein_name != "Unknown" and HAS_UNIPROT and self.uniprot_client:
                search_results = self.uniprot_client.search_by_protein_name(protein_name, limit=1)
                if search_results:
                    best_match = search_results[0]
                    uniprot_entry = self.uniprot_client.get_by_uniprot_id(best_match['uniprot_id'])
                    if uniprot_entry and hasattr(uniprot_entry, 'protein_families') and uniprot_entry.protein_families:
                        families = self._classify_from_uniprot_families(uniprot_entry.protein_families)
                        if families and families != ["unknown"]:
                            logger.debug(f"{structure_id} (EMDB): 通过名称找到UniProt分类 -> {families}")
                            return families
        
        # 验证分类结果
        validated_families = self._validate_classification(structure_id, base_families, metadata)
        
        logger.debug(f"{structure_id}: 最终分类结果 -> {validated_families}")
        return validated_families
    
    def _classify_from_uniprot_families(self, protein_families: List[str]) -> List[str]:
        """从UniProt的蛋白质家族列表分类"""
        if not protein_families:
            return ["unknown"]
        
        families_set = set()
        
        for family in protein_families:
            family_lower = family.lower()
            
            # 映射到我们的分类体系
            if any(keyword in family_lower for keyword in ['gpcr', 'g protein-coupled', '7tm', 'metabotropic', 'adrenergic']):
                families_set.add('gpcr')
            elif any(keyword in family_lower for keyword in ['ion channel', 'channel', 'aquaporin', 'porin']):
                families_set.add('ion_channel')
            elif any(keyword in family_lower for keyword in ['kinase', 'transferase', 'hydrolase', 'enzyme', 'protease', 'phosphatase']):
                families_set.add('enzyme')
            elif any(keyword in family_lower for keyword in ['transporter', 'carrier', 'pump', 'exchanger']):
                families_set.add('transporter')
            elif any(keyword in family_lower for keyword in ['cytoskeleton', 'actin', 'tubulin', 'dynein', 'kinesin', 'myosin']):
                families_set.add('cytoskeleton')
            elif any(keyword in family_lower for keyword in ['transcription factor', 'dna-binding', 'transcriptional']):
                families_set.add('transcription_factor')
            elif any(keyword in family_lower for keyword in ['viral', 'capsid', 'spike']):
                families_set.add('virus')
            elif any(keyword in family_lower for keyword in ['antibody', 'immunoglobulin', 'fab', 'fc']):
                families_set.add('antibody')
            elif any(keyword in family_lower for keyword in ['membrane protein', 'transmembrane']):
                families_set.add('membrane_protein')
        
        # 如果没有匹配到任何家族，返回unknown
        if not families_set:
            return ["unknown"]
        
        return list(families_set)
    
    def classify_from_metadata(self, metadata: Dict[str, Any]) -> List[str]:
        """从元数据自动分类蛋白质家族 - 改进版"""
        metadata_key = str(metadata)
        if metadata_key in self.classification_cache:
            return self.classification_cache[metadata_key]
        
        # 提取关键文本信息
        title = metadata.get("title", "").lower()
        organism = metadata.get("organism", "").lower()
        
        if not title:
            self.classification_cache[metadata_key] = ["unknown"]
            return ["unknown"]
        
        # 首先尝试基于蛋白质名称的启发式分类
        protein_name = self.extract_protein_name_from_title(metadata.get("title", ""))
        if protein_name and protein_name != "Unknown":
            heuristic_families = self._classify_by_protein_name_heuristic(protein_name)
            if heuristic_families:
                # 验证启发式分类
                for family in heuristic_families:
                    pattern = self.protein_family_patterns.get(family)
                    if pattern and pattern.get("exclude_words"):
                        # 检查是否有排除词
                        if any(exclude in title for exclude in pattern["exclude_words"]):
                            logger.debug(f"启发式分类被排除词否决: {protein_name} -> {heuristic_families}")
                            heuristic_families = []
                            break
                
                if heuristic_families:
                    self.classification_cache[metadata_key] = heuristic_families
                    logger.debug(f"启发式分类: {protein_name} -> {heuristic_families}")
                    return heuristic_families
        
        # 基于关键词的详细分类
        family_scores = {}
        
        for family_name, pattern in self.protein_family_patterns.items():
            score = 0.0
            
            # 1. 检查排除词（如果有排除词，直接跳过该家族）
            if pattern["exclude_words"]:
                if any(exclude in title for exclude in pattern["exclude_words"]):
                    continue
            
            # 2. 检查必选词（如果有必选词，必须至少匹配一个）
            if pattern["required_words"]:
                required_matched = False
                for req_word in pattern["required_words"]:
                    if req_word in title:
                        required_matched = True
                        score += 3.0  # 必选词匹配给予高分
                        break
                
                if not required_matched:
                    continue  # 如果没有匹配必选词，跳过该家族
            
            # 3. 检查关键词匹配
            keywords = pattern["keywords"]
            keyword_matches = []
            
            for keyword in keywords:
                if keyword in title:
                    keyword_matches.append(keyword)
            
            # 根据匹配的关键词数量和长度计算分数
            if keyword_matches:
                # 长关键词给予更高权重
                total_keyword_length = sum(len(kw) for kw in keyword_matches)
                score += len(keyword_matches) * 1.0  # 每个匹配加1.0分
                score += total_keyword_length * 0.1  # 每个字符加0.1分
            
            # 4. 基于生物体的加分
            if family_name == "virus" and ("virus" in organism or "viral" in organism):
                score += 2.0
            elif family_name == "antibody" and ("antibody" in organism or "immunoglobulin" in organism):
                score += 1.0
            
            # 5. 基于蛋白质名称的额外加分
            if protein_name:
                name_upper = protein_name.upper()
                if family_name == "gpcr" and ("GPR" in name_upper or "GPCR" in name_upper):
                    score += 2.0
                elif family_name == "enzyme" and name_upper.endswith("ASE"):
                    score += 1.5
                elif family_name == "ion_channel" and "CHANNEL" in name_upper:
                    score += 1.5
                elif family_name == "transporter" and ("SLC" in name_upper or "TRANSPORTER" in name_upper):
                    score += 1.5
            
            if score > 0:
                family_scores[family_name] = score
        
        # 根据分数选择家族
        families = []
        
        if family_scores:
            # 按分数排序
            sorted_families = sorted(family_scores.items(), key=lambda x: x[1], reverse=True)
            
            # 只选择分数最高的家族，且分数必须超过阈值
            top_family, top_score = sorted_families[0]
            
            if top_score >= 3.0:  # 提高阈值，确保准确性
                families = [top_family]
                
                # 只有在分数非常接近且都超过阈值时才考虑多个家族
                if len(sorted_families) > 1:
                    second_family, second_score = sorted_families[1]
                    if second_score >= 3.0 and (top_score - second_score) < 0.5:
                        # 两个家族分数非常接近，都包含
                        families = [top_family, second_family]
            
            logger.debug(f"关键词分类: {protein_name if protein_name else 'N/A'} -> {families} (分数: {family_scores})")
        
        # 如果没有家族达到阈值，尝试基于特征推断
        if not families:
            inferred_family = self._infer_family_from_features(title, organism, protein_name)
            if inferred_family:
                families = [inferred_family]
                logger.debug(f"特征推断分类: {protein_name if protein_name else 'N/A'} -> {families}")
            else:
                families = ["unknown"]
                logger.debug(f"未分类: {protein_name if protein_name else 'N/A'} -> unknown")
        
        # 缓存结果
        self.classification_cache[metadata_key] = families
        
        return families
    
    def _infer_family_from_features(self, title: str, organism: str, protein_name: str = "") -> Optional[str]:
        """根据特征推断蛋白质家族 - 改进版"""
        # 基于生物体推断
        if "virus" in organism or "viral" in organism:
            return "virus"
        
        # 基于蛋白质名称推断
        if protein_name:
            heuristic = self._classify_by_protein_name_heuristic(protein_name)
            if heuristic:
                return heuristic[0]
        
        # 基于标题中的关键词模式
        title_lower = title.lower()
        
        # 检查GPCR特定模式
        gpcr_patterns = ["g protein-coupled", "gpc receptor", "7tm", "seven transmembrane", "metabotropic"]
        if any(pattern in title_lower for pattern in gpcr_patterns):
            return "gpcr"
        
        # 检查酶特定模式
        enzyme_patterns = ["catalytic domain", "enzyme activity", "kinase domain", "phosphatase activity", "active site"]
        if any(pattern in title_lower for pattern in enzyme_patterns):
            return "enzyme"
        
        # 检查离子通道特定模式
        channel_patterns = ["ion channel", "channel protein", "pore-forming", "selectivity filter", "gating mechanism"]
        if any(pattern in title_lower for pattern in channel_patterns):
            return "ion_channel"
        
        # 检查转运蛋白
        if "transporter" in title_lower and "channel" not in title_lower and "receptor" not in title_lower:
            return "transporter"
        
        # 检查抗体
        antibody_patterns = ["fab fragment", "fc region", "antigen binding", "cdr loop", "variable domain"]
        if any(pattern in title_lower for pattern in antibody_patterns):
            return "antibody"
        
        # 检查细胞骨架
        cytoskeleton_patterns = ["microtubule", "actin filament", "cytoskeletal", "axonemal", "centriole", "centrosome"]
        if any(pattern in title_lower for pattern in cytoskeleton_patterns):
            return "cytoskeleton"
        
        # 检查膜蛋白
        if "membrane protein" in title_lower and not any(pattern in title_lower for pattern in ["channel", "transporter", "receptor"]):
            return "membrane_protein"
        
        # 检查转录因子
        if "transcription factor" in title_lower or "dna-binding" in title_lower:
            return "transcription_factor"
        
        return None
    
    def _get_uniprot_info(self, pdb_id: str) -> Optional[Dict[str, Any]]:
        """获取PDB结构的UniProt信息 - 改进版"""
        if not self.uniprot_client:
            return None
        
        try:
            # 检查缓存
            if pdb_id in self.uniprot_cache:
                return self.uniprot_cache[pdb_id]
            
            # 通过PDB ID查找UniProt条目
            entries = self.uniprot_client.get_by_pdb_id(pdb_id)
            if not entries:
                logger.debug(f"未找到UniProt条目: {pdb_id}")
                return None
            
            # 取第一个条目
            entry = entries[0]
            
            # 确保所有字段都有默认值
            uniprot_info = {
                'uniprot_id': entry.uniprot_id if hasattr(entry, 'uniprot_id') else '',
                'protein_name': entry.protein_name if hasattr(entry, 'protein_name') else '',
                'gene_names': entry.gene_names if hasattr(entry, 'gene_names') else [],
                'protein_families': entry.protein_families if hasattr(entry, 'protein_families') else [],
                'gene_ontology': entry.gene_ontology if hasattr(entry, 'gene_ontology') else {},
                'function': entry.function if hasattr(entry, 'function') else '',
                'subcellular_locations': entry.subcellular_locations if hasattr(entry, 'subcellular_locations') else [],
                'domains': entry.domains if hasattr(entry, 'domains') else [],
                'interactions': entry.interactions if hasattr(entry, 'interactions') else [],
                'disease_associations': entry.disease_associations if hasattr(entry, 'disease_associations') else [],
                'organism': entry.organism if hasattr(entry, 'organism') else ''
            }
            
            # 缓存结果
            self.uniprot_cache[pdb_id] = uniprot_info
            logger.debug(f"获取UniProt信息成功: {pdb_id} -> {uniprot_info.get('protein_name', 'N/A')}")
            return uniprot_info
            
        except Exception as e:
            logger.debug(f"获取UniProt信息失败 {pdb_id}: {e}")
            return None
    
    def _validate_classification(self, structure_id: str, families: List[str], metadata: Dict[str, Any]) -> List[str]:
        """验证和修正分类结果"""
        if not families or families == ["unknown"]:
            # 尝试其他方法
            protein_name = metadata.get("protein_name", "") or self.extract_protein_name_from_title(metadata.get("title", ""))
            if protein_name:
                # 基于蛋白质名称的二次分类
                heuristic = self._classify_by_protein_name_heuristic(protein_name)
                if heuristic and heuristic != ["unknown"]:
                    return heuristic
        
        # 检查是否有多重分类但矛盾
        if len(families) > 1:
            # 检查是否有矛盾组合
            contradiction_pairs = [
                ("gpcr", "enzyme"),
                ("gpcr", "ion_channel"),
                ("enzyme", "ion_channel"),
                ("enzyme", "transporter"),
                ("antibody", "enzyme"),
                ("antibody", "receptor")
            ]
            
            # 查找矛盾
            for family1, family2 in contradiction_pairs:
                if family1 in families and family2 in families:
                    # 根据优先级选择
                    priority_order = ["virus", "antibody", "gpcr", "ion_channel", "enzyme", "transporter", "cytoskeleton", "membrane_protein", "transcription_factor"]
                    
                    for priority_family in priority_order:
                        if priority_family in families:
                            logger.debug(f"检测到矛盾分类 {families}，选择 {priority_family}")
                            return [priority_family]
        
        return families
    
    def extract_protein_features_from_uniprot(self, uniprot_entry) -> Dict[str, float]:
        """从UniProt条目提取蛋白质特征（专注靶点信息）"""
        features = {}
        
        try:
            # 1. 蛋白质家族和类别
            if hasattr(uniprot_entry, 'protein_families') and uniprot_entry.protein_families:
                families = uniprot_entry.protein_families
                features['family_count'] = min(len(families), 10) / 10.0
                
                # 主要的蛋白质家族
                primary_family_keywords = [
                    'gpcr', 'receptor', 'ion channel', 'transporter',
                    'kinase', 'enzyme', 'transcription factor',
                    'cytoskeleton', 'membrane protein', 'viral protein'
                ]
                
                for keyword in primary_family_keywords:
                    features[f'family_{keyword}'] = 1.0 if any(keyword in f.lower() for f in families) else 0.0
            
            # 2. 功能描述特征
            if hasattr(uniprot_entry, 'function') and uniprot_entry.function:
                func_text = str(uniprot_entry.function).lower()
                
                # 功能关键词
                func_keywords = {
                    'receptor_activity': ['receptor', 'ligand binding', 'signal transduction'],
                    'enzyme_activity': ['enzyme', 'catalytic', 'kinase', 'phosphatase'],
                    'transporter_activity': ['transporter', 'channel', 'carrier', 'pump'],
                    'binding_activity': ['binding', 'protein-protein', 'dna-binding', 'rna-binding'],
                    'structural_role': ['structural', 'scaffold', 'cytoskeleton'],
                    'regulatory_role': ['regulatory', 'inhibitor', 'activator', 'modulator']
                }
                
                for func_type, keywords in func_keywords.items():
                    features[f'func_{func_type}'] = 1.0 if any(keyword in func_text for keyword in keywords) else 0.0
            
            # 3. 结构域特征
            if hasattr(uniprot_entry, 'domains') and uniprot_entry.domains:
                domains = uniprot_entry.domains
                features['domain_count'] = min(len(domains), 20) / 20.0
                
                # 常见结构域类型
                domain_types = [
                    'transmembrane', 'extracellular', 'cytoplasmic',
                    'catalytic', 'binding', 'regulatory',
                    'signal peptide', 'nucleotide-binding', 'zinc finger'
                ]
                
                for domain_type in domain_types:
                    features[f'domain_{domain_type}'] = 1.0 if any(domain_type in d.lower() for d in domains) else 0.0
            
            # 4. 亚细胞定位特征
            if hasattr(uniprot_entry, 'subcellular_locations') and uniprot_entry.subcellular_locations:
                locations = uniprot_entry.subcellular_locations
                
                location_types = [
                    'membrane', 'cytoplasm', 'nucleus', 'mitochondria',
                    'endoplasmic reticulum', 'golgi', 'extracellular',
                    'plasma membrane', 'vesicle', 'cytoskeleton'
                ]
                
                for loc_type in location_types:
                    features[f'location_{loc_type}'] = 1.0 if any(loc_type in loc.lower() for loc in locations) else 0.0
            
            # 5. 相互作用特征
            if hasattr(uniprot_entry, 'interactions') and uniprot_entry.interactions:
                interactions = uniprot_entry.interactions
                features['interaction_count'] = min(len(interactions), 50) / 50.0
            
            # 6. 序列特征（简化）
            if hasattr(uniprot_entry, 'sequence') and uniprot_entry.sequence:
                seq = uniprot_entry.sequence
                features['sequence_length'] = min(len(seq), 5000) / 5000.0
            
            # 7. 保守性特征（基于基因本体）
            if hasattr(uniprot_entry, 'gene_ontology') and uniprot_entry.gene_ontology:
                go = uniprot_entry.gene_ontology
                go_terms = 0
                
                for go_type in ['biological_process', 'molecular_function', 'cellular_component']:
                    if go_type in go:
                        go_terms += len(go[go_type])
                
                features['go_terms'] = min(go_terms, 30) / 30.0
            
            return features
            
        except Exception as e:
            logger.debug(f"提取UniProt蛋白质特征失败: {e}")
            return {}
    
    def analyze_structure_collection(self, structures_metadata: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """分析结构集合的蛋白质家族分布"""
        family_counts = Counter()
        family_structures = defaultdict(list)
        
        for struct_id, metadata in structures_metadata.items():
            # 使用增强分类（如果可用）
            if struct_id.startswith('EMD'):
                families = self.classify_from_metadata(metadata)
            else:
                families = self.classify_with_uniprot(struct_id, metadata)
            
            for family in families:
                family_counts[family] += 1
                family_structures[family].append(struct_id)
        
        # 计算百分比
        total_structures = len(structures_metadata)
        family_percentages = {
            family: (count / total_structures * 100) 
            for family, count in family_counts.items()
        }
        
        # 统计UniProt覆盖率
        uniprot_coverage = 0
        for struct_id in structures_metadata:
            if struct_id.startswith('EMD'):
                continue
            if struct_id in self.uniprot_cache and self.uniprot_cache[struct_id]:
                uniprot_coverage += 1
        
        # 分析unknown分类的原因
        unknown_structures = family_structures.get("unknown", [])
        unknown_analysis = []
        for struct_id in unknown_structures[:10]:  # 分析前10个
            if struct_id in structures_metadata:
                metadata = structures_metadata[struct_id]
                protein_name = self.extract_protein_name_from_title(metadata.get("title", ""))
                unknown_analysis.append({
                    "structure_id": struct_id,
                    "title": metadata.get("title", "")[:100],
                    "extracted_protein_name": protein_name
                })
        
        return {
            "family_distribution": dict(family_counts),
            "family_percentages": family_percentages,
            "family_structures": dict(family_structures),
            "total_structures": total_structures,
            "unique_families": len(family_counts),
            "uniprot_coverage": uniprot_coverage,
            "uniprot_coverage_percentage": (uniprot_coverage / total_structures * 100) if total_structures > 0 else 0,
            "unknown_analysis": unknown_analysis[:5]  # 只返回前5个分析
        }

# ---------- 结构知识图谱（专注靶点信息） ----------
class StructureKnowledgeGraph:
    """结构知识图谱（专注靶点信息）"""
    
    def __init__(self, graph_name: str = "structure_knowledge_graph"):
        self.graph_name = graph_name
        self.graph = nx.MultiDiGraph()  # 使用有向多重图
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: Dict[Tuple[str, str, EdgeType], GraphEdge] = {}
        self.structure_features: Dict[str, StructureFeature] = {}
        
        # 特征提取器
        self.vectorizer = None
        self.feature_names: List[str] = []
        
        # 蛋白质家族分类器
        self.family_classifier = EnhancedProteinFamilyClassifier()
        
        # UniProt客户端
        self.uniprot_client = self.family_classifier.uniprot_client
        self.uniprot_normalizer = self.family_classifier.uniprot_normalizer
        
        # 存储路径
        self.graph_dir = Path("structure_knowledge_graphs")
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"✅ 结构知识图谱初始化: {graph_name}（专注靶点信息）")
    
    def add_node(self, node: GraphNode) -> bool:
        """添加节点"""
        if node.id in self.nodes:
            logger.debug(f"节点已存在: {node.id}")
            return False
        
        self.nodes[node.id] = node
        self.graph.add_node(
            node.id,
            type=node.node_type.value,
            label=node.label,
            **node.properties
        )
        
        return True
    
    def add_edge(self, edge: GraphEdge) -> bool:
        """添加边"""
        edge_key = (edge.source, edge.target, edge.edge_type)
        
        # 检查节点是否存在
        if edge.source not in self.nodes or edge.target not in self.nodes:
            logger.warning(f"边的节点不存在: {edge.source} -> {edge.target}")
            return False
        
        if edge_key in self.edges:
            # 更新权重（平均权重）
            existing_edge = self.edges[edge_key]
            existing_edge.weight = (existing_edge.weight + edge.weight) / 2
            existing_edge.properties.update(edge.properties)
            return True
        
        self.edges[edge_key] = edge
        self.graph.add_edge(
            edge.source,
            edge.target,
            key=edge.edge_type.value,
            type=edge.edge_type.value,
            weight=edge.weight,
            **edge.properties
        )
        
        return True
    
    def remove_node(self, node_id: str) -> bool:
        """删除节点"""
        if node_id not in self.nodes:
            return False
        
        # 删除相关边
        edges_to_remove = []
        for edge_key, edge in self.edges.items():
            if edge.source == node_id or edge.target == node_id:
                edges_to_remove.append(edge_key)
        
        for edge_key in edges_to_remove:
            del self.edges[edge_key]
        
        # 删除节点
        del self.nodes[node_id]
        self.graph.remove_node(node_id)
        
        return True
    
    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """获取节点"""
        return self.nodes.get(node_id)
    
    def get_edge(self, source: str, target: str, edge_type: EdgeType) -> Optional[GraphEdge]:
        """获取边"""
        return self.edges.get((source, target, edge_type))
    
    def get_neighbors(self, node_id: str, edge_types: Optional[List[EdgeType]] = None) -> List[GraphNode]:
        """获取邻居节点"""
        if node_id not in self.nodes:
            return []
        
        neighbors = []
        
        if edge_types:
            for edge_type in edge_types:
                if edge_type.value in self.graph[node_id]:
                    for target in self.graph[node_id][edge_type.value]:
                        if target in self.nodes:
                            neighbors.append(self.nodes[target])
        else:
            # 获取所有邻居
            for edge_type in self.graph[node_id]:
                for target in self.graph[node_id][edge_type]:
                    if target in self.nodes:
                        neighbors.append(self.nodes[target])
        
        return list(set(neighbors))  # 去重
    
    def get_edges_between(self, source: str, target: str) -> List[GraphEdge]:
        """获取两个节点之间的所有边"""
        edges = []
        
        for edge_key, edge in self.edges.items():
            if edge.source == source and edge.target == target:
                edges.append(edge)
        
        return edges
    
    def compute_structure_co_occurrence(self, literature_structures: Dict[str, List[str]]):
        """计算结构共现关系"""
        logger.info("计算结构共现关系...")
        
        # 只考虑PDB ID（4字符，第一个为数字）
        valid_pdb_ids = {}
        for lit_id, structures in literature_structures.items():
            # 过滤出有效的PDB ID
            pdb_structures = [
                s for s in structures 
                if s and len(s) == 4 and s[0].isdigit() and s.isalnum()
            ]
            if pdb_structures:
                valid_pdb_ids[lit_id] = pdb_structures
        
        # 统计结构共现
        co_occurrence: Dict[Tuple[str, str], int] = Counter()
        
        for lit_id, structures in valid_pdb_ids.items():
            structures = [s for s in structures if s]  # 过滤空值
            if len(structures) < 2:
                continue
            
            # 为每对结构添加共现计数
            for i in range(len(structures)):
                for j in range(i + 1, len(structures)):
                    struct1 = structures[i]
                    struct2 = structures[j]
                    
                    # 确保顺序一致
                    if struct1 > struct2:
                        struct1, struct2 = struct2, struct1
                    
                    key = (struct1, struct2)
                    co_occurrence[key] += 1
        
        # 添加共现边
        added_edges = 0
        for (struct1, struct2), count in co_occurrence.items():
            # 标准化权重：log(共现次数 + 1)
            weight = math.log(count + 1)
            
            edge = GraphEdge(
                source=struct1,
                target=struct2,
                edge_type=EdgeType.CO_OCCURS,
                weight=weight,
                properties={"co_occurrence_count": count}
            )
            
            if self.add_edge(edge):
                added_edges += 1
        
        logger.info(f"✅ 添加了 {added_edges} 个PDB结构共现关系")
        return added_edges
    
    def extract_structure_features_target_focused(self, structure_metadata: Dict[str, Dict[str, Any]]):
        """从结构元数据中提取特征 - 专注靶点信息"""
        logger.info("提取结构特征（专注靶点信息）...")
        
        # 记录缺失字段的统计
        missing_fields = Counter()
        
        for struct_id, metadata in structure_metadata.items():
            # 只处理PDB ID
            if len(struct_id) != 4 or not struct_id[0].isdigit() or not struct_id.isalnum():
                logger.debug(f"跳过非PDB ID: {struct_id}")
                continue
            
            features = {}
            
            # 1. 蛋白质家族特征 - 使用增强分类器
            protein_families = self.family_classifier.classify_with_uniprot(struct_id, metadata)
            
            # 为每个蛋白质家族创建特征
            all_families = list(self.family_classifier.protein_family_patterns.keys())
            
            for family in all_families:
                features[f"family_{family}"] = 1.0 if family in protein_families else 0.0
            
            # 如果检测到多个家族，添加一个特征表示这种情况
            features["multi_family"] = 1.0 if len(protein_families) > 1 else 0.0
            
            # 2. UniProt蛋白质特征（主要特征）
            uniprot_features = self._extract_protein_features(struct_id)
            if uniprot_features:
                for key, value in uniprot_features.items():
                    features[f"protein_{key}"] = value
                features["has_protein_info"] = 1.0
            else:
                features["has_protein_info"] = 0.0
            
            # 3. 生物体特征（作为背景信息，但不是主要参考）
            if 'organism' in metadata and metadata['organism'] and metadata['organism'] != "Unknown":
                org = str(metadata['organism']).lower()
                features['is_human'] = 1.0 if 'homo sapiens' in org or 'human' in org else 0.0
                features['is_mouse'] = 1.0 if 'mus musculus' in org or 'mouse' in org else 0.0
                features['is_virus'] = 1.0 if 'virus' in org else 0.0
            else:
                features['is_human'] = 0.2
                features['is_mouse'] = 0.1
                features['is_virus'] = 0.1
            
            # 4. 文本特征（从标题中提取与靶点相关的关键词）
            title = metadata.get("title", "").lower()
            
            # 靶点相关的关键词
            target_keywords = [
                'complex', 'binding', 'domain', 'protein', 'enzyme',
                'channel', 'receptor', 'transporter', 'kinase',
                'polymerase', 'centriole', 'cytoskeleton',
                'virus', 'antibody', 'membrane', 'ligand',
                'subunit', 'assembly', 'interaction'
            ]
            
            for term in target_keywords:
                features[f'title_has_{term}'] = 1.0 if term in title else 0.0
            
            # 5. 基于蛋白质名称的哈希特征（确保唯一性）
            protein_name = ""
            if 'protein_name' in metadata and metadata['protein_name']:
                protein_name = str(metadata['protein_name']).lower()
            elif 'title' in metadata:
                # 从标题提取蛋白质名称
                protein_name = self.family_classifier.extract_protein_name_from_title(metadata['title']).lower()
            
            if protein_name:
                name_hash = hash(protein_name) % 1000
                features['name_hash'] = name_hash / 1000.0
            
            # 6. 基因名特征（如果有）
            if 'gene' in metadata and metadata['gene']:
                gene_name = str(metadata['gene']).upper()
                features['has_gene_name'] = 1.0
            else:
                features['has_gene_name'] = 0.0
            
            # 7. 基于蛋白质家族的确定性特征
            if protein_families:
                family_str = "_".join(sorted(protein_families))
                family_hash = hash(family_str) % 1000
                features['family_composition_hash'] = family_hash / 1000.0
            
            # 8. 结构大小特征（基于标题推断，但不是主要特征）
            size_indicators = ['complex', 'assembly', 'multimer', 'oligomer', 'dimer', 'trimer']
            features['likely_complex'] = 1.0 if any(indicator in title for indicator in size_indicators) else 0.0
            
            # 保存特征
            if features:
                self.structure_features[struct_id] = StructureFeature(
                    structure_id=struct_id,
                    features=features
                )
            else:
                missing_fields['all_features'] += 1
        
        # 提取特征名称
        if self.structure_features:
            sample_features = next(iter(self.structure_features.values()))
            self.feature_names = list(sample_features.features.keys())
            
            # 分析蛋白质家族分布
            family_counts = Counter()
            protein_info_coverage = 0
            
            for struct_id, feature in self.structure_features.items():
                # 提取蛋白质家族
                families = []
                for family in self.family_classifier.protein_family_patterns.keys():
                    if feature.features.get(f"family_{family}", 0) > 0.5:
                        families.append(family)
                
                if families:
                    family_counts[",".join(sorted(families))] += 1
                else:
                    family_counts["unknown"] += 1
                
                # 统计蛋白质信息覆盖率
                if feature.features.get("has_protein_info", 0) > 0.5:
                    protein_info_coverage += 1
            
            logger.info(f"✅ 提取了 {len(self.structure_features)} 个PDB结构的特征")
            logger.info(f"   - 蛋白质家族分布: {dict(family_counts)}")
            logger.info(f"   - 蛋白质信息覆盖率: {protein_info_coverage}/{len(self.structure_features)} ({protein_info_coverage/len(self.structure_features)*100:.1f}%)")
            logger.info(f"   - 特征维度: {len(self.feature_names)}")
            logger.info(f"   - 特征示例: {self.feature_names[:10]}")
        else:
            logger.warning("没有提取到任何PDB结构特征")
        
        return len(self.structure_features)
    
    def _extract_protein_features(self, structure_id: str) -> Dict[str, float]:
        """提取蛋白质特征（主要参考UniProt信息）"""
        if not self.uniprot_client:
            return {}
        
        try:
            # 通过PDB ID查找UniProt条目
            entries = self.uniprot_client.get_by_pdb_id(structure_id)
            if not entries:
                return {}
            
            # 取第一个条目
            entry = entries[0]
            
            # 使用分类器提取蛋白质特征
            protein_features = self.family_classifier.extract_protein_features_from_uniprot(entry)
            
            # 添加额外的蛋白质标识特征
            if hasattr(entry, 'uniprot_id'):
                protein_features['uniprot_id_hash'] = hash(entry.uniprot_id) % 1000 / 1000.0
            
            if hasattr(entry, 'protein_name'):
                name = entry.protein_name.lower()
                # 检查名称中是否包含关键功能词
                key_function_terms = ['receptor', 'kinase', 'transporter', 'channel', 'enzyme']
                for term in key_function_terms:
                    protein_features[f'name_contains_{term}'] = 1.0 if term in name else 0.0
            
            if hasattr(entry, 'gene_names') and entry.gene_names:
                protein_features['gene_count'] = min(len(entry.gene_names), 5) / 5.0
            
            return protein_features
            
        except Exception as e:
            logger.debug(f"提取蛋白质特征失败 {structure_id}: {e}")
            return {}
    
    def compute_structure_similarity_target_focused(self, similarity_threshold: float = 0.6):
        """计算结构相似性 - 专注靶点信息"""
        if not self.structure_features or len(self.structure_features) < 2:
            logger.warning("结构特征不足，无法计算相似性")
            return 0
        
        logger.info(f"计算结构相似性 (阈值={similarity_threshold}, 专注靶点信息)...")
        
        # 构建特征矩阵 - 只使用靶点相关特征
        structure_ids = list(self.structure_features.keys())
        logger.info(f"计算 {len(structure_ids)} 个PDB结构的相似性...")
        
        # 选择靶点相关特征（以family_和protein_开头）
        target_features = [name for name in self.feature_names 
                          if name.startswith('family_') or name.startswith('protein_')]
        
        if not target_features:
            logger.warning("没有靶点相关特征，无法计算相似性")
            return 0
        
        feature_vectors = []
        valid_structure_ids = []
        
        for struct_id in structure_ids:
            feature = self.structure_features[struct_id]
            
            # 只使用靶点相关特征
            vector = np.array([feature.features.get(name, 0.0) for name in target_features])
            
            # 检查向量是否有效
            if not np.any(np.isnan(vector)) and not np.any(np.isinf(vector)):
                feature_vectors.append(vector)
                valid_structure_ids.append(struct_id)
            else:
                logger.warning(f"结构 {struct_id} 的特征向量无效，跳过")
        
        if len(feature_vectors) < 2:
            logger.warning(f"有效特征向量不足 ({len(feature_vectors)})，无法计算相似性")
            return 0
        
        feature_matrix = np.vstack(feature_vectors)
        logger.info(f"特征矩阵形状: {feature_matrix.shape}")
        logger.info(f"使用的特征数: {len(target_features)}")
        
        # 计算余弦相似度
        try:
            similarity_matrix = cosine_similarity(feature_matrix)
            logger.info(f"相似度矩阵形状: {similarity_matrix.shape}")
            
            # 添加相似边（相似度大于阈值）
            added_edges = 0
            
            for i in range(len(valid_structure_ids)):
                for j in range(i + 1, len(valid_structure_ids)):
                    similarity = similarity_matrix[i, j]
                    
                    if similarity > similarity_threshold:
                        struct1 = valid_structure_ids[i]
                        struct2 = valid_structure_ids[j]
                        
                        # 确定边的类型
                        edge_type = EdgeType.FUNCTIONALLY_SIMILAR
                        
                        edge = GraphEdge(
                            source=struct1,
                            target=struct2,
                            edge_type=edge_type,
                            weight=similarity,
                            properties={
                                "similarity_score": float(similarity),
                                "feature_type": "target_focused",
                                "shared_families": self._get_shared_families(struct1, struct2)
                            }
                        )
                        
                        if self.add_edge(edge):
                            added_edges += 1
            
            # 记录相似度统计
            if similarity_matrix.size > 0:
                non_diag = similarity_matrix[~np.eye(similarity_matrix.shape[0], dtype=bool)]
                if len(non_diag) > 0:
                    logger.info(f"相似度统计 - 最小值: {np.min(non_diag):.3f}, 最大值: {np.max(non_diag):.3f}, 平均值: {np.mean(non_diag):.3f}")
            
            logger.info(f"✅ 添加了 {added_edges} 个功能相似关系 (阈值={similarity_threshold}, 特征类型=target_focused)")
            return added_edges
            
        except Exception as e:
            logger.error(f"计算相似度失败: {e}")
            return 0
    
    def _get_shared_families(self, struct1_id: str, struct2_id: str) -> List[str]:
        """获取两个结构共享的蛋白质家族"""
        shared = []
        
        if struct1_id in self.structure_features and struct2_id in self.structure_features:
            feature1 = self.structure_features[struct1_id]
            feature2 = self.structure_features[struct2_id]
            
            for family in self.family_classifier.protein_family_patterns.keys():
                family_key = f"family_{family}"
                if (feature1.features.get(family_key, 0) > 0.5 and 
                    feature2.features.get(family_key, 0) > 0.5):
                    shared.append(family)
        
        return shared
    
    def search_similar_structures_target_focused(self, query_structure_id: str, top_k: int = 10, min_similarity: float = 0.5) -> List[Dict[str, Any]]:
        """搜索相似结构 - 专注靶点信息"""
        if query_structure_id not in self.structure_features:
            logger.warning(f"查询结构 {query_structure_id} 无特征数据")
            return []
        
        # 选择靶点相关特征
        target_features = [name for name in self.feature_names 
                          if name.startswith('family_') or name.startswith('protein_')]
        
        if not target_features:
            logger.warning("没有靶点相关特征，无法搜索相似结构")
            return []
        
        # 获取查询结构的特征
        query_feature = self.structure_features[query_structure_id]
        query_vector = np.array([query_feature.features.get(name, 0.0) for name in target_features])
        
        # 检查查询向量是否有效
        if np.any(np.isnan(query_vector)) or np.any(np.isinf(query_vector)):
            logger.warning(f"查询结构 {query_structure_id} 的特征向量无效")
            return []
        
        # 获取查询结构的蛋白质家族
        query_families = []
        for family in self.family_classifier.protein_family_patterns.keys():
            if query_feature.features.get(f"family_{family}", 0) > 0.5:
                query_families.append(family)
        
        # 获取查询结构的蛋白质特征
        query_protein_features = {}
        for key in query_feature.features:
            if key.startswith('protein_'):
                query_protein_features[key] = query_feature.features[key]
        
        # 计算与其他所有结构的相似度
        similarities = []
        
        for struct_id, feature in self.structure_features.items():
            if struct_id == query_structure_id:
                continue
            
            # 只使用靶点相关特征
            target_vector = np.array([feature.features.get(name, 0.0) for name in target_features])
            
            # 检查目标向量是否有效
            if np.any(np.isnan(target_vector)) or np.any(np.isinf(target_vector)):
                continue
            
            try:
                similarity = cosine_similarity([query_vector], [target_vector])[0][0]
                
                # 过滤相似度
                if similarity < min_similarity:
                    continue
                
                # 获取目标结构的家族
                target_families = []
                for family in self.family_classifier.protein_family_patterns.keys():
                    if feature.features.get(f"family_{family}", 0) > 0.5:
                        target_families.append(family)
                
                # 获取目标结构的蛋白质特征
                target_protein_features = {}
                for key in feature.features:
                    if key.startswith('protein_'):
                        target_protein_features[key] = feature.features[key]
                
                # 计算蛋白质特征相似度
                protein_similarity = 0.0
                common_features = set()
                if query_protein_features and target_protein_features:
                    # 提取共同的蛋白质特征
                    common_features = set(query_protein_features.keys()) & set(target_protein_features.keys())
                    if common_features:
                        # 计算加权相似度
                        total_weight = 0
                        weighted_sum = 0
                        
                        for feat in common_features:
                            weight = 1.0
                            # 家族和功能特征权重更高
                            if 'family_' in feat or 'func_' in feat:
                                weight = 2.0
                            
                            q_val = query_protein_features[feat]
                            t_val = target_protein_features[feat]
                            feat_sim = 1.0 - abs(q_val - t_val)
                            
                            weighted_sum += feat_sim * weight
                            total_weight += weight
                        
                        if total_weight > 0:
                            protein_similarity = weighted_sum / total_weight
                
                # 获取结构标签
                structure_label = self.nodes[struct_id].label if struct_id in self.nodes else struct_id
                
                similarities.append({
                    "structure_id": struct_id,
                    "similarity_score": float(similarity),
                    "protein_similarity": float(protein_similarity),
                    "label": structure_label,
                    "protein_families": target_families,
                    "common_families": list(set(query_families) & set(target_families)),
                    "has_protein_info": feature.features.get("has_protein_info", 0) > 0.5,
                    "shared_protein_features": len(common_features)
                })
            except Exception as e:
                logger.debug(f"计算与 {struct_id} 的相似度失败: {e}")
        
        # 按相似度排序（优先蛋白质相似度）
        similarities.sort(key=lambda x: (x["protein_similarity"], x["similarity_score"]), reverse=True)
        
        return similarities[:top_k]
    
    def find_structural_clusters_target_focused(self, n_clusters: int = 5) -> Dict[str, Any]:
        """发现结构聚类 - 专注靶点信息"""
        if not self.structure_features or len(self.structure_features) < 2:
            return {"clusters": [], "visualization": None, "error": "结构特征不足"}
        
        logger.info(f"发现结构聚类 (k={n_clusters}, 专注靶点信息)...")
        
        # 构建特征矩阵 - 只使用靶点相关特征
        structure_ids = list(self.structure_features.keys())
        target_features = [name for name in self.feature_names 
                          if name.startswith('family_') or name.startswith('protein_')]
        
        if not target_features:
            return {"clusters": [], "visualization": None, "error": "没有靶点相关特征"}
        
        feature_vectors = []
        valid_structure_ids = []
        
        for struct_id in structure_ids:
            feature = self.structure_features[struct_id]
            vector = np.array([feature.features.get(name, 0.0) for name in target_features])
            
            # 检查向量是否有效
            if not np.any(np.isnan(vector)) and not np.any(np.isinf(vector)):
                feature_vectors.append(vector)
                valid_structure_ids.append(struct_id)
            else:
                logger.warning(f"结构 {struct_id} 的特征向量无效，跳过")
        
        if len(feature_vectors) < 2:
            return {"clusters": [], "visualization": None, "error": "有效特征向量不足"}
        
        feature_matrix = np.vstack(feature_vectors)
        
        # 调整聚类数量
        n_clusters = min(n_clusters, len(feature_vectors))
        
        # 使用K-means聚类
        try:
            from sklearn.cluster import KMeans
            
            kmeans = KMeans(n_clusters=n_clusters, random_state=42)
            cluster_labels = kmeans.fit_predict(feature_matrix)
            
            # 统计聚类结果
            clusters = defaultdict(list)
            for struct_id, label in zip(valid_structure_ids, cluster_labels):
                # 获取蛋白质家族
                protein_families = []
                feature = self.structure_features[struct_id]
                
                for family in self.family_classifier.protein_family_patterns.keys():
                    if feature.features.get(f"family_{family}", 0) > 0.5:
                        protein_families.append(family)
                
                clusters[label].append({
                    "structure_id": struct_id,
                    "label": self.nodes[struct_id].label if struct_id in self.nodes else struct_id,
                    "protein_families": protein_families,
                    "has_protein_info": feature.features.get("has_protein_info", 0) > 0.5
                })
            
            # 计算聚类中心特征
            cluster_centers = kmeans.cluster_centers_
            
            # 转换为结果格式
            cluster_results = []
            for cluster_id, members in clusters.items():
                # 计算聚类的主要蛋白质家族
                all_families = []
                for member in members:
                    all_families.extend(member["protein_families"])
                
                family_counts = Counter(all_families)
                primary_families = [family for family, count in family_counts.most_common(3)]
                
                # 计算蛋白质信息覆盖率
                protein_info_count = sum(1 for member in members if member["has_protein_info"])
                protein_coverage = protein_info_count / len(members) if members else 0
                
                # 找到代表性结构（距离中心最近）
                cluster_indices = [i for i, label in enumerate(cluster_labels) if label == cluster_id]
                cluster_vectors = feature_matrix[cluster_indices]
                
                if len(cluster_vectors) > 0:
                    distances = np.linalg.norm(cluster_vectors - cluster_centers[cluster_id], axis=1)
                    representative_idx = np.argmin(distances)
                    representative_struct = valid_structure_ids[cluster_indices[representative_idx]]
                else:
                    representative_struct = members[0]["structure_id"] if members else ""
                
                # 分析聚类特征
                cluster_features = {}
                if cluster_vectors.size > 0:
                    # 计算平均特征值
                    avg_features = np.mean(cluster_vectors, axis=0)
                    for i, feat_name in enumerate(target_features[:10]):  # 只显示前10个特征
                        cluster_features[feat_name] = float(avg_features[i])
                
                cluster_results.append({
                    "cluster_id": cluster_id,
                    "size": len(members),
                    "representative": representative_struct,
                    "primary_families": primary_families,
                    "protein_coverage": protein_coverage,
                    "family_distribution": dict(family_counts),
                    "cluster_features": cluster_features,
                    "members": members[:15]  # 只显示前15个成员
                })
            
            # 按大小排序
            cluster_results.sort(key=lambda x: x["size"], reverse=True)
            
            # 降维可视化
            visualization = self._create_target_focused_cluster_visualization(
                feature_matrix, cluster_labels, valid_structure_ids, target_features
            )
            
            return {
                "clusters": cluster_results,
                "visualization": visualization,
                "statistics": {
                    "total_structures": len(valid_structure_ids),
                    "cluster_count": len(cluster_results),
                    "avg_cluster_size": len(valid_structure_ids) / len(cluster_results) if cluster_results else 0,
                    "avg_protein_coverage": sum(c["protein_coverage"] for c in cluster_results) / len(cluster_results) if cluster_results else 0,
                    "feature_type": "target_focused",
                    "feature_count": len(target_features)
                }
            }
            
        except Exception as e:
            logger.error(f"聚类失败: {e}")
            return {"clusters": [], "visualization": None, "error": str(e)}
    
    def _create_target_focused_cluster_visualization(self, feature_matrix, cluster_labels, structure_ids, feature_names):
        """创建专注靶点信息的聚类可视化数据"""
        try:
            # 检查输入数据
            if len(feature_matrix) < 3:
                logger.warning(f"样本数太少 ({len(feature_matrix)})，无法进行t-SNE降维")
                return None
            
            # 设置t-SNE参数
            perplexity = min(30, len(feature_matrix) - 1)
            if perplexity < 1:
                perplexity = 1
            
            # 降维到2D
            tsne = TSNE(n_components=2, random_state=42, perplexity=perplexity)
            embeddings = tsne.fit_transform(feature_matrix)
            
            # 准备可视化数据
            visualization = {
                "points": [],
                "clusters": {},
                "feature_type": "target_focused",
                "feature_count": len(feature_names)
            }
            
            # 收集每个聚类的点
            for i, struct_id in enumerate(structure_ids):
                feature = self.structure_features[struct_id]
                
                # 获取蛋白质家族
                protein_families = []
                for family in self.family_classifier.protein_family_patterns.keys():
                    if feature.features.get(f"family_{family}", 0) > 0.5:
                        protein_families.append(family)
                
                # 获取蛋白质特征强度
                protein_feature_strength = 0.0
                for feat_name in feature_names:
                    if feat_name.startswith('protein_'):
                        protein_feature_strength += feature.features.get(feat_name, 0.0)
                
                # 标准化特征强度
                if len([f for f in feature_names if f.startswith('protein_')]) > 0:
                    protein_feature_strength /= len([f for f in feature_names if f.startswith('protein_')])
                
                point = {
                    "structure_id": struct_id,
                    "label": self.nodes[struct_id].label if struct_id in self.nodes else struct_id,
                    "x": float(embeddings[i, 0]),
                    "y": float(embeddings[i, 1]),
                    "cluster": int(cluster_labels[i]),
                    "protein_families": protein_families,
                    "has_protein_info": feature.features.get("has_protein_info", 0) > 0.5,
                    "protein_feature_strength": protein_feature_strength,
                    "family_count": len(protein_families)
                }
                visualization["points"].append(point)
                
                # 统计聚类
                cluster_id = cluster_labels[i]
                if cluster_id not in visualization["clusters"]:
                    visualization["clusters"][cluster_id] = {
                        "count": 0,
                        "structures": [],
                        "families": set(),
                        "protein_info_count": 0
                    }
                visualization["clusters"][cluster_id]["count"] += 1
                visualization["clusters"][cluster_id]["structures"].append(struct_id)
                visualization["clusters"][cluster_id]["families"].update(protein_families)
                if point["has_protein_info"]:
                    visualization["clusters"][cluster_id]["protein_info_count"] += 1
            
            # 计算每个聚类的蛋白质信息覆盖率
            for cluster_id in visualization["clusters"]:
                cluster_data = visualization["clusters"][cluster_id]
                cluster_data["protein_coverage"] = cluster_data["protein_info_count"] / cluster_data["count"] if cluster_data["count"] > 0 else 0
            
            return visualization
            
        except Exception as e:
            logger.warning(f"创建可视化失败: {e}")
            return None
    
    # 保留原有的通用方法
    def extract_structure_features(self, structure_metadata: Dict[str, Dict[str, Any]]):
        """从结构元数据中提取特征 - 增强版：集成UniProt"""
        return self.extract_structure_features_target_focused(structure_metadata)
    
    def compute_structure_similarity(self, similarity_threshold: float = 0.7, use_uniprot_features: bool = True):
        """计算结构相似性并添加相似边 - 增强版：可选使用UniProt特征"""
        return self.compute_structure_similarity_target_focused(similarity_threshold)
    
    def search_similar_structures(self, query_structure_id: str, top_k: int = 10, min_similarity: float = 0.5, use_uniprot_features: bool = True) -> List[Dict[str, Any]]:
        """搜索相似结构 - 增强版：可选使用UniProt特征"""
        return self.search_similar_structures_target_focused(query_structure_id, top_k, min_similarity)
    
    def find_structural_clusters(self, n_clusters: int = 5, use_uniprot: bool = True) -> Dict[str, Any]:
        """发现结构聚类 - 增强版：可选使用UniProt特征"""
        return self.find_structural_clusters_target_focused(n_clusters)
    
    def save_graph(self, filename: Optional[str] = None) -> str:
        """保存知识图谱"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.graph_name}_{timestamp}.json"
        
        save_path = self.graph_dir / filename
        
        # 准备保存数据
        graph_data = {
            "name": self.graph_name,
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges.values()],
            "structure_features": {
                struct_id: {
                    "structure_id": feature.structure_id,
                    "features": feature.features
                }
                for struct_id, feature in self.structure_features.items()
            },
            "feature_names": self.feature_names,
            "created_at": datetime.now().isoformat(),
            "graph_statistics": {
                "total_nodes": len(self.nodes),
                "total_edges": len(self.edges),
                "structure_node_count": len([n for n in self.nodes.values() if n.node_type == NodeType.STRUCTURE]),
                "literature_node_count": len([n for n in self.nodes.values() if n.node_type == NodeType.LITERATURE]),
                "uniprot_node_count": len([n for n in self.nodes.values() if n.node_type == NodeType.UNIPROT])
            },
            "uniprot_statistics": {
                "has_uniprot_client": HAS_UNIPROT,
                "structures_with_uniprot": sum(1 for f in self.structure_features.values() 
                                              if f.features.get("has_protein_info", 0) > 0.5),
                "total_structures": len(self.structure_features)
            }
        }
        
        # 保存到文件
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(graph_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ 知识图谱已保存到: {save_path}")
        return str(save_path)
    
    def load_graph(self, filename: str) -> bool:
        """加载知识图谱"""
        load_path = self.graph_dir / filename
        
        if not load_path.exists():
            logger.error(f"图谱文件不存在: {load_path}")
            return False
        
        try:
            with open(load_path, 'r', encoding='utf-8') as f:
                graph_data = json.load(f)
            
            # 清空现有数据
            self.nodes.clear()
            self.edges.clear()
            self.structure_features.clear()
            self.graph.clear()
            
            # 加载节点
            for node_dict in graph_data.get("nodes", []):
                node = GraphNode(
                    id=node_dict["id"],
                    node_type=NodeType(node_dict["type"]),
                    label=node_dict["label"],
                    properties=node_dict.get("properties", {})
                )
                self.add_node(node)
            
            # 加载边
            for edge_dict in graph_data.get("edges", []):
                edge = GraphEdge(
                    source=edge_dict["source"],
                    target=edge_dict["target"],
                    edge_type=EdgeType(edge_dict["type"]),
                    weight=edge_dict.get("weight", 1.0),
                    properties=edge_dict.get("properties", {})
                )
                self.add_edge(edge)
            
            # 加载特征
            for struct_id, feature_dict in graph_data.get("structure_features", {}).items():
                self.structure_features[struct_id] = StructureFeature(
                    structure_id=feature_dict["structure_id"],
                    features=feature_dict["features"]
                )
            
            self.feature_names = graph_data.get("feature_names", [])
            
            logger.info(f"✅ 知识图谱已加载: {len(self.nodes)} 节点, {len(self.edges)} 边")
            logger.info(f"   - 蛋白质信息覆盖: {graph_data.get('uniprot_statistics', {}).get('structures_with_uniprot', 0)} 个结构")
            
            return True
            
        except Exception as e:
            logger.error(f"加载知识图谱失败: {e}")
            return False
    
    def get_graph_statistics(self) -> Dict[str, Any]:
        """获取图谱统计信息 - 增强版：包含UniProt统计"""
        # 节点类型统计
        node_type_counts = defaultdict(int)
        for node in self.nodes.values():
            node_type_counts[node.node_type.value] += 1
        
        # 边类型统计
        edge_type_counts = defaultdict(int)
        for edge in self.edges.values():
            edge_type_counts[edge.edge_type.value] += 1
        
        # 计算图密度
        density = nx.density(self.graph) if len(self.graph.nodes()) > 1 else 0
        
        # 计算平均聚类系数
        try:
            avg_clustering = nx.average_clustering(self.graph)
        except:
            avg_clustering = 0
        
        # 蛋白质家族统计（包含UniProt增强的）
        family_distribution = Counter()
        protein_info_coverage = 0
        
        for struct_id, feature in self.structure_features.items():
            families = []
            
            # 基础家族
            for family in self.family_classifier.protein_family_patterns.keys():
                if feature.features.get(f"family_{family}", 0) > 0.5:
                    families.append(family)
            
            # UniProt增强的家族
            for key in feature.features:
                if key.startswith('protein_family_') and feature.features[key] > 0.5:
                    family = key.replace('protein_family_', '')
                    if family not in families:
                        families.append(family)
            
            if families:
                family_distribution[",".join(sorted(families))] += 1
            else:
                family_distribution["unknown"] += 1
            
            # 统计蛋白质信息覆盖率
            if feature.features.get("has_protein_info", 0) > 0.5:
                protein_info_coverage += 1
        
        # UniProt特征统计
        protein_feature_counts = Counter()
        if self.structure_features:
            sample_feature = next(iter(self.structure_features.values()))
            for key in sample_feature.features:
                if key.startswith('protein_'):
                    protein_feature_counts[key] = sum(1 for f in self.structure_features.values() 
                                                     if f.features.get(key, 0) > 0)
        
        return {
            "nodes": {
                "total": len(self.nodes),
                "by_type": dict(node_type_counts)
            },
            "edges": {
                "total": len(self.edges),
                "by_type": dict(edge_type_counts)
            },
            "graph_metrics": {
                "density": density,
                "average_clustering": avg_clustering,
                "is_connected": nx.is_weakly_connected(self.graph) if len(self.graph.nodes()) > 0 else False
            },
            "structure_features": {
                "count": len(self.structure_features),
                "feature_dimensions": len(self.feature_names) if self.feature_names else 0,
                "family_distribution": dict(family_distribution)
            },
            "protein_statistics": {
                "has_uniprot_client": HAS_UNIPROT,
                "structures_with_protein_info": protein_info_coverage,
                "protein_info_coverage_percentage": protein_info_coverage / len(self.structure_features) * 100 if self.structure_features else 0,
                "protein_feature_counts": dict(protein_feature_counts)
            }
        }
    
    def export_for_visualization(self) -> Dict[str, Any]:
        """导出用于可视化的数据 - 增强版：包含蛋白质信息"""
        # 节点数据
        nodes_list = []
        for node in self.nodes.values():
            # 对于结构节点，添加蛋白质家族和蛋白质信息
            if node.node_type == NodeType.STRUCTURE:
                if node.id in self.structure_features:
                    feature = self.structure_features[node.id]
                    # 提取蛋白质家族
                    protein_families = []
                    for family in self.family_classifier.protein_family_patterns.keys():
                        if feature.features.get(f"family_{family}", 0) > 0.5:
                            protein_families.append(family)
                    
                    # 从蛋白质特征提取家族
                    for key in feature.features:
                        if key.startswith('protein_family_') and feature.features[key] > 0.5:
                            family = key.replace('protein_family_', '')
                            if family not in protein_families:
                                protein_families.append(family)
                    
                    node.properties["protein_families"] = protein_families
                    node.properties["has_protein_info"] = feature.features.get("has_protein_info", 0) > 0.5
            
            nodes_list.append({
                "id": node.id,
                "label": node.label,
                "type": node.node_type.value,
                "properties": node.properties
            })
        
        # 边数据
        edges_list = []
        for edge in self.edges.values():
            edges_list.append({
                "source": edge.source,
                "target": edge.target,
                "type": edge.edge_type.value,
                "weight": edge.weight,
                "properties": edge.properties
            })
        
        # 统计信息
        stats = self.get_graph_statistics()
        
        return {
            "nodes": nodes_list,
            "edges": edges_list,
            "statistics": stats,
            "feature_names": self.feature_names,
            "uniprot_support": HAS_UNIPROT
        }
    
    def get_protein_info_coverage_report(self) -> Dict[str, Any]:
        """获取蛋白质信息覆盖率报告"""
        if not self.structure_features:
            return {"error": "没有结构特征数据"}
        
        total_structures = len(self.structure_features)
        structures_with_protein_info = 0
        structures_without_protein_info = []
        
        # 按家族统计蛋白质信息覆盖率
        family_coverage = defaultdict(lambda: {"total": 0, "with_protein_info": 0})
        
        for struct_id, feature in self.structure_features.items():
            # 检查是否有蛋白质信息
            has_protein_info = feature.features.get("has_protein_info", 0) > 0.5
            
            if has_protein_info:
                structures_with_protein_info += 1
            else:
                structures_without_protein_info.append(struct_id)
            
            # 按家族统计
            families = []
            for family in self.family_classifier.protein_family_patterns.keys():
                if feature.features.get(f"family_{family}", 0) > 0.5:
                    families.append(family)
            
            for family in families:
                family_coverage[family]["total"] += 1
                if has_protein_info:
                    family_coverage[family]["with_protein_info"] += 1
        
        # 计算覆盖率百分比
        coverage_percentage = (structures_with_protein_info / total_structures * 100) if total_structures > 0 else 0
        
        # 按覆盖率排序家族
        family_stats = []
        for family, stats in family_coverage.items():
            coverage = (stats["with_protein_info"] / stats["total"] * 100) if stats["total"] > 0 else 0
            family_stats.append({
                "family": family,
                "total_structures": stats["total"],
                "with_protein_info": stats["with_protein_info"],
                "coverage_percentage": coverage
            })
        
        family_stats.sort(key=lambda x: x["coverage_percentage"], reverse=True)
        
        return {
            "total_structures": total_structures,
            "structures_with_protein_info": structures_with_protein_info,
            "structures_without_protein_info": structures_without_protein_info[:20],  # 只显示前20个
            "coverage_percentage": coverage_percentage,
            "family_coverage": family_stats,
            "recommendations": [
                f"建议对{len(structures_without_protein_info)}个缺乏蛋白质信息的结构进行手动注释",
                f"覆盖最好的家族: {family_stats[0]['family'] if family_stats else 'N/A'} ({family_stats[0]['coverage_percentage']:.1f}%)",
                f"覆盖最差的家族: {family_stats[-1]['family'] if family_stats else 'N/A'} ({family_stats[-1]['coverage_percentage']:.1f}%)"
            ]
        }