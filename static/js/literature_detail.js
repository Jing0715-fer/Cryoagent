/* ============================================
   CryoAgent Pro - Literature Detail Page
   ============================================ */

let currentLiteratureId = null;
let currentSessionId = null;

// Initialize detail page
function initPage() {
    // Get literature ID from URL or data attribute
    const detailPage = document.querySelector('.detail-page');
    if (detailPage) {
        currentLiteratureId = parseInt(detailPage.dataset.litId || window.location.pathname.split('/').pop());
    }

    if (currentLiteratureId) {
        loadLiteratureDetail(currentLiteratureId);
        loadStructures(currentLiteratureId);
        loadSections(currentLiteratureId);
    }
}

// Load literature detail
async function loadLiteratureDetail(id) {
    try {
        const data = await apiRequest(`/literature/${id}`);

        // Update title
        const titleEl = document.getElementById('lit-title');
        if (titleEl) titleEl.textContent = data.title || 'Unknown';

        // Update authors
        const authorsEl = document.getElementById('lit-authors');
        if (authorsEl) {
            const authors = Array.isArray(data.authors) ? data.authors.map(a => a.name || a).join(', ') : (data.authors || 'Unknown');
            authorsEl.textContent = authors;
        }

        // Update journal
        const journalEl = document.getElementById('lit-journal');
        if (journalEl) journalEl.textContent = data.journal || 'Unknown';

        // Update year
        const yearEl = document.getElementById('lit-year');
        if (yearEl) yearEl.textContent = data.year || 'N/A';

        // Update DOI
        const doiEl = document.getElementById('lit-doi');
        if (doiEl) doiEl.textContent = data.doi || 'N/A';

        // Update status
        const statusEl = document.getElementById('lit-status');
        if (statusEl) {
            statusEl.textContent = (data.status || '').toUpperCase();
            statusEl.className = `status-badge status-${data.status || 'unknown'}`;
        }

        // Update info grid - skip N/A fields
        const infoGrid = document.getElementById('lit-info-grid');
        let infoItems = '';

        // DOI (always show)
        if (data.doi) {
            infoItems += `
                <div class="info-item full-width">
                    <label>DOI</label>
                    <p>${data.doi}</p>
                </div>
            `;
        }

        // Journal and Year
        if (data.journal) {
            infoItems += `
                <div class="info-item">
                    <label>期刊</label>
                    <p>${data.journal}</p>
                </div>
            `;
        }
        if (data.year) {
            infoItems += `
                <div class="info-item">
                    <label>年份</label>
                    <p>${data.year}</p>
                </div>
            `;
        }
        if (data.status) {
            infoItems += `
                <div class="info-item">
                    <label>状态</label>
                    <p>${data.status}</p>
                </div>
            `;
        }

        // Parsing method
        if (data.parsing_method && data.parsing_method !== 'N/A') {
            infoItems += `
                <div class="info-item">
                    <label>解析方法</label>
                    <p>${data.parsing_method}</p>
                </div>
            `;
        }

        // Keywords
        const keywords = data.keywords;
        const keywordsList = Array.isArray(keywords) ? keywords.filter(k => k && k.trim()) : (keywords && keywords.trim());
        if (keywordsList && keywordsList.length > 0) {
            const keywordsStr = Array.isArray(keywordsList) ? keywordsList.join(', ') : keywordsList;
            infoItems += `
                <div class="info-item full-width">
                    <label>关键词</label>
                    <p>${keywordsStr}</p>
                </div>
            `;
        }

        if (infoGrid) {
            infoGrid.innerHTML = infoItems;
        }

        // Update abstract
        const abstractEl = document.getElementById('lit-abstract');
        if (abstractEl) {
            abstractEl.textContent = data.abstract || '暂无摘要';
        }

        // Update page title
        document.title = `${data.title?.substring(0, 30) || '文献详情'} - CryoAgent Pro`;

    } catch (error) {
        console.error('Failed to load literature detail:', error);
        showToast('加载失败: ' + error.message, 'error');
    }
}

// Load related structures
async function loadStructures(litId) {
    const grid = document.getElementById('structures-grid');
    if (!grid) return;

    try {
        const data = await apiRequest(`/structure/literature/${litId}`);

        if (!data.structures || data.structures.length === 0) {
            grid.innerHTML = '<p class="empty-state">暂无结构信息</p>';
            return;
        }

        // 配对显示逻辑
        if (data.paired) {
            grid.innerHTML = data.structures.map(s => `
                <div class="structure-card paired" onclick="window.location.href='/structure/${s.pdb ? s.pdb.id : s.emdb.id}'">
                    <div class="card-content">
                        <div class="structure-pair">
                            ${s.pdb ? `
                                <div class="structure-item pdb" onclick="event.stopPropagation(); showStructurePopup('${s.pdb.id}', 'pdb', '${escapeHtml(s.pdb.title || '')}', '${s.pdb.resolution || ''}', '${s.pdb.method || ''}')">
                                    <div class="item-header">
                                        <span class="structure-type-badge type-pdb">PDB</span>
                                        <h4 class="card-title">${s.pdb.id}</h4>
                                    </div>
                                    <p class="structure-title">${escapeHtml(truncateText(s.pdb.title || '', 40))}</p>
                                    ${s.pdb.resolution ? `<span class="resolution-value">${s.pdb.resolution} Å</span>` : ''}
                                    <span class="meta-item">${s.pdb.method || ''}</span>
                                    <div class="popup-hint">点击查看详情</div>
                                </div>
                            ` : ''}
                            ${s.emdb ? `
                                <div class="structure-item emdb" onclick="event.stopPropagation(); showStructurePopup('${s.emdb.id}', 'emdb', '${escapeHtml(s.emdb.title || '')}', '${s.emdb.resolution || ''}', '${s.emdb.method || ''}')">
                                    <div class="item-header">
                                        <span class="structure-type-badge type-emdb">EMDB</span>
                                        <h4 class="card-title">${s.emdb.id}</h4>
                                    </div>
                                    <p class="structure-title">${escapeHtml(truncateText(s.emdb.title || '', 40))}</p>
                                    ${s.emdb.resolution ? `<span class="resolution-value">${s.emdb.resolution} Å</span>` : ''}
                                    <span class="meta-item">${s.emdb.method || ''}</span>
                                    <div class="popup-hint">点击查看详情</div>
                                </div>
                            ` : ''}
                        </div>
                        ${s.organism ? `<div class="meta-info"><span class="meta-item">${escapeHtml(s.organism)}</span></div>` : ''}
                        ${s.protein_name ? `<div class="meta-info"><span class="meta-item">${escapeHtml(truncateText(s.protein_name, 50))}</span></div>` : ''}
                    </div>
                </div>
            `).join('');
        } else {
            // 非配对模式（单个结构）
            grid.innerHTML = data.structures.map(s => `
                <div class="structure-card" onclick="window.location.href='/structure/${s.id}'">
                    <div class="card-header">
                        <span class="structure-type-badge type-${(s.type || '').toLowerCase()}">${s.type || 'PDB'}</span>
                        <h4 class="card-title">${s.id}</h4>
                    </div>
                    <div class="card-content">
                        <p class="structure-title">${escapeHtml(truncateText(s.title || '', 60))}</p>
                        ${s.resolution ? `
                            <div class="resolution-badge">
                                <span class="resolution-value">${s.resolution} &#197;</span>
                            </div>
                        ` : ''}
                        <div class="meta-info">
                            <span class="meta-item">${s.method || 'N/A'}</span>
                        </div>
                        ${s.organism ? `
                            <div class="meta-info">
                                <span class="meta-item">${escapeHtml(s.organism)}</span>
                            </div>
                        ` : ''}
                        ${s.protein_name ? `
                            <div class="meta-info">
                                <span class="meta-item">${escapeHtml(truncateText(s.protein_name, 40))}</span>
                            </div>
                        ` : ''}
                    </div>
                </div>
            `).join('');
        }

    } catch (error) {
        console.error('Failed to load structures:', error);
        grid.innerHTML = '<p class="empty-state">加载结构信息失败: ' + error.message + '</p>';
    }
}

// Load literature sections
async function loadSections(litId) {
    const container = document.getElementById('sections-container');
    if (!container) return;

    try {
        const data = await apiRequest(`/literature/${litId}`);

        // Build sections HTML
        const sections = [];

        if (data.introduction) {
            sections.push({
                title: '引言',
                content: data.introduction
            });
        }
        if (data.methods) {
            sections.push({
                title: '方法',
                content: data.methods
            });
        }
        if (data.results) {
            sections.push({
                title: '结果',
                content: data.results
            });
        }
        if (data.discussion) {
            sections.push({
                title: '讨论',
                content: data.discussion
            });
        }
        if (data.conclusions) {
            sections.push({
                title: '结论',
                content: data.conclusions
            });
        }

        if (sections.length === 0) {
            container.innerHTML = '<p class="empty-state">暂无章节信息</p>';
            return;
        }

        container.innerHTML = sections.map(s => `
            <div class="section-item">
                <h4 class="section-title">${s.title}</h4>
                <div class="section-content">${escapeHtml(s.content)}</div>
            </div>
        `).join('');

    } catch (error) {
        console.error('Failed to load sections:', error);
        container.innerHTML = '<p class="empty-state">加载章节信息失败</p>';
    }
}

// QA Functions
function sendQuestion() {
    const input = document.getElementById('qa-input');
    const question = input?.value.trim();

    if (!question) return;

    // Add user message
    addMessage('user', question);
    input.value = '';

    // Show loading
    showTypingIndicator();

    // Send to API
    apiRequest('/qa/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            question,
            literature_id: currentLiteratureId,
            context: []
        })
    }).then(response => {
        removeTypingIndicator();
        addMessage('assistant', response.answer, response.sources);
    }).catch(error => {
        removeTypingIndicator();
        showToast('问答失败: ' + error.message, 'error');
        addMessage('assistant', '抱歉，我无法回答您的问题。请稍后再试。', []);
    });
}

function addMessage(role, content, sources = []) {
    const container = document.getElementById('qa-messages') || document.getElementById('chat-messages');
    if (!container) return;

    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const isUser = role === 'user';
    const avatar = isUser ? '' : '<div class="message-avatar">&#129302;</div>';

    let sourcesHtml = '';
    if (sources && sources.length > 0) {
        sourcesHtml = `
            <div class="sources">
                <h5>参考来源：</h5>
                <ul>
                    ${sources.map(s => `
                        <li>
                            <a href="/literature/${s.id}" target="_blank">
                                ${escapeHtml(truncateText(s.title, 50))}
                            </a>
                        </li>
                    `).join('')}
                </ul>
            </div>
        `;
    }

    messageDiv.innerHTML = `
        ${avatar}
        <div class="message-content">
            <div class="message-text">${escapeHtml(content)}</div>
            ${sourcesHtml}
        </div>
    `;

    container.appendChild(messageDiv);
    container.scrollTop = container.scrollHeight;
}

function showTypingIndicator() {
    const container = document.getElementById('qa-messages') || document.getElementById('chat-messages');
    if (!container) return;

    const typingDiv = document.createElement('div');
    typingDiv.className = 'message assistant typing';
    typingDiv.id = 'typing-indicator';
    typingDiv.innerHTML = `
        <div class="message-avatar">&#129302;</div>
        <div class="message-content">
            <div class="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
            </div>
        </div>
    `;

    container.appendChild(typingDiv);
    container.scrollTop = container.scrollHeight;
}

function removeTypingIndicator() {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) indicator.remove();
}

function askSuggestion(btn) {
    const question = btn.textContent;
    const input = document.getElementById('qa-input');
    if (input) {
        input.value = question;
        input.focus();
        sendQuestion();
    }
}

// Reparse literature
async function reparseLiterature(id) {
    showToast('开始重新解析...', 'info');

    try {
        await apiRequest(`/literature/${id}/reparse`, { method: 'POST' });
        showToast('重新解析任务已启动', 'success');

        // Reload after a delay
        setTimeout(() => {
            loadLiteratureDetail(id);
            loadSections(id);
        }, 2000);

    } catch (error) {
        showToast('重新解析失败: ' + error.message, 'error');
    }
}

// Sequence alignment
async function runAlignment() {
    const seq1 = document.getElementById('seq1')?.value.trim();
    const seq2 = document.getElementById('seq2')?.value.trim();
    const resultDiv = document.getElementById('alignment-result');

    if (!seq1 || !seq2) {
        showToast('请输入两条序列', 'warning');
        return;
    }

    showToast('正在比对...', 'info');

    try {
        const result = await apiRequest('/utils/alignment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sequence1: seq1,
                sequence2: seq2,
                type: 'global'
            })
        });

        if (resultDiv) {
            resultDiv.innerHTML = `
                <div class="alignment-output">
                    <pre>${escapeHtml(result.aligned_seq1)}</pre>
                    <pre>${escapeHtml(result.aligned_seq2)}</pre>
                </div>
                <div class="alignment-stats">
                    <div class="alignment-stat">
                        <span class="alignment-stat-value">${result.score}</span>
                        <span class="alignment-stat-label">比对得分</span>
                    </div>
                    <div class="alignment-stat">
                        <span class="alignment-stat-value">${(result.identity * 100).toFixed(1)}%</span>
                        <span class="alignment-stat-label">一致性</span>
                    </div>
                    <div class="alignment-stat">
                        <span class="alignment-stat-value">${(result.similarity * 100).toFixed(1)}%</span>
                        <span class="alignment-stat-label">相似度</span>
                    </div>
                </div>
            `;
        }

    } catch (error) {
        showToast('比对失败: ' + error.message, 'error');
    }
}

// View structure detail
async function viewStructureDetail(structureId) {
    const modal = document.getElementById('structure-modal');
    const modalBody = document.getElementById('modal-body');

    if (!modal || !modalBody) {
        console.error('Structure modal not found');
        return;
    }

    modalBody.innerHTML = '<p class="loading-state">加载中...</p>';
    modal.style.display = 'flex';
    modal.classList.add('active');

    try {
        const data = await apiRequest(`/structure/${structureId}`);

        document.getElementById('modal-title').textContent = structureId;

        modalBody.innerHTML = `
            <div class="info-grid">
                <div class="info-item full-width">
                    <label>标题</label>
                    <p>${escapeHtml(data.title || 'N/A')}</p>
                </div>
                <div class="info-item">
                    <label>类型</label>
                    <p>${data.type || 'PDB'}</p>
                </div>
                <div class="info-item">
                    <label>分辨率</label>
                    <p>${data.resolution ? data.resolution + ' Å' : 'N/A'}</p>
                </div>
                <div class="info-item">
                    <label>方法</label>
                    <p>${data.method || 'N/A'}</p>
                </div>
                <div class="info-item">
                    <label>物种</label>
                    <p>${data.organism || 'N/A'}</p>
                </div>
                <div class="info-item">
                    <label>引用次数</label>
                    <p>${data.citation_count || 0}</p>
                </div>
                <div class="info-item full-width">
                    <label>作者</label>
                    <p>${escapeHtml(data.authors?.join(', ') || 'N/A')}</p>
                </div>
            </div>
        `;

    } catch (error) {
        modalBody.innerHTML = `<p class="empty-state">加载失败: ${error.message}</p>`;
    }
}

// Show structure popup for paired cards
async function showStructurePopup(structureId, type, title, resolution, method) {
    const modal = document.getElementById('structure-modal');
    const modalBody = document.getElementById('modal-body');

    if (!modal || !modalBody) {
        console.error('Structure modal not found');
        return;
    }

    modalBody.innerHTML = '<div class="popup-loading"><div class="spinner"></div><p>加载中...</p></div>';
    modal.style.display = 'flex';
    modal.classList.add('active');

    // Use data passed from the card
    const displayTitle = title || 'N/A';
    const displayResolution = resolution ? resolution + ' Å' : 'N/A';
    const displayMethod = method || 'N/A';

    // Build beautiful popup content
    const isPdb = type === 'pdb';
    const badgeColor = isPdb ? '#4CAF50' : '#FF9800';

    let content = `
        <div class="structure-popup">
            <div class="popup-body">
                <div class="popup-section">
                    <div class="popup-info-grid">
                        <div class="popup-info-item full-width">
                            <span class="popup-label">标题</span>
                            <span class="popup-value">${escapeHtml(displayTitle)}</span>
                        </div>
                        <div class="popup-info-item">
                            <span class="popup-label">分辨率</span>
                            <span class="popup-value">${displayResolution}</span>
                        </div>
                        ${!isPdb ? '' : `
                        <div class="popup-info-item">
                            <span class="popup-label">方法</span>
                            <span class="popup-value">${displayMethod}</span>
                        </div>
                        `}
                    </div>
                </div>

                <div class="popup-section">
                    <span class="popup-label">操作</span>
                    <div class="popup-links">
                        ${isPdb ? `
                            <a href="https://www.rcsb.org/structure/${structureId}" target="_blank" class="popup-link">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                                RCSB
                            </a>
                            <a href="https://www.ebi.ac.uk/pdbe/entry/pdb/${structureId.toLowerCase()}" target="_blank" class="popup-link">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                                PDBe
                            </a>
                        ` : `
                            <a href="https://www.ebi.ac.uk/emdb/entry/${structureId.replace('EMD-', '')}" target="_blank" class="popup-link">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                                EMDB
                            </a>
                            <a href="https://www.rcsb.org/structure/${structureId}" target="_blank" class="popup-link">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                                RCSB
                            </a>
                        `}
                        <a href="/structure/${structureId}" class="popup-link">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
                            查看详情
                        </a>
                    </div>
                </div>
            </div>
        </div>
    `;

    modalBody.innerHTML = content;
}

function closeModal() {
    const modal = document.getElementById('structure-modal');
    if (modal) {
        modal.classList.remove('active');
        modal.style.display = 'none';
    }
}

// Close modal when clicking outside
document.addEventListener('click', function(event) {
    const modal = document.getElementById('structure-modal');
    if (modal && event.target === modal) {
        closeModal();
    }
});

// Make functions globally available
window.initPage = initPage;
window.loadLiteratureDetail = loadLiteratureDetail;
window.loadStructures = loadStructures;
window.loadSections = loadSections;
window.sendQuestion = sendQuestion;
window.addMessage = addMessage;
window.askSuggestion = askSuggestion;
window.reparseLiterature = reparseLiterature;
window.runAlignment = runAlignment;
window.viewStructureDetail = viewStructureDetail;
window.closeModal = closeModal;
window.showStructurePopup = showStructurePopup;
