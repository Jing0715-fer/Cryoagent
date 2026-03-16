#!/usr/bin/env python3
"""
详细检查章节标记问题
"""

import lancedb
import pandas as pd

db = lancedb.connect('core/data/lancedb')
table = db.open_table("literature")
all_data = table.to_pandas()

print("📊 详细章节分析报告")
print("=" * 80)

# 1. 检查每个文献的章节完整性
print("\n1️⃣ 文献章节完整性检查")
print("-" * 80)

doc_ids = all_data['doc_id'].unique()
for doc_id in sorted(doc_ids):
    doc_data = all_data[all_data['doc_id'] == doc_id]
    sections = doc_data['section'].unique()

    print(f"\n文献 {doc_id}:")
    print(f"  总chunks: {len(doc_data)}")
    print(f"  章节: {', '.join(sections)}")

    # 检查是否有重复的章节类型
    section_counts = doc_data['section'].value_counts()
    has_methods = 'methods' in sections
    has_results = 'results' in sections

    # 标记潜在问题
    issues = []
    if not has_methods and len(doc_data) > 100:
        issues.append("缺少methods章节")
    if not has_results and len(doc_data) > 100:
        issues.append("缺少results章节")
    if 'full_text' in sections and len(sections) > 2:
        issues.append("有章节数据但仍包含full_text")

    if issues:
        print(f"  ⚠️ 问题: {'; '.join(issues)}")
    else:
        print(f"  ✅ 正常")

# 2. 检查chunk_index的分配逻辑
print("\n\n2️⃣ Chunk索引分配分析")
print("-" * 80)

for doc_id in sorted(doc_ids)[:5]:
    doc_data = all_data[all_data['doc_id'] == doc_id].sort_values('chunk_index')

    print(f"\n文献 {doc_id} - Chunk索引分配:")

    # 按section分组显示索引范围
    for section in doc_data['section'].unique():
        section_data = doc_data[doc_data['section'] == section]
        min_idx = section_data['chunk_index'].min()
        max_idx = section_data['chunk_index'].max()
        print(f"  {section:20s}: chunk_index {min_idx:3d} - {max_idx:3d} ({len(section_data)} chunks)")

# 3. 检查内容是否正确归属
print("\n\n3️⃣ 章节内容正确性抽样检查")
print("-" * 80)

# 随机抽几个methods chunk检查内容
methods_chunks = all_data[all_data['section'] == 'methods'].sample(min(3, len(all_data[all_data['section'] == 'methods'])))

print("\nMethods章节内容抽样:")
for i, row in methods_chunks.iterrows():
    print(f"\n  Doc {row['doc_id']}, Chunk {row['chunk_index']}:")
    content = row['full_text'][:300] if row['full_text'] else ""
    # 检查是否包含方法相关关键词
    method_keywords = ['method', 'protocol', 'buffer', 'purification', 'expression', 'incubated']
    has_method_content = any(kw in content.lower() for kw in method_keywords)
    print(f"    内容: {content}...")
    print(f"    方法关键词检测: {'✅ 包含' if has_method_content else '⚠️ 可能不含方法内容'}")

# 4. 检查是否有空章节
print("\n\n4️⃣ 空内容检查")
print("-" * 80)

empty_content = all_data[all_data['full_text'].isna() | (all_data['full_text'] == '')]
if len(empty_content) > 0:
    print(f"⚠️ 发现 {len(empty_content)} 个空内容chunks")
else:
    print("✅ 所有chunks都有内容")

# 5. 总结
print("\n\n📋 总结")
print("=" * 80)

total_docs = len(doc_ids)
total_chunks = len(all_data)
section_types = all_data['section'].nunique()

print(f"总文献数: {total_docs}")
print(f"总chunks: {total_chunks}")
print(f"章节类型数: {section_types}")
print(f"平均每文献chunks: {total_chunks/total_docs:.1f}")

# 检查是否所有文献都有章节数据
has_section_data = all_data.groupby('doc_id')['section'].nunique().mean()
print(f"平均每文献章节数: {has_section_data:.1f}")
