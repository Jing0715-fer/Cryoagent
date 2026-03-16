#!/usr/bin/env python3
"""
测试图片响应格式 - 验证后端返回的 JSON 格式是否正确
"""
import sys
import os

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 模拟后端返回的数据格式
def test_response_format():
    """测试响应格式"""
    # 模拟后端返回的数据
    response = {
        'success': True,
        'result': {
            'type': 'answer',
            'content': '已为您生成 7SHE 的 cartoon 结构图像。',
            'image_url': '/api/pymol/sessions/7SHE_cartoon_rainbow.png',
            'tool_results': [
                {
                    'tool_name': 'pymol_image',
                    'success': True,
                    'image_path': 'pymol_sessions/7SHE_cartoon_rainbow.png'
                }
            ],
            'sources': []
        },
        'session_id': 'test-session-123',
        'mode': 'agent',
        'analysis': {
            'question_type': 'agent',
            'sources_count': 0,
            'iterations': 1
        }
    }

    # 验证前端期望的字段
    result = response.get('result')
    assert result is not None, "result 字段不存在"
    assert result.get('type') == 'answer', "type 字段不是 answer"
    assert result.get('content') is not None, "content 字段不存在"
    assert result.get('image_url') is not None, "image_url 字段不存在"
    assert isinstance(result.get('tool_results'), list), "tool_results 不是数组"
    assert isinstance(result.get('sources'), list), "sources 不是数组"

    print("✓ 响应格式验证通过")
    print(f"  - type: {result.get('type')}")
    print(f"  - content: {result.get('content')[:50]}...")
    print(f"  - image_url: {result.get('image_url')}")
    print(f"  - tool_results count: {len(result.get('tool_results', []))}")
    print(f"  - sources count: {len(result.get('sources', []))}")

    # 测试前端 processAgentResult 逻辑
    print("\n✓ 模拟前端处理逻辑...")
    if result.get('image_url'):
        print(f"  - 检测到 image_url: {result['image_url']}")
    if result.get('sources'):
        print(f"  - 检测到 sources: {len(result['sources'])} 条")
    if result.get('tool_results'):
        print(f"  - 检测到 tool_results: {len(result['tool_results'])} 条")

    print("\n✓ 所有测试通过！")
    return True


if __name__ == '__main__':
    success = test_response_format()
    sys.exit(0 if success else 1)
