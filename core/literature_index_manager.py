# literature_index_manager.py - 文献索引管理器（适配统一RAG系统）
import os, json, logging, time, shutil, threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from collections import Counter

logger = logging.getLogger(__name__)

class LiteratureIndexManager:
    """文献索引管理器 - 管理统一RAG索引的加载、验证和重建"""
    
    _instance = None
    _initialized = False
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(LiteratureIndexManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, index_dir: str = "literature_indices"):
        if LiteratureIndexManager._initialized:
            logger.info("LiteratureIndexManager 已经初始化过，跳过重复初始化")
            return
            
        with LiteratureIndexManager._lock:
            if LiteratureIndexManager._initialized:
                return
                
            self.index_dir = Path(index_dir)
            self.index_dir.mkdir(parents=True, exist_ok=True)
            
            LiteratureIndexManager._initialized = True
            logger.info(f"索引管理器初始化，索引目录: {index_dir}")
    
    def check_index_integrity(self) -> Dict[str, Any]:
        """检查统一索引完整性"""
        integrity = {
            "overall": "unknown",
            "unified_index": {
                "exists": False,
                "documents": 0,
                "entity_types": {},
                "integrity": "missing"
            },
            "faiss_index": {
                "exists": False,
                "vector_count": 0,
                "integrity": "missing"
            },
            "structure_mappings": {
                "exists": False,
                "structures": 0,
                "literatures": 0,
                "integrity": "missing"
            },
            "id_mappings": {
                "exists": False,
                "mapping_count": 0,
                "integrity": "missing"
            },
            "needs_rebuild": True,
            "message": "索引未初始化",
            "last_checked": datetime.now().isoformat(),
            "version": "unknown"
        }
        
        try:
            # 检查统一索引文件
            unified_index_file = self.index_dir / "unified_index.json"
            if unified_index_file.exists():
                try:
                    with open(unified_index_file, 'r', encoding='utf-8') as f:
                        unified_data = json.load(f)
                        documents = unified_data.get('documents', {})
                        integrity["unified_index"]["exists"] = True
                        integrity["unified_index"]["documents"] = len(documents)
                        integrity["unified_index"]["integrity"] = "valid"
                        
                        # 统计实体类型
                        entity_types = Counter()
                        for doc_id, doc_data in documents.items():
                            entity_type = doc_data.get('entity_type', 'unknown')
                            entity_types[entity_type] += 1
                        integrity["unified_index"]["entity_types"] = dict(entity_types)
                        
                        # 获取版本信息
                        integrity["version"] = unified_data.get('version', '1.0')
                        
                except Exception as e:
                    logger.error(f"读取统一索引失败: {e}")
                    integrity["unified_index"]["integrity"] = "corrupted"
            
            # 检查FAISS索引
            faiss_index_file = self.index_dir / "faiss_index.bin"
            if faiss_index_file.exists():
                try:
                    import faiss
                    index = faiss.read_index(str(faiss_index_file))
                    integrity["faiss_index"]["exists"] = True
                    integrity["faiss_index"]["vector_count"] = index.ntotal
                    integrity["faiss_index"]["integrity"] = "valid"
                except ImportError:
                    integrity["faiss_index"]["integrity"] = "faiss_not_available"
                    logger.warning("FAISS库不可用，跳过索引检查")
                except Exception as e:
                    logger.error(f"读取FAISS索引失败: {e}")
                    integrity["faiss_index"]["integrity"] = "corrupted"
            
            # 检查结构映射
            structure_file = self.index_dir / "structure_mappings.json"
            if structure_file.exists():
                try:
                    with open(structure_file, 'r', encoding='utf-8') as f:
                        structure_data = json.load(f)
                        integrity["structure_mappings"]["exists"] = True
                        integrity["structure_mappings"]["structures"] = len(structure_data.get('structure_literature_map', {}))
                        integrity["structure_mappings"]["literatures"] = len(structure_data.get('literature_structure_map', {}))
                        integrity["structure_mappings"]["integrity"] = "valid"
                except Exception as e:
                    logger.error(f"读取结构映射失败: {e}")
                    integrity["structure_mappings"]["integrity"] = "corrupted"
            
            # 检查ID映射
            id_mapping_file = self.index_dir / "id_mappings.json"
            if id_mapping_file.exists():
                try:
                    with open(id_mapping_file, 'r', encoding='utf-8') as f:
                        id_data = json.load(f)
                        mapping_count = len(id_data.get('id_to_idx', {}))
                        integrity["id_mappings"]["exists"] = True
                        integrity["id_mappings"]["mapping_count"] = mapping_count
                        integrity["id_mappings"]["integrity"] = "valid"
                except Exception as e:
                    logger.error(f"读取ID映射失败: {e}")
                    integrity["id_mappings"]["integrity"] = "corrupted"
            
            # 综合评估
            has_unified = integrity["unified_index"]["integrity"] == "valid"
            has_faiss = integrity["faiss_index"]["integrity"] == "valid"
            has_structure = integrity["structure_mappings"]["integrity"] == "valid"
            has_id_mappings = integrity["id_mappings"]["integrity"] == "valid"
            
            if has_unified and has_faiss:
                integrity["overall"] = "healthy"
                integrity["needs_rebuild"] = False
                integrity["message"] = f"索引正常: {integrity['unified_index']['documents']} 个文档"
                
                # 检查索引创建时间
                try:
                    if unified_index_file.exists():
                        mtime = os.path.getmtime(unified_index_file)
                        days_old = (time.time() - mtime) / (24 * 3600)
                        if days_old > 7:  # 超过7天
                            integrity["overall"] = "stale"
                            integrity["message"] = f"索引已过期 ({days_old:.1f} 天)，建议更新"
                except Exception as e:
                    logger.warning(f"检查索引时间失败: {e}")
                    
            elif has_unified or has_faiss:
                integrity["overall"] = "partial"
                integrity["needs_rebuild"] = True
                missing = []
                if not has_unified:
                    missing.append("unified_index.json")
                if not has_faiss:
                    missing.append("faiss_index.bin")
                if not has_structure:
                    missing.append("structure_mappings.json")
                integrity["message"] = f"索引不完整，缺失: {', '.join(missing)}"
            else:
                integrity["overall"] = "missing"
                integrity["needs_rebuild"] = True
                integrity["message"] = "索引文件不存在"
            
            return integrity
            
        except Exception as e:
            logger.error(f"检查索引完整性失败: {e}")
            return {
                "overall": "error",
                "message": f"检查失败: {str(e)}",
                "needs_rebuild": True,
                "last_checked": datetime.now().isoformat()
            }
    
    def prepare_index_directories(self, clean: bool = False) -> bool:
        """准备索引目录"""
        try:
            if clean:
                # 清理旧索引
                if self.index_dir.exists():
                    shutil.rmtree(self.index_dir)
                    logger.info("清理索引目录")
            
            # 确保目录存在
            self.index_dir.mkdir(parents=True, exist_ok=True)
            
            # 创建初始元数据文件（如果不存在）
            metadata_file = self.index_dir / "index_metadata.json"
            if not metadata_file.exists():
                initial_metadata = {
                    "created_at": datetime.now().isoformat(),
                    "last_updated": None,
                    "total_documents": 0,
                    "structure_count": 0,
                    "status": "empty",
                    "version": "2.0",
                    "index_type": "unified_rag"
                }
                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(initial_metadata, f, indent=2, ensure_ascii=False)
                logger.info("创建初始索引元数据文件")
            
            return True
            
        except Exception as e:
            logger.error(f"准备索引目录失败: {e}")
            return False
    
    def save_index_metadata(self, total_documents: int, structure_count: int = 0) -> bool:
        """保存索引元数据"""
        try:
            metadata = {
                "total_documents": total_documents,
                "structure_count": structure_count,
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "status": "built",
                "version": "2.0",
                "index_type": "unified_rag"
            }
            
            metadata_file = self.index_dir / "index_metadata.json"
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            logger.info(f"保存索引元数据: {total_documents} 个文档, {structure_count} 个结构")
            return True
            
        except Exception as e:
            logger.error(f"保存索引元数据失败: {e}")
            return False
    
    def get_index_statistics(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        try:
            stats = {
                "unified_index": {
                    "exists": False,
                    "document_count": 0,
                    "entity_type_distribution": {}
                },
                "faiss_index": {
                    "exists": False,
                    "vector_count": 0
                },
                "structure_mappings": {
                    "exists": False,
                    "structure_count": 0,
                    "literature_count": 0,
                    "mapping_density": 0.0
                },
                "id_mappings": {
                    "exists": False,
                    "mapping_count": 0
                },
                "metadata": {},
                "version": "unknown",
                "last_modified": None
            }
            
            # 检查统一索引
            unified_file = self.index_dir / "unified_index.json"
            if unified_file.exists():
                try:
                    with open(unified_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        documents = data.get('documents', {})
                        stats["unified_index"]["exists"] = True
                        stats["unified_index"]["document_count"] = len(documents)
                        
                        # 统计实体类型分布
                        entity_types = Counter()
                        for doc_id, doc_data in documents.items():
                            entity_type = doc_data.get('entity_type', 'unknown')
                            entity_types[entity_type] += 1
                        stats["unified_index"]["entity_type_distribution"] = dict(entity_types)
                        
                        # 获取版本
                        stats["version"] = data.get('version', 'unknown')
                        
                        # 获取最后修改时间
                        stats["last_modified"] = datetime.fromtimestamp(
                            os.path.getmtime(unified_file)
                        ).isoformat()
                except Exception as e:
                    logger.warning(f"读取统一索引失败: {e}")
            
            # 检查FAISS索引
            faiss_file = self.index_dir / "faiss_index.bin"
            if faiss_file.exists():
                try:
                    import faiss
                    index = faiss.read_index(str(faiss_file))
                    stats["faiss_index"]["exists"] = True
                    stats["faiss_index"]["vector_count"] = index.ntotal
                except Exception as e:
                    logger.warning(f"读取FAISS索引失败: {e}")
            
            # 检查结构映射
            structure_file = self.index_dir / "structure_mappings.json"
            if structure_file.exists():
                try:
                    with open(structure_file, 'r', encoding='utf-8') as f:
                        structure_data = json.load(f)
                        structure_map = structure_data.get('structure_literature_map', {})
                        literature_map = structure_data.get('literature_structure_map', {})
                        
                        stats["structure_mappings"]["exists"] = True
                        stats["structure_mappings"]["structure_count"] = len(structure_map)
                        stats["structure_mappings"]["literature_count"] = len(literature_map)
                        
                        # 计算映射密度
                        if literature_map:
                            total_mappings = sum(len(struct_ids) for struct_ids in literature_map.values())
                            stats["structure_mappings"]["mapping_density"] = round(total_mappings / len(literature_map), 2)
                except Exception as e:
                    logger.warning(f"读取结构映射失败: {e}")
            
            # 检查ID映射
            id_mapping_file = self.index_dir / "id_mappings.json"
            if id_mapping_file.exists():
                try:
                    with open(id_mapping_file, 'r', encoding='utf-8') as f:
                        id_data = json.load(f)
                        mapping_count = len(id_data.get('id_to_idx', {}))
                        stats["id_mappings"]["exists"] = True
                        stats["id_mappings"]["mapping_count"] = mapping_count
                except Exception as e:
                    logger.warning(f"读取ID映射失败: {e}")
            
            # 读取元数据
            metadata_file = self.index_dir / "index_metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        stats["metadata"] = json.load(f)
                except Exception as e:
                    logger.warning(f"读取元数据失败: {e}")
            
            return stats
            
        except Exception as e:
            logger.error(f"获取索引统计失败: {e}")
            return {"error": str(e)}
    
    def cleanup_old_indices(self, keep_days: int = 30) -> Dict[str, Any]:
        """清理旧索引备份"""
        try:
            removed = []
            kept = []
            
            # 查找可能的备份目录
            for item in self.index_dir.iterdir():
                if item.is_dir() and item.name.startswith("backup_"):
                    try:
                        # 检查修改时间
                        mtime = item.stat().st_mtime
                        age_days = (time.time() - mtime) / (24 * 3600)
                        
                        if age_days > keep_days:
                            shutil.rmtree(item)
                            removed.append({
                                "name": item.name,
                                "age_days": round(age_days, 1)
                            })
                            logger.info(f"删除旧索引备份: {item.name} ({age_days:.1f} 天)")
                        else:
                            kept.append({
                                "name": item.name,
                                "age_days": round(age_days, 1)
                            })
                    except Exception as e:
                        logger.warning(f"无法处理 {item.name}: {e}")
            
            # 清理旧版本索引文件
            old_files = [
                "literature_index.faiss",
                "chunk_data.json",
                "index.pkl",
                "docstore.json"
            ]
            
            old_removed = []
            for old_file in old_files:
                file_path = self.index_dir / old_file
                if file_path.exists():
                    try:
                        file_path.unlink()
                        old_removed.append(old_file)
                        logger.info(f"删除旧索引文件: {old_file}")
                    except Exception as e:
                        logger.warning(f"无法删除 {old_file}: {e}")
            
            result = {
                "success": True,
                "backups_removed": removed,
                "backups_kept": kept,
                "old_files_removed": old_removed,
                "removed_count": len(removed) + len(old_removed),
                "kept_count": len(kept),
                "message": f"清理完成: 删除了 {len(removed)} 个旧备份和 {len(old_removed)} 个旧文件，保留了 {len(kept)} 个备份"
            }
            
            logger.info(result["message"])
            return result
            
        except Exception as e:
            logger.error(f"清理旧索引失败: {e}")
            return {
                "success": False, 
                "error": str(e),
                "message": f"清理失败: {str(e)}"
            }
    
    def load_index_if_exists(self, rag_system) -> bool:
        """过时方法：向后兼容，已不再需要手动加载索引"""
        logger.warning("load_index_if_exists 方法已过时，统一RAG系统会自动加载索引")
        return False
    
    def migrate_old_index(self, backup: bool = True) -> Dict[str, Any]:
        """迁移旧版本索引到新版本（仅结构，不迁移数据）"""
        try:
            old_faiss_dir = self.index_dir / "faiss"
            old_llama_dir = self.index_dir / "llama_index"
            
            if not old_faiss_dir.exists() and not old_llama_dir.exists():
                return {
                    "success": False,
                    "message": "未找到旧版本索引目录"
                }
            
            result = {
                "success": False,
                "backup_created": False,
                "directories_migrated": 0,
                "message": ""
            }
            
            # 备份旧索引
            if backup:
                backup_dir = self.index_dir / f"backup_old_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                backup_dir.mkdir(parents=True, exist_ok=True)
                
                if old_faiss_dir.exists():
                    try:
                        shutil.copytree(old_faiss_dir, backup_dir / "faiss")
                        result["directories_migrated"] += 1
                    except Exception as e:
                        logger.warning(f"备份faiss目录失败: {e}")
                
                if old_llama_dir.exists():
                    try:
                        shutil.copytree(old_llama_dir, backup_dir / "llama_index")
                        result["directories_migrated"] += 1
                    except Exception as e:
                        logger.warning(f"备份llama_index目录失败: {e}")
                
                if result["directories_migrated"] > 0:
                    result["backup_created"] = True
                    result["backup_location"] = str(backup_dir)
            
            # 重命名旧目录（添加.old后缀）
            if old_faiss_dir.exists():
                old_faiss_dir.rename(old_faiss_dir.with_suffix(".old"))
                logger.info(f"重命名faiss目录: {old_faiss_dir.name} -> {old_faiss_dir.name}.old")
            
            if old_llama_dir.exists():
                old_llama_dir.rename(old_llama_dir.with_suffix(".old"))
                logger.info(f"重命名llama_index目录: {old_llama_dir.name} -> {old_llama_dir.name}.old")
            
            # 创建新的统一索引结构
            self.prepare_index_directories(clean=False)
            
            result["success"] = True
            result["message"] = "索引目录迁移完成。注意：需要重新构建索引数据。"
            
            return result
            
        except Exception as e:
            logger.error(f"索引迁移失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"迁移失败: {str(e)}"
            }
    
    def verify_index_consistency(self) -> Dict[str, Any]:
        """验证索引一致性"""
        try:
            integrity = self.check_index_integrity()
            
            if integrity["overall"] != "healthy":
                return {
                    "success": False,
                    "consistent": False,
                    "message": "索引不完整，无法验证一致性",
                    "integrity": integrity
                }
            
            inconsistencies = []
            
            # 检查统一索引和FAISS索引大小是否一致
            if integrity["unified_index"]["documents"] != integrity["faiss_index"]["vector_count"]:
                inconsistencies.append({
                    "type": "size_mismatch",
                    "message": f"文档数量({integrity['unified_index']['documents']})与向量数量({integrity['faiss_index']['vector_count']})不匹配"
                })
            
            # 检查结构映射的一致性
            if integrity["structure_mappings"]["integrity"] == "valid":
                structure_file = self.index_dir / "structure_mappings.json"
                with open(structure_file, 'r', encoding='utf-8') as f:
                    structure_data = json.load(f)
                
                structure_literature_map = structure_data.get('structure_literature_map', {})
                literature_structure_map = structure_data.get('literature_structure_map', {})
                
                # 检查双向映射的一致性
                for struct_id, lit_ids in structure_literature_map.items():
                    for lit_id in lit_ids:
                        if lit_id not in literature_structure_map:
                            inconsistencies.append({
                                "type": "mapping_inconsistency",
                                "message": f"结构 {struct_id} 映射到文献 {lit_id}，但文献没有反向映射"
                            })
                        elif struct_id not in literature_structure_map[lit_id]:
                            inconsistencies.append({
                                "type": "mapping_inconsistency",
                                "message": f"结构 {struct_id} 映射到文献 {lit_id}，但文献的映射列表中没有该结构"
                            })
                
                for lit_id, struct_ids in literature_structure_map.items():
                    for struct_id in struct_ids:
                        if struct_id not in structure_literature_map:
                            inconsistencies.append({
                                "type": "mapping_inconsistency",
                                "message": f"文献 {lit_id} 映射到结构 {struct_id}，但结构没有反向映射"
                            })
                        elif lit_id not in structure_literature_map[struct_id]:
                            inconsistencies.append({
                                "type": "mapping_inconsistency",
                                "message": f"文献 {lit_id} 映射到结构 {struct_id}，但结构的映射列表中没有该文献"
                            })
            
            consistent = len(inconsistencies) == 0
            
            return {
                "success": True,
                "consistent": consistent,
                "inconsistencies": inconsistencies,
                "inconsistency_count": len(inconsistencies),
                "integrity": integrity,
                "message": f"索引一致性检查完成: {'一致' if consistent else f'发现{len(inconsistencies)}个不一致项'}"
            }
            
        except Exception as e:
            logger.error(f"验证索引一致性失败: {e}")
            return {
                "success": False,
                "consistent": False,
                "error": str(e),
                "message": f"验证失败: {str(e)}"
            }
    
    def backup_current_index(self, backup_name: str = None) -> Dict[str, Any]:
        """备份当前索引"""
        try:
            if backup_name is None:
                backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            backup_dir = self.index_dir / backup_name
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            # 复制所有索引文件
            files_copied = []
            for file_path in self.index_dir.iterdir():
                if file_path.is_file() and file_path.suffix in ['.json', '.bin', '.pkl']:
                    try:
                        shutil.copy2(file_path, backup_dir / file_path.name)
                        files_copied.append(file_path.name)
                    except Exception as e:
                        logger.warning(f"复制文件 {file_path.name} 失败: {e}")
            
            return {
                "success": True,
                "backup_name": backup_name,
                "backup_location": str(backup_dir),
                "files_copied": files_copied,
                "file_count": len(files_copied),
                "message": f"索引备份完成: {backup_name}"
            }
            
        except Exception as e:
            logger.error(f"备份索引失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"备份失败: {str(e)}"
            }

# 测试代码
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(level=logging.INFO)
    
    # 测试索引管理器
    manager = LiteratureIndexManager("test_indices")
    
    # 准备目录
    manager.prepare_index_directories()
    
    # 检查完整性
    integrity = manager.check_index_integrity()
    print("完整性检查:", json.dumps(integrity, indent=2, ensure_ascii=False))
    
    # 获取统计信息
    stats = manager.get_index_statistics()
    print("\n统计信息:", json.dumps(stats, indent=2, ensure_ascii=False))
    
    # 测试一致性验证
    consistency = manager.verify_index_consistency()
    print("\n一致性验证:", json.dumps(consistency, indent=2, ensure_ascii=False))
    
    # 清理测试目录
    import shutil
    if Path("test_indices").exists():
        shutil.rmtree("test_indices")
        print("\n清理测试目录")