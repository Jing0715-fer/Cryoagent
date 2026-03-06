# structure_manager.py - 结构元数据管理模块（增强版，集成UniProt API）
import json, logging, time, re, requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import concurrent.futures
from dataclasses import dataclass, asdict, field
import hashlib
from core.pdb_fetcher import PDBFetcher

try:
    from core.uniprot_client import get_uniprot_client, UniProtEntry
    HAS_UNIPROT = True
except ImportError as e:
    HAS_UNIPROT = False
    logger = logging.getLogger(__name__)
    logger.warning(f"无法导入UniProt客户端: {e}")

logger = logging.getLogger(__name__)

@dataclass
class PDBMetadata:
    pdb_id: str
    title: str
    resolution: float
    method: str
    deposition_date: str
    related_emdb_ids: List[str] = field(default_factory=list)
    organism: str = "Unknown"
    authors: Optional[List[Dict]] = None
    citation_count: Optional[int] = None
    expression_system: Optional[str] = None
    expression_system_strain: Optional[str] = None
    ncbi_taxonomy_id: Optional[int] = None
    gene: Optional[str] = None
    tissue: Optional[str] = None
    last_updated: Optional[str] = None
    release_date: Optional[str] = None
    citation: Optional[str] = None
    uniprot_ids: List[str] = field(default_factory=list)
    binding_sites: Optional[List[Dict]] = None
    molecular_weight: Optional[float] = None
    polymer_count: Optional[int] = None
    
    protein_name: Optional[str] = None
    ec_numbers: Optional[List[str]] = None
    entities: Optional[List[Dict]] = None
    sequence_length: Optional[int] = None

@dataclass
class EMDBMetadata:
    emdb_id: str
    title: str
    resolution: float
    deposition_date: str
    related_pdb_ids: List[str] = field(default_factory=list)
    organism: str = "Unknown"
    map_release_date: Optional[str] = None
    voxel_spacing: Optional[float] = None
    expression_system: Optional[str] = None
    tissue_source: Optional[str] = None
    supramolecule_name: Optional[str] = None
    molecular_weight: Optional[float] = None
    last_updated: Optional[str] = None
    uniprot_ids: List[str] = field(default_factory=list)
    method: Optional[str] = None

@dataclass
class StructureRelationship:
    source_id: str
    target_id: str
    relationship_type: str
    evidence: Optional[str] = None

class StructureCache:
    
    def __init__(self, cache_dir: str = "structure_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_timeout = 86400
    
    def _get_cache_key(self, structure_id: str) -> str:
        return hashlib.md5(structure_id.encode()).hexdigest()
    
    def _get_cache_path(self, structure_id: str) -> Path:
        cache_key = self._get_cache_key(structure_id)
        return self.cache_dir / f"{cache_key}.json"
    
    def get(self, structure_id: str) -> Optional[Dict]:
        cache_path = self._get_cache_path(structure_id)
        
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                cached_time = data.get('cached_at', 0)
                if time.time() - cached_time < self.cache_timeout:
                    # 返回metadata字段
                    return data.get('metadata')
                else:
                    logger.debug(f"缓存过期: {structure_id}")
            except Exception as e:
                logger.warning(f"读取缓存失败 {structure_id}: {e}")
        
        return None
    
    def set(self, structure_id: str, metadata: Dict) -> bool:
        try:
            cache_path = self._get_cache_path(structure_id)
            cache_data = {
                'metadata': metadata,
                'structure_id': structure_id,
                'cached_at': time.time(),
                'cached_date': datetime.now().isoformat()
            }
            
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"设置缓存失败 {structure_id}: {e}")
            return False
    
    def clear(self, structure_id: str = None) -> bool:
        try:
            if structure_id:
                cache_path = self._get_cache_path(structure_id)
                if cache_path.exists():
                    cache_path.unlink()
                    logger.info(f"清除缓存: {structure_id}")
            else:
                for cache_file in self.cache_dir.glob("*.json"):
                    cache_file.unlink()
                logger.info(f"清除所有缓存，共 {len(list(self.cache_dir.glob('*.json')))} 个文件")
            return True
        except Exception as e:
            logger.error(f"清除缓存失败: {e}")
            return False

class StructureMetadataFetcher:
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.pdbe_base_url = "https://www.ebi.ac.uk/pdbe/api"
        self.emdb_base_url = "https://www.ebi.ac.uk/emdb/api"
        self.max_workers = self.config.get('max_workers', 3)
        self.timeout = self.config.get('timeout', 15)
        self.cache = StructureCache()
        self.pdb_fetcher = PDBFetcher(timeout=self.timeout)
        # 新增：过滤标记和配置
        self.filtering_enabled = True  # 默认启用过滤
        self.filtering_rules = {
            "keep_max_first_digit": True,
            "keep_max_minus_one_with_emdb": True,
            "min_first_digit": None  # 可配置最小首位数字
        }
    
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'CryoAgent/1.0 (literature analysis tool)',
            'Accept': 'application/json'
        })
        
        self.uniprot_client = None
        if HAS_UNIPROT:
            try:
                self.uniprot_client = get_uniprot_client()
                logger.info("✅ UniProt客户端已初始化")
            except Exception as e:
                logger.warning(f"初始化UniProt客户端失败: {e}")
                self.uniprot_client = None
        else:
            logger.warning("❌ UniProt客户端不可用，无法获取蛋白质信息")

    def apply_literature_based_filtering(
        self,
        pdb_ids: List[str],
        pdb_metadata: Dict[str, Any],
        emdb_ids: List[str],
        source_info: Dict[str, Any] = None,
        emdb_metadata: Dict[str, Any] = None
    ) -> Tuple[List[str], Dict[str, Any]]:
        """
        基于文献的过滤方法 - 暂时禁用过滤，返回所有PDB
        """
        logger.info("🔍 跳过文献关联过滤，返回所有PDB")

        # 直接返回所有 PDB ID，不过滤
        return pdb_ids, {
            "filter_applied": False,
            "reason": "filtering_disabled",
            "original_pdb_ids": pdb_ids
        }

        # 获取DOI来源的PDB ID
        doi_pdb_ids = []
        if source_info:
            logger.info(f"🔍 来源信息内容: {source_info.keys()}")

            # 尝试多种方式获取DOI PDB IDs
            if "doi_pdb_ids" in source_info:
                doi_pdb_ids = source_info["doi_pdb_ids"]
            elif "doi_pdb_details" in source_info:
                doi_pdb_ids = list(source_info["doi_pdb_details"].keys())

            # 如果来源信息中还有嵌套的source_info
            if "source_info" in source_info and "doi_pdb_ids" in source_info["source_info"]:
                doi_pdb_ids = source_info["source_info"]["doi_pdb_ids"]

        logger.info(f"🔍 识别到的DOI PDB IDs: {doi_pdb_ids}")

        # 如果doi_pdb_ids为空，尝试从pdb_ids中识别（以7或8开头的）
        if not doi_pdb_ids:
            logger.warning("⚠️ 来源信息中没有DOI PDB IDs，尝试从PDB IDs中识别...")
            # 假设DOI获取的PDB可能是文献的主要结构
            # 这里可以添加更智能的识别逻辑

        # 预先构建EMDB->PDB的反向映射（如果提供了emdb_metadata）
        emdb_to_pdb_map = {}
        if emdb_metadata:
            logger.info("🔍 从EMDB元数据构建反向映射...")
            for emdb_id, emdb_data in emdb_metadata.items():
                related_pdb_ids = self.extract_related_pdb_ids(emdb_data)
                if related_pdb_ids:
                    emdb_to_pdb_map[emdb_id] = related_pdb_ids
                    logger.info(f"   EMDB {emdb_id} -> PDBs: {related_pdb_ids}")

        # 应用过滤规则
        final_pdb_ids = []
        filtered_pdb_ids = []

        for pdb_id in pdb_ids:
            if pdb_id not in pdb_metadata:
                logger.warning(f"⚠️ PDB {pdb_id} 不在元数据中，跳过")
                continue

            # 规则1: DOI获取的PDB ID全部保留
            if pdb_id in doi_pdb_ids:
                final_pdb_ids.append(pdb_id)
                logger.info(f"✅ 保留 {pdb_id}: 来自DOI")
                continue

            # 规则2: 检查是否与文献中的EMDB有关联
            metadata = pdb_metadata[pdb_id]
            has_literature_association = False

            # 2a: 从PDB元数据中提取EMDB关联
            related_emdb_ids = self.extract_related_emdb_ids(metadata)

            if related_emdb_ids:
                # 检查是否有与文献EMDB匹配的
                for emdb_id in emdb_ids:
                    normalized_emdb = self.normalize_emdb_id(emdb_id)
                    for related_emdb in related_emdb_ids:
                        normalized_related = self.normalize_emdb_id(related_emdb)
                        if normalized_emdb == normalized_related:
                            has_literature_association = True
                            logger.info(f"✅ {pdb_id} 与文献EMDB {emdb_id} 关联 (从PDB元数据)")
                            break
                    if has_literature_association:
                        break

            # 2b: 如果从PDB元数据没找到，尝试从EMDB反向映射中查找
            if not has_literature_association and emdb_to_pdb_map:
                pdb_id_normalized = self.normalize_pdb_id(pdb_id)
                for emdb_id in emdb_ids:
                    normalized_emdb = self.normalize_emdb_id(emdb_id)
                    if normalized_emdb in emdb_to_pdb_map:
                        related_pdb_ids = emdb_to_pdb_map[normalized_emdb]
                        pdb_id_normalized = self.normalize_pdb_id(pdb_id)
                        for related_pdb in related_pdb_ids:
                            related_pdb_normalized = self.normalize_pdb_id(related_pdb)
                            if pdb_id_normalized == related_pdb_normalized:
                                has_literature_association = True
                                logger.info(f"✅ {pdb_id} 与文献EMDB {emdb_id} 关联 (从EMDB反向映射)")
                                break
                        if has_literature_association:
                            break

            if has_literature_association:
                final_pdb_ids.append(pdb_id)
            else:
                filtered_pdb_ids.append(pdb_id)
                if related_emdb_ids:
                    logger.info(f"❌ 过滤 {pdb_id}: 有EMDB关联 {related_emdb_ids}，但不在文献中")
                else:
                    logger.info(f"❌ 过滤 {pdb_id}: 无EMDB关联")

        logger.info(f"🎯 过滤结果: 保留 {len(final_pdb_ids)}个，过滤 {len(filtered_pdb_ids)}个")

        return final_pdb_ids, {
            "filter_applied": True,
            "doi_pdb_ids": doi_pdb_ids,
            "final_pdb_ids": final_pdb_ids,
            "filtered_pdb_ids": filtered_pdb_ids
        }

    def fetch_pdbe_molecules(self, pdb_id: str) -> List[Dict]:
        """
        从 PDBe Molecules API 获取所有分子实体
        修复版：处理API返回的不同数据结构
        """
        try:
            pdb_id_clean = pdb_id.lower()
            url = f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/molecules/{pdb_id_clean}"
            
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                # 修复：检查数据结构
                if isinstance(data, dict) and pdb_id_clean in data:
                    entry_data = data[pdb_id_clean]
                    
                    # PDBe API可能返回不同的数据结构
                    if isinstance(entry_data, dict):
                        molecules = entry_data.get('molecules', [])
                    elif isinstance(entry_data, list):
                        # 有时直接返回列表
                        molecules = entry_data
                    else:
                        molecules = []
                    
                    # 记录统计
                    molecule_types = {}
                    for mol in molecules:
                        if isinstance(mol, dict):
                            mol_type = mol.get('molecule_type', 'unknown')
                            molecule_types[mol_type] = molecule_types.get(mol_type, 0) + 1
                    
                    logger.info(f"PDB {pdb_id}: 从PDBe获取到 {len(molecules)} 个分子实体")
                    for mol_type, count in molecule_types.items():
                        logger.info(f"  - {mol_type}: {count}个")
                    
                    return molecules
                else:
                    logger.warning(f"PDBe Molecules API 返回异常数据结构: {type(data)}")
                    return []
            else:
                logger.warning(f"PDBe Molecules API 返回状态码 {response.status_code} for {pdb_id}")
                return []
                
        except Exception as e:
            logger.warning(f"从 PDBe 获取 molecules 失败 {pdb_id}: {str(e)}")
            import traceback
            traceback.print_exc()
            return []

    def extract_related_emdb_ids(self, metadata: Any) -> List[str]:
        """从PDB元数据中提取关联的EMDB IDs（增强版）"""
        related_emdb_ids = []
        
        try:
            # 首先尝试从PDBe API获取关联的EMDB ID
            if hasattr(metadata, 'pdb_id'):
                pdb_id = metadata.pdb_id
                logger.debug(f"尝试从PDBe API获取 {pdb_id} 的EMDB关联")
                
                # 调用PDBe API获取关联数据
                url = f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/related_experimental_data/{pdb_id.lower()}"
                response = requests.get(url, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    if pdb_id.lower() in data:
                        for entry in data[pdb_id.lower()]:
                            if entry.get("database") == "EMDB":
                                emdb_id = entry.get("accession_code", "")
                                if emdb_id:
                                    emdb_clean = emdb_id.upper()
                                    if not emdb_clean.startswith("EMD-"):
                                        emdb_clean = f"EMD-{emdb_clean}"
                                    related_emdb_ids.append(emdb_clean)
            
            # 如果API没有获取到，尝试从元数据中提取
            if not related_emdb_ids:
                # 检查不同格式的元数据
                if hasattr(metadata, 'related_emdb_ids'):
                    related_emdb_ids = metadata.related_emdb_ids
                elif isinstance(metadata, dict) and 'related_emdb_ids' in metadata:
                    related_emdb_ids = metadata['related_emdb_ids']
                elif hasattr(metadata, 'related_ids'):
                    related_ids = metadata.related_ids
                    if isinstance(related_ids, list):
                        related_emdb_ids = [
                            id for id in related_ids 
                            if isinstance(id, str) and ('EMD' in id.upper() or id.startswith('EMD-'))
                        ]
                elif isinstance(metadata, dict):
                    # 检查嵌套结构
                    for key, value in metadata.items():
                        if isinstance(value, dict) and 'related_emdb_ids' in value:
                            related_emdb_ids = value['related_emdb_ids']
                            break
            
            # 标准化所有EMDB ID
            standardized_ids = []
            for emdb_id in related_emdb_ids:
                if isinstance(emdb_id, str):
                    standardized = self.normalize_emdb_id(emdb_id)
                    if standardized:
                        standardized_ids.append(standardized)
            
            return list(set(standardized_ids))
            
        except Exception as e:
            logger.warning(f"提取EMDB关联ID时出错: {e}")
            return []

    def fetch_pdb_metadata(self, pdb_id: str, use_cache: bool = True, force_update: bool = False, 
                        fetch_uniprot: bool = False) -> Optional[PDBMetadata]:
        """获取PDB元数据（整合版 - 包含强制更新逻辑）"""
        cache_key = f"PDB_{pdb_id}"
        
        if use_cache and not force_update:
            cached = self.cache.get(cache_key)
            if cached:
                try:
                    return PDBMetadata(**cached)
                except Exception as e:
                    logger.warning(f"反序列化PDB缓存失败 {pdb_id}: {e}")
        else:
            if force_update:
                logger.debug(f"[{pdb_id}] 强制更新模式：跳过缓存，请求 API...")
        
        try:
            pdb_id_lower = pdb_id.lower()
            metadata_dict = {}
            
            # 2. 使用 PDBFetcher 获取完整信息
            complete_info = self.pdb_fetcher.fetch_pdb_complete_info(pdb_id_lower)
            
            if complete_info:
                # 3. 提取基本信息
                if 'basic_info' in complete_info and complete_info['basic_info']:
                    basic_metadata = self._extract_metadata_from_basic_info(
                        complete_info['basic_info'], pdb_id_lower
                    )
                    metadata_dict.update(basic_metadata)
                
                # 4. 提取实体信息 (整合实体-UniProt映射)
                if 'entities' in complete_info:
                    entities_info = self._extract_metadata_from_entities(
                        entities=complete_info['entities'],
                        pdb_id=pdb_id_lower,
                        uniprot_mappings=[] 
                    )
                    metadata_dict.update(entities_info)
                
                # 5. 提取UniProt映射 ID (用于主表)
                if 'uniprot_mappings' in complete_info:
                    uniprot_info = self._extract_metadata_from_uniprot(
                        complete_info['uniprot_mappings'],
                        complete_info.get('uniprot_details', {}),
                        pdb_id_lower
                    )
                    metadata_dict.update(uniprot_info)

                # 6. 提取关联的 EMDB ID
                if complete_info.get('related_emdb_ids'):
                    metadata_dict['related_emdb_ids'] = complete_info['related_emdb_ids']
                
                # 7. 【关键修复】调用 PDBe API 补充/修正元数据
                # 这一步会修复 "Unknown" organism 和缺失的 protein_name
                try:
                    logger.debug(f"[{pdb_id}] 尝试从 PDBe 获取元数据进行补充...")
                    pdbe_summary = self.fetch_pdbe_summary(pdb_id)
                    
                    if pdbe_summary:
                        metadata_dict = self._merge_metadata_with_pdbe(metadata_dict, pdbe_summary, pdb_id)
                except Exception as e:
                    logger.warning(f"PDBe 数据修正失败 {pdb_id}: {e}")
                
                # 8. 构建 PDBMetadata 对象
                if metadata_dict:
                    metadata = self._build_pdb_metadata(metadata_dict, pdb_id_lower)
                    
                    # 9. 保存到缓存
                    if not force_update:
                        cache_data = asdict(metadata)
                        self.cache.set(cache_key, cache_data)
                    
                    # 10. 异步保存UniProt信息到数据库
                    if fetch_uniprot and complete_info.get('uniprot_mappings'):
                        try:
                            self._save_uniprot_info_from_fetcher_result(
                                pdb_id, metadata, complete_info
                            )
                        except Exception as e:
                            logger.warning(f"保存UniProt信息失败 {pdb_id}: {e}")
                    
                    return metadata
                
            logger.warning(f"无法获取PDB {pdb_id} 的完整信息")
            return None
                
        except Exception as e:
            logger.error(f"获取PDB {pdb_id} 时出错: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _extract_metadata_from_basic_info(self, basic_info: Dict, pdb_id: str) -> Dict:
        """从基本信息中提取元数据 (适配 RCSB 数据结构)"""
        extracted = {}
        
        try:
            # 1. 标题
            title = basic_info.get('struct', {}).get('title', '')
            if title:
                extracted['title'] = title
            
            # 2. 实验方法
            exptl = basic_info.get('exptl')
            if isinstance(exptl, list) and exptl:
                if isinstance(exptl[0], dict):
                    # 【修改】使用格式化函数
                    raw_method = exptl[0].get('method', 'Unknown')
                    extracted['method'] = self._format_experimental_method(raw_method)
            
            # 3. 分辨率
            rcsb_info = basic_info.get('rcsb_entry_info', {})
            resolution = rcsb_info.get('resolution_combined')
            if isinstance(resolution, list) and resolution:
                try:
                    extracted['resolution'] = float(resolution[0])
                except (ValueError, TypeError):
                    pass
            elif isinstance(resolution, (int, float)):
                extracted['resolution'] = float(resolution)
            
            # 4. 日期
            access_info = basic_info.get('rcsb_accession_info', {})
            deposition_date = access_info.get('initial_release_date', '')
            if deposition_date:
                extracted['deposition_date'] = str(deposition_date)[:10]
                
            release_date = access_info.get('deposit_date', '')
            if release_date:
                extracted['release_date'] = str(release_date)[:10]
                
            # 5. 分子量 (简化)
            struct_keywords = basic_info.get('struct_keywords')
            if isinstance(struct_keywords, list):
                for keyword in struct_keywords:
                    if isinstance(keyword, dict) and keyword.get('pdbx_keyword', '') == 'MOLECULE_WEIGHT':
                        try:
                            extracted['molecular_weight'] = float(keyword.get('text', 0))
                        except:
                            pass
                            
        except Exception as e:
            logger.warning(f"提取基本信息失败 {pdb_id}: {e}")
        
        return extracted

    def fetch_pdbe_summary(self, pdb_id: str) -> Dict:
        """
        从 PDBe API 获取摘要信息，用于修正 RCSB 数据缺失的情况
        """
        try:
            pdb_id_clean = pdb_id.lower()
            url = f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/summary/{pdb_id_clean}"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if pdb_id_clean in data:
                    entry = data[pdb_id_clean][0]
                    
                    # 提取关键修正字段
                    return {
                        'title': entry.get('title'),
                        'organism': entry.get('organism_scientific', ''), # PDBe 直接提供 organism
                        'expression_system': entry.get('expression_system', ''),
                        'experimental_methods': entry.get('experimental_method', []),
                        'macromolecules': entry.get('macromolecules', []) # 包含每个分子的信息
                    }
            return {}
        except Exception as e:
            logger.warning(f"从 PDBe 获取摘要失败 {pdb_id}: {e}")
            return {}

    def _merge_metadata_with_pdbe(self, rcsb_metadata: Dict, pdbe_metadata: Dict, pdb_id: str) -> Dict:
        """合并 RCSB 和 PDBe 的元数据，优先级：PDbe (缺失修正) > RCSB"""
        merged = rcsb_metadata.copy()
        
        if not pdbe_metadata:
            return merged
        
        # 1. 修正 Title
        if not merged.get('title') or merged.get('title') == f'Structure of {pdb_id}' or merged.get('title') == 'N/A':
            if pdbe_metadata.get('title'):
                merged['title'] = pdbe_metadata['title']

        # 2. 修正 Organism (重点修复你的问题)
        if not merged.get('organism') or merged.get('organism') == 'Unknown':
            if pdbe_metadata.get('organism'):
                merged['organism'] = pdbe_metadata['organism']
                logger.info(f"[{pdb_id}] 修正 Organism: {pdbe_metadata['organism']}")

        # 3. 修正 Expression System
        if not merged.get('expression_system'):
            if pdbe_metadata.get('expression_system'):
                merged['expression_system'] = pdbe_metadata['expression_system']

        # 4. 从 PDBE macromolecules 补充蛋白质名
        # 只有当 RCSB 没提取到或提取结果为空时才补充
        current_protein = merged.get('protein_name')
        if not current_protein:
            pdbe_macros = pdbe_metadata.get('macromolecules', [])
            if pdbe_macros:
                names = [m.get('name') for m in pdbe_macros if m.get('name')]
                if names:
                    merged['protein_name'] = names[0]
                    logger.info(f"[{pdb_id}] 修正 Protein Name: {names[0]}")
        
        # 5. 修正 Method (如果 RCSB 为 Unknown)
        if not merged.get('method') or merged.get('method') == 'Unknown':
            pdbe_methods = pdbe_metadata.get('experimental_methods', [])
            if pdbe_methods:
                # 【修改】使用格式化函数
                raw_method = pdbe_methods[0]
                merged['method'] = self._format_experimental_method(raw_method)

        return merged

    def _extract_metadata_from_entities(self, entities: List[Dict], pdb_id: str, uniprot_mappings: List[Dict] = None) -> Dict:
        """
        整合多个数据源获取完整的实体信息（修复版：使用unp_start/end）
        """
        extracted = {}
        
        try:
            # 1. 获取PDBe Molecules完整列表
            pdbe_molecules_list = self.fetch_pdbe_molecules(pdb_id)
            
            if not pdbe_molecules_list:
                logger.warning(f"PDB {pdb_id} 无法从PDBe获取Molecules列表")
                return self._extract_entities_fallback(entities, pdb_id, uniprot_mappings)
            
            # 2. 从RCSB API获取UniProt映射信息（备用来源）
            rcsb_uniprot_mappings = self._fetch_rcsb_uniprot_mappings(pdb_id)
            
            # 3. 从PDBe获取UniProt映射（主要来源，包含 unp_start/end）
            pdbe_uniprot_mappings = self._fetch_pdbe_uniprot_mappings(pdb_id)
            
            # 4. 构建RCSB实体映射
            rcsb_entity_map = {}
            for e in entities:
                eid = str(e.get('entity_id', ''))
                if eid:
                    rcsb_entity_map[eid] = e
            
            # 5. 处理所有分子实体
            normalized_entities = []
            organisms = set()
            genes = set()
            protein_names = set()
            polymer_count = 0
            molecular_weight = 0.0
            uniprot_ids_in_structure = set()
            expression_hosts = set()
            
            for pdbe_mol in pdbe_molecules_list:
                try:
                    if not isinstance(pdbe_mol, dict):
                        continue
                    
                    eid = pdbe_mol.get('entity_id')
                    if eid is None:
                        continue
                        
                    eid_str = str(eid)
                    
                    # === 初始化实体 ===
                    molecule_name = pdbe_mol.get('molecule_name', [])
                    if not isinstance(molecule_name, list):
                        molecule_name = [molecule_name] if molecule_name else []
                    
                    description = pdbe_mol.get('synonym', '')
                    if not description:
                        description = pdbe_mol.get('name', '')
                    
                    in_chains = pdbe_mol.get('in_chains', [])
                    if not isinstance(in_chains, list):
                        in_chains = [in_chains] if in_chains else []
                    
                    norm_entity = {
                        'entity_id': eid_str,
                        'molecule_type': str(pdbe_mol.get('molecule_type', '')),
                        'molecule_name': molecule_name,
                        'description': description,
                        'chain_ids': [],
                        'asym_ids': [],
                        'in_chains': in_chains,
                        'sequence': '',
                        'length': pdbe_mol.get('length', 0),
                        'weight': pdbe_mol.get('weight', 0.0),
                        'number_of_copies': pdbe_mol.get('number_of_copies', 1),
                        'source_organism': '',
                        'expression_host': '',
                        'taxon_id': '',
                        'gene_names': [],
                        'uniprot_ids': [],           # 待填充
                        'start_residue': None,       # 将使用 unp_start
                        'end_residue': None,         # 将使用 unp_end
                        'uniprot_ranges': [],        # 保存详细范围信息
                        'entity_data': None
                    }
                    
                    # === 从PDBe Molecules提取来源生物信息 ===
                    sources = pdbe_mol.get('source', [])
                    if sources and isinstance(sources, list) and sources:
                        source_data = sources[0]
                        if isinstance(source_data, dict):
                            if 'organism_scientific_name' in source_data:
                                norm_entity['source_organism'] = source_data.get('organism_scientific_name', '')
                                norm_entity['taxon_id'] = str(source_data.get('tax_id', ''))
                            elif 'expression_host_scientific_name' in source_data:
                                norm_entity['expression_host'] = source_data.get('expression_host_scientific_name', '')
                                norm_entity['taxon_id'] = str(source_data.get('tax_id', ''))
                    
                    # === 关键修复：从PDbe Mappings获取 UniProt ID 和 unp_start/end ===
                    uniprot_info_list = []
                    if pdbe_uniprot_mappings:
                        # 缓存已获取的UniProt序列，避免重复请求
                        uniprot_sequence_cache = {}

                        for uniprot_id, mappings in pdbe_uniprot_mappings.items():
                            
                            # 1. 获取该 UniProt ID 的完整序列 (带缓存)
                            if uniprot_id not in uniprot_sequence_cache:
                                uniprot_sequence_cache[uniprot_id] = ""
                                seq_info = self._fetch_uniprot_sequence_info(uniprot_id)
                                if seq_info and seq_info.get('sequence'):
                                    uniprot_sequence_cache[uniprot_id] = seq_info['sequence']
                                    logger.debug(f"Fetched sequence for {uniprot_id}, length: {len(uniprot_sequence_cache[uniprot_id])}")
                                else:
                                    logger.warning(f"Could not fetch sequence for {uniprot_id}")

                            current_uniprot_seq = uniprot_sequence_cache[uniprot_id]

                            # 2. 遍历该 UniProt ID 的所有映射片段
                            for mapping in mappings:
                                # 严格匹配 entity_id
                                mapping_eid = mapping.get('entity_id')
                                if mapping_eid is not None and str(mapping_eid) == eid_str:
                                    
                                    # 1. 填充 uniprot_ids
                                    if uniprot_id not in norm_entity['uniprot_ids']:
                                        norm_entity['uniprot_ids'].append(uniprot_id)
                                        uniprot_ids_in_structure.add(uniprot_id)
                                    
                                    # 2. 设置 start/end residue
                                    if norm_entity['start_residue'] is None:
                                        norm_entity['start_residue'] = mapping.get('unp_start') # 保留逻辑或根据需求调整
                                    if norm_entity['end_residue'] is None:
                                        norm_entity['end_residue'] = mapping.get('unp_end')
                                    
                                    # 补充链信息
                                    chain_id = mapping.get('chain_id')
                                    if chain_id and chain_id not in norm_entity['in_chains']:
                                        norm_entity['in_chains'].append(chain_id)
                                    
                                    # 3. 【关键修改】保存详细范围，包含 UniProt Sequence
                                    range_info = {
                                        'uniprot_id': uniprot_id,
                                        'chain_id': chain_id,
                                        'unp_start': mapping.get('unp_start'),
                                        'unp_end': mapping.get('unp_end'),
                                        'pdb_start': mapping.get('start_residue_number'),
                                        'pdb_end': mapping.get('end_residue_number'),
                                        'uniprot_sequence': current_uniprot_seq  # 将序列直接存入 range
                                    }
                                    uniprot_info_list.append(range_info)

                    if uniprot_info_list:
                        norm_entity['uniprot_ranges'] = uniprot_info_list

                    # 如果没有在PDBe找到，尝试RCSB
                    if not norm_entity['uniprot_ids'] and rcsb_uniprot_mappings and eid_str in rcsb_uniprot_mappings:
                        rcsb_uniprot_info = rcsb_uniprot_mappings[eid_str]
                        if 'uniprot_ids' in rcsb_uniprot_info:
                            norm_entity['uniprot_ids'] = rcsb_uniprot_info['uniprot_ids']
                            uniprot_ids_in_structure.update(norm_entity['uniprot_ids'])
                        if 'gene_names' in rcsb_uniprot_info and not norm_entity['gene_names']:
                            norm_entity['gene_names'] = rcsb_uniprot_info['gene_names']

                    # === 从UniProt API补充其他信息 ===
                    if norm_entity['uniprot_ids']:
                        found_sequence = False
                        for uniprot_id in norm_entity['uniprot_ids']:
                            uniprot_sequence_info = self._fetch_uniprot_sequence_info(uniprot_id)
                            
                            if not uniprot_sequence_info:
                                logger.debug(f"Entity {eid_str}: UniProt {uniprot_id} 未获取到信息")
                                continue
                            
                            # 1. 补充蛋白质名称
                            protein_name = uniprot_sequence_info.get('protein_name')
                            if protein_name and not description:
                                norm_entity['description'] = protein_name
                            
                            # 2. 补充基因名
                            uni_genes = uniprot_sequence_info.get('gene_names', [])
                            if uni_genes and not norm_entity['gene_names']:
                                norm_entity['gene_names'] = uni_genes
                            
                            # 3. 补充生物体
                            uni_org = uniprot_sequence_info.get('organism')
                            if uni_org and not norm_entity['source_organism']:
                                norm_entity['source_organism'] = uni_org
                            
                            # 【修复关键逻辑】保存完整序列用于比对
                            if uniprot_sequence_info.get('sequence'):
                                norm_entity['uniprot_sequence'] = uniprot_sequence_info['sequence']
                                found_sequence = True
                                logger.info(f"📝 Entity {eid_str}: 绑定 UniProt 序列 (ID: {uniprot_id}, 长度: {len(norm_entity['uniprot_sequence'])})")
                                # 如果找到序列，继续尝试其他ID以获取其他信息
                                # 不立即break，继续检查其他UniProt ID
                                
                            # 【新增】如果没有序列但有其他信息，记录下来
                            elif uniprot_sequence_info:
                                logger.debug(f"Entity {eid_str}: UniProt {uniprot_id} 有信息但无序列")
                        
                        # 如果循环结束后还没有序列，设置为空字符串而不是 "NULL"
                        if not found_sequence and 'uniprot_sequence' not in norm_entity:
                            norm_entity['uniprot_sequence'] = ''
                            logger.warning(f"⚠️ Entity {eid_str}: 所有UniProt ID均未获取到序列")
                    
                    # === 补充RCSB详细信息 ===
                    if eid_str in rcsb_entity_map:
                        rcsb_ent = rcsb_entity_map[eid_str]
                        rcsb_raw = rcsb_ent.get('entity_data', {})
                        
                        # 补充序列
                        if not norm_entity['sequence']:
                            poly = rcsb_raw.get('entity_poly', {})
                            seq = poly.get('pdbx_seq_one_letter_code_can') or poly.get('pdbx_seq_one_letter_code', '')
                            if seq:
                                norm_entity['sequence'] = seq
                                norm_entity['length'] = len(seq)
                        
                        # 补充基因名
                        if not norm_entity['gene_names']:
                            gene_list = rcsb_raw.get('rcsb_gene_name', [])
                            genes_raw = []
                            for g in gene_list:
                                if isinstance(g, dict): 
                                    genes_raw.append(g.get('value'))
                                else: 
                                    genes_raw.append(str(g))
                            norm_entity['gene_names'] = list(set(genes_raw))
                        
                        # 补充描述
                        if not norm_entity['description']:
                            p_desc = rcsb_raw.get('entity_poly', {}).get('pdbx_description', '')
                            norm_entity['description'] = p_desc
                        
                        # 补充链信息
                        if not norm_entity['chain_ids']:
                            container_ids = rcsb_raw.get('rcsb_polymer_entity_container_identifiers', {})
                            if container_ids:
                                norm_entity['chain_ids'] = container_ids.get('auth_asym_ids', [])
                                norm_entity['asym_ids'] = container_ids.get('asym_ids', [])
                    
                    # === 确保关键字段有值 ===
                    if not norm_entity['description'] and norm_entity['molecule_name']:
                        if isinstance(norm_entity['molecule_name'], list) and norm_entity['molecule_name']:
                            norm_entity['description'] = norm_entity['molecule_name'][0]
                        else:
                            norm_entity['description'] = str(norm_entity['molecule_name'])
                    
                    # === 聚合统计信息 ===
                    mol_type = norm_entity['molecule_type']
                    
                    if 'protein' in mol_type or 'polypeptide' in mol_type:
                        polymer_count += 1
                        molecular_weight += norm_entity['weight']
                        
                        if norm_entity['source_organism']:
                            organisms.add(norm_entity['source_organism'])
                        elif norm_entity['expression_host']:
                            expression_hosts.add(norm_entity['expression_host'])
                        
                        if norm_entity['gene_names']:
                            genes.update(norm_entity['gene_names'])
                        
                        if norm_entity['description']:
                            protein_names.add(norm_entity['description'])
                    
                    if norm_entity['expression_host']:
                        expression_hosts.add(norm_entity['expression_host'])
                    
                    normalized_entities.append(norm_entity)
                    
                except Exception as e:
                    logger.warning(f"处理PDB {pdb_id} 实体 {pdbe_mol.get('entity_id')} 时出错: {e}")
                    continue
            
            # 6. 构建返回结果
            if organisms:
                extracted['organism'] = ', '.join(list(organisms)[:3])
            elif expression_hosts:
                extracted['organism'] = ', '.join(list(expression_hosts)[:3])
            
            if expression_hosts:
                extracted['expression_system'] = ', '.join(list(expression_hosts)[:3])
            
            if genes:
                extracted['gene'] = ', '.join(list(genes)[:5])
            
            if protein_names:
                extracted['protein_name'] = ', '.join(list(protein_names)[:3])
            
            if uniprot_ids_in_structure:
                extracted['uniprot_ids'] = list(uniprot_ids_in_structure)
            
            extracted['polymer_count'] = polymer_count
            extracted['molecular_weight'] = molecular_weight
            extracted['entities'] = normalized_entities
            
            # 移除entity_data字段
            for entity in extracted['entities']:
                if 'entity_data' in entity:
                    del entity['entity_data']
            
            logger.info(f"提取元数据 [{pdb_id}]: 总实体={len(normalized_entities)}, UniProt IDs={len(uniprot_ids_in_structure)}")
            
            return extracted
            
        except Exception as e:
            logger.error(f"提取实体信息失败 {pdb_id}: {e}", exc_info=True)
            return {}
        
    def _fetch_rcsb_uniprot_mappings(self, pdb_id: str) -> Dict:
        """
        从RCSB API获取UniProt映射信息（主要来源）
        返回格式: {entity_id: {'uniprot_ids': [], 'gene_names': []}}
        """
        try:
            pdb_id_clean = pdb_id.lower()
            url = f"https://data.rcsb.org/rest/v1/core/polymer_entities/{pdb_id_clean}"
            
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                
                result = {}
                
                # RCSB API返回的是一个列表，每个元素对应一个实体
                for entity_data in data:
                    entity_id = entity_data.get('entity_id')
                    if not entity_id:
                        continue
                        
                    entity_info = {'uniprot_ids': [], 'gene_names': []}
                    
                    # 提取UniProt映射
                    container_ids = entity_data.get('rcsb_polymer_entity_container_identifiers', {})
                    uniprot_ids = container_ids.get('uniprot_ids', [])
                    if uniprot_ids:
                        entity_info['uniprot_ids'] = uniprot_ids
                    
                    # 提取基因名称
                    rcsb_gene_name = entity_data.get('rcsb_gene_name', [])
                    if rcsb_gene_name:
                        gene_names = []
                        for gene in rcsb_gene_name:
                            if isinstance(gene, dict):
                                gene_names.append(gene.get('value', ''))
                            else:
                                gene_names.append(str(gene))
                        entity_info['gene_names'] = list(set(gene_names))
                    
                    result[str(entity_id)] = entity_info
                
                logger.info(f"从RCSB获取到 {len(result)} 个实体的UniProt映射")
                return result
                
        except Exception as e:
            logger.warning(f"获取RCSB UniProt映射失败 {pdb_id}: {e}")
        
        return {}
    
    def _fetch_pdbe_uniprot_mappings(self, pdb_id: str) -> Dict:
        """
        从PDBe API获取UniProt映射信息（修复版：处理实际API数据结构）
        返回格式: {uniprot_id: [{'entity_id': ..., 'chain_id': ..., 'unp_start': ..., 'unp_end': ...}, ...]}
        """
        try:
            pdb_id_clean = pdb_id.lower()
            url = f"https://www.ebi.ac.uk/pdbe/api/mappings/uniprot/{pdb_id_clean}"
            
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                if pdb_id_clean in data:
                    uniprot_data = data[pdb_id_clean].get('UniProt', {})
                    
                    result = {}
                    for uniprot_id, content_dict in uniprot_data.items():
                        # content_dict 是类似 {'name': 'TPO_HUMAN', 'mappings': [...], 'identifier': '...'} 的字典
                        # 不一定是列表
                        
                        if not isinstance(content_dict, dict):
                            continue
                            
                        mappings_list = content_dict.get('mappings', [])
                        
                        if not isinstance(mappings_list, list):
                            continue

                        current_mappings = []
                        for m in mappings_list:
                            if not isinstance(m, dict):
                                continue
                            
                            # 提取需要的字段，特别是 unp_start 和 unp_end
                            mapping_info = {
                                'entity_id': m.get('entity_id'),      # 可能是 int (例如 1)
                                'chain_id': m.get('chain_id'),
                                'unp_start': m.get('unp_start'),      # UniProt 起始位置
                                'unp_end': m.get('unp_end'),          # UniProt 结束位置
                                'start_residue_number': m.get('start', {}).get('residue_number'),
                                'end_residue_number': m.get('end', {}).get('residue_number')
                            }
                            current_mappings.append(mapping_info)
                        
                        if current_mappings:
                            result[uniprot_id] = current_mappings
                    
                    logger.info(f"从PDBe获取到 {len(result)} 个UniProt映射")
                    return result
        except Exception as e:
            logger.warning(f"获取PDBe UniProt映射失败 {pdb_id}: {e}")
            import traceback
            traceback.print_exc()
        
        return {}
    
    def _fetch_uniprot_sequence_info(self, uniprot_id: str) -> Dict:
        """
        从 UniProt API 获取序列信息（增强调试版）
        """
        try:
            url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}?format=json"
            
            headers = {
                'User-Agent': 'CryoAgent/1.0 (structural biology tool)',
                'Accept': 'application/json'
            }
            
            logger.info(f"🔍 请求UniProt API: {url}")
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                # 详细记录API响应结构
                logger.debug(f"UniProt {uniprot_id} API响应:")
                logger.debug(f"  状态码: {response.status_code}")
                logger.debug(f"  根级键: {list(data.keys())}")
                
                result = {
                    'length': None,
                    'sequence': '',
                    'mass': None,
                    'protein_name': '',
                    'gene_names': [],
                    'organism': ''
                }
                
                # --- 1. 提取序列（多种尝试）---
                # 方法1: 从标准路径获取
                if 'sequence' in data:
                    seq_obj = data['sequence']
                    logger.debug(f"  sequence字段类型: {type(seq_obj)}")
                    
                    if isinstance(seq_obj, dict):
                        logger.debug(f"  sequence字段内键: {list(seq_obj.keys())}")
                        
                        # 尝试获取序列值
                        if 'value' in seq_obj and isinstance(seq_obj['value'], str):
                            result['sequence'] = seq_obj['value']
                            result['length'] = seq_obj.get('length')
                            result['mass'] = seq_obj.get('molWeight')
                            logger.debug(f"  从sequence['value']获取序列，长度: {len(result['sequence'])}")
                        
                        # 或者检查是否有直接的字符串值
                        elif isinstance(seq_obj, str):
                            result['sequence'] = seq_obj
                            logger.debug(f"  sequence字段本身是字符串，长度: {len(result['sequence'])}")
                    
                    # sequence字段可能是字符串
                    elif isinstance(seq_obj, str):
                        result['sequence'] = seq_obj
                        logger.debug(f"  从sequence字段获取序列，长度: {len(result['sequence'])}")
                
                # 方法2: 如果没有从标准路径获取到，尝试其他可能路径
                if not result['sequence']:
                    logger.debug(f"  未从标准路径获取到序列，尝试其他路径...")
                    
                    # 深度遍历查找可能的序列
                    def find_sequence_in_dict(d, path=""):
                        if isinstance(d, dict):
                            for key, value in d.items():
                                new_path = f"{path}.{key}" if path else key
                                if isinstance(value, str) and len(value) > 50:  # 假设序列长度大于50
                                    logger.debug(f"    在 {new_path} 找到可能序列，长度: {len(value)}")
                                    return value
                                elif isinstance(value, (dict, list)):
                                    found = find_sequence_in_dict(value, new_path)
                                    if found:
                                        return found
                        elif isinstance(d, list):
                            for i, item in enumerate(d):
                                new_path = f"{path}[{i}]"
                                found = find_sequence_in_dict(item, new_path)
                                if found:
                                    return found
                        return None
                    
                    found_seq = find_sequence_in_dict(data)
                    if found_seq:
                        result['sequence'] = found_seq
                
                # --- 2. 提取蛋白质名称 ---
                if 'proteinDescription' in data:
                    protein_desc = data['proteinDescription']
                    logger.debug(f"  proteinDescription类型: {type(protein_desc)}")
                    
                    if isinstance(protein_desc, dict):
                        rec_name = protein_desc.get('recommendedName', {})
                        if rec_name and isinstance(rec_name, dict):
                            result['protein_name'] = rec_name.get('fullName', {}).get('value', '')
                            logger.debug(f"  蛋白质名称: {result['protein_name']}")
                        elif protein_desc.get('submittedName'):
                            submitted = protein_desc['submittedName']
                            if isinstance(submitted, list) and submitted:
                                result['protein_name'] = submitted[0].get('fullName', {}).get('value', '')
                
                # --- 3. 提取基因名称 ---
                if 'genes' in data:
                    genes = data['genes']
                    logger.debug(f"  genes字段类型: {type(genes)}")
                    
                    if isinstance(genes, list):
                        for gene in genes:
                            if isinstance(gene, dict):
                                g_name = gene.get('geneName', {}).get('value')
                                if g_name:
                                    result['gene_names'].append(g_name)
                        logger.debug(f"  找到基因名: {result['gene_names']}")
                
                # --- 4. 提取生物体信息 ---
                if 'organism' in data:
                    org_data = data['organism']
                    if isinstance(org_data, dict):
                        result['organism'] = org_data.get('scientificName', '')
                        logger.debug(f"  生物体: {result['organism']}")
                
                # 最终检查
                if result['sequence']:
                    logger.info(f"✅ UniProt {uniprot_id}: 成功获取序列，长度={len(result['sequence'])}")
                else:
                    logger.warning(f"⚠️ UniProt {uniprot_id}: 未找到序列数据")
                    # 保存部分响应用于调试
                    response_preview = str(data)[:500] if data else "空响应"
                    logger.debug(f"  API响应预览: {response_preview}...")
                
                return result
                
            elif response.status_code == 404:
                logger.warning(f"⚠️ UniProt {uniprot_id}: 未找到 (404)")
                return {}
            else:
                logger.error(f"❌ UniProt API 错误 {response.status_code} for {uniprot_id}")
                logger.error(f"  响应内容: {response.text[:200]}")
                return {}
                
        except requests.exceptions.Timeout:
            logger.error(f"❌ UniProt API 请求超时: {uniprot_id}")
            return {}
        except Exception as e:
            logger.error(f"❌ 获取 UniProt 信息异常 {uniprot_id}: {e}")
            import traceback
            logger.error(f"完整异常信息: {traceback.format_exc()}")
            return {}
    
    def _format_experimental_method(self, method: str) -> str:
        """格式化实验方法名称（如 singleParticle -> Single Particle）"""
        if not method or method == "Unknown":
            return "Unknown"
        
        # 统一转换：下划线转空格，首字母大写
        formatted = method.replace("_", " ").title()
        
        # 特殊映射表（处理一些API返回的非标准缩写）
        method_map = {
            "Solution Nmr": "Solution NMR",
            "Solid-State Nmr": "Solid-State NMR",
            "Electron Microscopy": "Electron Microscopy",
            "X-Ray Diffraction": "X-ray Diffraction",
            "Neutron Diffraction": "Neutron Diffraction",
            "Fiber Diffraction": "Fiber Diffraction",
            "Infrared Spectroscopy": "Infrared Spectroscopy",
            "Theoretical Model": "Theoretical Model",
            "singleParticle": "Single Particle"
        }
        
        return method_map.get(formatted, formatted)

    def _extract_entities_fallback(self, entities: List[Dict], pdb_id: str, uniprot_mappings: List[Dict] = None) -> Dict:
        """
        回退方法：直接从RCSB实体数据中提取信息
        """
        extracted = {}
        normalized_entities = []
        uniprot_ids_in_structure = set()
        
        try:
            # 尝试从RCSB API获取UniProt信息
            rcsb_uniprot_mappings = self._fetch_rcsb_uniprot_mappings(pdb_id)
            
            for entity in entities:
                try:
                    eid = str(entity.get('entity_id', ''))
                    if not eid:
                        continue
                    
                    # 从RCSB数据提取基本信息
                    entity_data = entity.get('entity_data', {})
                    
                    # 确定分子类型
                    mol_type = 'unknown'
                    if 'pdbx_entity_molecule_type' in entity_data:
                        mol_type = entity_data.get('pdbx_entity_molecule_type', 'unknown').lower()
                    elif 'rcsb_entity_source_organism' in entity_data:
                        mol_type = 'polypeptide(l)'
                    
                    norm_entity = {
                        'entity_id': eid,
                        'molecule_type': mol_type,
                        'molecule_name': [],
                        'description': '',
                        'chain_ids': [],
                        'asym_ids': [],
                        'in_chains': [],
                        'sequence': '',
                        'length': 0,
                        'weight': 0.0,
                        'number_of_copies': 1,
                        'source_organism': '',
                        'expression_host': '',
                        'taxon_id': '',
                        'gene_names': [],
                        'uniprot_ids': [],
                        'start_residue': None,
                        'end_residue': None,
                        'uniprot_ranges': [],
                        'entity_data': None
                    }
                    
                    # 提取序列
                    poly = entity_data.get('entity_poly', {})
                    seq = poly.get('pdbx_seq_one_letter_code_can') or poly.get('pdbx_seq_one_letter_code', '')
                    if seq:
                        norm_entity['sequence'] = seq
                        norm_entity['length'] = len(seq)
                        norm_entity['start_residue'] = 1
                        norm_entity['end_residue'] = len(seq)
                    
                    # 提取链信息
                    container_ids = entity_data.get('rcsb_polymer_entity_container_identifiers', {})
                    if container_ids:
                        norm_entity['asym_ids'] = container_ids.get('asym_ids', [])
                        norm_entity['in_chains'] = container_ids.get('asym_ids', [])
                        norm_entity['chain_ids'] = container_ids.get('auth_asym_ids', [])
                    
                    # 从RCSB UniProt映射获取信息
                    if eid in rcsb_uniprot_mappings:
                        rcsb_info = rcsb_uniprot_mappings[eid]
                        norm_entity['uniprot_ids'] = rcsb_info.get('uniprot_ids', [])
                        norm_entity['gene_names'] = rcsb_info.get('gene_names', [])
                        
                        # 添加到总集合
                        for uniprot_id in norm_entity['uniprot_ids']:
                            uniprot_ids_in_structure.add(uniprot_id)
                    
                    # 提取描述
                    description = entity_data.get('pdbx_description', '')
                    if description:
                        norm_entity['description'] = description
                    
                    # 提取生物体信息
                    source_org = entity_data.get('rcsb_entity_source_organism', [])
                    if source_org and isinstance(source_org, list):
                        first_source = source_org[0]
                        norm_entity['source_organism'] = first_source.get('ncbi_scientific_name', '')
                        norm_entity['taxon_id'] = str(first_source.get('ncbi_taxonomy_id', ''))
                    
                    normalized_entities.append(norm_entity)
                    
                except Exception as e:
                    logger.warning(f"处理回退实体 {eid} 时出错: {e}")
                    continue
            
            # 构建返回结果
            if uniprot_ids_in_structure:
                extracted['uniprot_ids'] = list(uniprot_ids_in_structure)
            
            extracted['entities'] = normalized_entities
            
            # 移除entity_data字段
            for entity in extracted['entities']:
                if 'entity_data' in entity:
                    del entity['entity_data']
            
            logger.info(f"使用回退方法提取 [{pdb_id}] 实体: {len(normalized_entities)}个, UniProt IDs: {len(uniprot_ids_in_structure)}")
            
        except Exception as e:
            logger.error(f"回退方法提取实体失败 {pdb_id}: {e}")
        
        return extracted

    def _extract_metadata_from_uniprot(self, mappings: List[Dict], details: Dict, pdb_id: str) -> Dict:
        """从UniProt映射中提取元数据"""
        extracted = {}
        
        try:
            uniprot_ids = []
            
            for mapping in mappings:
                uniprot_id = mapping.get('uniprot_id')
                if uniprot_id:
                    uniprot_ids.append(uniprot_id)
                    
                    # 如果有详细信息，可以提取更多
                    if uniprot_id in details:
                        detail = details[uniprot_id]
                        # 可以根据需要提取更多信息
            
            if uniprot_ids:
                extracted['uniprot_ids'] = list(set(uniprot_ids))
            
        except Exception as e:
            logger.warning(f"提取UniProt信息失败 {pdb_id}: {e}")
        
        return extracted
    
    def _normalize_entity_for_metadata(self, rcsb_entity_data: Dict, pdbe_mol_data: Dict = None) -> Dict:
        """
        标准化实体数据 V2
        使用 PDBe 数据填充 molecule_type 和 uniprot_ids
        使用 RCSB 数据填充详细分类学信息和序列
        """
        normalized = {
            'entity_id': rcsb_entity_data.get('entity_id', ''),
            'chain_ids': [],
            'asym_ids': [],
            'sequence': '',
            'description': '',
            'length': 0,
            'source_organism': '', # 字符串或字典
            'taxon_id': '',
            'weight': 0.0,
            'gene_names': [],
            'in_chains': [],
            'number_of_copies': 1,
            'molecule_name': [],
            'molecule_type': '', # 关键字段：修复它
            'uniprot_ids': []    # 关键字段：修复它
        }

        # === A. 基础数据提取 (RCSB) ===
        # 尝试获取 raw_data
        raw_data = rcsb_entity_data.get('entity_data', {})
        if not raw_data:
            raw_data = rcsb_entity_data

        # 1. 提取 Chains (in_chains) - 修复逻辑
        container_ids = raw_data.get('rcsb_polymer_entity_container_identifiers', {})
        if container_ids:
            asym_ids = container_ids.get('asym_ids', [])
            auth_ids = container_ids.get('auth_asym_ids', [])
            normalized['asym_ids'] = asym_ids
            normalized['in_chains'] = asym_ids # 使用 asym_ids 作为 in_chains
            if auth_ids:
                normalized['chain_ids'] = auth_ids

        # 2. 提取 Description / Molecule Name
        poly_entity = raw_data.get('rcsb_polymer_entity', {})
        if poly_entity:
            desc = poly_entity.get('pdbx_description', '')
            normalized['description'] = desc
            combined_names = poly_entity.get('rcsb_macromolecular_names_combined', [])
            if combined_names:
                names = [n.get('name') for n in combined_names if n.get('name')]
                normalized['molecule_name'] = list(set(names))

        # 3. 提取 序列
        entity_poly = raw_data.get('entity_poly', {})
        if entity_poly:
            seq = entity_poly.get('pdbx_seq_one_letter_code_can') or entity_poly.get('pdbx_seq_one_letter_code', '')
            if seq:
                normalized['sequence'] = seq
                normalized['length'] = len(seq)

        # 4. 提取 Gene Names
        gene_list = raw_data.get('rcsb_gene_name', [])
        if not gene_list:
            gene_list = raw_data.get('rcsb_polymer_entity_container_identifiers', {}).get('gene_names', [])
        
        if gene_list:
            genes = []
            for g in gene_list:
                if isinstance(g, str):
                    genes.append(g)
                elif isinstance(g, dict):
                    genes.append(g.get('value'))
            normalized['gene_names'] = list(set(filter(None, genes)))

        # 5. 提取 Source Organism
        src_org_list = raw_data.get('rcsb_entity_source_organism', [])
        if src_org_list and isinstance(src_org_list, list) and len(src_org_list) > 0:
            first_source = src_org_list[0]
            normalized['source_organism'] = {
                'scientific_name': first_source.get('ncbi_scientific_name', ''),
                'taxonomy_id': str(first_source.get('ncbi_taxonomy_id', '')),
                'common_name': first_source.get('ncbi_common_names', [''])[0] if first_source.get('ncbi_common_names') else ''
            }
            normalized['taxon_id'] = str(first_source.get('ncbi_taxonomy_id', ''))

        # === B. 关键修正数据提取 (PDBe Molecules) ===
        if pdbe_mol_data:
            # 1. Molecule Type (如 protein, dna, rna)
            mol_type = pdbe_mol_data.get('molecule_type')
            if mol_type:
                normalized['molecule_type'] = mol_type.lower() # 存为小写
            
            # 2. UniProt ID
            uni_id = pdbe_mol_data.get('uniprot_accession')
            if uni_id:
                normalized['uniprot_ids'] = [uni_id]
            
            # 3. 覆盖 Description (如果 RCSB 为空)
            if not normalized['description'] and pdbe_mol_data.get('name'):
                normalized['description'] = pdbe_mol_data['name']
                normalized['molecule_name'] = [pdbe_mol_data['name']]

        # === C. 兜底逻辑 ===
        if not normalized['description']:
            normalized['description'] = raw_data.get('description', '')
        if not normalized['length']:
            normalized['length'] = raw_data.get('length', 0)

        return normalized
    def _extract_gene_names_from_entity(self, entity_data: Dict) -> List[str]:
        """从实体数据中提取基因名"""
        gene_names = []
        
        try:
            # 尝试从原始数据中提取
            raw_entity = entity_data.get('entity_data', {})
            if raw_entity:
                # 检查rcsb_polymer_entity中的gene字段
                if 'rcsb_polymer_entity' in raw_entity:
                    gene_info = raw_entity['rcsb_polymer_entity'].get('rcsb_gene_source_organism', [])
                    for gene in gene_info:
                        gene_name = gene.get('gene_name', {}).get('value', '')
                        if gene_name:
                            gene_names.append(gene_name)
                
                # 检查rcsb_polymer_entity_container_identifiers中的gene信息
                container_ids = raw_entity.get('rcsb_polymer_entity_container_identifiers', {})
                if 'gene_names' in container_ids:
                    gene_names.extend(container_ids['gene_names'])
        except Exception as e:
            logger.debug(f"提取基因名失败: {e}")
        
        return gene_names

    def _save_uniprot_info_from_fetcher_result(
        self, 
        pdb_id: str, 
        pdb_metadata: PDBMetadata, 
        fetcher_result: Dict
    ):
        """
        使用fetcher结果保存UniProt信息到数据库
        
        参数:
            pdb_id: PDB ID
            pdb_metadata: PDB元数据对象
            fetcher_result: PDBFetcher返回的完整信息
        """
        try:
            from core.structure_database import get_enhanced_structure_manager
            
            # 获取数据库实例
            structure_db = get_enhanced_structure_manager()
            if not structure_db:
                logger.warning("离线数据库管理器不可用")
                return
            
            mappings = fetcher_result.get('uniprot_mappings', [])
            uniprot_details = fetcher_result.get('uniprot_details', {})
            entities = fetcher_result.get('entities', [])
            
            logger.info(f"开始保存UniProt信息: {len(mappings)}个映射, {len(uniprot_details)}个详情")
            
            saved_count = 0
            entity_mapping_count = 0
            
            # 保存每个UniProt映射
            for mapping in mappings:
                uniprot_id = mapping.get('uniprot_id')
                if not uniprot_id:
                    continue
                
                # 获取UniProt详细信息
                uniprot_detail = uniprot_details.get(uniprot_id, {})
                
                # 准备UniProt条目数据
                uniprot_entry_data = {
                    'id': uniprot_id,
                    'uniprot_id': uniprot_id,
                    'entry_name': uniprot_detail.get('entry_name', ''),
                    'protein_name': uniprot_detail.get('protein_name', ''),
                    'gene_names': uniprot_detail.get('gene_names', []),
                    'organism': uniprot_detail.get('organism', ''),
                    'organism_id': uniprot_detail.get('organism_id', ''),
                    'function': uniprot_detail.get('function', ''),
                    'sequence_length': uniprot_detail.get('sequence_length', 0),
                    'mass': uniprot_detail.get('mass', 0),
                    'pdb_ids': [pdb_id],
                    'keywords': uniprot_detail.get('keywords', []),
                    'source': 'uniprot_rest_api',
                    'type': 'uniprot'
                }
                
                # 保存UniProt条目
                saved_entry = structure_db.database.save_structure(uniprot_entry_data, "uniprot")
                
                # 保存UniProt-结构映射
                if saved_entry:
                    mapping_saved = structure_db.database.add_uniprot_structure_mapping(
                        uniprot_id=uniprot_id,
                        structure_id=pdb_id,
                        protein_name=uniprot_detail.get('protein_name', ''),
                        gene_name=uniprot_detail.get('gene_names', [''])[0] if uniprot_detail.get('gene_names') else '',
                        confidence=1.0,
                        source="pdbe_api_official"
                    )
                    
                    if mapping_saved:
                        saved_count += 1
                
                # 保存实体映射
                chains = mapping.get('chains', [])
                for chain in chains:
                    if isinstance(chain, dict):
                        entity_id = chain.get('entity_id')
                        chain_id = chain.get('chain_id')
                        
                        if entity_id and chain_id:
                            # 提取序列范围
                            unp_start = None
                            unp_end = None
                            pdb_start = None
                            pdb_end = None
                            
                            if 'mappings' in chain and chain['mappings']:
                                for mapping_info in chain['mappings']:
                                    if isinstance(mapping_info, dict):
                                        unp_start = mapping_info.get('unp_start')
                                        unp_end = mapping_info.get('unp_end')
                                        pdb_start = mapping_info.get('pdb_start')
                                        pdb_end = mapping_info.get('pdb_end')
                                        break
                            
                            # 准备映射数据
                            mapping_data = {
                                'id': f"{uniprot_id}_{pdb_id}_{entity_id}",
                                'uniprot_id': uniprot_id,
                                'pdb_id': pdb_id,
                                'entity_id': str(entity_id),
                                'match_score': 1.0,  # 官方映射，置信度高
                                'match_evidence': 'official_mapping_from_pdbe',
                                'entity_info': {
                                    'entity_id': entity_id,
                                    'chain_id': chain_id,
                                    'uniprot_range': f"{unp_start}-{unp_end}" if unp_start and unp_end else '',
                                    'pdb_range': f"{pdb_start}-{pdb_end}" if pdb_start and pdb_end else ''
                                },
                                'uniprot_info': {
                                    'uniprot_id': uniprot_id,
                                    'protein_name': uniprot_detail.get('protein_name', ''),
                                    'gene_names': uniprot_detail.get('gene_names', [])
                                },
                                'created_at': datetime.now().isoformat(),
                                'source': 'pdbe_api_official',
                                'type': 'uniprot_entity_mapping'
                            }
                            
                            # 保存实体映射
                            if structure_db.database.save_structure(mapping_data, "uniprot_entity_mapping"):
                                entity_mapping_count += 1
                                logger.info(f"✅ 实体映射保存: {uniprot_id} -> {pdb_id}/{entity_id}")
            
            logger.info(f"✅ UniProt信息保存完成: {saved_count}/{len(mappings)} 个条目, {entity_mapping_count} 个实体映射")
            
        except ImportError as e:
            logger.warning(f"无法导入离线数据库模块: {e}")
        except Exception as e:
            logger.error(f"保存UniProt信息失败: {e}")

    def _build_pdb_metadata(self, metadata_dict: Dict, pdb_id: str) -> PDBMetadata:
        """构建PDB元数据对象（确保包含所有信息）"""
        pdb_id = pdb_id.upper()
        
        # 确保关键字段存在
        if 'organism' not in metadata_dict:
            metadata_dict['organism'] = 'Unknown'
        
        if 'title' not in metadata_dict:
            metadata_dict['title'] = f'Structure of {pdb_id}'
        
        if 'method' not in metadata_dict:
            metadata_dict['method'] = 'Unknown'
        
        if 'resolution' not in metadata_dict:
            metadata_dict['resolution'] = 0.0
        
        # 构建元数据对象
        metadata = PDBMetadata(
            pdb_id=pdb_id,
            title=metadata_dict.get('title', f'Structure of {pdb_id}'),
            resolution=metadata_dict.get('resolution', 0.0),
            method=metadata_dict.get('method', 'Unknown'),
            deposition_date=metadata_dict.get('deposition_date', ''),
            organism=metadata_dict.get('organism', 'Unknown'),
            expression_system=metadata_dict.get('expression_system'),
            expression_system_strain=metadata_dict.get('expression_system_strain'),
            gene=metadata_dict.get('gene'),
            release_date=metadata_dict.get('release_date'),
            authors=metadata_dict.get('authors'),
            citation_count=metadata_dict.get('citation_count'),
            binding_sites=metadata_dict.get('binding_sites'),
            molecular_weight=metadata_dict.get('molecular_weight'),
            polymer_count=metadata_dict.get('polymer_count'),
            uniprot_ids=metadata_dict.get('uniprot_ids', []),
            protein_name=metadata_dict.get('protein_name'),
            ec_numbers=metadata_dict.get('ec_numbers'),
            entities=metadata_dict.get('entities', []),
            sequence_length=metadata_dict.get('sequence_length'),
            last_updated=datetime.now().isoformat()
        )
        
        # 记录详细信息
        logger.info(f"构建PDB元数据 {pdb_id}:")
        logger.info(f"  - 标题: {metadata.title}")
        logger.info(f"  - 蛋白质: {metadata.protein_name}")
        logger.info(f"  - 基因: {metadata.gene}")
        logger.info(f"  - 生物体: {metadata.organism}")
        logger.info(f"  - UniProt IDs: {len(metadata.uniprot_ids)} 个")
        logger.info(f"  - 实体数量: {len(metadata.entities) if metadata.entities else 0}")
        
        return metadata

    def _extract_binding_sites_info(self, binding_sites_data: Dict, pdb_id: str) -> Dict:
        extracted = {}
        pdb_id = pdb_id.lower()
        
        try:
            if pdb_id in binding_sites_data:
                sites = binding_sites_data[pdb_id]
                binding_sites = []
                
                for site in sites:
                    site_info = {
                        'site_id': site.get('site_id', ''),
                        'description': site.get('description', ''),
                        'residues': site.get('residues', []),
                        'ligands': site.get('ligands', [])
                    }
                    binding_sites.append(site_info)
                
                if binding_sites:
                    extracted['binding_sites'] = binding_sites
                
        except Exception as e:
            logger.warning(f"提取binding_sites信息失败 {pdb_id}: {e}")
        
        return extracted
    
    def filter_pdb_ids_by_emdb_association(self, pdb_ids: List[str], 
                                        pdb_metadata: Dict[str, Any],
                                        literature_emdb_ids: List[str] = None) -> List[str]:
        """
        简化版本 - 只进行格式验证，真正的过滤由 apply_final_filtering 方法处理
        
        参数:
            pdb_ids: PDB ID列表
            pdb_metadata: PDB元数据字典
            literature_emdb_ids: 文献中提到的EMDB ID列表
            
        返回:
            直接返回所有有效的PDB ID
        """
        logger.info("📝 简化版PDB验证：只验证格式")
        
        # 只做基本格式验证
        valid_pdb_ids = []
        for pdb_id in pdb_ids:
            if not pdb_id or not isinstance(pdb_id, str):
                continue
                
            pdb_id_clean = pdb_id.strip().upper()
            
            # 标准PDB格式：4个字符，第一个是数字
            if len(pdb_id_clean) == 4 and pdb_id_clean[0].isdigit():
                valid_pdb_ids.append(pdb_id_clean)
        
        logger.info(f"格式验证后PDB IDs: {len(valid_pdb_ids)}个")
        
        return valid_pdb_ids

    @staticmethod
    def fix_existing_database_duplicates():
        """修复现有数据库中的重复数据（简化版）"""
        try:
            from core.structure_database import EnhancedStructureManager
            
            structure_db = EnhancedStructureManager()
            
            if not structure_db:
                logger.error("无法连接数据库")
                return
            
            # 使用数据库层的方法修复重复数据
            result = structure_db.validate_and_fix_database()
            
            if result.get('success'):
                logger.info(f"✅ 数据库修复完成: {result}")
            else:
                logger.error(f"数据库修复失败: {result.get('error')}")
            
        except Exception as e:
            logger.error(f"数据库修复失败: {e}")

    def save_to_offline_database_enhanced(self, structure_metadata: Dict[str, Any], 
                                        structure_type: str = "mixed", 
                                        force_update: bool = True,
                                        failed_ids: List[str] = None,
                                        cleanup_old_data: bool = False,
                                        validate_before_save: bool = True) -> Dict[str, Any]:
        """增强版的保存方法（确保实体信息保存）"""
        result = {
            "success_count": 0,
            "failed_count": 0,
            "warnings": {},
            "errors": [],
            "total_structures": len(structure_metadata),
            "entities_saved": 0
        }
        
        try:
            from core.structure_database import get_enhanced_structure_manager, StructureType
            
            structure_db = get_enhanced_structure_manager()
            
            if not structure_db:
                logger.warning("离线数据库管理器不可用")
                result["errors"].append("database_unavailable")
                return result
            
            logger.info(f"开始保存 {len(structure_metadata)} 个结构到离线数据库")
            logger.info(f"  结构类型: {structure_type}, 强制更新: {force_update}")
            
            success_count = 0
            failed_count = 0
            entities_saved = 0
            
            for structure_id, metadata in structure_metadata.items():
                try:
                    # 确定结构类型
                    structure_id = structure_id.upper()
                    
                    if len(structure_id) == 4 and structure_id[0].isdigit():
                        db_type = StructureType.PDB
                        type_str = "pdb"
                    elif structure_id.startswith('EMD-'):
                        db_type = StructureType.EMDB
                        type_str = "emdb"
                    elif structure_id.startswith('AF-'):
                        db_type = StructureType.ALPHAFOLD
                        type_str = "alphafold"
                    else:
                        db_type = StructureType.PDB
                        type_str = "pdb"
                    
                    # 准备数据
                    if hasattr(metadata, '__dict__'):
                        metadata_dict = metadata.__dict__
                    else:
                        metadata_dict = metadata
                    
                    # 关键：检查并记录实体信息
                    has_entities = False
                    entities_count = 0
                    
                    if 'entities' in metadata_dict and metadata_dict['entities']:
                        has_entities = True
                        entities_count = len(metadata_dict['entities'])
                        entities_saved += entities_count
                        logger.info(f"结构 {structure_id} 有 {entities_count} 个实体信息")
                        
                        # 记录第一个实体的信息
                        if entities_count > 0:
                            first_entity = metadata_dict['entities'][0]
                            logger.debug(f"第一个实体: entity_id={first_entity.get('entity_id')}, "
                                    f"molecule_name={first_entity.get('molecule_name')}")
                    
                    # 确保有ID字段和type字段
                    metadata_dict['id'] = structure_id
                    metadata_dict['type'] = type_str
                    
                    # 保存到数据库
                    saved = structure_db.database.save_structure(metadata_dict, db_type)
                    
                    if saved:
                        success_count += 1
                        logger.debug(f"保存结构 {structure_id} 到离线数据库成功 (类型: {type_str})")
                        if has_entities:
                            logger.debug(f"  包含 {entities_count} 个实体信息")
                    else:
                        failed_count += 1
                        logger.warning(f"保存结构 {structure_id} 到离线数据库失败")
                        
                except Exception as e:
                    logger.error(f"保存结构 {structure_id} 时出错: {e}")
                    failed_count += 1
            
            result["success_count"] = success_count
            result["failed_count"] = failed_count
            result["entities_saved"] = entities_saved
            result["success_rate"] = success_count / len(structure_metadata) * 100 if structure_metadata else 0
            
            logger.info(f"✅ 保存到离线数据库完成: 成功 {success_count}/{len(structure_metadata)} 个结构")
            logger.info(f"   实体信息保存: {entities_saved} 个实体")
            
            return result
                
        except ImportError as e:
            error_msg = f"无法导入离线数据库模块: {e}"
            logger.warning(error_msg)
            result["errors"].append(error_msg)
            return result
            
        except Exception as e:
            error_msg = f"保存到离线数据库失败: {e}"
            logger.error(error_msg)
            result["errors"].append(error_msg)
            return result
        
    def save_relationships_to_database(self, relationships: List[StructureRelationship]) -> bool:
        """保存所有关联关系到数据库（修复版，不依赖不存在的find_relationships方法）"""
        try:
            from core.structure_database import EnhancedStructureManager
            
            structure_db = EnhancedStructureManager()
            if not structure_db:
                logger.warning("离线数据库管理器不可用")
                return False
            
            success_count = 0
            failed_count = 0
            
            for rel in relationships:
                try:
                    rel_dict = asdict(rel) if hasattr(rel, '__dict__') else rel
                    
                    # 直接保存，不再检查是否已存在（让数据库层处理重复）
                    saved = structure_db.save_relationship(rel_dict)
                    if saved:
                        success_count += 1
                        logger.debug(f"保存关系 {rel.source_id} -> {rel.target_id} ({rel.relationship_type})")
                    else:
                        failed_count += 1
                        logger.warning(f"保存关系 {rel.source_id} -> {rel.target_id} 失败")
                        
                except Exception as e:
                    logger.error(f"保存关系 {rel.source_id} -> {rel.target_id} 失败: {e}")
                    failed_count += 1
            
            logger.info(f"保存关系到数据库完成: 成功 {success_count}/{len(relationships)} 个关系，失败 {failed_count} 个")
            
            return success_count > 0 or failed_count == 0
                
        except Exception as e:
            logger.error(f"保存关系到数据库失败: {e}")
            return False
    
    def save_structure_groups_to_database(self, groups: List[Dict[str, Any]]) -> bool:
        """保存结构分组到数据库（避免重复存储）"""
        try:
            from core.structure_database import get_enhanced_structure_manager
            
            structure_db = get_enhanced_structure_manager()
            if not structure_db:
                logger.warning("离线数据库管理器不可用")
                return False
            
            success_count = 0
            for group in groups:
                try:
                    group_id = group.get('group_id')
                    structure_ids = group.get('structure_ids', [])
                    
                    if not group_id or not structure_ids:
                        continue
                    
                    # 简化的分组信息，避免重复存储
                    simplified_group_info = {
                        'group_id': group_id,
                        'structure_ids': structure_ids,
                        'is_combined': group.get('is_combined', False),
                        'structure_count': group.get('structure_count', len(structure_ids)),
                        'primary_structure_id': None,
                        'relationship_count': group.get('relationship_count', 0),
                        'group_metadata': {
                            'description': f"Group of {len(structure_ids)} structures",
                            'created_at': datetime.now().isoformat()
                        }
                    }
                    
                    # 如果有主要结构，只存储ID而不是完整数据
                    if group.get('primary_structure'):
                        primary = group['primary_structure']
                        if isinstance(primary, dict) and 'id' in primary:
                            simplified_group_info['primary_structure_id'] = primary['id']
                    
                    # 为分组中的每个结构保存简化信息
                    for struct_id in structure_ids:
                        try:
                            # 获取现有结构数据（如果存在）
                            existing_structure = structure_db.get_or_fetch_structure(struct_id)
                            
                            if existing_structure:
                                # 只添加分组ID，不重复存储完整数据
                                existing_structure['group_ids'] = existing_structure.get('group_ids', [])
                                if group_id not in existing_structure['group_ids']:
                                    existing_structure['group_ids'].append(group_id)
                                
                                # 保存简化后的分组信息
                                existing_structure['simplified_group_info'] = simplified_group_info
                                
                                # 更新结构数据
                                saved = structure_db.update_structure_metadata(struct_id, existing_structure)
                                if saved:
                                    success_count += 1
                                    logger.debug(f"为结构 {struct_id} 添加分组信息成功")
                                else:
                                    logger.warning(f"为结构 {struct_id} 添加分组信息失败")
                            
                        except Exception as e:
                            logger.error(f"处理结构 {struct_id} 的分组信息失败: {e}")
                    
                    # 也保存到structure_groups表（简化版）
                    try:
                        group_data = json.dumps(simplified_group_info, ensure_ascii=False)
                        
                        # 这里调用数据库方法保存分组
                        # 假设structure_db.database.save_structure_group存在
                        if hasattr(structure_db.database, 'save_structure_group'):
                            structure_db.database.save_structure_group({
                                'group_id': group_id,
                                'structure_ids': structure_ids,
                                'group_data': group_data
                            })
                            logger.debug(f"保存分组 {group_id} 到数据库")
                            
                    except Exception as e:
                        logger.warning(f"保存分组到数据库失败: {e}")
                        
                except Exception as e:
                    logger.error(f"保存分组信息失败: {e}")
            
            logger.info(f"保存分组信息完成: 成功 {success_count} 个结构的分组信息")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"保存分组信息到数据库失败: {e}")
            return False
    
    def get_pdb_info(self, pdb_id: str) -> Dict[str, Any]:
        metadata = self.fetch_pdb_metadata(pdb_id)
        if metadata is None:
            return {}
        
        info = {
            "pdb_id": metadata.pdb_id,
            "title": metadata.title,
            "method": metadata.method,
            "resolution": metadata.resolution,
            "deposition_date": metadata.deposition_date,
            "release_date": metadata.release_date,
            "organism": metadata.organism,
            "expression_system": metadata.expression_system,
            "related_emdb_ids": metadata.related_emdb_ids,
            "citation": metadata.citation,
            "authors": metadata.authors,
            "uniprot_ids": metadata.uniprot_ids
        }
        return info
    
    def normalize_emdb_id(self, emdb_id: str) -> str:
        emdb_id = emdb_id.strip().upper()
        
        if emdb_id.startswith('EMD-'):
            return emdb_id
        
        match = re.search(r'(\d+)', emdb_id)
        if match:
            return f"EMD-{match.group(1)}"
        
        return f"EMD-{emdb_id}"
    
    def get_emdb_id_number(self, emdb_id: str) -> str:
        emdb_id = emdb_id.strip().upper()
        
        if emdb_id.startswith('EMD-'):
            return emdb_id.replace('EMD-', '')
        
        match = re.search(r'(\d+)', emdb_id)
        if match:
            return match.group(1)
        
        return emdb_id
    
    def normalize_pdb_id(self, pdb_id: str) -> str:
        pdb_id = pdb_id.strip().upper()
        if len(pdb_id) == 4 and pdb_id.isalnum():
            return pdb_id
        match = re.search(r'\b([1-9][A-Za-z0-9]{3})\b', pdb_id)
        if match:
            return match.group(1).upper()
        return pdb_id.upper()
    
    def classify_ids(self, ids: List[str]) -> Tuple[List[str], List[str]]:
        pdb_ids = []
        emdb_ids = []
        
        logger.info(f"classify_ids 输入: {ids}")
        
        for id_str in ids:
            if not id_str or not isinstance(id_str, str):
                continue
                
            id_str = id_str.strip().upper()
            
            if len(id_str) == 4 and id_str.isalnum():
                pdb_ids.append(id_str)
            elif "EMD" in id_str or re.match(r'^\d+$', id_str):
                emdb_id = self.normalize_emdb_id(id_str)
                emdb_ids.append(emdb_id)
    
        pdb_ids = list(set(pdb_ids))
        emdb_ids = list(set(emdb_ids))
        
        logger.info(f"classify_ids 结果: PDB={len(pdb_ids)}个 ({pdb_ids}), EMDB={len(emdb_ids)}个 ({emdb_ids})")
        
        return pdb_ids, emdb_ids
    
    def fetch_emdb_metadata(self, emdb_id: str, use_cache: bool = True, force_update: bool = False) -> Optional[EMDBMetadata]:
        emdb_number = self.get_emdb_id_number(emdb_id)
        
        logger.info(f"获取EMDB元数据，ID数字部分: {emdb_number}")
        
        cache_key = f"EMDB_{emdb_number}"
        if use_cache and not force_update:
            cached = self.cache.get(cache_key)
            if cached:
                try:
                    return EMDBMetadata(**cached)
                except Exception as e:
                    logger.warning(f"反序列化EMDB缓存失败 {emdb_number}: {e}")
        
        try:
            url = f"{self.emdb_base_url}/entry/{emdb_number}"
            
            headers = {
                'accept': 'application/json',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            }
            
            max_retries = 3
            retry_delay = 2
            
            for retry in range(max_retries):
                try:
                    logger.info(f"请求EMDB API: {url} (尝试 {retry+1}/{max_retries})")
                    response = requests.get(url, headers=headers, timeout=self.timeout)
                    
                    if response.status_code != 200:
                        logger.warning(f"无法获取EMDB {emdb_number} (状态码: {response.status_code})")
                        logger.warning(f"响应内容: {response.text[:200]}")
                        if retry < max_retries - 1:
                            logger.info(f"等待 {retry_delay} 秒后重试...")
                            time.sleep(retry_delay)
                            retry_delay *= 1.5
                            continue
                        else:
                            return None
                    
                    break  # 成功获取响应，跳出重试循环
                    
                except requests.exceptions.SSLError as e:
                    logger.error(f"获取EMDB {emdb_number} 时SSL错误: {e}")
                    if retry < max_retries - 1:
                        logger.info(f"等待 {retry_delay} 秒后重试...")
                        time.sleep(retry_delay)
                        retry_delay *= 1.5
                        continue
                    else:
                        logger.error(f"获取EMDB {emdb_number} 失败，已尝试 {max_retries} 次")
                        return None
                        
                except requests.exceptions.RequestException as e:
                    logger.error(f"获取EMDB {emdb_number} 时网络错误: {e}")
                    if retry < max_retries - 1:
                        logger.info(f"等待 {retry_delay} 秒后重试...")
                        time.sleep(retry_delay)
                        retry_delay *= 1.5
                        continue
                    else:
                        logger.error(f"获取EMDB {emdb_number} 失败，已尝试 {max_retries} 次")
                        return None

            # 验证响应是否为有效JSON
            try:
                data = response.json()
            except ValueError as e:
                logger.warning(f"EMDB {emdb_number} API返回无效JSON: {e}")
                logger.warning(f"响应内容(前200字符): {response.text[:200]}")
                return None
            
            title = "N/A"
            if 'admin' in data and 'title' in data['admin']:
                title = data['admin'].get('title', 'N/A')

            method_str = "Unknown"
            try:
                # 路径: structure_determination_list -> structure_determination -> [0] -> method
                det_list = data.get('structure_determination_list', {}).get('structure_determination', [])
                if det_list and isinstance(det_list, list):
                    method_str = det_list[0].get('method', 'Unknown')
                    logger.info(f"提取到 method: {method_str}")
            except Exception as e:
                logger.warning(f"提取 EMDB method 失败: {e}")
            formatted_method = self._format_experimental_method(method_str)

            resolution = 0.0
            try:
                if ('structure_determination_list' in data and 
                    'structure_determination' in data['structure_determination_list'] and
                    len(data['structure_determination_list']['structure_determination']) > 0):
                    
                    sd = data['structure_determination_list']['structure_determination'][0]
                    if ('image_processing' in sd and len(sd['image_processing']) > 0 and
                        'final_reconstruction' in sd['image_processing'][0] and
                        'resolution' in sd['image_processing'][0]['final_reconstruction'] and
                        'valueOf_' in sd['image_processing'][0]['final_reconstruction']['resolution']):
                        
                        res_value = sd['image_processing'][0]['final_reconstruction']['resolution']['valueOf_']
                        resolution = float(res_value)
            except (KeyError, IndexError, ValueError, TypeError) as e:
                logger.warning(f"解析EMDB {emdb_number} 分辨率时出错: {e}")
            
            deposition_date = "N/A"
            if ('admin' in data and 'key_dates' in data['admin'] and 
                'deposition' in data['admin']['key_dates']):
                date_str = data['admin']['key_dates'].get('deposition', 'N/A')
                if date_str != 'N/A' and 'T' in date_str:
                    deposition_date = date_str.split('T')[0]
                else:
                    deposition_date = date_str
            
            related_pdb_ids = []
            if ('crossreferences' in data and 'pdb_list' in data['crossreferences'] and
                'pdb_reference' in data['crossreferences']['pdb_list']):
                
                pdb_refs = data['crossreferences']['pdb_list']['pdb_reference']
                if isinstance(pdb_refs, list):
                    for ref in pdb_refs:
                        if 'pdb_id' in ref:
                            related_pdb_ids.append(self.normalize_pdb_id(ref['pdb_id']))
                elif isinstance(pdb_refs, dict) and 'pdb_id' in pdb_refs:
                    related_pdb_ids.append(self.normalize_pdb_id(pdb_refs['pdb_id']))
            
            organism = "Unknown"
            expression_system = None
            tissue_source = None
            supramolecule_name = None
            molecular_weight = None
            
            try:
                def extract_from_natural_source(natural_source):
                    org = "Unknown"
                    tissue = None
                    cell_info = None
                    
                    if isinstance(natural_source, dict):
                        if 'organism' in natural_source:
                            org_data = natural_source['organism']
                            if isinstance(org_data, dict) and 'valueOf_' in org_data:
                                org = org_data.get('valueOf_', 'Unknown')
                            elif isinstance(org_data, str):
                                org = org_data
                        
                        if 'tissue' in natural_source:
                            tissue_data = natural_source['tissue']
                            if isinstance(tissue_data, str):
                                tissue = tissue_data
                            elif isinstance(tissue_data, dict) and 'valueOf_' in tissue_data:
                                tissue = tissue_data.get('valueOf_')
                        
                        if 'cell' in natural_source:
                            cell_data = natural_source['cell']
                            if isinstance(cell_data, str):
                                cell_info = cell_data
                            elif isinstance(cell_data, dict) and 'valueOf_' in cell_data:
                                cell_info = cell_data.get('valueOf_')
                    
                    elif isinstance(natural_source, list) and len(natural_source) > 0:
                        return extract_from_natural_source(natural_source[0])
                    
                    if cell_info and not tissue:
                        tissue = cell_info
                    
                    return org, tissue
                
                def extract_from_recombinant_expression(recombinant_expr):
                    if not recombinant_expr:
                        return None
                    
                    expr_parts = []
                    
                    if isinstance(recombinant_expr, dict):
                        if 'recombinant_organism' in recombinant_expr:
                            expr_org = recombinant_expr['recombinant_organism']
                            if isinstance(expr_org, dict) and 'valueOf_' in expr_org:
                                expr_parts.append(expr_org.get('valueOf_'))
                            elif isinstance(expr_org, str):
                                expr_parts.append(expr_org)
                        
                        if 'recombinant_cell' in recombinant_expr:
                            expr_cell = recombinant_expr['recombinant_cell']
                            if isinstance(expr_cell, str):
                                expr_parts.append(expr_cell)
                            elif isinstance(expr_cell, dict) and 'valueOf_' in expr_cell:
                                expr_parts.append(expr_cell.get('valueOf_'))
                    elif isinstance(recombinant_expr, list) and len(recombinant_expr) > 0:
                        return extract_from_recombinant_expression(recombinant_expr[0])
                    
                    return '; '.join(expr_parts) if expr_parts else None
                
                def extract_molecular_weight(mol_weight_data):
                    if not mol_weight_data:
                        return None
                    
                    if isinstance(mol_weight_data, dict):
                        if 'experimental' in mol_weight_data:
                            exp_data = mol_weight_data['experimental']
                            if isinstance(exp_data, dict) and 'valueOf_' in exp_data:
                                return exp_data.get('valueOf_')
                        
                        if 'theoretical' in mol_weight_data:
                            theo_data = mol_weight_data['theoretical']
                            if isinstance(theo_data, dict) and 'valueOf_' in theo_data:
                                return theo_data.get('valueOf_')
                    
                    return None
                
                sample_data = data.get('sample', {})
                
                macromolecules = None
                if 'macromolecule_list' in sample_data and 'macromolecule' in sample_data['macromolecule_list']:
                    macromolecules = sample_data['macromolecule_list']['macromolecule']
                    if not isinstance(macromolecules, list):
                        macromolecules = [macromolecules]
                
                supramolecules = None
                if 'supramolecule_list' in sample_data and 'supramolecule' in sample_data['supramolecule_list']:
                    supramolecules = sample_data['supramolecule_list']['supramolecule']
                    if not isinstance(supramolecules, list):
                        supramolecules = [supramolecules]
                
                if 'name' in sample_data:
                    name_data = sample_data['name']
                    if isinstance(name_data, dict) and 'valueOf_' in name_data:
                        supramolecule_name = name_data.get('valueOf_')
                
                if macromolecules:
                    for mol in macromolecules:
                        if not isinstance(mol, dict):
                            continue
                        
                        if not supramolecule_name and 'name' in mol:
                            name_data = mol['name']
                            if isinstance(name_data, dict) and 'valueOf_' in name_data:
                                supramolecule_name = name_data.get('valueOf_')
                        
                        if 'natural_source' in mol:
                            natural_source = mol['natural_source']
                            org, tissue = extract_from_natural_source(natural_source)
                            if org != "Unknown" and organism == "Unknown":
                                organism = org
                            if tissue and not tissue_source:
                                tissue_source = tissue
                        
                        if 'recombinant_expression' in mol and not expression_system:
                            recombinant_expr = mol['recombinant_expression']
                            expression_system = extract_from_recombinant_expression(recombinant_expr)
                        
                        if 'molecular_weight' in mol and not molecular_weight:
                            molecular_weight = extract_molecular_weight(mol['molecular_weight'])
                
                if supramolecules and (organism == "Unknown" or not expression_system or not tissue_source):
                    for sup in supramolecules:
                        if not isinstance(sup, dict):
                            continue
                        
                        if not supramolecule_name and 'name' in sup:
                            name_data = sup['name']
                            if isinstance(name_data, dict) and 'valueOf_' in name_data:
                                supramolecule_name = name_data.get('valueOf_')
                        
                        if 'natural_source' in sup:
                            natural_source = sup['natural_source']
                            org, tissue = extract_from_natural_source(natural_source)
                            if org != "Unknown" and organism == "Unknown":
                                organism = org
                            if tissue and not tissue_source:
                                tissue_source = tissue
                        
                        if 'recombinant_expression' in sup and not expression_system:
                            recombinant_expr = sup['recombinant_expression']
                            expression_system = extract_from_recombinant_expression(recombinant_expr)
                        
                        if 'molecular_weight' in sup and not molecular_weight:
                            molecular_weight = extract_molecular_weight(sup['molecular_weight'])
                
                if not expression_system and organism != "Unknown":
                    expression_system = organism
                
                if molecular_weight and isinstance(molecular_weight, str):
                    try:
                        if ' ' in molecular_weight:
                            value, unit = molecular_weight.split(' ', 1)
                            if unit.lower() == 'mda':
                                molecular_weight = float(value) * 1000
                            else:
                                molecular_weight = float(value)
                        else:
                            molecular_weight = float(molecular_weight)
                    except (ValueError, AttributeError):
                        try:
                            molecular_weight = float(molecular_weight)
                        except (ValueError, AttributeError):
                            molecular_weight = None
                
                logger.debug(f"EMDB {emdb_number} 提取结果: 生物体={organism}, 表达系统={expression_system}, "
                        f"组织来源={tissue_source}, 超分子名称={supramolecule_name}, 分子量={molecular_weight}")
                    
            except (KeyError, IndexError, AttributeError, ValueError, TypeError) as e:
                logger.warning(f"解析EMDB {emdb_number} 样品信息时出错: {e}")
                import traceback
                traceback.print_exc()
            
            map_release_date = None
            if ('admin' in data and 'key_dates' in data['admin'] and 
                'map_release' in data['admin']['key_dates']):
                date_str = data['admin']['key_dates'].get('map_release')
                if date_str and 'T' in date_str:
                    map_release_date = date_str.split('T')[0]
            
            voxel_spacing = None
            try:
                if ('map' in data and 'pixel_spacing' in data['map'] and
                    'x' in data['map']['pixel_spacing']):
                    
                    x_spacing = data['map']['pixel_spacing']['x']
                    
                    if isinstance(x_spacing, dict):
                        if 'valueOf_' in x_spacing:
                            try:
                                voxel_spacing = float(x_spacing['valueOf_'])
                            except (ValueError, TypeError):
                                logger.warning(f"无法从字典中提取体素间距: {x_spacing}")
                        elif 'value' in x_spacing:
                            try:
                                voxel_spacing = float(x_spacing['value'])
                            except (ValueError, TypeError):
                                logger.warning(f"无法从字典中提取体素间距: {x_spacing}")
                        else:
                            try:
                                voxel_spacing = float(str(x_spacing))
                            except (ValueError, TypeError):
                                logger.warning(f"无法解析体素间距字典: {x_spacing}")
                    elif isinstance(x_spacing, (int, float)):
                        voxel_spacing = float(x_spacing)
                    elif isinstance(x_spacing, str):
                        try:
                            voxel_spacing = float(x_spacing)
                        except ValueError:
                            logger.warning(f"无法将字符串转换为浮点数: {x_spacing}")
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"解析EMDB {emdb_number} 体素间距时出错: {e}")
            
            full_emdb_id = f"EMD-{emdb_number}"
            
            metadata = EMDBMetadata(
                emdb_id=full_emdb_id,
                title=title,
                method=formatted_method,
                resolution=resolution,
                deposition_date=deposition_date,
                related_pdb_ids=related_pdb_ids,
                organism=organism,
                map_release_date=map_release_date,
                voxel_spacing=voxel_spacing,
                expression_system=expression_system,
                tissue_source=tissue_source,
                supramolecule_name=supramolecule_name,
                molecular_weight=molecular_weight,
                last_updated=datetime.now().isoformat()
            )
            
            if not force_update:
                self.cache.set(cache_key, asdict(metadata))
            
            logger.info(f"成功获取EMDB元数据: {full_emdb_id} - {title}")
            return metadata
            
        except Exception as e:
            logger.error(f"获取EMDB {emdb_number} 时出错: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def fetch_all_metadata(self, pdb_ids: List[str], emdb_ids: List[str], use_cache: bool = True, 
                        save_to_offline_db: bool = True, force_update: bool = False,
                        cleanup_old_data: bool = True) -> Tuple[Dict[str, PDBMetadata], Dict[str, EMDBMetadata]]:
        
        logger.info(f"开始获取元数据: PDB={len(pdb_ids)}个 ({pdb_ids}), EMDB={len(emdb_ids)}个 ({emdb_ids}), "
                    f"保存到离线数据库={save_to_offline_db}, 强制更新={force_update}, 清理旧数据={cleanup_old_data}")
        
        if force_update:
            logger.info("强制更新模式: 清除相关缓存并重新获取数据")
            for pdb_id in pdb_ids:
                self.cache.clear(f"PDB_{pdb_id}")
            for emdb_id in emdb_ids:
                self.cache.clear(f"EMDB_{self.get_emdb_id_number(emdb_id)}")
        
        pdb_results = {}
        emdb_results = {}
        failed_pdb_ids = []
        failed_emdb_ids = []
        
        # 如果没有需要获取的ID，直接返回空结果
        if not pdb_ids and not emdb_ids:
            logger.warning("没有需要获取的PDB或EMDB ID")
            return pdb_results, emdb_results
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            pdb_futures = {executor.submit(self.fetch_pdb_metadata, pdb_id, use_cache and not force_update, force_update): pdb_id 
                        for pdb_id in pdb_ids}
            
            emdb_futures = {executor.submit(self.fetch_emdb_metadata, emdb_id, use_cache and not force_update, force_update): emdb_id 
                        for emdb_id in emdb_ids}
            
            for future in concurrent.futures.as_completed(pdb_futures):
                pdb_id = pdb_futures[future]
                try:
                    result = future.result(timeout=self.timeout + 10)
                    if result:
                        pdb_results[pdb_id.upper()] = result
                        logger.info(f"✓ 获取PDB {pdb_id} 成功")
                    else:
                        logger.warning(f"✗ 获取PDB {pdb_id} 失败，返回None")
                        failed_pdb_ids.append(pdb_id)
                except concurrent.futures.TimeoutError:
                    logger.error(f"处理PDB {pdb_id} 超时")
                    failed_pdb_ids.append(pdb_id)
                except Exception as e:
                    logger.error(f"处理PDB {pdb_id} 时出错: {e}")
                    failed_pdb_ids.append(pdb_id)
                    import traceback
                    traceback.print_exc()
            
            for future in concurrent.futures.as_completed(emdb_futures):
                emdb_id = emdb_futures[future]
                try:
                    result = future.result(timeout=self.timeout + 10)
                    if result:
                        emdb_results[result.emdb_id] = result
                        logger.info(f"✓ 获取EMDB {result.emdb_id} 成功")
                    else:
                        logger.warning(f"✗ 获取EMDB {emdb_id} 失败，返回None")
                        failed_emdb_ids.append(emdb_id)
                except concurrent.futures.TimeoutError:
                    logger.error(f"处理EMDB {emdb_id} 超时")
                    failed_emdb_ids.append(emdb_id)
                except Exception as e:
                    logger.error(f"处理EMDB {emdb_id} 时出错: {e}")
                    failed_emdb_ids.append(emdb_id)
                    import traceback
                    traceback.print_exc()
        
        if save_to_offline_db and (pdb_results or emdb_results):
            try:
                all_metadata = {}
                all_metadata.update(pdb_results)
                all_metadata.update(emdb_results)
                
                # 修改：调用增强版的保存方法，包含验证
                result = self.save_to_offline_database_enhanced(
                    all_metadata, 
                    structure_type="mixed",
                    force_update=force_update,
                    failed_ids=failed_pdb_ids + failed_emdb_ids,
                    cleanup_old_data=cleanup_old_data,
                    validate_before_save=True
                )
                
                if result.get("success_count", 0) > 0:
                    logger.info(f"✅ 结构元数据已保存到离线数据库: PDB={len(pdb_results)}, EMDB={len(emdb_results)}")
                    logger.info(f"⚠️ 未获取到数据的ID将保留旧数据: PDB={len(failed_pdb_ids)}, EMDB={len(failed_emdb_ids)}")
                else:
                    logger.warning(f"保存到离线数据库失败或没有数据保存")
                    
            except Exception as e:
                logger.error(f"保存到离线数据库时出错: {e}")
        
        # 关键修复：确保返回元组
        logger.info(f"获取完成: PDB={len(pdb_results)}个, EMDB={len(emdb_results)}个")
        return pdb_results, emdb_results

    def extract_related_pdb_ids(self, metadata: Any) -> List[str]:
        """从EMDB元数据中提取关联的PDB IDs（修复版）"""
        related_pdb_ids = []
        
        # 检查不同格式的元数据
        if hasattr(metadata, 'related_pdb_ids'):
            related_pdb_ids = metadata.related_pdb_ids
        elif isinstance(metadata, dict) and 'related_pdb_ids' in metadata:
            related_pdb_ids = metadata['related_pdb_ids']
        elif hasattr(metadata, 'related_ids'):
            related_ids = metadata.related_ids
            if isinstance(related_ids, list):
                related_pdb_ids = [
                    id for id in related_ids 
                    if isinstance(id, str) and (len(id) == 4 and id[0].isdigit() or 'PDB' in id.upper())
                ]
        
        # 如果还是空的，检查其他可能字段
        if not related_pdb_ids and isinstance(metadata, dict):
            for key, value in metadata.items():
                if 'pdb' in key.lower() and isinstance(value, list):
                    related_pdb_ids = value
                    break
        
        # 标准化PDB ID格式并修正常见错误
        normalized_pdb_ids = []
        for pdb_id in related_pdb_ids:
            if isinstance(pdb_id, str):
                # 清理和标准化
                pdb_clean = pdb_id.strip().upper()
                
                # 修正常见错误：7V5M -> 7X5M
                if pdb_clean == '7V5M':
                    pdb_clean = '7X5M'
                    logger.info(f"修正PDB ID: 7V5M -> 7X5M")
                
                # 标准化
                normalized = self.normalize_pdb_id(pdb_clean)
                if normalized and normalized not in normalized_pdb_ids:
                    normalized_pdb_ids.append(normalized)
        
        return normalized_pdb_ids

    def find_relationships(self, pdb_metadata: Dict[str, Any], 
                        emdb_metadata: Dict[str, Any]) -> List[StructureRelationship]:
        """查找PDB和EMDB之间的关联关系（修复版）"""
        relationships = []
        seen_relationship_pairs = set()  # 使用元组去重
        
        logger.info(f"开始查找 {len(pdb_metadata)} 个PDB和 {len(emdb_metadata)} 个EMDB之间的关联关系")
        
        # 首先，直接从PDBe API获取所有PDB的EMDB关联
        logger.info("🔍 从PDBe API获取所有PDB的EMDB关联...")
        pdb_to_emdb_map = {}
        
        for pdb_id in pdb_metadata.keys():
            try:
                url = f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/related_experimental_data/{pdb_id.lower()}"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if pdb_id.lower() in data:
                        emdb_entries = [entry for entry in data[pdb_id.lower()] if entry.get("database") == "EMDB"]
                        emdb_ids = []
                        for entry in emdb_entries:
                            emdb_id = entry.get("accession_code", "")
                            if emdb_id:
                                emdb_clean = emdb_id.upper()
                                if not emdb_clean.startswith("EMD-"):
                                    emdb_clean = f"EMD-{emdb_clean}"
                                emdb_ids.append(emdb_clean)
                        
                        if emdb_ids:
                            pdb_to_emdb_map[pdb_id] = emdb_ids
                            logger.info(f"  API: {pdb_id} -> {emdb_ids}")
            except Exception as e:
                logger.debug(f"  API查询 {pdb_id} 失败: {e}")
        
        # 阶段1：从PDB到EMDB的关联（使用API数据）
        logger.info("🔗 创建PDB->EMDB关联关系...")
        for pdb_id, emdb_list in pdb_to_emdb_map.items():
            for emdb_id in emdb_list:
                emdb_id_clean = self.normalize_emdb_id(emdb_id)
                
                # 检查这个EMDB是否在我们要处理的EMDB列表中
                if emdb_id_clean in emdb_metadata:
                    # 创建双向关系
                    # PDB -> EMDB
                    pdb_to_emdb_key = (pdb_id, emdb_id_clean, "pdb_to_emdb")
                    if pdb_to_emdb_key not in seen_relationship_pairs:
                        relationships.append(StructureRelationship(
                            source_id=pdb_id,
                            target_id=emdb_id_clean,
                            relationship_type="pdb_to_emdb",
                            evidence="PDBe API获取的关联"
                        ))
                        seen_relationship_pairs.add(pdb_to_emdb_key)
                        logger.debug(f"    添加关系: {pdb_id} -> {emdb_id_clean} (pdb_to_emdb)")
                    
                    # EMDB -> PDB (反向关系)
                    emdb_to_pdb_key = (emdb_id_clean, pdb_id, "emdb_to_pdb")
                    if emdb_to_pdb_key not in seen_relationship_pairs:
                        relationships.append(StructureRelationship(
                            source_id=emdb_id_clean,
                            target_id=pdb_id,
                            relationship_type="emdb_to_pdb",
                            evidence="PDBe API获取的关联的反向关系"
                        ))
                        seen_relationship_pairs.add(emdb_to_pdb_key)
                        logger.debug(f"    添加关系: {emdb_id_clean} -> {pdb_id} (emdb_to_pdb)")
        
        # 阶段2：从EMDB到PDB的关联（确保完整性）
        logger.info("🔗 创建EMDB->PDB关联关系...")
        for emdb_id, emdb_data in emdb_metadata.items():
            related_pdb_ids = self.extract_related_pdb_ids(emdb_data)
            
            if related_pdb_ids:
                logger.info(f"  EMDB {emdb_id} 关联 {len(related_pdb_ids)} 个PDB: {related_pdb_ids}")
            
            for pdb_id in related_pdb_ids:
                pdb_id_clean = self.normalize_pdb_id(pdb_id)
                
                # 检查这个PDB是否在我们要处理的PDB列表中
                if pdb_id_clean in pdb_metadata:
                    # EMDB -> PDB
                    emdb_to_pdb_key = (emdb_id, pdb_id_clean, "emdb_to_pdb")
                    if emdb_to_pdb_key not in seen_relationship_pairs:
                        relationships.append(StructureRelationship(
                            source_id=emdb_id,
                            target_id=pdb_id_clean,
                            relationship_type="emdb_to_pdb",
                            evidence="EMDB元数据中引用的PDB ID"
                        ))
                        seen_relationship_pairs.add(emdb_to_pdb_key)
                        logger.debug(f"    添加关系: {emdb_id} -> {pdb_id_clean} (emdb_to_pdb)")
                    
                    # PDB -> EMDB (反向关系)
                    pdb_to_emdb_key = (pdb_id_clean, emdb_id, "pdb_to_emdb")
                    if pdb_to_emdb_key not in seen_relationship_pairs:
                        relationships.append(StructureRelationship(
                            source_id=pdb_id_clean,
                            target_id=emdb_id,
                            relationship_type="pdb_to_emdb",
                            evidence="EMDB元数据中引用的PDB ID的反向关联"
                        ))
                        seen_relationship_pairs.add(pdb_to_emdb_key)
                        logger.debug(f"    添加关系: {pdb_id_clean} -> {emdb_id} (pdb_to_emdb)")
        
        logger.info(f"找到 {len(relationships)} 个PDB-EMDB关联关系")
        
        # 详细记录关系
        relationship_summary = {}
        for rel in relationships[:20]:  # 只显示前20个避免日志过长
            if hasattr(rel, 'source_id'):
                key = f"{rel.source_id}->{rel.target_id}"
                relationship_summary[key] = rel.relationship_type
        
        if relationship_summary:
            logger.info(f"关系示例: {list(relationship_summary.keys())[:10]}")
        
        # 详细记录关系
        relationship_summary = {}
        for rel in relationships[:20]:  # 只显示前20个避免日志过长
            key = f"{rel.source_id}->{rel.target_id}"
            relationship_summary[key] = rel.relationship_type
        
        if relationship_summary:
            logger.info(f"关系示例: {list(relationship_summary.keys())[:10]}")
        
        return relationships
    
    def group_related_structures(self, pdb_metadata: Dict[str, Any], 
                                emdb_metadata: Dict[str, Any],
                                relationships: List[StructureRelationship]) -> List[Dict[str, Any]]:
        graph = {}
        all_structures = {}
        
        for pdb_id, data in pdb_metadata.items():
            all_structures[pdb_id] = {"type": "pdb", "data": data}
            graph[pdb_id] = set()
        
        for emdb_id, data in emdb_metadata.items():
            all_structures[emdb_id] = {"type": "emdb", "data": data}
            graph[emdb_id] = set()
        
        for rel in relationships:
            if rel.source_id in graph and rel.target_id in graph:
                graph[rel.source_id].add(rel.target_id)
                graph[rel.target_id].add(rel.source_id)
        
        visited = set()
        groups = []
        
        for structure_id in graph:
            if structure_id not in visited:
                queue = [structure_id]
                group = []
                
                while queue:
                    current = queue.pop(0)
                    if current not in visited:
                        visited.add(current)
                        group.append(current)
                        for neighbor in graph[current]:
                            if neighbor not in visited:
                                queue.append(neighbor)
                
                if group:
                    groups.append(group)
        
        result = []
        for group in groups:
            if len(group) == 0:
                continue
                
            group_structures = []
            for struct_id in group:
                struct_info = all_structures.get(struct_id)
                if struct_info:
                    group_structures.append({
                        "id": struct_id,
                        "type": struct_info["type"],
                        "metadata": struct_info["data"] if isinstance(struct_info["data"], dict) else asdict(struct_info["data"])
                    })
            
            primary_structure = None
            if len(group_structures) == 1:
                primary_structure = group_structures[0]
            else:
                pdb_structures = [s for s in group_structures if s["type"] == "pdb"]
                if pdb_structures:
                    primary_structure = min(pdb_structures, 
                                          key=lambda x: x["metadata"].get("resolution", float('inf')) if isinstance(x["metadata"], dict) else getattr(x["metadata"], "resolution", float('inf')))
                else:
                    primary_structure = min(group_structures, 
                                          key=lambda x: x["metadata"].get("resolution", float('inf')) if isinstance(x["metadata"], dict) else getattr(x["metadata"], "resolution", float('inf')))
            
            result.append({
                "group_id": f"group_{hash(tuple(sorted(group)))}",
                "structure_ids": group,
                "structures": group_structures,
                "primary_structure": primary_structure,
                "is_combined": len(group) > 1,
                "relationship_count": sum(1 for rel in relationships if rel.source_id in group or rel.target_id in group),
                "structure_count": len(group)
            })
        
        return result
    
    def get_biological_info_summary(self, pdb_metadata: Dict[str, Any] = None,
                                   emdb_metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        summary = {
            "organisms": set(),
            "expression_systems": set(),
            "genes": set(),
            "tissues": set(),
            "uniprot_ids": set()
        }
        
        if pdb_metadata:
            for pdb_id, data in pdb_metadata.items():
                organism = None
                if isinstance(data, dict):
                    organism = data.get('organism')
                elif hasattr(data, 'organism'):
                    organism = data.organism
                
                if organism and organism != "Unknown":
                    summary["organisms"].add(organism)
                
                expression_system = None
                if isinstance(data, dict):
                    expression_system = data.get('expression_system')
                elif hasattr(data, 'expression_system'):
                    expression_system = data.expression_system
                
                if expression_system:
                    summary["expression_systems"].add(expression_system)
                
                gene = None
                if isinstance(data, dict):
                    gene = data.get('gene')
                elif hasattr(data, 'gene'):
                    gene = data.gene
                
                if gene:
                    summary["genes"].add(gene)
                
                tissue = None
                if isinstance(data, dict):
                    tissue = data.get('tissue')
                elif hasattr(data, 'tissue'):
                    tissue = data.tissue
                
                if tissue:
                    summary["tissues"].add(tissue)
                
                uniprot_ids = []
                if isinstance(data, dict):
                    uniprot_ids = data.get('uniprot_ids', [])
                elif hasattr(data, 'uniprot_ids'):
                    uniprot_ids = data.uniprot_ids
                
                if uniprot_ids:
                    summary["uniprot_ids"].update(uniprot_ids)
        
        if emdb_metadata:
            for emdb_id, data in emdb_metadata.items():
                organism = None
                if isinstance(data, dict):
                    organism = data.get('organism')
                elif hasattr(data, 'organism'):
                    organism = data.organism
                
                if organism and organism != "Unknown":
                    summary["organisms"].add(organism)
                
                expression_system = None
                if isinstance(data, dict):
                    expression_system = data.get('expression_system')
                elif hasattr(data, 'expression_system'):
                    expression_system = data.expression_system
                
                if expression_system:
                    summary["expression_systems"].add(expression_system)
                
                tissue_source = None
                if isinstance(data, dict):
                    tissue_source = data.get('tissue_source')
                elif hasattr(data, 'tissue_source'):
                    tissue_source = data.tissue_source
                
                if tissue_source:
                    summary["tissues"].add(tissue_source)
        
        summary["organisms"] = list(summary["organisms"])
        summary["expression_systems"] = list(summary["expression_systems"])
        summary["genes"] = list(summary["genes"])
        summary["tissues"] = list(summary["tissues"])
        summary["uniprot_ids"] = list(summary["uniprot_ids"])
        
        return summary

    def process_structure_ids(self, structure_ids: Dict[str, Any],
                            force_update: bool = True,
                            fetch_uniprot: bool = True,
                            cleanup_old_data: bool = True) -> Dict[str, Any]:
        """
        处理结构ID（使用文献关联过滤）- 修复变量引用错误
        """
        try:
            logger.info("=" * 80)
            logger.info(f"开始处理结构ID（获取UniProt={fetch_uniprot}）")
            logger.info("=" * 80)

            # 提取ID和来源信息 - 确保变量被正确定义
            pdb_ids = structure_ids.get("pdb_ids", []) if structure_ids else []
            emdb_ids = structure_ids.get("emdb_ids", []) if structure_ids else []
            source_info = structure_ids.get("source_info", {}) if structure_ids else {}
            
            # 获取DOI来源的PDB ID
            doi_pdb_ids = source_info.get("doi_pdb_ids", []) if source_info else []
            
            logger.info("🔍 输入结构ID详情:")
            logger.info(f"  - PDB IDs: {pdb_ids}")
            logger.info(f"  - EMDB IDs: {emdb_ids}")
            logger.info(f"  - DOI PDB IDs: {doi_pdb_ids}")
            
            # 验证输入
            if not pdb_ids and not emdb_ids:
                logger.warning("⚠️ 未接收到任何结构ID")
                return {
                    "structure_ids": structure_ids,
                    "pdb_metadata": {},
                    "emdb_metadata": {},
                    "relationships": [],
                    "groups": [],
                    "filtering_info": {
                        "filter_applied": False,
                        "reason": "no_structure_ids_received"
                    },
                    "error": "no_structure_ids_received"
                }

            # 特别调试：检查是否有PDB关联多个EMDB
            if pdb_ids:
                logger.info("🔍 检查每个PDB可能关联的EMDB:")
                for pdb_id in pdb_ids:
                    # 直接查询PDBe API获取关联
                    try:
                        url = f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/related_experimental_data/{pdb_id.lower()}"
                        response = requests.get(url, timeout=5)
                        if response.status_code == 200:
                            data = response.json()
                            if pdb_id.lower() in data:
                                emdb_entries = [entry for entry in data[pdb_id.lower()] if entry.get("database") == "EMDB"]
                                if emdb_entries:
                                    emdb_ids_found = [entry.get("accession_code", "") for entry in emdb_entries]
                                    logger.info(f"    {pdb_id}: 通过API找到 {len(emdb_ids_found)} 个EMDB关联 -> {emdb_ids_found}")
                                else:
                                    logger.debug(f"    {pdb_id}: API返回无EMDB关联")
                    except Exception as e:
                        logger.debug(f"    {pdb_id}: API查询失败 {e}")

            # 步骤1: 获取所有元数据
            logger.info(f"🚀 步骤1: 获取所有结构元数据...")
            logger.info(f"  - 获取 {len(pdb_ids)} 个PDB和 {len(emdb_ids)} 个EMDB的元数据")
            
            metadata_result = self.fetch_all_metadata(
                pdb_ids=pdb_ids,
                emdb_ids=emdb_ids,
                use_cache=not force_update,
                save_to_offline_db=True,  # 先保存所有数据，后面再过滤
                force_update=force_update,
                cleanup_old_data=cleanup_old_data
            )
            
            if metadata_result is None:
                logger.error("❌ fetch_all_metadata 返回 None")
                return {
                    "error": "fetch_all_metadata_returned_none",
                    "structure_ids": structure_ids,
                    "pdb_metadata": {},
                    "emdb_metadata": {},
                    "filtering_info": {
                        "filter_applied": False,
                        "reason": "metadata_fetch_failed"
                    }
                }
            
            # 解包结果
            pdb_metadata_all, emdb_metadata_all = metadata_result
            
            logger.info(f"✅ 元数据获取完成:")
            logger.info(f"  - PDB元数据: {len(pdb_metadata_all)}/{len(pdb_ids)} 个成功获取")
            logger.info(f"  - EMDB元数据: {len(emdb_metadata_all)}/{len(emdb_ids)} 个成功获取")
            
            # 步骤2: 应用文献关联过滤
            logger.info("🎯 步骤2: 应用文献关联过滤规则...")
            logger.info("  规则1: DOI获取的PDB ID全部保留（最高优先级）")
            logger.info("  规则2: 其他PDB ID只保留与这篇文献中EMDB有关联的")
            logger.info("  规则3: 所有EMDB ID全部保留")
            
            final_pdb_ids, filtering_info = self.apply_literature_based_filtering(
                pdb_ids=pdb_ids,
                pdb_metadata=pdb_metadata_all,
                emdb_ids=emdb_ids,  # 传递文献中的EMDB ID列表
                source_info=source_info,
                emdb_metadata=emdb_metadata_all  # 传递EMDB元数据以支持反向查找
            )
            
            # 创建过滤后的元数据字典
            final_pdb_metadata = {}
            for pdb_id in final_pdb_ids:
                if pdb_id in pdb_metadata_all:
                    final_pdb_metadata[pdb_id] = pdb_metadata_all[pdb_id]
                else:
                    logger.warning(f"过滤后的PDB {pdb_id} 没有元数据，跳过")
            
            # 所有文献中的EMDB ID都保留
            final_emdb_metadata = {}
            for emdb_id in emdb_ids:
                normalized_id = self.normalize_emdb_id(emdb_id)
                if normalized_id in emdb_metadata_all:
                    final_emdb_metadata[normalized_id] = emdb_metadata_all[normalized_id]
                else:
                    logger.warning(f"EMDB {emdb_id} 没有元数据，跳过")
            
            logger.info(f"📊 过滤后元数据:")
            logger.info(f"  - PDB: {len(final_pdb_metadata)}/{len(pdb_metadata_all)} 个")
            logger.info(f"  - EMDB: {len(final_emdb_metadata)}/{len(emdb_metadata_all)} 个")
            
            if len(final_pdb_metadata) == 0 and len(final_emdb_metadata) == 0:
                logger.warning("⚠️ 过滤后没有任何元数据")
                return {
                    "structure_ids": structure_ids,
                    "pdb_metadata": {},
                    "emdb_metadata": {},
                    "relationships": [],
                    "groups": [],
                    "filtering_info": filtering_info,
                    "error": "no_metadata_after_filtering"
                }
            
            # 步骤3: 分析PDB-EMDB关联关系
            logger.info("🔗 步骤3: 分析PDB-EMDB关联关系...")
            filtered_relationships = self.find_relationships(final_pdb_metadata, final_emdb_metadata)
            
            # 临时调试：打印详细关系信息
            logger.info("📋 详细关系列表:")
            for i, rel in enumerate(filtered_relationships, 1):
                if hasattr(rel, '__dict__'):
                    logger.info(f"  {i}. {rel.source_id} -> {rel.target_id} ({rel.relationship_type})")
                elif isinstance(rel, dict):
                    logger.info(f"  {i}. {rel.get('source_id')} -> {rel.get('target_id')} ({rel.get('relationship_type')})")
                else:
                    logger.info(f"  {i}. {rel}")
            
            # 去重
            unique_relationships = []
            seen_relationship_tuples = set()
            
            for rel in filtered_relationships:
                # 使用对象属性或字典访问
                if hasattr(rel, 'source_id'):
                    rel_tuple = (rel.source_id, rel.target_id, rel.relationship_type)
                elif isinstance(rel, dict):
                    rel_tuple = (rel.get('source_id'), rel.get('target_id'), rel.get('relationship_type'))
                else:
                    continue
                    
                if rel_tuple not in seen_relationship_tuples:
                    unique_relationships.append(rel)
                    seen_relationship_tuples.add(rel_tuple)
            
            logger.info(f"📊 关联关系分析:")
            logger.info(f"  - 原始关系: {len(filtered_relationships)} 个")
            logger.info(f"  - 去重后关系: {len(unique_relationships)} 个")
            
            # 步骤4: 对相关结构进行分组
            logger.info("📦 步骤4: 对相关结构进行分组...")
            filtered_groups = self.group_related_structures(
                final_pdb_metadata, 
                final_emdb_metadata, 
                filtered_relationships
            )
            
            logger.info(f"📊 结构分组:")
            logger.info(f"  - 创建了 {len(filtered_groups)} 个结构组")
            
            # 步骤5: 获取生物信息摘要
            logger.info("🧬 步骤5: 获取生物信息摘要...")
            biological_summary = self.get_biological_info_summary(
                final_pdb_metadata,
                final_emdb_metadata
            )
            
            # 步骤6: 保存到离线数据库（只保存过滤后的数据）
            logger.info("💾 步骤6: 保存过滤后的元数据到离线数据库...")
            
            # 合并所有过滤后的元数据
            all_filtered_metadata = {}
            all_filtered_metadata.update(final_pdb_metadata)
            all_filtered_metadata.update(final_emdb_metadata)
            
            save_result = self.save_to_offline_database_enhanced(
                all_filtered_metadata,
                structure_type="mixed",
                force_update=force_update,
                validate_before_save=True,
                cleanup_old_data=force_update
            )
            
            # 步骤7: 保存UniProt映射（如果启用）
            uniprot_saved_count = 0
            if fetch_uniprot and final_pdb_metadata:
                try:
                    from core.structure_database import get_enhanced_structure_manager
                    structure_db = get_enhanced_structure_manager()
                    
                    if structure_db:
                        logger.info("🔄 步骤7: 保存UniProt映射到数据库...")
                        
                        for pdb_id, pdb_meta in final_pdb_metadata.items():
                            try:
                                # 获取UniProt IDs
                                uniprot_ids = []
                                if hasattr(pdb_meta, 'uniprot_ids'):
                                    uniprot_ids = pdb_meta.uniprot_ids
                                elif isinstance(pdb_meta, dict) and 'uniprot_ids' in pdb_meta:
                                    uniprot_ids = pdb_meta['uniprot_ids']
                                
                                if uniprot_ids:
                                    # 获取蛋白质名称和基因名
                                    protein_name = None
                                    gene_name = None
                                    
                                    if hasattr(pdb_meta, 'protein_name'):
                                        protein_name = pdb_meta.protein_name
                                    elif isinstance(pdb_meta, dict) and 'protein_name' in pdb_meta:
                                        protein_name = pdb_meta['protein_name']
                                    
                                    if hasattr(pdb_meta, 'gene'):
                                        gene_name = pdb_meta.gene
                                    elif isinstance(pdb_meta, dict) and 'gene' in pdb_meta:
                                        gene_name = pdb_meta['gene']
                                    
                                    # 保存每个UniProt映射
                                    for uniprot_id in uniprot_ids:
                                        try:
                                            saved = structure_db.database.add_uniprot_structure_mapping(
                                                uniprot_id=uniprot_id,
                                                structure_id=pdb_id,
                                                protein_name=protein_name,
                                                gene_name=gene_name,
                                                confidence=1.0,
                                                source=f"pdb_{pdb_id}_filtered"
                                            )
                                            
                                            if saved:
                                                uniprot_saved_count += 1
                                        except Exception as e:
                                            logger.error(f"保存UniProt映射失败 {uniprot_id} -> {pdb_id}: {e}")
                            except Exception as e:
                                logger.error(f"处理 {pdb_id} 的UniProt映射失败: {e}")
                        
                        logger.info(f"✅ UniProt映射保存完成: 成功 {uniprot_saved_count} 个映射")
                    else:
                        logger.warning("无法获取数据库实例，跳过UniProt映射保存")
                except Exception as e:
                    logger.warning(f"保存UniProt映射失败: {e}")
            
            # 步骤8: 保存关联关系
            try:
                if unique_relationships:
                    self.save_relationships_to_database(unique_relationships)
                    logger.info(f"✅ 关联关系已保存到数据库: {len(unique_relationships)} 个")
                else:
                    logger.info("没有关联关系需要保存")
            except Exception as e:
                logger.warning(f"保存关系到数据库失败: {e}")
            
            # 步骤9: 保存结构分组
            try:
                if filtered_groups:
                    self.save_structure_groups_to_database(filtered_groups)
                    logger.info(f"✅ 结构分组已保存到数据库: {len(filtered_groups)} 个")
                else:
                    logger.info("没有结构分组需要保存")
            except Exception as e:
                logger.warning(f"保存分组信息到数据库失败: {e}")
            
            # 构建最终结果
            result = {
                "structure_ids": structure_ids,
                "pdb_metadata": {
                    pdb_id: self._metadata_to_dict(metadata)
                    for pdb_id, metadata in final_pdb_metadata.items()
                },
                "emdb_metadata": {
                    emdb_id: self._metadata_to_dict(metadata)
                    for emdb_id, metadata in final_emdb_metadata.items()
                },
                "relationships": [
                    self._relationship_to_dict(r) for r in unique_relationships
                ],
                "groups": [
                    self._group_to_dict(group) for group in filtered_groups
                ],
                "biological_summary": biological_summary,
                "filtering_info": filtering_info,
                "metadata_summary": {
                    "pdb_count": len(final_pdb_metadata),
                    "emdb_count": len(final_emdb_metadata),
                    "relationship_count": len(unique_relationships),
                    "group_count": len(filtered_groups),
                    "combined_structures": sum(1 for g in filtered_groups if g.get('is_combined', False)),
                    "filtering_stats": {
                        "original_pdb_count": len(pdb_ids),  # 使用原始的pdb_ids
                        "final_pdb_count": len(final_pdb_metadata),
                        "filtered_out_count": len(pdb_ids) - len(final_pdb_metadata),
                        "doi_pdb_count": len(doi_pdb_ids),
                        "literature_emdb_count": len(emdb_ids),
                        "pdb_with_literature_emdb_count": filtering_info.get("pdb_with_literature_emdb_count", 0)
                    },
                    "uniprot_info": {
                        "fetched": fetch_uniprot,
                        "client_available": self.uniprot_client is not None,
                        "total_uniprot_ids": len(biological_summary.get("uniprot_ids", [])),
                        "mapping_saved": uniprot_saved_count,
                        "note": "UniProt信息已同步获取并保存到数据库"
                    },
                    "database_info": {
                        "structures_saved": save_result.get("success_count", 0),
                        "uniprot_mappings_saved": uniprot_saved_count,
                        "relationships_saved": len(unique_relationships),
                        "groups_saved": len(filtered_groups),
                        "entities_saved": save_result.get("entities_saved", 0)
                    }
                },
            }
            
            # 验证关联关系
            if unique_relationships:
                logger.info("🔍 验证PDB-EMDB关联关系:")
                
                # 统计每个EMDB关联的PDB数量
                emdb_to_pdb_count = {}
                for rel in unique_relationships:
                    # 使用对象属性或字典访问
                    if hasattr(rel, 'relationship_type'):
                        rel_type = rel.relationship_type
                        source_id = rel.source_id
                        target_id = rel.target_id
                    elif isinstance(rel, dict):
                        rel_type = rel.get('relationship_type')
                        source_id = rel.get('source_id')
                        target_id = rel.get('target_id')
                    else:
                        continue
                        
                    if rel_type == 'emdb_to_pdb':
                        emdb_id = source_id
                        pdb_id = target_id
                        if emdb_id in emdb_to_pdb_count:
                            emdb_to_pdb_count[emdb_id].append(pdb_id)
                        else:
                            emdb_to_pdb_count[emdb_id] = [pdb_id]
                
                # 记录统计信息
                for emdb_id, pdb_list in emdb_to_pdb_count.items():
                    if len(pdb_list) > 1:
                        logger.info(f"  ✅ EMDB {emdb_id} 关联了 {len(pdb_list)} 个PDB: {pdb_list}")
                    else:
                        logger.info(f"  ✓ EMDB {emdb_id} 关联了 {len(pdb_list)} 个PDB")
                
                # 将统计信息添加到结果中
                result["relationship_stats"] = {
                    "emdb_with_multiple_pdbs": sum(1 for pdb_list in emdb_to_pdb_count.values() if len(pdb_list) > 1),
                    "total_emdb_with_relationships": len(emdb_to_pdb_count),
                    "average_pdbs_per_emdb": len(unique_relationships) / len(emdb_to_pdb_count) if emdb_to_pdb_count else 0,
                    "total_relationships": len(unique_relationships)
                }
            
            # 添加过滤详情到日志
            logger.info("=" * 80)
            logger.info("✅ 结构ID处理完成（包含文献关联过滤）")
            
            if filtering_info.get("filter_applied"):
                logger.info(f"📋 过滤详情:")
                logger.info(f"  - 规则: {filtering_info.get('filter_rules', ['N/A'])}")
                logger.info(f"  - DOI PDB: {len(doi_pdb_ids)}个全部保留")
                logger.info(f"  - 文献EMDB: {len(emdb_ids)}个") 
                logger.info(f"  - 原始PDB: {len(pdb_ids)}个")
                logger.info(f"  - 最终PDB: {len(final_pdb_metadata)}个")
                logger.info(f"  - 过滤PDB: {len(pdb_ids) - len(final_pdb_metadata)}个")
                
                # 显示过滤的PDB ID（如果有）
                filtered_pdb_list = filtering_info.get("filtered_pdb_ids", [])
                if filtered_pdb_list:
                    logger.info(f"  - 过滤的PDB IDs: {filtered_pdb_list[:10]}{'...' if len(filtered_pdb_list) > 10 else ''}")
            
            logger.info(
                f"📊 结果统计: "
                f"PDB={len(final_pdb_metadata)}, "
                f"EMDB={len(final_emdb_metadata)}, "
                f"关联关系={len(unique_relationships)}, "
                f"结构组={len(filtered_groups)}, "
                f"UniProt ID数量={len(biological_summary.get('uniprot_ids', []))}"
            )
            
            # 显示DOI PDB的保留情况
            if doi_pdb_ids:
                retained_doi_pdbs = [p for p in doi_pdb_ids if p in final_pdb_metadata]
                logger.info(f"📚 DOI PDB保留情况: {len(retained_doi_pdbs)}/{len(doi_pdb_ids)} 个")
                if len(retained_doi_pdbs) < len(doi_pdb_ids):
                    missing = set(doi_pdb_ids) - set(retained_doi_pdbs)
                    logger.warning(f"⚠️ 部分DOI PDB没有保留: {missing}")
            
            logger.info("=" * 80)

            return result

        except Exception as e:
            logger.error(f"❌ 处理结构ID失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "error": str(e),
                "structure_ids": structure_ids,
                "pdb_metadata": {},
                "emdb_metadata": {},
                "filtering_info": {
                    "filter_applied": False,
                    "reason": f"processing_error: {str(e)[:100]}"
                }
            }
      
    def _metadata_to_dict(self, metadata):
        """将元数据对象转换为字典（简化分组信息）"""
        if hasattr(metadata, '__dict__'):
            result = metadata.__dict__
        else:
            result = metadata
        
        # 简化实体信息（如果太大）
        if 'entities' in result and result['entities'] and len(result['entities']) > 10:
            # 只保留前10个实体，其他的用计数表示
            result['entities'] = result['entities'][:10]
            result['total_entities_count'] = len(metadata.entities) if hasattr(metadata, 'entities') else len(result['entities'])
        
        return result

    def _group_to_dict(self, group):
        """将分组对象转换为字典（避免重复）"""
        if not isinstance(group, dict):
            return group
        
        result = group.copy()
        
        # 简化分组信息
        if 'structures' in result:
            # 只保留结构的基本信息，而不是完整数据
            simplified_structures = []
            for struct_info in result['structures'][:5]:  # 只保留前5个
                if isinstance(struct_info, dict):
                    simplified = {
                        'id': struct_info.get('id'),
                        'type': struct_info.get('type'),
                        'title': struct_info.get('title', '')[:100] if struct_info.get('title') else None,
                        'resolution': struct_info.get('resolution')
                    }
                    simplified_structures.append(simplified)
            result['structures'] = simplified_structures
        
        # 简化primary_structure
        if 'primary_structure' in result and isinstance(result['primary_structure'], dict):
            primary = result['primary_structure']
            if 'metadata' in primary and isinstance(primary['metadata'], dict):
                # 只保留必要的metadata字段
                primary['metadata'] = {
                    'id': primary['metadata'].get('id'),
                    'title': primary['metadata'].get('title', '')[:100],
                    'resolution': primary['metadata'].get('resolution'),
                    'method': primary['metadata'].get('method')
                }
        
        return result

    def _relationship_to_dict(self, relationship):
        """将关系对象转换为字典"""
        if hasattr(relationship, '__dict__'):
            return relationship.__dict__
        else:
            return relationship
    
    def process_literature_structure_ids(self, literature_data: Dict[str, Any],
                                        force_update: bool = True,
                                        fetch_uniprot: bool = True) -> Dict[str, Any]:
        logger.warning("⚠️ 使用向后兼容的process_literature_structure_ids方法，建议直接使用process_structure_ids")
        
        structure_ids = {}
        
        if "parsed_data" in literature_data and "structure_ids" in literature_data["parsed_data"]:
            structure_ids = literature_data["parsed_data"]["structure_ids"]
            logger.info("从parsed_data.structure_ids中提取结构ID")
        
        elif "cryo_targets" in literature_data:
            cryo_targets = literature_data["cryo_targets"]
            if isinstance(cryo_targets, dict):
                structure_ids = {
                    "pdb_ids": cryo_targets.get("pdb_ids", []),
                    "emdb_ids": cryo_targets.get("emdb_ids", []),
                    "extraction_method": "cryo_targets_backward_compat"
                }
                logger.info("从cryo_targets中提取结构ID（旧格式）")
        
        elif "structure_ids" in literature_data:
            structure_ids = literature_data["structure_ids"]
            logger.info("从顶级structure_ids字段提取结构ID")
        
        if not structure_ids:
            logger.error("literature_data中没有找到structure_ids信息")
            return {
                "error": "no_structure_ids_found",
                "input_structure_ids": {},
                "pdb_metadata": {},
                "emdb_metadata": {}
            }
        
        return self.process_structure_ids(structure_ids, force_update, fetch_uniprot)
    
    def debug_fetch_metadata(self, pdb_ids: List[str] = None, emdb_ids: List[str] = None,
                            fetch_uniprot: bool = True) -> None:
        if not pdb_ids and not emdb_ids:
            logger.warning("没有提供测试ID")
            return
        
        logger.info(f"调试 - 测试获取元数据:")
        logger.info(f"  PDB IDs: {pdb_ids}")
        logger.info(f"  EMDB IDs: {emdb_ids}")
        logger.info(f"  获取UniProt: {fetch_uniprot}")
        
        if emdb_ids:
            test_id = emdb_ids[0]
            logger.info(f"测试获取EMDB {test_id}...")
            result = self.fetch_emdb_metadata(test_id, use_cache=False, force_update=True)
            if result:
                logger.info(f"成功获取EMDB {result.emdb_id}: {result.title}")
                logger.info(f"  相关PDB IDs: {result.related_pdb_ids}")
            else:
                logger.error(f"无法获取EMDB {test_id}")
        
        if pdb_ids:
            test_id = pdb_ids[0]
            logger.info(f"测试获取PDB {test_id}...")
            result = self.fetch_pdb_metadata(test_id, use_cache=False, force_update=True, fetch_uniprot=fetch_uniprot)
            if result:
                logger.info(f"成功获取PDB {test_id}: {result.title}")
                logger.info(f"  相关EMDB IDs: {result.related_emdb_ids}")
                logger.info(f"  相关UniProt IDs: {result.uniprot_ids}")
                
                if fetch_uniprot and result.uniprot_ids:
                    try:
                        from core.structure_database import get_enhanced_structure_manager
                        structure_db = get_enhanced_structure_manager()
                        if structure_db:
                            uniprot_mappings = structure_db.database.find_uniprot_ids_for_structure(test_id)
                            logger.info(f"  数据库中的UniProt映射: {uniprot_mappings}")
                    except Exception as e:
                        logger.warning(f"查询数据库UniProt映射失败: {e}")
            else:
                logger.error(f"无法获取PDB {test_id}")

    def check_pdb_emdb_associations(self, pdb_metadata: Dict[str, Any]) -> None:
        """检查PDB元数据中的EMDB关联信息（增强版）"""
        logger.info("🔍 检查PDB元数据中的EMDB关联信息:")
        
        for pdb_id, metadata in pdb_metadata.items():
            # 使用增强的提取方法
            related_emdb_ids = self.extract_related_emdb_ids(metadata)
            
            if related_emdb_ids:
                logger.info(f"  ✅ {pdb_id}: 关联 {len(related_emdb_ids)} 个EMDB -> {related_emdb_ids}")
            else:
                logger.info(f"  ❌ {pdb_id}: 无EMDB关联")
                
            # 调试信息：显示元数据结构
            logger.debug(f"  {pdb_id} 元数据类型: {type(metadata)}")
            if hasattr(metadata, '__dict__'):
                logger.debug(f"  {pdb_id} 属性列表: {list(metadata.__dict__.keys())}")
                # 特别检查是否有EMDB相关字段
                emdb_fields = [k for k in metadata.__dict__.keys() if 'emdb' in k.lower()]
                if emdb_fields:
                    logger.debug(f"  {pdb_id} EMDB相关字段: {emdb_fields}")

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    print("=" * 80)
    print("测试增强版StructureMetadataFetcher（集成UniProt API）")
    print("=" * 80)
    
    fetcher = StructureMetadataFetcher()
    
    test_pdbs = ["7EWL", "6VSB", "5T1A"]
    
    for pdb_id in test_pdbs:
        print(f"\n测试获取PDB {pdb_id}（包含UniProt信息）:")
        metadata = fetcher.fetch_pdb_metadata(pdb_id, fetch_uniprot=True)
        if metadata:
            print(f"✅ 成功获取: {metadata.title}")
            print(f"   分辨率: {metadata.resolution} Å")
            print(f"   方法: {metadata.method}")
            print(f"   生物体: {metadata.organism}")
            print(f"   相关UniProt IDs ({len(metadata.uniprot_ids)}): {metadata.uniprot_ids[:5]}")
            if len(metadata.uniprot_ids) > 5:
                print(f"   ... 还有 {len(metadata.uniprot_ids)-5} 个UniProt ID")
        else:
            print(f"❌ 获取失败")
    
    print("\n\n测试批量处理结构ID:")
    test_structure_ids = {
        "pdb_ids": ["7EWL", "6VSB"],
        "emdb_ids": ["EMD-12345", "EMD-23456"]
    }
    
    result = fetcher.process_structure_ids(
        structure_ids=test_structure_ids,
        force_update=False,
        fetch_uniprot=True
    )
    
    if "error" not in result:
        print(f"✅ 批量处理成功")
        print(f"   获取到 {len(result['pdb_metadata'])} 个PDB")
        print(f"   获取到 {len(result['emdb_metadata'])} 个EMDB")
        print(f"   找到 {len(result['relationships'])} 个关联关系")
        
        uniprot_info = result.get('metadata_summary', {}).get('uniprot_info', {})
        if uniprot_info.get('fetched'):
            print(f"   UniProt信息: 已获取，共 {uniprot_info.get('total_uniprot_ids', 0)} 个UniProt ID")
    else:
        print(f"❌ 批量处理失败: {result.get('error')}")
    
    print("\n" + "=" * 80)
    print("✅ 增强版StructureMetadataFetcher测试完成")
    print("=" * 80)