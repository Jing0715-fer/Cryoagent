"""
飞书长连接服务
用于接收飞书消息回调并通过AI自动回复
"""
import os
import sys
import json
import logging
import threading
import time

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lark_oapi as lark
from lark_oapi.event.callback.model.p2_im_message_receive_v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_im_message_receive_v1 import P2ImMessageReceiveV1Response

logger = logging.getLogger(__name__)


class FeishuLongConnection:
    """飞书长连接客户端"""

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.client = None
        self.rag_system = None
        self._running = False

    def set_rag_system(self, rag_system):
        """设置RAG系统用于问答"""
        self.rag_system = rag_system

    def handle_message(self, data: P2ImMessageReceiveV1) -> P2ImMessageReceiveV1Response:
        """处理接收到的消息"""
        try:
            event = data.event
            if not event or not event.message:
                logger.warning("收到空消息事件")
                return P2ImMessageReceiveV1Response()

            message = event.message
            msg_type = message.msg_type
            content = message.content
            receive_id = message.sender_id

            logger.info(f"收到消息: msg_type={msg_type}, sender_id={receive_id}, content={content[:100] if content else 'empty'}...")

            # 只处理文本消息
            if msg_type != "text":
                logger.info(f"忽略非文本消息: {msg_type}")
                return P2ImMessageReceiveV1Response()

            # 解析文本内容
            try:
                content_json = json.loads(content) if content else {}
                text = content_json.get("text", "").strip()
            except json.JSONDecodeError:
                text = content.strip() if content else ""

            if not text:
                logger.warning("消息内容为空")
                return P2ImMessageReceiveV1Response()

            logger.info(f"用户消息: {text[:100]}...")

            # 调用AI回答
            answer = self.get_ai_answer(text)
            logger.info(f"AI回答: {answer[:100]}...")

            # 发送回复
            self.send_message(message.chat_id, answer)

            return P2ImMessageReceiveV1Response()

        except Exception as e:
            logger.error(f"处理消息失败: {e}", exc_info=True)
            return P2ImMessageReceiveV1Response()

    def get_ai_answer(self, query: str) -> str:
        """获取AI回答"""
        try:
            if self.rag_system is None:
                # 延迟导入RAG系统
                from literature_index import UnifiedRAGSystem
                self.rag_system = UnifiedRAGSystem()

            # 检索相关文档
            results = self.rag_system.retrieve(query, top_k=3)

            if results:
                # 构建上下文
                context = "\n\n".join([
                    f"来源: {r.get('metadata', {}).get('title', '未知')}\n{r.get('content', '')[:500]}"
                    for r in results
                ])

                prompt = f"""基于以下参考资料回答用户问题。如果资料中没有相关信息，请如实说明。

参考资料:
{context}

用户问题: {query}

回答:"""

                # 调用LLM生成回答
                from agent_core import get_llm_response
                answer = get_llm_response(prompt)
                return answer
            else:
                return "抱歉，我在知识库中没有找到相关信息。"

        except Exception as e:
            logger.error(f"获取AI回答失败: {e}", exc_info=True)
            return f"处理问题时出现错误: {str(e)}"

    def send_message(self, chat_id: str, text: str):
        """发送消息"""
        try:
            # 延迟创建客户端
            if not hasattr(self, '_feishu_client'):
                from utils.feishu_client import FeishuClient
                from utils.feishu_client import load_feishu_config

                config = load_feishu_config()
                self._feishu_client = FeishuClient(config['app_id'], config['app_secret'])

            self._feishu_client.send_text_message(
                receive_id=chat_id,
                text=text,
                receive_id_type="chat_id"
            )
            logger.info(f"消息已发送至群聊: {chat_id}")

        except Exception as e:
            logger.error(f"发送消息失败: {e}", exc_info=True)

    def start(self):
        """启动长连接"""
        if self._running:
            logger.warning("长连接已在运行中")
            return

        # 创建事件处理器
        def on_message(data: P2ImMessageReceiveV1) -> P2ImMessageReceiveV1Response:
            return self.handle_message(data)

        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(on_message) \
            .build()

        # 创建客户端
        self.client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO
        )

        self._running = True

        logger.info("正在连接飞书长连接...")
        try:
            self.client.start()
        except KeyboardInterrupt:
            logger.info("收到中断信号，停止长连接")
            self.stop()
        except Exception as e:
            logger.error(f"长连接出错: {e}", exc_info=True)
            self._running = False

    def stop(self):
        """停止长连接"""
        self._running = False
        logger.info("飞书长连接已停止")


# 全局长连接实例
_long_connection_instance = None
_long_connection_thread = None


def start_feishu_long_connection(app_id: str = None, app_secret: str = None):
    """启动飞书长连接（后台线程）"""
    global _long_connection_instance, _long_connection_thread

    # 如果没有提供参数，从配置加载
    if not app_id or not app_secret:
        from utils.feishu_client import load_feishu_config
        config = load_feishu_config()
        app_id = config.get('app_id')
        app_secret = config.get('app_secret')

    if not app_id or not app_secret:
        logger.error("未配置飞书应用凭证")
        return False

    if _long_connection_instance and _long_connection_instance._running:
        logger.warning("长连接已在运行")
        return True

    _long_connection_instance = FeishuLongConnection(app_id, app_secret)

    # 在后台线程中运行
    _long_connection_thread = threading.Thread(target=_long_connection_instance.start, daemon=True)
    _long_connection_thread.start()

    logger.info("飞书长连接已在后台启动")
    return True


def stop_feishu_long_connection():
    """停止飞书长连接"""
    global _long_connection_instance

    if _long_connection_instance:
        _long_connection_instance.stop()
        _long_connection_instance = None
        logger.info("飞书长连接已停止")
        return True
    return False


def is_long_connection_running():
    """检查长连接是否在运行"""
    global _long_connection_instance
    return _long_connection_instance is not None and _long_connection_instance._running


if __name__ == "__main__":
    # 测试用
    logging.basicConfig(level=logging.INFO)

    from utils.feishu_client import load_feishu_config

    config = load_feishu_config()
    if config.get('app_id') and config.get('app_secret'):
        start_feishu_long_connection(config['app_id'], config['app_secret'])
    else:
        print("请先配置飞书应用凭证")
