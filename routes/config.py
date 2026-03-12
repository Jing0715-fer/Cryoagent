"""
Configuration API Routes
"""
import os
import json
from flask import jsonify, request, Blueprint, render_template
import logging
logger = logging.getLogger(__name__)

bp = Blueprint('config', __name__)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ai_config.json')

# API Provider configurations
API_PROVIDERS = {
    'openai': {
        'name': 'OpenAI / DeepSeek / 通义千问 (OpenAI兼容)',
        'default_base': 'https://api.deepseek.com',
        'default_model': 'deepseek-chat',
        'api_format': 'openai'
    },
    'anthropic': {
        'name': 'Anthropic Claude / MiniMax (Anthropic兼容)',
        'default_base': 'https://api.anthropic.com',
        'default_model': 'claude-sonnet-4-20250514',
        'api_format': 'anthropic'
    }
}


def load_config():
    """Load AI configuration from file"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")
    return {}


def save_config(config):
    """Save AI configuration to file"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False


@bp.route('/api/config/ai', methods=['GET'])
def get_ai_config():
    """API endpoint to get AI configuration"""
    config = load_config()

    # Get models list and active model
    models = config.get('models', [])
    active_model_id = config.get('active_model_id', '')

    # Find active model details
    active_model = None
    for m in models:
        if m.get('id') == active_model_id:
            active_model = m
            break

    # If no active model but have models, use first one
    if not active_model and models:
        active_model = models[0]
        active_model_id = active_model.get('id', '')

    # Return only relevant AI config fields
    return jsonify({
        'chat_model': active_model.get('chat_model', '') if active_model else '',
        'api_base': active_model.get('api_base', '') if active_model else '',
        'api_key': active_model.get('api_key', '') if active_model else '',
        'api_provider': config.get('api_provider', 'openai'),
        'models': models,
        'active_model_id': active_model_id,
        'active_model': active_model
    })


@bp.route('/api/config/models', methods=['POST'])
def save_models_config():
    """Save models configuration"""
    try:
        data = request.json or {}

        models = data.get('models', [])
        active_model_id = data.get('active_model_id', '')

        # Load existing config to preserve other fields
        config = load_config()

        # Update models and active_model_id while preserving other config
        config['models'] = models
        config['active_model_id'] = active_model_id
        # Also update the active model's api_base and api_key in the main config
        # for backwards compatibility
        for model in models:
            if model.get('id') == active_model_id:
                config['api_base'] = model.get('api_base', '')
                config['api_key'] = model.get('api_key', '')
                config['chat_model'] = model.get('chat_model', '')
                break

        if save_config(config):
            logger.info("Models configuration saved successfully")
            return jsonify({'success': True, 'message': '模型配置已保存'})
        else:
            return jsonify({'success': False, 'message': '保存配置失败'})

    except Exception as e:
        logger.error(f"Failed to save models config: {e}")
        return jsonify({'success': False, 'message': str(e)})


@bp.route('/api/config/', methods=['GET'])
def get_config_api():
    """API endpoint to get full configuration"""
    config = load_config()
    return jsonify({'config': config})


@bp.route('/config', methods=['GET', 'POST'])
def config_page():
    """Render configuration page"""
    config = load_config()

    # Handle form submission (POST)
    if request.method == 'POST':
        # Get form data
        api_provider = request.form.get('api_provider', 'openai').strip()
        api_base = request.form.get('api_base', '').strip()
        api_key = request.form.get('api_key', '').strip()
        chat_model = request.form.get('chat_model', '').strip()
        embedding_model = request.form.get('embedding_model', '').strip()

        # Vector database config
        vector_engine = request.form.get('vector_engine', 'lancedb').strip()
        search_type = request.form.get('search_type', 'vector').strip()
        reranker_enabled = request.form.get('reranker_enabled') == 'on'

        # Embedding model config
        embedding_provider = request.form.get('embedding_provider', 'local').strip()
        embedding_api_key = request.form.get('embedding_api_key', '').strip()
        embedding_api_base = request.form.get('embedding_api_base', '').strip()

        # Get default values based on provider
        provider_defaults = API_PROVIDERS.get(api_provider, API_PROVIDERS['openai'])

        # Validate - only require API settings if using remote model
        is_local_embedding = '(本地)' in embedding_model.lower() or embedding_model.startswith('sentence-transformers')

        if not is_local_embedding:
            if not api_base:
                config = load_config()
                from routes.feishu import load_feishu_config
                feishu_config = load_feishu_config()
                return render_template('config.html',
                                       api_provider=config.get('api_provider', 'openai'),
                                       api_base=config.get('api_base', ''),
                                       api_key=config.get('api_key', ''),
                                       chat_model=config.get('chat_model', ''),
                                       embedding_model=embedding_model,
                                       embedding_provider=embedding_provider,
                                       embedding_api_key=embedding_api_key,
                                       embedding_api_base=embedding_api_base,
                                       vector_engine=vector_engine,
                                       search_type=search_type,
                                       reranker_enabled=reranker_enabled,
                                       jina_api_key=config.get('jina_api_key', ''),
                                       providers=API_PROVIDERS,
                                       feishu_config=feishu_config,
                                       status={'error': '请输入 API Base URL'},
                                       error='请输入 API Base URL')
            if not api_key:
                saved_config = load_config()
                from routes.feishu import load_feishu_config
                feishu_config = load_feishu_config()
                return render_template('config.html',
                                       api_provider=api_provider,
                                       api_base=api_base or saved_config.get('api_base', ''),
                                       api_key='',
                                       chat_model=chat_model,
                                       embedding_model=embedding_model,
                                       embedding_provider=embedding_provider,
                                       embedding_api_key=embedding_api_key,
                                       embedding_api_base=embedding_api_base,
                                       vector_engine=vector_engine,
                                       search_type=search_type,
                                       reranker_enabled=reranker_enabled,
                                       jina_api_key=saved_config.get('jina_api_key', ''),
                                       providers=API_PROVIDERS,
                                       feishu_config=feishu_config,
                                       status={'error': '请输入 API Key'},
                                       error='请输入 API Key')

        # Save config
        config = {
            'api_provider': api_provider,
            'api_base': api_base or provider_defaults['default_base'],
            'api_key': api_key,
            'chat_model': chat_model or provider_defaults['default_model'],
            'embedding_model': embedding_model,
            'embedding_provider': embedding_provider,
            'embedding_api_key': embedding_api_key,
            'embedding_api_base': embedding_api_base,
            'vector_engine': vector_engine,
            'search_type': search_type,
            'reranker_enabled': reranker_enabled
        }
        if save_config(config):
            logger.info("AI configuration saved successfully")
            # Apply vector_engine to current app config immediately
            from flask import current_app
            if current_app:
                current_app.config['VECTOR_ENGINE'] = vector_engine
                logger.info(f"Applied VECTOR_ENGINE={vector_engine} to app.config")

        # Reload config for display
        config = load_config()

    # Get values from config or defaults
    api_provider = config.get('api_provider', 'openai')
    api_base = config.get('api_base', API_PROVIDERS.get(api_provider, API_PROVIDERS['openai'])['default_base'])
    api_key = config.get('api_key', '')
    chat_model = config.get('chat_model', '')
    embedding_model = config.get('embedding_model', 'all-MiniLM-L6-v2')
    embedding_provider = config.get('embedding_provider', 'local')
    embedding_api_key = config.get('embedding_api_key', '')
    embedding_api_base = config.get('embedding_api_base', '')
    vector_engine = config.get('vector_engine', 'lancedb')
    search_type = config.get('search_type', 'vector')
    reranker_enabled = config.get('reranker_enabled', False)
    jina_api_key = config.get('jina_api_key', '')

    # Load feishu config
    from routes.feishu import load_feishu_config
    feishu_config = load_feishu_config()

    # Check if API key is set
    api_key_set = bool(api_key)
    api_key_display = '已设置' if api_key_set else '未设置'

    status = {
        'api_provider': api_provider,
        'api_base': api_base or '未配置',
        'api_key': api_key_set,
        'api_key_display': api_key_display,
        'chat_model': chat_model or '未配置',
        'embedding_model': embedding_model or '未配置',
        'vector_engine': vector_engine or '未配置'
    }

    # Get active model for status bar
    models = config.get('models', [])
    active_model_id = config.get('active_model_id', '')
    active_model = None
    for m in models:
        if m.get('id') == active_model_id:
            active_model = m
            break

    return render_template('config.html',
                           api_provider=api_provider,
                           api_base=api_base,
                           api_key=api_key,
                           chat_model=chat_model,
                           embedding_model=embedding_model,
                           embedding_provider=embedding_provider,
                           embedding_api_key=embedding_api_key,
                           embedding_api_base=embedding_api_base,
                           vector_engine=vector_engine,
                           search_type=search_type,
                           reranker_enabled=reranker_enabled,
                           jina_api_key=jina_api_key,
                           providers=API_PROVIDERS,
                           status=status,
                           active_model=active_model,
                           feishu_config=feishu_config)


@bp.route('/api/config/save', methods=['POST'])
def save_ai_config():
    """Save AI configuration"""
    try:
        # Support both JSON and form data
        if request.is_json:
            data = request.json or {}
        else:
            data = request.form or {}

        # Load existing config to preserve models and active_model_id
        existing_config = load_config()

        api_provider = data.get('api_provider', 'openai').strip()
        provider_defaults = API_PROVIDERS.get(api_provider, API_PROVIDERS['openai'])

        # Vector config
        vector_engine = data.get('vector_engine', 'lancedb').strip()
        search_type = data.get('search_type', 'vector').strip()
        reranker_enabled = data.get('reranker_enabled', False)

        # Validate vector_engine value
        if vector_engine not in ['lancedb']:
            return jsonify({'success': False, 'message': f'Invalid vector_engine: {vector_engine}. Must be "lancedb"'})

        config = {
            'api_provider': api_provider,
            'api_base': data.get('api_base', '').strip() or provider_defaults['default_base'],
            'api_key': data.get('api_key', '').strip(),
            'chat_model': data.get('chat_model', '').strip() or provider_defaults['default_model'],
            'embedding_model': data.get('embedding_model', '').strip(),
            'vector_engine': vector_engine,
            'search_type': search_type,
            'reranker_enabled': reranker_enabled,
            'jina_api_key': data.get('jina_api_key', '').strip(),
            # Preserve models configuration
            'models': existing_config.get('models', []),
            'active_model_id': existing_config.get('active_model_id', '')
        }

        # Check if using local embedding model
        is_local_embedding = '(本地)' in config['embedding_model'].lower() or \
                             config['embedding_model'].startswith('sentence-transformers')

        # Only require API settings if using remote models
        if not is_local_embedding:
            if not config['api_key']:
                return jsonify({'success': False, 'message': '请输入 API Key'})

        if save_config(config):
            logger.info("AI configuration saved successfully")

            # Apply vector_engine to current app config immediately
            from flask import current_app
            if current_app:
                current_app.config['VECTOR_ENGINE'] = vector_engine
                logger.info(f"Applied VECTOR_ENGINE={vector_engine} to app.config")

            msg = '本地Embedding模型配置已保存' if is_local_embedding else '配置已保存'
            return jsonify({'success': True, 'message': msg})
        else:
            return jsonify({'success': False, 'message': '保存配置失败'})

    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return jsonify({'success': False, 'message': str(e)})


@bp.route('/api/config/test-ai', methods=['POST'])
def test_ai_connection():
    """Test AI API connection"""
    import time
    start_time = time.time()

    try:
        data = request.json or {}
        api_provider = data.get('api_provider', 'openai').strip()
        api_base = data.get('api_base', '').strip()
        api_key = data.get('api_key', '').strip()
        chat_model = data.get('chat_model', '').strip()

        provider_defaults = API_PROVIDERS.get(api_provider, API_PROVIDERS['openai'])

        if not api_key:
            return jsonify({'success': False, 'message': '请输入 API Key'})

        latency = int((time.time() - start_time) * 1000)

        # Test based on provider type
        if api_provider == 'anthropic':
            # Test Anthropic connection (支持 MiniMax)
            try:
                import anthropic
                import os

                # MiniMax 需要设置环境变量并传递base_url
                if 'minimaxi' in api_base.lower():
                    os.environ['ANTHROPIC_BASE_URL'] = api_base
                    os.environ['ANTHROPIC_API_KEY'] = api_key

                # 创建客户端（如果提供了api_base则使用）
                if api_base:
                    client = anthropic.Anthropic(api_key=api_key, base_url=api_base, timeout=10.0)
                else:
                    client = anthropic.Anthropic(api_key=api_key, timeout=10.0)

                response = client.messages.create(
                    model=chat_model or provider_defaults['default_model'],
                    max_tokens=20,
                    messages=[
                        {"role": "user", "content": "Say 'Connection successful' in one sentence."}
                    ]
                )

                latency = int((time.time() - start_time) * 1000)

                # 正确处理响应（可能包含 ThinkingBlock）
                response_text = ""
                for block in response.content:
                    if hasattr(block, 'text'):
                        response_text = block.text
                        break

                logger.info(f"AI connection test successful (Anthropic/MiniMax): {chat_model}")
                return jsonify({
                    'success': True,
                    'message': f'Anthropic {chat_model} 连接成功',
                    'latency': latency,
                    'response': response_text
                })

            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Anthropic connection test failed: {error_msg}")

                if '401' in error_msg or 'authentication' in error_msg.lower():
                    return jsonify({'success': False, 'message': '认证失败，请检查 API Key', 'error': error_msg})
                elif '403' in error_msg or 'forbidden' in error_msg.lower():
                    return jsonify({'success': False, 'message': '访问被拒绝，请检查 API Key 权限或账户额度', 'error': error_msg})
                elif 'connection' in error_msg.lower():
                    return jsonify({'success': False, 'message': '无法连接到 Anthropic API', 'error': error_msg})
                else:
                    return jsonify({'success': False, 'message': f'连接失败: {error_msg[:100]}', 'error': error_msg})
        else:
            # Test OpenAI-compatible connection
            try:
                from openai import OpenAI

                client = OpenAI(api_key=api_key, base_url=api_base, timeout=10.0)

                response = client.chat.completions.create(
                    model=chat_model or provider_defaults['default_model'],
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": "Say 'Connection successful' in one sentence."}
                    ],
                    max_tokens=20
                )

                latency = int((time.time() - start_time) * 1000)

                logger.info(f"AI connection test successful: {chat_model}")
                return jsonify({
                    'success': True,
                    'message': f'模型 {chat_model} 连接成功',
                    'latency': latency,
                    'response': response.choices[0].message.content
                })

            except Exception as e:
                error_msg = str(e)
                logger.warning(f"AI connection test failed: {error_msg}")

                # Provide helpful error messages
                if '401' in error_msg or 'authentication' in error_msg.lower():
                    return jsonify({'success': False, 'message': '认证失败，请检查 API Key', 'error': error_msg})
                elif '404' in error_msg or 'not found' in error_msg.lower():
                    return jsonify({'success': False, 'message': 'API 端点不存在，请检查 API Base URL', 'error': error_msg})
                elif 'connection' in error_msg.lower():
                    return jsonify({'success': False, 'message': '无法连接到 API 服务器', 'error': error_msg})
                else:
                    return jsonify({'success': False, 'message': f'连接失败: {error_msg[:100]}', 'error': error_msg})

    except Exception as e:
        logger.error(f"AI test error: {e}")
        return jsonify({'success': False, 'message': str(e)})
