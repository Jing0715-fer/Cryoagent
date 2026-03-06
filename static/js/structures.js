/* ============================================
   CryoAgent Pro - Structures Page (Enhanced)
   ============================================ */

let structuresPage = 1;
const structuresPerPage = 48;  // 分页显示，每页48个

// Advanced search configuration
const searchFields = {
    title: { weight: 1.0, label: '标题' },
    authors: { weight: 0.8, label: '作者' },
    pdb_id: { weight: 2.0, label: 'PDB ID' },
    journal: { weight: 0.6, label: '期刊' },
    gene: { weight: 1.2, label: '基因' },
    organism: { weight: 0.7, label: '物种' }
};

// Initialize structures page
function initPage() {
    loadStructures();

    // Search input with debounce
    const searchInput = document.getElementById('structure-search');
    if (searchInput) {
        let debounceTimer;
        searchInput.addEventListener('input', function(e) {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                structuresPage = 1;
                loadStructures();
            }, 300);
        });
        searchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                structuresPage = 1;
                loadStructures();
            }
        });
    }

    // Filter checkboxes
    document.querySelectorAll('.filter-row input[type="checkbox"]').forEach(cb => {
        cb.addEventListener('change', () => {
            structuresPage = 1;
            loadStructures();
        });
    });

    // Load initial structure list for comparison dropdown
    loadStructureList();
}

// Load structures with advanced search and pagination
async function loadStructures() {
    const grid = document.getElementById('structures-grid');
    if (!grid) return;

    showLoading(grid);

    const searchInput = document.getElementById('structure-search');
    const query = searchInput?.value.trim() || '';

    try {
        const data = await apiRequest('/structure/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: query,
                limit: structuresPerPage,
                page: structuresPage
            })
        });

        renderStructures(data.structures || []);
        renderPagination(data.page, data.total_pages, data.total);

    } catch (error) {
        console.error('Failed to load structures:', error);
        grid.innerHTML = `
            <div class="empty-state">
                <p>加载失败: ${error.message}</p>
                <button class="btn btn-primary" onclick="loadStructures()">重试</button>
            </div>
        `;
    }
}

// Render pagination controls
function renderPagination(currentPage, totalPages, total) {
    const container = document.getElementById('pagination-container');
    if (!container) return;

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    let html = `<div class="pagination-info">共 ${total} 个结构</div>`;
    html += '<div class="pagination">';

    // Previous button
    html += `<button class="page-btn" ${currentPage === 1 ? 'disabled' : ''} onclick="goToPage(${currentPage - 1})">« 上一页</button>`;

    // Page numbers
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);

    if (startPage > 1) {
        html += `<button class="page-btn" onclick="goToPage(1)">1</button>`;
        if (startPage > 2) html += `<span class="page-ellipsis">...</span>`;
    }

    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }

    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += `<span class="page-ellipsis">...</span>`;
        html += `<button class="page-btn" onclick="goToPage(${totalPages})">${totalPages}</button>`;
    }

    // Next button
    html += `<button class="page-btn" ${currentPage === totalPages ? 'disabled' : ''} onclick="goToPage(${currentPage + 1})">下一页 »</button>`;

    html += '</div>';
    container.innerHTML = html;
}

// Navigate to specific page
function goToPage(page) {
    structuresPage = page;
    loadStructures();
    // Scroll to top of grid
    const grid = document.getElementById('structures-grid');
    if (grid) grid.scrollIntoView({ behavior: 'smooth' });
}

// Load structure list for comparison dropdown
async function loadStructureList() {
    try {
        const data = await apiRequest('/structure/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: '',
                limit: 200  // 获取所有结构用于下拉列表
            })
        });

        const structures = data.structures || [];

        // Populate comparison dropdowns
        const select1 = document.getElementById('compare-structure-1');
        const select2 = document.getElementById('compare-structure-2');

        if (select1) {
            select1.innerHTML = '<option value="">选择结构...</option>' +
                structures.map(s => `<option value="${s.id}">${s.id} - ${truncateText(s.title || '', 40)}</option>`).join('');
        }
        if (select2) {
            select2.innerHTML = '<option value="">选择结构...</option>' +
                structures.map(s => `<option value="${s.id}">${s.id} - ${truncateText(s.title || '', 40)}</option>`).join('');
        }

    } catch (error) {
        console.error('Failed to load structure list:', error);
    }
}

// Render structures grid
function renderStructures(structures) {
    const grid = document.getElementById('structures-grid');
    if (!grid) return;

    // Filter by type
    const showPdb = document.getElementById('filter-pdb')?.checked ?? true;
    const showEmdb = document.getElementById('filter-emdb')?.checked ?? true;
    const showAf = document.getElementById('filter-af')?.checked ?? true;

    const filtered = structures.filter(s => {
        const type = (s.type || '').toUpperCase();
        if (type === 'PDB' && !showPdb) return false;
        if (type === 'EMDB' && !showEmdb) return false;
        if (type === 'ALPHAFOLD' && !showAf) return false;
        return true;
    });

    if (filtered.length === 0) {
        grid.innerHTML = `
            <div class="empty-state">
                <p>暂无结构数据</p>
                ${document.getElementById('structure-search')?.value ?
                    '<p style="font-size: 12px; color: #999;">尝试其他搜索词</p>' : ''}
            </div>
        `;
        return;
    }

    grid.innerHTML = filtered.map(s => `
        <a href="/structure/${s.id}" class="structure-card" data-id="${s.id}">
            <div class="card-header">
                <span class="structure-type-badge type-${(s.type || 'pdb').toLowerCase()}">${(s.type || 'PDB').toUpperCase()}</span>
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
            </div>
        </a>
    `).join('');
}

// Search structures with field-specific weighting
function searchStructures() {
    structuresPage = 1;
    loadStructures();
}

// View structure detail (modal)
async function viewStructureDetail(structureId) {
    const modal = document.getElementById('structure-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');

    if (!modal || !modalBody) return;

    modalTitle.textContent = structureId;
    modalBody.innerHTML = '<p class="loading-state">加载中...</p>';
    modal.classList.add('active');

    try {
        const data = await apiRequest(`/structure/${structureId}`);

        modalBody.innerHTML = `
            <div class="info-card">
                <div class="card-header">
                    <h3 class="card-title">${data.id}</h3>
                    <span class="structure-type-badge type-${(data.type || 'pdb').toLowerCase()}">${(data.type || 'PDB').toUpperCase()}</span>
                </div>
                <div class="card-content">
                    <div class="info-grid">
                        <div class="info-item full-width">
                            <label>标题</label>
                            <p>${escapeHtml(data.title || 'N/A')}</p>
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
                            <label>表达系统</label>
                            <p>${data.expression_system || 'N/A'}</p>
                        </div>
                        <div class="info-item">
                            <label>基因</label>
                            <p>${data.gene || 'N/A'}</p>
                        </div>
                        <div class="info-item full-width">
                            <label>蛋白质名称</label>
                            <p>${data.protein_name || 'N/A'}</p>
                        </div>
                        <div class="info-item">
                            <label>引用次数</label>
                            <p>${data.citation_count || 0}</p>
                        </div>
                        <div class="info-item full-width">
                            <label>作者</label>
                            <p>${escapeHtml(data.authors?.join(', ') || 'N/A')}</p>
                        </div>
                        ${data.related_ids && data.related_ids.length > 0 ? `
                            <div class="info-item full-width">
                                <label>相关ID</label>
                                <p>${data.related_ids.join(', ')}</p>
                            </div>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;

    } catch (error) {
        modalBody.innerHTML = `<p class="empty-state">加载失败: ${error.message}</p>`;
    }
}

// Close modal
function closeModal() {
    const modal = document.getElementById('structure-modal');
    if (modal) modal.classList.remove('active');
}

// Refresh all structure metadata
async function refreshAllMetadata() {
    const progressDiv = document.getElementById('refresh-progress');
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');

    if (!progressDiv || !progressFill || !progressText) return;

    if (!confirm('确定要刷新所有结构的元数据吗？这可能需要几分钟时间。')) {
        return;
    }

    progressDiv.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.textContent = '正在开始刷新...';

    try {
        const response = await fetch('/api/structure/refresh/all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const data = await response.json();

        if (data.success) {
            progressFill.style.width = '100%';
            progressText.textContent = data.message;
            alert('刷新完成！请刷新页面查看更新后的元数据。');
            setTimeout(() => {
                progressDiv.style.display = 'none';
                loadStructures();
            }, 2000);
        } else {
            throw new Error(data.error || '刷新失败');
        }

    } catch (error) {
        progressText.textContent = '刷新失败: ' + error.message;
        alert('刷新失败: ' + error.message);
    }
}

// Make functions globally available
window.initPage = initPage;
window.loadStructures = loadStructures;
window.renderStructures = renderStructures;
window.searchStructures = searchStructures;
window.viewStructureDetail = viewStructureDetail;
window.closeModal = closeModal;
window.loadStructureList = loadStructureList;
window.refreshAllMetadata = refreshAllMetadata;
