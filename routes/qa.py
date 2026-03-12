"""
QA System API Routes - 多阶段智能问答
"""
import sys
import os
import json
import logging
import logging.config

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)
# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import jsonify, request, Blueprint, Response
from flask_login import current_user
from utils.ai_client import get_ai_client, load_ai_config
from core.literature_index import EntityType
from core.literature_db import get_literature_entry

bp = Blueprint('qa', __name__, url_prefix='/api/qa')


def get_current_user_id():
    """获取当前登录用户的ID，未登录返回None"""
    if current_user.is_authenticated:
        return current_user.id
    return None


def _handle_agent_mode(question: str, session_id: str, original_data: dict, max_tokens: int = None):
    """
    处理 Agent 模式 - 调用 Agent 端点
    """
    import logging
    import uuid
    logger = logging.getLogger(__name__)

    try:
        # 准备调用 Agent 的参数
        skill_id = original_data.get('skill_id')

        # 获取会话历史作为上下文
        context = []
        try:
            from core.literature_db import get_qa_chat_history_by_session
            user_id = get_current_user_id()
            if session_id:
                history = get_qa_chat_history_by_session(session_id, user_id)
                # 将历史转换为上下文格式
                for h in history[-5:]:  # 只取最近5条
                    context.append({
                        'type': 'user',
                        'content': h.question
                    })
                    if h.answer:
                        context.append({
                            'type': 'assistant',
                            'content': h.answer
                        })
                print(f"[QA v2] 获取到 {len(history)} 条历史记录，上下文: {len(context)} 条")
        except Exception as e:
            logger.warning(f"获取历史失败: {e}")

        def run_agent():
            # 不使用 app_context()，避免阻塞
            from core.agent_tools import get_tool_registry, initialize_tools
            from core.qa_agent import create_agent

            # 初始化工具
            registry = get_tool_registry()
            if not registry.get_all_tools():
                initialize_tools()

            # 创建 Agent 并处理问题
            agent = create_agent(registry, skill_id=skill_id)

            # 使用更安全的 asyncio 方式运行，避免与 PyMOL 线程冲突
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            if loop.is_running():
                # 如果 loop 正在运行（不太可能在同步 Flask 中），创建新的
                return asyncio.run(agent.process(question, context, {}, skill_id=skill_id, max_tokens=max_tokens))
            else:
                return loop.run_until_complete(agent.process(question, context, {}, skill_id=skill_id, max_tokens=max_tokens))

        # 直接执行 Agent，不使用线程池
        try:
            # 5分钟超时
            logger.info("[QA v2] 开始执行 Agent...")
            result = run_agent()
            logger.info(f"[QA v2] Agent 执行完成！result type: {type(result)}")
        except Exception as e:
            import traceback
            logger.error(f"Agent 执行异常: {e}")
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': f'Agent 执行失败: {str(e)}'
            }), 500

        # 从 Agent 结果中提取信息
        print(f"[QA v2] 开始提取 Agent 结果...")
        answer = result.get('content', '')
        tool_results = result.get('tool_results', [])
        print(f"[QA v2] 提取完成：content_len={len(answer) if answer else 0}, tool_results={len(tool_results)}")

        # 打印 tool_results 的类型和内容
        print(f"[QA v2] tool_results 类型: {type(tool_results)}")
        if tool_results:
            print(f"[QA v2] 第一个 tool_result: {str(tool_results[0])[:500]}")
        print(f"[QA v2] Agent result 完整数据：{json.dumps(result, ensure_ascii=False)[:1000]}...")

        # 提取图像 URL（如果有）
        image_url = None
        logger.info(f"[QA v2] tool_results count: {len(tool_results)}")
        for tr in tool_results:
            logger.info(f"[QA v2] tool: {tr.get('tool_name')}, success: {tr.get('success')}")
            if tr.get('tool_name') == 'pymol_image' and tr.get('success'):
                # 数据结构: result.result.image_path (嵌套两层)
                result_data = tr.get('result', {})
                logger.info(f"[QA v2] result_data level 1: {result_data}")
                # 处理嵌套的 result 结构
                if 'result' in result_data:
                    result_data = result_data.get('result', {})
                    logger.info(f"[QA v2] result_data level 2: {result_data}")
                image_path = result_data.get('image_path')
                logger.info(f"[QA v2] pymol_image result: image_path={image_path}")
                if image_path:
                    # 使用 os.path.basename 提取文件名
                    filename = os.path.basename(image_path)

                    # 使用统一的 sessions 目录（与 routes/pymol.py 一致）
                    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    sessions_dir = os.path.join(project_root, 'pymol_sessions')

                    # 检查文件是否存在，如果不存在尝试小写版本
                    if not os.path.exists(os.path.join(sessions_dir, filename)):
                        filename_lower = filename.lower()
                        if os.path.exists(os.path.join(sessions_dir, filename_lower)):
                            filename = filename_lower
                        else:
                            logger.warning(f"Image file not found: {filename}")

                    image_url = f"/api/pymol/sessions/{filename}"
                    break

        # 提取来源
        sources = []
        for tr in tool_results:
            # 文献来源
            if tr.get('tool_name') == 'search_literature' and tr.get('success'):
                lit_results = tr.get('result', {}).get('results', [])
                for lit in lit_results:  # 显示全部来源
                    sources.append({
                        'type': 'literature',
                        'id': str(lit.get('id', '')),
                        'title': lit.get('title', '')[:100],
                        'content': lit.get('content', '')  # 添加 content 字段用于前端过滤
                    })
            # 结构来源
            if tr.get('tool_name') == 'search_structures' and tr.get('success'):
                struct_results = tr.get('result', {}).get('results', [])
                for struct in struct_results:  # 显示全部来源
                    sources.append({
                        'type': 'structure',
                        'id': struct.get('pdb_id', ''),
                        'title': struct.get('title', '')[:100]
                    })

        print(f"[QA v2] Agent 模式完成, image_url: {image_url}, sources: {len(sources)}")
        print(f"[QA v2] 准备保存历史记录...")

        # 保存历史（截断过大的结果）
        # 支持 session_id 方式保存历史（未登录用户也能看到当前会话的历史）
        try:
            from core.literature_db import save_qa_history
            user_id = get_current_user_id()
            print(f"[QA v2] user_id = {user_id}, session_id = {session_id}")
            print(f"[QA v2] 开始保存历史，result 类型: {type(result)}")
            # 截断过大的结果JSON，防止数据库存储失败
            result_json_str = json.dumps(result)
            max_history_size = 500000  # 500KB 限制
            if len(result_json_str) > max_history_size:
                # 创建一个精简版本，保留完整的数据来源信息
                truncated_result = {
                    'content': result.get('content', ''),
                    'iteration': result.get('iteration', 0),
                    'tool_results': []
                }
                # 保留工具名称、成功状态和结果数据（用于显示来源）
                for tr in result.get('tool_results', []):
                    tool_name = tr.get('tool_name', '')
                    truncated_tr = {
                        'tool_name': tool_name,
                        'success': tr.get('success', False)
                    }
                    # 保留搜索结果用于显示来源
                    if tool_name in ['search_literature', 'search_structures']:
                        truncated_tr['result'] = tr.get('result', {})
                    # 保留图片信息
                    if tool_name == 'pymol_image':
                        truncated_tr['result'] = {
                            'pdb_id': tr.get('result', {}).get('pdb_id'),
                            'image_path': tr.get('result', {}).get('image_path')
                        }
                    truncated_result['tool_results'].append(truncated_tr)
                result_json_str = json.dumps(truncated_result)
                logger.warning(f"结果数据过大，已截断保存: {len(result_json_str)} bytes")

            save_qa_history(
                question=question,
                answer=answer,
                session_id=session_id,
                user_id=user_id,  # 可以为 None，但 session_id 会保存
                result_json=result_json_str
            )
            print(f"[QA v2] 历史保存成功")
        except Exception as e:
            logger.warning(f"保存历史失败: {e}")

        # 返回结果 - 不返回完整的tool_results以减小响应大小
        # 只返回工具调用摘要
        tool_results_summary = []
        for tr in tool_results:
            summary = {
                'tool_name': tr.get('tool_name', ''),
                'success': tr.get('success', False)
            }
            # 如果是图片工具，包含image_path
            if tr.get('tool_name') == 'pymol_image' and tr.get('success'):
                summary['image_path'] = tr.get('result', {}).get('image_path')
            # 如果是搜索工具，包含结果数量
            if tr.get('tool_name') in ['search_literature', 'search_structures'] and tr.get('success'):
                summary['count'] = tr.get('result', {}).get('count', 0)
            tool_results_summary.append(summary)

        # 构建符合前端期望的响应格式
        # 格式：{'success': True, 'result': {type, content, image_url, tool_results}, 'session_id': ...}
        result_data = {
            'type': 'answer',
            'content': answer,
            'tool_results': tool_results_summary
        }

        # 如果有图片，添加到 result 中
        if image_url:
            result_data['image_url'] = image_url

        # 如果有来源，也添加到 result 中
        if sources:
            result_data['sources'] = sources

        response = {
            'success': True,
            'result': result_data,
            'session_id': session_id,
            'mode': 'agent',
            'analysis': {
                'question_type': 'agent',
                'sources_count': len(sources),
                'iterations': result.get('iteration', 0)
            }
        }

        # 添加调试日志
        logger.info(f"[QA v2] 返回响应：success=True, result.type={result_data.get('type')}, content_len={len(answer) if answer else 0}, image_url={image_url}")

        # 尝试序列化响应，捕获可能的错误
        try:
            json.dumps(response)  # 测试是否可以正常序列化
            logger.info("[QA v2] JSON 序列化成功")
        except TypeError as je:
            logger.error(f"[QA v2] JSON 序列化失败：{je}")
            # 如果序列化失败，返回错误响应
            return jsonify({
                'success': False,
                'error': f'响应序列化失败：{str(je)}'
            }), 500

        logger.info("[QA v2] 准备返回 jsonify 响应")
        response_obj = jsonify(response)
        logger.info("[QA v2] jsonify 完成，准备返回")
        return response_obj

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"Agent 模式错误: {e}")
        return jsonify({
            'error': f'Agent 处理失败: {str(e)}',
            'fallback': '请尝试使用 RAG 模式'
        }), 500


@bp.route('/ask-v2', methods=['POST'])
def ask_question_v2():
    """
    智能问答 v2 - 基于问题类型的智能路由
    自动选择 RAG 或 Agent 模式
    """
    import logging
    import json
    import re
    import uuid
    logger = logging.getLogger(__name__)
    print(f"[QA v2] 收到问题...")

    try:
        data = request.json
        question = data.get('question', '')
        literature_id = data.get('literature_id')
        session_id = data.get('session_id')  # 获取session_id
        model_id = data.get('model_id')  # 获取模型ID
        force_mode = data.get('mode', 'auto')  # 强制模式: auto, rag, agent
        print(f"[QA v2] 收到session_id: {session_id}, model_id: {model_id}, force_mode: {force_mode}")

        # 如果没有session_id，创建一个新的
        if not session_id:
            session_id = str(uuid.uuid4())
            print(f"[QA v2] 创建新session: {session_id}")

        # 修复飞书消息的JSON格式问题 {"text": "实际问题"}
        if isinstance(question, str):
            question_stripped = question.strip()
            if question_stripped.startswith('{') and '"text"' in question_stripped:
                try:
                    import json
                    q_data = json.loads(question_stripped)
                    if isinstance(q_data, dict) and 'text' in q_data:
                        question = q_data['text']
                        print(f"[QA v2] 解析JSON格式问题: {question[:50]}")
                except:
                    pass
            # 处理外层引号包裹的JSON {"text":"..."}
            elif question_stripped.startswith('"') and question_stripped.endswith('"'):
                try:
                    import json
                    inner = question_stripped[1:-1].replace('\\"', '"').replace('\\\\', '\\')
                    q_data = json.loads(inner)
                    if isinstance(q_data, dict) and 'text' in q_data:
                        question = q_data['text']
                        print(f"[QA v2] 解析外层引号JSON格式问题: {question[:50]}")
                except:
                    pass

        if not question:
            return jsonify({'error': 'Question is required'}), 400

        question_lower = question.lower()

        # ====== 简化模式：始终使用 Agent + RAG ======
        # 忽略 force_mode 参数，始终使用 Agent 模式
        use_agent_mode = True
        rag_needed = True

        # 提取明确的 PDB/EMDB ID
        pdb_pattern = r'[1-9][A-Za-z0-9]{3}'
        emdb_pattern = r'EMD[A-Z]?\d+'
        explicit_pdb_ids = re.findall(pdb_pattern, question.upper())
        explicit_emdb_ids = re.findall(emdb_pattern, question.upper())
        explicit_structure_ids = explicit_pdb_ids + explicit_emdb_ids

        print(f"[QA v2] 路由决策: use_agent_mode={use_agent_mode}, rag_needed={rag_needed}, explicit_structure_ids={explicit_structure_ids}")
        print(f"[QA v2] 问题包含关键词检查：question_lower='{question_lower[:50]}...'")
        print(f"[QA v2] 检查 image/cartoon 关键词：{any(kw in question_lower for kw in ['图片', 'image', '可视化', 'visualize', 'cartoon', 'stick'])}")

        # ====== 统一使用 Agent 模式 ======
        # Agent 模式会自动判断是否需要搜索文献/结构，并调用相应工具
        print(f"[QA v2] 使用统一 Agent 模式...")
        max_tokens = data.get('max_tokens')  # 获取前端传来的 max_tokens
        return _handle_agent_mode(question, session_id, data, max_tokens=max_tokens)

        # 分析问题类型
        pdb_pattern = r'[1-9][A-Za-z0-9]{3}'
        emdb_pattern = r'EMD[A-Z]?\d+'
        explicit_pdb_ids = re.findall(pdb_pattern, question.upper())
        explicit_emdb_ids = re.findall(emdb_pattern, question.upper())
        explicit_structure_ids = explicit_pdb_ids + explicit_emdb_ids

        question_type = "general"
        if explicit_structure_ids or 'structure' in question.lower() or 'pdb' in question.lower():
            question_type = "structure"
        elif 'sequence' in question.lower() or '序列' in question:
            question_type = "sequence"
        elif 'literature' in question.lower() or '摘要' in question:
            question_type = "literature"

        print(f"[QA v2] 问题类型: {question_type}, 结构ID: {explicit_structure_ids}")

        # 初始化AI客户端
        client = get_ai_client(model_id)
        config = load_ai_config()
        model = config.get('chat_model', 'deepseek-chat')

        literature_context = ""
        structure_context = ""
        sources = []
        structure_ids = []

        # ====== 步骤0：蛋白名称标准化 ======
        # 检测问题中是否包含非标准的蛋白/基因名称，并转换为标准名称
        print(f"[QA v2] 开始蛋白名称标准化...")

        standardize_prompt = f"""你是一个专业的结构生物学文献检索助手。

你的任务是将用户问题中的蛋白/基因名称标准化。

用户问题：{question}

请按以下格式返回标准化的名称：

## 标准化结果
标准基因名: [例如: ADORA2A, GPR158]
标准蛋白名: [例如: adenosine A2A receptor]
UniProt ID: [例如: P29274]
其他常用名: [例如: A2AR]

如果问题中没有需要标准化的蛋白/基因名，请返回：
## 标准化结果
无

只返回上述格式的内容，不要返回其他内容。"""

        messages_standardize = [
            {"role": "system", "content": standardize_prompt},
            {"role": "user", "content": "请标准化问题中的蛋白/基因名称。"}
        ]

        result_standardize = client.chat(messages_standardize, timeout=30)
        standardized_info = ""
        if result_standardize.get('success'):
            standardized_info = result_standardize.get('content', '')
            print(f"[QA v2] 标准化结果: {standardized_info[:300]}")

        # 提取标准化后的名称用于搜索
        standardized_gene = ""
        standardized_uniprot = ""

        if standardized_info and '无' not in standardized_info:
            # 提取标准基因名
            gene_match = re.search(r'标准基因名[:：]\s*([A-Z][A-Z0-9]+)', standardized_info)
            if gene_match:
                standardized_gene = gene_match.group(1).strip()
                print(f"[QA v2] 提取到标准基因名: {standardized_gene}")

            # 提取UniProt ID
            uniprot_match = re.search(r'(UniProt|ID)[:：]\s*([PQ][0-9][A-Z0-9]{{3}})', standardized_info)
            if uniprot_match:
                standardized_uniprot = uniprot_match.group(2).strip()
                print(f"[QA v2] 提取到UniProt ID: {standardized_uniprot}")

        # 获取文献信息（包括methods部分）
        if literature_id:
            entry = get_literature_entry(literature_id)
            if entry:
                title = getattr(entry, 'title', '')
                abstract = getattr(entry, 'abstract', '')
                methods = getattr(entry, 'methods', '')

                literature_context = f"【相关文献】\n标题: {title}\n摘要: {abstract}"
                if methods and len(methods.strip()) > 10:
                    methods_preview = methods[:5000] if len(methods) > 5000 else methods
                    literature_context += f"\n\n【实验方法/Methods】:\n{methods_preview}"

        # RAG文献搜索 - 始终执行（RAG默认开启，无需检测关键词）
        print(f"[QA v2] 执行RAG文献搜索...")
        literature_source_ids = []  # 用于去重

        # ====== 首先：使用 LanceDB 向量搜索获取相关 chunks ======
        try:
            print(f"[QA v2] 使用 LanceDB 向量搜索...")
            from core.search_factory import search_vector
            from core.literature_index import EntityType

            # 构建搜索查询
            search_query = question
            if standardized_gene:
                search_query += f" {standardized_gene}"

            # 执行向量搜索
            vector_results = search_vector(
                query=search_query,
                top_k=10,
                entity_filter=EntityType.LITERATURE,
                search_type='hybrid'
            )

            print(f"[QA v2] LanceDB 搜索返回 {len(vector_results)} 个结果")

            # 处理向量搜索结果 - 直接添加到 literature_context
            if vector_results:
                literature_context += "\n\n【LanceDB向量搜索检索到的相关文献内容】:\n"

                for i, result in enumerate(vector_results[:8], 1):
                    doc = result.get('document', {})
                    content = doc.get('full_text', '') or doc.get('content', '') or doc.get('abstract', '')
                    title = doc.get('title', '')
                    result_id = result.get('id', '')

                    if content:
                        literature_context += f"\n{'='*60}\n"
                        literature_context += f"文献片段 {i}: {title[:100]}\n"
                        literature_context += f"ID: {result_id}\n"
                        literature_context += f"{'='*60}\n"
                        literature_context += f"{content}\n"

                        # 添加到 sources
                        sources.append({
                            'id': str(result_id),
                            'title': title[:100],
                            'type': 'literature'
                        })

                print(f"[QA v2] LanceDB 向量搜索完成，添加了 {len(vector_results)} 个 chunks")

        except Exception as e:
            import traceback
            print(f"[QA v2] LanceDB 向量搜索失败: {e}")
            traceback.print_exc()

            # 继续原有的数据库搜索作为补充
            try:
                from core.literature_db import get_literature_entry
                import sqlite3
                db_path = os.path.join(PROJECT_ROOT, 'data/literature.db')
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()

                # 提取搜索关键词
                protein_names = re.findall(r'([A-Z]{2,10}[0-9]{0,5})', question)
                protein_names_lower = re.findall(r'([a-z]{2,10}[0-9]{0,5})', question.lower())
                search_proteins = [p.upper() for p in protein_names] + [p.lower() for p in protein_names_lower]

                # 添加标准化后的搜索关键词
                if standardized_gene and standardized_gene.upper() not in [p.upper() for p in search_proteins]:
                    search_proteins.append(standardized_gene.upper())
                    print(f"[QA v2] 添加标准化基因名到搜索: {standardized_gene}")
                if standardized_uniprot and standardized_uniprot.upper() not in [p.upper() for p in search_proteins]:
                    search_proteins.append(standardized_uniprot.upper())
                    print(f"[QA v2] 添加UniProt ID到搜索: {standardized_uniprot}")

                # 特殊处理：希腊字母和TCR相关关键词（如Vγ9Vδ2, γδ TCR等）
                greek_keywords = []
                if 'γ' in question or 'δ' in question or 'gamma' in question.lower() or 'delta' in question.lower():
                    greek_keywords = ['γδ', 'gamma-delta', 'gamma delta', 'tcr', 'γ chain', 'δ chain']
                    print(f"[QA v2] 检测到希腊字母/TCR关键词: {greek_keywords}")
                if 'tcr' in question.lower():
                    if 'tcr' not in greek_keywords:
                        greek_keywords.append('tcr')

                print(f"[QA v2] 初始搜索蛋白: {search_proteins}, 希腊/TCR关键词: {greek_keywords}")

                # 搜索有methods的文献
                cursor.execute("SELECT id, title, methods FROM literature_entries WHERE methods IS NOT NULL AND methods != ''")
                all_methods = cursor.fetchall()

                matched_lit_ids = []
                for row in all_methods:
                    lit_id, title, methods = row
                    # 检查是否匹配搜索词
                    text_to_search = f"{title} {methods}".lower()
                    match = False
                    if search_proteins:
                        for p in search_proteins:
                            if p.lower() in text_to_search:
                                match = True
                                break
                    # 检查希腊字母/TCR关键词
                    if not match and greek_keywords:
                        for kw in greek_keywords:
                            if kw.lower() in text_to_search:
                                match = True
                                print(f"[QA v2] 希腊/TCR关键词匹配: {kw} in 文献 {lit_id}")
                                break
                    # 如果没有特定蛋白名但问题是关于纯化/方法的，也返回所有有methods的文献
                    elif not search_proteins and not greek_keywords:
                        if any(kw in question.lower() for kw in ['纯化', '方法', 'method', 'purif', '表达', 'protein']):
                            match = True

                    if match and lit_id not in matched_lit_ids:
                        matched_lit_ids.append(lit_id)

                print(f"[QA v2] 数据库搜索完成: 共匹配 {len(matched_lit_ids)} 篇文献: {matched_lit_ids}")

                conn.close()

                # 如果找到匹配的文献，从数据库获取完整的methods
                if matched_lit_ids:
                    print(f"[QA v2] ========== 从数据库找到 {len(matched_lit_ids)} 篇有methods的文献 ==========")
                    from core.literature_db import get_literature_entry

                    for lit_id in matched_lit_ids[:5]:  # 最多处理5篇
                        entry = get_literature_entry(lit_id)
                        if entry:
                            title = getattr(entry, 'title', '')
                            methods = getattr(entry, 'methods', '')
                            if methods and len(methods.strip()) > 20:
                                # 直接添加到literature_context（而不是rag_context）
                                literature_context += f"\n\n{'='*60}\n"
                                literature_context += f"文献 {lit_id}: {title[:100]}\n"
                                literature_context += f"{'='*60}\n\n"
                                literature_context += f"【Experimental Methods - 英文原文】:\n{methods[:8000]}\n"

                                # 添加到sources
                                if lit_id not in literature_source_ids:
                                    literature_source_ids.append(lit_id)
                                    sources.append({
                                        'id': str(lit_id),
                                        'title': title[:100],
                                        'type': 'literature'
                                    })
                                    print(f"[QA v2] >>> 添加到sources: lit_id={lit_id}, title={title[:50]}")

            except Exception as e:
                import traceback
                print(f"[QA v2] 从数据库搜索methods失败: {e}")

            # 继续执行原有的unified_index搜索
            try:
                # 直接从unified_index.json读取并搜索chunks
                import json
                index_path = os.path.join(PROJECT_ROOT, 'literature_indices', 'unified_index.json')

                if os.path.exists(index_path):
                    with open(index_path, 'r') as f:
                        index_data = json.load(f)

                    docs = index_data.get('documents', {})

                    # 提取搜索关键词
                    import re
                    # 匹配大写蛋白名如 GPR158, PDB 7SHE
                    protein_names = re.findall(r'([A-Z]{2,10}[0-9]{0,5})', question)
                    # 也匹配小写蛋白名如 gpr158
                    protein_names_lower = re.findall(r'([a-z]{2,10}[0-9]{0,5})', question.lower())
                    search_terms = [t.lower() for t in protein_names] + protein_names_lower
                    # 如果没有找到任何蛋白名，使用整个问题作为搜索词
                    if not search_terms:
                        search_terms = [question.lower()[:20]]
                    # 也添加中文关键词
                    if '纯化' in question or '表达' in question or '克隆' in question:
                        search_terms.extend(['purif', 'express', 'clon', 'method', 'protein', 'buffer', 'column', 'concentration'])

                    # 添加标准化后的搜索关键词
                    if standardized_gene and standardized_gene.lower() not in search_terms:
                        search_terms.append(standardized_gene.lower())
                        print(f"[QA v2] 添加标准化基因名到索引搜索: {standardized_gene}")
                    if standardized_uniprot and standardized_uniprot.lower() not in search_terms:
                        search_terms.append(standardized_uniprot.lower())
                        print(f"[QA v2] 添加UniProt ID到索引搜索: {standardized_uniprot}")

                    # 特殊处理：希腊字母和TCR相关关键词
                    if 'γ' in question or 'δ' in question or 'gamma' in question.lower() or 'delta' in question.lower() or 'tcr' in question.lower():
                        if 'γδ' not in search_terms:
                            search_terms.append('γδ')
                        if 'gamma-delta' not in search_terms:
                            search_terms.append('gamma-delta')
                        if 'tcr' not in search_terms:
                            search_terms.append('tcr')
                        print(f"[QA v2] 添加希腊/TCR关键词到索引搜索")

                    print(f"[QA v2] 搜索关键词: {search_terms}")

                    # 搜索chunks
                    matched_chunks = []
                    for doc_id, doc in docs.items():
                        content = doc.get('content', '')
                        title = doc.get('title', '') or ''
                        metadata = doc.get('metadata', {})
                        source_id = doc.get('source_id', '')

                        # 计算匹配分数
                        text_lower = f"{title} {content}".lower()
                        score = 0
                        for term in search_terms:
                            if term.lower() in text_lower:
                                score += 1
                                # 标题匹配权重更高
                                if term.lower() in title.lower():
                                    score += 2

                        if score > 0:
                            matched_chunks.append({
                                'doc_id': doc_id,
                                'source_id': source_id,
                                'title': title,
                                'content': content,
                                'score': score,
                                'doc_type': metadata.get('doc_type', 'unknown') if metadata else 'unknown'
                            })

                    # 按分数排序
                    matched_chunks.sort(key=lambda x: x.get('score', 0), reverse=True)
                    matched_chunks = matched_chunks[:8]  # 取前8个更全面

                    print(f"[QA v2] 找到 {len(matched_chunks)} 个相关chunks")

                    if matched_chunks:
                        rag_context = "\n\n【检索到的相关文献methods和详细内容】:\n"

                        # 按文献ID分组
                        lit_sources = {}
                        for chunk in matched_chunks:
                            source_id = chunk.get('source_id', '')
                            # 提取literature ID
                            lit_id = source_id.replace('literature_', '') if source_id.startswith('literature_') else source_id

                            if lit_id not in lit_sources:
                                lit_sources[lit_id] = {
                                    'chunks': [],
                                    'title': chunk.get('title', '')[:150],
                                    'full_content': []  # 保存完整内容用于比较
                                }

                            # 添加chunk内容
                            chunk_type = chunk.get('doc_type', 'unknown')
                            content = chunk.get('content', '')

                            lit_sources[lit_id]['chunks'].append({
                                'type': chunk_type,
                                'content': content
                            })
                            lit_sources[lit_id]['full_content'].append(content)

                        # 获取每个文献的完整信息
                        from core.literature_db import get_literature_entry

                        # 构建上下文 - 包含完整methods和英文原文
                        for lit_id, lit_data in lit_sources.items():
                            try:
                                entry = get_literature_entry(int(lit_id))
                            except:
                                entry = None

                            title = lit_data['title']

                            # 添加文献标题
                            rag_context += f"\n{'='*60}\n"
                            rag_context += f"文献 {lit_id}: {title}\n"
                            rag_context += f"{'='*60}\n\n"

                            if entry:
                                methods = getattr(entry, 'methods', '')
                                if methods and len(methods.strip()) > 20:
                                    # 添加完整methods内容（英文原文）
                                    rag_context += f"【Experimental Methods - 英文原文】:\n{methods}\n\n"

                            # 添加相关的chunks内容
                            for chunk_info in lit_data['chunks']:
                                chunk_type = chunk_info['type']
                                content = chunk_info['content']
                                if len(content) > 3000:
                                    content = content[:3000] + "..."
                                rag_context += f"[{chunk_type}]:\n{content}\n\n"

                            # 添加到sources（去重）
                            if lit_id not in literature_source_ids:
                                literature_source_ids.append(lit_id)
                                sources.append({
                                    'id': str(lit_id),
                                    'title': title,
                                    'type': 'literature'
                                })

                        literature_context += rag_context
                        print(f"[QA v2] RAG文献上下文已添加, 共 {len(lit_sources)} 篇文献")
                else:
                    print(f"[QA v2] 索引文件不存在: {index_path}")

            except Exception as e:
                import traceback
                print(f"[QA v2] RAG搜索失败: {e}")
                traceback.print_exc()

        # 搜索结构数据库
        if question_type in ["structure", "sequence", "general"]:
            print(f"[QA v2] ========== 搜索结构数据库 ==========")
            print(f"[QA v2] question_type: {question_type}, explicit_structure_ids: {explicit_structure_ids}")

            from core.structure_database import StructureOfflineDatabase
            db = StructureOfflineDatabase()
            structure_ids = []

            protein_pattern = r'([A-Z]{2,10}[0-9]{0,10})'
            proteins = re.findall(protein_pattern, question)
            # 也匹配小写蛋白名如 gpr158
            protein_pattern_lower = r'([a-z]{2,10}[0-9]{0,10})'
            proteins_lower = re.findall(protein_pattern_lower, question.lower())
            proteins = list(set(proteins + proteins_lower))
            proteins = [p for p in proteins if p.upper() not in ['THE', 'AND', 'FOR', 'NOT', 'THIS', 'FROM', 'WHAT', 'WITH', 'GIVE', 'SHOW', 'SOME']]

            # 添加标准化后的蛋白名称
            if standardized_gene and standardized_gene.upper() not in [p.upper() for p in proteins]:
                proteins.append(standardized_gene)
                print(f"[QA v2] 添加标准化基因名到结构搜索: {standardized_gene}")
            if standardized_uniprot and standardized_uniprot.upper() not in [p.upper() for p in proteins]:
                proteins.append(standardized_uniprot)
                print(f"[QA v2] 添加UniProt ID到结构搜索: {standardized_uniprot}")

            proteins = list(set(proteins))[:5]

            # 如果有明确的 PDB/EMDB ID，添加到搜索列表
            if explicit_structure_ids:
                for sid in explicit_structure_ids:
                    if sid.upper() not in [p.upper() for p in proteins]:
                        proteins.append(sid.upper())
                        print(f"[QA v2] 添加显式 PDB ID 到搜索: {sid}")

            print(f"[QA v2] 蛋白质搜索: {proteins}")

            # 通用结构搜索：从多个表和字段搜索
            try:
                import sqlite3
                conn = sqlite3.connect(os.path.join(PROJECT_ROOT, 'data/structure_offline.db'))
                cursor = conn.cursor()

                for protein in proteins:
                    protein_upper = protein.upper()
                    protein_lower = protein.lower()

                    # 1. 搜索structures表的title, protein_name, gene字段（不区分大小写）
                    cursor.execute("""
                        SELECT DISTINCT id FROM structures
                        WHERE LOWER(id) LIKE ?
                           OR LOWER(title) LIKE ?
                           OR LOWER(COALESCE(protein_name, '')) LIKE ?
                           OR LOWER(COALESCE(gene, '')) LIKE ?
                        LIMIT 20
                    """, (f'%{protein_lower}%', f'%{protein_lower}%', f'%{protein_lower}%', f'%{protein_lower}%'))
                    results = cursor.fetchall()
                    for row in results:
                        sid = row[0].upper()
                        if sid and sid not in structure_ids:
                            structure_ids.append(sid)
                            print(f"[QA v2] structures表匹配 {protein} -> {sid}")

                    # 2. 搜索structure_entities表（不区分大小写）
                    cursor.execute("""
                        SELECT DISTINCT structure_id FROM structure_entities
                        WHERE LOWER(molecule_name) LIKE ?
                           OR LOWER(gene_names) LIKE ?
                        LIMIT 20
                    """, (f'%{protein_lower}%', f'%{protein_lower}%'))
                    results = cursor.fetchall()
                    for row in results:
                        sid = row[0].upper()
                        if sid and sid not in structure_ids:
                            structure_ids.append(sid)
                            print(f"[QA v2] entities表匹配 {protein} -> {sid}")

                conn.close()
            except Exception as e:
                print(f"[QA v2] 通用结构搜索失败: {e}")

            # 如果数据库搜索没找到，使用向量索引搜索
            if not structure_ids:
                print(f"[QA v2] 数据库搜索无结果，使用向量索引...")
                try:
                    from core.literature_index import UnifiedRAGSystem, EntityType
                    print(f"[QA v2] 成功导入 UnifiedRAGSystem, EntityType")
                    rag = UnifiedRAGSystem()
                    print(f"[QA v2] UnifiedRAGSystem 实例创建成功")
                    # 搜索结构
                    results = rag.retrieve(question, top_k=5, entity_types=[EntityType.STRUCTURE])
                    print(f"[QA v2] 向量检索完成，结果数: {len(results.get('results', []))}")
                    for r in results.get('results', []):
                        sid = r.doc_id.upper()
                        if sid and sid not in structure_ids:
                            structure_ids.append(sid)
                            print(f"[QA v2] 向量索引匹配 {sid}")
                except Exception as e:
                    import traceback
                    print(f"[QA v2] 向量索引搜索失败: {e}")
                    print(f"[QA v2] 详细错误: {traceback.format_exc()}")

            # 使用文献关联结构
            if literature_id and not structure_ids:
                entry = get_literature_entry(literature_id)
                if entry:
                    cryoem_targets = getattr(entry, 'cryoem_targets', {})
                    if isinstance(cryoem_targets, dict):
                        lit_structures = cryoem_targets.get('pdb_ids', []) + cryoem_targets.get('emdb_ids', [])
                        for sid in lit_structures:
                            if sid and sid not in structure_ids:
                                structure_ids.append(sid)
                        print(f"[QA v2] 追加文献关联结构: {lit_structures}")

            # 获取结构详细信息
            if structure_ids:
                print(f"[QA v2] 获取 {len(structure_ids)} 个结构详情...")

                # 如果有多个候选结构，让AI筛选但保留所有相关的
                if len(structure_ids) > 5:
                    print(f"[QA v2] 使用AI筛选相关结构...")
                    try:
                        client = get_ai_client()
                        config = load_ai_config()

                        # 构建候选结构列表
                        candidates_info = []
                        for sid in structure_ids[:10]:  # 最多10个
                            s = db.get_structure(sid, simplify=True)
                            if s:
                                candidates_info.append(f"- {s.get('id', sid)}: {s.get('title', 'N/A')[:100]}")

                        if candidates_info:
                            filter_prompt = f"""用户询问的是: {question}

候选结构列表:
{chr(10).join(candidates_info)}

请筛选出与用户问题直接相关的结构。返回相关结构的ID列表，用逗号分隔。
只返回ID列表，不要其他内容。

注意：如果不确定，请返回所有结构ID。"""

                            messages = [{"role": "user", "content": filter_prompt}]
                            result = client.chat(messages, timeout=30)
                            if result.get('success'):
                                import re
                                # 提取结构ID
                                response = result.get('content', '')
                                # 匹配PDB/EMD格式
                                relevant_ids = re.findall(r'\b[0-9][A-Z0-9]{3}\b|\bEMD[-]?[A-Z0-9]+\b', response.upper())
                                # 过滤有效的结构ID
                                filtered_ids = [sid.upper() for sid in relevant_ids if sid.upper() in [s.upper() for s in structure_ids]]
                                if filtered_ids and len(filtered_ids) >= len(structure_ids) * 0.3:  # 至少保留30%
                                    print(f"[QA v2] AI筛选后保留: {filtered_ids}")
                                    structure_ids = filtered_ids
                                else:
                                    print(f"[QA v2] AI筛选结果太少，保留原始列表")
                    except Exception as e:
                        print(f"[QA v2] AI筛选失败: {e}")

                # 限制最多获取4个结构，避免上下文太大
                for sid in structure_ids[:4]:
                    s = db.get_structure(sid, simplify=False)
                    if s:
                        res_str = f", 分辨率: {s.get('resolution', 'N/A')} Å" if s.get('resolution') else ""
                        org_str = f", 物种: {s.get('organism', 'N/A')}" if s.get('organism') else ""

                        structure_context += f"\n## 结构 {s['id']} ({s.get('type', 'Unknown')})\n"
                        structure_context += f"标题: {s.get('title', 'N/A')}{res_str}{org_str}\n"

                        entities = s.get('entities', [])
                        if entities:
                            structure_context += f"包含 {len(entities)} 个实体:\n"
                            # 获取所有实体的完整序列
                            for entity in entities:  # 获取所有实体，不限制数量
                                molecule_names = ', '.join(entity.get('molecule_name', [])) or '未知'
                                gene_names = ', '.join(entity.get('gene_names', [])) or '未知'
                                seq = entity.get('sequence', '')
                                # 显示完整序列，不截断
                                if seq:
                                    seq_lines = [seq[i:i+70] for i in range(0, len(seq), 70)]
                                    seq_len = len(seq)
                                    structure_context += f"\n  - 实体 {entity.get('id', '?')}: {molecule_names}\n"
                                    structure_context += f"    基因: {gene_names}\n"
                                    structure_context += f"    序列 (完整{seq_len}字符):\n"
                                    structure_context += "    " + "\n    ".join(seq_lines) + "\n"

                        # 添加结构来源（去重）
                        struct_id = s.get('id')
                        existing_ids = [src.get('id') for src in sources]
                        if struct_id not in existing_ids:
                            sources.append({
                                'id': struct_id,
                                'title': s.get('title', '')[:100],
                                'type': 'structure'
                            })

        # 搜索飞书文档知识库
        feishu_context = ""
        if question_type in ["general", "literature"]:
            print(f"[QA v2] 搜索飞书文档知识库...")
            try:
                from services.feishu_document import FeishuDocumentService
                feishu_service = FeishuDocumentService()

                # 首先确保飞书文档已索引（如果需要）
                feishu_service.ensure_all_indexed()

                # 执行搜索
                feishu_results = feishu_service.search(question, top_k=3)

                if feishu_results:
                    print(f"[QA v2] 找到 {len(feishu_results)} 个相关飞书文档")
                    feishu_context = "\n\n【飞书文档知识库】:\n"

                    for i, result in enumerate(feishu_results):
                        # 支持对象和字典两种格式
                        if hasattr(result, 'metadata'):
                            title = getattr(result, 'title', '未知标题')
                            content = getattr(result, 'content', '')
                            doc_id = result.metadata.get('feishu_doc_id', result.doc_id)
                        else:
                            title = result.get('title', '未知标题')
                            content = result.get('content', '')
                            doc_id = result.get('doc_id', '')

                        feishu_context += f"\n{'='*60}\n"
                        feishu_context += f"飞书文档 {i+1}: {title[:100]}\n"
                        feishu_context += f"{'='*60}\n\n"

                        # 截断内容
                        if len(content) > 2000:
                            content = content[:2000] + "..."
                        feishu_context += f"{content}\n"

                        # 添加到sources
                        existing_ids = [src.get('id') for src in sources]
                        if doc_id not in existing_ids:
                            sources.append({
                                'id': str(doc_id),
                                'title': title[:100],
                                'type': 'feishu'
                            })
                else:
                    print(f"[QA v2] 未找到相关飞书文档")
            except Exception as e:
                import traceback
                print(f"[QA v2] 飞书文档搜索失败: {e}")
                traceback.print_exc()

        # 生成回答
        print(f"[QA v2] 生成回答...")

        system_prompt = """你是专业的结构生物学文献研究助手。请根据提供的上下文信息回答用户问题。

要求：
1. **必须用中文回答**，仅蛋白质/基因名称、结构ID保留英文
2. 如果提供了结构信息（包含序列），务必包含序列详情
3. **当有多篇文献涉及同一蛋白的纯化时，必须分别详细列出每篇文献的具体方法和参数，然后进行对比分析**
4. **纯化方法必须包含具体参数**：浓度(mM, mg/ml)、温度(°C)、时间(hours/minutes)、pH值、缓冲液成分、离心转速等
5. **在回答中必须附上相关methods的英文原文**
6. 回答要简洁，专业、有据可查
7. **重要：只使用下面提供的【文献】和【结构】信息来回答问题，不要编造参考文献**
8. 参考来源只能列出系统提供的真实来源，不要列出不在列表中的文献
9. **如果用户问题中涉及的蛋白/基因/结构在提供的上下文中没有找到相关信息，必须明确告知用户"抱歉，数据库中没有找到相关信息"，禁止编造任何文献、结构、序列或PDB ID**"""

        # 合并所有上下文到单个system消息中（MiniMax兼容性）
        # 增加限制以支持完整序列和methods内容
        full_system = system_prompt
        if literature_context:
            full_system += f"\n\n【文献】{literature_context[:25000]}"
        if feishu_context:
            full_system += f"\n\n【飞书文档】{feishu_context[:8000]}"
        if structure_context:
            full_system += f"\n\n【结构】{structure_context[:8000]}"

        # 添加历史对话上下文
        history_context = ""
        if session_id:
            try:
                from core.literature_db import get_qa_chat_history_by_session
                user_id = get_current_user_id()
                history_records = get_qa_chat_history_by_session(session_id, user_id)
                if history_records:
                    history_context = "\n\n【历史对话记录】:\n"
                    for i, record in enumerate(history_records[-5:]):  # 最多5条历史
                        history_context += f"\n--- 对话 {i+1} ---\n"
                        history_context += f"用户问题: {record.question}\n"
                        history_context += f"AI回答: {record.answer[:500]}...\n"
                    print(f"[QA v2] 已添加 {len(history_records[-5:])} 条历史记录到上下文")
            except Exception as e:
                print(f"[QA v2] 获取历史记录失败: {e}")

        if history_context:
            full_system += history_context[:5000]

        # ====== 步骤1：先让AI判断第一轮搜索结果是否足够 ======
        # 构建判断用的prompt
        judge_system = f"""你是一个专业的结构生物学文献检索助手。你的任务是判断提供的搜索结果是否足够回答用户的问题。

请仔细分析提供的【文献】和【结构】信息，然后判断：
1. 这些信息是否足够回答用户问题？
2. 如果不够，你还需要什么信息？（例如：特定的PDB ID、基因名、Uniprot ID、蛋白名称等）

判断标准：
- 如果文献中有相关的methods章节或结构信息足够详细，则认为"足够"
- 如果需要知道具体的PDB ID、基因名、Uniprot ID才能找到更多信息，则认为"不够"

请按以下格式返回判断结果：

## 判断结果
足够/不够

## 需要的标识符（如果不够）
请列出你需要的具体标识符，格式如下：
- PDB ID: [例如: 7EWL, 7SHE]
- 基因名: [例如: ADORA2A, GPR158]
- Uniprot ID: [例如: P29274]
- 其他: [任何其他有助于进一步搜索的关键词]

只返回上述格式的内容，不要返回其他内容。

用户问题是：{question}

提供的搜索结果：
【文献】{literature_context[:5000]}
【结构】{structure_context[:3000]}
【已有来源数量】{len(sources)}"""

        print(f"[QA v2] 开始AI判断第一轮搜索结果是否足够...")
        messages_judge = [
            {"role": "system", "content": judge_system},
            {"role": "user", "content": "请判断这些搜索结果是否足够回答问题，并提供需要的标识符（如果不够）。"}
        ]

        result_judge = client.chat(messages_judge, timeout=60)

        judge_response = ""
        if result_judge.get('success'):
            judge_response = result_judge.get('content', '')
            print(f"[QA v2] AI判断结果: {judge_response[:500]}")
        else:
            print(f"[QA v2] AI判断失败，继续使用第一轮结果")

        # 检查AI判断结果
        need_second_round = False
        extracted_ids = []

        if judge_response:
            # 判断是否"不够"
            if '不够' in judge_response or '不足' in judge_response or '需要更多' in judge_response:
                need_second_round = True
                print(f"[QA v2] AI判断第一轮搜索不够，需要第二轮搜索")

                # 从AI判断响应中提取需要的标识符
                # 提取PDB ID
                pdb_pattern = r'PDB\s*ID[:：]\s*\[([^\]]+)\]'
                pdb_match = re.search(pdb_pattern, judge_response, re.IGNORECASE)
                if pdb_match:
                    pdbs = [p.strip().lower() for p in pdb_match.group(1).split(',')]
                    extracted_ids.extend(pdbs)
                    print(f"[QA v2] AI提供的PDB ID: {pdbs}")

                # 提取基因名
                gene_pattern = r'基因名[:：]\s*\[([^\]]+)\]'
                gene_match = re.search(gene_pattern, judge_response, re.IGNORECASE)
                if gene_match:
                    genes = [g.strip().lower() for g in gene_match.group(1).split(',')]
                    extracted_ids.extend(genes)
                    print(f"[QA v2] AI提供的基因名: {genes}")

                # 提取Uniprot ID
                uniprot_pattern = r'Uniprot\s*ID[:：]\s*\[([^\]]+)\]'
                uniprot_match = re.search(uniprot_pattern, judge_response, re.IGNORECASE)
                if uniprot_match:
                    uniprots = [u.strip().lower() for u in uniprot_match.group(1).split(',')]
                    extracted_ids.extend(uniprots)
                    print(f"[QA v2] AI提供的Uniprot ID: {uniprots}")

                # 提取其他关键词
                other_pattern = r'其他[:：]\s*\[([^\]]+)\]'
                other_match = re.search(other_pattern, judge_response, re.IGNORECASE)
                if other_match:
                    others = [o.strip().lower() for o in other_match.group(1).split(',')]
                    extracted_ids.extend(others)
                    print(f"[QA v2] AI提供的其他关键词: {others}")
            else:
                print(f"[QA v2] AI判断第一轮搜索足够，直接生成答案")

        # ====== 步骤2：如果需要第二轮搜索 ======
        second_round_structure_context = ""
        if need_second_round and extracted_ids:
            print(f"[QA v2] 执行第二轮搜索，使用的标识符: {extracted_ids}")

            try:
                import sqlite3
                conn = sqlite3.connect(os.path.join(PROJECT_ROOT, 'data/structure_offline.db'))
                cursor = conn.cursor()

                second_round_structures = []
                for extracted_id in extracted_ids[:10]:
                    id_lower = extracted_id.lower()

                    # 搜索structures表
                    cursor.execute("""
                        SELECT DISTINCT id FROM structures
                        WHERE LOWER(id) LIKE ?
                           OR LOWER(title) LIKE ?
                           OR LOWER(COALESCE(protein_name, '')) LIKE ?
                           OR LOWER(COALESCE(gene, '')) LIKE ?
                        LIMIT 10
                    """, (f'%{id_lower}%', f'%{id_lower}%', f'%{id_lower}%', f'%{id_lower}%'))
                    results = cursor.fetchall()
                    for row in results:
                        sid = row[0].upper()
                        if sid and sid not in second_round_structures and sid not in structure_ids:
                            second_round_structures.append(sid)

                    # 搜索structure_entities表
                    cursor.execute("""
                        SELECT DISTINCT structure_id FROM structure_entities
                        WHERE LOWER(molecule_name) LIKE ?
                           OR LOWER(gene_names) LIKE ?
                        LIMIT 10
                    """, (f'%{id_lower}%', f'%{id_lower}%'))
                    results = cursor.fetchall()
                    for row in results:
                        sid = row[0].upper()
                        if sid and sid not in second_round_structures and sid not in structure_ids:
                            second_round_structures.append(sid)

                conn.close()

                if second_round_structures:
                    print(f"[QA v2] 第二轮搜索找到新结构: {second_round_structures}")
                    structure_ids.extend(second_round_structures)

                    # 获取新结构的详细信息
                    from core.structure_database import StructureOfflineDatabase
                    db = StructureOfflineDatabase()
                    second_round_structure_context = "\n\n【第二轮搜索找到的相关结构】:\n"
                    for sid in second_round_structures[:5]:
                        try:
                            # 使用 simplify=False 获取完整信息，包括序列
                            struct = db.get_structure(sid, simplify=False)
                            if struct:
                                title = struct.get('title', '') or sid
                                resolution = struct.get('resolution', '')
                                method = struct.get('method', '')
                                gene = struct.get('gene', '')
                                protein_name = struct.get('protein_name', '')
                                entities = struct.get('entities', [])

                                second_round_structure_context += f"\n## 结构 {sid}\n"
                                second_round_structure_context += f"标题: {title}\n"
                                if resolution:
                                    second_round_structure_context += f"分辨率: {resolution}Å\n"
                                if method:
                                    second_round_structure_context += f"方法: {method}\n"

                                # 添加实体信息（包括序列）
                                if entities:
                                    second_round_structure_context += f"包含 {len(entities)} 个实体:\n"
                                    for entity in entities:
                                        molecule_names = ', '.join(entity.get('molecule_name', [])) or '未知'
                                        entity_gene_names = ', '.join(entity.get('gene_names', [])) or '未知'
                                        seq = entity.get('sequence', '')
                                        if seq:
                                            seq_lines = [seq[i:i+70] for i in range(0, len(seq), 70)]
                                            seq_len = len(seq)
                                            second_round_structure_context += f"\n  - 实体 {entity.get('id', '?')}: {molecule_names}\n"
                                            second_round_structure_context += f"    基因: {entity_gene_names}\n"
                                            second_round_structure_context += f"    序列 (完整{seq_len}字符):\n"
                                            second_round_structure_context += "    " + "\n    ".join(seq_lines) + "\n"
                                        else:
                                            second_round_structure_context += f"\n  - 实体 {entity.get('id', '?')}: {molecule_names} (基因: {entity_gene_names})\n"
                                second_round_structure_context += "\n"

                                if sid not in [s['id'] for s in sources]:
                                    sources.append({
                                        'id': sid,
                                        'title': title[:80],
                                        'type': 'structure'
                                    })
                        except Exception as e:
                            print(f"[QA v2] 获取结构 {sid} 详情失败: {e}")

            except Exception as e:
                print(f"[QA v2] 第二轮搜索失败: {e}")

        # ====== 步骤2.5：检测是否需要生成结构图像 (PyMOL) ======
        # 检测是否需要生成图像
        need_image = any(kw in question.lower() for kw in [
            "image", "图片", "图像", "可视化", "visualize", "show structure",
            "展示结构", "生成图像", "cartoon", "stick", "ribbon", "surface"
        ])

        pymol_image_url = None
        if need_image and explicit_structure_ids:
            # 提取 PDB ID
            pdb_id = explicit_structure_ids[0].upper()
            # 提取样式
            style = "cartoon"
            if "stick" in question.lower():
                style = "sticks"
            elif "ribbon" in question.lower():
                style = "ribbon"
            elif "surface" in question.lower():
                style = "surface"
            elif "line" in question.lower():
                style = "line"

            print(f"[QA v2] 需要生成 PyMOL 图像: {pdb_id}, style={style}")

            try:
                from core.pymol_wrapper import get_pymol_wrapper
                wrapper = get_pymol_wrapper()
                if wrapper.is_available():
                    image_path = wrapper.generate_image(pdb_id, style, "rainbow")
                    if image_path:
                        # 处理大小写问题
                        original_filename = image_path.split('/')[-1] if '/' in image_path else image_path
                        filename = original_filename
                        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                        sessions_dir = os.path.join(project_root, 'pymol_sessions')
                        if not os.path.exists(os.path.join(sessions_dir, filename)):
                            filename_lower = original_filename.lower()
                            if os.path.exists(os.path.join(sessions_dir, filename_lower)):
                                filename = filename_lower
                        pymol_image_url = f"/api/pymol/sessions/{filename}"
                        structure_context += f"\n\n【结构图像】\n- PDB ID: {pdb_id}\n- 图像URL: {pymol_image_url}\n"
                        print(f"[QA v2] PyMOL 图像生成成功: {pymol_image_url}")
                else:
                    print(f"[QA v2] PyMOL 不可用")
            except Exception as e:
                print(f"[QA v2] PyMOL 图像生成失败: {e}")

        # ====== 步骤3：生成最终答案 ======
        # 合并所有上下文
        final_system = system_prompt
        if literature_context:
            final_system += f"\n\n【文献】{literature_context[:20000]}"
        if feishu_context:
            final_system += f"\n\n【飞书文档】{feishu_context[:8000]}"
        if structure_context:
            final_system += f"\n\n【结构】{structure_context[:8000]}"
        if second_round_structure_context:
            final_system += second_round_structure_context[:5000]
        if history_context:
            final_system += history_context[:5000]

        messages_final = [
            {"role": "system", "content": final_system},
            {"role": "user", "content": question}
        ]

        print(f"[QA v2] 生成最终答案...")
        result = client.chat(messages_final, timeout=120)

        if not result.get('success'):
            return jsonify({'error': result.get('error', 'API调用失败')}), 500

        answer = result.get('content', '')

        # 检查回答是否已经包含参考来源，如果没有则添加
        if sources and '参考来源' not in answer and 'Reference' not in answer and 'Sources' not in answer:
            answer += "\n\n---\n**参考来源:**\n"
            for i, source in enumerate(sources[:5], 1):
                source_type = '文献' if source['type'] == 'literature' else source['type']
                answer += f"{i}. {source_type} {source['id']}: {source['title'][:60]}...\n"

        # 保存历史
        try:
            from core.literature_db import save_qa_chat_history
            user_id = get_current_user_id()
            save_qa_chat_history(
                question=question, answer=answer,
                literature_id=int(literature_id) if literature_id else None,
                user_id=user_id,
                model_used=result.get('model', model),
                sources=sources, question_type=question_type,
                session_id=session_id
            )
        except Exception as e:
            logger.warning(f"保存历史失败: {e}")

        print(f"[QA v2] 最终返回 sources: {sources}")
        print(f"[QA v2] 返回 image_url: {pymol_image_url}")

        return jsonify({
            'answer': answer, 'model': result.get('model', model), 'success': True,
            'session_id': session_id,
            'analysis': {
                'question_type': question_type, 'sources_count': len(sources),
                'found_structures': structure_ids
            },
            'sources': sources,
            'image_url': pymol_image_url  # PyMOL 生成的图像URL
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/ask', methods=['GET', 'POST'])
def ask_question():
    """
    Intelligent QA endpoint - 使用配置文件的 AI 设置
    支持两种模式：
    - SSE流式输出 (Accept: text/event-stream 或未指定)
    - 普通JSON响应 (Accept: application/json)
    """
    import logging
    logger = logging.getLogger(__name__)

    # 在请求上下文中获取所有参数
    if request.method == 'POST':
        data = request.json or {}
        question = data.get('question', '')
        literature_id = data.get('literature_id')
    else:
        question = request.args.get('question', '')
        literature_id = request.args.get('literature_id')

    # 检查是否需要返回普通JSON（非SSE）
    accept_header = request.headers.get('Accept', '')
    wants_json = 'application/json' in accept_header

    def get_answer():
        """获取答案，返回字典格式"""
        try:
            if not question:
                return {'answer': '请提供问题', 'sources': []}

            # Get literature entry if ID provided
            context_text = ""
            structure_info = ""
            structure_info_parts = []
            structure_ids = []  # 初始化变量

            if literature_id:
                entry = get_literature_entry(literature_id)
                if entry:
                    e = entry if isinstance(entry, dict) else entry.__dict__
                    title = e.get('title', '') if isinstance(e, dict) else (getattr(entry, 'title', '') if hasattr(entry, 'title') else '')
                    abstract = e.get('abstract', '') if isinstance(e, dict) else (getattr(entry, 'abstract', '') if hasattr(entry, 'abstract') else '')
                    context_text = f"文献标题: {title}\n\n摘要: {abstract}"

                    cryoem = e.get('cryoem_targets', {}) if isinstance(e, dict) else (getattr(entry, 'cryoem_targets', {}) if hasattr(entry, 'cryoem_targets') else {})
                    pdb_ids = cryoem.get('pdb_ids', []) if isinstance(cryoem, dict) else []
                    emdb_ids = cryoem.get('emdb_ids', []) if isinstance(cryoem, dict) else []

                    if pdb_ids or emdb_ids:
                        from core.structure_database import StructureOfflineDatabase
                        db = StructureOfflineDatabase()

                        for pdb_id in pdb_ids[:5]:
                            struct = db.get_structure(pdb_id)
                            if struct:
                                s = struct if isinstance(struct, dict) else struct.__dict__
                                info = f"PDB {pdb_id}: "
                                if s.get('title'):
                                    info += f"{s.get('title', '')[:100]}"
                                if s.get('resolution'):
                                    info += f", 分辨率: {s.get('resolution')} Å"
                                structure_info_parts.append(info)

                        for emdb_id in emdb_ids[:5]:
                            struct = db.get_structure(emdb_id)
                            if struct:
                                s = struct if isinstance(struct, dict) else struct.__dict__
                                info = f"EMDB {emdb_id}: "
                                if s.get('title'):
                                    info += f"{s.get('title', '')[:100]}"
                                if s.get('resolution'):
                                    info += f", 分辨率: {s.get('resolution')} Å"
                                structure_info_parts.append(info)

            if structure_info_parts:
                structure_info = "\n\n【相关结构信息】：\n" + "\n".join(structure_info_parts)

            # Get AI client
            client = get_ai_client()
            config = load_ai_config()

            system_prompt = """你是专业的结构生物学文献研究助手。请根据提供的文献内容和结构信息回答问题。

要求：
1. **必须用中文回答**，仅蛋白质名称、结构ID、技术缩写等保留英文
2. 回答要基于事实，引用具体的发现、数据或结论
3. 如果上下文信息不足，请说明需要更多信息
4. 保持回答简洁、专业、准确
5. **重要：如果用户问题中涉及的蛋白/基因/结构在提供的上下文中没有找到相关信息，必须明确告知用户"抱歉，数据库中没有找到相关信息"，禁止编造任何文献、结构、序列或PDB ID**"""

            messages = [{"role": "system", "content": system_prompt}]

            if context_text:
                messages.append({"role": "system", "content": f"【文献上下文】：\n{context_text[:3000]}"})

            if structure_info:
                messages.append({"role": "system", "content": structure_info[:2000]})

            messages.append({"role": "user", "content": question})

            model = config.get('chat_model', 'deepseek-chat')
            result = client.chat(messages, timeout=300)

            if not result['success']:
                return {'answer': result.get('error', 'API调用失败'), 'sources': []}

            return {'answer': result.get('content', ''), 'sources': []}

        except Exception as e:
            import traceback
            logger.error(f"[QA] 错误: {e}")
            traceback.print_exc()
            return {'answer': str(e), 'sources': []}

    def generate():
        """生成器函数，用于 SSE 流式输出"""
        try:
            if not question:
                yield json.dumps({'type': 'error', 'content': 'Question is required'})
                return

            # 步骤1: 理解问题
            logger.info(f"[QA] 步骤1: 理解问题 - {question[:50]}...")
            yield json.dumps({
                'type': 'step', 'step': 1, 'name': '问题理解',
                'message': '正在理解您的问题...', 'progress': 10
            }) + '\n'

            # Get literature entry if ID provided
            context_text = ""
            structure_info = ""
            structure_info_parts = []
            structure_ids = []  # 初始化变量

            if literature_id:
                entry = get_literature_entry(literature_id)
                if entry:
                    e = entry if isinstance(entry, dict) else entry.__dict__
                    title = e.get('title', '') if isinstance(e, dict) else (getattr(entry, 'title', '') if hasattr(entry, 'title') else '')
                    abstract = e.get('abstract', '') if isinstance(e, dict) else (getattr(entry, 'abstract', '') if hasattr(entry, 'abstract') else '')
                    context_text = f"文献标题: {title}\n\n摘要: {abstract}"

                    cryoem = e.get('cryoem_targets', {}) if isinstance(e, dict) else (getattr(entry, 'cryoem_targets', {}) if hasattr(entry, 'cryoem_targets') else {})
                    pdb_ids = cryoem.get('pdb_ids', []) if isinstance(cryoem, dict) else []
                    emdb_ids = cryoem.get('emdb_ids', []) if isinstance(cryoem, dict) else []

                    if pdb_ids or emdb_ids:
                        from core.structure_database import StructureOfflineDatabase
                        db = StructureOfflineDatabase()

                        for pdb_id in pdb_ids[:5]:
                            struct = db.get_structure(pdb_id)
                            if struct:
                                s = struct if isinstance(struct, dict) else struct.__dict__
                                info = f"PDB {pdb_id}: "
                                if s.get('title'):
                                    info += f"{s.get('title', '')[:100]}"
                                if s.get('resolution'):
                                    info += f", 分辨率: {s.get('resolution')} Å"
                                structure_info_parts.append(info)

                        for emdb_id in emdb_ids[:5]:
                            struct = db.get_structure(emdb_id)
                            if struct:
                                s = struct if isinstance(struct, dict) else struct.__dict__
                                info = f"EMDB {emdb_id}: "
                                if s.get('title'):
                                    info += f"{s.get('title', '')[:100]}"
                                if s.get('resolution'):
                                    info += f", 分辨率: {s.get('resolution')} Å"
                                structure_info_parts.append(info)

            if structure_info_parts:
                structure_info = "\n\n【相关结构信息】：\n" + "\n".join(structure_info_parts)

            # 步骤2: 检索知识库
            logger.info("[QA] 步骤2: 检索知识库...")
            yield json.dumps({
                'type': 'step', 'step': 2, 'name': '知识检索',
                'message': '正在检索相关文献和结构信息...', 'progress': 30
            }) + '\n'

            # 步骤3: 构建上下文
            logger.info("[QA] 步骤3: 构建上下文...")
            yield json.dumps({
                'type': 'step', 'step': 3, 'name': '上下文构建',
                'message': '正在构建问答上下文...', 'progress': 50
            }) + '\n'

            # Get AI client
            client = get_ai_client()
            config = load_ai_config()

            system_prompt = """你是专业的结构生物学文献研究助手。请根据提供的文献内容和结构信息回答问题。

要求：
1. **必须用中文回答**，仅蛋白质名称、结构ID、技术缩写等保留英文
2. 回答要基于事实，引用具体的发现、数据或结论
3. 如果上下文信息不足，请说明需要更多信息
4. 保持回答简洁、专业、准确
5. **重要：如果用户问题中涉及的蛋白/基因/结构在提供的上下文中没有找到相关信息，必须明确告知用户"抱歉，数据库中没有找到相关信息"，禁止编造任何文献、结构、序列或PDB ID**"""

            messages = [{"role": "system", "content": system_prompt}]

            if context_text:
                messages.append({"role": "system", "content": f"【文献上下文】：\n{context_text[:3000]}"})

            if structure_info:
                messages.append({"role": "system", "content": structure_info[:2000]})

            messages.append({"role": "user", "content": question})

            # 步骤4: 调用AI
            logger.info("[QA] 步骤4: 调用AI生成回答...")
            yield json.dumps({
                'type': 'step', 'step': 4, 'name': 'AI生成',
                'message': '正在生成回答...', 'progress': 70
            }) + '\n'

            model = config.get('chat_model', 'deepseek-chat')
            result = client.chat(messages, timeout=300)

            if not result['success']:
                yield json.dumps({'type': 'error', 'content': result.get('error', 'API调用失败')}) + '\n'
                return

            # 步骤5: 返回结果
            logger.info("[QA] 步骤5: 回答生成完成")
            yield json.dumps({
                'type': 'step', 'step': 5, 'name': '完成',
                'message': '回答生成完成', 'progress': 100
            }) + '\n'

            # 返回最终答案
            yield json.dumps({
                'type': 'answer',
                'content': result.get('content', ''),
                'model': result.get('model', model)
            }) + '\n'

        except Exception as e:
            import traceback
            logger.error(f"[QA] 错误: {e}")
            traceback.print_exc()
            yield json.dumps({'type': 'error', 'content': str(e)}) + '\n'

    # 根据Accept头决定返回格式
    if wants_json:
        # 返回普通JSON
        result = get_answer()
        return jsonify(result)
    else:
        # 返回SSE流
        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no'
            }
        )


@bp.route('/ai-search', methods=['POST'])
def ai_search():
    """
    AI-enhanced literature search - 使用配置文件的 AI 设置
    """
    try:
        data = request.json
        question = data.get('question', '')
        top_k = data.get('top_k', 5)

        if not question:
            return jsonify({'error': 'Question is required'}), 400

        # Get AI client
        client = get_ai_client()
        config = load_ai_config()

        # Build search query message
        system_prompt = """你是一个文献搜索助手。请根据用户问题，生成一个优化的搜索查询，用于在Cryo-EM和结构生物学文献库中搜索相关论文。

要求：
1. 生成简洁的搜索关键词，包含蛋白质名称，技术方法、或生物学主题
2. **必须用中文回答**，仅蛋白质/基因名称、技术缩写等保留英文
3. 保持查询简洁明确"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"生成搜索查询: {question}"}
        ]

        model = config.get('chat_model', 'deepseek-chat')
        result = client.chat(messages, timeout=120)

        if not result['success']:
            return jsonify({'error': result.get('error', 'API调用失败')}), 500

        search_query = result['content']

        # Now search using vector search (LanceDB)
        from core.search_factory import search_vector
        search_results = search_vector(
            query=search_query,
            top_k=top_k,
            entity_filter=EntityType.LITERATURE,
            search_type='hybrid'
        )

        # Convert vector search results to literature format
        literature_results = []
        for r in search_results:
            doc = r.get('document', {})
            # 使用 full_text 或 content 字段
            text_content = doc.get('full_text', '') or doc.get('content', '') or doc.get('abstract', '')
            literature_results.append({
                'id': r.get('id'),
                'title': doc.get('title', ''),
                'authors': doc.get('authors', []),
                'journal': doc.get('journal', ''),
                'year': doc.get('year'),
                'doi': doc.get('doi', ''),
                'abstract': text_content,  # 返回完整内容
                'content': text_content,
                'score': r.get('score', 0),
            })

        return jsonify({
            'answer': f"搜索查询: {search_query}",
            'literature': literature_results,
            'structures': []
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/suggest-questions', methods=['POST'])
def suggest_questions():
    """
    Generate suggested questions based on literature
    """
    try:
        data = request.json
        literature_id = data.get('literature_id')

        if not literature_id:
            return jsonify({'error': 'Literature ID is required'}), 400

        from core.literature_db import get_literature_entry
        entry = get_literature_entry(literature_id)

        if not entry:
            return jsonify({'error': 'Literature not found'}), 404

        # Generate suggested questions based on the paper
        title = entry.title if hasattr(entry, 'title') else str(entry.get('title', ''))

        # Simple question generation based on common patterns
        suggestions = [
            f"What is the main finding of '{title[:30]}...'",
            "What methods were used in this study?",
            "What are the key conclusions?",
            "What is the resolution of the structure?",
            "What proteins or molecules were studied?"
        ]

        return jsonify({'suggestions': suggestions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ========== QA Chat History Endpoints ==========

@bp.route('/history', methods=['GET'])
def get_qa_history():
    """获取QA聊天历史列表

    支持两种模式：
    1. 登录用户：获取用户的所有历史记录
    2. 未登录用户：通过 session_id 获取当前会话的历史记录
    """
    try:
        literature_id = request.args.get('literature_id', type=int)
        session_id = request.args.get('session_id')  # 支持按session获取
        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)

        from core.literature_db import get_qa_chat_history
        user_id = get_current_user_id()

        # 优先使用 user_id，如果没有则使用 session_id
        if user_id:
            history_list = get_qa_chat_history(
                literature_id=literature_id,
                limit=limit,
                offset=offset,
                user_id=user_id
            )
        elif session_id:
            # 未登录用户：按 session_id 获取历史
            history_list = get_qa_chat_history(
                literature_id=literature_id,
                limit=limit,
                offset=offset,
                session_id=session_id
            )
        else:
            # 既没有 user_id 也没有 session_id，返回空列表
            history_list = []

        return jsonify({
            'success': True,
            'items': [h.to_dict() for h in history_list],
            'total': len(history_list)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/history/<int:history_id>', methods=['GET'])
def get_qa_history_detail(history_id):
    """获取单条QA聊天记录详情"""
    try:
        from core.literature_db import get_qa_chat_history_by_id
        user_id = get_current_user_id()
        history = get_qa_chat_history_by_id(history_id, user_id)
        if not history:
            return jsonify({'error': '记录不存在'}), 404
        return jsonify({
            'success': True,
            'data': history.to_dict()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/history/<int:history_id>', methods=['DELETE'])
def delete_qa_history(history_id):
    """删除QA聊天记录"""
    try:
        from core.literature_db import delete_qa_chat_history
        user_id = get_current_user_id()
        success = delete_qa_chat_history(history_id, user_id)
        return jsonify({
            'success': success,
            'message': '删除成功' if success else '记录不存在'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
