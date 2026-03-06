# structure_kg_integration.py - 结构知识图谱集成模块（专注靶点信息）
import json, logging, time, re, math
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict, Counter
from datetime import datetime
from dataclasses import asdict
import networkx as nx
import numpy as np

# 添加缺少的导入
from core.structure_kg_manager import get_kg_manager
from core.structure_knowledge_graph import NodeType, EdgeType
from core.literature_db import create_literature_session, LiteratureEntry

# 尝试导入UniProt模块
try:
    from core.uniprot_client import (
        UniProtAPIClient, UniProtNormalizer, get_uniprot_client, get_uniprot_normalizer
    )
    HAS_UNIPROT = True
except ImportError as e:
    HAS_UNIPROT = False
    logger = logging.getLogger(__name__)
    logger.warning(f"无法导入UniProt模块: {e}")

logger = logging.getLogger(__name__)

class StructureKGIntegration:
    """结构知识图谱集成（专注靶点信息）"""
    
    def __init__(self, literature_manager=None):
        self.literature_manager = literature_manager
        self.kg_manager = get_kg_manager()
        
        # UniProt客户端
        self.uniprot_client = None
        self.uniprot_normalizer = None
        
        if HAS_UNIPROT:
            try:
                self.uniprot_client = get_uniprot_client()
                self.uniprot_normalizer = get_uniprot_normalizer()
                logger.info("✅ UniProt客户端初始化完成")
            except Exception as e:
                logger.warning(f"UniProt客户端初始化失败: {e}")
        
        # 如果文献管理器未提供，尝试获取默认的
        if not self.literature_manager:
            try:
                # 尝试从 structure_enhanced_literature 获取
                from structure_enhanced_literature import get_enhanced_literature_manager
                self.literature_manager = get_enhanced_literature_manager()
            except ImportError:
                logger.warning("无法导入 structure_enhanced_literature，将使用直接数据库访问")
        
        logger.info("✅ 结构知识图谱集成初始化（专注靶点信息）")
    
    def build_kg_from_literature(self) -> Dict[str, Any]:
        """从文献数据构建知识图谱"""
        try:
            # 1. 获取所有文献数据
            logger.info("获取文献数据...")
            session = create_literature_session()
            literature_entries = session.query(LiteratureEntry).filter(
                LiteratureEntry.cryoem_targets.isnot(None)
            ).all()
            
            if not literature_entries:
                # 如果没有包含结构信息的文献，尝试获取所有文献
                literature_entries = session.query(LiteratureEntry).all()
                if not literature_entries:
                    session.close()
                    return {"success": False, "error": "数据库中没有文献数据"}
            
            # 2. 获取结构元数据
            logger.info("获取结构元数据...")
            structure_metadata = {}
            all_structure_ids = set()
            
            for entry in literature_entries:
                try:
                    if entry.cryoem_targets:
                        # 解析结构ID
                        cryo_targets = json.loads(entry.cryoem_targets) if isinstance(entry.cryoem_targets, str) else entry.cryoem_targets
                        
                        if isinstance(cryo_targets, dict):
                            structure_ids = []
                            pdb_ids = cryo_targets.get("pdb_ids", [])
                            emdb_ids = cryo_targets.get("emdb_ids", [])
                            
                            # 确保ID是字符串且不为空
                            if isinstance(pdb_ids, list):
                                structure_ids.extend([str(id).strip().upper() for id in pdb_ids if id])
                            if isinstance(emdb_ids, list):
                                structure_ids.extend([str(id).strip().upper() for id in emdb_ids if id])
                            
                            # 收集所有结构ID
                            all_structure_ids.update(structure_ids)
                except Exception as e:
                    logger.debug(f"处理文献 {entry.id} 失败: {e}")
            
            session.close()
            
            # 3. 如果有结构ID，获取元数据
            if all_structure_ids:
                # 清理结构ID，移除空值和无效值
                cleaned_structure_ids = []
                for struct_id in all_structure_ids:
                    if struct_id and isinstance(struct_id, str) and struct_id.strip():
                        cleaned_structure_ids.append(struct_id.strip().upper())
                
                if cleaned_structure_ids:
                    # 尝试使用structure_manager获取元数据
                    try:
                        from core.structure_manager import StructureMetadataFetcher
                        fetcher = StructureMetadataFetcher()
                        pdb_meta, emdb_meta = fetcher.fetch_all_metadata(cleaned_structure_ids, use_cache=True)
                        
                        # 合并元数据
                        if pdb_meta:
                            for k, v in pdb_meta.items():
                                if hasattr(v, '__dataclass_fields__'):
                                    structure_metadata[k] = asdict(v)
                                else:
                                    structure_metadata[k] = v
                        
                        if emdb_meta:
                            for k, v in emdb_meta.items():
                                if hasattr(v, '__dataclass_fields__'):
                                    structure_metadata[k] = asdict(v)
                                else:
                                    structure_metadata[k] = v
                        
                        logger.info(f"获取到 {len(structure_metadata)} 个结构的元数据")
                    except Exception as e:
                        logger.warning(f"获取结构元数据失败: {e}")
                        # 创建基础元数据
                        for struct_id in cleaned_structure_ids:
                            if struct_id.startswith("EMD"):
                                structure_metadata[struct_id] = {
                                    "id": struct_id,
                                    "title": f"EMDB结构 {struct_id}",
                                    "type": "emdb"
                                }
                            else:
                                structure_metadata[struct_id] = {
                                    "id": struct_id,
                                    "title": f"PDB结构 {struct_id}",
                                    "type": "pdb"
                                }
                else:
                    logger.warning("没有有效的结构ID")
            else:
                logger.warning("没有找到结构ID，将创建基础图谱")
            
            # 4. 准备文献数据
            literature_data = []
            for entry in literature_entries:
                try:
                    cryo_targets = None
                    if entry.cryoem_targets:
                        cryo_targets = json.loads(entry.cryoem_targets) if isinstance(entry.cryoem_targets, str) else entry.cryoem_targets
                    
                    literature_data.append({
                        "id": entry.id,
                        "title": entry.title or "",
                        "year": entry.year,
                        "journal": entry.journal or "",
                        "authors": entry.authors or "",
                        "abstract": entry.abstract or "",
                        "cryoem_targets": cryo_targets
                    })
                except Exception as e:
                    logger.debug(f"准备文献数据 {entry.id} 失败: {e}")
            
            # 5. 构建知识图谱
            logger.info(f"开始构建知识图谱: {len(literature_data)} 篇文献, {len(structure_metadata)} 个结构")
            
            result = self.kg_manager.build_from_literature_data(
                literature_data, 
                structure_metadata
            )
            
            return result
            
        except Exception as e:
            logger.error(f"构建知识图谱失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def _enhance_metadata_with_uniprot(self, structure_metadata: Dict[str, Dict[str, Any]]) -> int:
        """使用UniProt增强结构元数据"""
        enhanced_count = 0
        
        for struct_id, metadata in list(structure_metadata.items()):
            # 只处理PDB ID
            if not struct_id.startswith('EMD') and len(struct_id) == 4 and struct_id[0].isdigit():
                try:
                    # 通过PDB ID查找UniProt条目
                    entries = self.uniprot_client.get_by_pdb_id(struct_id)
                    if entries:
                        entry = entries[0]
                        
                        # 添加UniProt信息到元数据
                        metadata["uniprot_info"] = {
                            "uniprot_id": entry.uniprot_id,
                            "protein_name": entry.protein_name,
                            "gene_names": entry.gene_names,
                            "organism": entry.organism,
                            "function": getattr(entry, 'function', '')[:500] if hasattr(entry, 'function') else '',
                            "has_uniprot": True
                        }
                        
                        # 如果元数据中没有蛋白质名称，使用UniProt的名称
                        if not metadata.get("protein_name") and entry.protein_name:
                            metadata["protein_name"] = entry.protein_name
                        
                        # 如果元数据中没有基因名，使用UniProt的基因名
                        if not metadata.get("gene") and entry.gene_names:
                            metadata["gene"] = entry.gene_names[0] if isinstance(entry.gene_names, list) else str(entry.gene_names)
                        
                        enhanced_count += 1
                        
                except Exception as e:
                    logger.debug(f"增强结构 {struct_id} 失败: {e}")
        
        return enhanced_count
    
    def analyze_structure_network(self) -> Dict[str, Any]:
        """分析结构网络（专注靶点信息）"""
        try:
            # 1. 跨文献关联分析
            cross_analysis = self.kg_manager.analyze_cross_literature_associations()
            
            # 2. 查找桥接结构
            bridge_structures = self.kg_manager.find_bridge_structures()
            
            # 3. 发现结构聚类（专注靶点信息）
            clusters = self.kg_manager.discover_structural_clusters_target_focused(n_clusters=5)
            
            # 4. 获取图谱统计
            stats = self.kg_manager.get_graph_statistics()
            
            # 5. 蛋白质信息分析
            protein_analysis = self._analyze_protein_information()
            
            return {
                "success": True,
                "cross_literature_analysis": cross_analysis,
                "bridge_structures": bridge_structures,
                "structural_clusters": clusters,
                "graph_statistics": stats,
                "protein_analysis": protein_analysis,
                "summary": {
                    "total_analyses": 5,
                    "has_bridge_structures": bridge_structures.get("total_found", 0) > 0,
                    "has_clusters": clusters.get("success", False) and len(clusters.get("clusters", [])) > 0,
                    "protein_info_coverage": protein_analysis.get("protein_info_coverage_percentage", 0)
                }
            }
            
        except Exception as e:
            logger.error(f"分析结构网络失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _analyze_protein_information(self) -> Dict[str, Any]:
        """分析蛋白质信息"""
        try:
            # 获取知识图谱实例
            kg = self.kg_manager.knowledge_graph
            
            if not hasattr(kg, 'structure_features') or not kg.structure_features:
                return {"error": "没有结构特征数据"}
            
            # 统计蛋白质信息覆盖率
            total_structures = len(kg.structure_features)
            structures_with_protein_info = 0
            protein_feature_counts = Counter()
            
            for struct_id, feature in kg.structure_features.items():
                if feature.features.get("has_protein_info", 0) > 0.5:
                    structures_with_protein_info += 1
                    
                    # 统计蛋白质特征类型
                    for key in feature.features:
                        if key.startswith('protein_'):
                            protein_feature_counts[key] += 1
            
            # 分析蛋白质家族分布
            family_distribution = Counter()
            for struct_id, feature in kg.structure_features.items():
                families = []
                
                # 基础家族
                for family in kg.family_classifier.protein_family_patterns.keys():
                    if feature.features.get(f"family_{family}", 0) > 0.5:
                        families.append(family)
                
                # 蛋白质特征中的家族
                for key in feature.features:
                    if key.startswith('protein_family_') and feature.features[key] > 0.5:
                        family = key.replace('protein_family_', '')
                        if family not in families:
                            families.append(family)
                
                if families:
                    family_distribution[",".join(sorted(families))] += 1
                else:
                    family_distribution["unknown"] += 1
            
            # 分析最常见的蛋白质特征
            common_protein_features = []
            for feature_name, count in protein_feature_counts.most_common(10):
                common_protein_features.append({
                    "feature": feature_name,
                    "count": count,
                    "percentage": (count / total_structures * 100) if total_structures > 0 else 0
                })
            
            return {
                "success": True,
                "total_structures": total_structures,
                "structures_with_protein_info": structures_with_protein_info,
                "protein_info_coverage_percentage": (structures_with_protein_info / total_structures * 100) if total_structures > 0 else 0,
                "family_distribution": dict(family_distribution),
                "common_protein_features": common_protein_features,
                "has_uniprot_client": HAS_UNIPROT
            }
            
        except Exception as e:
            logger.error(f"蛋白质信息分析失败: {e}")
            return {"success": False, "error": str(e)}
    
    def search_similar_structures_advanced(self, 
                                          query: str,
                                          top_k: int = 10) -> Dict[str, Any]:
        """高级相似结构搜索（专注靶点信息）"""
        try:
            # 从查询中提取结构ID或蛋白质名称
            structure_ids = []
            protein_names = []
            
            # 提取PDB ID
            pdb_matches = re.findall(r'\b([1-9][A-Za-z0-9]{3})\b', query.upper())
            structure_ids.extend(pdb_matches)
            
            # 提取EMDB ID
            emdb_matches = re.findall(r'\b(EMD[-\s_]?\d{4,6})\b', query.upper())
            structure_ids.extend([m.replace(' ', '').replace('_', '-') for m in emdb_matches])
            
            # 尝试提取蛋白质名称
            if HAS_UNIPROT and self.uniprot_normalizer:
                extracted_names = self.uniprot_normalizer.extract_protein_names_from_text(query)
                protein_names.extend(extracted_names)
            
            # 如果没有找到结构ID，但有蛋白质名称，尝试查找相关结构
            if not structure_ids and protein_names and HAS_UNIPROT:
                # 使用第一个蛋白质名称查找相关结构
                protein_name = protein_names[0]
                
                # 标准化蛋白质名称
                normalized_names = self.uniprot_normalizer.normalize_protein_name(protein_name)
                if normalized_names:
                    # 查找最佳UniProt匹配
                    best_match = None
                    for name in normalized_names:
                        match = self.uniprot_normalizer.find_best_uniprot_match(name)
                        if match and (best_match is None or match.get('confidence', 0) > best_match.get('confidence', 0)):
                            best_match = match
                    
                    if best_match:
                        # 通过UniProt ID查找相关PDB结构
                        uniprot_id = best_match['uniprot_id']
                        entries = self.uniprot_client.get_by_uniprot_id(uniprot_id)
                        if entries:
                            entry = entries[0]
                            pdb_ids = entry.pdb_ids
                            if pdb_ids:
                                structure_ids.append(pdb_ids[0])  # 使用第一个PDB ID
            
            if not structure_ids:
                return {
                    "success": False,
                    "error": "查询中未找到结构ID或蛋白质名称",
                    "suggestion": "请使用PDB ID (如 9MD0)、EMDB ID (如 EMD-12345) 或蛋白质名称 (如 GPR158)"
                }
            
            # 使用第一个找到的结构ID进行搜索
            query_structure_id = structure_ids[0]
            
            # 检查图谱中是否有这个节点
            kg = self.kg_manager.knowledge_graph
            if query_structure_id not in kg.nodes:
                return {
                    "success": False,
                    "error": f"结构 {query_structure_id} 不在知识图谱中",
                    "suggestion": "请先构建知识图谱或添加该结构到图谱中"
                }
            
            # 相似结构搜索（专注靶点信息）
            similar_results = self.kg_manager.search_similar_structures(
                query_structure_id, 
                top_k=top_k,
                include_features=True
            )
            
            if not similar_results.get("success"):
                return similar_results
            
            # 获取邻居网络
            neighborhood = self.kg_manager.get_structure_neighborhood(
                query_structure_id,
                max_depth=2
            )
            
            # 功能相似性分析
            functional_analysis = self._analyze_functional_similarity(
                query_structure_id, 
                similar_results.get("similar_structures", [])
            )
            
            return {
                "success": True,
                "query_structure": query_structure_id,
                "detected_protein_names": protein_names,
                "similar_structures": similar_results,
                "neighborhood": neighborhood,
                "functional_analysis": functional_analysis,
                "search_summary": {
                    "search_type": "target_focused",
                    "found_structures": len(structure_ids),
                    "found_proteins": len(protein_names),
                    "similar_count": len(similar_results.get("similar_structures", [])),
                    "neighbor_count": neighborhood.get("neighborhood", {}).get("node_count", 0) if neighborhood.get("success") else 0
                }
            }
            
        except Exception as e:
            logger.error(f"高级相似结构搜索失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _analyze_functional_similarity(self, query_structure_id: str, 
                                      similar_structures: List[Dict[str, Any]]) -> Dict[str, Any]:
        """分析功能相似性"""
        try:
            kg = self.kg_manager.knowledge_graph
            
            if query_structure_id not in kg.structure_features:
                return {"error": "查询结构无特征数据"}
            
            # 获取查询结构的蛋白质特征
            query_feature = kg.structure_features[query_structure_id]
            
            # 提取功能特征
            query_func_features = {}
            for key, value in query_feature.features.items():
                if key.startswith('protein_func_') or key.startswith('protein_family_'):
                    query_func_features[key] = value
            
            # 分析每个相似结构的功能相似性
            functional_similarities = []
            
            for struct in similar_structures[:10]:  # 只分析前10个
                struct_id = struct.get("structure_id")
                if struct_id in kg.structure_features:
                    target_feature = kg.structure_features[struct_id]
                    
                    # 提取目标结构的功能特征
                    target_func_features = {}
                    for key, value in target_feature.features.items():
                        if key.startswith('protein_func_') or key.startswith('protein_family_'):
                            target_func_features[key] = value
                    
                    # 计算功能相似度
                    if query_func_features and target_func_features:
                        # 获取共同特征
                        common_features = set(query_func_features.keys()) & set(target_func_features.keys())
                        
                        if common_features:
                            # 计算加权相似度
                            total_weight = 0
                            weighted_sum = 0
                            
                            for feature in common_features:
                                query_val = query_func_features[feature]
                                target_val = target_func_features[feature]
                                
                                # 特征权重：功能特征权重更高
                                if 'func_' in feature:
                                    weight = 1.5
                                else:  # family特征
                                    weight = 1.0
                                
                                similarity = 1.0 - abs(query_val - target_val)
                                weighted_sum += similarity * weight
                                total_weight += weight
                            
                            if total_weight > 0:
                                functional_similarity = weighted_sum / total_weight
                                
                                # 提取共同的功能特征
                                common_func_features = []
                                for feature in common_features:
                                    if query_func_features[feature] > 0.5 and target_func_features[feature] > 0.5:
                                        feature_name = feature.replace('protein_func_', '').replace('protein_family_', '')
                                        common_func_features.append(feature_name)
                                
                                functional_similarities.append({
                                    "structure_id": struct_id,
                                    "functional_similarity": functional_similarity,
                                    "common_features": common_func_features[:5],  # 只显示前5个
                                    "has_protein_features": len(target_func_features) > 0
                                })
            
            # 按功能相似度排序
            functional_similarities.sort(key=lambda x: x["functional_similarity"], reverse=True)
            
            return {
                "success": True,
                "query_structure": query_structure_id,
                "functional_similarities": functional_similarities,
                "total_analyzed": len(functional_similarities),
                "avg_functional_similarity": sum(s["functional_similarity"] for s in functional_similarities) / len(functional_similarities) if functional_similarities else 0
            }
            
        except Exception as e:
            logger.error(f"功能相似性分析失败: {e}")
            return {"success": False, "error": str(e)}
    
    def get_structure_insights(self, structure_id: str) -> Dict[str, Any]:
        """获取结构洞察（专注靶点信息）"""
        try:
            insights = {}
            
            # 1. 相似结构
            similar = self.kg_manager.search_similar_structures(structure_id, top_k=5)
            if similar.get("success"):
                insights["similar_structures"] = similar
            
            # 2. 邻居网络
            neighborhood = self.kg_manager.get_structure_neighborhood(structure_id, max_depth=2)
            if neighborhood.get("success"):
                insights["neighborhood"] = neighborhood
            
            # 3. 在知识图谱中的位置
            kg = self.kg_manager.knowledge_graph
            if structure_id in kg.nodes:
                node = kg.get_node(structure_id)
                
                # 计算度中心性
                graph = kg.graph
                degree = graph.degree(structure_id)
                
                # 查找连接的文献
                connected_literature = []
                for edge_key, edge in kg.edges.items():
                    if edge.source == structure_id and edge.edge_type == EdgeType.REFERENCES:
                        lit_id = edge.target
                        lit_node = kg.get_node(lit_id)
                        if lit_node:
                            connected_literature.append({
                                "literature_id": lit_id.replace("lit_", ""),
                                "title": lit_node.label,
                                "properties": lit_node.properties
                            })
                
                insights["graph_position"] = {
                    "degree": degree,
                    "node_type": node.node_type.value if node else "unknown",
                    "connected_literature_count": len(connected_literature),
                    "connected_literature": connected_literature[:5]  # 只显示前5个
                }
            
            # 4. UniProt信息（如果可用）
            protein_info = None
            if HAS_UNIPROT and self.uniprot_client:
                # 检查是否是PDB ID
                if not structure_id.startswith('EMD') and len(structure_id) == 4 and structure_id[0].isdigit():
                    try:
                        entries = self.uniprot_client.get_by_pdb_id(structure_id)
                        if entries:
                            entry = entries[0]
                            protein_info = {
                                "uniprot_id": entry.uniprot_id,
                                "protein_name": entry.protein_name,
                                "gene_names": entry.gene_names,
                                "organism": entry.organism,
                                "function": getattr(entry, 'function', '')[:300] + '...' if hasattr(entry, 'function') else '',
                                "subcellular_locations": getattr(entry, 'subcellular_locations', []),
                                "has_protein_info": True
                            }
                    except Exception as e:
                        logger.debug(f"获取UniProt信息失败 {structure_id}: {e}")
            
            insights["protein_info"] = protein_info
            
            # 5. 结构特征信息
            if structure_id in kg.structure_features:
                feature = kg.structure_features[structure_id]
                feature_summary = {
                    "has_protein_features": feature.features.get("has_protein_info", 0) > 0.5,
                    "protein_families": []
                }
                
                # 提取蛋白质家族
                for family in kg.family_classifier.protein_family_patterns.keys():
                    if feature.features.get(f"family_{family}", 0) > 0.5:
                        feature_summary["protein_families"].append(family)
                
                # 从蛋白质特征提取家族
                for key in feature.features:
                    if key.startswith('protein_family_') and feature.features[key] > 0.5:
                        family = key.replace('protein_family_', '')
                        if family not in feature_summary["protein_families"]:
                            feature_summary["protein_families"].append(family)
                
                insights["feature_summary"] = feature_summary
            
            return {
                "success": True,
                "structure_id": structure_id,
                "insights": insights,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "analysis_type": "target_focused"
            }
            
        except Exception as e:
            logger.error(f"获取结构洞察失败: {e}")
            return {"success": False, "error": str(e)}
    
    def analyze_target_focused(self) -> Dict[str, Any]:
        """靶点专注分析"""
        try:
            # 1. 获取蛋白质统计
            protein_stats = self.get_protein_statistics()
            
            # 2. 靶点专注聚类
            target_clusters = self.kg_manager.discover_structural_clusters_target_focused(n_clusters=5)
            
            # 3. 比较聚类方法
            comparison = self.kg_manager.compare_clustering_methods(n_clusters=5)
            
            # 4. 分析蛋白质信息覆盖率
            coverage_report = self._get_protein_info_coverage_report()
            
            return {
                "success": True,
                "protein_statistics": protein_stats,
                "target_focused_clustering": target_clusters,
                "method_comparison": comparison,
                "coverage_report": coverage_report,
                "summary": {
                    "has_protein_data": protein_stats.get("success", False) and 
                                      protein_stats.get("protein_info_coverage", 0) > 0.1,
                    "recommended_method": comparison.get("summary", {}).get("recommendation", "未知"),
                    "target_cluster_count": len(target_clusters.get("clusters", [])),
                    "protein_info_coverage_percentage": coverage_report.get("coverage_percentage", 0)
                }
            }
            
        except Exception as e:
            logger.error(f"靶点专注分析失败: {e}")
            return {"success": False, "error": str(e)}
    
    def get_protein_statistics(self) -> Dict[str, Any]:
        """获取蛋白质统计信息"""
        try:
            kg = self.kg_manager.knowledge_graph
            
            if not hasattr(kg, 'structure_features') or not kg.structure_features:
                return {"error": "没有结构特征数据"}
            
            # 统计蛋白质信息覆盖率
            total_structures = len(kg.structure_features)
            structures_with_protein_info = 0
            protein_feature_counts = Counter()
            
            for struct_id, feature in kg.structure_features.items():
                if feature.features.get("has_protein_info", 0) > 0.5:
                    structures_with_protein_info += 1
                    
                    # 统计蛋白质特征类型
                    for key in feature.features:
                        if key.startswith('protein_'):
                            protein_feature_counts[key] += 1
            
            # 统计蛋白质家族分布
            family_distribution = Counter()
            for struct_id, feature in kg.structure_features.items():
                families = []
                
                # 基础家族
                for family in kg.family_classifier.protein_family_patterns.keys():
                    if feature.features.get(f"family_{family}", 0) > 0.5:
                        families.append(family)
                
                # 蛋白质特征中的家族
                for key in feature.features:
                    if key.startswith('protein_family_') and feature.features[key] > 0.5:
                        family = key.replace('protein_family_', '')
                        if family not in families:
                            families.append(family)
                
                if families:
                    family_distribution[",".join(sorted(families))] += 1
                else:
                    family_distribution["unknown"] += 1
            
            return {
                "success": True,
                "total_structures": total_structures,
                "structures_with_protein_info": structures_with_protein_info,
                "protein_info_coverage": structures_with_protein_info / total_structures if total_structures > 0 else 0,
                "protein_feature_counts": dict(protein_feature_counts),
                "family_distribution": dict(family_distribution),
                "has_uniprot_client": HAS_UNIPROT
            }
            
        except Exception as e:
            logger.error(f"获取蛋白质统计失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _get_protein_info_coverage_report(self) -> Dict[str, Any]:
        """获取蛋白质信息覆盖率报告"""
        try:
            kg = self.kg_manager.knowledge_graph
            
            if not hasattr(kg, 'get_protein_info_coverage_report'):
                # 如果知识图谱没有这个方法，手动计算
                return self.get_protein_statistics()
            
            return kg.get_protein_info_coverage_report()
            
        except Exception as e:
            logger.error(f"获取蛋白质信息覆盖率报告失败: {e}")
            return {"error": str(e)}
    
    def export_kg_data(self, format: str = "json", include_protein_info: bool = True) -> Dict[str, Any]:
        """导出知识图谱数据（可选包含蛋白质信息）"""
        try:
            if format == "json":
                # 导出为可视化格式
                export_result = self.kg_manager.export_for_visualization()
                
                if export_result.get("success"):
                    data = export_result.get("visualization_data", {})
                    
                    # 如果包含蛋白质信息，添加相关信息
                    if include_protein_info:
                        # 添加蛋白质统计
                        protein_stats = self.get_protein_statistics()
                        if protein_stats.get("success"):
                            data["protein_statistics"] = protein_stats
                        
                        # 在节点数据中添加蛋白质信息
                        for node in data.get("nodes", []):
                            if node["type"] == "structure":
                                struct_id = node["id"]
                                if struct_id in kg.structure_features:
                                    feature = kg.structure_features[struct_id]
                                    node["properties"]["has_protein_info"] = feature.features.get("has_protein_info", 0) > 0.5
                    
                    return {
                        "success": True,
                        "format": format,
                        "data": data,
                        "include_protein_info": include_protein_info,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                else:
                    return export_result
            
            elif format == "graphml":
                # 导出为GraphML格式
                try:
                    kg = self.kg_manager.knowledge_graph
                    graph = kg.graph
                    
                    filename = f"structure_kg_{time.strftime('%Y%m%d_%H%M%S')}.graphml"
                    filepath = f"structure_knowledge_graphs/{filename}"
                    
                    # 确保目录存在
                    Path("structure_knowledge_graphs").mkdir(parents=True, exist_ok=True)
                    
                    # 导出图
                    nx.write_graphml(graph, filepath)
                    
                    # 如果包含蛋白质信息，创建元数据文件
                    if include_protein_info:
                        metadata = {
                            "export_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "format": "graphml",
                            "include_protein_info": include_protein_info,
                            "protein_statistics": self.get_protein_statistics(),
                            "graph_info": {
                                "nodes": len(graph.nodes()),
                                "edges": len(graph.edges()),
                                "has_uniprot": HAS_UNIPROT
                            }
                        }
                        
                        metadata_file = f"structure_knowledge_graphs/{filename.replace('.graphml', '_metadata.json')}"
                        with open(metadata_file, 'w', encoding='utf-8') as f:
                            json.dump(metadata, f, indent=2, ensure_ascii=False)
                    
                    return {
                        "success": True,
                        "format": format,
                        "filepath": filepath,
                        "filename": filename,
                        "metadata_file": metadata_file if include_protein_info else None,
                        "message": "知识图谱已导出为GraphML格式"
                    }
                except Exception as e:
                    return {"success": False, "error": f"GraphML导出失败: {str(e)}"}
            
            else:
                return {
                    "success": False,
                    "error": f"不支持的格式: {format}",
                    "supported_formats": ["json", "graphml"]
                }
                
        except Exception as e:
            logger.error(f"导出知识图谱数据失败: {e}")
            return {"success": False, "error": str(e)}

# ---------- API接口 ----------
class StructureKGAPI:
    """结构知识图谱API接口（专注靶点信息）"""
    
    def __init__(self):
        self.integration = StructureKGIntegration()
    
    def build_knowledge_graph(self) -> Dict[str, Any]:
        """构建知识图谱（专注靶点信息）"""
        return self.integration.build_kg_from_literature()
    
    def analyze_network(self) -> Dict[str, Any]:
        """分析结构网络（专注靶点信息）"""
        return self.integration.analyze_structure_network()
    
    def search_similar(self, 
                      query: str, 
                      top_k: int = 10) -> Dict[str, Any]:
        """搜索相似结构（专注靶点信息）"""
        return self.integration.search_similar_structures_advanced(
            query, top_k
        )
    
    def get_insights(self, structure_id: str) -> Dict[str, Any]:
        """获取结构洞察（专注靶点信息）"""
        return self.integration.get_structure_insights(structure_id)
    
    def get_neighborhood(self, 
                        structure_id: str, 
                        max_depth: int = 2) -> Dict[str, Any]:
        """获取邻居网络"""
        kg_manager = get_kg_manager()
        return kg_manager.get_structure_neighborhood(structure_id, max_depth)
    
    def discover_clusters(self, n_clusters: int = 5) -> Dict[str, Any]:
        """发现结构聚类（专注靶点信息）"""
        kg_manager = get_kg_manager()
        return kg_manager.discover_structural_clusters_target_focused(n_clusters)
    
    def compare_clustering_methods(self, n_clusters: int = 5) -> Dict[str, Any]:
        """比较聚类方法"""
        kg_manager = get_kg_manager()
        return kg_manager.compare_clustering_methods(n_clusters)
    
    def export_data(self, format: str = "json", include_protein_info: bool = True) -> Dict[str, Any]:
        """导出数据（可选包含蛋白质信息）"""
        return self.integration.export_kg_data(format, include_protein_info)
    
    def get_statistics(self, include_protein_info: bool = True) -> Dict[str, Any]:
        """获取统计信息（可选包含蛋白质信息）"""
        kg_manager = get_kg_manager()
        stats = kg_manager.get_graph_statistics()
        
        if include_protein_info:
            protein_stats = self.get_protein_stats()
            if protein_stats.get("success"):
                stats["protein_statistics"] = protein_stats
        
        return stats
    
    def get_protein_stats(self) -> Dict[str, Any]:
        """获取蛋白质统计"""
        return self.integration.get_protein_statistics()
    
    def analyze_target_focused(self) -> Dict[str, Any]:
        """靶点专注分析"""
        return self.integration.analyze_target_focused()
    
    def get_target_focused_capabilities(self) -> Dict[str, Any]:
        """获取靶点专注能力信息"""
        return {
            "target_focused": True,
            "uniprot_integration": HAS_UNIPROT,
            "capabilities": [
                "protein_family_analysis",
                "functional_similarity_calculation", 
                "protein_feature_extraction",
                "target_focused_clustering",
                "protein_info_coverage_analysis"
            ],
            "features_excluded": [
                "method_based_features",
                "resolution_based_features"
            ],
            "primary_features": [
                "protein_families",
                "protein_function",
                "protein_domains",
                "subcellular_locations"
            ]
        }

# ---------- 全局实例 ----------
_kg_api_instance = None

def get_kg_api() -> StructureKGAPI:
    """获取知识图谱API实例"""
    global _kg_api_instance
    
    if _kg_api_instance is None:
        _kg_api_instance = StructureKGAPI()
    
    return _kg_api_instance

# ---------- 使用示例 ----------
if __name__ == "__main__":
    # 测试靶点专注功能
    import logging
    logging.basicConfig(level=logging.INFO)
    
    api = get_kg_api()
    
    # 获取靶点专注能力信息
    capabilities = api.get_target_focused_capabilities()
    print(f"靶点专注能力: {capabilities}")
    
    if capabilities["target_focused"]:
        # 测试靶点专注分析
        print("\n测试靶点专注分析...")
        analysis = api.analyze_target_focused()
        if analysis.get("success"):
            print(f"  分析成功: {analysis.get('summary', {}).get('protein_info_coverage_percentage', 0):.1f}% 蛋白质信息覆盖率")
        
        # 测试蛋白质统计
        print("\n测试蛋白质统计...")
        stats = api.get_protein_stats()
        if stats.get("success"):
            print(f"  蛋白质信息覆盖率: {stats.get('protein_info_coverage', 0)*100:.1f}%")
            print(f"  有蛋白质信息的结构: {stats.get('structures_with_protein_info', 0)}/{stats.get('total_structures', 0)}")
        
        # 测试靶点专注聚类
        print("\n测试靶点专注聚类...")
        clusters = api.discover_clusters(n_clusters=3)
        if clusters.get("success"):
            print(f"  发现 {len(clusters.get('clusters', []))} 个聚类")
            for cluster in clusters.get("clusters", [])[:2]:
                print(f"  聚类 {cluster.get('cluster_id')}: {cluster.get('size')} 个结构, 蛋白质信息覆盖率: {cluster.get('protein_coverage', 0)*100:.1f}%")
    
    # 测试蛋白质名称搜索
    print("\n测试蛋白质名称搜索...")
    search_result = api.search_similar("GPR158 protein structure")
    if search_result.get("success"):
        print(f"  搜索成功，找到 {search_result.get('search_summary', {}).get('similar_count', 0)} 个相似结构")
        print(f"  检测到的蛋白质: {search_result.get('detected_protein_names', [])}")
    
    # 测试比较聚类方法
    print("\n测试聚类方法比较...")
    comparison = api.compare_clustering_methods(n_clusters=3)
    if comparison.get("success"):
        summary = comparison.get("summary", {})
        print(f"  靶点专注聚类: {summary.get('target_focused_clusters', 0)} 个聚类")
        print(f"  蛋白质家族聚类: {summary.get('protein_family_clusters', 0)} 个聚类")
        print(f"  推荐: {summary.get('recommendation', '未知')}")