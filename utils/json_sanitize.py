# utils/json_sanitize.py - 统一JSON序列化/字段清洗函数
import json
import logging
from typing import Any, Dict, List, Optional, Union
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------- JSON字段标准定义 ----------
FIELD_STANDARDS = {
    # 字段名: (期望类型, 最大长度, 默认值)
    'authors': ('list', 200, []),
    'keywords': ('list', 100, []),
    'tags': ('list', 100, []),
    'key_findings': ('list', 500, []),
    'cryoem_targets': ('dict', 1000, {}),
    'sections_json': ('dict', 10000, {}),
    'section_embeddings': ('dict', 5000, {}),
    'references': ('list', 1000, []),
    'cited_by': ('list', 1000, []),
    'related_structures': ('list', 100, []),
    'related_scripts': ('list', 100, []),
    'disciplines': ('list', 100, []),
    'search_text_blob': ('text', 30000, ''),
}

def ensure_json_serializable(value: Any, field_name: str = None) -> Any:
    """
    确保值是JSON可序列化的（统一版本）
    
    Args:
        value: 任意值
        field_name: 字段名（可选，用于日志和特殊处理）
        
    Returns:
        JSON可序列化的值
    """
    if value is None:
        return None
    
    # 如果是基本的JSON类型，直接返回
    if isinstance(value, (str, int, float, bool)):
        return value
    
    # 如果是datetime，转换为ISO格式字符串
    if isinstance(value, datetime):
        return value.isoformat()
    
    # 如果是列表，递归处理每个元素
    if isinstance(value, list):
        # 限制列表长度，防止过大
        max_length = 100 if field_name not in FIELD_STANDARDS else FIELD_STANDARDS[field_name][1]
        limited_list = value[:max_length] if len(value) > max_length else value
        
        return [
            ensure_json_serializable(item, f"{field_name}[{i}]" if field_name else None)
            for i, item in enumerate(limited_list)
        ]
    
    # 如果是字典，递归处理每个键值对
    if isinstance(value, dict):
        # 限制字典大小，防止过大
        max_items = 50 if field_name not in FIELD_STANDARDS else min(FIELD_STANDARDS[field_name][1] // 20, 100)
        limited_dict = dict(list(value.items())[:max_items])
        
        return {
            str(k): ensure_json_serializable(v, f"{field_name}.{k}" if field_name else None)
            for k, v in limited_dict.items()
        }
    
    # 尝试转换为字符串（处理数据库模型等对象）
    try:
        # 检查是否是数据库模型对象
        if hasattr(value, '__dict__'):
            # 尝试提取简单表示
            try:
                # 对于SQLAlchemy模型，避免循环引用
                if hasattr(value, 'id'):
                    return f"{value.__class__.__name__}(id={value.id})"
            except:
                pass
            return str(value)[:500]
        
        # 其他对象直接转换为字符串
        return str(value)[:500]
        
    except Exception as e:
        if field_name:
            logger.debug(f"无法序列化字段 {field_name} 的值: {e}")
        return None

def prepare_json_field(value: Any, field_name: str = None) -> Any:
    """
    准备JSON字段，确保可序列化并符合字段标准（统一版本）
    
    Args:
        value: 输入值
        field_name: 字段名，用于应用字段标准
        
    Returns:
        处理后的值，符合字段标准
    """
    if value is None:
        return None
    
    # 获取字段标准
    expected_type, max_length, default_value = FIELD_STANDARDS.get(
        field_name, ('auto', 1000, None)
    )
    
    # 如果已经是字符串，尝试解析为JSON
    if isinstance(value, str):
        # 空字符串直接返回默认值
        if not value.strip():
            return default_value
        
        # 尝试解析为JSON
        try:
            parsed = json.loads(value)
            # 递归处理解析后的值
            processed = prepare_json_field(parsed, field_name)
            return ensure_json_serializable(processed, field_name)
        except json.JSONDecodeError:
            # 如果不是JSON，根据字段类型处理
            if expected_type == 'list':
                # 根据字段类型创建适当的列表结构
                if field_name == 'authors':
                    return [{"name": value[:200]}]
                elif field_name == 'key_findings':
                    return [{"finding": value[:500]}]
                else:
                    return [value[:max_length]]
            
            elif expected_type == 'dict':
                # 根据字段类型创建适当的字典结构
                if field_name == 'cryoem_targets':
                    # 尝试提取结构ID
                    import re
                    pdb_ids = re.findall(r'\b([1-9][A-Z0-9]{3})\b', value.upper())
                    emdb_ids = re.findall(r'\b(EMD[-_]?\d+)\b', value.upper())
                    return {
                        'pdb_ids': list(set(pdb_ids))[:10],
                        'emdb_ids': list(set(emdb_ids))[:10]
                    }
                else:
                    return {"raw": value[:max_length]}
            
            elif expected_type == 'text':
                # 纯文本字段，直接返回（限制长度）
                return value[:max_length]
            
            else:
                # 未知类型，返回字符串（限制长度）
                return value[:max_length]
    
    # 如果不是字符串，直接确保可序列化
    result = ensure_json_serializable(value, field_name)
    
    # 应用字段类型约束
    if expected_type == 'list' and not isinstance(result, list):
        return [result] if result is not None else default_value
    
    if expected_type == 'dict' and not isinstance(result, dict):
        return {"value": result} if result is not None else default_value
    
    # 如果是list或dict但为空，返回默认值
    if result in ([], {}):
        return default_value
    
    return result

def sanitize_literature_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    清洗文献数据，确保所有字段符合标准
    
    Args:
        data: 原始文献数据
        
    Returns:
        清洗后的文献数据
    """
    if not isinstance(data, dict):
        return {}
    
    sanitized = {}
    
    for field, value in data.items():
        # 跳过空值
        if value is None:
            continue
            
        # 特殊处理字段
        if field in FIELD_STANDARDS:
            sanitized[field] = prepare_json_field(value, field)
        else:
            # 非JSON字段，直接处理
            if isinstance(value, (str, int, float, bool)):
                sanitized[field] = value
            else:
                # 尝试转换为字符串
                try:
                    sanitized[field] = str(value)[:1000]
                except:
                    sanitized[field] = None
    
    return sanitized

def normalize_authors(authors_value: Any) -> List[Dict[str, str]]:
    """
    标准化作者字段，统一格式为 [{"name": "作者1"}, {"name": "作者2"}]
    
    Args:
        authors_value: 原始作者值
        
    Returns:
        标准化的作者列表
    """
    if not authors_value:
        return []
    
    # 如果已经是标准格式的列表，直接返回
    if isinstance(authors_value, list):
        normalized = []
        for author in authors_value:
            if isinstance(author, dict) and 'name' in author:
                normalized.append({"name": str(author['name'])[:200]})
            elif isinstance(author, str) and author.strip():
                normalized.append({"name": author.strip()[:200]})
        return normalized
    
    # 如果是字符串，尝试解析
    if isinstance(authors_value, str):
        # 尝试解析JSON
        try:
            parsed = json.loads(authors_value)
            return normalize_authors(parsed)
        except json.JSONDecodeError:
            # 按逗号分隔
            authors = [a.strip() for a in authors_value.split(',') if a.strip()]
            return [{"name": author[:200]} for author in authors]
    
    # 其他类型，转换为字符串再处理
    return normalize_authors(str(authors_value))

def normalize_cryoem_targets(targets_value: Any) -> Dict[str, List[str]]:
    """
    标准化冷冻电镜目标字段
    
    Args:
        targets_value: 原始值
        
    Returns:
        标准格式: {"pdb_ids": [], "emdb_ids": []}
    """
    default = {"pdb_ids": [], "emdb_ids": []}
    
    if not targets_value:
        return default
    
    # 处理不同格式
    try:
        if isinstance(targets_value, dict):
            # 已经是字典格式
            result = default.copy()
            if 'pdb_ids' in targets_value:
                result['pdb_ids'] = [
                    str(id).strip().upper() for id in targets_value['pdb_ids'] 
                    if id and str(id).strip()
                ][:50]  # 限制数量
            if 'emdb_ids' in targets_value:
                result['emdb_ids'] = [
                    str(id).strip().upper() for id in targets_value['emdb_ids'] 
                    if id and str(id).strip()
                ][:50]
            return result
        
        elif isinstance(targets_value, str):
            # 尝试解析JSON
            try:
                parsed = json.loads(targets_value)
                return normalize_cryoem_targets(parsed)
            except json.JSONDecodeError:
                # 尝试提取结构ID
                import re
                pdb_ids = re.findall(r'\b([1-9][A-Z0-9]{3})\b', targets_value.upper())
                emdb_ids = re.findall(r'\b(EMD[-_]?\d+)\b', targets_value.upper())
                
                return {
                    "pdb_ids": list(set(pdb_ids))[:50],
                    "emdb_ids": list(set(emdb_ids))[:50]
                }
        
        elif isinstance(targets_value, list):
            # 列表格式，分类ID
            pdb_ids = []
            emdb_ids = []
            for item in targets_value:
                if isinstance(item, str):
                    item_upper = item.strip().upper()
                    if re.match(r'^[0-9][A-Z0-9]{3}$', item_upper):
                        pdb_ids.append(item_upper)
                    elif item_upper.startswith('EMD-'):
                        emdb_ids.append(item_upper)
            
            return {
                "pdb_ids": list(set(pdb_ids))[:50],
                "emdb_ids": list(set(emdb_ids))[:50]
            }
    except Exception as e:
        logger.debug(f"标准化cryoem_targets失败: {e}")
    
    return default

# ---------- 批量处理函数 ----------
def batch_prepare_json_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    批量准备JSON字段
    
    Args:
        data: 原始数据字典
        
    Returns:
        处理后的数据字典
    """
    result = {}
    
    for field, value in data.items():
        result[field] = prepare_json_field(value, field)
    
    return result

def validate_literature_data(data: Dict[str, Any], required_fields: List[str] = None) -> Dict[str, Any]:
    """
    验证文献数据
    
    Args:
        data: 文献数据
        required_fields: 必填字段列表
        
    Returns:
        验证结果: {"valid": bool, "errors": List[str], "sanitized_data": Dict}
    """
    errors = []
    
    # 检查必填字段
    if required_fields:
        for field in required_fields:
            if field not in data or data[field] is None or (isinstance(data[field], str) and not data[field].strip()):
                errors.append(f"必填字段 '{field}' 缺失或为空")
    
    # 验证字段类型
    for field, value in data.items():
        if field in FIELD_STANDARDS:
            expected_type, _, _ = FIELD_STANDARDS[field]
            processed = prepare_json_field(value, field)
            
            if expected_type == 'list' and not isinstance(processed, list):
                errors.append(f"字段 '{field}' 应为列表类型")
            elif expected_type == 'dict' and not isinstance(processed, dict):
                errors.append(f"字段 '{field}' 应为字典类型")
    
    # 清洗数据
    sanitized_data = sanitize_literature_data(data)
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "sanitized_data": sanitized_data
    }