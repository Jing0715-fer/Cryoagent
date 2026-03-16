#!/usr/bin/env python3
"""
检查LanceDB索引中的章节标记是否正确
"""

import lancedb
import json

# 连接到LanceDB
db_path = 'core/data/lancedb'
print(f"正在连接到LanceDB: {db_path}")

try:
    db = lancedb.connect(db_path)
    table = db.open_table("literature")

    # 获取所有数据
    all_data = table.to_pandas()

    print(f"\n✅ 总记录数: {len(all_data)}")
    print("=" * 80)

    # 1. 统计章节分布
    section_counts = all_data['section'].value_counts()
    print("\n📊 章节分布统计:")
    print("-" * 40)
    for section, count in section_counts.items():
        print(f"  {section:20s}: {count:5d} chunks ({count/len(all_data)*100:.1f}%)")

    # 2. 按文献统计
    print("\n📚 按文献统计章节:")
    print("=" * 80)

    doc_ids = all_data['doc_id'].unique()
    for doc_id in sorted(doc_ids)[:5]:  # 只看前5篇文献
        doc_data = all_data[all_data['doc_id'] == doc_id]
        print(f"\n文献 ID: {doc_id}")
        print("-" * 40)

        # 获取该文献的所有章节
        sections = doc_data['section'].unique()
        for section in sections:
            section_data = doc_data[doc_data['section'] == section]
            print(f"  章节 '{section}': {len(section_data)} chunks")

            # 显示第一个chunk的内容预览
            first_chunk = section_data.iloc[0]
            content_preview = first_chunk['full_text'][:150] if first_chunk['full_text'] else ""
            if content_preview:
                print(f"    预览: {content_preview}...")

    # 3. 检查是否有方法类章节
    print("\n🔬 方法类章节检查:")
    print("=" * 80)

    methods_keywords = ['methods', 'method', 'experimental', 'protocol', 'procedure']
    method_sections = all_data[all_data['section'].str.lower().isin(methods_keywords)]

    print(f"找到 {len(method_sections)} 个方法类chunks")

    if len(method_sections) > 0:
        # 显示几个方法类chunk的示例
        print("\n方法类chunk示例:")
        for i, row in method_sections.head(3).iterrows():
            print(f"\n  Doc ID: {row['doc_id']}, Section: {row['section']}")
            print(f"  Chunk Index: {row['chunk_index']}")
            print(f"  内容前200字符:")
            content = row['full_text'][:200] if row['full_text'] else ""
            print(f"    {content}...")

    # 4. 检查章节边界（chunk_index连续性）
    print("\n🔗 章节边界检查:")
    print("=" * 80)

    for doc_id in sorted(doc_ids)[:3]:
        doc_data = all_data[all_data['doc_id'] == doc_id].sort_values('chunk_index')

        print(f"\n文献 {doc_id}:")
        sections_in_doc = doc_data['section'].unique()

        for section in sections_in_doc:
            section_chunks = doc_data[doc_data['section'] == section].sort_values('chunk_index')
            chunk_indices = section_chunks['chunk_index'].tolist()

            if len(chunk_indices) > 1:
                # 检查是否连续
                is_continuous = chunk_indices == list(range(min(chunk_indices), max(chunk_indices)+1))
                print(f"  章节 '{section}': {len(chunk_indices)} chunks, 索引: {min(chunk_indices)}-{max(chunk_indices)}")
                print(f"    连续性: {'✅ 正常' if is_continuous else '⚠️ 不连续'}")

    # 5. 检查metadata字段
    print("\n📋 Metadata字段检查:")
    print("=" * 80)

    # 检查第一条记录的metadata
    first_record = all_data.iloc[0]
    print(f"第一条记录 ID: {first_record['id']}")
    print(f"Section字段: {first_record['section']}")
    print(f"Chunk Index: {first_record['chunk_index']}")
    print(f"Doc Type: {first_record.get('doc_type', 'N/A')}")

    # 检查metadata JSON
    metadata_str = first_record.get('metadata', '{}')
    if isinstance(metadata_str, str):
        try:
            metadata = json.loads(metadata_str)
            print(f"Metadata中的section: {metadata.get('section', 'N/A')}")
        except:
            print(f"Metadata (raw): {metadata_str[:100]}...")

    print("\n✅ 检查完成!")

except Exception as e:
    print(f"❌ 检查失败: {e}")
    import traceback
    traceback.print_exc()
