# structure_enhanced_literature.py - 结构增强的文献管理系统
import os, json, logging, re, time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from datetime import datetime
from collections import defaultdict
import concurrent.futures

# 导入现有模块
try:
    from core.literature_db import (
        LiteratureEntry, LiteratureStatus, create_literature_session,
        get_literature_entry, search_literature
    )
    HAS_LITERATURE_DB = True
except ImportError:
    HAS_LITERATURE_DB = False

try:
    from literature_index import IntegratedLiteratureIndexer, LiteratureIndexConfig
    HAS_LITERATURE_INDEX = True
except ImportError:
    HAS_LITERATURE_INDEX = False

try:
    from core.literature_parser import StructureIDExtractor
    HAS_PARSER = True
except ImportError:
    HAS_PARSER = False

# 结构管理器（如果存在）
try:
    from core.structure_manager import StructureMetadataFetcher, PDBMetadata, EMDBMetadata
    from dataclasses import asdict
    HAS_STRUCTURE_MANAGER = True
except ImportError:
    HAS_STRUCTURE_MANAGER = False

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------- 结构增强的文献索引器 ----------
class StructureEnhancedLiteratureIndexer:
    """结构增强的文献索引器 - 解决存储、索引和关联问题"""
    
    def __init__(self, base_indexer: IntegratedLiteratureIndexer = None):
        self.base_indexer = base_indexer
        if not self.base_indexer and HAS_LITERATURE_INDEX:
            self.base_indexer = IntegratedLiteratureIndexer()
        
        # 结构增强的存储
        self.structure_literature_map = {}  # 结构ID -> 文献ID列表
        self.literature_structure_map = {}  # 文献ID -> 结构ID列表
        self.structure_index = {}  # 结构ID -> 结构信息
        self.structure_search_index = None  # 专门用于结构搜索的索引
        
        # 加载现有数据
        self._load_structure_mappings()
        
        logger.info("✅ 结构增强文献索引器初始化完成")
    
    def _load_structure_mappings(self):
        """从数据库加载结构映射关系"""
        if not HAS_LITERATURE_DB:
            return
        
        try:
            session = create_literature_session()
            literature_entries = session.query(LiteratureEntry).filter(
                LiteratureEntry.cryoem_targets.isnot(None)
            ).all()
            
            for entry in literature_entries:
                lit_id = str(entry.id)
                try:
                    if isinstance(entry.cryoem_targets, str):
                        cryo_targets = json.loads(entry.cryoem_targets)
                    else:
                        cryo_targets = entry.cryoem_targets
                    
                    if isinstance(cryo_targets, dict):
                        pdb_ids = cryo_targets.get('pdb_ids', [])
                        emdb_ids = cryo_targets.get('emdb_ids', [])
                        
                        # 验证和过滤结构ID
                        valid_structure_ids = []
                        
                        # 验证PDB IDs
                        for pdb_id in pdb_ids:
                            if pdb_id:
                                pdb_id_str = str(pdb_id).strip().upper()
                                # 有效的PDB ID格式：4个字符，第一个是数字
                                if re.match(r'^[1-9][A-Za-z0-9]{3}$', pdb_id_str):
                                    valid_structure_ids.append(pdb_id_str)
                                else:
                                    logger.debug(f"跳过无效的PDB ID: {pdb_id}")
                        
                        # 验证EMDB IDs
                        for emdb_id in emdb_ids:
                            if emdb_id:
                                emdb_id_str = str(emdb_id).strip().upper()
                                # 有效的EMDB ID格式：以EMD-开头
                                if emdb_id_str.startswith('EMD-') or re.match(r'^EMD\d+$', emdb_id_str):
                                    valid_structure_ids.append(emdb_id_str)
                                elif re.match(r'^\d+$', emdb_id_str) and 3 <= len(emdb_id_str) <= 6:
                                    valid_structure_ids.append(f'EMD-{emdb_id_str}')
                                else:
                                    logger.debug(f"跳过无效的EMDB ID: {emdb_id}")
                        
                        if valid_structure_ids:
                            self.literature_structure_map[lit_id] = valid_structure_ids
                            
                            for struct_id in valid_structure_ids:
                                if struct_id not in self.structure_literature_map:
                                    self.structure_literature_map[struct_id] = []
                                if lit_id not in self.structure_literature_map[struct_id]:
                                    self.structure_literature_map[struct_id].append(lit_id)
                except Exception as e:
                    logger.debug(f"加载文献 {lit_id} 结构映射失败: {e}")
            
            session.close()
            logger.info(f"✅ 加载结构映射: {len(self.literature_structure_map)} 篇文献, {len(self.structure_literature_map)} 个结构")
            
        except Exception as e:
            logger.error(f"加载结构映射失败: {e}")
    
    def enhance_literature_data(self, literature_data: Dict[str, Any]) -> Dict[str, Any]:
        """增强文献数据，添加结构关联信息"""
        enhanced = literature_data.copy()
        lit_id = str(literature_data.get('id', ''))
        
        # 添加结构ID列表
        if lit_id in self.literature_structure_map:
            structure_ids = self.literature_structure_map[lit_id]
            # 再次验证结构ID（确保数据一致性）
            valid_structure_ids = []
            for struct_id in structure_ids:
                if struct_id:
                    struct_id_str = str(struct_id).strip().upper()
                    # 验证PDB或EMDB格式
                    if re.match(r'^[1-9][A-Za-z0-9]{3}$', struct_id_str) or struct_id_str.startswith('EMD-'):
                        valid_structure_ids.append(struct_id_str)
            if valid_structure_ids:
                enhanced['structure_ids'] = valid_structure_ids
        
        # 添加结构元数据（如果可用）
        if HAS_STRUCTURE_MANAGER:
            structure_ids = enhanced.get('structure_ids', [])
            if structure_ids:
                try:
                    from core.structure_manager import StructureMetadataFetcher
                    fetcher = StructureMetadataFetcher({'max_workers': 2, 'timeout': 10})
                    pdb_metadata, emdb_metadata = fetcher.fetch_all_metadata(structure_ids, use_cache=True)
                    
                    enhanced['structure_metadata'] = {
                        'pdb': {k: asdict(v) for k, v in pdb_metadata.items()},
                        'emdb': {k: asdict(v) for k, v in emdb_metadata.items()}
                    }
                except Exception as e:
                    logger.debug(f"获取结构元数据失败: {e}")
        
        return enhanced
    
    def update_structure_mapping(self, literature_id: str, structure_ids: List[str]):
        """更新结构映射关系"""
        lit_id = str(literature_id)
        
        # 验证和过滤结构ID
        valid_structure_ids = []
        for struct_id in structure_ids:
            if struct_id:
                struct_id_str = str(struct_id).strip().upper()
                # 验证PDB或EMDB格式
                if re.match(r'^[1-9][A-Za-z0-9]{3}$', struct_id_str) or struct_id_str.startswith('EMD-'):
                    valid_structure_ids.append(struct_id_str)
                elif re.match(r'^\d+$', struct_id_str) and 3 <= len(struct_id_str) <= 6:
                    # 纯数字的EMDB ID
                    valid_structure_ids.append(f'EMD-{struct_id_str}')
                else:
                    logger.debug(f"跳过无效的结构ID: {struct_id}")
        
        # 清除旧的映射
        if lit_id in self.literature_structure_map:
            old_ids = self.literature_structure_map[lit_id]
            for struct_id in old_ids:
                if struct_id in self.structure_literature_map and lit_id in self.structure_literature_map[struct_id]:
                    self.structure_literature_map[struct_id].remove(lit_id)
                    if not self.structure_literature_map[struct_id]:
                        del self.structure_literature_map[struct_id]
        
        # 添加新的映射
        if valid_structure_ids:
            self.literature_structure_map[lit_id] = valid_structure_ids
            
            for struct_id in valid_structure_ids:
                if struct_id not in self.structure_literature_map:
                    self.structure_literature_map[struct_id] = []
                if lit_id not in self.structure_literature_map[struct_id]:
                    self.structure_literature_map[struct_id].append(lit_id)
            
            logger.info(f"更新结构映射: 文献 {lit_id} -> {len(structure_ids)} 个结构")
            self._save_structure_mappings()
    
    def _save_structure_mappings(self):
        """保存结构映射到文件"""
        try:
            data = {
                'structure_literature_map': self.structure_literature_map,
                'literature_structure_map': self.literature_structure_map,
                'updated_at': datetime.now().isoformat()
            }
            
            save_dir = Path("structure_indices")
            save_dir.mkdir(parents=True, exist_ok=True)
            
            with open(save_dir / "structure_mappings.json", 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"✅ 结构映射已保存: {len(self.structure_literature_map)} 个结构")
            
        except Exception as e:
            logger.error(f"保存结构映射失败: {e}")
    
    def search_by_structure(self, structure_query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """根据结构ID或名称搜索文献"""
        results = []
        
        # 直接按结构ID搜索
        if structure_query.upper() in self.structure_literature_map:
            lit_ids = self.structure_literature_map[structure_query.upper()]
            logger.info(f"直接找到结构 {structure_query}: {len(lit_ids)} 篇文献")
            
            for lit_id in lit_ids[:top_k]:
                literature_info = self._get_literature_info(lit_id)
                if literature_info:
                    literature_info['match_type'] = 'direct_structure_id'
                    literature_info['matched_structure'] = structure_query.upper()
                    results.append(literature_info)
        
        # 模糊搜索结构ID
        if not results:
            for struct_id in self.structure_literature_map.keys():
                if structure_query.upper() in struct_id:
                    lit_ids = self.structure_literature_map[struct_id]
                    logger.info(f"模糊匹配结构 {struct_id}: {len(lit_ids)} 篇文献")
                    
                    for lit_id in lit_ids[:top_k]:
                        literature_info = self._get_literature_info(lit_id)
                        if literature_info:
                            literature_info['match_type'] = 'fuzzy_structure_id'
                            literature_info['matched_structure'] = struct_id
                            results.append(literature_info)
        
        # 如果有基础索引器，使用文本搜索补充
        if not results and self.base_indexer:
            try:
                index_results = self.base_indexer.search_literature(
                    f"structure {structure_query} OR PDB {structure_query} OR EMDB {structure_query}",
                    top_k=top_k
                )
                
                for result in index_results:
                    result['match_type'] = 'text_search'
                    results.append(result)
            except Exception as e:
                logger.error(f"文本搜索失败: {e}")
        
        # 去重
        unique_results = []
        seen_ids = set()
        for result in results:
            lit_id = result.get('literature_id') or result.get('id')
            if lit_id and lit_id not in seen_ids:
                seen_ids.add(lit_id)
                unique_results.append(result)
        
        return unique_results[:top_k]
    
    def _get_literature_info(self, literature_id: str) -> Optional[Dict[str, Any]]:
        """获取文献信息"""
        if not HAS_LITERATURE_DB:
            return None
        
        try:
            session = create_literature_session()
            entry = session.query(LiteratureEntry).get(int(literature_id))
            
            if entry:
                result = {
                    'literature_id': str(entry.id),
                    'title': entry.title,
                    'authors': entry.authors,
                    'year': entry.year,
                    'journal': entry.journal,
                    'abstract': entry.abstract[:200] + "..." if entry.abstract and len(entry.abstract) > 200 else entry.abstract,
                    'structure_ids': self.literature_structure_map.get(str(entry.id), []),
                    'similarity_score': 1.0  # 直接匹配，最高相似度
                }
                session.close()
                return result
            session.close()
            return None
            
        except Exception as e:
            logger.error(f"获取文献信息失败 {literature_id}: {e}")
            return None
    
    def build_structure_aware_index(self, rebuild: bool = False) -> bool:
        """构建结构感知的索引"""
        try:
            logger.info("开始构建结构感知索引...")
            
            # 确保有基础索引
            if self.base_indexer:
                # 检查基础索引状态
                logger.info("使用统一 RAG 索引系统")
            
            # 构建结构关键词索引
            self._build_structure_keyword_index()
            
            # 保存增强索引
            self._save_enhanced_index()
            
            logger.info("✅ 结构感知索引构建完成")
            return True
            
        except Exception as e:
            logger.error(f"构建结构感知索引失败: {e}")
            return False
    
    def _build_structure_keyword_index(self):
        """构建结构关键词索引"""
        logger.info("构建结构关键词索引...")
        
        # 收集所有结构相关的关键词
        structure_keywords = set()
        
        for struct_id in self.structure_literature_map.keys():
            # 提取结构类型和编号
            if struct_id.startswith('EMD-'):
                structure_keywords.add('emdb')
                structure_keywords.add('electron microscopy')
                structure_keywords.add('cryo-em')
            elif re.match(r'^[1-9][A-Za-z0-9]{3}$', struct_id):
                structure_keywords.add('pdb')
                structure_keywords.add('protein data bank')
                structure_keywords.add('structure')
                structure_keywords.add('crystal structure')
        
        # 添加到索引
        self.structure_keywords = list(structure_keywords)
        logger.info(f"收集到 {len(structure_keywords)} 个结构关键词")
    
    def _save_enhanced_index(self):
        """保存增强索引"""
        try:
            index_dir = Path("structure_indices")
            index_dir.mkdir(parents=True, exist_ok=True)
            
            data = {
                'structure_literature_map': self.structure_literature_map,
                'literature_structure_map': self.literature_structure_map,
                'structure_keywords': self.structure_keywords,
                'created_at': datetime.now().isoformat(),
                'version': '2.0'
            }
            
            with open(index_dir / "enhanced_index.json", 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"✅ 增强索引已保存: {len(self.structure_literature_map)} 个结构")
            
        except Exception as e:
            logger.error(f"保存增强索引失败: {e}")

# ---------- 结构感知的问答系统 ----------
class StructureAwareQASystem:
    """结构感知的问答系统"""
    
    def __init__(self, enhanced_indexer: StructureEnhancedLiteratureIndexer):
        self.enhanced_indexer = enhanced_indexer
        
        # 尝试导入AI模块
        try:
            from core.agent_core import ask_literature_question, HAS_AGENT
            self.has_agent = HAS_AGENT
        except ImportError:
            self.has_agent = False
        
        logger.info(f"✅ 结构感知问答系统初始化完成 (AI: {'可用' if self.has_agent else '不可用'})")
    
    def ask_question(self, question: str, literature_ids: List[str] = None,
                    structure_context: str = None) -> Dict[str, Any]:
        """回答问题 - 增强结构感知能力"""
        start_time = time.time()
        
        try:
            logger.info(f"结构感知问答: '{question}'")
            
            # 1. 检测问题是否包含结构信息
            structure_queries = self._extract_structure_queries(question)
            
            # 2. 根据问题类型选择检索策略
            if structure_queries and not literature_ids:
                # 结构相关问题，优先使用结构搜索
                search_results = []
                for struct_query in structure_queries[:3]:  # 最多3个结构查询
                    struct_results = self.enhanced_indexer.search_by_structure(struct_query, top_k=5)
                    search_results.extend(struct_results)
                
                # 去重
                unique_results = []
                seen_ids = set()
                for result in search_results:
                    lit_id = result.get('literature_id')
                    if lit_id and lit_id not in seen_ids:
                        seen_ids.add(lit_id)
                        unique_results.append(result)
                
                search_results = unique_results
                search_type = 'structure_search'
                
            else:
                # 使用基础搜索
                if self.enhanced_indexer.base_indexer:
                    search_results = self.enhanced_indexer.base_indexer.search_literature(
                        question,
                        literature_ids=literature_ids,
                        top_k=5
                    )
                else:
                    search_results = []
                search_type = 'text_search'
            
            # 3. 如果没有结果，尝试其他搜索策略
            if not search_results and structure_queries:
                # 尝试在全文搜索结构相关的术语
                if self.enhanced_indexer.base_indexer:
                    backup_query = " OR ".join([f"PDB {q}" for q in structure_queries] + 
                                               [f"EMDB {q}" for q in structure_queries] +
                                               ["cryo-em", "electron microscopy"])
                    search_results = self.enhanced_indexer.base_indexer.search_literature(
                        backup_query,
                        top_k=5
                    )
                    search_type = 'backup_search'
            
            # 4. 构建上下文并生成答案
            if search_results:
                context = self._build_enhanced_context(search_results, question, structure_queries)
                
                if self.has_agent and not structure_context:
                    # 使用AI生成答案
                    answer = self._generate_ai_answer(question, context, structure_queries)
                else:
                    # 生成简单答案
                    answer = self._generate_simple_answer(search_results, question, structure_queries)
                
                # 5. 格式化响应
                response = {
                    "success": True,
                    "question": question,
                    "answer": answer,
                    "sources": self._format_enhanced_sources(search_results, structure_queries),
                    "search_type": search_type,
                    "detected_structures": structure_queries,
                    "total_results": len(search_results),
                    "confidence": self._calculate_enhanced_confidence(search_results, structure_queries),
                    "process_time": time.time() - start_time
                }
                
                logger.info(f"✅ 结构感知问答完成: {len(search_results)} 个结果，检测到 {len(structure_queries)} 个结构")
                return response
            else:
                return {
                    "success": False,
                    "answer": "没有找到相关的文献信息。",
                    "sources": [],
                    "detected_structures": structure_queries,
                    "process_time": time.time() - start_time
                }
                
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"结构感知问答失败: {e}")
            return {
                "success": False,
                "answer": f"抱歉，回答问题失败: {str(e)}",
                "sources": [],
                "process_time": process_time
            }
    
    def _extract_structure_queries(self, text: str) -> List[str]:
        """从文本中提取结构查询"""
        structure_queries = []
        
        # 提取PDB ID (如 9MD0, 6VSB)
        pdb_pattern = r'\b([1-9][A-Za-z0-9]{3})\b'
        pdb_matches = re.findall(pdb_pattern, text, re.IGNORECASE)
        structure_queries.extend([m.upper() for m in pdb_matches])
        
        # 提取EMDB ID (如 EMD-12345)
        emdb_pattern = r'\b(EMD[-\s_]?\d{4,6})\b'
        emdb_matches = re.findall(emdb_pattern, text, re.IGNORECASE)
        structure_queries.extend([m.upper().replace(' ', '').replace('_', '-') for m in emdb_matches])
        
        # 提取结构相关关键词
        structure_keywords = ['pdb', 'emdb', 'structure', 'cryo-em', 'cryoem', 
                            'electron microscopy', 'protein structure', 'molecular structure']
        
        text_lower = text.lower()
        for keyword in structure_keywords:
            if keyword in text_lower:
                # 提取关键词周围的上下文
                idx = text_lower.find(keyword)
                start = max(0, idx - 20)
                end = min(len(text), idx + len(keyword) + 20)
                context = text[start:end]
                
                # 从上下文中提取可能的ID
                context_matches = re.findall(pdb_pattern, context, re.IGNORECASE)
                structure_queries.extend([m.upper() for m in context_matches])
                
                context_matches = re.findall(emdb_pattern, context, re.IGNORECASE)
                structure_queries.extend([m.upper().replace(' ', '').replace('_', '-') for m in context_matches])
        
        # 去重
        unique_queries = []
        seen = set()
        for query in structure_queries:
            if query not in seen:
                seen.add(query)
                unique_queries.append(query)
        
        logger.info(f"提取结构查询: {unique_queries}")
        return unique_queries
    
    def _build_enhanced_context(self, results: List[Dict], question: str, 
                               structure_queries: List[str]) -> str:
        """构建增强的上下文"""
        context_parts = []
        
        context_parts.append(f"用户问题: {question}")
        
        if structure_queries:
            context_parts.append(f"检测到的结构查询: {', '.join(structure_queries)}")
        
        context_parts.append("\n检索到的相关文献信息:")
        
        for i, result in enumerate(results[:3]):  # 最多3篇文献
            title = result.get('title', 'Unknown')
            authors = result.get('authors', '')
            year = result.get('year', '')
            journal = result.get('journal', '')
            abstract = result.get('abstract', '') or result.get('chunk_text', '')
            
            # 提取结构信息
            structure_info = ""
            if 'structure_ids' in result and result['structure_ids']:
                structure_info = f" (包含结构: {', '.join(result['structure_ids'][:3])})"
            elif 'matched_structure' in result:
                structure_info = f" (匹配结构: {result['matched_structure']})"
            
            source_info = f"\n[{i+1}] {title}{structure_info}"
            if authors:
                source_info += f" | {authors}"
            if year:
                source_info += f" ({year})"
            if journal:
                source_info += f" | {journal}"
            
            context_parts.append(source_info)
            context_parts.append(f"相关内容: {abstract[:300]}...")
        
        # 添加结构元数据信息
        if structure_queries and HAS_STRUCTURE_MANAGER:
            try:
                from core.structure_manager import StructureMetadataFetcher
                fetcher = StructureMetadataFetcher({'max_workers': 2, 'timeout': 5})
                
                structure_metadata = {}
                for struct_id in structure_queries[:5]:  # 最多5个结构
                    if struct_id.startswith('EMD-'):
                        pdb_meta, emdb_meta = fetcher.fetch_all_metadata([struct_id], use_cache=True)
                        if emdb_meta:
                            structure_metadata[struct_id] = asdict(list(emdb_meta.values())[0])
                    elif re.match(r'^[1-9][A-Za-z0-9]{3}$', struct_id):
                        pdb_meta, emdb_meta = fetcher.fetch_all_metadata([struct_id], use_cache=True)
                        if pdb_meta:
                            structure_metadata[struct_id] = asdict(list(pdb_meta.values())[0])
                
                if structure_metadata:
                    context_parts.append("\n结构元数据信息:")
                    for struct_id, meta in structure_metadata.items():
                        if 'title' in meta:
                            context_parts.append(f"{struct_id}: {meta.get('title', '')}")
                        if 'resolution' in meta:
                            context_parts.append(f"  分辨率: {meta.get('resolution', '')} Å")
            except Exception as e:
                logger.debug(f"获取结构元数据失败: {e}")
        
        return "\n".join(context_parts)
    
    def _generate_ai_answer(self, question: str, context: str, 
                           structure_queries: List[str]) -> str:
        """使用AI生成答案"""
        try:
            from core.agent_core import ask_literature_question
            
            # 构建增强的提示词
            prompt_parts = []
            prompt_parts.append("你是一个专业的结构生物学研究助手。请根据提供的文献信息和结构元数据回答问题。")
            
            if structure_queries:
                prompt_parts.append(f"注意：问题中提到了以下结构: {', '.join(structure_queries)}。")
                prompt_parts.append("请重点分析这些结构的相关信息，并在回答中引用具体的结构数据。")
            
            prompt_parts.append(f"\n{context}")
            prompt_parts.append(f"\n问题: {question}")
            
            prompt = "\n".join(prompt_parts)
            
            result = ask_literature_question(prompt, context)
            
            if isinstance(result, dict) and result.get("success"):
                answer = result.get("answer", "")
            else:
                answer = self._generate_simple_answer([], question, structure_queries)
            
            return str(answer)[:2000]
            
        except Exception as e:
            logger.error(f"AI答案生成失败: {e}")
            return self._generate_simple_answer([], question, structure_queries)
    
    def _generate_simple_answer(self, results: List[Dict], question: str,
                               structure_queries: List[str]) -> str:
        """生成简单答案"""
        if not results:
            if structure_queries:
                return f"没有找到与结构 {', '.join(structure_queries)} 相关的文献信息。"
            return "没有找到相关的文献信息。"
        
        answer_parts = []
        
        # 根据结构查询定制回答
        if structure_queries:
            answer_parts.append(f"关于结构 {', '.join(structure_queries)}，我找到了以下相关文献：\n")
        else:
            answer_parts.append("根据文献检索，我找到了以下相关信息：\n")
        
        for i, result in enumerate(results[:3]):  # 最多3篇
            title = result.get('title', '相关文献')
            authors = result.get('authors', '')
            year = result.get('year', '')
            journal = result.get('journal', '')
            
            answer_parts.append(f"{i+1}. **{title}**")
            if authors:
                answer_parts.append(f"   作者: {authors}")
            if year:
                answer_parts.append(f"   发表年份: {year}")
            if journal:
                answer_parts.append(f"   期刊: {journal}")
            
            # 显示结构信息
            if 'structure_ids' in result and result['structure_ids']:
                structures = result['structure_ids'][:3]
                answer_parts.append(f"   涉及结构: {', '.join(structures)}")
            elif 'matched_structure' in result:
                answer_parts.append(f"   匹配结构: {result['matched_structure']}")
            
            answer_parts.append("")
        
        if len(results) > 3:
            answer_parts.append(f"\n此外，还有 {len(results)-3} 篇相关文献可供参考。")
        
        if structure_queries:
            answer_parts.append("\n提示：您可以使用具体的PDB或EMDB ID进行更精确的搜索。")
        
        return "\n".join(answer_parts)
    
    def _format_enhanced_sources(self, results: List[Dict], 
                                 structure_queries: List[str]) -> List[Dict]:
        """格式化来源信息"""
        sources = []
        
        for result in results[:5]:  # 最多5个来源
            source = {
                "title": result.get("title", "Unknown"),
                "authors": result.get("authors", ""),
                "year": result.get("year", ""),
                "journal": result.get("journal", ""),
                "similarity_score": result.get("similarity_score", result.get("composite_score", 0)),
                "excerpt": result.get("abstract", result.get("chunk_text", ""))[:200],
                "match_type": result.get("match_type", "text_search")
            }
            
            # 添加结构信息
            if 'structure_ids' in result and result['structure_ids']:
                source['structures'] = result['structure_ids'][:3]
            elif 'matched_structure' in result:
                source['matched_structure'] = result['matched_structure']
            
            sources.append(source)
        
        return sources
    
    def _calculate_enhanced_confidence(self, results: List[Dict], 
                                      structure_queries: List[str]) -> float:
        """计算增强的置信度"""
        if not results:
            return 0.0
        
        # 基础置信度
        max_similarity = max(r.get("similarity_score", r.get("composite_score", 0)) for r in results)
        result_count = len(results)
        
        base_confidence = (
            max_similarity * 0.6 +
            min(result_count / 10, 0.4)
        )
        
        # 如果检测到结构查询且有结构匹配，提高置信度
        if structure_queries:
            structure_match_count = 0
            for result in results:
                if ('structure_ids' in result and result['structure_ids'] and 
                    any(struct in structure_queries for struct in result['structure_ids'])):
                    structure_match_count += 1
                elif ('matched_structure' in result and 
                      result['matched_structure'] in structure_queries):
                    structure_match_count += 1
            
            if structure_match_count > 0:
                base_confidence = min(base_confidence + 0.2, 1.0)
        
        return min(base_confidence, 1.0)

# ---------- 结构检索优化器 ----------
class StructureRetrievalOptimizer:
    """结构检索优化器"""
    
    def __init__(self, enhanced_indexer: StructureEnhancedLiteratureIndexer):
        self.enhanced_indexer = enhanced_indexer
        self.structure_patterns = {
            'pdb': re.compile(r'\b([1-9][A-Za-z0-9]{3})\b'),
            'emdb': re.compile(r'\b(EMD[-\s_]?\d{4,6})\b')
        }
    
    def optimize_search(self, query: str, top_k: int = 10) -> Dict[str, Any]:
        """优化搜索查询，特别处理结构ID"""
        start_time = time.time()
        
        try:
            # 1. 提取结构ID
            structure_ids = self._extract_all_structure_ids(query)
            
            # 2. 根据查询类型选择策略
            if structure_ids:
                logger.info(f"检测到结构ID查询: {structure_ids}")
                
                # 直接结构搜索
                structure_results = []
                for struct_id in structure_ids[:3]:  # 最多搜索3个结构
                    results = self.enhanced_indexer.search_by_structure(struct_id, top_k=top_k)
                    structure_results.extend(results)
                
                # 文本搜索（作为补充）
                text_results = []
                if self.enhanced_indexer.base_indexer:
                    text_results = self.enhanced_indexer.base_indexer.search_literature(query, top_k=top_k)
                
                # 合并结果
                combined_results = self._merge_results(structure_results, text_results, top_k)
                
                return {
                    "success": True,
                    "query": query,
                    "detected_structures": structure_ids,
                    "results": combined_results,
                    "search_strategy": "structure_enhanced",
                    "structure_result_count": len(structure_results),
                    "text_result_count": len(text_results),
                    "process_time": time.time() - start_time
                }
            else:
                # 普通文本搜索
                if self.enhanced_indexer.base_indexer:
                    results = self.enhanced_indexer.base_indexer.search_literature(query, top_k=top_k)
                else:
                    results = []
                
                return {
                    "success": True,
                    "query": query,
                    "detected_structures": [],
                    "results": results,
                    "search_strategy": "text_only",
                    "process_time": time.time() - start_time
                }
                
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"优化搜索失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "process_time": process_time
            }
    
    def _extract_all_structure_ids(self, text: str) -> List[str]:
        """从文本中提取所有结构ID"""
        structure_ids = []
        
        # 提取PDB ID
        pdb_matches = self.structure_patterns['pdb'].findall(text.upper())
        structure_ids.extend([m.upper() for m in pdb_matches])
        
        # 提取EMDB ID
        emdb_matches = self.structure_patterns['emdb'].findall(text.upper())
        structure_ids.extend([m.upper().replace(' ', '').replace('_', '-') for m in emdb_matches])
        
        # 去重
        return list(set(structure_ids))
    
    def _merge_results(self, structure_results: List[Dict], 
                       text_results: List[Dict], top_k: int) -> List[Dict]:
        """合并结构搜索和文本搜索结果"""
        combined = []
        seen_ids = set()
        
        # 优先添加结构搜索结果
        for result in structure_results:
            lit_id = result.get('literature_id')
            if lit_id and lit_id not in seen_ids:
                result['search_type'] = 'structure'
                combined.append(result)
                seen_ids.add(lit_id)
        
        # 添加文本搜索结果
        for result in text_results:
            lit_id = result.get('literature_id') or result.get('id')
            if lit_id and lit_id not in seen_ids:
                result['search_type'] = 'text'
                combined.append(result)
                seen_ids.add(lit_id)
        
        # 重新排序（结构结果优先）
        def sort_key(result):
            score = result.get('similarity_score', result.get('composite_score', 0))
            if result.get('search_type') == 'structure':
                return score + 0.5  # 结构结果加分
            return score
        
        combined.sort(key=sort_key, reverse=True)
        
        return combined[:top_k]
    
    def get_structure_statistics(self) -> Dict[str, Any]:
        """获取结构统计信息"""
        structure_map = self.enhanced_indexer.structure_literature_map
        
        # 统计不同类型的结构
        pdb_count = 0
        emdb_count = 0
        
        for struct_id in structure_map.keys():
            if struct_id.startswith('EMD-'):
                emdb_count += 1
            elif re.match(r'^[1-9][A-Za-z0-9]{3}$', struct_id):
                pdb_count += 1
        
        # 统计文献-结构关联
        literature_count = len(self.enhanced_indexer.literature_structure_map)
        
        # 统计最常出现的结构
        structure_freq = sorted(
            [(struct_id, len(lit_ids)) for struct_id, lit_ids in structure_map.items()],
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        return {
            "total_structures": len(structure_map),
            "pdb_count": pdb_count,
            "emdb_count": emdb_count,
            "literature_with_structures": literature_count,
            "top_structures": structure_freq,
            "structure_coverage": f"{literature_count} 篇文献包含结构信息"
        }

# ---------- 主管理器 ----------
class StructureEnhancedLiteratureManager:
    """结构增强的文献管理器 - 主入口"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        
        # 初始化基础索引器
        if HAS_LITERATURE_INDEX:
            self.base_indexer = IntegratedLiteratureIndexer()
        else:
            self.base_indexer = None
            logger.warning("基础文献索引器不可用")
        
        # 初始化增强索引器
        self.enhanced_indexer = StructureEnhancedLiteratureIndexer(self.base_indexer)
        
        # 初始化问答系统
        self.qa_system = StructureAwareQASystem(self.enhanced_indexer)
        
        # 初始化检索优化器
        self.retrieval_optimizer = StructureRetrievalOptimizer(self.enhanced_indexer)
        
        logger.info("✅ 结构增强文献管理器初始化完成")
    
    def sync_structure_data(self, rebuild: bool = False) -> Dict[str, Any]:
        """同步结构数据"""
        start_time = time.time()
        
        try:
            # 重新加载结构映射
            self.enhanced_indexer._load_structure_mappings()
            
            # 构建增强索引
            if rebuild:
                success = self.enhanced_indexer.build_structure_aware_index(rebuild=True)
            else:
                success = self.enhanced_indexer.build_structure_aware_index(rebuild=False)
            
            process_time = time.time() - start_time
            
            stats = self.get_structure_statistics()
            
            return {
                "success": success,
                "message": "结构数据同步完成" if success else "结构数据同步失败",
                "statistics": stats,
                "process_time": process_time,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"同步结构数据失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "process_time": process_time
            }
    
    def search(self, query: str, search_type: str = "auto", 
               top_k: int = 10) -> Dict[str, Any]:
        """增强搜索 - 自动检测结构查询"""
        return self.retrieval_optimizer.optimize_search(query, top_k)
    
    def ask(self, question: str, literature_ids: List[str] = None) -> Dict[str, Any]:
        """结构感知的问答"""
        return self.qa_system.ask_question(question, literature_ids)
    
    def get_literature_with_structures(self, literature_id: str) -> Dict[str, Any]:
        """获取文献及其结构信息"""
        return self.enhanced_indexer.enhance_literature_data({'id': literature_id})
    
    def get_structure_statistics(self) -> Dict[str, Any]:
        """获取结构统计信息"""
        return self.retrieval_optimizer.get_structure_statistics()
    
    def find_related_structures(self, structure_id: str) -> List[Dict[str, Any]]:
        """查找相关结构"""
        if structure_id in self.enhanced_indexer.structure_literature_map:
            lit_ids = self.enhanced_indexer.structure_literature_map[structure_id]
            
            # 获取这些文献中的所有结构
            all_structures = set()
            for lit_id in lit_ids:
                if lit_id in self.enhanced_indexer.literature_structure_map:
                    all_structures.update(self.enhanced_indexer.literature_structure_map[lit_id])
            
            # 排除查询的结构本身
            all_structures.discard(structure_id)
            
            # 统计出现频率
            structure_freq = {}
            for struct_id in all_structures:
                for lit_id in lit_ids:
                    if lit_id in self.enhanced_indexer.literature_structure_map:
                        if struct_id in self.enhanced_indexer.literature_structure_map[lit_id]:
                            structure_freq[struct_id] = structure_freq.get(struct_id, 0) + 1
            
            # 转换为列表并排序
            related = []
            for struct_id, freq in sorted(structure_freq.items(), key=lambda x: x[1], reverse=True):
                related.append({
                    "structure_id": struct_id,
                    "co_occurrence_count": freq,
                    "related_literature_count": len(self.enhanced_indexer.structure_literature_map.get(struct_id, []))
                })
            
            return related[:10]  # 返回前10个相关结构
        
        return []
    
    def batch_update_structure_mappings(self) -> Dict[str, Any]:
        """批量更新结构映射（从数据库重新构建）"""
        if not HAS_LITERATURE_DB:
            return {"success": False, "error": "数据库不可用"}
        
        start_time = time.time()
        
        try:
            session = create_literature_session()
            
            # 获取所有有结构信息的文献
            literature_entries = session.query(LiteratureEntry).filter(
                LiteratureEntry.cryoem_targets.isnot(None)
            ).all()
            
            updated_count = 0
            error_count = 0
            
            for entry in literature_entries:
                try:
                    lit_id = str(entry.id)
                    
                    # 提取结构ID
                    if isinstance(entry.cryoem_targets, str):
                        cryo_targets = json.loads(entry.cryoem_targets)
                    else:
                        cryo_targets = entry.cryoem_targets
                    
                    structure_ids = []
                    if isinstance(cryo_targets, dict):
                        structure_ids.extend(cryo_targets.get('pdb_ids', []))
                        structure_ids.extend(cryo_targets.get('emdb_ids', []))
                    
                    # 更新映射
                    if structure_ids:
                        self.enhanced_indexer.update_structure_mapping(lit_id, structure_ids)
                        updated_count += 1
                    
                except Exception as e:
                    error_count += 1
                    logger.debug(f"更新文献 {entry.id} 结构映射失败: {e}")
            
            session.close()
            
            process_time = time.time() - start_time
            
            return {
                "success": True,
                "message": f"批量更新完成: {updated_count} 篇文献更新，{error_count} 个错误",
                "updated_count": updated_count,
                "error_count": error_count,
                "total_structures": len(self.enhanced_indexer.structure_literature_map),
                "process_time": process_time
            }
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"批量更新结构映射失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "process_time": process_time
            }

# ---------- 全局实例 ----------
_enhanced_manager = None

def get_enhanced_literature_manager() -> StructureEnhancedLiteratureManager:
    """获取增强的文献管理器实例"""
    global _enhanced_manager
    
    if _enhanced_manager is None:
        _enhanced_manager = StructureEnhancedLiteratureManager()
    
    return _enhanced_manager

def initialize_enhanced_system() -> Dict[str, Any]:
    """初始化增强系统"""
    global _enhanced_manager
    
    start_time = time.time()
    
    try:
        _enhanced_manager = StructureEnhancedLiteratureManager()
        
        # 同步结构数据
        sync_result = _enhanced_manager.sync_structure_data(rebuild=False)
        
        process_time = time.time() - start_time
        
        stats = _enhanced_manager.get_structure_statistics()
        
        return {
            "status": "success",
            "message": "结构增强文献系统初始化完成",
            "initialization_time": process_time,
            "sync_result": sync_result,
            "statistics": stats,
            "capabilities": {
                "structure_search": True,
                "structure_aware_qa": True,
                "structure_retrieval_optimization": True,
                "structure_statistics": True,
                "related_structures": True
            }
        }
        
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"初始化增强系统失败: {e}")
        return {
            "status": "error",
            "message": f"初始化失败: {str(e)}",
            "initialization_time": process_time
        }

# ---------- 使用示例 ----------
if __name__ == "__main__":
    # 测试初始化
    result = initialize_enhanced_system()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # 获取管理器
    manager = get_enhanced_literature_manager()
    
    # 测试结构搜索
    print("\n测试结构搜索...")
    search_results = manager.search("PDB 9MD0 或者 EMD-12345", top_k=5)
    print(f"搜索到 {len(search_results.get('results', []))} 个结果")
    if search_results.get('detected_structures'):
        print(f"检测到的结构: {search_results['detected_structures']}")
    
    # 测试结构感知问答
    print("\n测试结构感知问答...")
    qa_response = manager.ask("PDB 9MD0的结构特征是什么？")
    print(f"答案: {qa_response.get('answer', '')[:200]}...")
    print(f"置信度: {qa_response.get('confidence', 0):.2f}")
    print(f"检测到的结构: {qa_response.get('detected_structures', [])}")
    
    # 测试结构统计
    print("\n测试结构统计...")
    stats = manager.get_structure_statistics()
    print(f"总结构数: {stats.get('total_structures', 0)}")
    print(f"PDB数量: {stats.get('pdb_count', 0)}")
    print(f"EMDB数量: {stats.get('emdb_count', 0)}")
    print(f"包含结构的文献: {stats.get('literature_with_structures', 0)}")
    
    print("\n✅ 结构增强系统测试完成")