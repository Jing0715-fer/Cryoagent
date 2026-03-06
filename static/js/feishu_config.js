/**
 * 飞书集成配置页面 JavaScript
 */

// 加载配置
document.addEventListener('DOMContentLoaded', function() {
    loadDocuments();
});

// 表单提交
document.getElementById('feishu-config-form').addEventListener('submit', async function(e) {
    e.preventDefault();

    const formData = {
        enabled: document.getElementById('enabled').checked,
        app_id: document.getElementById('app-id').value.trim(),
        app_secret: document.getElementById('app-secret').value.trim(),
        bot_id: document.getElementById('bot-id').value.trim(),
        verification_token: document.getElementById('verification-token').value.trim(),
        encrypt_key: document.getElementById('encrypt-key').value.trim(),
        webhook_url: document.getElementById('webhook-url').value.trim()
    };

    try {
        const response = await fetch('/api/feishu/config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });

        const result = await response.json();

        showTestResult('test-result', result.success, result.message);

        if (result.success) {
            // 重新加载页面以刷新配置显示
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        }
    } catch (error) {
        showTestResult('test-result', false, '保存失败: ' + error.message);
    }
});

// 测试连接
async function testConnection() {
    const appId = document.getElementById('app-id').value.trim();
    const appSecret = document.getElementById('app-secret').value.trim();

    if (!appId || !appSecret) {
        showTestResult('test-result', false, '请输入 App ID 和 App Secret');
        return;
    }

    try {
        const response = await fetch('/api/feishu/test', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                app_id: appId,
                app_secret: appSecret
            })
        });

        const result = await response.json();
        showTestResult('test-result', result.success, result.message);
    } catch (error) {
        showTestResult('test-result', false, '连接失败: ' + error.message);
    }
}

// 获取并索引文档
async function fetchDocument() {
    const docToken = document.getElementById('doc-token').value.trim();

    if (!docToken) {
        showTestResult('fetch-result', false, '请输入文档 Token');
        return;
    }

    try {
        const response = await fetch('/api/feishu/documents/fetch', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                doc_token: docToken
            })
        });

        const result = await response.json();
        showTestResult('fetch-result', result.success, result.message);

        if (result.success) {
            document.getElementById('doc-token').value = '';
            loadDocuments();
        }
    } catch (error) {
        showTestResult('fetch-result', false, '获取文档失败: ' + error.message);
    }
}

// 加载文档列表（从本地文件）
async function loadDocuments() {
    const listContainer = document.getElementById('document-list');

    try {
        const response = await fetch('/api/feishu/documents/list');
        const result = await response.json();

        if (result.success) {
            const documents = result.documents || [];

            if (documents.length === 0) {
                listContainer.innerHTML = '<p class="empty">暂无同步的文档</p>';
                return;
            }

            listContainer.innerHTML = documents.map(doc => `
                <div class="document-item" data-doc-id="${doc.doc_id}">
                    <div class="doc-info">
                        <div class="doc-title">${escapeHtml(doc.title)}</div>
                        <div class="doc-meta">ID: ${escapeHtml(doc.doc_id)} | 获取时间: ${formatDate(doc.metadata.fetched_at)}</div>
                        <div class="doc-preview">${escapeHtml(doc.content || '')}</div>
                    </div>
                    <div class="doc-actions">
                        <button class="btn btn-secondary" onclick="viewDocument('${doc.doc_id}')">查看</button>
                        <button class="btn btn-danger" onclick="deleteDocument('${doc.doc_id}')">删除</button>
                    </div>
                </div>
            `).join('');
        } else {
            listContainer.innerHTML = '<p class="error">加载失败: ' + (result.message || '') + '</p>';
        }
    } catch (error) {
        listContainer.innerHTML = '<p class="error">加载失败: ' + error.message + '</p>';
    }
}

// 查看文档详情
async function viewDocument(docId) {
    try {
        const response = await fetch('/api/feishu/documents/' + docId);
        const result = await response.json();

        if (result.success && result.document) {
            const doc = result.document;
            document.getElementById('modal-title').textContent = doc.title;
            document.getElementById('modal-content').innerHTML = `
                <div class="doc-detail">
                    <p><strong>文档ID:</strong> ${escapeHtml(doc.doc_id)}</p>
                    <p><strong>飞书ID:</strong> ${escapeHtml(doc.source_id)}</p>
                    <hr>
                    <div class="doc-text">
                        <h3>文档内容:</h3>
                        <pre style="white-space: pre-wrap; word-wrap: break-word; max-height: 500px; overflow-y: auto;">${escapeHtml(doc.content || '无内容')}</pre>
                    </div>
                </div>
            `;
            document.getElementById('doc-modal').style.display = 'block';
        } else {
            alert('获取文档失败: ' + (result.message || '未知错误'));
        }
    } catch (error) {
        alert('获取文档失败: ' + error.message);
    }
}

// 关闭Modal
function closeModal() {
    document.getElementById('doc-modal').style.display = 'none';
}

// 点击Modal外部关闭
window.onclick = function(event) {
    const modal = document.getElementById('doc-modal');
    if (event.target === modal) {
        modal.style.display = 'none';
    }
}

// 删除文档
async function deleteDocument(docId) {
    if (!confirm('确定要删除此文档吗？')) {
        return;
    }

    try {
        const response = await fetch('/api/feishu/documents/delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                doc_id: docId
            })
        });

        const result = await response.json();

        if (result.success) {
            loadDocuments();
        } else {
            alert(result.message);
        }
    } catch (error) {
        alert('删除失败: ' + error.message);
    }
}

// 搜索飞书知识库
async function searchFeishu() {
    const query = document.getElementById('search-query').value.trim();
    const resultsContainer = document.getElementById('search-results');

    if (!query) {
        resultsContainer.style.display = 'block';
        resultsContainer.innerHTML = '<p class="error">请输入搜索内容</p>';
        return;
    }

    try {
        const response = await fetch('/api/feishu/search', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                query: query,
                top_k: 5
            })
        });

        const result = await response.json();

        resultsContainer.style.display = 'block';

        if (result.success && result.results && result.results.length > 0) {
            resultsContainer.innerHTML = result.results.map(r => `
                <div class="search-result-item">
                    <div class="result-title">${escapeHtml(r.title || r.metadata?.title || '无标题')}</div>
                    <div class="result-content">${escapeHtml(r.content || r.metadata?.content || '')}</div>
                    <div class="result-score">相似度: ${(r.score || 0).toFixed(4)}</div>
                </div>
            `).join('');
        } else {
            resultsContainer.innerHTML = '<p>未找到相关结果</p>';
        }
    } catch (error) {
        resultsContainer.style.display = 'block';
        resultsContainer.innerHTML = '<p class="error">搜索失败: ' + error.message + '</p>';
    }
}

// 辅助函数：显示测试结果
function showTestResult(elementId, success, message) {
    const container = document.getElementById(elementId);
    container.style.display = 'block';
    container.className = 'test-result ' + (success ? 'success' : 'error');
    container.textContent = message;

    // 5秒后隐藏
    setTimeout(() => {
        container.style.display = 'none';
    }, 5000);
}

// 辅助函数：HTML转义
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 辅助函数：格式化日期
function formatDate(dateStr) {
    if (!dateStr) return '';
    try {
        const date = new Date(dateStr);
        return date.toLocaleString('zh-CN');
    } catch {
        return dateStr;
    }
}
