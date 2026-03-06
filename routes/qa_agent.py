"""
QA Agent API Routes - 智能问答Agent API
"""
import sys
import os
import json
import asyncio
import logging

print(f"DEBUG: Loading routes.qa_agent from {__file__}")

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import jsonify, request, Blueprint, Response, current_app
from flask_login import current_user

logger = logging.getLogger(__name__)

bp = Blueprint('qa_agent', __name__, url_prefix='/api/qa/agent')


def get_current_user_id():
    """获取当前登录用户的ID，未登录返回None"""
    if current_user.is_authenticated:
        return current_user.id
    return None


def get_or_create_session(user_id: str = None) -> str:
    """获取或创建会话ID"""
    import uuid

    if not user_id:
        # 为未登录用户创建临时会话
        session_id = request.headers.get('X-Session-ID')
        if not session_id:
            session_id = str(uuid.uuid4())
    else:
        # 使用用户ID作为会话前缀
        session_id = f"{user_id}_{request.json.get('session_id', 'default') if request.is_json else 'default'}"

    return session_id


# 初始化工具注册表和Agent
def get_agent(skill_id: str = None):
    """获取Agent实例（延迟初始化）

    Args:
        skill_id: 可选的 Skill ID，用于加载特定 Skill
    """
    from core.agent_tools import get_tool_registry, initialize_tools
    from core.qa_agent import create_agent

    # 初始化工具
    registry = get_tool_registry()
    if not registry.get_all_tools():
        initialize_tools()

    return create_agent(registry, skill_id=skill_id)


@bp.route('', methods=['POST'])
def agent_process():
    """
    Agent主入口 - 处理用户问题
    支持 skill_id 参数来指定使用的 Skill
    """
    import uuid

    try:
        data = request.json
        question = data.get('question', '')
        session_id = data.get('session_id')  # 可选
        skill_id = data.get('skill_id')     # 可选 - 指定使用的 Skill
        user_id = get_current_user_id()

        # 如果没有session_id，创建一个新的
        if not session_id:
            session_id = str(uuid.uuid4())

        logger.info(f"[QA Agent] Question: {question[:50]}..., session: {session_id}, skill: {skill_id}")

        # 获取或初始化会话数据
        session_data = _get_session_data(session_id)

        # 检查是否需要处理澄清选项
        clarification_id = data.get('clarification_id')
        clarification_value = data.get('clarification_value')

        if clarification_id and clarification_value:
            # 处理用户选择的澄清选项
            session_data = _handle_clarification_response(
                session_id, clarification_id, clarification_value, session_data
            )

        # 准备上下文
        context = _get_context(session_id)

        # 异步执行Agent（传入 skill_id）
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                get_agent(skill_id=skill_id).process(question, context, session_data, skill_id=skill_id)
            )
            result = future.result()

        # 保存会话数据
        _save_session_data(session_id, session_data)

        # 如果是澄清类型，额外保存clarification_id
        if result.get('type') == 'clarification':
            session_data['last_clarification_id'] = result.get('clarification', {}).get('question', '')
            _save_session_data(session_id, session_data)

        # 保存问答历史
        _save_qa_history(user_id, session_id, question, result)

        # 构建响应
        response = {
            "success": True,
            "session_id": session_id,
            "result": result
        }

        # 如果使用了 Skill，添加 Skill 信息
        if skill_id:
            from core.skills import get_skill_registry
            skill_registry = get_skill_registry()
            skill = skill_registry.get_skill(skill_id)
            if skill:
                response["skill"] = {
                    "id": skill.id,
                    "name": skill.name,
                    "description": skill.description
                }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Error in agent_process: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/stream', methods=['GET'])
def agent_stream():
    """
    SSE流式输出Agent执行过程
    """
    import uuid

    try:
        question = request.args.get('question', '')
        session_id = request.args.get('session_id')

        if not session_id:
            session_id = str(uuid.uuid4())

        user_id = get_current_user_id()

        def generate():
            """生成SSE流"""
            # 发送开始消息
            yield f"data: {json.dumps({'type': 'start', 'session_id': session_id})}\n\n"

            try:
                # 获取Agent
                agent = get_agent()
                session_data = _get_session_data(session_id)
                context = _get_context(session_id)

                # 发送分析消息
                yield f"data: {json.dumps({'type': 'thinking', 'message': '正在分析问题...'})}\n\n"

                # 模拟流式输出（实际实现中可以根据迭代逐步发送）
                result = asyncio.run(agent.process(question, context, session_data))

                # 发送工具执行结果
                if result.get('tool_results'):
                    for tool_result in result['tool_results']:
                        yield f"data: {json.dumps({'type': 'tool_result', 'tool': tool_result['tool_name'], 'success': tool_result['success']})}\n\n"

                # 发送最终结果
                yield f"data: {json.dumps({'type': 'result', 'result': result})}\n\n"

            except Exception as e:
                logger.error(f"Error in stream: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

            # 发送结束消息
            yield f"data: {json.dumps({'type': 'end'})}\n\n"

        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )

    except Exception as e:
        logger.error(f"Error in agent_stream: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/tools', methods=['GET'])
def list_tools():
    """列出所有可用工具"""
    try:
        registry = get_agent().tool_registry
        tools = registry.list_tools()

        return jsonify({
            "success": True,
            "tools": tools,
            "count": len(tools)
        })

    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/history', methods=['GET'])
def get_history():
    """获取问答历史"""
    try:
        user_id = get_current_user_id()
        session_id = request.args.get('session_id')
        limit = request.args.get('limit', 20, type=int)

        if not user_id:
            return jsonify({
                "success": False,
                "error": "User not authenticated"
            }), 401

        from core.literature_db import get_qa_history
        history = get_qa_history(user_id=user_id, session_id=session_id, limit=limit)

        return jsonify({
            "success": True,
            "history": history,
            "count": len(history)
        })

    except Exception as e:
        logger.error(f"Error getting history: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/session', methods=['GET', 'DELETE'])
def manage_session():
    """管理会话"""
    try:
        session_id = request.args.get('session_id')

        if request.method == 'DELETE':
            # 清除会话
            if session_id and session_id in _sessions:
                del _sessions[session_id]
                return jsonify({"success": True, "message": "Session cleared"})

        # 获取会话数据
        session_data = _get_session_data(session_id) if session_id else {}

        return jsonify({
            "success": True,
            "session_id": session_id,
            "session_data": session_data
        })

    except Exception as e:
        logger.error(f"Error managing session: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================
# 会话管理
# ============================================

# 内存会话存储（生产环境应使用Redis等）
_sessions = {}


def _get_session_data(session_id: str) -> dict:
    """获取会话数据"""
    return _sessions.get(session_id, {})


def _save_session_data(session_id: str, data: dict):
    """保存会话数据"""
    _sessions[session_id] = data


def _get_context(session_id: str) -> list[Dict]:
    """获取会话上下文"""
    session_data = _get_session_data(session_id)
    return session_data.get('context', [])


def _handle_clarification_response(session_id: str, clarification_id: str,
                                   value: any, session_data: dict) -> dict:
    """处理用户对澄清问题的响应"""
    logger.info(f"Handling clarification: {clarification_id} = {value}")

    # 更新会话数据
    if not session_data:
        session_data = {}

    # 根据澄清类型处理值
    if clarification_id == "序列输入方式":
        session_data['pending_clarification'] = 'sequence_input'
        session_data['sequence_input_type'] = value
    elif clarification_id == "结构查询":
        session_data['pending_clarification'] = 'structure_query'
        session_data['structure_query_type'] = value
    else:
        # 通用处理
        session_data[f'clarification_{clarification_id}'] = value

    _save_session_data(session_id, session_data)

    return session_data


def _save_qa_history(user_id: str, session_id: str, question: str, result: dict):
    """保存问答历史"""
    try:
        from core.literature_db import save_qa_history

        if user_id:
            save_qa_history(
                user_id=user_id,
                session_id=session_id,
                question=question,
                answer=result.get('content', '') if result.get('type') == 'answer' else '',
                result_json=json.dumps(result)
            )
    except Exception as e:
        logger.error(f"Error saving QA history: {e}")
