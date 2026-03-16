#!/usr/bin/env python
"""调试文献 4 为什么没有进入最终结果"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

import logging
logging.basicConfig(level=logging.WARNING)

# 复制 _score_method_content 函数
def score_method_content(text: str) -> float:
    """计算方法内容得分"""
    if not text:
        return 0.0

    text_lower = text.lower()
    score = 0.0

    method_keywords = {
        'purification': 3.0, 'purified': 2.0, 'chromatography': 3.0,
        'column': 1.5, 'buffer': 1.5, 'centrifug': 2.0, 'filtration': 1.5,
        'detergent': 2.0, 'solubilization': 2.0, 'expression': 2.5,
        'transfection': 2.0, 'transfected': 1.5, 'cultured': 1.5,
        'culture': 1.0, 'protocol': 2.0, 'procedure': 1.5, 'performed': 1.0,
        'incubated': 1.5, 'washed': 1.0, 'collected': 1.0, 'prepared': 1.0,
        'sd-page': 2.0, 'western': 2.0, 'blot': 1.5, 'assay': 1.5,
        'measurement': 1.0, 'analysis': 0.5, 'reagent': 1.0, 'kit': 1.0,
        'antibody': 1.0,
    }

    for keyword, weight in method_keywords.items():
        if keyword in text_lower:
            score += weight

    return score


def debug_lit4():
    """追踪文献 4 在多阶段搜索中的命运"""

    query = "GPR158 的纯化方法"

    print("=" * 80)
    print(f"查询：{query}")
    print("=" * 80)

    # 使用 UnifiedLanceRAG 进行搜索（正确的方式）
    from core.lancedb_rag.rag import get_unified_rag

    rag = get_unified_rag()
    rag.initialize_tables()

    # 执行向量搜索
    results = rag.search(
        query=query,
        top_k=100,
        search_type="vector",
        include_structure=False,
        use_rerank=False,
    )

    all_results = results.get('results', [])
    print(f"\n向量搜索返回 {len(all_results)} 个结果")

    # 找出文献 4 和文献 5 的所有 chunk
    lit4_chunks = [r for r in all_results if r.get('document', {}).get('doc_id') == '4']
    lit5_chunks = [r for r in all_results if r.get('document', {}).get('doc_id') == '5']

    print(f"\n前 100 个结果中：")
    print(f"  文献 4: {len(lit4_chunks)} 个 chunks")
    print(f"  文献 5: {len(lit5_chunks)} 个 chunks")

    if len(lit4_chunks) == 0:
        print("\n⚠️ 警告: 文献 4 在向量搜索结果中未找到！")
        print("   这意味着文献 4 的内容可能与查询不够相似")

    # 计算每个 chunk 的方法得分
    print(f"\n--- 文献 4 的 chunk 详情 ---")
    lit4_with_scores = []
    for i, chunk in enumerate(lit4_chunks):
        content = chunk.get('document', {}).get('full_text', '')
        method_score = score_method_content(content)
        lit4_with_scores.append({
            'id': chunk.get('id'),
            'score': chunk.get('score'),  # 向量距离分数
            'method_score': method_score,
            'content_preview': content[:100]
        })
        print(f"  Chunk {i}: id={chunk.get('id')}, vector_score={chunk.get('score'):.4f}, method_score={method_score}")

    print(f"\n--- 文献 5 的 chunk 详情 ---")
    lit5_with_scores = []
    for i, chunk in enumerate(lit5_chunks):
        content = chunk.get('document', {}).get('full_text', '')
        method_score = score_method_content(content)
        lit5_with_scores.append({
            'id': chunk.get('id'),
            'score': chunk.get('score'),
            'method_score': method_score,
            'content_preview': content[:100]
        })
        print(f"  Chunk {i}: id={chunk.get('id')}, vector_score={chunk.get('score'):.4f}, method_score={method_score}")

    # 检查通过方法分数过滤的情况
    min_method_score = 15
    lit4_passing = [c for c in lit4_with_scores if c['method_score'] >= min_method_score]
    lit5_passing = [c for c in lit5_with_scores if c['method_score'] >= min_method_score]

    print(f"\n--- 通过方法分数过滤 (min_score={min_method_score}) ---")
    print(f"  文献 4: {len(lit4_passing)}/{len(lit4_chunks)} 个 chunks 通过")
    print(f"  文献 5: {len(lit5_passing)}/{len(lit5_chunks)} 个 chunks 通过")

    # 模拟排序逻辑
    print(f"\n--- 模拟排序逻辑 ---")
    all_results_scored = []
    for chunk in lit4_with_scores:
        all_results_scored.append({
            'id': chunk['id'],
            'doc_id': 4,
            'score': chunk['score'],
            'method_score': chunk['method_score']
        })
    for chunk in lit5_with_scores:
        all_results_scored.append({
            'id': chunk['id'],
            'doc_id': 5,
            'score': chunk['score'],
            'method_score': chunk['method_score']
        })

    # 过滤
    filtered = [r for r in all_results_scored if r['method_score'] >= min_method_score]

    # 排序 (method_score, score) 降序
    sorted_results = sorted(
        filtered,
        key=lambda x: (x['method_score'], x['score']),
        reverse=True
    )

    print(f"\n排序后的前 25 个结果：")
    for i, r in enumerate(sorted_results[:25]):
        marker = " <-- 文献 4" if r['doc_id'] == 4 else ""
        print(f"  {i+1}. doc_id={r['doc_id']}, method_score={r['method_score']}, vector_score={r['score']:.4f}{marker}")

    # 取前 20 个
    top20 = sorted_results[:20]
    lit4_in_top20 = [r for r in top20 if r['doc_id'] == 4]
    lit5_in_top20 = [r for r in top20 if r['doc_id'] == 5]

    print(f"\n--- 前 20 个结果中的分布 ---")
    print(f"  文献 4: {len(lit4_in_top20)} 个 chunks")
    print(f"  文献 5: {len(lit5_in_top20)} 个 chunks")

    if len(lit4_in_top20) == 0 and len(lit4_passing) > 0:
        print(f"\n❌ 文献 4 虽然通过了方法分数过滤，但没有进入前 20！")
        print(f"   原因：排序时按 (method_score, score) 排序")
        print(f"   文献 4 的 method_score 可能不够高，或者 vector_score 较低")

    # 统计前 20 中各文献的分布
    doc_id_counts = {}
    for r in top20:
        doc_id_counts[r['doc_id']] = doc_id_counts.get(r['doc_id'], 0) + 1

    print(f"\n前 20 个结果按文献分布：")
    for doc_id, count in sorted(doc_id_counts.items(), key=lambda x: -x[1]):
        print(f"  文献 {doc_id}: {count} 个 chunks")


if __name__ == '__main__':
    debug_lit4()
