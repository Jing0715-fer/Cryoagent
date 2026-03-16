<template>
  <div class="literature-view">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">文献管理</h1>
        <p class="page-subtitle">管理您的冷冻电镜文献库</p>
      </div>
      <div class="page-actions">
        <div class="search-box">
          <MagnifyingGlassIcon class="search-icon" />
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索文献标题、作者、关键词..."
            class="search-input"
            @keyup.enter="handleSearch"
          />
        </div>
        <button @click="showUpload = true" class="btn-primary">
          <PlusIcon class="w-4 h-4" />
          添加文献
        </button>
      </div>
    </div>

    <!-- Filters -->
    <div class="filters">
      <div class="filter-group">
        <label class="filter-label">年份</label>
        <select v-model="filters.year" class="filter-select" @change="handleFilter">
          <option value="">全部</option>
          <option v-for="year in availableYears" :key="year" :value="year">{{ year }}</option>
        </select>
      </div>

      <div class="filter-group">
        <label class="filter-label">期刊</label>
        <select v-model="filters.journal" class="filter-select" @change="handleFilter">
          <option value="">全部</option>
          <option v-for="journal in availableJournals" :key="journal" :value="journal">{{ journal }}</option>
        </select>
      </div>

      <div class="filter-group">
        <label class="filter-label">类型</label>
        <select v-model="filters.has_pdf" class="filter-select" @change="handleFilter">
          <option value="">全部</option>
          <option :value="true">有PDF</option>
          <option :value="false">无PDF</option>
        </select>
      </div>

      <button v-if="hasActiveFilters" @click="clearFilters" class="filter-clear">
        <XMarkIcon class="w-4 h-4" />
        清除筛选
      </button>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="literature.length === 0" class="empty-state">
      <BookOpenIcon class="w-16 h-16 text-gray-400" />
      <h3>暂无文献</h3>
      <p>开始上传您的第一篇文献吧</p>
      <button @click="showUpload = true" class="btn-primary mt-4">
        <PlusIcon class="w-4 h-4" />
        添加文献
      </button>
    </div>

    <!-- Literature List -->
    <div v-else class="literature-list">
      <div
        v-for="item in literature"
        :key="item.id"
        class="literature-card"
        @click="viewDetail(item.id)"
      >
        <div class="literature-header">
          <h3 class="literature-title">{{ item.title }}</h3>
          <div class="literature-badges">
            <span v-if="item.has_pdf" class="badge badge-pdf">PDF</span>
            <span v-if="item.has_structure" class="badge badge-structure">结构</span>
            <span v-if="item.year" class="badge badge-year">{{ item.year }}</span>
          </div>
        </div>

        <div class="literature-meta">
          <span v-if="item.authors" class="meta-item">
            <UsersIcon class="w-4 h-4" />
            {{ formatAuthors(item.authors) }}
          </span>
          <span v-if="item.journal" class="meta-item">
            <NewspaperIcon class="w-4 h-4" />
            {{ item.journal }}
          </span>
        </div>

        <p v-if="item.abstract" class="literature-abstract">
          {{ truncateAbstract(item.abstract) }}
        </p>

        <div class="literature-footer">
          <div class="literature-ids">
            <span v-if="item.doi" class="id-tag">DOI: {{ item.doi }}</span>
            <span v-if="item.pmid" class="id-tag">PMID: {{ item.pmid }}</span>
          </div>
          <div class="literature-actions">
            <button
              v-if="item.has_pdf"
              @click.stop="viewPdf(item.id)"
              class="action-btn"
              title="查看PDF"
            >
              <EyeIcon class="w-4 h-4" />
            </button>
            <button
              @click.stop="confirmDelete(item)"
              class="action-btn text-red-500 hover:text-red-700"
              title="删除"
            >
              <TrashIcon class="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <Pagination
      v-if="totalPages > 1"
      :current-page="currentPage"
      :total-pages="totalPages"
      @change="handlePageChange"
    />

    <!-- Upload Modal -->
    <Teleport to="body">
      <div v-if="showUpload" class="modal-overlay" @click.self="showUpload = false">
        <div class="modal">
          <div class="modal-header">
            <h3>添加文献</h3>
            <button @click="showUpload = false" class="modal-close">
              <XMarkIcon class="w-5 h-5" />
            </button>
          </div>
          <div class="modal-body">
            <UploadZone />
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Delete Confirmation -->
    <Teleport to="body">
      <div v-if="itemToDelete" class="modal-overlay" @click.self="itemToDelete = null">
        <div class="modal modal-sm">
          <div class="modal-header">
            <h3>确认删除</h3>
          </div>
          <div class="modal-body">
            <p>确定要删除文献《{{ itemToDelete.title }}》吗？此操作不可撤销。</p>
          </div>
          <div class="modal-footer">
            <button @click="itemToDelete = null" class="btn-secondary">取消</button>
            <button @click="deleteItem" class="btn-danger">删除</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  MagnifyingGlassIcon,
  PlusIcon,
  XMarkIcon,
  BookOpenIcon,
  UsersIcon,
  NewspaperIcon,
  EyeIcon,
  TrashIcon,
} from '@heroicons/vue/24/outline'
import Pagination from '@/components/common/Pagination.vue'
import UploadZone from '@/components/common/UploadZone.vue'
import { literatureApi, type Literature } from '@/api/literature'
import { useToastStore } from '@/stores/toast'

const router = useRouter()
const toast = useToastStore()

// State
const loading = ref(false)
const literature = ref<Literature[]>([])
const currentPage = ref(1)
const totalPages = ref(1)
const totalItems = ref(0)
const searchQuery = ref('')
const showUpload = ref(false)
const itemToDelete = ref<Literature | null>(null)
const availableYears = ref<number[]>([])
const availableJournals = ref<string[]>([])

const filters = ref({
  year: '',
  journal: '',
  has_pdf: '',
})

const hasActiveFilters = computed(() => {
  return filters.value.year || filters.value.journal || filters.value.has_pdf !== ''
})

// Methods
const fetchLiterature = async () => {
  loading.value = true
  try {
    const response = await literatureApi.getList(currentPage.value, 20, {
      search: searchQuery.value || undefined,
      year: filters.value.year ? parseInt(filters.value.year) : undefined,
      journal: filters.value.journal || undefined,
      has_pdf: filters.value.has_pdf !== '' ? filters.value.has_pdf === 'true' : undefined,
    })
    literature.value = response.items
    totalPages.value = response.total_pages
    totalItems.value = response.total
  } catch (error) {
    toast.error('加载文献失败')
    console.error(error)
  } finally {
    loading.value = false
  }
}

const fetchFilters = async () => {
  try {
    const response = await literatureApi.getFilters()
    availableYears.value = response.years.sort((a, b) => b - a)
    availableJournals.value = response.journals
  } catch (error) {
    console.error('Failed to fetch filters:', error)
  }
}

const handleSearch = () => {
  currentPage.value = 1
  fetchLiterature()
}

const handleFilter = () => {
  currentPage.value = 1
  fetchLiterature()
}

const clearFilters = () => {
  filters.value = { year: '', journal: '', has_pdf: '' }
  handleFilter()
}

const handlePageChange = (page: number) => {
  currentPage.value = page
  fetchLiterature()
}

const viewDetail = (id: number) => {
  router.push(`/literature/${id}`)
}

const viewPdf = (id: number) => {
  window.open(literatureApi.getPdfUrl(id), '_blank')
}

const confirmDelete = (item: Literature) => {
  itemToDelete.value = item
}

const deleteItem = async () => {
  if (!itemToDelete.value) return

  try {
    await literatureApi.delete(itemToDelete.value.id)
    toast.success('文献已删除')
    fetchLiterature()
  } catch (error) {
    toast.error('删除失败')
  } finally {
    itemToDelete.value = null
  }
}

const formatAuthors = (authors: string) => {
  const list = authors.split(',').map(a => a.trim())
  if (list.length <= 2) return list.join(', ')
  return `${list[0]}, ${list[1]} 等`
}

const truncateAbstract = (abstract: string, maxLength = 200) => {
  if (abstract.length <= maxLength) return abstract
  return abstract.slice(0, maxLength) + '...'
}

// Watch for search query changes with debounce
let searchTimeout: ReturnType<typeof setTimeout>
watch(searchQuery, () => {
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    handleSearch()
  }, 300)
})

onMounted(() => {
  fetchLiterature()
  fetchFilters()
})
</script>

<style scoped>
.literature-view {
  @apply space-y-6;
}

.page-header {
  @apply flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4;
}

.page-title {
  @apply text-2xl font-bold text-gray-900 dark:text-white;
}

.page-subtitle {
  @apply text-gray-500 dark:text-gray-400;
}

.page-actions {
  @apply flex items-center gap-3;
}

.search-box {
  @apply relative;
}

.search-icon {
  @apply absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400;
}

.search-input {
  @apply w-64 pl-10 pr-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600;
  @apply bg-white dark:bg-gray-800 text-gray-900 dark:text-white;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500;
}

/* Filters */
.filters {
  @apply flex flex-wrap items-center gap-4 pb-4 border-b border-gray-200 dark:border-gray-700;
}

.filter-group {
  @apply flex items-center gap-2;
}

.filter-label {
  @apply text-sm font-medium text-gray-700 dark:text-gray-300;
}

.filter-select {
  @apply px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600;
  @apply bg-white dark:bg-gray-800 text-sm;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500;
}

.filter-clear {
  @apply flex items-center gap-1 text-sm text-red-600 hover:text-red-700;
  @apply dark:text-red-400 dark:hover:text-red-300;
}

/* Loading & Empty States */
.loading-state,
.empty-state {
  @apply flex flex-col items-center justify-center py-16 text-gray-500 dark:text-gray-400;
}

.spinner {
  @apply w-8 h-8 border-4 border-primary-200 border-t-primary-600 rounded-full;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.empty-state h3 {
  @apply text-lg font-medium text-gray-900 dark:text-white mt-4;
}

/* Literature List */
.literature-list {
  @apply space-y-4;
}

.literature-card {
  @apply bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700;
  @apply p-5 cursor-pointer;
  @apply hover:shadow-md hover:border-primary-300 dark:hover:border-primary-700;
  @apply transition-all duration-200;
}

.literature-header {
  @apply flex items-start justify-between gap-4 mb-3;
}

.literature-title {
  @apply text-lg font-semibold text-gray-900 dark:text-white flex-1;
  @apply hover:text-primary-600 dark:hover:text-primary-400;
}

.literature-badges {
  @apply flex items-center gap-2;
}

.badge {
  @apply px-2 py-0.5 text-xs font-medium rounded-full;
}

.badge-pdf {
  @apply bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400;
}

.badge-structure {
  @apply bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400;
}

.badge-year {
  @apply bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300;
}

.literature-meta {
  @apply flex flex-wrap items-center gap-4 mb-3 text-sm text-gray-600 dark:text-gray-400;
}

.meta-item {
  @apply flex items-center gap-1;
}

.literature-abstract {
  @apply text-sm text-gray-600 dark:text-gray-400 mb-4 line-clamp-2;
}

.literature-footer {
  @apply flex items-center justify-between pt-3 border-t border-gray-100 dark:border-gray-700;
}

.literature-ids {
  @apply flex items-center gap-3 text-xs text-gray-500 dark:text-gray-500;
}

.id-tag {
  @apply px-2 py-1 bg-gray-100 dark:bg-gray-700 rounded;
}

.literature-actions {
  @apply flex items-center gap-2;
}

.action-btn {
  @apply p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors;
}

/* Modal */
.modal-overlay {
  @apply fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4;
}

.modal {
  @apply bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-auto;
}

.modal-sm {
  @apply max-w-md;
}

.modal-header {
  @apply flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700;
}

.modal-header h3 {
  @apply text-lg font-semibold text-gray-900 dark:text-white;
}

.modal-close {
  @apply p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700;
}

.modal-body {
  @apply p-4;
}

.modal-footer {
  @apply flex items-center justify-end gap-3 p-4 border-t border-gray-200 dark:border-gray-700;
}
</style>
