/* ============================================
   CryoAgent Pro - Main Application
   ============================================ */

// Application State
const AppState = {
    currentPage: 1,
    perPage: 20,
    totalPages: 1,
    totalItems: 0,
    isLoading: false,
    filters: {},
    theme: 'original'
};

// Theme Management
const ThemeManager = {
    themes: {
        'original': { name: '原始', css: null },
        'dark': { name: '夜间', css: '/static/css/theme-dark.css' },
        'cyberpunk': { name: '赛博朋克', css: '/static/css/theme-cyberpunk.css' },
        'matrix': { name: '黑客帝国', css: '/static/css/theme-matrix.css' },
        'persona5': { name: 'P5', css: '/static/css/theme-persona5.css' },
        'persona4': { name: 'P4', css: '/static/css/theme-persona4.css' },
        'persona3': { name: 'P3', css: '/static/css/theme-persona3.css' }
    },

    currentTheme: 'original',
    themeLink: null,

    init() {
        // Load saved theme
        const savedTheme = localStorage.getItem('theme') || 'original';
        this.setTheme(savedTheme, false);
    },

    setTheme(themeName, save = true) {
        if (!this.themes[themeName]) {
            console.error('Unknown theme:', themeName);
            return;
        }

        this.currentTheme = themeName;

        // Remove existing theme link
        if (this.themeLink) {
            this.themeLink.remove();
            this.themeLink = null;
        }

        // Add new theme CSS if not original
        const theme = this.themes[themeName];
        if (theme.css) {
            this.themeLink = document.createElement('link');
            this.themeLink.rel = 'stylesheet';
            this.themeLink.href = theme.css;
            document.head.appendChild(this.themeLink);
        }

        // Set data attribute on root
        document.documentElement.setAttribute('data-theme', themeName === 'original' ? '' : themeName);

        // Logo动态渐变效果 - body class已在CSS中处理
        if (themeName === 'cyberpunk') {
            document.body.classList.add('cyberpunk-logo');
            document.documentElement.setAttribute('data-theme', 'cyberpunk');
        } else {
            document.body.classList.remove('cyberpunk-logo');
        }

        // Save to localStorage
        if (save) {
            localStorage.setItem('theme', themeName);
        }

        // Update theme switcher UI
        this.updateThemeSwitcherUI();
    },

    updateThemeSwitcherUI() {
        const switcher = document.getElementById('theme-switcher');
        if (!switcher) return;

        const buttons = switcher.querySelectorAll('.theme-btn');
        buttons.forEach(btn => {
            btn.classList.remove('active');
            if (btn.dataset.theme === this.currentTheme) {
                btn.classList.add('active');
            }
        });
    },

    getThemes() {
        return this.themes;
    }
};

// Initialize application
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

async function initializeApp() {
    // Initialize theme
    ThemeManager.init();

    // Load statistics
    await loadStats();

    // Initialize file upload
    initializeUpload();

    // Initialize sidebar
    initializeSidebar();

    // Check for page-specific initialization
    if (typeof initPage === 'function') {
        initPage();
    }
}

// Load sidebar statistics
async function loadStats() {
    console.log('loadStats() called');
    try {
        const response = await fetch('/api/utils/stats');
        console.log('Stats API response:', response.status);
        if (!response.ok) throw new Error('Stats API failed: ' + response.status);
        const stats = await response.json();
        console.log('Stats data:', stats);
        updateStatsUI(stats);
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

function updateStatsUI(stats) {
    const totalEl = document.getElementById('total-count');
    const structureEl = document.getElementById('structure-count');
    const vectorEl = document.getElementById('vector-count');

    if (totalEl) totalEl.textContent = formatNumber(stats.total_count || 0);
    if (structureEl) structureEl.textContent = formatNumber(stats.structure_count || 0);
    if (vectorEl) vectorEl.textContent = formatNumber(stats.vector_count || 0);
}

// File upload handling - pending files list
let pendingFiles = [];

function initializeUpload() {
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('file-input');

    if (!uploadZone || !fileInput) return;

    // Click to upload
    uploadZone.addEventListener('click', (e) => {
        if (e.target !== fileInput && !uploadZone.querySelector('.upload-btn')) return;
    });

    // File input change - add to pending list instead of immediate upload
    fileInput.addEventListener('change', handleFileSelect);

    // Confirm upload button
    const confirmBtn = document.getElementById('confirm-upload-btn');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', () => {
            if (pendingFiles.length > 0) {
                uploadFiles(pendingFiles);
            }
        });
    }

    // Clear files button
    const clearBtn = document.getElementById('clear-files-btn');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            pendingFiles = [];
            updatePendingFilesDisplay();
            // Reset file input
            fileInput.value = '';
        });
    }

    // Drag and drop - add to pending list
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('drag-over');
    });

    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('drag-over');
    });

    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('drag-over');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFilesDrop(files);
        }
    });
}

function handleFileSelect(e) {
    const files = e.target.files;
    if (files.length > 0) {
        addFilesToPending(files);
    }
}

function handleFilesDrop(files) {
    addFilesToPending(files);
}

function addFilesToPending(files) {
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        // Check if file already in pending list
        const exists = pendingFiles.some(f => f.name === file.name && f.size === file.size);
        if (!exists) {
            pendingFiles.push(file);
        }
    }
    updatePendingFilesDisplay();
}

function updatePendingFilesDisplay() {
    const container = document.getElementById('pending-files-container');
    const list = document.getElementById('pending-files-list');

    if (!container || !list) return;

    if (pendingFiles.length > 0) {
        container.style.display = 'block';
        list.innerHTML = '';

        pendingFiles.forEach((file, index) => {
            const item = document.createElement('div');
            item.style.cssText = 'display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; margin-bottom: 4px; background: #e9ecef; border-radius: 4px; font-size: 12px; border: 1px solid #dee2e6;';

            const nameSpan = document.createElement('span');
            nameSpan.textContent = '📄 ' + file.name;
            nameSpan.style.cssText = 'overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; color: #212529; font-weight: 500;';
            nameSpan.title = file.name;

            const removeBtn = document.createElement('button');
            removeBtn.textContent = '✕';
            removeBtn.style.cssText = 'background: none; border: none; color: #dc3545; cursor: pointer; padding: 2px 6px; font-size: 14px; font-weight: bold;';
            removeBtn.title = '移除';
            removeBtn.onclick = () => {
                pendingFiles.splice(index, 1);
                updatePendingFilesDisplay();
            };

            item.appendChild(nameSpan);
            item.appendChild(removeBtn);
            list.appendChild(item);
        });

        // Update confirm button text
        const confirmBtn = document.getElementById('confirm-upload-btn');
        if (confirmBtn) {
            confirmBtn.textContent = `上传 ${pendingFiles.length} 个文件`;
        }
    } else {
        container.style.display = 'none';
    }
}

async function uploadFiles(files) {
    const progressContainer = document.getElementById('upload-progress');
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');
    const logContainer = document.getElementById('upload-log-container');
    const logContent = document.getElementById('upload-logs');

    if (progressContainer) {
        progressContainer.style.display = 'block';
    }
    if (logContainer) {
        logContainer.style.display = 'block';
    }
    if (logContent) {
        logContent.innerHTML = '<div style="color: #818cf8;">📤 正在开始上传...</div>';
    }
    if (progressText) {
        progressText.textContent = '上传中...';
    }
    if (progressFill) {
        progressFill.style.width = '30%';
    }

    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
        formData.append('files[]', files[i]);
    }

    try {
        if (progressFill) {
            progressFill.style.width = '50%';
        }
        if (logContent) {
            logContent.innerHTML += '<div style="color: #818cf8;">⏳ 正在处理文件...</div>';
            logContainer.scrollTop = logContainer.scrollHeight;
        }

        const response = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (progressFill) {
            progressFill.style.width = '80%';
        }

        // Display logs from server
        if (result.logs && logContent) {
            logContent.innerHTML = '';
            result.logs.forEach(log => {
                let color = 'rgba(255,255,255,0.9)';
                if (log.level === 'success') color = '#10b981';
                else if (log.level === 'warning') color = '#f59e0b';
                else if (log.level === 'error') color = '#ef4444';
                else if (log.level === 'info') color = '#818cf8';

                const logLine = document.createElement('div');
                logLine.style.cssText = `color: ${color}; margin: 2px 0; word-break: break-word;`;
                logLine.textContent = `[${log.timestamp}] ${log.message}`;
                logContent.appendChild(logLine);
            });
            // Scroll to bottom
            logContainer.scrollTop = logContainer.scrollHeight;
        }

        if (result.results) {
            let successCount = 0;
            result.results.forEach(r => {
                if (r.success) successCount++;
                else showToast(`${r.filename}: ${r.error}`, 'error');
            });

            if (successCount > 0) {
                showToast(`成功上传 ${successCount} 个文件`, 'success');
                // Refresh data
                if (typeof loadLiterature === 'function') {
                    loadLiterature();
                }
                await loadStats();
            }
        }

        if (progressFill) progressFill.style.width = '100%';
        if (progressText) progressText.textContent = '完成!';

        // Keep logs visible for 5 seconds after completion
        setTimeout(() => {
            if (progressContainer) progressContainer.style.display = 'none';
            if (progressFill) progressFill.style.width = '0%';
            if (progressText) progressText.textContent = '0%';
        }, 5000);

        // Auto-hide logs after 8 seconds
        setTimeout(() => {
            if (logContainer) logContainer.style.display = 'none';
            if (logContent) logContent.innerHTML = '';
        }, 8000);

        // Clear pending files after upload
        pendingFiles = [];
        updatePendingFilesDisplay();
        // Reset file input
        const fileInput = document.getElementById('file-input');
        if (fileInput) fileInput.value = '';

    } catch (error) {
        console.error('Upload failed:', error);
        if (logContent) {
            logContent.innerHTML += `<div style="color: #ef4444;">❌ 上传失败: ${error.message}</div>`;
        }
        showToast('上传失败: ' + error.message, 'error');
    }
}

// Sidebar interactions
function initializeSidebar() {
    // Mobile sidebar toggle could be added here
}

// Tab switching (for pages with multiple tabs)
function switchTab(tabId) {
    // Update tab buttons
    document.querySelectorAll('.tabs .tab-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.tab === tabId) {
            btn.classList.add('active');
        }
    });

    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });

    const tabContent = document.getElementById(`tab-${tabId}`);
    if (tabContent) {
        tabContent.classList.add('active');
    }

    // Update filters based on tab
    if (tabId === 'has-structure') {
        AppState.filters.has_cryoem = 'true';
    } else {
        delete AppState.filters.has_cryoem;
    }

    // Reload content
    if (typeof loadLiterature === 'function') {
        loadLiterature();
    }
}

// Detail page tab switching
function switchDetailTab(tabId) {
    document.querySelectorAll('.detail-tabs .tab-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.tab === tabId) {
            btn.classList.add('active');
        }
    });

    document.querySelectorAll('.detail-page > .tab-content').forEach(content => {
        content.classList.remove('active');
    });

    const tabContent = document.getElementById(`tab-${tabId}`);
    if (tabContent) {
        tabContent.classList.add('active');
    }
}

// Clear filters
function clearFilters() {
    document.getElementById('search-input').value = '';
    document.getElementById('filter-year-from').value = '';
    document.getElementById('filter-year-to').value = '';
    document.getElementById('filter-status').value = '';
    document.getElementById('filter-has-structure').checked = false;

    AppState.filters = {};
    AppState.currentPage = 1;

    if (typeof loadLiterature === 'function') {
        loadLiterature();
    }
}

// Page navigation
function changePage(delta) {
    const newPage = AppState.currentPage + delta;
    if (newPage >= 1 && newPage <= AppState.totalPages) {
        AppState.currentPage = newPage;
        if (typeof loadLiterature === 'function') {
            loadLiterature();
        }
        scrollToElement(document.querySelector('.literature-grid') || document.body);
    }
}

// Update pagination UI
function updatePagination() {
    const pagination = document.getElementById('pagination');
    const pageInfo = document.getElementById('page-info');
    const prevBtn = document.getElementById('prev-page');
    const nextBtn = document.getElementById('next-page');

    if (!pagination) return;

    if (AppState.totalPages <= 1) {
        pagination.style.display = 'none';
        return;
    }

    pagination.style.display = 'flex';
    if (pageInfo) {
        pageInfo.textContent = `第 ${AppState.currentPage} 页 / 共 ${AppState.totalPages} 页`;
    }
    if (prevBtn) prevBtn.disabled = AppState.currentPage === 1;
    if (nextBtn) nextBtn.disabled = AppState.currentPage === AppState.totalPages;
}

// Get status badge HTML
function getStatusBadgeHTML(status, isVertical = false) {
    const statusClass = `status-${status}`;
    const verticalClass = isVertical ? 'status-vertical' : '';
    const statusText = {
        'uploaded': '已上传',
        'parsing': '解析中',
        'parsed': '已解析',
        'indexed': '已索引',
        'error': '错误'
    };
    return `<span class="status-badge ${statusClass} ${verticalClass}">${statusText[status] || status}</span>`;
}

// Get structure badges HTML
function getStructureBadgesHTML(cryoem_targets) {
    if (!cryoem_targets) return '';

    // Handle string JSON
    if (typeof cryoem_targets === 'string') {
        try {
            cryoem_targets = JSON.parse(cryoem_targets);
        } catch (e) {
            return '';
        }
    }

    if (typeof cryoem_targets !== 'object') return '';

    let html = '<div class="structure-badges">';
    if (cryoem_targets.pdb_ids && cryoem_targets.pdb_ids.length > 0) {
        html += `<span class="badge pdb">PDB: ${cryoem_targets.pdb_ids.slice(0, 2).join(', ').toUpperCase()}${cryoem_targets.pdb_ids.length > 2 ? '...' : ''}</span>`;
    }
    if (cryoem_targets.emdb_ids && cryoem_targets.emdb_ids.length > 0) {
        html += `<span class="badge emdb">EMDB: ${cryoem_targets.emdb_ids.slice(0, 2).join(', ').toUpperCase()}${cryoem_targets.emdb_ids.length > 2 ? '...' : ''}</span>`;
    }
    html += '</div>';
    return html;
}

// View literature detail
function viewLiterature(id) {
    window.location.href = `/literature/${id}`;
}

// Delete literature
async function deleteLiterature(id) {
    if (!confirm('确定要删除这篇文献吗？此操作不可恢复。')) {
        return;
    }

    try {
        const result = await apiRequest(`/literature/${id}`, {
            method: 'DELETE'
        });

        if (result.success) {
            showToast('删除成功', 'success');
            // Check if we're on the detail page (has .detail-page class)
            const detailPage = document.querySelector('.detail-page');
            if (detailPage) {
                // Redirect to home page
                window.location.href = '/';
                return;
            }
            // Refresh list
            if (typeof loadLiterature === 'function') {
                loadLiterature();
            }
            await loadStats();
        } else {
            showToast('删除失败', 'error');
        }
    } catch (error) {
        showToast('删除失败: ' + error.message, 'error');
    }
}

// Delete structure
async function deleteStructure(structureId) {
    if (!confirm('确定要删除这个结构吗？此操作不可恢复。')) {
        return;
    }

    try {
        const result = await apiRequest(`/structure/${structureId}`, {
            method: 'DELETE'
        });

        if (result.success) {
            showToast('删除成功', 'success');
            // Go back to previous page
            history.back();
        } else {
            showToast('删除失败', 'error');
        }
    } catch (error) {
        showToast('删除失败: ' + error.message, 'error');
    }
}

// Export for use in other scripts
window.AppState = AppState;
window.showToast = showToast;
window.debounce = debounce;
window.apiRequest = apiRequest;
window.formatNumber = formatNumber;
window.formatDate = formatDate;
window.switchTab = switchTab;
window.changePage = changePage;
window.viewLiterature = viewLiterature;
window.deleteLiterature = deleteLiterature;
window.deleteStructure = deleteStructure;
window.loadStats = loadStats;
window.ThemeManager = ThemeManager;

// Rebuild index function
function rebuildIndex() {
    // 创建确认弹窗
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = `
        <div class="confirm-dialog">
            <h3>重建索引</h3>
            <p>确定要重建索引吗？这可能需要几分钟时间。</p>
            <div class="confirm-buttons">
                <button class="btn-cancel">取消</button>
                <button class="btn-confirm">确定</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    // 绑定事件
    const cancelBtn = overlay.querySelector('.btn-cancel');
    const confirmBtn = overlay.querySelector('.btn-confirm');

    const closeDialog = () => overlay.remove();

    cancelBtn.onclick = closeDialog;
    confirmBtn.onclick = async () => {
        closeDialog();
        try {
            const response = await fetch('/api/literature/index/rebuild', { method: 'POST' });
            const data = await response.json();
            if (data.success) {
                showToast('索引重建任务已在后台启动', 'success');
            } else {
                showToast('启动失败: ' + (data.error || '未知错误'), 'error');
            }
        } catch (e) {
            showToast('请求失败: ' + e.message, 'error');
        }
    };

    // 点击遮罩关闭
    overlay.onclick = (e) => {
        if (e.target === overlay) closeDialog();
    };
}

window.rebuildIndex = rebuildIndex;

// Extract full text function
async function extractFullText() {
    if (!confirm('确定要从所有PDF中提取完整文本吗？这将提取全文用于RAG分块。')) return;

    try {
        const response = await fetch('/api/literature/extract-fulltext', { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            showToast('全文提取任务已在后台启动', 'success');
            startFulltextProgressPolling();
        } else {
            showToast('启动失败: ' + (data.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('请求失败: ' + e.message, 'error');
    }
}

window.extractFullText = extractFullText;

// Fulltext progress polling
let fulltextPollInterval = null;

function startFulltextProgressPolling() {
    // 显示进度区域
    const progressEl = document.getElementById('fulltext-progress');
    if (progressEl) progressEl.style.display = 'block';

    // 立即查询一次
    checkFulltextProgress();

    // 每2秒轮询一次
    if (fulltextPollInterval) clearInterval(fulltextPollInterval);
    fulltextPollInterval = setInterval(checkFulltextProgress, 2000);
}

async function checkFulltextProgress() {
    try {
        const response = await fetch('/api/literature/extract-fulltext/progress');
        const data = await response.json();

        const progressFill = document.getElementById('fulltext-progress-fill');
        const progressPercent = document.getElementById('fulltext-progress-percent');
        const progressStage = document.getElementById('fulltext-progress-stage');
        const progressMessage = document.getElementById('fulltext-progress-message');
        const progressEl = document.getElementById('fulltext-progress');

        if (progressFill) progressFill.style.width = data.progress_pct + '%';
        if (progressPercent) progressPercent.textContent = data.progress_pct + '%';
        if (progressStage) progressStage.textContent = data.status === 'running' ? '提取全文中...' : '完成';
        if (progressMessage) progressMessage.textContent = data.message || '';

        if (data.status === 'completed') {
            clearInterval(fulltextPollInterval);
            showToast('全文提取完成！', 'success');
            setTimeout(() => {
                if (progressEl) progressEl.style.display = 'none';
            }, 3000);
        } else if (data.status === 'error') {
            clearInterval(fulltextPollInterval);
            showToast('提取失败: ' + data.message, 'error');
            setTimeout(() => {
                if (progressEl) progressEl.style.display = 'none';
            }, 3000);
        }
    } catch (e) {
        console.error('Fulltext progress check failed:', e);
    }
}

// Progress polling variables
let progressPollInterval = null;

function startProgressPolling() {
    // 显示进度区域
    const progressEl = document.getElementById('sidebar-progress');
    if (progressEl) progressEl.style.display = 'block';

    // 立即查询一次
    checkIndexProgress();

    // 每2秒轮询一次
    if (progressPollInterval) clearInterval(progressPollInterval);
    progressPollInterval = setInterval(checkIndexProgress, 2000);
}

async function checkIndexProgress() {
    try {
        const response = await fetch('/api/index/progress');
        const data = await response.json();

        const progressFill = document.getElementById('index-progress-fill');
        const progressText = document.getElementById('index-progress-text');
        const progressEl = document.getElementById('sidebar-progress');

        if (progressFill) progressFill.style.width = data.progress_pct + '%';
        if (progressText) {
            if (data.status === 'running') {
                progressText.textContent = `${data.message} (${data.current}/${data.total})`;
            } else if (data.status === 'completed') {
                progressText.textContent = '索引重建完成！';
                showToast('索引重建完成', 'success');
                // 停止轮询
                if (progressPollInterval) {
                    clearInterval(progressPollInterval);
                    progressPollInterval = null;
                }
                setTimeout(() => {
                    if (progressEl) progressEl.style.display = 'none';
                }, 3000);
            } else if (data.status === 'error') {
                progressText.textContent = '索引重建失败: ' + data.message;
                showToast('索引重建失败: ' + data.message, 'error');
                if (progressPollInterval) {
                    clearInterval(progressPollInterval);
                    progressPollInterval = null;
                }
            } else {
                progressText.textContent = data.message || '准备中...';
            }
        }
    } catch (e) {
        console.error('Failed to check progress:', e);
    }
}

// Toggle sidebar settings panel
function toggleSettings() {
    const settingsPanel = document.querySelector('.sidebar-settings');
    if (settingsPanel) {
        settingsPanel.classList.toggle('active');
    }
}

// Make checkIndexProgress globally available
window.checkIndexProgress = checkIndexProgress;
window.startProgressPolling = startProgressPolling;
window.toggleSettings = toggleSettings;
