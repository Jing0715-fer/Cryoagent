# structure_integration.py - 结构集成模块（增强版：集成UniProt）
import logging
from typing import Dict, List, Any, Optional
from structure_enhanced_literature import (
    get_enhanced_literature_manager, 
    StructureEnhancedLiteratureManager
)

# 尝试导入UniProt模块
try:
    from core.uniprot_client import (
        UniProtAPIClient, UniProtNormalizer, get_uniprot_client, get_uniprot_normalizer
    )
    HAS_UNIPROT = True
except ImportError:
    HAS_UNIPROT = False

logger = logging.getLogger(__name__)

# ---------- 集成装饰器 ----------
class StructureIntegration:
    """结构集成装饰器 - 增强版：为现有功能添加结构感知和UniProt增强能力"""
    
    def __init__(self, target_object):
        self.target = target_object
        self.enhanced_manager = get_enhanced_literature_manager()
        
        # 尝试获取结构知识图谱API
        try:
            from structure_kg_integration import get_kg_api
            self.kg_api = get_kg_api()
        except ImportError:
            self.kg_api = None
            logger.warning("无法导入结构知识图谱API")
        
        # 初始化UniPro客户端
        self.uniprot_client = None
        self.uniprot_normalizer = None
        if HAS_UNIPROT:
            try:
                self.uniprot_client = get_uniprot_client()
                self.uniprot_normalizer = get_uniprot_normalizer()
                logger.info("✅ UniProt客户端初始化完成")
            except Exception as e:
                logger.warning(f"UniProt客户端初始化失败: {e}")
    
    def enhance_search(self, query: str, **kwargs) -> Dict[str, Any]:
        """增强搜索功能（集成UniProt）"""
        # 首先尝试使用UniProt增强搜索
        if HAS_UNIPROT and self.uniprot_normalizer:
            enhanced_results = self._search_with_uniprot(query, **kwargs)
            if enhanced_results.get('success', False):
                enhanced_results['search_enhancement'] = 'uniprot_enhanced'
                return enhanced_results
        
        # 调用增强搜索
        enhanced_results = self.enhanced_manager.search(query, **kwargs)
        
        # 如果增强搜索没有结果，回退到原始搜索
        if not enhanced_results.get('results') and hasattr(self.target, 'search_literature'):
            original_results = self.target.search_literature(query, **kwargs)
            
            # 合并结果
            if original_results.get('success', False):
                enhanced_results['results'] = original_results.get('results', [])
                enhanced_results['fallback_to_original'] = True
                enhanced_results['original_result_count'] = len(original_results.get('results', []))
        
        return enhanced_results
    
    def _search_with_uniprot(self, query: str, **kwargs) -> Dict[str, Any]:
        """使用UniProt增强搜索"""
        try:
            # 提取蛋白质名称
            protein_names = self.uniprot_normalizer.extract_protein_names_from_text(query)
            
            if not protein_names:
                # 如果没有提取到蛋白质名称，返回空结果
                return {
                    'success': True,
                    'query': query,
                    'results': [],
                    'protein_names': [],
                    'uniprot_enhancement': 'no_protein_detected'
                }
            
            # 标准化蛋白质名称
            normalized_names = []
            for protein_name in protein_names:
                normalized = self.uniprot_normalizer.normalize_protein_name(protein_name)
                normalized_names.extend(normalized)
            
            # 去重
            normalized_names = list(set(normalized_names))
            
            # 对每个标准化名称进行搜索
            all_results = []
            for name in normalized_names:
                # 使用增强管理器搜索
                name_results = self.enhanced_manager.search(name, **kwargs)
                if name_results.get('results'):
                    # 标记这些结果来自哪个蛋白质名称
                    for result in name_results['results']:
                        result['matched_protein_name'] = name
                    all_results.extend(name_results['results'])
            
            # 去重结果（基于文献ID）
            seen_ids = set()
            unique_results = []
            for result in all_results:
                lit_id = result.get('literature_id') or result.get('id')
                if lit_id and lit_id not in seen_ids:
                    seen_ids.add(lit_id)
                    unique_results.append(result)
            
            return {
                'success': True,
                'query': query,
                'protein_names': protein_names,
                'normalized_names': normalized_names,
                'results': unique_results,
                'total_results': len(unique_results),
                'uniprot_enhancement': 'protein_normalization'
            }
            
        except Exception as e:
            logger.error(f"UniProt增强搜索失败: {e}")
            # 返回空结果，让流程继续
            return {
                'success': False,
                'query': query,
                'results': [],
                'error': str(e)
            }
    
    def enhance_qa(self, question: str, **kwargs) -> Dict[str, Any]:
        """增强问答功能（集成UniProt）"""
        # 首先尝试使用UniProt分析问题
        protein_analysis = None
        if HAS_UNIPROT and self.uniprot_normalizer:
            protein_analysis = self._analyze_question_with_uniprot(question)
        
        # 调用增强问答
        enhanced_response = self.enhanced_manager.ask(question, **kwargs)
        
        # 添加UniProt分析结果
        if protein_analysis and protein_analysis.get('success'):
            enhanced_response['protein_analysis'] = protein_analysis
            
            # 如果检测到蛋白质，但增强问答没有结果，尝试使用蛋白质信息重新搜索
            if not enhanced_response.get('answer') or '无法回答' in enhanced_response.get('answer', ''):
                protein_names = protein_analysis.get('protein_names', [])
                if protein_names:
                    # 使用蛋白质名称重新搜索
                    protein_results = self._search_with_proteins(protein_names, question)
                    if protein_results:
                        enhanced_response['protein_based_results'] = protein_results
                        
                        # 构建基于蛋白质的回答
                        protein_answer = self._build_protein_answer(protein_analysis, protein_results)
                        enhanced_response['protein_enhanced_answer'] = protein_answer
        
        # 如果增强问答失败，回退到原始问答
        if not enhanced_response.get('success') and hasattr(self.target, 'ask_question'):
            original_response = self.target.ask_question(question, **kwargs)
            
            # 合并响应
            if original_response.get('success', False):
                enhanced_response.update({
                    'answer': original_response.get('answer', ''),
                    'sources': original_response.get('sources', []),
                    'confidence': original_response.get('confidence', 0),
                    'fallback_to_original': True
                })
        
        return enhanced_response
    
    def _analyze_question_with_uniprot(self, question: str) -> Dict[str, Any]:
        """使用UniProt分析问题"""
        try:
            # 提取蛋白质名称
            protein_names = self.uniprot_normalizer.extract_protein_names_from_text(question)
            
            if not protein_names:
                return {
                    'success': False,
                    'message': '未检测到蛋白质名称'
                }
            
            # 标准化蛋白质名称
            normalized_names = []
            uniprot_matches = []
            
            for protein_name in protein_names:
                normalized = self.uniprot_normalizer.normalize_protein_name(protein_name)
                normalized_names.extend(normalized)
                
                # 查找最佳UniProt匹配
                for name in normalized:
                    match = self.uniprot_normalizer.find_best_uniprot_match(name)
                    if match:
                        uniprot_matches.append({
                            'query_name': name,
                            'uniprot_id': match.get('uniprot_id'),
                            'confidence': match.get('confidence', 0),
                            'protein_name': match.get('protein_name')
                        })
            
            # 去重
            normalized_names = list(set(normalized_names))
            
            return {
                'success': True,
                'original_question': question,
                'protein_names': protein_names,
                'normalized_names': normalized_names,
                'uniprot_matches': uniprot_matches,
                'detected_proteins_count': len(protein_names),
                'normalized_count': len(normalized_names),
                'has_uniprot_matches': len(uniprot_matches) > 0
            }
            
        except Exception as e:
            logger.error(f"UniProt问题分析失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _search_with_proteins(self, protein_names: List[str], original_question: str) -> List[Dict[str, Any]]:
        """使用蛋白质名称搜索相关文献"""
        all_results = []
        
        for protein_name in protein_names:
            # 搜索包含该蛋白质的文献
            search_results = self.enhanced_manager.search(protein_name, limit=5)
            if search_results.get('results'):
                for result in search_results['results']:
                    result['matched_protein'] = protein_name
                    result['relevance_to_question'] = self._calculate_relevance(result, original_question)
                all_results.extend(search_results['results'])
        
        # 按相关性排序
        all_results.sort(key=lambda x: x.get('relevance_to_question', 0), reverse=True)
        
        # 去重
        seen_ids = set()
        unique_results = []
        for result in all_results:
            lit_id = result.get('literature_id') or result.get('id')
            if lit_id and lit_id not in seen_ids:
                seen_ids.add(lit_id)
                unique_results.append(result)
        
        return unique_results[:10]  # 返回前10个结果
    
    def _calculate_relevance(self, result: Dict[str, Any], question: str) -> float:
        """计算结果与问题的相关性"""
        relevance = 0.0
        
        # 检查标题
        title = result.get('title', '').lower()
        question_lower = question.lower()
        
        # 简单关键词匹配
        keywords = question_lower.split()
        for keyword in keywords:
            if len(keyword) > 3 and keyword in title:
                relevance += 0.1
        
        # 如果有结构信息，增加相关性
        if result.get('structure_ids'):
            relevance += 0.2
        
        # 如果有摘要，检查摘要中的关键词
        abstract = result.get('abstract', '').lower()
        if abstract:
            for keyword in keywords:
                if len(keyword) > 3 and keyword in abstract:
                    relevance += 0.05
        
        return min(relevance, 1.0)
    
    def _build_protein_answer(self, protein_analysis: Dict[str, Any], 
                              search_results: List[Dict[str, Any]]) -> str:
        """构建基于蛋白质的答案"""
        answer_parts = []
        
        # 添加蛋白质分析信息
        protein_names = protein_analysis.get('protein_names', [])
        if protein_names:
            answer_parts.append(f"在您的问题中检测到蛋白质: {', '.join(protein_names)}")
        
        uniprot_matches = protein_analysis.get('uniprot_matches', [])
        if uniprot_matches:
            answer_parts.append("\n相关的UniProt信息:")
            for match in uniprot_matches[:3]:  # 只显示前3个
                answer_parts.append(f"- {match.get('query_name')} -> {match.get('protein_name')} (UniProt ID: {match.get('uniprot_id')}, 置信度: {match.get('confidence', 0):.2f})")
        
        # 添加文献结果信息
        if search_results:
            answer_parts.append(f"\n找到 {len(search_results)} 篇相关文献:")
            for i, result in enumerate(search_results[:3]):  # 只显示前3个
                title = result.get('title', '无标题')[:100]
                matched_protein = result.get('matched_protein', '未知')
                answer_parts.append(f"{i+1}. {title} (相关蛋白质: {matched_protein})")
        
        return "\n".join(answer_parts)
    
    def get_enhanced_literature_detail(self, literature_id: str) -> Dict[str, Any]:
        """获取增强的文献详情（集成UniProt）"""
        # 获取原始详情
        original_detail = {}
        if hasattr(self.target, 'get_literature_detail'):
            original_detail = self.target.get_literature_detail(int(literature_id))
        
        # 获取结构增强信息
        enhanced_info = self.enhanced_manager.get_literature_with_structures(literature_id)
        
        # 获取UniProt增强信息（如果有结构）
        uniprot_info = None
        structure_ids = enhanced_info.get('structure_ids', [])
        if structure_ids and HAS_UNIPROT and self.uniprot_client:
            uniprot_info = self._get_uniprot_info_for_structures(structure_ids)
        
        # 合并
        result = {
            'literature_id': literature_id,
            'original_detail': original_detail if original_detail.get('success') else {},
            'enhanced_info': enhanced_info,
            'uniprot_info': uniprot_info,
            'has_structure_info': 'structure_ids' in enhanced_info,
            'structure_count': len(enhanced_info.get('structure_ids', [])),
            'has_uniprot_info': uniprot_info is not None
        }
        
        return result
    
    def _get_uniprot_info_for_structures(self, structure_ids: List[str]) -> Dict[str, Any]:
        """获取结构的UniProt信息"""
        uniprot_results = []
        
        for struct_id in structure_ids:
            if struct_id.startswith('EMD'):
                continue  # 跳过EMDB ID
            
            try:
                # 通过PDB ID查找UniProt条目
                entries = self.uniprot_client.get_by_pdb_id(struct_id)
                if entries:
                    entry = entries[0]
                    uniprot_results.append({
                        'pdb_id': struct_id,
                        'uniprot_id': entry.uniprot_id,
                        'protein_name': entry.protein_name,
                        'gene_names': entry.gene_names,
                        'function': getattr(entry, 'function', '')[:200] + '...' if hasattr(entry, 'function') else ''
                    })
            except Exception as e:
                logger.debug(f"获取UniProt信息失败 {struct_id}: {e}")
        
        return {
            'structures_analyzed': len(structure_ids),
            'uniprot_matches_found': len(uniprot_results),
            'uniprot_results': uniprot_results
        }
    
    def enhance_with_uniprot(self, query: str) -> Dict[str, Any]:
        """使用UniProt增强查询"""
        if not self.kg_api:
            return {"error": "知识图谱API不可用"}
        
        try:
            # 1. 搜索相似结构
            search_result = self.kg_api.search_similar(query, search_type="hybrid", top_k=10)
            
            # 2. 使用UniProt分析
            uniprot_analysis = self.kg_api.analyze_with_uniprot()
            
            # 3. 获取UniProt统计
            uniprot_stats = self.kg_api.get_uniprot_stats()
            
            # 4. 提取蛋白质名称
            protein_names = []
            if HAS_UNIPROT and self.uniprot_normalizer:
                protein_names = self.uniprot_normalizer.extract_protein_names_from_text(query)
            
            return {
                "success": True,
                "query": query,
                "search_results": search_result,
                "uniprot_analysis": uniprot_analysis,
                "uniprot_statistics": uniprot_stats,
                "protein_names": protein_names,
                "enhancement_level": "full" if uniprot_stats.get("success") else "partial"
            }
            
        except Exception as e:
            logger.error(f"UniProt增强查询失败: {e}")
            return {"success": False, "error": str(e)}

# ---------- 全局集成函数 ----------
def integrate_structure_enhancements(original_manager) -> StructureIntegration:
    """为现有管理器集成结构增强功能"""
    return StructureIntegration(original_manager)

def get_enhanced_search(query: str, original_search_func=None, **kwargs) -> Dict[str, Any]:
    """获取增强的搜索结果（集成UniProt）"""
    try:
        enhanced_manager = get_enhanced_literature_manager()
        integration = StructureIntegration(enhanced_manager)
        return integration.enhance_search(query, **kwargs)
    except Exception as e:
        logger.error(f"增强搜索失败，使用原始搜索: {e}")
        if original_search_func:
            return original_search_func(query, **kwargs)
        return {'success': False, 'error': str(e), 'results': []}

def get_enhanced_qa(question: str, original_qa_func=None, **kwargs) -> Dict[str, Any]:
    """获取增强的问答结果（集成UniProt）"""
    try:
        enhanced_manager = get_enhanced_literature_manager()
        integration = StructureIntegration(enhanced_manager)
        return integration.enhance_qa(question, **kwargs)
    except Exception as e:
        logger.error(f"增强问答失败，使用原始问答: {e}")
        if original_qa_func:
            return original_qa_func(question, **kwargs)
        return {'success': False, 'answer': f'抱歉，回答问题失败: {str(e)}', 'sources': []}

def get_uniprot_enhanced_search(query: str, **kwargs) -> Dict[str, Any]:
    """获取UniProt增强的搜索结果"""
    try:
        enhanced_manager = get_enhanced_literature_manager()
        integration = StructureIntegration(enhanced_manager)
        return integration.enhance_with_uniprot(query)
    except Exception as e:
        logger.error(f"UniProt增强搜索失败: {e}")
        return {'success': False, 'error': str(e)}

# ---------- 数据库更新函数 ----------
def update_literature_structure_data(literature_id: int, structure_data: Dict[str, Any]) -> bool:
    """更新文献结构数据到数据库"""
    try:
        from core.literature_db import create_literature_session, update_literature_entry
        
        session = create_literature_session()
        
        # 准备更新数据
        updates = {
            'cryoem_targets': structure_data
        }
        
        success = update_literature_entry(literature_id, updates)
        session.close()
        
        if success:
            # 更新内存中的映射
            enhanced_manager = get_enhanced_literature_manager()
            
            # 提取结构ID
            structure_ids = []
            if isinstance(structure_data, dict):
                structure_ids.extend(structure_data.get('pdb_ids', []))
                structure_ids.extend(structure_data.get('emdb_ids', []))
            
            enhanced_manager.enhanced_indexer.update_structure_mapping(str(literature_id), structure_ids)
            
            logger.info(f"✅ 更新文献 {literature_id} 结构数据: {len(structure_ids)} 个结构")
            
            # 如果有UniProt客户端，尝试获取UniProt信息
            if HAS_UNIPROT:
                try:
                    from core.uniprot_client import get_uniprot_client
                    uniprot_client = get_uniprot_client()
                    
                    # 为PDB结构获取UniProt信息
                    pdb_ids = structure_data.get('pdb_ids', [])
                    for pdb_id in pdb_ids[:5]:  # 只处理前5个，避免过多请求
                        try:
                            entries = uniprot_client.get_by_pdb_id(pdb_id)
                            if entries:
                                logger.info(f"  获取到PDB {pdb_id} 的UniProt信息: {entries[0].uniprot_id}")
                        except Exception as e:
                            logger.debug(f"获取UniProt信息失败 {pdb_id}: {e}")
                except Exception as e:
                    logger.warning(f"UniProt信息获取失败: {e}")
        
        return success
        
    except Exception as e:
        logger.error(f"更新文献结构数据失败: {e}")
        return False

def batch_update_all_structure_data() -> Dict[str, Any]:
    """批量更新所有文献的结构数据"""
    enhanced_manager = get_enhanced_literature_manager()
    return enhanced_manager.batch_update_structure_mappings()

# ---------- API接口 ----------
class StructureEnhancedAPI:
    """结构增强的API接口（集成UniProt）"""
    
    def __init__(self):
        self.enhanced_manager = get_enhanced_literature_manager()
        self.integration = StructureIntegration(self.enhanced_manager)
        
        # 尝试获取知识图谱API
        try:
            from structure_kg_integration import get_kg_api
            self.kg_api = get_kg_api()
        except ImportError:
            self.kg_api = None
    
    def search(self, query: str, search_type: str = "auto", 
               limit: int = 10, use_uniprot: bool = True) -> Dict[str, Any]:
        """搜索接口（可选使用UniProt）"""
        if use_uniprot:
            return self.integration.enhance_search(query, search_type=search_type, top_k=limit)
        else:
            return self.enhanced_manager.search(query, search_type=search_type, top_k=limit)
    
    def ask(self, question: str, literature_ids: List[str] = None, 
            use_uniprot: bool = True) -> Dict[str, Any]:
        """问答接口（可选使用UniProt）"""
        if use_uniprot:
            return self.integration.enhance_qa(question, literature_ids)
        else:
            return self.enhanced_manager.ask(question, literature_ids)
    
    def get_literature_structures(self, literature_id: str, 
                                  include_uniprot: bool = True) -> Dict[str, Any]:
        """获取文献的结构信息（可选包含UniProt）"""
        result = self.enhanced_manager.get_literature_with_structures(literature_id)
        
        if include_uniprot and HAS_UNIPROT:
            # 添加UniProt信息
            structure_ids = result.get('structure_ids', [])
            if structure_ids:
                uniprot_info = self.integration._get_uniprot_info_for_structures(structure_ids)
                result['uniprot_info'] = uniprot_info
        
        return result
    
    def get_structure_statistics(self, include_uniprot: bool = True) -> Dict[str, Any]:
        """获取结构统计（可选包含UniProt）"""
        stats = self.enhanced_manager.get_structure_statistics()
        
        if include_uniprot and self.kg_api:
            try:
                uniprot_stats = self.kg_api.get_uniprot_stats()
                if uniprot_stats.get('success'):
                    stats['uniprot_statistics'] = uniprot_stats
            except Exception as e:
                logger.warning(f"获取UniProt统计失败: {e}")
        
        return stats
    
    def find_related_structures(self, structure_id: str, 
                                use_uniprot: bool = True) -> List[Dict[str, Any]]:
        """查找相关结构（可选使用UniProt）"""
        if use_uniprot and self.kg_api:
            try:
                # 使用知识图谱API查找功能相似的结构
                result = self.kg_api.get_neighborhood(structure_id, max_depth=2)
                if result.get('success'):
                    return result.get('neighborhood', {}).get('nodes', [])
            except Exception as e:
                logger.warning(f"UniProt相关结构查找失败: {e}")
        
        # 回退到基础方法
        return self.enhanced_manager.find_related_structures(structure_id)
    
    def sync_structure_data(self, rebuild: bool = False, 
                            include_uniprot: bool = True) -> Dict[str, Any]:
        """同步结构数据（可选包含UniProt）"""
        result = self.enhanced_manager.sync_structure_data(rebuild)
        
        if include_uniprot and HAS_UNIPROT:
            result['uniprot_integration'] = {
                'has_uniprot': True,
                'message': 'UniProt集成已启用'
            }
        
        return result
    
    def analyze_with_uniprot(self) -> Dict[str, Any]:
        """使用UniProt增强分析"""
        return self.integration.enhance_with_uniprot("uniprot_analysis")
    
    def get_uniprot_capabilities(self) -> Dict[str, Any]:
        """获取UniProt能力信息"""
        return {
            "has_uniprot": HAS_UNIPROT,
            "capabilities": {
                "protein_name_normalization": HAS_UNIPROT,
                "protein_name_extraction": HAS_UNIPROT,
                "uniprot_id_mapping": HAS_UNIPROT,
                "functional_analysis": HAS_UNIPROT,
                "structure_annotation": HAS_UNIPROT
            },
            "enhanced_features": [
                "enhanced_search",
                "enhanced_qa",
                "protein_based_clustering",
                "functional_similarity"
            ]
        }

# ---------- 使用示例 ----------
if __name__ == "__main__":
    # 初始化
    from structure_enhanced_literature import initialize_enhanced_system
    init_result = initialize_enhanced_system()
    print(f"初始化结果: {init_result.get('status')}")
    
    # 创建API实例
    api = StructureEnhancedAPI()
    
    # 测试UniProt能力
    capabilities = api.get_uniprot_capabilities()
    print(f"\nUniProt能力: {capabilities}")
    
    # 测试搜索（使用UniProt）
    results = api.search("SARS-CoV-2 spike protein structure PDB", limit=5, use_uniprot=True)
    print(f"\n搜索结果: {len(results.get('results', []))} 个")
    if 'protein_names' in results:
        print(f"检测到的蛋白质: {results.get('protein_names', [])}")
    
    # 测试问答（使用UniProt）
    answer = api.ask("PDB 6VSB的分辨率是多少？", use_uniprot=True)
    print(f"\n问答结果: {answer.get('answer', '')[:100]}...")
    if 'protein_analysis' in answer:
        print(f"蛋白质分析: {answer['protein_analysis'].get('detected_proteins_count', 0)} 个蛋白质")
    
    # 测试增强分析
    if api.kg_api:
        analysis = api.analyze_with_uniprot()
        print(f"\n增强分析结果: {analysis.get('enhancement_level', 'unknown')}")
    
    # 测试统计
    stats = api.get_structure_statistics(include_uniprot=True)
    print(f"\n结构统计: {stats.get('total_structures', 0)} 个结构")
    if 'uniprot_statistics' in stats:
        print(f"UniProt统计: {stats['uniprot_statistics'].get('structures_with_uniprot', 0)} 个结构有UniProt信息")