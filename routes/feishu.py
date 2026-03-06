"""
飞书集成 API 路由
"""
import os
import json
import logging
import uuid
from datetime import datetime
from flask import Blueprint, jsonify, request, render_template
from flask_login import current_user
import requests

logger = logging.getLogger(__name__)

bp = Blueprint('feishu', __name__, url_prefix='/api/feishu')


def get_current_user_id():
    """获取当前登录用户的ID，未登录返回None"""
    if current_user.is_authenticated:
        return current_user.id
    return None

# 配置文件路径
FEISHU_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'feishu_config.json'
)

# 飞书API基础URL
FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"

# 已处理消息缓存（防止重复处理）
_processed_messages = set()
_processed_messages_ttl = 300  # 5分钟 TTL


def load_feishu_config():
    """加载飞书配置"""
    if os.path.exists(FEISHU_CONFIG_FILE):
        try:
            with open(FEISHU_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载飞书配置失败: {e}")
    return {
        "enabled": False,
        "app_id": "",
        "app_secret": "",
        "verification_token": "",
        "encrypt_key": "",
        "bot_id": "",
        "webhook_url": "",
        "documents": []
    }


def save_feishu_config(config):
    """保存飞书配置"""
    try:
        with open(FEISHU_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"保存飞书配置失败: {e}")
        return False


def get_feishu_client():
    """获取飞书客户端实例"""
    config = load_feishu_config()
    if not config.get("app_id") or not config.get("app_secret"):
        return None

    from flask_app.utils.feishu_client import FeishuClient
    return FeishuClient(config["app_id"], config["app_secret"])


@bp.route('/folders', methods=['GET'])
def get_folders():
    """获取配置的监控文件夹列表"""
    config = load_feishu_config()
    folders = config.get("monitor_folders", [])
    return jsonify({"success": True, "folders": folders})


@bp.route('/folders', methods=['POST'])
def add_folder():
    """添加监控文件夹"""
    try:
        data = request.json or {}
        folder_token = data.get("folder_token", "").strip()
        folder_name = data.get("folder_name", "").strip()

        if not folder_token:
            return jsonify({"success": False, "message": "请输入文件夹 Token"})

        config = load_feishu_config()
        folders = config.get("monitor_folders", [])

        # 检查是否已存在
        for f in folders:
            if f.get("folder_token") == folder_token:
                return jsonify({"success": False, "message": "该文件夹已在监控列表中"})

        # 添加文件夹
        folders.append({
            "folder_token": folder_token,
            "folder_name": folder_name or folder_token,
            "added_at": datetime.now().isoformat()
        })

        config["monitor_folders"] = folders
        save_feishu_config(config)

        return jsonify({"success": True, "message": "文件夹添加成功"})

    except Exception as e:
        logger.error(f"添加文件夹失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@bp.route('/folders/<folder_token>', methods=['DELETE'])
def delete_folder(folder_token):
    """删除监控文件夹"""
    try:
        config = load_feishu_config()
        folders = config.get("monitor_folders", [])
        folders = [f for f in folders if f.get("folder_token") != folder_token]
        config["monitor_folders"] = folders
        save_feishu_config(config)

        return jsonify({"success": True, "message": "文件夹删除成功"})

    except Exception as e:
        logger.error(f"删除文件夹失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@bp.route('/folders/sync', methods=['POST'])
def sync_folders():
    """同步所有监控文件夹中的文档"""
    try:
        config = load_feishu_config()
        folders = config.get("monitor_folders", [])

        if not folders:
            return jsonify({"success": False, "message": "没有配置监控文件夹"})

        client = get_feishu_client()
        if not client:
            return jsonify({"success": False, "message": "请先配置飞书应用凭证"})

        from flask_app.services.feishu_document import FeishuDocumentService
        doc_service = FeishuDocumentService(client)

        synced_count = 0
        error_count = 0

        for folder in folders:
            folder_token = folder.get("folder_token")
            folder_name = folder.get("folder_name", "未知")

            # 尝试获取文件夹元数据
            try:
                folder_meta = client.get_folder_meta(folder_token)
                if folder_meta and folder_meta.get("name"):
                    folder_name = folder_meta["name"]
                    # 更新配置中的文件夹名称
                    folder["folder_name"] = folder_name
            except Exception as e:
                logger.warning(f"获取文件夹 {folder_token} 元数据失败: {e}")

            logger.info(f"正在同步文件夹: {folder_name}, token: {folder_token}")
            try:
                # 获取文件夹中的文件
                files_data = client.get_folder_files(folder_token=folder_token)
                logger.info(f"API返回: {files_data}")
                files = files_data.get("files", [])

                logger.info(f"文件夹 {folder_name} 共有 {len(files)} 个文件")

                for file in files:
                    file_type = file.get("type")
                    file_token = file.get("token")
                    file_name = file.get("name")

                    # 只处理文档类型
                    # 处理文档和快捷方式
                    actual_token = file_token
                    if file_type == "shortcut":
                        # 快捷方式需要使用target_token
                        shortcut_info = file.get("shortcut_info", {})
                        actual_token = shortcut_info.get("target_token", file_token)
                        logger.info(f"快捷方式 {file_name} -> {actual_token}")

                    if file_type in ["docx", "doc", "shortcut"]:
                        try:
                            logger.info(f"正在同步文档: {file_name} (type: {file_type}, token: {actual_token})")
                            # 获取并索引文档
                            doc_data = doc_service.fetch_document(actual_token, folder_name)
                            doc_service.vectorize_and_index(doc_data)
                            synced_count += 1
                            logger.info(f"已同步文档: {file_name}")
                        except Exception as e:
                            logger.error(f"同步文档 {file_name} 失败: {e}")
                            error_count += 1

            except Exception as e:
                logger.error(f"同步文件夹 {folder_name} 失败: {e}")
                error_count += 1

        # 保存更新后的文件夹名称
        save_feishu_config(config)

        # 如果没有找到任何文档，提示用户
        if synced_count == 0 and error_count == 0:
            return jsonify({
                "success": True,
                "message": "未找到需要同步的文档。请检查：1) 文件夹是否有文档；2) 应用是否有文件夹访问权限"
            })

        return jsonify({
            "success": True,
            "message": f"同步完成：成功 {synced_count} 个，失败 {error_count} 个"
        })

    except Exception as e:
        logger.error(f"同步文件夹失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@bp.route('/config', methods=['GET'])
def get_config():
    """获取飞书配置"""
    config = load_feishu_config()

    return jsonify({"success": True, "config": config})


@bp.route('/config', methods=['POST'])
def save_config():
    """保存飞书配置"""
    try:
        data = request.json or {}

        config = load_feishu_config()

        # 更新配置
        if "enabled" in data:
            config["enabled"] = bool(data.get("enabled"))
        if "app_id" in data:
            config["app_id"] = data.get("app_id", "").strip()
        if "app_secret" in data and data.get("app_secret") != "***":
            config["app_secret"] = data.get("app_secret", "").strip()
        if "verification_token" in data and data.get("verification_token") != "***":
            config["verification_token"] = data.get("verification_token", "").strip()
        if "encrypt_key" in data and data.get("encrypt_key") != "***":
            config["encrypt_key"] = data.get("encrypt_key", "").strip()
        if "bot_id" in data:
            config["bot_id"] = data.get("bot_id", "").strip()
        if "webhook_url" in data:
            config["webhook_url"] = data.get("webhook_url", "").strip()

        if save_feishu_config(config):
            return jsonify({"success": True, "message": "配置已保存"})
        else:
            return jsonify({"success": False, "message": "保存配置失败"})

    except Exception as e:
        logger.error(f"保存飞书配置失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@bp.route('/test', methods=['POST'])
def test_connection():
    """测试飞书连接"""
    try:
        data = request.json or {}
        app_id = data.get("app_id", "").strip()
        app_secret = data.get("app_secret", "").strip()

        if not app_id or not app_secret:
            return jsonify({"success": False, "message": "请输入 App ID 和 App Secret"})

        # 创建临时客户端测试连接
        from flask_app.utils.feishu_client import FeishuClient
        client = FeishuClient(app_id, app_secret)

        # 测试获取token
        token = client.get_tenant_access_token()

        return jsonify({
            "success": True,
            "message": "连接成功",
            "token": token[:20] + "..."
        })

    except requests.exceptions.RequestException as e:
        logger.error(f"飞书连接测试失败: {e}")
        return jsonify({"success": False, "message": f"连接失败: {str(e)}"})
    except Exception as e:
        logger.error(f"飞书连接测试失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@bp.route('/documents', methods=['GET'])
def get_documents():
    """获取已同步的飞书文档列表"""
    config = load_feishu_config()
    return jsonify({
        "success": True,
        "documents": config.get("documents", [])
    })


@bp.route('/documents/fetch', methods=['POST'])
def fetch_document():
    """获取并同步飞书文档"""
    try:
        data = request.json or {}
        doc_token = data.get("doc_token", "").strip()

        if not doc_token:
            return jsonify({"success": False, "message": "请输入文档 Token"})

        # 获取客户端
        client = get_feishu_client()
        if not client:
            return jsonify({"success": False, "message": "请先配置飞书应用凭证"})

        # 获取文档
        from flask_app.services.feishu_document import FeishuDocumentService
        doc_service = FeishuDocumentService(client)

        # 获取并解析文档
        doc_data = doc_service.fetch_document(doc_token)

        # 向量化并索引
        doc_service.vectorize_and_index(doc_data)

        # 更新配置中的文档列表
        config = load_feishu_config()
        documents = config.get("documents", [])

        # 检查是否已存在
        doc_info = {
            "doc_id": doc_data["doc_id"],
            "source_id": doc_data["source_id"],
            "title": doc_data["title"],
            "fetched_at": doc_data["metadata"]["fetched_at"]
        }

        # 移除已存在的相同文档
        documents = [d for d in documents if d.get("source_id") != doc_token]
        documents.append(doc_info)

        config["documents"] = documents
        save_feishu_config(config)

        return jsonify({
            "success": True,
            "message": f"文档 '{doc_data['title']}' 获取并索引成功",
            "document": doc_info
        })

    except Exception as e:
        logger.error(f"获取飞书文档失败: {e}")
        error_msg = str(e)
        # 提供更友好的错误提示
        if "404" in error_msg:
            return jsonify({"success": False, "message": "文档获取失败: 请检查文档 Token 是否正确，或者该文档是否对应用开放了权限"})
        elif "401" in error_msg or "unauthorized" in error_msg.lower():
            return jsonify({"success": False, "message": "认证失败: 请检查 App ID 和 App Secret 是否正确"})
        elif "permission" in error_msg.lower():
            return jsonify({"success": False, "message": "权限不足: 请确保飞书应用已开通文档权限"})
        else:
            return jsonify({"success": False, "message": f"获取文档失败: {error_msg}"})


@bp.route('/documents/delete', methods=['POST'])
def delete_document():
    """删除飞书文档"""
    try:
        data = request.json or {}
        doc_id = data.get("doc_id", "")

        if not doc_id:
            return jsonify({"success": False, "message": "请指定要删除的文档"})

        # 获取文档服务并删除
        from flask_app.services.feishu_document import FeishuDocumentService
        doc_service = FeishuDocumentService(None)

        if doc_service.delete_document(doc_id):
            # 更新配置
            config = load_feishu_config()
            documents = [d for d in config.get("documents", []) if d.get("doc_id") != doc_id]
            config["documents"] = documents
            save_feishu_config(config)

            return jsonify({"success": True, "message": "文档已删除"})
        else:
            return jsonify({"success": False, "message": "删除文档失败"})

    except Exception as e:
        logger.error(f"删除飞书文档失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@bp.route('/webhook/feishu', methods=['GET', 'POST'])
def webhook_feishu():
    """飞书回调Web端点（兼容ngrok路径）"""
    return webhook()


@bp.route('/webhook', methods=['GET', 'POST'])
def webhook():
    """
    飞书回调Webhook端点
    支持URL验证和消息事件
    """
    try:
        config = load_feishu_config()

        # GET请求用于URL验证
        if request.method == 'GET':
            challenge = request.args.get("challenge")
            verification_token = config.get("verification_token", "")

            if challenge and verification_token:
                # 验证token
                if verification_token == request.args.get("verification_token"):
                    return jsonify({"challenge": challenge})
                else:
                    return jsonify({"error": "verification_token mismatch"}), 403
            return jsonify({"challenge": challenge})

        # POST请求处理事件
        data = request.json or {}
        logger.info(f"收到飞书回调: {json.dumps(data)[:500]}")

        # 处理加密内容
        encrypt_key = config.get("encrypt_key", "")
        if encrypt_key and data.get("encrypt"):
            try:
                from flask_app.utils.feishu_client import FeishuClient
                decrypted = FeishuClient.decrypt_content(encrypt_key, data.get("encrypt"))
                data = json.loads(decrypted)
            except Exception as e:
                logger.error(f"解密失败: {e}")
                return jsonify({"error": "decrypt failed"}), 400

        # 获取事件类型
        header = data.get("header", {})
        event_type = header.get("event_type", "")

        # URL验证事件
        if event_type == "url_verification":
            challenge = data.get("challenge", "")
            return jsonify({"challenge": challenge})

        # 消息接收事件
        if event_type == "im.message.receive_v1":
            return handle_message_event(data, config)

        # 其他事件类型
        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"处理飞书回调失败: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route('/webhook-mode/enable', methods=['POST'])
def enable_webhook_mode():
    """启用Webhook模式"""
    try:
        config = load_feishu_config()

        if not config.get('app_id') or not config.get('app_secret'):
            return jsonify({"success": False, "message": "请先配置飞书应用凭证"})

        # 更新配置
        config['enabled'] = True
        save_feishu_config(config)

        return jsonify({
            "success": True,
            "message": "Webhook模式已启用。请在飞书开放平台配置回调URL为: http://your-domain.com/api/feishu/webhook"
        })

    except Exception as e:
        logger.error(f"启用Webhook模式失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@bp.route('/webhook-mode/disable', methods=['POST'])
def disable_webhook_mode():
    """禁用Webhook模式"""
    try:
        config = load_feishu_config()
        config['enabled'] = False
        save_feishu_config(config)

        return jsonify({"success": True, "message": "Webhook模式已禁用"})

    except Exception as e:
        logger.error(f"禁用Webhook模式失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@bp.route('/webhook-mode/status', methods=['GET'])
def get_webhook_mode_status():
    """获取Webhook模式状态"""
    try:
        config = load_feishu_config()
        enabled = config.get('enabled', False)
        # 优先使用配置中的webhook_url，否则使用默认
        webhook_url = config.get('webhook_url') or f"{request.host_url}api/feishu/webhook"

        return jsonify({
            "success": True,
            "enabled": enabled,
            "message": "已启用" if enabled else "未启用",
            "webhook_url": webhook_url
        })

    except Exception as e:
        logger.error(f"获取Webhook模式状态失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@bp.route('/webhook-mode/set-url', methods=['POST'])
def set_webhook_url():
    """设置自定义Webhook URL"""
    try:
        data = request.json or {}
        webhook_url = data.get('webhook_url', '').strip()

        config = load_feishu_config()
        config['webhook_url'] = webhook_url
        save_feishu_config(config)

        return jsonify({
            "success": True,
            "message": "Webhook URL已更新"
        })

    except Exception as e:
        logger.error(f"设置Webhook URL失败: {e}")
        return jsonify({"success": False, "message": str(e)})


def handle_message_event(event_data: dict, config: dict):
    """处理飞书消息事件"""
    try:
        # 提取消息内容
        message = event_data.get("event", {}).get("message", {})
        msg_type = message.get("msg_type", "")
        content_raw = message.get("content", "")

        # 解析消息内容 - 可能是JSON字符串或dict
        content = content_raw
        if isinstance(content_raw, str):
            try:
                content = json.loads(content_raw)
            except json.JSONDecodeError:
                content = {"text": content_raw}

        # 解析消息文本
        if msg_type == "text":
            text_content = content.get("text", "") if isinstance(content, dict) else str(content)
        else:
            # 其他类型消息处理
            text_content = json.dumps(content) if not isinstance(content, str) else content

        # 获取发送者信息
        sender_id = message.get("sender_id", {}).get("open_id", "")
        message_id = message.get("message_id", "")

        # 去重检查：避免处理重复消息
        if message_id and message_id in _processed_messages:
            logger.info(f"跳过重复消息: {message_id}")
            return jsonify({"success": True, "skipped": True})
        if message_id:
            _processed_messages.add(message_id)
            # 清理过期的消息ID
            if len(_processed_messages) > 1000:
                _processed_messages.clear()

        if not text_content:
            return jsonify({"success": True})

        logger.info(f"收到消息 from {sender_id}: {text_content[:100]}")

        # 调用RAG系统回答问题
        answer = answer_question(text_content, knowledge_base="feishu")

        # 发送回复
        client = get_feishu_client()
        if client:
            client.reply_message(
                message_id=message_id,
                msg_type="text",
                content={"text": answer}
            )

        # 注意：ask-v2端点已经保存了历史记录，这里不再重复保存

        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"处理消息事件失败: {e}")
        return jsonify({"error": str(e)}), 500


def save_to_qa_history(question: str, answer: str, source: str = "feishu"):
    """保存问答到历史记录"""
    try:
        from core.literature_db import save_qa_chat_history
        user_id = get_current_user_id()

        history_id = save_qa_chat_history(
            question=question,
            answer=answer,
            literature_id=None,
            user_id=user_id,
            model_used="MiniMax-M2.1",
            sources=[],
            question_type="feishu"
        )
        logger.info(f"保存飞书问答到历史记录: ID={history_id}")
        return history_id
    except Exception as e:
        logger.error(f"保存历史记录失败: {e}")
        return None


def answer_question(question: str, knowledge_base: str = "all") -> str:
    """
    使用QA系统的API回答问题

    Args:
        question: 用户问题
        knowledge_base: 知识库来源 ("literature", "feishu", "all") - 当前忽略，使用全部知识库

    Returns:
        回答文本
    """
    try:
        import requests
        from flask import Flask
        app = Flask(__name__)

        # 使用应用上下文获取base URL
        with app.app_context():
            # 通过HTTP调用QA API (使用ask-v2端点以启用RAG检索)
            response = requests.post(
                'http://127.0.0.1:5000/api/qa/ask-v2',
                json={'question': question},
                headers={'Accept': 'application/json'},
                timeout=120
            )

            if response.status_code == 200:
                data = response.json()
                # 解析SSE格式或JSON格式
                answer = data.get('answer', '')
                if not answer and data.get('message'):
                    # 可能是SSE格式，尝试解析
                    answer = data.get('message', '')
                return answer or "未找到答案"
            else:
                logger.error(f"QA API返回错误: {response.status_code}")
                return f"调用问答服务失败: {response.status_code}"

    except Exception as e:
        logger.error(f"调用QA API失败: {e}")
        return f"处理问题时发生错误: {str(e)}"
        logger.error(f"回答问题失败: {e}")
        return f"处理问题时发生错误: {str(e)}"


@bp.route('/', methods=['GET'])
def config_page():
    """飞书配置页面"""
    config = load_feishu_config()

    # 返回完整配置（前端需要显示实际值）
    return render_template('feishu_config.html', config=config)


@bp.route('/documents/list', methods=['GET'])
def list_documents():
    """获取所有文档列表（包含内容）"""
    try:
        from flask_app.services.feishu_document import FEISHU_DOCS_DIR
        import os

        documents = []
        if os.path.exists(FEISHU_DOCS_DIR):
            for filename in os.listdir(FEISHU_DOCS_DIR):
                if filename.endswith(".json") and not filename.startswith("__"):
                    filepath = os.path.join(FEISHU_DOCS_DIR, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            content = f.read()
                            doc = json.loads(content)
                            content_text = doc.get("content", "")
                            documents.append({
                                "doc_id": doc.get("doc_id"),
                                "title": doc.get("title"),
                                "source_id": doc.get("source_id"),
                                "content": content_text[:500] if content_text else "",
                                "full_content": content_text,
                                "metadata": doc.get("metadata", {})
                            })
                    except json.JSONDecodeError as e:
                        logger.error(f"解析文档 {filename} JSON失败: {e}")
                    except Exception as e:
                        logger.error(f"读取文档 {filename} 失败: {e}")

        return jsonify({"success": True, "documents": documents})

    except Exception as e:
        logger.error(f"获取文档列表失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@bp.route('/documents/<doc_id>', methods=['GET'])
def get_document(doc_id):
    """获取单个文档详情"""
    try:
        from flask_app.services.feishu_document import FEISHU_DOCS_DIR
        import os

        filepath = None
        if os.path.exists(FEISHU_DOCS_DIR):
            for filename in os.listdir(FEISHU_DOCS_DIR):
                if filename.startswith(doc_id):
                    filepath = os.path.join(FEISHU_DOCS_DIR, filename)
                    break

        if not filepath or not os.path.exists(filepath):
            return jsonify({"success": False, "message": "文档不存在"})

        with open(filepath, "r", encoding="utf-8") as f:
            doc = json.load(f)

        return jsonify({
            "success": True,
            "document": {
                "doc_id": doc.get("doc_id"),
                "title": doc.get("title"),
                "source_id": doc.get("source_id"),
                "content": doc.get("content", ""),
                "metadata": doc.get("metadata", {})
            }
        })

    except Exception as e:
        logger.error(f"获取文档失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@bp.route('/rebuild-index', methods=['POST'])
def rebuild_index():
    """重建所有飞书文档的索引"""
    try:
        from flask_app.services.feishu_document import FEISHU_DOCS_DIR
        import os

        # 获取所有文档
        if not os.path.exists(FEISHU_DOCS_DIR):
            return jsonify({"success": False, "message": "没有找到任何飞书文档"})

        # 初始化RAG系统
        from core.literature_index import UnifiedRAGSystem, UnifiedDocument, EntityType
        rag_system = UnifiedRAGSystem()

        count = 0
        files = os.listdir(FEISHU_DOCS_DIR)
        logger.info(f"Found {len(files)} files in {FEISHU_DOCS_DIR}")

        for filename in files:
            if filename.endswith(".json") and not filename.startswith("__"):
                filepath = os.path.join(FEISHU_DOCS_DIR, filename)
                logger.info(f"Processing file: {filename}")
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        doc_data = json.load(f)

                    logger.info(f"Document title: {doc_data.get('title', 'N/A')}, content length: {len(doc_data.get('content', ''))}")

                    # 检查FAISS是否可用
                    try:
                        import faiss
                        # FAISS可用，添加到索引
                        doc = UnifiedDocument(
                            doc_id=doc_data.get("doc_id", f"feishu_{uuid.uuid4().hex[:8]}"),
                            entity_type=EntityType.LITERATURE,
                            source_id=doc_data.get("source_id", ""),
                            title=doc_data.get("title", ""),
                            content=doc_data.get("content", ""),
                            metadata={
                                **doc_data.get("metadata", {}),
                                "feishu_doc_id": doc_data.get("doc_id"),
                                "is_feishu": True
                            }
                        )

                        # 添加到索引
                        rag_system.add_document(doc)
                        count += 1
                        logger.info(f"已索引文档: {doc_data.get('title', '未知')}")
                    except ImportError:
                        # FAISS不可用，只记录文档信息
                        count += 1
                        logger.info(f"FAISS未安装，跳过向量索引，文档已记录: {doc_data.get('title', '未知')}")

                except Exception as e:
                    logger.error(f"索引文档 {filename} 失败: {e}")

        return jsonify({
            "success": True,
            "message": f"索引重建成功，已处理 {count} 个文档"
        })

    except Exception as e:
        logger.error(f"重建索引失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@bp.route('/search', methods=['POST'])
def search_feishu():
    """在飞书知识库中搜索"""
    try:
        data = request.json or {}
        query = data.get("query", "").strip()
        top_k = data.get("top_k", 5)

        if not query:
            return jsonify({"success": False, "message": "请输入搜索内容"})

        # 获取客户端
        client = get_feishu_client()
        if not client:
            return jsonify({"success": False, "message": "请先配置飞书应用凭证"})

        # 搜索
        from flask_app.services.feishu_document import FeishuDocumentService
        doc_service = FeishuDocumentService(client)
        results = doc_service.search(query, top_k=top_k)

        return jsonify({
            "success": True,
            "results": results
        })

    except Exception as e:
        logger.error(f"搜索失败: {e}")
        return jsonify({"success": False, "message": str(e)})
