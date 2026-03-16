#!/usr/bin/env python3
"""
诊断检索问题 - 检查 Methods 章节内容是否真的存在
"""

import lancedb
import pandas as pd

db = lancedb.connect('core/data/lancedb')
table = db.open_table("literature")
all_data = table.to_pandas()

print("🔍 检索问题诊断")
print("=" * 80)

# 1. 检查 Methods 章节内容
print("\n1️⃣ Methods 章节内容检查")
print("-" * 80)

methods_data = all_data[all_data['section'] == 'methods']
print(f"总 Methods chunks: {len(methods_data)}")

if len(methods_data) > 0:
    # 随机抽样几个 methods chunks 查看内容
    samples = methods_data.sample(min(3, len(methods_data)))

    for i, (_, row) in enumerate(samples.iterrows(), 1):
        print(f"\n示例 {i}:")
        print(f"  Doc ID: {row['doc_id']}")
        print(f"  Chunk Index: {row['chunk_index']}")
        print(f"  Title: {row['title'][:80]}...")
        print(f"  内容前300字符:")
        content = row['full_text'][:300] if row['full_text'] else ""
        print(f"    {content}...")

        # 检查是否包含纯化相关关键词
        purification_keywords = ['purification', 'purified', 'expression', 'protocol',
                                  '纯化', '表达', 'protocol', 'procedure']
        has_purification = any(kw in content.lower() for kw in purification_keywords)
        print(f"  包含纯化关键词: {'✅ 是' if has_purification else '❌ 否'}")

# 2. 搜索包含GPR158的文档
print("\n\n2️⃣ GPR158相关内容搜索")
print("-" * 80)

gpr158_docs = all_data[all_data['full_text'].str.contains('GPR158', case=False, na=False)]
print(f"包含 'GPR158' 的chunks: {len(gpr158_docs)}")

if len(gpr158_docs) > 0:
    print("\n包含GPR158的文档分布:")
    section_counts = gpr158_docs['section'].value_counts()
    for section, count in section_counts.items():
        print(f"  {section}: {count} chunks")

    # 检查是否有GPR158 + purification的内容
    gpr158_purification = gpr158_docs[gpr158_docs['full_text'].str.contains('purification|purified|纯化', case=False, na=False)]
    print(f"\n包含 'GPR158' + 'purification/纯化' 的chunks: {len(gpr158_purification)}")

    if len(gpr158_purification) > 0:
        print("\n相关chunks:")
        for _, row in gpr158_purification.head(3).iterrows():
            print(f"  - {row['section']} chunk {row['chunk_index']}: {row['full_text'][:150]}...")

# 3. 检查查询扩展
print("\n\n3️⃣ 查询扩展测试")
print("-" * 80)

from core.agent_tools import _expand_method_query, _is_method_query

test_queries = [
    "GPR158的纯化方法",
    "GPR158 purification",
    "purification method of GPR158"
]

for q in test_queries:
    is_method = _is_method_query(q)
    expanded = _expand_method_query(q)
    print(f"\n查询: {q}")
    print(f"  是否方法查询: {is_method}")
    print(f"  扩展查询: {expanded}")

# 4. 直接向量检索测试
print("\n\n4️⃣ 向量检索测试")
print("-" * 80)

try:
    from core.lancedb_rag.rag import get_unified_rag

    rag = get_unified_rag()

    test_query = "GPR158 purification method"
    print(f"\n测试查询: {test_query}")

    # 测试1: 所有章节
    results_all = rag.retrieve_chunks(test_query, top_k=10, sections=None)
    print(f"  所有章节检索: {len(results_all)} 结果")
    if results_all:
        sections_found = [r.get('section', 'unknown') for r in results_all]
        print(f"    章节分布: {sections_found}")

    # 测试2: 仅 methods 章节
    results_methods = rag.retrieve_chunks(test_query, top_k=10, sections=['methods'])
    print(f"  Methods章节检索: {len(results_methods)} 结果")
    if results_methods:
        for r in results_methods[:3]:
            print(f"    - {r.get('section')}: {r.get('content', '')[:100]}...")

except Exception as e:
    print(f"  向量检索测试失败: {e}")
    import traceback
    traceback.print_exc()

print("\n✅ 诊断完成")
