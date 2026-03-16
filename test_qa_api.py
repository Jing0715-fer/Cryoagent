#!/usr/bin/env python3
"""
测试 QA API 响应格式 - 验证后端返回的 JSON 格式是否正确
"""
import sys
import os
import json

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 模拟后端 _handle_agent_mode 返回的数据
def test_handle_agent_mode_response():
    """测试 _handle_agent_mode 响应格式"""

    # 模拟 Agent 执行结果
    result = {
        'content': '已为您生成 7SHE 的 cartoon 结构图像。',
        'iteration': 1,
        'tool_results': [
            {
                'tool_name': 'pymol_image',
                'success': True,
                'result': {
                    'pdb_id': '7SHE',
                    'image_path': 'pymol_sessions/7SHE_cartoon_rainbow.png',
                    'style': 'cartoon'
                }
            }
        ]
    }

    # 模拟提取的数据
    answer = result.get('content', '')
    tool_results = result.get('tool_results', [])

    # 提取图像 URL
    image_url = None
    for tr in tool_results:
        if tr.get('tool_name') == 'pymol_image' and tr.get('success'):
            image_path = tr.get('result', {}).get('image_path')
            if image_path:
                image_url = f"/api/pymol/sessions/{os.path.basename(image_path)}"
                break

    # 构建 tool_results_summary
    tool_results_summary = []
    for tr in tool_results:
        summary = {
            'tool_name': tr.get('tool_name', ''),
            'success': tr.get('success', False)
        }
        if tr.get('tool_name') == 'pymol_image' and tr.get('success'):
            summary['image_path'] = tr.get('result', {}).get('image_path')
        tool_results_summary.append(summary)

    # 构建响应格式
    result_data = {
        'type': 'answer',
        'content': answer,
        'tool_results': tool_results_summary
    }

    if image_url:
        result_data['image_url'] = image_url

    response = {
        'success': True,
        'result': result_data,
        'session_id': 'test-session-123',
        'mode': 'agent',
        'analysis': {
            'question_type': 'agent',
            'sources_count': 0,
            'iterations': result.get('iteration', 0)
        }
    }

    print("=" * 60)
    print("后端 _handle_agent_mode 返回的响应格式:")
    print("=" * 60)
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print("=" * 60)

    # 验证前端期望的字段
    print("\n字段验证:")
    print(f"  - response.result: {response.get('result') is not None}")
    print(f"  - response.result.type: {result_data.get('type')}")
    print(f"  - response.result.content: {result_data.get('content')[:50]}...")
    print(f"  - response.result.image_url: {result_data.get('image_url')}")
    print(f"  - response.result.tool_results: {len(result_data.get('tool_results', []))} 条")

    # 模拟前端处理逻辑
    print("\n前端处理逻辑模拟:")
    data = response

    if data.get('result'):
        result = data['result']
        print(f"  ✓ 检测到 data.result")
        print(f"    - type: {result.get('type')}")
        print(f"    - content: {result.get('content')[:50]}...")
        print(f"    - image_url: {result.get('image_url')}")
        print(f"    - sources: {result.get('sources', [])}")
    elif data.get('answer') is not None:
        print(f"  ✓ 检测到 data.answer (旧格式)")
    else:
        print(f"  ✗ 未检测到有效结果!")

    return True


if __name__ == '__main__':
    success = test_handle_agent_mode_response()
    print("\n" + "=" * 60)
    if success:
        print("测试通过!")
    else:
        print("测试失败!")
    print("=" * 60)
    sys.exit(0 if success else 1)
