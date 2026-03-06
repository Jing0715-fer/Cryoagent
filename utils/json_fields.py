# utils/json_fields.py
import json
import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

def normalize_key_findings(key_findings: Any) -> List[Dict[str, Any]]:
    """标准化关键发现数据格式
    
    统一返回格式:
    [
        {
            "category": "主要发现",
            "findings": [
                {"text": "发现1内容", "confidence": 0.9},
                {"text": "发现2内容", "confidence": 0.8}
            ]
        }
    ]
    """
    if not key_findings:
        return []
    
    try:
        # 如果是字符串，尝试解析JSON
        if isinstance(key_findings, str):
            try:
                data = json.loads(key_findings)
            except json.JSONDecodeError:
                # 如果不是JSON，当作普通文本处理
                data = [{"text": key_findings}]
        else:
            data = key_findings
        
        # 标准化格式
        result = []
        
        if isinstance(data, list):
            # 如果是列表，处理每个元素
            category = "主要发现"
            findings = []
            
            for item in data:
                if isinstance(item, dict):
                    # 如果是字典，提取text或finding字段
                    text = item.get("text") or item.get("finding")
                    if text:
                        confidence = item.get("confidence", 0.8)
                        findings.append({"text": str(text), "confidence": confidence})
                    else:
                        # 如果没有text/finding字段，尝试其他字段
                        for key, value in item.items():
                            if key not in ["confidence", "type", "category"] and isinstance(value, str) and value.strip():
                                findings.append({"text": value, "confidence": 0.7})
                                break
                elif isinstance(item, str):
                    # 如果是字符串，直接添加
                    findings.append({"text": item, "confidence": 0.8})
            
            if findings:
                result.append({
                    "category": category,
                    "findings": findings
                })
        
        elif isinstance(data, dict):
            # 如果是字典，按类别分组
            if "findings" in data:
                # 已经是我们期望的格式
                findings = data.get("findings", [])
                category = data.get("category", "主要发现")
                
                normalized_findings = []
                for finding in findings:
                    if isinstance(finding, dict):
                        text = finding.get("text") or finding.get("finding")
                        if text:
                            confidence = finding.get("confidence", 0.8)
                            normalized_findings.append({"text": str(text), "confidence": confidence})
                    elif isinstance(finding, str):
                        normalized_findings.append({"text": finding, "confidence": 0.8})
                
                if normalized_findings:
                    result.append({
                        "category": category,
                        "findings": normalized_findings
                    })
            else:
                # 其他字典格式，尝试转换
                category = "主要发现"
                findings = []
                
                for key, value in data.items():
                    if key in ["findings", "key_findings", "discoveries"] and isinstance(value, list):
                        # 嵌套的findings列表
                        for item in value:
                            if isinstance(item, dict):
                                text = item.get("text") or item.get("finding")
                                if text:
                                    confidence = item.get("confidence", 0.8)
                                    findings.append({"text": str(text), "confidence": confidence})
                            elif isinstance(item, str):
                                findings.append({"text": item, "confidence": 0.8})
                    elif isinstance(value, str) and value.strip():
                        # 字符串值，作为发现
                        findings.append({"text": f"{key}: {value}", "confidence": 0.7})
                
                if findings:
                    result.append({
                        "category": category,
                        "findings": findings
                    })
        
        else:
            # 其他类型
            result.append({
                "category": "主要发现",
                "findings": [{"text": str(data), "confidence": 0.7}]
            })
        
        return result
        
    except Exception as e:
        logger.error(f"标准化关键发现失败: {e}")
        # 返回空结果，让前端显示默认文本
        return []

def normalize_cryoem_targets(cryoem_targets: Any) -> Dict[str, Any]:
    """标准化冷冻电镜目标数据格式"""
    if not cryoem_targets:
        return {"pdb_ids": [], "emdb_ids": [], "structure_info": {}}
    
    try:
        if isinstance(cryoem_targets, str):
            try:
                data = json.loads(cryoem_targets)
            except json.JSONDecodeError:
                # 如果不是JSON，尝试从字符串中提取
                return {
                    "pdb_ids": [],
                    "emdb_ids": [],
                    "structure_info": {},
                    "raw_text": cryoem_targets
                }
        else:
            data = cryoem_targets
        
        # 标准化格式
        result = {
            "pdb_ids": [],
            "emdb_ids": [],
            "structure_info": {}
        }
        
        if isinstance(data, dict):
            # 直接字典格式
            pdb_ids = data.get("pdb_ids", [])
            if isinstance(pdb_ids, str):
                # 处理逗号分隔的字符串
                pdb_ids = [id.strip() for id in pdb_ids.split(",") if id.strip()]
            elif not isinstance(pdb_ids, list):
                pdb_ids = []
            
            emdb_ids = data.get("emdb_ids", [])
            if isinstance(emdb_ids, str):
                # 处理逗号分隔的字符串
                emdb_ids = [id.strip() for id in emdb_ids.split(",") if id.strip()]
            elif not isinstance(emdb_ids, list):
                emdb_ids = []
            
            result["pdb_ids"] = pdb_ids
            result["emdb_ids"] = emdb_ids
            result["structure_info"] = data.get("structure_info", {})
            
        elif isinstance(data, list):
            # 列表格式，可能是混合的ID列表
            pdb_ids = []
            emdb_ids = []
            
            for item in data:
                if isinstance(item, str):
                    item_str = item.strip().upper()
                    if item_str.startswith("EMD-") or (item_str.isdigit() and len(item_str) >= 4):
                        emdb_ids.append(item_str if item_str.startswith("EMD-") else f"EMD-{item_str}")
                    elif len(item_str) == 4 and item_str.isalnum():
                        pdb_ids.append(item_str)
            
            result["pdb_ids"] = pdb_ids
            result["emdb_ids"] = emdb_ids
            
        return result
        
    except Exception as e:
        logger.error(f"标准化cryoem_targets失败: {e}")
        return {"pdb_ids": [], "emdb_ids": [], "structure_info": {}}
    
def convert_structure_result_for_json(structure_result: Dict) -> Dict:
    """将结构结果转换为可JSON序列化的格式"""
    try:
        import copy
        
        result = copy.deepcopy(structure_result)
        
        # 处理PDB元数据
        pdb_metadata = result.get('pdb_metadata', {})
        for pdb_id, metadata in pdb_metadata.items():
            if hasattr(metadata, '__dict__'):
                from dataclasses import asdict
                pdb_metadata[pdb_id] = asdict(metadata)
        
        # 处理EMDB元数据
        emdb_metadata = result.get('emdb_metadata', {})
        for emdb_id, metadata in emdb_metadata.items():
            if hasattr(metadata, '__dict__'):
                from dataclasses import asdict
                emdb_metadata[emdb_id] = asdict(metadata)
        
        # 处理关系
        relationships = result.get('relationships', [])
        for i, rel in enumerate(relationships):
            if hasattr(rel, '__dict__'):
                from dataclasses import asdict
                relationships[i] = asdict(rel)
        
        # 处理分组
        groups = result.get('groups', [])
        for group in groups:
            structures = group.get('structures', [])
            for j, struct in enumerate(structures):
                metadata = struct.get('metadata')
                if metadata and hasattr(metadata, '__dict__'):
                    from dataclasses import asdict
                    structures[j]['metadata'] = asdict(metadata)
            
            primary_structure = group.get('primary_structure')
            if primary_structure and primary_structure.get('metadata'):
                metadata = primary_structure['metadata']
                if hasattr(metadata, '__dict__'):
                    from dataclasses import asdict
                    primary_structure['metadata'] = asdict(metadata)
        
        return result
        
    except Exception as e:
        logger.error(f"转换结构结果为JSON格式失败: {e}")
        return structure_result