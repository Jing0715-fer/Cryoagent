import json
import time
import logging
import requests
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# 设置日志
logger = logging.getLogger(__name__)

class RCSBPDBSearch:
    """RCSB PDB Search API 封装类"""
    
    def __init__(self, base_url: str = "https://search.rcsb.org"):
        """初始化RCSB搜索API客户端"""
        self.base_url = base_url.rstrip('/')
        self.search_url = f"{self.base_url}/rcsbsearch/v2/query"

    def _save_uniprot_entity_mappings_from_structure_result(self, structure_result: Dict) -> Dict[str, Any]:
        """
        从结构管理器结果中提取并保存UniProt-实体映射（改进版 - 只保存最优匹配）
        """
        try:
            from structure_database import get_enhanced_structure_manager
            
            # 获取结构数据库管理器
            structure_db = get_enhanced_structure_manager()
            if not structure_db:
                logger.warning("结构数据库管理器不可用，跳过UniProt-实体映射保存")
                return {"success": False, "error": "Database not available"}
            
            pdb_metadata = structure_result.get("pdb_metadata", {})
            
            saved_mappings = []
            skipped_mappings = []
            total_entities_processed = 0
            
            logger.info(f"开始从结构结果中提取UniProt-实体映射，包含 {len(pdb_metadata)} 个PDB结构")
            
            # 准备批量保存的数据
            mappings_to_save = []
            
            for pdb_id, metadata in pdb_metadata.items():
                if not metadata:
                    continue
                
                # 获取UniProt IDs
                uniprot_ids = []
                if hasattr(metadata, 'uniprot_ids'):
                    uniprot_ids = metadata.uniprot_ids
                elif isinstance(metadata, dict):
                    uniprot_ids = metadata.get('uniprot_ids', [])
                
                if not uniprot_ids:
                    continue
                
                # 获取实体信息
                entities = []
                if hasattr(metadata, 'entities'):
                    entities = metadata.entities
                elif isinstance(metadata, dict):
                    entities = metadata.get('entities', [])
                
                if not entities:
                    logger.debug(f"PDB {pdb_id} 没有实体信息，跳过UniProt-实体映射")
                    continue
                
                logger.debug(f"处理PDB {pdb_id}: {len(uniprot_ids)}个UniProt ID, {len(entities)}个实体")
                total_entities_processed += len(entities)
                
                # 修改：不再简单地为每个UniProt ID创建映射
                # 而是通过匹配算法找出每个实体的最佳UniProt ID
                # 这部分逻辑已经在structure_manager.py的_save_uniprot_entity_mappings中实现
                # 这里只需要确保调用该方法
                
                # 为每个UniProt ID调用智能匹配算法
                for uniprot_id in uniprot_ids:
                    try:
                        # 获取UniProt条目信息
                        uniprot_entries = []
                        if hasattr(structure_db.database, 'get_uniprot_entries_for_pdb'):
                            uniprot_entries = structure_db.database.get_uniprot_entries_for_pdb(pdb_id, uniprot_id)
                        
                        if uniprot_entries:
                            uniprot_entry = uniprot_entries[0]
                            # 调用智能匹配算法
                            saved_count = self._save_uniprot_entity_mappings(
                                structure_db, uniprot_id, pdb_id, entities, uniprot_entry
                            )
                            
                            if saved_count > 0:
                                saved_mappings.append({
                                    'uniprot_id': uniprot_id,
                                    'pdb_id': pdb_id,
                                    'saved_count': saved_count
                                })
                    
                    except Exception as e:
                        logger.warning(f"准备映射数据失败 {uniprot_id} -> {pdb_id}: {e}")
                        skipped_mappings.append({
                            'uniprot_id': uniprot_id,
                            'pdb_id': pdb_id,
                            'reason': str(e)
                        })
            
            # 统计信息
            stats = {
                'success': len(saved_mappings) > 0,
                'saved_mappings_count': len(saved_mappings),
                'skipped_mappings_count': len(skipped_mappings),
                'total_entities_processed': total_entities_processed,
                'total_pdb_processed': len(pdb_metadata),
                'pdb_with_uniprot': sum(1 for metadata in pdb_metadata.values() 
                                    if metadata and (
                                        (hasattr(metadata, 'uniprot_ids') and metadata.uniprot_ids) or
                                        (isinstance(metadata, dict) and metadata.get('uniprot_ids'))
                                    ))
            }
            
            logger.info(f"UniProt-实体映射保存完成: {len(saved_mappings)}个映射成功保存，{len(skipped_mappings)}个跳过")
            
            return stats
            
        except ImportError as e:
            logger.warning(f"导入结构数据库模块失败: {e}")
            return {"success": False, "error": f"Import error: {e}"}
        except Exception as e:
            logger.error(f"保存UniProt-实体映射失败: {e}")
            return {"success": False, "error": str(e)}
    
    def search_by_doi(self, doi: str, return_type: str = "entry") -> List[str]:
        """通过DOI精确搜索PDB ID"""
        # 清理DOI格式
        doi_clean = self._clean_doi(doi)

        # 构建查询
        query = {
            "query": {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "rcsb_primary_citation.pdbx_database_id_DOI",
                    "operator": "exact_match",
                    "value": doi_clean
                }
            },
            "return_type": return_type
        }

        try:
            response = requests.post(
                self.search_url,
                json=query,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            response.raise_for_status()

            results = response.json()
            pdb_ids = []

            if "result_set" in results:
                for item in results["result_set"]:
                    if "identifier" in item:
                        pdb_ids.append(item["identifier"].upper())

            return list(set(pdb_ids))  # 去重

        except requests.exceptions.RequestException as e:
            logger.warning(f"RCSB API请求失败: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.warning(f"RCSB JSON解析失败: {e}")
            return []

    def search_by_doi_with_emdb(self, doi: str) -> Tuple[List[str], List[str]]:
        """
        通过DOI搜索，同时返回PDB ID和关联的EMDB ID
        返回: (pdb_ids, emdb_ids)
        """
        doi_clean = self._clean_doi(doi)

        # 构建查询
        query = {
            "query": {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "rcsb_primary_citation.pdbx_database_id_DOI",
                    "operator": "exact_match",
                    "value": doi_clean
                }
            },
            "return_type": "entry"
        }

        try:
            response = requests.post(
                self.search_url,
                json=query,
                headers={"Content-Type": "application/json"},
                timeout=30
            )

            if response.status_code != 200:
                logger.warning(f"RCSB API返回状态码: {response.status_code}")
                # 回退到原方法
                pdb_ids = self.search_by_doi(doi)
                return pdb_ids, []

            results = response.json()
            pdb_ids = []
            emdb_ids = set()

            if "result_set" in results:
                for item in results["result_set"]:
                    if "identifier" in item:
                        pdb_id = item["identifier"].upper()
                        pdb_ids.append(pdb_id)

                        # 从每个PDB获取EMDB ID
                        emdb = self.get_associated_emdb(pdb_id)
                        if emdb:
                            emdb_ids.add(emdb)

            return list(set(pdb_ids)), list(emdb_ids)

        except requests.exceptions.RequestException as e:
            logger.warning(f"RCSB API请求失败: {e}")
            pdb_ids = self.search_by_doi(doi)
            return pdb_ids, []
        except Exception as e:
            logger.warning(f"搜索失败: {e}")
            return [], []

    def get_associated_emdb(self, pdb_id: str) -> Optional[str]:
        """获取PDB关联的EMDB ID"""
        try:
            url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id.upper()}"
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                data = response.json()

                # 检查database2字段
                if "database2" in data:
                    for db in data["database2"]:
                        if db.get("database_id") == "EMDB":
                            code = db.get("database_code", "")
                            if code:
                                return f"EMD-{code}" if not code.startswith("EMD-") else code

        except Exception as e:
            logger.debug(f"获取{pdb_id}关联EMDB失败: {e}")
        return None
    
    def _clean_doi(self, doi: str) -> str:
        """清理DOI格式"""
        if not doi:
            return ""
        
        doi_str = str(doi).strip()
        
        # 移除URL前缀
        prefixes = [
            "https://doi.org/",
            "http://doi.org/",
            "doi:",
            "DOI:",
            "https://dx.doi.org/",
            "http://dx.doi.org/"
        ]
        
        for prefix in prefixes:
            if doi_str.startswith(prefix):
                doi_str = doi_str[len(prefix):]
                break
        
        return doi_str.strip()
    
    def get_pdb_details(self, pdb_id: str) -> Dict[str, Any]:
        """获取PDB结构的详细信息"""
        pdb_id_clean = str(pdb_id).strip().lower()
        
        try:
            # 获取结构摘要信息
            summary_url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id_clean}"
            summary_response = requests.get(summary_url, timeout=30)
            
            details = {
                "pdb_id": pdb_id_clean.upper(),
                "summary": None,
                "citation_info": None,
                "related_emdb": [],
                "is_cryoem": False,
                "error": None
            }
            
            if summary_response.status_code == 200:
                details["summary"] = summary_response.json()
                
                # 检查是否为冷冻电镜结构
                exp_methods = details["summary"].get("exptl", [])
                for method in exp_methods:
                    method_str = method.get("method", "").lower()
                    if any(keyword in method_str for keyword in ["electron microscopy", "cryo-em", "cryoem", "em"]):
                        details["is_cryoem"] = True
                        break
            
            # 获取关联的EMDB ID
            details["related_emdb"] = self._get_related_emdb_ids(pdb_id_clean)
            
            # 如果有EMDB关联，也标记为冷冻电镜
            if details["related_emdb"]:
                details["is_cryoem"] = True
            
            return details
            
        except Exception as e:
            logger.warning(f"获取PDB {pdb_id} 详情失败: {e}")
            return {
                "pdb_id": pdb_id_clean.upper(),
                "error": str(e)
            }
    
    def _get_related_emdb_ids(self, pdb_id: str) -> List[str]:
        """获取与PDB结构关联的EMDB ID"""
        try:
            # 使用PDBe API获取关联的EMDB ID
            pdbe_url = f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/related_experimental_data/{pdb_id}"
            response = requests.get(pdbe_url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                emdb_ids = []
                
                # 解析返回数据，提取EMDB ID
                for entry in data.get(pdb_id, []):
                    if entry.get("database") == "EMDB":
                        emdb_id = entry.get("accession_code", "")
                        if emdb_id:
                            emdb_clean = emdb_id.upper()
                            if not emdb_clean.startswith("EMD-"):
                                emdb_clean = f"EMD-{emdb_clean}"
                            emdb_ids.append(emdb_clean)
                
                return list(set(emdb_ids))
        except Exception as e:
            logger.warning(f"获取EMDB关联信息失败: {e}")
        
        return []
    
    def get_pdbe_metadata(self, pdb_id: str) -> Dict[str, Any]:
        """从PDBe API获取PDB结构的详细元数据（包括关联的EMDB ID）"""
        try:
            pdb_id_clean = str(pdb_id).strip().lower()
            url = f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/summary/{pdb_id_clean}"
            
            response = requests.get(url, timeout=30)
            
            if response.status_code != 200:
                return {"error": f"API请求失败: {response.status_code}"}
            
            data = response.json()
            
            if pdb_id_clean not in data or not data[pdb_id_clean]:
                return {"error": "PDB ID不存在或数据为空"}
            
            entry_data = data[pdb_id_clean][0]
            
            # 提取EMDB ID
            emdb_ids = []
            if "related_structures" in entry_data:
                for related in entry_data["related_structures"]:
                    if related.get("resource") == "EMDB":
                        emdb_id = related.get("accession", "")
                        if emdb_id:
                            emdb_clean = emdb_id.upper()
                            if not emdb_clean.startswith("EMD-"):
                                emdb_clean = f"EMD-{emdb_clean}"
                            emdb_ids.append(emdb_clean)
            
            # 构建元数据
            metadata = {
                "pdb_id": pdb_id_clean.upper(),
                "title": entry_data.get("title", ""),
                "deposition_date": entry_data.get("deposition_date", ""),
                "release_date": entry_data.get("release_date", ""),
                "experimental_methods": entry_data.get("experimental_method", []),
                "experimental_method_class": entry_data.get("experimental_method_class", []),
                "related_structures": entry_data.get("related_structures", []),
                "related_emdb_ids": emdb_ids,
                "is_cryoem": "em" in [c.lower() for c in entry_data.get("experimental_method_class", [])] or bool(emdb_ids)
            }
            
            return metadata
            
        except Exception as e:
            logger.warning(f"获取PDBe元数据失败 {pdb_id}: {e}")
            return {"error": str(e)}

    def get_pdb_from_emdb(self, emdb_id: str) -> Tuple[List[str], Dict[str, Any]]:
        """
        通过EMDB ID获取关联的PDB ID（调用PDBe API）

        Args:
            emdb_id: EMDB ID（如 "EMD-12345" 或 "12345"）

        Returns:
            Tuple[List[str], Dict]: (pdb_ids, api_response)
            - pdb_ids: 关联的PDB ID列表
            - api_response: API响应信息（用于调试或额外信息）
        """
        # 清理EMDB ID格式
        emdb_clean = emdb_id.strip().upper()

        # 移除EMD-前缀（如果存在）
        emdb_code = emdb_clean
        if emdb_clean.startswith("EMD-"):
            emdb_code = emdb_clean[4:]

        # 如果只剩数字，添加回去
        if emdb_code.isdigit():
            emdb_code = f"EMD-{emdb_code}"

        logger.info(f"查询EMDB {emdb_clean} 关联的PDB ID...")

        try:
            # 方法1：使用PDBe API获取关联的PDB ID
            pdbe_url = f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/related_experimental_data/{emdb_code.lower()}"

            response = requests.get(pdbe_url, timeout=30)

            api_response = {
                "url": pdbe_url,
                "status_code": response.status_code,
                "data": None
            }

            pdb_ids = []

            if response.status_code == 200:
                data = response.json()
                api_response["data"] = data

                # 解析返回数据，提取PDB ID
                # PDBe API返回格式: {"emd_code": [{"database": "PDB", "accession_code": "pdb_id"}]}
                if emdb_code.lower() in data:
                    for entry in data[emdb_code.lower()]:
                        if entry.get("database") == "PDB":
                            pdb_id = entry.get("accession_code", "").upper()
                            if pdb_id and len(pdb_id) == 4 and pdb_id[0].isdigit():
                                pdb_ids.append(pdb_id)

                pdb_ids = list(set(pdb_ids))
                logger.info(f"EMDB {emdb_clean} 找到 {len(pdb_ids)} 个关联PDB: {pdb_ids}")
            else:
                logger.warning(f"PDBe API返回状态码: {response.status_code}")

            # 方法2：如果方法1失败，尝试从RCSB获取
            if not pdb_ids:
                rcsb_url = f"https://data.rcsb.org/rest/v1/core/entry/{emdb_clean.lower()}"
                try:
                    rcsb_response = requests.get(rcsb_url, timeout=30)

                    if rcsb_response.status_code == 200:
                        rcsb_data = rcsb_response.json()
                        api_response["rcsb_data"] = rcsb_data

                        # 从database2字段提取PDB ID
                        if "database2" in rcsb_data:
                            for db in rcsb_data["database2"]:
                                if db.get("database_id") == "PDB":
                                    pdb_id = db.get("database_code", "").upper()
                                    if pdb_id and len(pdb_id) == 4 and pdb_id[0].isdigit():
                                        pdb_ids.append(pdb_id)

                        pdb_ids = list(set(pdb_ids))
                        logger.info(f"通过RCSB API找到 {len(pdb_ids)} 个关联PDB: {pdb_ids}")
                except Exception as rcsb_error:
                    logger.debug(f"RCSB API查询失败: {rcsb_error}")

            return pdb_ids, api_response

        except requests.exceptions.RequestException as e:
            logger.warning(f"PDBe API请求失败: {e}")
            return [], {"error": str(e)}
        except Exception as e:
            logger.error(f"获取EMDB关联PDB失败: {e}")
            return [], {"error": str(e)}

    def get_emdb_to_pdb_mapping(self, emdb_ids: List[str]) -> Dict[str, List[str]]:
        """
        批量获取多个EMDB ID对应的PDB ID

        Args:
            emdb_ids: EMDB ID列表

        Returns:
            Dict: {emdb_id: [pdb_ids]} 的映射字典
        """
        mapping = {}

        for emdb_id in emdb_ids:
            pdb_ids, _ = self.get_pdb_from_emdb(emdb_id)
            if pdb_ids:
                mapping[emdb_id] = pdb_ids

        return mapping

    # 添加异步保存方法
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

def re_extract_structure_ids(
    literature_id: int,
    show_progress: bool = True,
    use_structure_manager: bool = True,
    force_update: bool = True,
    fetch_missing_emdb: bool = True,
    use_doi_for_validation: bool = True
) -> Dict[str, Any]:
    """
    重新提取和处理文献的结构ID（简化版，不进行过滤）
    
    流程：
    1. PDF提取：从PDF中提取原始结构ID
    2. DOI验证：通过DOI获取文献关联的结构ID  
    3. ID合并：EMDB合并去重，PDB不进行过滤
    4. 补充获取：如果没有EMDB ID，从最大数字PDB获取
    5. 结构处理：使用结构管理器处理所有ID（包含过滤）
    6. 保存数据库：保存到 literature.cryoem_targets
    """
    result = {
        "success": False,
        "message": "",
        "extracted_ids": {"pdb_ids": [], "emdb_ids": []},
        "validated_ids": {"pdb_ids": [], "emdb_ids": []},
        "doi_validation": {},
        "database_saved": False,
        "error": None,
        "emdb_fetch_info": {},
        "structure_manager_result": None
    }
    
    try:
        from core.literature_db import create_literature_session
        session = create_literature_session()
        
        from core.literature_db import LiteratureEntry
        literature = session.get(LiteratureEntry, literature_id)
        
        if not literature:
            result["message"] = "文献不存在"
            result["error"] = "Literature not found"
            session.close()
            return result
            
        if not literature.main_pdf_path:
            result["message"] = "文献没有PDF文件"
            result["error"] = "No PDF file"
            session.close()
            return result
        
        if show_progress:
            import streamlit as st
            with st.spinner("提取和处理结构ID中..."):
                return _process_extraction_final_simplified(
                    literature, 
                    session, 
                    show_progress, 
                    use_structure_manager, 
                    force_update,
                    fetch_missing_emdb,
                    use_doi_for_validation,
                    result
                )
        else:
            return _process_extraction_final_simplified(
                literature, 
                session, 
                show_progress, 
                use_structure_manager, 
                force_update,
                fetch_missing_emdb,
                use_doi_for_validation,
                result
            )
            
    except Exception as e:
        logger.error(f"处理失败: {e}")
        result["error"] = str(e)
        result["message"] = f"处理失败: {e}"
        return result   

# 修复1：修复变量作用域问题
def _process_extraction_final_simplified(
    literature,
    session,
    show_progress: bool,
    use_structure_manager: bool,
    force_update: bool,
    fetch_missing_emdb: bool,
    use_doi_for_validation: bool,
    result: Dict
) -> Dict:
    """提取处理核心逻辑（添加DOI验证调试）"""
    try:
        if show_progress:
            import streamlit as st
            st.info("📄 步骤1: 解析PDF文件提取结构ID...")
        
        # 1. 从PDF提取结构ID
        structure_ids = _extract_ids_from_pdf(literature.main_pdf_path, show_progress)
        
        if not structure_ids:
            result["message"] = "未从PDF中提取到任何结构ID"
            literature.cryoem_targets = {}
            session.commit()
            result["database_saved"] = True
            return result
        
        pdf_pdb_ids = structure_ids.get("pdb_ids", [])
        pdf_emdb_ids = structure_ids.get("emdb_ids", [])
        
        logger.info(f"PDF提取结果: PDB={pdf_pdb_ids}, EMDB={pdf_emdb_ids}")
        
        # 2. 如果有DOI，通过DOI验证和获取结构ID
        doi_validation_result = {}
        if use_doi_for_validation and literature.doi:
            if show_progress:
                import streamlit as st
                st.info("🔗 步骤2: 通过DOI验证和获取结构ID...")
            
            doi_validation_result = _validate_ids_with_doi(
                literature.doi, 
                pdf_pdb_ids, 
                pdf_emdb_ids,
                show_progress
            )
            
            result["doi_validation"] = doi_validation_result
            
            # 添加调试信息
            logger.info(f"🔍 DOI验证结果:")
            logger.info(f"  - DOI: {literature.doi}")
            logger.info(f"  - DOI获取的PDB IDs: {doi_validation_result.get('doi_pdb_ids', [])}")
            logger.info(f"  - DOI获取的EMDB IDs: {doi_validation_result.get('doi_emdb_ids', [])}")
            logger.info(f"  - 验证状态: {doi_validation_result.get('validation_status', 'unknown')}")
            
            if show_progress:
                import streamlit as st
                if doi_validation_result.get("doi_pdb_ids"):
                    st.success(f"✅ 通过DOI获取到 {len(doi_validation_result['doi_pdb_ids'])} 个PDB结构")
                else:
                    st.warning(f"⚠️ 通过DOI未获取到PDB结构")
        
        # 3. 合并所有ID（不进行过滤）
        if show_progress:
            import streamlit as st
            st.info("🔄 步骤3: 合并所有结构ID...")
        
        merged_result = merge_structure_ids_without_filtering(
            pdf_pdb_ids=pdf_pdb_ids,
            pdf_emdb_ids=pdf_emdb_ids,
            doi_pdb_ids=doi_validation_result.get("doi_pdb_ids", []),
            doi_emdb_ids=doi_validation_result.get("doi_emdb_ids", []),
            show_progress=show_progress
        )
        
        # 添加合并结果的调试信息
        logger.info(f"🔍 合并结果:")
        logger.info(f"  - 总PDB IDs: {len(merged_result['pdb_ids'])}个")
        logger.info(f"  - 总EMDB IDs: {len(merged_result['emdb_ids'])}个")
        logger.info(f"  - DOI PDB IDs: {doi_validation_result.get('doi_pdb_ids', [])}")
        logger.info(f"  - PDF PDB IDs: {pdf_pdb_ids}")
        
        all_pdb_ids = merged_result["pdb_ids"]
        all_emdb_ids = merged_result["emdb_ids"]

        # 初始化变量，避免作用域问题
        final_pdb_ids = all_pdb_ids
        final_emdb_ids = all_emdb_ids
        
        # 4. 使用结构管理器处理所有ID（包含获取元数据和过滤）
        if use_structure_manager and (all_pdb_ids or all_emdb_ids):
            try:
                if show_progress:
                    import streamlit as st
                    st.info("⚙️ 步骤4: 使用结构管理器获取元数据并应用过滤...")
                
                # 准备传递给结构管理器的数据 - 确保变量在if语句内定义
                structure_ids_for_manager = {
                    "pdb_ids": all_pdb_ids,
                    "emdb_ids": all_emdb_ids,
                    "extraction_method": "pdf_parser_with_doi_validation",
                    "source_type": "pdf_text",
                    "source_info": {
                        "pdf_path": literature.main_pdf_path,
                        "doi": literature.doi,
                        "extraction_timestamp": datetime.now().isoformat(),
                        "pdf_pdb_ids": pdf_pdb_ids,
                        "doi_pdb_ids": doi_validation_result.get("doi_pdb_ids", []),
                        "doi_pdb_details": doi_validation_result.get("pdb_details", {})
                    }
                }
                
                # 调用结构管理器（应用过滤）
                structure_result = _call_structure_manager_with_filtering(
                    structure_ids_for_manager, 
                    force_update, 
                    show_progress
                )
                
                result["structure_manager_result"] = structure_result
                
                # 从结构管理器结果中获取过滤后的ID
                if structure_result and "pdb_metadata" in structure_result:
                    filtered_pdb_ids = list(structure_result["pdb_metadata"].keys())
                    final_pdb_ids = filtered_pdb_ids
                    
                    # 显示过滤结果
                    if show_progress:
                        filtering_info = structure_result.get("filtering_info", {})
                        if filtering_info.get("filter_applied"):
                            original = filtering_info.get("original_pdb_count", 0)
                            final = filtering_info.get("final_pdb_count", 0)
                            filtered = filtering_info.get("filtered_out_count", 0)
                            
                            if filtered > 0:
                                st.success(f"✅ 过滤完成: 保留 {final}/{original} 个PDB，过滤掉 {filtered} 个")
                                if filtering_info.get("filtered_pdb_ids"):
                                    with st.expander("查看过滤的PDB ID"):
                                        for pdb_id in filtering_info["filtered_pdb_ids"]:
                                            st.write(f"- {pdb_id}")
                else:
                    final_pdb_ids = all_pdb_ids
                
                # 使用结构管理器结果中的EMDB ID
                if structure_result and "emdb_metadata" in structure_result:
                    final_emdb_ids = list(structure_result["emdb_metadata"].keys())
                else:
                    final_emdb_ids = all_emdb_ids
                
            except ImportError as e:
                logger.warning(f"结构管理器导入失败: {e}")
                result["structure_manager_error"] = f"结构管理器不可用: {e}"
                final_pdb_ids = all_pdb_ids
                final_emdb_ids = all_emdb_ids
            except Exception as e:
                logger.warning(f"结构管理器处理失败: {e}")
                result["structure_manager_error"] = f"结构管理器处理失败: {e}"
                final_pdb_ids = all_pdb_ids
                final_emdb_ids = all_emdb_ids
        
        # 5. 构建简化的cryoem_targets数据
        cryoem_targets = _build_simple_cryoem_targets(
            pdb_ids=final_pdb_ids,
            emdb_ids=final_emdb_ids,
            extraction_info={
                "method": structure_ids.get("extraction_method", "pdf_parser"),
                "source_type": structure_ids.get("source_type", "pdf_text"),
                "filtering_performed": use_structure_manager,
                "extracted_at": datetime.now().isoformat(),
                "pdf_path": literature.main_pdf_path
            }
        )
        
        # 6. 保存到数据库
        logger.info(f"保存cryoem_targets到数据库: PDB={len(final_pdb_ids)}, EMDB={len(final_emdb_ids)}")
        
        literature.cryoem_targets = cryoem_targets
        literature.updated_at = datetime.now()
        
        # 如果有提取到结构ID，更新状态
        if final_pdb_ids or final_emdb_ids:
            from core.literature_db import LiteratureStatus
            literature.status = LiteratureStatus.PARSED
            literature.parsed_at = datetime.now()
        
        session.commit()
        
        result["cryoem_targets"] = cryoem_targets
        result["database_saved"] = True
        result["success"] = True
        result["message"] = "结构ID提取和处理完成，已保存到数据库！"
        
        # 7. 显示最终结果摘要
        if show_progress:
            import streamlit as st
            st.success("🎉 结构ID提取和处理完成，已保存到数据库！")
            
            # 显示结果统计
            col1, col2 = st.columns(2)
            with col1:
                st.metric("最终PDB数量", len(final_pdb_ids))
            with col2:
                st.metric("最终EMDB数量", len(final_emdb_ids))
        
        session.close()
        return result
        
    except Exception as e:
        error_msg = f"重新提取失败: {e}"
        logger.error(f"重新提取结构ID失败: {e}", exc_info=True)
        if show_progress:
            import streamlit as st
            st.error(error_msg)
        result["error"] = error_msg
        result["message"] = error_msg
        try:
            session.rollback()
            session.close()
        except:
            pass
        return result
    
def merge_structure_ids_without_filtering(
    pdf_pdb_ids: List[str],
    pdf_emdb_ids: List[str],
    doi_pdb_ids: List[str],
    doi_emdb_ids: List[str],
    show_progress: bool = False
) -> Dict[str, Any]:
    """
    合并结构ID但不进行过滤（因为需要元数据信息）
    
    规则：
    1. EMDB ID: PDF提取 + DOI获取，合并去重
    2. PDB ID: PDF提取 + DOI获取，合并去重
    3. 不进行任何过滤（留给结构管理器在获取元数据后处理）
    
    Args:
        pdf_pdb_ids: 从PDF提取的PDB IDs
        pdf_emdb_ids: 从PDF提取的EMDB IDs
        doi_pdb_ids: 通过DOI获取的PDB IDs
        doi_emdb_ids: 通过DOI获取的EMDB IDs
        show_progress: 是否显示进度
        
    Returns:
        合并结果
    """
    # 1. 合并所有EMDB ID（去重）
    all_emdb_ids = list(set(pdf_emdb_ids + doi_emdb_ids))
    
    # 2. 合并所有PDB ID（去重）
    all_pdb_ids = list(set(pdf_pdb_ids + doi_pdb_ids))
    
    # 3. 记录来源信息
    source_info = {
        "pdf_pdb_count": len(pdf_pdb_ids),
        "pdf_emdb_count": len(pdf_emdb_ids),
        "doi_pdb_count": len(doi_pdb_ids),
        "doi_emdb_count": len(doi_emdb_ids),
        "merged_pdb_count": len(all_pdb_ids),
        "merged_emdb_count": len(all_emdb_ids),
        "pdf_pdb_ids": pdf_pdb_ids,
        "doi_pdb_ids": doi_pdb_ids,
        "timestamp": datetime.now().isoformat()
    }
    
    if show_progress:
        import streamlit as st
        st.info("📊 ID合并结果（不进行过滤）:")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("PDF PDB", len(pdf_pdb_ids))
        with col2:
            st.metric("DOI PDB", len(doi_pdb_ids))
        with col3:
            st.metric("PDF EMDB", len(pdf_emdb_ids))
        with col4:
            st.metric("DOI EMDB", len(doi_emdb_ids))
        
        st.info("🔍 过滤将在获取元数据后由结构管理器执行")
    
    return {
        "pdb_ids": all_pdb_ids,
        "emdb_ids": all_emdb_ids,
        "source_info": source_info
    }

def _call_structure_manager_with_filtering(
    structure_ids: Dict, 
    force_update: bool, 
    show_progress: bool
) -> Dict:
    """
    调用结构管理器并应用过滤（强制更新版）
    """
    try:
        # 尝试导入结构管理器
        try:
            from core.structure_manager import StructureMetadataFetcher
        except ImportError:
            try:
                from structure.structure_manager import StructureMetadataFetcher
            except ImportError as e:
                logger.error(f"结构管理器导入失败: {e}")
                return {"error": f"结构管理器不可用: {e}"}
        
        # 创建结构管理器配置
        fetcher_config = {
            'max_workers': 3,
            'timeout': 30 # 稍微增加超时，因为现在要请求 PDBe
        }
        
        # 创建结构管理器
        structure_fetcher = StructureMetadataFetcher(fetcher_config)
        
        # 添加标记，告诉结构管理器需要应用过滤
        structure_ids_with_mark = structure_ids.copy()
        structure_ids_with_mark["apply_filtering"] = True
        
        # === 关键修改：强制开启 force_update ===
        # 这里的 force_update=True 会传递给 fetch_pdb_metadata
        # 从而跳过文件缓存，重新执行 API 请求和新的修正逻辑
        real_force_update = True 
        
        if show_progress:
            import streamlit as st
            with st.spinner("使用新的高效方法获取结构元数据..."):
                # 调用结构管理器
                structure_result = structure_fetcher.process_structure_ids(
                    structure_ids=structure_ids_with_mark,
                    force_update=real_force_update, # <--- 强制为 True
                    fetch_uniprot=True  # 确保获取UniProt信息
                )
        else:
            structure_result = structure_fetcher.process_structure_ids(
                structure_ids=structure_ids_with_mark,
                force_update=real_force_update, # <--- 强制为 True
                fetch_uniprot=True
            )
        
        return structure_result
        
    except Exception as e:
        logger.error(f"结构管理器处理失败: {e}")
        return {"error": f"结构管理器处理失败: {e}"}

def _validate_ids_with_doi(
    doi: str, 
    pdf_pdb_ids: List[str],
    pdf_emdb_ids: List[str],
    show_progress: bool = False
) -> Dict[str, Any]:
    """
    通过DOI验证和获取结构ID - 修复版
    """
    result = {
        "doi": doi,
        "doi_pdb_ids": [],
        "doi_pdb_details": {},
        "doi_emdb_ids": [],
        "validation_status": "not_attempted",
        "error": None
    }
    
    try:
        # 初始化RCSB搜索客户端
        search_client = RCSBPDBSearch()

        if show_progress:
            import streamlit as st
            st.write(f"  查询DOI: {doi}")

        # 通过DOI同时获取PDB ID和EMDB ID
        doi_pdb_ids, doi_emdb_ids = search_client.search_by_doi_with_emdb(doi)

        if not doi_pdb_ids:
            result["validation_status"] = "no_pdb_found"
            logger.warning(f"DOI {doi} 没有找到关联的PDB结构")
            return result

        result["doi_pdb_ids"] = doi_pdb_ids
        result["doi_emdb_ids"] = doi_emdb_ids  # 添加从RCSB API获取的EMDB ID
        result["validation_status"] = "pdb_found"

        logger.info(f"✅ DOI {doi} 找到 {len(doi_pdb_ids)} 个PDB结构: {doi_pdb_ids}")
        if doi_emdb_ids:
            logger.info(f"  同时找到 {len(doi_emdb_ids)} 个EMDB结构: {doi_emdb_ids}")

        # 并行获取每个PDB的详细信息
        if show_progress:
            import streamlit as st
            st.write(f"  获取 {len(doi_pdb_ids)} 个PDB结构的详细信息...")

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_pdb = {
                executor.submit(search_client.get_pdbe_metadata, pdb_id): pdb_id
                for pdb_id in doi_pdb_ids
            }

            for future in as_completed(future_to_pdb):
                pdb_id = future_to_pdb[future]
                try:
                    pdb_details = future.result(timeout=10)
                    result["doi_pdb_details"][pdb_id] = pdb_details

                    # 提取EMDB ID
                    if "related_emdb_ids" in pdb_details:
                        emdb_ids = pdb_details["related_emdb_ids"]
                        if emdb_ids:
                            result["doi_emdb_ids"].extend(emdb_ids)
                            logger.info(f"  PDB {pdb_id} 有关联的EMDB: {emdb_ids}")

                    # 🔍 检查PDB是否为冷冻电镜结构
                    is_cryoem = pdb_details.get("is_cryoem", False)
                    if is_cryoem:
                        logger.info(f"  PDB {pdb_id} 是冷冻电镜结构")

                except Exception as e:
                    logger.warning(f"获取PDB {pdb_id} 详情失败: {e}")
                    result["doi_pdb_details"][pdb_id] = {"error": str(e)}

        # 去重
        result["doi_emdb_ids"] = list(set(result["doi_emdb_ids"]))
        
        if show_progress:
            import streamlit as st
            st.write(f"  通过DOI找到 {len(doi_pdb_ids)} 个PDB ID和 {len(result['doi_emdb_ids'])} 个EMDB ID")
        
        logger.info(f"✅ DOI验证完成: {len(doi_pdb_ids)} PDB, {len(result['doi_emdb_ids'])} EMDB")
        
        return result
        
    except Exception as e:
        logger.error(f"DOI验证失败: {e}")
        result["validation_status"] = "error"
        result["error"] = str(e)
        return result

def _extract_ids_from_pdf(pdf_path: str, show_progress: bool) -> Dict:
    """从PDF中提取结构ID"""
    try:
        # 尝试导入文献解析器
        try:
            from core.literature_parser import LiteratureParserConfig, LiteratureParserManager
        except ImportError:
            try:
                from literature.literature_parser import LiteratureParserConfig, LiteratureParserManager
            except ImportError:
                logger.error("无法导入文献解析器")
                return {}
        
        # 创建解析器配置
        parser_config = LiteratureParserConfig()
        parser_config.AI_ENABLED = False  # 禁用AI，只提取ID
        parser_config.FETCH_METADATA_ONLINE = False
        parser_config.EXTRACT_STRUCTURE_IDS = True
        
        # 创建解析器
        parser = LiteratureParserManager(parser_config)
        
        # 解析PDF文件
        logger.info(f"解析PDF文件: {pdf_path}")
        parse_result = parser.parse_literature_file(pdf_path)
        
        if not parse_result.get("success"):
            logger.warning(f"PDF解析失败: {parse_result.get('errors', [])}")
            return {}
        
        parsed_data = parse_result.get("parsed_data", {})
        structure_ids = parsed_data.get("structure_ids", {})
        
        # 清理和标准化ID
        if "pdb_ids" in structure_ids:
            structure_ids["pdb_ids"] = _clean_pdb_ids(structure_ids["pdb_ids"])
        
        if "emdb_ids" in structure_ids:
            structure_ids["emdb_ids"] = _clean_emdb_ids(structure_ids["emdb_ids"])
        
        logger.info(f"提取到的结构ID: PDB={structure_ids.get('pdb_ids', [])}, EMDB={structure_ids.get('emdb_ids', [])}")
        return structure_ids
        
    except Exception as e:
        logger.error(f"PDF解析失败: {e}", exc_info=True)
        return {}


def _clean_pdb_ids(pdb_ids) -> List[str]:
    """清理和标准化PDB IDs"""
    if not pdb_ids:
        return []
    
    cleaned = []
    for pdb_id in pdb_ids:
        if isinstance(pdb_id, str):
            pdb_clean = pdb_id.strip().upper()
            # PDB ID格式：4个字符，第一个是数字
            if len(pdb_clean) == 4 and pdb_clean[0].isdigit():
                cleaned.append(pdb_clean)
    
    return list(set(cleaned))


def _clean_emdb_ids(emdb_ids) -> List[str]:
    """清理和标准化EMDB IDs"""
    if not emdb_ids:
        return []
    
    cleaned = []
    for emdb_id in emdb_ids:
        if isinstance(emdb_id, str):
            emdb_clean = emdb_id.strip().upper()
            # 标准化EMDB ID格式：EMD-数字
            if emdb_clean.startswith("EMD-"):
                cleaned.append(emdb_clean)
            elif re.match(r'^EMD\d+$', emdb_clean):
                # 格式：EMD12345 -> EMD-12345
                cleaned.append(f"EMD-{emdb_clean[3:]}")
            elif re.match(r'^\d+$', emdb_clean):
                # 格式：12345 -> EMD-12345
                cleaned.append(f"EMD-{emdb_clean}")
    
    return list(set(cleaned))

def _build_simple_cryoem_targets(
    pdb_ids: List[str],
    emdb_ids: List[str],
    extraction_info: Dict
) -> Dict:
    """
    构建简化的cryoem_targets数据，只包含ID和基本提取信息
    
    Args:
        pdb_ids: PDB ID列表
        emdb_ids: EMDB ID列表
        extraction_info: 提取信息
        
    Returns:
        简化的cryoem_targets字典
    """
    return {
        "pdb_ids": pdb_ids,
        "emdb_ids": emdb_ids,
        "extraction_info": extraction_info,
        "saved_at": datetime.now().isoformat()
    }


# 使用示例
def create_extract_button(
    literature_id: int, 
    button_label: str = "🔍 重新提取ID", 
    fetch_missing_emdb: bool = True,
    use_doi_validation: bool = True
):
    """创建提取按钮的便捷函数"""
    import streamlit as st
    
    if st.button(button_label, key=f"extract_ids_{literature_id}", use_container_width=True):
        result = re_extract_structure_ids(
            literature_id, 
            show_progress=True,
            fetch_missing_emdb=fetch_missing_emdb,
            use_doi_for_validation=use_doi_validation
        )
        
        if result["success"]:
            time.sleep(2)
            st.rerun()
        else:
            st.error(f"❌ {result.get('message', '提取失败')}")


# 批量处理版本
def batch_re_extract_structure_ids(
    literature_ids: List[int],
    max_workers: int = 3,
    show_progress: bool = True,
    fetch_missing_emdb: bool = True,
    use_doi_validation: bool = True
) -> Dict[int, Dict[str, Any]]:
    """
    批量重新提取多个文献的结构ID
    
    Args:
        literature_ids: 文献ID列表
        max_workers: 最大并发数
        show_progress: 是否显示总体进度
        fetch_missing_emdb: 是否尝试获取缺失的EMDB ID
        use_doi_validation: 是否使用DOI验证
        
    Returns:
        字典，键为文献ID，值为处理结果
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import streamlit as st
    
    results = {}
    
    if show_progress:
        progress_bar = st.progress(0)
        status_text = st.empty()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {
            executor.submit(
                re_extract_structure_ids, 
                lit_id, 
                show_progress=False,
                fetch_missing_emdb=fetch_missing_emdb,
                use_doi_for_validation=use_doi_validation
            ): lit_id
            for lit_id in literature_ids
        }
        
        completed = 0
        total = len(literature_ids)
        
        for future in as_completed(future_to_id):
            lit_id = future_to_id[future]
            try:
                result = future.result()
                results[lit_id] = result
            except Exception as e:
                results[lit_id] = {
                    "success": False,
                    "error": str(e),
                    "message": f"处理异常: {e}"
                }
            
            completed += 1
            if show_progress:
                progress = completed / total
                progress_bar.progress(progress)
                status_text.text(f"处理进度: {completed}/{total}")
    
    if show_progress:
        progress_bar.empty()
        status_text.empty()
        
        # 显示统计信息
        success_count = sum(1 for r in results.values() if r.get("success"))
        total_pdb = sum(len(r.get("validated_ids", {}).get("pdb_ids", [])) for r in results.values())
        total_emdb = sum(len(r.get("validated_ids", {}).get("emdb_ids", [])) for r in results.values())
        
        # 统计过滤掉的PDB数量
        filtered_count = sum(r.get("pdb_filter_info", {}).get("filtered_count", 0) for r in results.values())
        
        st.info(f"批量处理完成: {success_count}/{total} 成功")
        st.info(f"📊 提取统计: PDB ID={total_pdb}个, EMDB ID={total_emdb}个")
        if filtered_count > 0:
            st.info(f"⚠️ 过滤统计: 过滤掉 {filtered_count} 个没有EMDB关联的PDB ID")
    
    return results


# 集成到 literature_db.py 的便捷函数
def re_extract_structure_ids_for_literature(
    literature_id: int, 
    fetch_missing_emdb: bool = True,
    use_doi_validation: bool = True
) -> Dict[str, Any]:
    """
    为文献重新提取结构ID（直接在 literature_db.py 中使用的版本）
    
    Args:
        literature_id: 文献ID
        fetch_missing_emdb: 是否尝试获取缺失的EMDB ID
        use_doi_validation: 是否使用DOI验证
        
    Returns:
        处理结果字典
    """
    return re_extract_structure_ids(
        literature_id, 
        show_progress=False,
        fetch_missing_emdb=fetch_missing_emdb,
        use_doi_for_validation=use_doi_validation
    )


# 测试函数
if __name__ == "__main__":
    print("测试结构提取功能...")
    
    # 测试PDBe API
    test_pdb = "7SHE"
    print(f"\n测试从PDBe获取EMDB ID: {test_pdb}")
    print(f"获取到的EMDB ID: {emdb_ids}")
    
    # 测试RCSB搜索
    search_client = RCSBPDBSearch()
    test_doi = "10.1038/s41586-021-03969-3"
    print(f"\n测试RCSB DOI搜索: {test_doi}")
    pdb_ids = search_client.search_by_doi(test_doi)
    print(f"获取到的PDB ID: {pdb_ids}")
    
    if pdb_ids:
        print(f"\n获取第一个PDB的详细信息:")
        details = search_client.get_pdbe_metadata(pdb_ids[0])
        print(f"标题: {details.get('title', 'N/A')}")
        print(f"EMDB关联: {details.get('related_emdb_ids', [])}")
    
    print("\n✅ 测试完成！")