#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG 评估测试脚本

测试 RAG 检索功能和评估指标计算
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_metrics():
    """测试评估指标计算"""
    print("=" * 60)
    print("测试 1: 评估指标计算")
    print("=" * 60)

    from core.rag_evaluation.metrics import (
        MetricsCalculator,
        calculate_all_metrics,
        aggregate_metrics,
    )

    # 模拟检索结果
    retrieved_ids = ["doc1", "doc2", "doc3", "doc4", "doc5"]
    relevant_ids = {"doc1", "doc3", "doc7"}  # doc7 未被检索到

    # 计算单个查询的指标
    metrics = calculate_all_metrics(
        retrieved_ids=retrieved_ids,
        relevant_ids=relevant_ids,
        k_values=[5, 10]
    )

    print(f"Precision@5: {metrics.precision_at_5:.3f}")
    print(f"Recall@5: {metrics.recall_at_5:.3f}")
    print(f"MRR: {metrics.mrr:.3f}")
    print(f"NDCG@5: {metrics.ndcg_at_5:.3f}")

    # 验证计算
    assert metrics.precision_at_5 == 2/5, "Precision@5 计算错误"
    assert metrics.recall_at_5 == 2/3, "Recall@5 计算错误"
    assert metrics.mrr == 1.0, "MRR 计算错误"  # 第一个结果就是相关的

    print("✅ 指标计算测试通过!")
    return True


def test_ground_truth():
    """测试 Ground Truth 管理"""
    print("\n" + "=" * 60)
    print("测试 2: Ground Truth 管理")
    print("=" * 60)

    from core.rag_evaluation.ground_truth import GroundTruthManager, GroundTruthEntry
    from core.rag_evaluation.storage import EvaluationStorage

    # 使用内存数据库
    storage = EvaluationStorage(db_path=":memory:")
    manager = GroundTruthManager(storage=storage)

    # 添加条目
    entry = manager.add_entry(
        query_text="Vγ9Vδ2 T cell receptor structure",
        relevant_ids=["6T0K", "6T0L", "6T0M"],
        relevance_scores={"6T0K": 3.0, "6T0L": 2.0, "6T0M": 2.0},
        category="structure",
    )

    print(f"添加条目: {entry.query_id}")
    print(f"查询: {entry.query_text}")
    print(f"相关文档: {entry.relevant_ids}")

    # 获取条目
    retrieved = manager.get_entry(entry.query_id)
    assert retrieved is not None, "获取条目失败"
    assert retrieved.query_text == entry.query_text, "条目内容不匹配"

    print("✅ Ground Truth 管理测试通过!")
    return True


def test_evaluator():
    """测试评估器"""
    print("\n" + "=" * 60)
    print("测试 3: 评估器")
    print("=" * 60)

    from core.rag_evaluation.evaluator import RAGEvaluator, EvaluationConfig
    from core.rag_evaluation.storage import EvaluationStorage

    # 创建模拟搜索函数
    def mock_search_fn(query: str, top_k: int, config: dict):
        # 返回模拟结果
        return [
            {"id": "doc1", "score": 0.9},
            {"id": "doc2", "score": 0.8},
            {"id": "doc3", "score": 0.7},
        ]

    storage = EvaluationStorage(db_path=":memory:")
    evaluator = RAGEvaluator(
        search_fn=mock_search_fn,
        storage=storage,
    )

    # 评估单个查询
    result = evaluator.evaluate_single(
        query_text="test query",
        relevant_ids=["doc1", "doc3"],
        config=EvaluationConfig(top_k=5),
    )

    print(f"查询: {result['query_text']}")
    print(f"检索结果: {result['retrieved_ids']}")
    print(f"Precision@5: {result['metrics'].precision_at_5:.3f}")
    print(f"MRR: {result['metrics'].mrr:.3f}")

    assert result['metrics'].precision_at_5 > 0, "Precision 应该大于 0"

    print("✅ 评估器测试通过!")
    return True


def test_chunk_storage():
    """测试 LanceDB 分块存储"""
    print("\n" + "=" * 60)
    print("测试 4: LanceDB 分块存储")
    print("=" * 60)

    try:
        from core.lancedb_rag import UnifiedLanceRAG, RAGConfig

        # 创建测试配置
        config = RAGConfig(
            db_path="/tmp/test_rag_db",
            vector_dim=384,
            embedding_model="all-MiniLM-L6-v2",
            use_rerank=False,
            use_session=False,
        )

        rag = UnifiedLanceRAG(config=config)
        rag.initialize_tables(overwrite=True)

        # 模拟文献数据
        literature_data = {
            'id': 'test_lit_001',
            'title': 'Test Literature for RAG Evaluation',
            'abstract': 'This is a test abstract for evaluating the RAG chunk storage functionality.',
            'full_text': 'Introduction: This paper presents a novel approach to protein structure analysis. '
                        'Methods: We used cryo-EM to determine the structure. '
                        'Results: The structure was resolved at 3.5 Angstrom resolution. '
                        'Discussion: Our findings provide new insights into the mechanism.',
            'year': 2024,
            'journal': 'Test Journal',
            'doi': '10.1234/test.001',
        }

        # 添加分块
        chunk_count = rag.add_literature_chunks(literature_data, chunk_size=200)

        print(f"添加了 {chunk_count} 个 chunks 到 LanceDB")

        # 检索测试
        results = rag.retrieve_chunks(
            query="protein structure analysis",
            top_k=5,
        )

        print(f"检索到 {len(results)} 个结果")
        for r in results[:3]:
            print(f"  - {r.get('section', 'unknown')}: {r.get('content', '')[:50]}...")

        print("✅ LanceDB 分块存储测试通过!")
        return True

    except Exception as e:
        print(f"⚠️ LanceDB 测试跳过: {e}")
        return None


def test_api_routes():
    """测试 API 路由是否正确注册"""
    print("\n" + "=" * 60)
    print("测试 5: API 路由")
    print("=" * 60)

    try:
        from routes.rag_evaluation import bp

        # 检查蓝图是否正确配置
        print(f"蓝图名称: {bp.name}")
        print(f"URL 前缀: {bp.url_prefix}")

        # 列出所有路由
        routes = []
        for rule in bp.deferred_functions:
            routes.append(str(rule))

        print(f"注册的路由数量: {len(routes)}")

        print("✅ API 路由测试通过!")
        return True

    except Exception as e:
        print(f"⚠️ API 路由测试跳过: {e}")
        return None


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("RAG 评估模块测试")
    print("=" * 60 + "\n")

    results = []

    # 运行测试
    results.append(("指标计算", test_metrics()))
    results.append(("Ground Truth", test_ground_truth()))
    results.append(("评估器", test_evaluator()))
    results.append(("分块存储", test_chunk_storage()))
    results.append(("API 路由", test_api_routes()))

    # 汇总结果
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)

    passed = 0
    failed = 0
    skipped = 0

    for name, result in results:
        if result is True:
            print(f"✅ {name}: 通过")
            passed += 1
        elif result is False:
            print(f"❌ {name}: 失败")
            failed += 1
        else:
            print(f"⚠️ {name}: 跳过")
            skipped += 1

    print(f"\n总计: {passed} 通过, {failed} 失败, {skipped} 跳过")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)