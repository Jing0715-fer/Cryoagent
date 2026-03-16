/* ============================================
   CryoAgent Pro - Q&A Page
   ============================================ */

// Global state
let chatHistory = [];
let isProcessing = false;
let currentSessionId = null;  // 当前会话ID
let currentClarification = null;  // 当前待澄清的问题

// Initialize QA page
function initPage() {
    // 从 localStorage 恢复 session_id
    currentSessionId = localStorage.getItem('currentSessionId') || null;
    console.log('恢复会话 ID:', currentSessionId || '新会话');

    // 添加 new-session 类（简洁欢迎界面）
    const qaPage = document.querySelector('.qa-page');
    if (qaPage) {
        qaPage.classList.add('new-session');
    }

    // RAG 和 Agent 模式已固定开启，无需初始化按钮

    const chatInput = document.getElementById('chat-input');
    if (chatInput) {
        // Auto-resize textarea
        chatInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 120) + 'px';
        });

        // Handle Enter key - use agent mode by default
        chatInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (agentMode) {
                    sendAgentMessage();
                } else {
                    sendChatMessage();
                }
            }
        });
    }

    // Load chat history from server
    loadChatHistoryFromServer();

    // 为已存在的消息添加复制按钮
    setTimeout(() => {
        const container = document.getElementById('chat-messages');
        if (container) {
            addCopyButtons(container);
        }
    }, 500);
}

// Start a new session - 清除当前会话，开始新会话
function startNewSession() {
    currentSessionId = null;
    localStorage.removeItem('currentSessionId');

    // 清除聊天界面，显示欢迎消息（新的欢迎界面）
    const container = document.getElementById('chat-messages');
    if (container) {
        container.innerHTML = `
            <div class="welcome-screen" id="welcome-screen">
                <div class="welcome-icon">
                    <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 2L2 7l10 5 10-5-10-5z"></path>
                        <path d="M2 17l10 5 10-5"></path>
                        <path d="M2 12l10 5 10-5"></path>
                    </svg>
                </div>
                <h2 class="welcome-title">今天想聊些什么？</h2>
                <p class="welcome-subtitle">基于 AI 的 Cryo-EM 文献智能问答系统，我可以帮助你回答问题、查找文献。</p>
                <div class="welcome-prompts">
                    <button class="welcome-prompt" onclick="askQuestion('Vγ9Vδ2 TCR 的序列是什么？')">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"></circle>
                            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                            <line x1="12" y1="17" x2="12.01" y2="17"></line>
                        </svg>
                        Vγ9Vδ2 TCR 的序列
                    </button>
                    <button class="welcome-prompt" onclick="askQuestion('CRYO-EM 结构解析的最佳实践')">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"></circle>
                            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                            <line x1="12" y1="17" x2="12.01" y2="17"></line>
                        </svg>
                        CRYO-EM 最佳实践
                    </button>
                    <button class="welcome-prompt" onclick="askQuestion('EMDB 数据库的使用方法')">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"></circle>
                            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                            <line x1="12" y1="17" x2="12.01" y2="17"></line>
                        </svg>
                        EMDB 使用方法
                    </button>
                    <button class="welcome-prompt" onclick="askQuestion('如何提高冷冻电镜的分辨率？')">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"></circle>
                            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                            <line x1="12" y1="17" x2="12.01" y2="17"></line>
                        </svg>
                        提高分辨率技巧
                    </button>
                </div>
            </div>
        `;
    }

    // 清除搜索结果
    const searchPanel = document.getElementById('search-results');
    if (searchPanel) {
        searchPanel.innerHTML = '<div class="empty-state">输入问题后显示相关文献</div>';
    }

    // 聚焦输入框
    const chatInput = document.getElementById('chat-input');
    if (chatInput) {
        chatInput.value = '';
        chatInput.focus();
    }

    // 关闭历史面板
    const panel = document.getElementById('chat-history-panel');
    const overlay = document.getElementById('chat-history-overlay');
    if (panel) panel.classList.remove('open');
    if (overlay) overlay.classList.remove('open');
}

// Load chat history from server
async function loadChatHistoryFromServer() {
    console.log('[QA] 正在加载聊天历史...');
    try {
        // 构建 URL，如果有 session_id 则发送
        let url = '/api/qa/history?limit=50';
        if (currentSessionId) {
            url += `&session_id=${encodeURIComponent(currentSessionId)}`;
        }
        console.log('[QA] 请求URL:', url);

        const response = await fetch(url);
        console.log('[QA] 历史API响应状态:', response.status);
        const data = await response.json();
        console.log('[QA] 历史数据:', data);
        if (data.success) {
            chatHistory = data.items || [];
            console.log('[QA] 加载到', chatHistory.length, '条历史记录');
            // 同时渲染到侧边栏和抽屉面板
            renderChatHistory(chatHistory, 'chat-history-list');
            renderChatHistory(chatHistory, 'chat-history-list-drawer');
        } else {
            console.warn('[QA] API返回失败:', data.error);
        }
    } catch (e) {
        console.error('[QA] 加载聊天历史失败:', e);
        // Fallback to localStorage
        try {
            const saved = localStorage.getItem('cryoagent_qa_history');
            chatHistory = saved ? JSON.parse(saved) : [];
            renderChatHistory(chatHistory, 'chat-history-list');
            renderChatHistory(chatHistory, 'chat-history-list-drawer');
        } catch (e2) {
            chatHistory = [];
        }
    }
}

// Render chat history grouped by date then by session
function renderChatHistory(history, containerId = 'chat-history-list') {
    const container = document.getElementById(containerId);
    if (!container) {
        console.warn('[QA] 未找到容器:', containerId);
        return;
    }

    console.log('[QA] 渲染历史到', containerId, ', 记录数:', history.length);

    if (history.length === 0) {
        container.innerHTML = '<div class="history-empty"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4" style="margin-bottom:12px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg><p>暂无历史记录</p></div>';
        return;
    }

    const today = new Date().toISOString().split('T')[0];
    const yesterday = new Date(Date.now() - 86400000).toISOString().split('T')[0];

    // 先按session分组，收集每个session的信息
    const sessionGroups = {};
    history.forEach(entry => {
        const sessionId = entry.session_id || `no-session-${entry.id}`;
        const date = entry.created_at ? entry.created_at.split('T')[0] : '';
        const rawPreview = entry.preview || entry.question || '';
        const preview = parseJsonTitle(rawPreview).substring(0, 50) || '未知问题';
        const timestamp = entry.timestamp || entry.created_at;

        if (!sessionGroups[sessionId]) {
            sessionGroups[sessionId] = {
                date: date,
                items: [],
                timestamp: timestamp,
                preview: preview
            };
        }
        sessionGroups[sessionId].itemCount = (sessionGroups[sessionId].itemCount || 0) + 1;
        sessionGroups[sessionId].items.push(entry);
    });

    // 再按日期分组
    const dateGroups = {};
    Object.keys(sessionGroups).forEach(sessionId => {
        const group = sessionGroups[sessionId];
        const dateLabel = group.date === today ? '今天' :
                         group.date === yesterday ? '昨天' : group.date;
        if (!dateGroups[dateLabel]) {
            dateGroups[dateLabel] = {
                sessions: [],
                latestTimestamp: group.timestamp
            };
        }
        dateGroups[dateLabel].sessions.push({
            sessionId: sessionId,
            ...group
        });
    });

    // 按日期排序（今天在前）
    const sortedDates = Object.keys(dateGroups).sort((a, b) => {
        if (a === '今天') return -1;
        if (b === '今天') return 1;
        if (a === '昨天') return -1;
        if (b === '昨天') return 1;
        return b.localeCompare(a);
    });

    // 渲染
    let html = '';
    sortedDates.forEach(dateLabel => {
        const dateGroup = dateGroups[dateLabel];
        // 按时间排序每个日期下的session（最新的在前）
        dateGroup.sessions.sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));

        html += `<div class="history-group"><div class="history-date">${dateLabel}</div>`;
        html += '<div class="history-items">';

        dateGroup.sessions.forEach(sess => {
            const itemCount = sess.itemCount || sess.items.length;
            const firstQuestion = sess.preview || '会话';

            html += `
                <div class="history-item" onclick="loadHistorySession('${sess.sessionId}')">
                    <div class="history-left">
                        <div class="history-question">${escapeHtml(firstQuestion)}</div>
                        <div class="history-time">${formatTime(sess.timestamp)} · ${itemCount}轮对话</div>
                    </div>
                </div>
            `;
        });

        html += '</div></div>';
    });

    container.innerHTML = html;
}

// Load entire session history - 加载整个会话的所有对话并直接恢复
async function loadHistorySession(sessionId) {
    try {
        // 获取该session的所有历史记录
        const response = await fetch(`/api/qa/history?limit=100`);
        const data = await response.json();
        if (!response.ok || data.error) {
            showToast(data.error || '获取对话失败', 'error');
            return;
        }

        // 过滤出同session的记录（处理session_id为null的情况）
        const sessionItems = data.items.filter(item => {
            if (sessionId.startsWith('no-session-')) {
                // 没有session_id的记录
                return item.session_id === null;
            }
            return item.session_id === sessionId;
        });

        // 按时间正序排列（旧的在前）
        sessionItems.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));

        // 设置当前 session_id
        if (!sessionId.startsWith('no-session-')) {
            currentSessionId = sessionId;
            localStorage.setItem('currentSessionId', currentSessionId);
        }

        // 进入对话模式：隐藏欢迎消息和建议问题
        enterConversationMode();

        // 清空聊天容器并渲染历史消息
        const container = document.getElementById('chat-messages');
        if (!container) return;

        container.innerHTML = '';

        // 渲染所有历史消息
        sessionItems.forEach(entry => {
            // 用户消息
            addChatMessage('user', entry.question || '', []);

            // AI 回答 - 尝试从 result_json 中提取来源
            let sources = entry.sources || [];

            // 如果有 result_json，尝试解析出完整的来源信息
            if (entry.result_json) {
                try {
                    const result = JSON.parse(entry.result_json);
                    // 优先使用后端保存的 sources 字段（包含完整信息）
                    if (result.sources && result.sources.length > 0) {
                        sources = result.sources;
                    } else {
                        // 兼容旧数据：从 tool_results 提取来源
                        const toolResults = result.tool_results || [];
                        sources = [];
                        for (const tr of toolResults) {
                            if (tr.tool_name === 'search_literature' && tr.result) {
                                const results = tr.result.results || [];
                                for (const lit of results) {
                                    sources.push({
                                        type: 'literature',
                                        id: String(lit.id || ''),
                                        title: (lit.title || '').substring(0, 100),
                                        authors: lit.authors || '',
                                        year: lit.year || '',
                                        journal: lit.journal || '',
                                        doi: lit.doi || '',
                                        content: lit.content || lit.abstract || ''
                                    });
                                }
                            }
                            if (tr.tool_name === 'search_structures' && tr.result) {
                                const results = tr.result.results || [];
                                for (const struct of results) {
                                    sources.push({
                                        type: 'structure',
                                        id: struct.pdb_id || '',
                                        title: (struct.title || '').substring(0, 100)
                                    });
                                }
                            }
                        }
                    }
                } catch (e) {
                    console.warn('解析 result_json 失败:', e);
                }
            }

            addChatMessage('assistant', entry.answer || '', sources);
        });

        // 更新搜索结果面板（显示最后一条消息的来源）
        if (sessionItems.length > 0) {
            const lastItem = sessionItems[sessionItems.length - 1];
            let lastSources = lastItem.sources || [];

            // 同样尝试从 result_json 解析最后一条的来源
            if (lastItem.result_json) {
                try {
                    const result = JSON.parse(lastItem.result_json);
                    // 优先使用后端保存的 sources 字段
                    if (result.sources && result.sources.length > 0) {
                        lastSources = result.sources;
                    } else {
                        // 兼容旧数据
                        const toolResults = result.tool_results || [];
                        lastSources = [];
                        for (const tr of toolResults) {
                            if (tr.tool_name === 'search_literature' && tr.result) {
                                const results = tr.result.results || [];
                                for (const lit of results) {
                                    lastSources.push({
                                        type: 'literature',
                                        id: String(lit.id || ''),
                                        title: (lit.title || '').substring(0, 100),
                                        authors: lit.authors || '',
                                        year: lit.year || '',
                                        journal: lit.journal || '',
                                        doi: lit.doi || '',
                                        content: lit.content || lit.abstract || ''
                                    });
                                }
                            }
                            if (tr.tool_name === 'search_structures' && tr.result) {
                                const results = tr.result.results || [];
                                for (const struct of results) {
                                    lastSources.push({
                                        type: 'structure',
                                        id: struct.pdb_id || '',
                                        title: (struct.title || '').substring(0, 100)
                                    });
                                }
                            }
                        }
                    }
                } catch (e) {
                    console.warn('解析 result_json 失败:', e);
                }
            }

            updateSearchResults(lastSources);
        }

        // 关闭历史面板（如果在移动端）
        const panel = document.getElementById('chat-history-panel');
        const overlay = document.getElementById('chat-history-overlay');
        if (panel && window.innerWidth < 768) {
            panel.classList.remove('open');
            overlay.classList.remove('open');
        }

        // 聚焦输入框
        const chatInput = document.getElementById('chat-input');
        if (chatInput) {
            chatInput.focus();
        }

        showToast('已恢复对话', 'success');
    } catch (e) {
        console.error('获取会话详情失败:', e);
        showToast('获取会话详情失败', 'error');
    }
}

// Enter conversation mode - 隐藏欢迎消息和建议问题，显示对话
function enterConversationMode() {
    const container = document.getElementById('chat-messages');
    if (container) {
        // 移除欢迎消息元素（兼容新旧多种格式）
        const welcomeMsg = container.querySelector('.welcome-message');
        if (welcomeMsg) {
            welcomeMsg.remove();
        }
        // 移除简化欢迎消息
        const welcomeSimple = container.querySelector('.welcome-simple');
        if (welcomeSimple) {
            welcomeSimple.remove();
        }
        // 移除新的欢迎界面
        const welcomeScreen = container.querySelector('.welcome-screen');
        if (welcomeScreen) {
            welcomeScreen.style.display = 'none';
        }
    }

    // 移除 qa-page 的 new-session 类（如果之前有的话）
    const qaPage = document.querySelector('.qa-page');
    if (qaPage) {
        qaPage.classList.remove('new-session');
    }
}

// Load a specific history item - 从服务器获取并显示完整对话内容
async function loadHistoryItem(id) {
    try {
        const response = await fetch(`/api/qa/history/${id}`);
        const data = await response.json();
        if (!response.ok || data.error) {
            showToast(data.error || '获取对话详情失败', 'error');
            return;
        }
        const entry = data.data;

        // 创建弹窗显示完整对话
        const modal = document.createElement('div');
        modal.className = 'modal active';
        modal.onclick = function(e) {
            if (e.target === modal) modal.remove();
        };

        const date = new Date(entry.created_at);
        const dateStr = date.toLocaleString('zh-CN');

        modal.innerHTML = `
            <div class="modal-content" style="max-width: 1050px;">
                <div class="modal-header">
                    <h2>历史对话</h2>
                    <button class="close-btn" onclick="this.closest('.modal').remove()">&times;</button>
                </div>
                <div class="modal-body" style="font-size: 14px;">
                    <style>
                        .modal-body table { border-collapse: collapse; width: 100%; margin: 10px 0; }
                        .modal-body th, .modal-body td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
                        .modal-body th { background-color: #f5f5f5; font-weight: 600; }
                        .modal-body tr:nth-child(even) { background-color: #fafafa; }
                    </style>
                    <div class="history-meta" style="color: #666; font-size: 12px; margin-bottom: 15px;">
                        ${dateStr}
                    </div>
                    ${entry.question_type ? `<div style="margin-bottom: 10px; color: #666; font-size: 12px;">问题类型: ${entry.question_type}</div>` : ''}
                    <div class="history-detail">
                        <div class="history-question-box" style="background: #f5f5f5; padding: 15px; border-radius: 8px; margin-bottom: 15px;">
                            <div style="font-weight: 600; margin-bottom: 8px; color: #333;">
                                <span style="color: #1976D2;">&#128100;</span> 问题
                            </div>
                            <div style="line-height: 1.6;">${formatMessage(entry.question)}</div>
                        </div>
                        <div class="history-answer-box" style="padding: 15px;">
                            <div style="font-weight: 600; margin-bottom: 8px; color: #333;">
                                <span style="color: #E65100;">&#129302;</span> 回答
                            </div>
                            <div style="line-height: 1.6;" class="markdown-body">${formatMessage(entry.answer || '（无回答）')}</div>
                        </div>
                    </div>
                    ${entry.sources && entry.sources.length > 0 ? `
                        <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #eee;">
                            <div style="font-weight: 600; margin-bottom: 10px; color: #333;">参考来源</div>
                            <ul style="margin: 0; padding-left: 20px;">
                                ${entry.sources.map(s => `
                                    <li style="margin-bottom: 5px;">
                                        <a href="/literature/${s.id}" target="_blank" style="color: #1976D2;">
                                            ${escapeHtml(truncateText(s.title || s.id, 60))}
                                        </a>
                                    </li>
                                `).join('')}
                            </ul>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;

        document.body.appendChild(modal);
    } catch (e) {
        console.error('获取对话详情失败:', e);
        showToast('获取对话详情失败', 'error');
    }
}

// Format time
function formatTime(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

// Follow-up question - 追问
function followupQuestion(question, sessionId) {
    const input = document.getElementById('chat-input');
    if (!input) return;

    // 设置session_id
    if (sessionId) {
        currentSessionId = sessionId;
        localStorage.setItem('currentSessionId', currentSessionId);
        console.log('设置Session ID:', currentSessionId);
    }

    // 将问题放到输入框
    input.value = question;
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    input.focus();

    // 显示提示
    showToast('已复制问题到输入框，继续提问', 'info');
}

// Clear history - 从服务器删除所有历史
async function clearChatHistory() {
    if (!confirm('确定要清除所有聊天历史吗？此操作不可恢复。')) return;

    try {
        const response = await fetch('/api/qa/history?limit=1000');
        const data = await response.json();
        if (data.items && data.items.length > 0) {
            // Delete each history item
            for (const item of data.items) {
                await fetch(`/api/qa/history/${item.id}`, { method: 'DELETE' });
            }
        }
        // Also clear localStorage
        localStorage.removeItem('cryoagent_qa_history');
        loadChatHistoryFromServer();
        showToast('聊天历史已清除', 'success');
    } catch (e) {
        console.error('清除历史失败:', e);
        showToast('清除历史失败', 'error');
    }
}

// Add message to chat
function addChatMessage(role, content, sources = [], imageUrl = null) {
    const container = document.getElementById('chat-messages');
    console.log('[QA.js] addChatMessage called:', { role, content: content?.substring(0, 50), sources: sources?.length, imageUrl });

    if (!container) {
        console.error('[QA.js] chat-messages container not found!');
        return;
    }

    // Null safety checks
    if (!content) content = '';
    if (!sources || !Array.isArray(sources)) sources = [];
    if (!imageUrl) imageUrl = null;

    // 过滤无效 chunks - 过滤掉内容太短或包含版权关键词的 chunks
    const originalSourcesCount = sources.length;
    sources = sources.filter(s => {
        // 非 literature 类型保留
        if (s.type !== 'literature') return true;
        const content = s.content || '';
        // 过滤版权关键词
        const invalidKeywords = ['creative commons', 'copyright', 'license', 'author(s)', 'original author', 'permitting parties', 'permitted under', 'open access'];
        const hasInvalidKeyword = invalidKeywords.some(kw => content.toLowerCase().includes(kw));
        // 过滤内容太短的
        return content.length > 100 && !hasInvalidKeyword;
    });
    console.log('[QA.js] 过滤 sources:', originalSourcesCount, '->', sources.length);

    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    // User gets no avatar (aligned to right), AI gets the sparkles icon
    const avatar = role === 'user' ? '' : '<div class="message-avatar"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"></path><path d="M2 17l10 5 10-5"></path><path d="M2 12l10 5 10-5"></path></svg></div>';

    let sourcesHtml = '';
    if (sources && sources.length > 0) {
        // Group sources by literature for better display
        // 去重：按文献 ID 去重，保留第一个出现的
        const seenLiteratureIds = new Set();
        const literatureSources = sources.filter(s => {
            if (s.type !== 'literature') return false;
            // 从 ID 中提取文献号 (如 literature_5_full_chunk_104 -> literature_5)
            const idStr = String(s.id);
            const litMatch = idStr.match(/literature_(\d+)/);
            const litId = litMatch ? `literature_${litMatch[1]}` : idStr;
            if (seenLiteratureIds.has(litId)) {
                return false;  // 重复，过滤掉
            }
            seenLiteratureIds.add(litId);
            return true;
        });
        const otherSources = sources.filter(s => s.type !== 'literature');

        sourcesHtml = `
            <div class="sources">
                <h5>📚 参考来源 (${sources.length} 个)：</h5>
                <ul class="source-list">
                    ${literatureSources.map((s, idx) => {
                        let url = '#';
                        const idStr = String(s.id);
                        if (idStr.startsWith('literature_') && idStr.includes('_full_chunk_')) {
                            url = '/literature/chunk/' + idStr;
                        } else {
                            url = '/literature/' + s.id;
                        }
                        // Extract literature number from chunk ID (e.g., literature_5_full_chunk_185 -> 文献 5)
                        const litMatch = idStr.match(/literature_(\d+)_/);
                        const litNum = litMatch ? litMatch[1] : (idx + 1);

                        // Show content with expandable/collapsible section (no truncation)
                        const contentSection = s.content ? `
                            <div class="source-content-wrapper" style="margin-top: 10px;">
                                <button class="toggle-content-btn" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'; this.textContent=this.nextElementSibling.style.display==='none'?'📄 展开原文':'📄 收起原文'" style="background: #e3f2fd; border: none; padding: 5px 12px; border-radius: 4px; cursor: pointer; font-size: 0.85em; color: #1976d2;">
                                    📄 展开原文
                                </button>
                                <div class="source-content" style="display: none; margin-top: 8px; padding: 12px; background: #f8f9fa; border-radius: 4px; font-size: 0.9em; color: #333; line-height: 1.5; max-height: 400px; overflow-y: auto; border: 1px solid #e0e0e0; white-space: pre-wrap; word-wrap: break-word;">
                                    ${escapeHtml(s.content)}
                                </div>
                            </div>
                        ` : '';

                        return `
                        <li class="source-item" style="margin-bottom: 15px; padding: 10px; border-left: 3px solid #4CAF50; background: #fafafa;">
                            <div class="source-header">
                                <strong>文献 ${litNum}：</strong>
                                <a href="${url}" target="_blank" style="font-weight: 500;">
                                    ${escapeHtml(truncateText(s.title || '', 80))}
                                </a>
                            </div>
                            <div class="source-meta" style="font-size: 0.85em; color: #666; margin-top: 5px;">
                                ${s.authors ? `<span>👥 ${escapeHtml(truncateText(s.authors, 50))}</span><br>` : ''}
                                ${s.journal ? `<span>📰 ${escapeHtml(s.journal)}</span>` : ''}
                                ${s.year ? `<span>📅 ${s.year}</span>` : ''}
                                ${s.doi ? `<span> 🔗 DOI: ${escapeHtml(s.doi)}</span>` : ''}
                            </div>
                            ${contentSection}
                        </li>
                    `}).join('')}
                    ${otherSources.map(s => {
                        let url = '#';
                        if (s.type === 'structure') {
                            url = '/structure/' + s.id;
                        }
                        return `
                        <li class="source-item" style="margin-bottom: 10px;">
                            <a href="${url}" target="_blank">
                                ${escapeHtml(truncateText(s.title || '', 50))} (${s.type || 'unknown'}: ${s.id || 'N/A'})
                            </a>
                        </li>
                    `}).join('')}
                </ul>
            </div>
        `;
    }

    // Image display
    let imageHtml = '';
    if (imageUrl) {
        imageHtml = `
            <div class="message-image">
                <img src="${escapeHtml(imageUrl)}" alt="结构图像" style="max-width: 100%; border-radius: 8px; margin-top: 10px;" onerror="this.style.display='none'">
            </div>
        `;
    }

    // Simple markdown-like formatting - 同时去除首尾空白
    const formattedContent = formatMessage(content).trim();

    messageDiv.innerHTML = `
        ${avatar}
        <div class="message-content">
            <div class="message-text markdown-body">${formattedContent}</div>
            ${imageHtml}
            ${sourcesHtml}
        </div>
    `;

    container.appendChild(messageDiv);
    container.scrollTop = container.scrollHeight;

    // 为代码块添加复制按钮
    addCopyButtons(messageDiv);
}

// Format message content with Markdown support
// Parse JSON title to plain text
function parseJsonTitle(text) {
    if (!text) return '';
    try {
        const trimmed = text.trim();
        if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
            const obj = JSON.parse(trimmed);
            if (obj.text) return obj.text;
            if (obj.title) return obj.title;
            if (obj.content) return obj.content;
        }
        // 处理外层引号包裹的JSON
        if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
            const inner = trimmed.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, '\\');
            const obj = JSON.parse(inner);
            if (obj.text) return obj.text;
            if (obj.title) return obj.title;
            if (obj.content) return obj.content;
        }
    } catch (e) {
        // 不是JSON，返回原文本
    }
    return text;
}

function formatMessage(text) {
    if (!text) return '';

    try {
        // 使用marked.js进行markdown渲染
        if (typeof marked !== 'undefined') {
            // 配置marked选项
            marked.setOptions({
                breaks: true,
                gfm: true,
                headerIds: false,
                mangle: false
            });
            const result = marked.parse(text);
            console.log('[formatMessage] marked.js result:', result.substring(0, 100));
            return result;
        } else {
            console.warn('[formatMessage] marked.js not loaded');
        }
    } catch (e) {
        console.warn('[formatMessage] Markdown parsing failed:', e);
    }

    // Fallback: 简单转换
    let formatted = escapeHtml(text);
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    formatted = formatted.replace(/\*(.*?)\*/g, '<em>$1</em>');
    formatted = formatted.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');
    formatted = formatted.replace(/\n/g, '<br>');

    return formatted;
}

// Add copy buttons to code blocks
function addCopyButtons(container) {
    const preBlocks = container.querySelectorAll('.message-text pre');
    preBlocks.forEach(pre => {
        // 跳过已有复制按钮的
        if (pre.querySelector('.copy-btn')) return;

        const code = pre.querySelector('code');
        if (!code) return;

        const copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.title = '复制';
        // 使用 SVG 图标
        copyBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
        </svg>`;
        copyBtn.onclick = async (e) => {
            e.preventDefault();
            const textToCopy = code.textContent || '';
            try {
                await navigator.clipboard.writeText(textToCopy);
                // 切换到勾选图标
                copyBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>`;
                copyBtn.classList.add('copied');
                setTimeout(() => {
                    copyBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>`;
                    copyBtn.classList.remove('copied');
                }, 2000);
            } catch (err) {
                console.error('复制失败:', err);
            }
        };
        pre.appendChild(copyBtn);
    });
}

// Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Truncate text
function truncateText(text, length) {
    if (!text) return '';
    return text.length > length ? text.substring(0, length) + '...' : text;
}

// Show toast notification
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        if (toast && toast.parentNode) {
            toast.style.opacity = '0';
            setTimeout(() => {
                if (toast && toast.parentNode) toast.remove();
            }, 300);
        }
    }, 3000);
}

// Update search results panel
function updateSearchResults(sources) {
    const panel = document.getElementById('search-results');
    if (!panel) return;

    if (!sources || sources.length === 0) {
        panel.innerHTML = '<p class="empty-state">未找到相关来源</p>';
        return;
    }

    // 过滤无效 chunks - 过滤掉内容太短或包含版权关键词的 chunks
    sources = sources.filter(s => {
        // 非 literature 类型保留
        if (s.type !== 'literature') return true;
        const content = s.content || '';
        // 过滤版权关键词
        const invalidKeywords = ['creative commons', 'copyright', 'license', 'author(s)', 'original author', 'permitting parties', 'permitted under', 'open access'];
        const hasInvalidKeyword = invalidKeywords.some(kw => content.toLowerCase().includes(kw));
        // 过滤内容太短的
        return content.length > 100 && !hasInvalidKeyword;
    });

    if (!sources || sources.length === 0) {
        panel.innerHTML = '<p class="empty-state">未找到相关来源</p>';
        return;
    }

    panel.innerHTML = sources.map((s, idx) => {
        // 根据类型决定链接
        let url = '#';
        const idStr = String(s.id);
        if (s.type === 'structure') {
            url = '/structure/' + s.id;
        } else if (s.type === 'literature') {
            // 检测 chunk ID 格式: literature_5_full_chunk_185
            if (idStr.startsWith('literature_') && idStr.includes('_full_chunk_')) {
                url = '/literature/chunk/' + idStr;
            } else {
                url = '/literature/' + s.id;
            }
        }
        // Extract literature number
        const litMatch = idStr.match(/literature_(\d+)_/);
        const litNum = litMatch ? litMatch[1] : (idx + 1);

        // 格式化作者（处理数组）
        let authorsStr = '';
        if (s.authors) {
            if (Array.isArray(s.authors)) {
                authorsStr = s.authors.slice(0, 3).join(', ');
                if (s.authors.length > 3) authorsStr += ' et al.';
            } else {
                authorsStr = String(s.authors);
            }
        }

        // 显示合并的 chunk 范围（如果有）
        let chunkRangeLabel = '';
        if (s.chunk_range && s.chunk_count > 1) {
            chunkRangeLabel = `<span style="background: #2196F3; color: white; padding: 2px 6px; border-radius: 10px; font-size: 0.7em; margin-left: 5px;">第${s.chunk_range}部分</span>`;
        } else if (s.chunk_count > 1) {
            chunkRangeLabel = `<span style="background: #2196F3; color: white; padding: 2px 6px; border-radius: 10px; font-size: 0.7em; margin-left: 5px;">${s.chunk_count}个片段</span>`;
        }

        return `
        <div class="search-result-item" style="padding: 12px; border-bottom: 1px solid #eee; cursor: pointer; transition: background 0.2s;" onmouseover="this.style.background='#f5f5f5'" onmouseout="this.style.background='white'" onclick="window.location.href='${url}'">
            <div style="display: flex; align-items: center; margin-bottom: 5px;">
                <span style="background: #4CAF50; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; margin-right: 8px;">文献 ${litNum}</span>
                ${chunkRangeLabel}
                <span style="font-size: 0.8em; color: #666; margin-left: auto;">${s.year || 'N/A'}</span>
            </div>
            <div class="title" style="font-weight: 500; color: #333; margin-bottom: 5px; line-height: 1.3;">${escapeHtml(truncateText(s.title || '', 80))}</div>
            <div class="meta" style="font-size: 0.8em; color: #666;">
                ${authorsStr ? `<div>👥 ${escapeHtml(authorsStr)}</div>` : ''}
                ${s.journal ? `<div>📰 ${escapeHtml(s.journal)}</div>` : ''}
            </div>
        </div>
    `}).join('');
}

// Ask suggested question - use agent mode by default
function askQuestion(question) {
    const input = document.getElementById('chat-input');
    if (input) {
        input.value = question;
        input.focus();
        if (agentMode) {
            sendAgentMessage();
        } else {
            sendChatMessage();
        }
    }
}

// Removed: toggleRag() - RAG is always enabled
// Removed: toggleAgentMode() - Agent mode is always on
// Removed: initRagButton() - No longer needed
// Removed: initAgentModeButton() - No longer needed

// Main send chat message function - Simplified to always use Agent mode
async function sendChatMessage() {
    // Always use Agent mode
    await sendAgentMessage();
}

// Send chat message using Agent API
async function sendAgentMessage() {
    if (isProcessing) return;

    // 初始化变量以防止引用错误
    let imageUrl = null;
    let sources = [];

    const input = document.getElementById('chat-input');
    const message = input?.value.trim();
    if (!message) return;

    // Add user message - 去除末尾空白（包括换行）
    const trimmedMessage = message.trim().replace(/^[\s\n\r]+|[\s\n\r]+$/g, '');
    addChatMessage('user', trimmedMessage);
    chatHistory.push({ role: 'user', content: trimmedMessage });

    // Clear input
    if (input) {
        input.value = '';
        input.style.height = 'auto';
    }

    isProcessing = true;

    // Hide suggestions and welcome message - 进入对话模式
    document.querySelector('.suggestion-chips')?.classList.add('hidden');
    enterConversationMode();

    try {
        const useRag = document.getElementById('use-rag')?.checked ?? true;

        // Create simple loading message (隐藏思考过程)
        const loadingDiv = document.createElement('div');
        loadingDiv.className = 'message assistant loading';
        loadingDiv.id = 'loading-message';
        loadingDiv.innerHTML = `
            <div class="message-avatar">🤖</div>
            <div class="message-content">
                <div class="message-text" style="color: #666;">正在思考...</div>
            </div>
        `;
        document.getElementById('chat-messages')?.appendChild(loadingDiv);
        loadingDiv.scrollIntoView({ behavior: 'smooth' });

        // 使用普通JSON请求，避免SSE解析问题
        console.log('[QA] 发送请求，session_id:', currentSessionId, 'model_id:', currentModel?.id);
        const response = await fetch('/api/qa/ask-v2', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: message,
                context: chatHistory.slice(-6),
                use_rag: useRag,
                session_id: currentSessionId,  // 传入当前session_id
                model_id: currentModel?.id  // 传入当前模型ID
            })
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        // 尝试解析为普通JSON响应
        try {
            const data = await response.json();
            if (data.success) {
                if (data.result) {
                    // 新格式：{'success': true, 'result': {type, content, image_url, ...}}
                    finalAnswer = data.result.content || '';
                    sources = data.result.sources || [];
                    imageUrl = data.result.image_url || null;
                    console.log('[QA.js] 使用新格式：content=', finalAnswer.substring(0, 50), 'imageUrl=', imageUrl);
                } else if (data.answer) {
                    // 旧格式：{'success': true, 'answer': ..., 'image_url': ...}
                    finalAnswer = data.answer;
                    sources = data.sources || [];
                    imageUrl = data.image_url || null;
                    console.log('[QA.js] 使用旧格式：content=', finalAnswer.substring(0, 50), 'imageUrl=', imageUrl);
                } else {
                    console.error('API 返回成功但没有内容:', data);
                }
                // 保存返回的 session_id
                if (data.session_id) {
                    currentSessionId = data.session_id;
                    localStorage.setItem('currentSessionId', currentSessionId);
                    console.log('Session ID:', currentSessionId);
                }
            } else {
                console.error('API 返回错误:', data);
                throw new Error(data.error || 'Unknown error');
            }
        } catch (e) {
            console.error('JSON parse error:', e);
            finalAnswer = '抱歉，处理响应时发生错误';
        }

        // 如果上面的JSON解析失败，尝试SSE流式处理作为fallback
        if (!finalAnswer) {
        // 更新步骤状态的函数
        const updateStep = (stepNum, stepName, message) => {
            for (let i = 1; i <= 5; i++) {
                const stepEl = document.getElementById(`step-${i}`);
                if (stepEl) {
                    if (i < stepNum) {
                        stepEl.classList.remove('active');
                        stepEl.classList.add('completed');
                    } else if (i === stepNum) {
                        stepEl.classList.add('active');
                        stepEl.classList.remove('completed');
                    } else {
                        stepEl.classList.remove('active', 'completed');
                    }
                }
            }
        };

        // 处理 SSE 事件
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    try {
                        const event = JSON.parse(data);

                        if (event.type === 'step') {
                            // 更新步骤显示
                            updateStep(event.step, event.name, event.message);
                        } else if (event.type === 'content' || event.type === 'answer') {
                            // 流式内容（这里只收集，最后一起显示）
                            finalAnswer += event.content || '';
                        } else if (event.type === 'sources') {
                            sources = event.sources || [];
                        } else if (event.type === 'image_url') {
                            // 图像 URL 事件
                            imageUrl = event.image_url || null;
                        } else if (event.type === 'done') {
                            // 完成
                            updateStep(5, '生成回答', '回答生成完成');
                        } else if (event.answer) {
                            // 普通 JSON 响应
                            finalAnswer = event.answer;
                            sources = event.sources || [];
                            imageUrl = event.image_url || null;
                        }
                    } catch (e) {
                        // 可能是不是 JSON 的原始内容
                        if (data.trim()) {
                            finalAnswer += data;
                        }
                    }
                }
            }
        }
        }  // 结束 if (!finalAnswer)

        // Remove loading message
        loadingDiv.remove();

        // 如果没有流式内容，从sources中获取
        if (sources.length === 0 && window.lastSources) {
            sources = window.lastSources;
        }

        // Add assistant message (包含 image_url)
        addChatMessage('assistant', finalAnswer || '抱歉，我没有找到相关信息。', sources, imageUrl);
        chatHistory.push({ role: 'assistant', content: finalAnswer || '' });

        // Refresh history list
        loadChatHistoryFromServer();

        // Update sources panel
        updateSearchResults(sources || []);

    } catch (error) {
        console.error('QA Error:', error);
        // Remove loading if exists
        const loading = document.getElementById('loading-message');
        if (loading) loading.remove();
        addChatMessage('assistant', '抱歉，发生了错误: ' + error.message, []);
        showToast('问答失败: ' + error.message, 'error');
    } finally {
        // 重置处理状态，允许继续发送消息
        isProcessing = false;
    }
}

// ============================================
// Simplified Mode - Agent only, RAG always on
// ============================================

let agentMode = true; // Always use Agent mode

// Simplified: Always use Agent mode
function askQuestion(question) {
    const input = document.getElementById('chat-input');
    if (input) {
        input.value = question;
        input.focus();
        sendAgentMessage();
    }
}

// Removed: toggleRag() - RAG is always enabled
// Removed: toggleAgentMode() - Agent mode is always on
// Removed: initRagButton() - No longer needed
// Removed: initAgentModeButton() - No longer needed

// Send message using Agent mode
async function sendAgentMessage() {
    if (isProcessing) return;

    const input = document.getElementById('chat-input');
    const message = input?.value.trim();
    if (!message) return;

    // Check if there's pending clarification
    if (currentClarification) {
        // Handle clarification response
        await handleClarificationResponse(message);
        return;
    }

    // Add user message
    const trimmedMessage = message.trim();
    addChatMessage('user', trimmedMessage);
    chatHistory.push({ role: 'user', content: trimmedMessage });

    // Clear input
    if (input) {
        input.value = '';
        input.style.height = 'auto';
    }

    isProcessing = true;

    // Enter conversation mode
    enterConversationMode();

    // [DEBUG] 检查 agentMode 状态
    console.log('[QA.js] agentMode:', agentMode);

    try {
        // Create loading message
        const loadingDiv = createLoadingMessage();
        document.getElementById('chat-messages')?.appendChild(loadingDiv);

        console.log('[QA Agent] Sending message:', trimmedMessage, 'session_id:', currentSessionId);

        // 使用 ask-v2 端点，支持自动路由
        // 获取 max_tokens 配置
        const maxTokensInput = document.getElementById('max-tokens');
        const maxTokens = maxTokensInput ? parseInt(maxTokensInput.value, 10) || 8096 : 8096;

        const response = await fetch('/api/qa/ask-v2', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: trimmedMessage,
                session_id: currentSessionId,
                max_tokens: maxTokens
            })
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();

        // [DEBUG] 打印后端返回的原始数据
        console.log('[QA.js] 收到后端响应:', JSON.stringify(data, null, 2));

        // Remove loading
        if (loadingDiv && loadingDiv.parentNode) {
            loadingDiv.remove();
        }

        if (!data.success) {
            throw new Error(data.error || 'Agent处理失败');
        }

        // Update session ID
        if (data.session_id) {
            currentSessionId = data.session_id;
            localStorage.setItem('currentSessionId', currentSessionId);
        }

        // Process result based on type
        // Support both new format (data.result) and old format (data.answer, data.image_url)
        if (data.result) {
            // New format: {'success': True, 'result': {type, content, image_url, ...}, ...}
            await processAgentResult(data.result);
        } else if (data.answer !== undefined) {
            // Old format: {'answer': ..., 'image_url': ..., 'success': True, ...}
            // Convert to new format
            const convertedResult = {
                type: 'answer',
                content: data.answer,
                image_url: data.image_url || null,
                tool_results: data.tool_results || []
            };
            await processAgentResult(convertedResult);
        } else {
            console.error('No result in response:', data);
            addChatMessage('assistant', '抱歉，发生了错误: 未收到有效响应', []);
        }

    } catch (error) {
        console.error('QA Agent Error:', error);
        const loading = document.getElementById('loading-message');
        if (loading) loading.remove();
        addChatMessage('assistant', '抱歉，发生了错误: ' + error.message, []);
        showToast('问答失败: ' + error.message, 'error');
    } finally {
        isProcessing = false;
    }
}

// Handle clarification response
async function handleClarificationResponse(value) {
    if (!currentClarification) return;

    const input = document.getElementById('chat-input');
    const message = input?.value.trim();

    // Add user response to chat
    addChatMessage('user', message);

    // Clear input
    if (input) {
        input.value = '';
        input.style.height = 'auto';
    }

    // Clear clarification state
    const clarificationDiv = document.getElementById('clarification-options');
    if (clarificationDiv) {
        clarificationDiv.remove();
    }

    // Create loading
    const loadingDiv = createLoadingMessage();
    document.getElementById('chat-messages')?.appendChild(loadingDiv);

    try {
        const response = await fetch('/api/qa/agent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: message,
                session_id: currentSessionId,
                clarification_id: currentClarification.question,
                clarification_value: value || message
            })
        });

        const data = await response.json();
        // Remove loading
        if (loadingDiv && loadingDiv.parentNode) {
            loadingDiv.remove();
        }

        if (!data.success) {
            throw new Error(data.error || '处理失败');
        }

        // Update session
        if (data.session_id) {
            currentSessionId = data.session_id;
            localStorage.setItem('currentSessionId', currentSessionId);
        }

        // Clear clarification state
        currentClarification = null;

        // Process result - support both new and old format
        if (data.result) {
            await processAgentResult(data.result);
        } else if (data.answer !== undefined) {
            const convertedResult = {
                type: 'answer',
                content: data.answer,
                image_url: data.image_url || null,
                tool_results: data.tool_results || []
            };
            await processAgentResult(convertedResult);
        }

    } catch (error) {
        console.error('Clarification Error:', error);
        if (loadingDiv && loadingDiv.parentNode) {
            loadingDiv.remove();
        }
        addChatMessage('assistant', '处理选择时出错: ' + error.message, []);
    } finally {
        isProcessing = false;
    }
}

// Process agent result based on type
async function processAgentResult(result) {
    console.log('[QA.js] processAgentResult called with:', JSON.stringify(result, null, 2));

    if (!result || !result.type) {
        console.error('Invalid result:', result);
        addChatMessage('assistant', '抱歉，发生了错误: 响应格式无效', []);
        return;
    }

    switch (result.type) {
        case 'clarification':
            // Show clarification options
            showClarification(result.clarification, result.options);
            break;

        case 'answer':
            // Show answer with image if available
            const imageUrl = result.image_url || null;
            const sources = result.sources || [];
            console.log('[QA.js] answer case: content=', result.content, 'imageUrl=', imageUrl, 'sources=', sources);
            addChatMessage('assistant', result.content, sources, imageUrl);
            // Update search results if there are tool results
            if (result.tool_results && result.tool_results.length > 0) {
                processToolResults(result.tool_results);
            }
            // Update search results panel
            if (sources.length > 0) {
                updateSearchResults(sources);
            }
            break;

        case 'error':
            addChatMessage('assistant', result.message, []);
            if (result.suggestion) {
                showToast(result.suggestion, 'info');
            }
            break;

        default:
            console.warn('Unknown result type:', result.type);
    }
}

// Show clarification options to user
function showClarification(question, options) {
    // Store current clarification
    currentClarification = { question: question };

    // Remove existing clarification if any
    const existing = document.getElementById('clarification-options');
    if (existing) existing.remove();

    // Create clarification UI
    const container = document.getElementById('chat-messages');
    if (!container) return;

    const clarificationDiv = document.createElement('div');
    clarificationDiv.id = 'clarification-options';
    clarificationDiv.className = 'message assistant clarification-message';

    const optionsHtml = options.map(opt => `
        <button class="clarification-option" onclick="handleClarificationResponse('${opt.value || opt.id}')">
            <div class="option-icon">${getOptionIcon(opt.id)}</div>
            <div class="option-content">
                <div class="option-label">${escapeHtml(opt.label)}</div>
                ${opt.description ? `<div class="option-desc">${escapeHtml(opt.description)}</div>` : ''}
            </div>
        </button>
    `).join('');

    clarificationDiv.innerHTML = `
        <div class="message-avatar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
        </div>
        <div class="message-content">
            <div class="clarification-question">${escapeHtml(question)}</div>
            <div class="clarification-options">${optionsHtml}</div>
        </div>
    `;

    container.appendChild(clarificationDiv);
    container.scrollTop = container.scrollHeight;

    // Focus input
    const input = document.getElementById('chat-input');
    if (input) input.focus();
}

// Get icon for option type
function getOptionIcon(optionId) {
    const icons = {
        'pdb_select': '📂',
        'uniprot': '🧬',
        'sequence': '📝',
        'pdb_input': '🔍',
        'emdb_input': '🔍',
        'pdb_search': '🔍',
        'custom': '⌨️'
    };
    return icons[optionId] || '👉';
}

// Process tool results for display
function processToolResults(toolResults) {
    const sources = [];

    toolResults.forEach(result => {
        if (!result.success) return;

        const toolName = result.tool_name;
        const data = result.result;

        // Fix: Check if data exists before accessing properties
        if (!data) return;

        if (toolName === 'search_literature' && data.results) {
            data.results.forEach(lit => {
                sources.push({
                    type: 'literature',
                    id: lit.id,
                    title: lit.title || 'Unknown',
                    // Add more details for better source display
                    authors: lit.authors || '',
                    year: lit.year || '',
                    journal: lit.journal || '',
                    doi: lit.doi || '',
                    content: lit.content || lit.abstract || ''  // Add content for preview
                });
            });
        } else if (toolName === 'get_structure_details' && data.structure) {
            sources.push({
                type: 'structure',
                id: data.structure.pdb_id,
                title: data.structure.title || 'Structure'
            });
        }
    });

    if (sources.length > 0) {
        updateSearchResults(sources);
    }
}

// Create loading message
function createLoadingMessage() {
    const div = document.createElement('div');
    div.className = 'message assistant loading';
    div.id = 'loading-message';
    div.innerHTML = `
        <div class="message-avatar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7l10 5 10-5-10-5z"></path>
                <path d="M2 17l10 5 10-5"></path>
                <path d="M2 12l10 5 10-5"></path>
            </svg>
        </div>
        <div class="message-content">
            <div class="thinking-indicator">
                <span class="thinking-dot"></span>
                <span class="thinking-dot"></span>
                <span class="thinking-dot"></span>
            </div>
            <div class="message-text" style="color: #666;">正在分析问题...</div>
        </div>
    `;
    return div;
}

// SSE streaming for agent (optional, for real-time feedback)
async function sendAgentMessageStream() {
    if (isProcessing) return;

    const input = document.getElementById('chat-input');
    const message = input?.value.trim();
    if (!message) return;

    // Add user message
    addChatMessage('user', message);
    chatHistory.push({ role: 'user', content: message });

    if (input) {
        input.value = '';
    }

    isProcessing = true;
    enterConversationMode();

    try {
        const url = `/api/qa/agent/stream?question=${encodeURIComponent(message)}&session_id=${currentSessionId || ''}`;
        const response = await fetch(url);

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let thinkingDiv = createThinkingPanel();

        document.getElementById('chat-messages')?.appendChild(thinkingDiv);

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    try {
                        const event = JSON.parse(data);
                        updateThinkingPanel(thinkingDiv, event);
                    } catch (e) {}
                }
            }
        }

        // Remove thinking panel
        thinkingDiv.remove();

    } catch (error) {
        console.error('Stream error:', error);
        addChatMessage('assistant', '抱歉，发生了错误: ' + error.message, []);
    } finally {
        isProcessing = false;
    }
}

// Create thinking process panel
function createThinkingPanel() {
    const div = document.createElement('div');
    div.className = 'thinking-panel';
    div.id = 'thinking-panel';
    div.innerHTML = `
        <div class="thinking-header">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7l10 5 10-5-10-5z"></path>
                <path d="M2 17l10 5 10-5"></path>
                <path d="M2 12l10 5 10-5"></path>
            </svg>
            <span>AI 思考过程</span>
        </div>
        <div class="thinking-steps"></div>
    `;
    return div;
}

// Update thinking panel
function updateThinkingPanel(panel, event) {
    const stepsContainer = panel.querySelector('.thinking-steps');
    if (!stepsContainer) return;

    const steps = {
        'start': { icon: '🔍', text: '正在分析问题...' },
        'thinking': { icon: '🧠', text: '思考中...' },
        'tool_call': { icon: '🛠️', text: `调用工具: ${event.tool || '...'}` },
        'tool_result': { icon: '📊', text: `工具执行${event.success ? '成功' : '失败'}` },
        'result': { icon: '✅', text: '生成答案...' },
        'error': { icon: '❌', text: `错误: ${event.message}` },
        'end': { icon: '✨', text: '完成' }
    };

    const step = steps[event.type];
    if (step) {
        const stepDiv = document.createElement('div');
        stepDiv.className = `thinking-step ${event.type}`;
        stepDiv.innerHTML = `
            <span class="step-icon">${step.icon}</span>
            <span class="step-text">${step.text}</span>
        `;
        stepsContainer.appendChild(stepDiv);
        stepsContainer.scrollTop = stepsContainer.scrollHeight;
    }
}

// Make functions globally available
window.initPage = initPage;
window.startNewSession = startNewSession;
window.enterConversationMode = enterConversationMode;
window.sendChatMessage = sendChatMessage;
window.addChatMessage = addChatMessage;
window.askQuestion = askQuestion;
// Removed: window.toggleRag - RAG is always enabled
window.showToast = showToast;
window.updateSearchResults = updateSearchResults;
window.loadChatHistory = loadChatHistoryFromServer;
window.loadHistoryItem = loadHistoryItem;
window.loadHistorySession = loadHistorySession;
window.clearChatHistory = clearChatHistory;
window.escapeHtml = escapeHtml;
window.truncateText = truncateText;

// Agent mode functions
window.sendAgentMessage = sendAgentMessage;
window.handleClarificationResponse = handleClarificationResponse;
// Removed: window.toggleAgentMode - Agent mode is always on
window.processAgentResult = processAgentResult;
