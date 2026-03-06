# structure_kg_manager.py - 结构知识图谱管理器（专注靶点信息）
import logging, json, time
from pathlib import Path  # 添加这行
from typing import Dict, List, Any, Optional
from collections import defaultdict, Counter
import numpy as np

from core.structure_knowledge_graph import (
    StructureKnowledgeGraph, GraphNode, GraphEdge,
    NodeType, EdgeType
)

logger = logging.getLogger(__name__)

# 尝试导入UniProt模块
try:
    from core.uniprot_client import (
        UniProtAPIClient, UniProtNormalizer
    )
    HAS_UNIPROT = True
except ImportError:
    HAS_UNIPROT = False

class StructureKnowledgeGraphManager:
    """结构知识图谱管理器（专注靶点信息）"""
    
    def __init__(self):
        self.knowledge_graph = StructureKnowledgeGraph("cryoagent_structure_kg_target_focused")
        self.initialized = False
        
        logger.info("✅ 结构知识图谱管理器初始化（专注靶点信息）")
    
    def build_from_literature_data(self, 
                                   literature_data: List[Dict[str, Any]],
                                   structure_metadata: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """从文献数据构建知识图谱 - 专注靶点信息"""
        logger.info("开始构建结构知识图谱（专注靶点信息）...")
        start_time = time.time()
        
        try:
            # 1. 收集结构-文献映射（只收集PDB ID）
            literature_structures = {}
            structure_literatures = defaultdict(list)
            
            for lit_data in literature_data:
                lit_id = str(lit_data.get("id", ""))
                if not lit_id:
                    continue
                
                # 创建文献节点
                lit_node = GraphNode(
                    id=f"lit_{lit_id}",
                    node_type=NodeType.LITERATURE,
                    label=lit_data.get("title", f"Literature {lit_id}")[:100],
                    properties={
                        "title": lit_data.get("title", ""),
                        "year": lit_data.get("year"),
                        "journal": lit_data.get("journal", ""),
                        "authors": lit_data.get("authors", ""),
                        "abstract": (lit_data.get("abstract", "")[:200] + "...") if lit_data.get("abstract") else ""
                    }
                )
                self.knowledge_graph.add_node(lit_node)
                
                # 提取结构ID - 只提取PDB ID
                structure_ids = []
                
                # 从cryoem_targets字段提取
                cryo_targets = lit_data.get("cryoem_targets", {})
                if isinstance(cryo_targets, str):
                    try:
                        cryo_targets = json.loads(cryo_targets)
                    except:
                        cryo_targets = {}
                
                if isinstance(cryo_targets, dict):
                    # 只提取PDB ID
                    pdb_ids = cryo_targets.get("pdb_ids", [])
                    
                    # 过滤出有效的PDB ID（4字符，第一个为数字）
                    valid_pdb_ids = []
                    for pdb_id in pdb_ids:
                        if pdb_id and isinstance(pdb_id, str):
                            pdb_id_clean = pdb_id.strip().upper()
                            if len(pdb_id_clean) == 4 and pdb_id_clean[0].isdigit() and pdb_id_clean.isalnum():
                                valid_pdb_ids.append(pdb_id_clean)
                    
                    structure_ids.extend(valid_pdb_ids)
                
                if structure_ids:
                    literature_structures[lit_id] = structure_ids
                    
                    # 创建结构节点和关系
                    for struct_id in structure_ids:
                        # 添加结构节点（如果不存在）
                        if struct_id not in self.knowledge_graph.nodes:
                            struct_label = struct_id
                            struct_properties = {}
                            
                            # 尝试从元数据中获取更多信息
                            if struct_id in structure_metadata:
                                meta = structure_metadata[struct_id]
                                struct_label = meta.get("title", meta.get("id", struct_id))
                                if not struct_label or not isinstance(struct_label, str):
                                    struct_label = struct_id
                                    
                                struct_properties = {
                                    "resolution": meta.get("resolution"),
                                    "method": meta.get("experimental_method", ""),
                                    "release_date": meta.get("release_date", ""),
                                    "organism": meta.get("organism", ""),
                                    "protein_name": meta.get("protein_name", "")
                                }
                            
                            struct_node = GraphNode(
                                id=struct_id,
                                node_type=NodeType.STRUCTURE,
                                label=str(struct_label)[:100],
                                properties=struct_properties
                            )
                            self.knowledge_graph.add_node(struct_node)
                        
                        # 记录文献-结构关系
                        structure_literatures[struct_id].append(lit_id)
                        
                        # 添加文献-结构边
                        contains_edge = GraphEdge(
                            source=f"lit_{lit_id}",
                            target=struct_id,
                            edge_type=EdgeType.CONTAINS,
                            weight=1.0,
                            properties={"source": "literature_parsing"}
                        )
                        self.knowledge_graph.add_edge(contains_edge)
                        
                        # 添加结构-文献边
                        references_edge = GraphEdge(
                            source=struct_id,
                            target=f"lit_{lit_id}",
                            edge_type=EdgeType.REFERENCES,
                            weight=1.0,
                            properties={"source": "literature_parsing"}
                        )
                        self.knowledge_graph.add_edge(references_edge)
            
            logger.info(f"处理了 {len(literature_structures)} 篇文献，包含 {sum(len(s) for s in literature_structures.values())} 个结构关系")
            
            # 2. 计算结构共现关系（只考虑PDB）
            self.knowledge_graph.compute_structure_co_occurrence(literature_structures)
            
            # 3. 提取结构特征（专注靶点信息）
            # 清理结构元数据，确保值不为None
            cleaned_structure_metadata = {}
            for struct_id, meta in structure_metadata.items():
                if meta and isinstance(meta, dict):
                    # 确保所有值都是字符串或数字，不是None
                    cleaned_meta = {}
                    for key, value in meta.items():
                        if value is None:
                            cleaned_meta[key] = ""
                        elif isinstance(value, (str, int, float)):
                            cleaned_meta[key] = value
                        else:
                            cleaned_meta[key] = str(value)
                    cleaned_structure_metadata[struct_id] = cleaned_meta
            
            self.knowledge_graph.extract_structure_features_target_focused(cleaned_structure_metadata)
            
            # 4. 计算结构相似性（基于靶点信息）
            self.knowledge_graph.compute_structure_similarity_target_focused(similarity_threshold=0.6)
            
            # 5. 分析蛋白质家族分布
            family_analysis = self._analyze_structure_families()
            
            # 6. 保存图谱
            save_path = self.knowledge_graph.save_graph()
            
            elapsed = time.time() - start_time
            stats = self.knowledge_graph.get_graph_statistics()
            
            # 添加蛋白质家族分析到统计中
            stats["protein_family_analysis"] = family_analysis
            
            logger.info(f"✅ 结构知识图谱构建完成 ({elapsed:.2f}秒)")
            
            return {
                "success": True,
                "elapsed_time": elapsed,
                "save_path": save_path,
                "statistics": stats,
                "literature_count": len(literature_data),
                "structure_count": len(structure_metadata),
                "pdb_count": len([sid for sid in structure_metadata.keys() 
                                  if len(sid) == 4 and sid[0].isdigit()]),
                "protein_family_analysis": family_analysis,
                "literature_structures": {
                    "literature_with_structures": len(literature_structures),
                    "total_relationships": sum(len(structs) for structs in literature_structures.values())
                }
            }
            
        except Exception as e:
            logger.error(f"构建知识图谱失败: {e}", exc_info=True)
            elapsed = time.time() - start_time
            return {
                "success": False,
                "error": str(e),
                "elapsed_time": elapsed
            }
    
    def _analyze_structure_families(self) -> Dict[str, Any]:
        """分析结构蛋白质家族"""
        logger.info("分析结构蛋白质家族（专注靶点信息）...")
        
        # 收集所有结构的家族信息
        structure_families = {}
        family_structures = defaultdict(list)
        protein_info_coverage = 0
        
        for struct_id, feature in self.knowledge_graph.structure_features.items():
            families = []
            
            # 从基础特征提取
            for family in self.knowledge_graph.family_classifier.protein_family_patterns.keys():
                if feature.features.get(f"family_{family}", 0) > 0.5:
                    families.append(family)
            
            # 从蛋白质特征提取
            for key in feature.features:
                if key.startswith('protein_family_') and feature.features[key] > 0.5:
                    family = key.replace('protein_family_', '')
                    if family not in families:
                        families.append(family)
            
            if not families:
                families = ["unknown"]
            
            structure_families[struct_id] = families
            
            for family in families:
                family_structures[family].append(struct_id)
            
            # 统计蛋白质信息覆盖率
            if feature.features.get("has_protein_info", 0) > 0.5:
                protein_info_coverage += 1
        
        # 计算家族统计
        family_counts = Counter()
        for families in structure_families.values():
            for family in families:
                family_counts[family] += 1
        
        # 计算家族之间的相似度（基于蛋白质特征）
        family_similarities = {}
        if family_counts:
            for family1 in family_counts.keys():
                for family2 in family_counts.keys():
                    if family1 < family2:  # 避免重复
                        # 获取两个家族的结构特征
                        family1_vectors = []
                        family2_vectors = []
                        
                        for struct_id in family_structures.get(family1, []):
                            if struct_id in self.knowledge_graph.structure_features:
                                feature = self.knowledge_graph.structure_features[struct_id]
                                vector = feature.to_vector(self.knowledge_graph.feature_names)
                                family1_vectors.append(vector)
                        
                        for struct_id in family_structures.get(family2, []):
                            if struct_id in self.knowledge_graph.structure_features:
                                feature = self.knowledge_graph.structure_features[struct_id]
                                vector = feature.to_vector(self.knowledge_graph.feature_names)
                                family2_vectors.append(vector)
                        
                        if family1_vectors and family2_vectors:
                            try:
                                # 将列表转换为numpy数组
                                family1_matrix = np.vstack(family1_vectors)
                                family2_matrix = np.vstack(family2_vectors)
                                
                                # 计算相似度矩阵
                                from sklearn.metrics.pairwise import cosine_similarity
                                similarity_matrix = cosine_similarity(family1_matrix, family2_matrix)
                                avg_similarity = np.mean(similarity_matrix)
                                family_similarities[f"{family1}_{family2}"] = float(avg_similarity)
                            except Exception as e:
                                logger.debug(f"计算家族 {family1} 和 {family2} 相似度失败: {e}")
                                family_similarities[f"{family1}_{family2}"] = 0.0
        
        return {
            "structure_families": structure_families,
            "family_structures": dict(family_structures),
            "family_counts": dict(family_counts),
            "family_similarities": family_similarities,
            "total_structures": len(structure_families),
            "unique_families": len(family_counts),
            "protein_info_coverage": protein_info_coverage,
            "protein_info_coverage_percentage": protein_info_coverage / len(structure_families) * 100 if structure_families else 0
        }
    
    def analyze_cross_literature_associations(self) -> Dict[str, Any]:
        """分析跨文献关联"""
        logger.info("分析跨文献结构关联...")
        start_time = time.time()
        
        try:
            analysis_result = self._analyze_structure_families()
            elapsed = time.time() - start_time
            
            return {
                "success": True,
                "elapsed_time": elapsed,
                "analysis": analysis_result
            }
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"跨文献关联分析失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "elapsed_time": elapsed
            }
    
    def search_similar_structures(self, 
                                 query_structure_id: str, 
                                 top_k: int = 10,
                                 include_features: bool = False) -> Dict[str, Any]:
        """搜索相似结构（专注靶点信息）"""
        logger.info(f"搜索与 {query_structure_id} 相似的结构（专注靶点信息）...")
        start_time = time.time()
        
        try:
            similar_structures = self.knowledge_graph.search_similar_structures_target_focused(
                query_structure_id, 
                top_k=top_k,
                min_similarity=0.5
            )
            elapsed = time.time() - start_time
            
            # 获取查询结构的蛋白质家族
            query_families = []
            if query_structure_id in self.knowledge_graph.structure_features:
                feature = self.knowledge_graph.structure_features[query_structure_id]
                for family in self.knowledge_graph.family_classifier.protein_family_patterns.keys():
                    if feature.features.get(f"family_{family}", 0) > 0.5:
                        query_families.append(family)
            
            # 格式化结果
            formatted_results = []
            for result in similar_structures:
                formatted = {
                    "structure_id": result["structure_id"],
                    "similarity_score": result["similarity_score"],
                    "protein_similarity": result["protein_similarity"],
                    "label": result["label"],
                    "protein_families": result["protein_families"],
                    "common_families": result["common_families"],
                    "has_protein_info": result["has_protein_info"],
                    "shared_protein_features": result["shared_protein_features"]
                }
                
                if include_features and result["structure_id"] in self.knowledge_graph.structure_features:
                    formatted["features"] = self.knowledge_graph.structure_features[result["structure_id"]].features
                
                formatted_results.append(formatted)
            
            return {
                "success": True,
                "query_structure": query_structure_id,
                "query_families": query_families,
                "elapsed_time": elapsed,
                "similar_structures": formatted_results,
                "total_found": len(formatted_results),
                "feature_type": "target_focused"
            }
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"相似结构搜索失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "elapsed_time": elapsed
            }
    
    def discover_structural_clusters(self, n_clusters: int = 5) -> Dict[str, Any]:
        """发现结构聚类（专注靶点信息）"""
        return self.discover_structural_clusters_target_focused(n_clusters=n_clusters)
    
    def discover_structural_clusters_target_focused(self, n_clusters: int = 5) -> Dict[str, Any]:
        """发现结构聚类（专注靶点信息）"""
        logger.info(f"发现结构聚类 (k={n_clusters}, 专注靶点信息)...")
        start_time = time.time()
        
        try:
            clusters_result = self.knowledge_graph.find_structural_clusters_target_focused(
                n_clusters=n_clusters
            )
            elapsed = time.time() - start_time
            
            # 如果蛋白质信息覆盖率低，给出警告
            if clusters_result.get("statistics", {}).get("avg_protein_coverage", 0) < 0.3:
                clusters_result["warning"] = "蛋白质信息覆盖率较低，建议补充UniProt数据"
            
            return {
                "success": True,
                "elapsed_time": elapsed,
                "feature_type": "target_focused",
                "clusters": clusters_result.get("clusters", []),
                "visualization": clusters_result.get("visualization"),
                "statistics": clusters_result.get("statistics", {}),
                "error": clusters_result.get("error")
            }
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"结构聚类发现失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "elapsed_time": elapsed
            }
    
    def get_structure_neighborhood(self, 
                                  structure_id: str, 
                                  max_depth: int = 2) -> Dict[str, Any]:
        """获取结构的邻居网络"""
        logger.info(f"获取结构 {structure_id} 的邻居网络 (深度={max_depth})...")
        start_time = time.time()
        
        try:
            if structure_id not in self.knowledge_graph.nodes:
                return {
                    "success": False,
                    "error": f"结构 {structure_id} 不存在"
                }
            
            # 导入networkx
            import networkx as nx
            
            # 获取子图
            neighbors = nx.single_source_shortest_path_length(
                self.knowledge_graph.graph, 
                structure_id, 
                cutoff=max_depth
            )
            
            # 创建子图
            subgraph_nodes = set(neighbors.keys())
            subgraph = self.knowledge_graph.graph.subgraph(subgraph_nodes)
            
            # 转换为可视化格式
            nodes_list = []
            for node_id in subgraph_nodes:
                node = self.knowledge_graph.get_node(node_id)
                if node:
                    # 获取蛋白质家族信息
                    protein_families = []
                    if node_id in self.knowledge_graph.structure_features:
                        feature = self.knowledge_graph.structure_features[node_id]
                        for family in self.knowledge_graph.family_classifier.protein_family_patterns.keys():
                            if feature.features.get(f"family_{family}", 0) > 0.5:
                                protein_families.append(family)
                    
                    node_dict = {
                        "id": node.id,
                        "label": node.label,
                        "type": node.node_type.value,
                        "distance": neighbors.get(node_id, 0),
                        "properties": node.properties
                    }
                    
                    if protein_families:
                        node_dict["protein_families"] = protein_families
                    
                    nodes_list.append(node_dict)
            
            edges_list = []
            for source, target, edge_data in subgraph.edges(data=True):
                edges_list.append({
                    "source": source,
                    "target": target,
                    "type": edge_data.get("type", ""),
                    "weight": edge_data.get("weight", 1.0)
                })
            
            elapsed = time.time() - start_time
            
            return {
                "success": True,
                "elapsed_time": elapsed,
                "query_structure": structure_id,
                "max_depth": max_depth,
                "neighborhood": {
                    "nodes": nodes_list,
                    "edges": edges_list,
                    "node_count": len(nodes_list),
                    "edge_count": len(edges_list)
                },
                "statistics": {
                    "direct_neighbors": len(list(subgraph.neighbors(structure_id))),
                    "total_reachable": len(subgraph_nodes) - 1,
                    "graph_density": nx.density(subgraph) if len(subgraph_nodes) > 1 else 0
                }
            }
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"获取邻居网络失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "elapsed_time": elapsed
            }
    
    def find_bridge_structures(self) -> Dict[str, Any]:
        """查找桥接结构"""
        logger.info("查找桥接结构...")
        start_time = time.time()
        
        try:
            # 分析跨文献关联
            analysis = self.analyze_cross_literature_associations()
            if not analysis.get("success"):
                return analysis
            
            # 查找连接多篇文献的结构
            bridge_structures = []
            for struct_id, literature_ids in analysis.get("analysis", {}).get("structure_literatures", {}).items():
                if len(literature_ids) > 1:
                    node = self.knowledge_graph.get_node(struct_id)
                    if node:
                        bridge_structures.append({
                            "structure_id": struct_id,
                            "structure_label": node.label,
                            "literature_count": len(literature_ids),
                            "literature_ids": list(literature_ids)[:5]
                        })
            
            # 排序并筛选
            significant_bridges = [
                bridge for bridge in bridge_structures 
                if bridge.get("literature_count", 0) >= 2
            ]
            
            significant_bridges.sort(key=lambda x: x["literature_count"], reverse=True)
            
            elapsed = time.time() - start_time
            
            return {
                "success": True,
                "elapsed_time": elapsed,
                "bridge_structures": significant_bridges[:20],  # 只显示前20个
                "total_found": len(significant_bridges),
                "statistics": {
                    "avg_literature_count": sum(b.get("literature_count", 0) for b in significant_bridges) / len(significant_bridges) if significant_bridges else 0,
                    "max_literature_count": max((b.get("literature_count", 0) for b in significant_bridges), default=0)
                }
            }
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"查找桥接结构失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "elapsed_time": elapsed
            }
    
    def export_for_visualization(self) -> Dict[str, Any]:
        """导出用于可视化的数据"""
        logger.info("导出知识图谱可视化数据...")
        start_time = time.time()
        
        try:
            export_data = self.knowledge_graph.export_for_visualization()
            elapsed = time.time() - start_time
            
            return {
                "success": True,
                "elapsed_time": elapsed,
                "visualization_data": export_data
            }
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"导出可视化数据失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "elapsed_time": elapsed
            }
    
    def get_graph_statistics(self) -> Dict[str, Any]:
        """获取图谱统计信息"""
        return self.knowledge_graph.get_graph_statistics()
    
    def get_protein_statistics(self) -> Dict[str, Any]:
        """获取蛋白质统计信息"""
        try:
            kg = self.knowledge_graph
            
            if not hasattr(kg, 'structure_features') or not kg.structure_features:
                return {"error": "没有结构特征数据"}
            
            # 统计蛋白质信息覆盖率
            total_structures = len(kg.structure_features)
            structures_with_protein_info = 0
            protein_feature_counts = Counter()
            
            if total_structures > 0:
                # 从特征中统计
                for struct_id, feature in kg.structure_features.items():
                    if feature.features.get("has_protein_info", 0) > 0.5:
                        structures_with_protein_info += 1
                        
                        # 统计蛋白质特征类型
                        for key in feature.features:
                            if key.startswith('protein_'):
                                if key not in protein_feature_counts:
                                    protein_feature_counts[key] = 0
                                protein_feature_counts[key] += 1
            
            # 统计蛋白质家族分布
            family_distribution = {}
            if hasattr(kg, 'family_classifier'):
                # 分析家族分布
                family_counts = Counter()
                for struct_id, feature in kg.structure_features.items():
                    families = []
                    for family in kg.family_classifier.protein_family_patterns.keys():
                        if feature.features.get(f"family_{family}", 0) > 0.5:
                            families.append(family)
                    
                    if families:
                        family_counts[",".join(sorted(families))] += 1
                    else:
                        family_counts["unknown"] += 1
                
                family_distribution = dict(family_counts)
            
            return {
                "success": True,
                "total_structures": total_structures,
                "structures_with_protein_info": structures_with_protein_info,
                "protein_info_coverage": structures_with_protein_info / total_structures if total_structures > 0 else 0,
                "protein_feature_counts": dict(protein_feature_counts),
                "family_distribution": family_distribution,
                "has_uniprot_client": HAS_UNIPROT
            }
            
        except Exception as e:
            logger.error(f"获取蛋白质统计失败: {e}")
            return {"success": False, "error": str(e)}
    
    def compare_clustering_methods(self, n_clusters: int = 5) -> Dict[str, Any]:
        """比较不同聚类方法的效果"""
        logger.info(f"比较聚类方法 (k={n_clusters})...")
        start_time = time.time()
        
        try:
            # 基础聚类（使用所有特征）
            basic_result = self.discover_structural_clusters_target_focused(n_clusters=n_clusters)
            
            # 仅使用蛋白质家族特征聚类
            protein_family_result = self._cluster_by_protein_families(n_clusters=n_clusters)
            
            elapsed = time.time() - start_time
            
            # 计算比较指标
            comparison = {
                "target_focused_clustering": {
                    "success": basic_result.get("success", False),
                    "cluster_count": len(basic_result.get("clusters", [])),
                    "avg_cluster_size": basic_result.get("statistics", {}).get("avg_cluster_size", 0),
                    "avg_protein_coverage": basic_result.get("statistics", {}).get("avg_protein_coverage", 0),
                    "quality_score": self._calculate_clustering_quality(basic_result)
                },
                "protein_family_clustering": {
                    "success": protein_family_result.get("success", False),
                    "cluster_count": len(protein_family_result.get("clusters", [])),
                    "avg_cluster_size": protein_family_result.get("statistics", {}).get("avg_cluster_size", 0),
                    "quality_score": self._calculate_clustering_quality(protein_family_result)
                }
            }
            
            # 判断哪种方法更好
            if (basic_result.get("success") and protein_family_result.get("success") and
                comparison["target_focused_clustering"]["quality_score"] > 
                comparison["protein_family_clustering"]["quality_score"]):
                comparison["recommendation"] = "建议使用靶点专注聚类（包含蛋白质功能特征）"
            else:
                comparison["recommendation"] = "建议使用蛋白质家族聚类"
            
            return {
                "success": True,
                "elapsed_time": elapsed,
                "comparison": comparison,
                "summary": {
                    "target_focused_clusters": len(basic_result.get("clusters", [])),
                    "protein_family_clusters": len(protein_family_result.get("clusters", [])),
                    "recommendation": comparison.get("recommendation", "无法确定")
                }
            }
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"聚类方法比较失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "elapsed_time": elapsed
            }
    
    def _cluster_by_protein_families(self, n_clusters: int = 5) -> Dict[str, Any]:
        """仅使用蛋白质家族特征进行聚类"""
        try:
            kg = self.knowledge_graph
            
            if not kg.structure_features or len(kg.structure_features) < 2:
                return {"clusters": [], "visualization": None, "error": "结构特征不足"}
            
            # 构建特征矩阵 - 只使用蛋白质家族特征
            structure_ids = list(kg.structure_features.keys())
            family_features = [name for name in kg.feature_names 
                             if name.startswith('family_')]
            
            if not family_features:
                return {"clusters": [], "visualization": None, "error": "没有蛋白质家族特征"}
            
            feature_vectors = []
            valid_structure_ids = []
            
            for struct_id in structure_ids:
                feature = kg.structure_features[struct_id]
                vector = np.array([feature.features.get(name, 0.0) for name in family_features])
                
                if not np.any(np.isnan(vector)) and not np.any(np.isinf(vector)):
                    feature_vectors.append(vector)
                    valid_structure_ids.append(struct_id)
            
            if len(feature_vectors) < 2:
                return {"clusters": [], "visualization": None, "error": "有效特征向量不足"}
            
            feature_matrix = np.vstack(feature_vectors)
            n_clusters = min(n_clusters, len(feature_vectors))
            
            # 使用K-means聚类
            from sklearn.cluster import KMeans
            
            kmeans = KMeans(n_clusters=n_clusters, random_state=42)
            cluster_labels = kmeans.fit_predict(feature_matrix)
            
            # 统计聚类结果
            clusters = defaultdict(list)
            for struct_id, label in zip(valid_structure_ids, cluster_labels):
                # 获取蛋白质家族
                protein_families = []
                feature = kg.structure_features[struct_id]
                
                for family in kg.family_classifier.protein_family_patterns.keys():
                    if feature.features.get(f"family_{family}", 0) > 0.5:
                        protein_families.append(family)
                
                clusters[label].append({
                    "structure_id": struct_id,
                    "label": kg.nodes[struct_id].label if struct_id in kg.nodes else struct_id,
                    "protein_families": protein_families
                })
            
            # 转换为结果格式
            cluster_results = []
            for cluster_id, members in clusters.items():
                # 计算聚类的主要蛋白质家族
                all_families = []
                for member in members:
                    all_families.extend(member["protein_families"])
                
                family_counts = Counter(all_families)
                primary_families = [family for family, count in family_counts.most_common(3)]
                
                cluster_results.append({
                    "cluster_id": cluster_id,
                    "size": len(members),
                    "primary_families": primary_families,
                    "family_distribution": dict(family_counts),
                    "members": members[:15]
                })
            
            # 按大小排序
            cluster_results.sort(key=lambda x: x["size"], reverse=True)
            
            return {
                "clusters": cluster_results,
                "statistics": {
                    "total_structures": len(valid_structure_ids),
                    "cluster_count": len(cluster_results),
                    "avg_cluster_size": len(valid_structure_ids) / len(cluster_results) if cluster_results else 0,
                    "feature_type": "protein_families_only"
                }
            }
            
        except Exception as e:
            logger.error(f"蛋白质家族聚类失败: {e}")
            return {"clusters": [], "visualization": None, "error": str(e)}
    
    def _calculate_clustering_quality(self, clustering_result: Dict[str, Any]) -> float:
        """计算聚类质量"""
        try:
            clusters = clustering_result.get("clusters", [])
            if len(clusters) < 2:
                return 0.0
            
            # 计算聚类大小分布的质量
            sizes = [cluster.get("size", 0) for cluster in clusters]
            total = sum(sizes)
            
            if total == 0:
                return 0.0
            
            # 计算大小分布的均匀性（越均匀越好）
            avg_size = total / len(clusters)
            variance = sum((size - avg_size) ** 2 for size in sizes) / len(clusters)
            
            # 归一化的质量分数（1 - 变异系数）
            if avg_size > 0:
                cv = (variance ** 0.5) / avg_size
                quality = 1.0 - min(cv, 1.0)  # 限制在0-1之间
            else:
                quality = 0.0
            
            # 考虑家族纯度
            family_purity = 0.0
            for cluster in clusters:
                if cluster.get("size", 0) > 0:
                    primary_families = cluster.get("primary_families", [])
                    if primary_families:
                        # 主要家族占比
                        family_purity += len(primary_families) / len(cluster.get("family_distribution", {}))
            
            if clusters:
                family_purity /= len(clusters)
            
            # 综合质量分数
            final_quality = 0.7 * quality + 0.3 * family_purity
            
            return max(0.0, min(1.0, final_quality))
            
        except Exception as e:
            logger.debug(f"计算聚类质量失败: {e}")
            return 0.0
    
    def save_graph(self) -> str:
        """保存知识图谱"""
        return self.knowledge_graph.save_graph()
    
    def load_graph(self, filename: str) -> bool:
        """加载知识图谱"""
        return self.knowledge_graph.load_graph(filename)

# ---------- 全局实例 ----------
_kg_manager_instance = None

def get_kg_manager() -> StructureKnowledgeGraphManager:
    """获取知识图谱管理器实例"""
    global _kg_manager_instance
    
    if _kg_manager_instance is None:
        _kg_manager_instance = StructureKnowledgeGraphManager()
    
    return _kg_manager_instance

def initialize_structure_kg() -> Dict[str, Any]:
    """初始化结构知识图谱系统"""
    global _kg_manager_instance
    
    start_time = time.time()
    
    try:
        _kg_manager_instance = StructureKnowledgeGraphManager()
        
        elapsed = time.time() - start_time
        
        return {
            "status": "success",
            "message": "结构知识图谱系统初始化完成（专注靶点信息）",
            "initialization_time": elapsed,
            "capabilities": {
                "protein_family_analysis": True,
                "cross_literature_analysis": True,
                "similarity_search": True,
                "structural_clustering": True,
                "neighborhood_analysis": True,
                "bridge_structure_detection": True,
                "graph_visualization": True,
                "uniprot_integration": HAS_UNIPROT,
                "target_focused_analysis": True
            }
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"初始化结构知识图谱系统失败: {e}")
        return {
            "status": "error",
            "message": f"初始化失败: {str(e)}",
            "initialization_time": elapsed
        }