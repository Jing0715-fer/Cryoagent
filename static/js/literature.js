/* ============================================
   CryoAgent Pro - Literature List Page
   ============================================ */

// Initialize literature page
function initPage() {
    loadLiterature();

    // Search input debounce
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(() => {
            AppState.currentPage = 1;
            loadLiterature();
        }, 300));
    }

    // Filter changes
    document.querySelectorAll('.filter-row select, .filter-row input').forEach(el => {
        el.addEventListener('change', () => {
            AppState.currentPage = 1;
            loadLiterature();
        });
    });
}

// Load literature list
async function loadLiterature() {
    const grid = document.getElementById('literature-grid') || document.getElementById('literature-list');
    if (!grid) return;

    showLoading(grid);
    AppState.isLoading = true;

    // Build query params
    const params = new URLSearchParams();
    params.set('page', AppState.currentPage);
    params.set('per_page', AppState.perPage);

    // Search query
    const searchInput = document.getElementById('search-input');
    if (searchInput && searchInput.value) {
        params.set('query', searchInput.value);
    }

    // Filters
    const yearFrom = document.getElementById('filter-year-from');
    if (yearFrom && yearFrom.value) params.set('year_from', yearFrom.value);

    const yearTo = document.getElementById('filter-year-to');
    if (yearTo && yearTo.value) params.set('year_to', yearTo.value);

    const status = document.getElementById('filter-status');
    if (status && status.value) params.set('status', status.value);

    const hasStructure = document.getElementById('filter-has-structure');
    if (hasStructure && hasStructure.checked) params.set('has_cryoem', 'true');

    try {
        const data = await apiRequest(`/literature?${params.toString()}`);
        renderLiterature(data.items);

        AppState.totalItems = data.total;
        AppState.totalPages = data.pages;
        updatePagination();

    } catch (error) {
        console.error('Failed to load literature:', error);
        grid.innerHTML = `
            <div class="empty-state">
                <p>加载失败: ${error.message}</p>
                <button class="btn btn-primary" onclick="loadLiterature()">重试</button>
            </div>
        `;
    } finally {
        AppState.isLoading = false;
    }
}

// Render literature grid
function renderLiterature(items) {
    const grid = document.getElementById('literature-grid') || document.getElementById('literature-list');
    if (!grid) return;

    if (!items || items.length === 0) {
        grid.innerHTML = `
            <div class="empty-state">
                <p>暂无文献</p>
                <p style="font-size: 12px; color: #999; margin-top: 10px;">上传 PDF 文件开始构建文献库</p>
            </div>
        `;
        return;
    }

    // Use list view for literature list page
    const isListView = grid.id === 'literature-list';

    if (isListView) {
        grid.innerHTML = items.map(item => `
            <div class="literature-list-item" onclick="viewLiterature(${item.id})">
                <div class="list-item-icon">&#128196;</div>
                <div class="list-item-content">
                    <div class="list-item-title">${escapeHtml(item.title)}</div>
                    <div class="list-item-meta">
                        ${item.authors ? truncateText(item.authors, 50) : 'Unknown'} &bull;
                        ${item.year || 'N/A'} &bull;
                        ${item.journal ? truncateText(item.journal, 30) : 'Unknown'}
                    </div>
                    ${getStructureBadgesHTML(item.cryoem_targets)}
                </div>
                <div class="list-item-actions" onclick="event.stopPropagation()">
                    ${getStatusBadgeHTML(item.status, true)}
                    <button class="action-btn" onclick="viewLiterature(${item.id})">查看</button>
                </div>
            </div>
        `).join('');
    } else {
        // Grid view
        grid.innerHTML = items.map(item => `
            <div class="literature-card" data-id="${item.id}" onclick="viewLiterature(${item.id})">
                <div class="card-header">
                    <h3 class="card-title">${escapeHtml(truncateText(item.title, 80))}</h3>
                    ${getStatusBadgeHTML(item.status, true)}
                </div>
                <div class="card-content">
                    <p class="authors">${escapeHtml(truncateText(item.authors, 100)) || 'Unknown'}</p>
                    <div class="meta-info">
                        <span class="meta-item">
                            <span class="meta-icon">&#128197;</span>
                            ${item.year || 'N/A'}
                        </span>
                        <span class="meta-item">
                            <span class="meta-icon">&#128212;</span>
                            ${truncateText(item.journal, 20) || 'Unknown'}
                        </span>
                    </div>
                    ${getStructureBadgesHTML(item.cryoem_targets)}
                </div>
                <div class="card-footer">
                    <span class="date">${formatDate(item.publication_date) || 'Recently added'}</span>
                    <div class="card-actions">
                        <button class="action-btn" onclick="event.stopPropagation(); viewLiterature(${item.id})">查看</button>
                        <button class="action-btn danger" onclick="event.stopPropagation(); deleteLiterature(${item.id})">删除</button>
                    </div>
                </div>
            </div>
        `).join('');
    }
}

// Search function (for search bar)
function performSearch() {
    AppState.currentPage = 1;
    loadLiterature();
}

// Search function triggered by search button
function searchLiterature() {
    AppState.currentPage = 1;
    loadLiterature();
}

// Clear all filters
function clearFilters() {
    const searchInput = document.getElementById('search-input');
    const yearFrom = document.getElementById('filter-year-from');
    const yearTo = document.getElementById('filter-year-to');
    const status = document.getElementById('filter-status');
    const hasStructure = document.getElementById('filter-has-structure');

    if (searchInput) searchInput.value = '';
    if (yearFrom) yearFrom.value = '';
    if (yearTo) yearTo.value = '';
    if (status) status.value = '';
    if (hasStructure) hasStructure.checked = false;

    AppState.currentPage = 1;
    loadLiterature();
}

// Make functions globally available
window.initPage = initPage;
window.loadLiterature = loadLiterature;
window.renderLiterature = renderLiterature;
window.performSearch = performSearch;
