"""
统一 AI 客户端 - 支持 OpenAI/DeepSeek 和 Anthropic Claude API
"""
import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Config file path
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ai_config.json')


def load_ai_config() -> Dict[str, Any]:
    """Load AI configuration from file"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")
    return {}


def get_model_config(model_id: str = None) -> Dict[str, Any]:
    """Get model configuration by model_id, or return active model config"""
    config = load_ai_config()

    # If no model_id provided, try to get active model
    if not model_id:
        model_id = config.get('active_model_id', '')

    # Find model by ID
    models = config.get('models', [])
    for model in models:
        if model.get('id') == model_id:
            # Use api_format from model if available, otherwise fallback to api_provider
            api_format = model.get('api_format', config.get('api_provider', 'openai'))
            return {
                'api_provider': api_format,
                'api_base': model.get('api_base', ''),
                'api_key': model.get('api_key', ''),
                'chat_model': model.get('chat_model', ''),
                'api_format': api_format
            }

    # Fallback to legacy config fields
    return {
        'api_provider': config.get('api_provider', 'openai'),
        'api_base': config.get('api_base', ''),
        'api_key': config.get('api_key', ''),
        'chat_model': config.get('chat_model', ''),
        'api_format': config.get('api_provider', 'openai')
    }


def get_ai_client(model_id: str = None):
    """
    创建统一的 AI 客户端
    根据配置自动选择 OpenAI 兼容 API 或 Anthropic API
    """
    model_config = get_model_config(model_id)
    # Use api_format from model config, fallback to api_provider for backwards compatibility
    provider = model_config.get('api_format', model_config.get('api_provider', 'openai'))
    api_base = model_config.get('api_base', '')
    api_key = model_config.get('api_key', '')
    chat_model = model_config.get('chat_model', '')

    if provider == 'anthropic':
        return AnthropicClient(api_key=api_key, model=chat_model, base_url=api_base)
    else:
        return OpenAIClient(api_key=api_key, base_url=api_base, model=chat_model)


class OpenAIClient:
    """OpenAI 兼容 API 客户端"""

    def __init__(self, api_key: str, base_url: str = None, model: str = None):
        self.api_key = api_key
        self.base_url = base_url or 'https://api.deepseek.com'
        self.model = model or 'deepseek-chat'
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            # 创建OpenAI客户端，增加超时时间用于长文本处理
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=300.0  # 5分钟超时
            )
        return self._client

    def chat(self, messages, temperature=0.3, max_tokens=None, timeout=300):
        """发送对话请求"""
        try:
            # MiniMax 兼容性：移除不支持的参数
            kwargs = {
                'model': self.model,
                'messages': messages,
                'timeout': timeout
            }
            if max_tokens:
                kwargs['max_tokens'] = max_tokens
            # 只在明确设置非默认值时添加 temperature
            if temperature is not None and temperature != 0.3:
                kwargs['temperature'] = temperature

            logger.info(f"[AI Client] Request: model={self.model}, msg_count={len(messages)}, max_tokens={max_tokens}")
            for i, msg in enumerate(messages[:3]):  # 只打印前3条
                content_preview = msg.get('content', '')[:100].replace('\n', ' ')
                logger.info(f"[AI Client] Msg {i}: role={msg.get('role')}, content={content_preview}...")

            response = self.client.chat.completions.create(**kwargs)
            return {
                'success': True,
                'content': response.choices[0].message.content,
                'model': self.model
            }
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return {'success': False, 'error': str(e)}

    def json_chat(self, messages, temperature=0.1, timeout=180):
        """发送 JSON 模式对话请求"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
                timeout=timeout
            )
            return {
                'success': True,
                'content': response.choices[0].message.content,
                'model': self.model
            }
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return {'success': False, 'error': str(e)}


class AnthropicClient:
    """Anthropic Claude API 客户端 (支持 MiniMax)"""

    def __init__(self, api_key: str, model: str = None, base_url: str = None):
        self.api_key = api_key
        self.model = model or 'claude-sonnet-4-20250514'
        self.base_url = base_url
        self._client = None
        self._anthropic_available = None

    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
                import os
                self._anthropic_available = True

                # MiniMax 需要设置环境变量和base_url
                if self.base_url and 'minimaxi' in self.base_url.lower():
                    os.environ['ANTHROPIC_BASE_URL'] = self.base_url
                    os.environ['ANTHROPIC_API_KEY'] = self.api_key
                    print(f"[DEBUG] Setting ANTHROPIC_BASE_URL={self.base_url}")

                # 创建客户端 - 明确传递base_url
                client_kwargs = {
                    'api_key': self.api_key,
                    'timeout': 60.0
                }
                # 如果有base_url，传递给客户端
                if self.base_url:
                    client_kwargs['base_url'] = self.base_url
                    print(f"[DEBUG] Passing base_url to Anthropic client: {self.base_url}")
                print(f"[DEBUG] Creating Anthropic client with kwargs: {client_kwargs}")
                self._client = anthropic.Anthropic(**client_kwargs)
            except ImportError:
                self._anthropic_available = False
                self._client = None
        return self._client

    def chat(self, messages, temperature=0.3, max_tokens=None, timeout=300):
        """发送对话请求"""
        try:
            # 检查 anthropic 是否可用
            if self._anthropic_available is False:
                return {'success': False, 'error': 'anthropic package not installed. Run: pip install anthropic'}

            # 将 OpenAI 格式转换为 Anthropic 格式
            # Anthropic 使用 system 和 user 消息
            system_msg = None
            user_msgs = []

            for msg in messages:
                if msg['role'] == 'system':
                    system_msg = msg['content']
                else:
                    user_msgs.append(msg['content'])

            user_content = '\n'.join(user_msgs)

            # 构建消息列表 - MiniMax可能不支持system消息，合并到user消息中
            if system_msg:
                combined_content = f"{system_msg}\n\n{user_content}"
            else:
                combined_content = user_content

            kwargs = {
                'model': self.model,
                'messages': [{"role": "user", "content": combined_content}],
                'max_tokens': max_tokens if max_tokens else 4096,
                'timeout': timeout
            }

            print(f"[DEBUG] API Request: model={self.model}, max_tokens={kwargs['max_tokens']}, timeout={timeout}")

            response = self.client.messages.create(**kwargs)

            # 正确处理响应（可能包含 ThinkingBlock）
            for block in response.content:
                if hasattr(block, 'text'):
                    response_text = block.text
                    break
            else:
                response_text = ""
            return {
                'success': True,
                'content': response_text,
                'model': self.model
            }
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return {'success': False, 'error': str(e)}

    def json_chat(self, messages, temperature=0.1, timeout=180):
        """发送 JSON 模式对话请求"""
        try:
            # 检查 anthropic 是否可用
            if self._anthropic_available is False:
                return {'success': False, 'error': 'anthropic package not installed. Run: pip install anthropic'}

            system_msg = None
            user_msgs = []

            for msg in messages:
                if msg['role'] == 'system':
                    system_msg = msg['content']
                else:
                    user_msgs.append(msg['content'])

            user_content = f"{chr(10).join(user_msgs)}\n\n请以JSON格式回复。"

            kwargs = {
                'model': self.model,
                'messages': [{"role": "user", "content": user_content}],
                'temperature': temperature,
                'timeout': timeout,
                'max_tokens': 4096  # Anthropic requires max_tokens
            }

            if system_msg:
                kwargs['system'] = system_msg

            response = self.client.messages.create(**kwargs)
            # 正确处理响应（可能包含 ThinkingBlock）
            response_text = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    response_text = block.text
                    break
            return {
                'success': True,
                'content': response_text,
                'model': self.model
            }
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return {'success': False, 'error': str(e)}


# 便捷函数
def get_openai_client():
    """获取 OpenAI 兼容客户端"""
    config = load_ai_config()
    api_base = config.get('api_base', '')
    api_key = config.get('api_key', '')
    model = config.get('chat_model', '')
    return OpenAIClient(api_key=api_key, base_url=api_base, model=model)


def get_anthropic_client():
    """获取 Anthropic 客户端"""
    config = load_ai_config()
    api_key = config.get('api_key', '')
    model = config.get('chat_model', '')
    base_url = config.get('api_base', '')
    return AnthropicClient(api_key=api_key, model=model, base_url=base_url)


def get_current_provider() -> str:
    """获取当前配置的 API 提供商"""
    config = load_ai_config()
    return config.get('api_provider', 'openai')


def get_chat_model() -> str:
    """获取当前配置的模型名称"""
    config = load_ai_config()
    provider = config.get('api_provider', 'openai')

    if provider == 'anthropic':
        return config.get('chat_model', 'claude-sonnet-4-20250514')
    else:
        return config.get('chat_model', 'deepseek-chat')


def is_configured() -> bool:
    """检查是否已配置 AI"""
    config = load_ai_config()
    if config.get('embedding_model', '').lower().find('(本地)') != -1:
        return True
    return bool(config.get('api_key'))
