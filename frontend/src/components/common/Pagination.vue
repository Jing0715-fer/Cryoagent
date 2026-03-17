<template>
  <div v-if="totalPages > 1" class="pagination">
    <!-- Previous -->
    <button
      :disabled="currentPage <= 1"
      @click="goToPage(currentPage - 1)"
      class="pagination-btn"
      aria-label="上一页"
    >
      <ChevronLeftIcon class="w-5 h-5" />
    </button>

    <!-- First page + ellipsis if needed -->
    <template v-if="showFirst">
      <button
        @click="goToPage(1)"
        :class="['pagination-btn', { active: currentPage === 1 }]"
      >
        1
      </button>
      <span class="pagination-ellipsis">...</span>
    </template>

    <!-- Page numbers -->
    <button
      v-for="page in visiblePages"
      :key="page"
      @click="goToPage(page)"
      :class="['pagination-btn', { active: page === currentPage }]"
    >
      {{ page }}
    </button>

    <!-- Last page + ellipsis if needed -->
    <template v-if="showLast">
      <span class="pagination-ellipsis">...</span>
      <button
        @click="goToPage(totalPages)"
        :class="['pagination-btn', { active: currentPage === totalPages }]"
      >
        {{ totalPages }}
      </button>
    </template>

    <!-- Next -->
    <button
      :disabled="currentPage >= totalPages"
      @click="goToPage(currentPage + 1)"
      class="pagination-btn"
      aria-label="下一页"
    >
      <ChevronRightIcon class="w-5 h-5" />
    </button>

    <!-- Page info -->
    <span class="pagination-info">
      第 {{ currentPage }} / {{ totalPages }} 页
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ChevronLeftIcon, ChevronRightIcon } from '@heroicons/vue/20/solid'

interface Props {
  currentPage: number
  totalPages: number
  maxVisible?: number
}

const props = withDefaults(defineProps<Props>(), {
  maxVisible: 5,
})

const emit = defineEmits<{
  change: [page: number]
}>()

const visiblePages = computed(() => {
  const pages: number[] = []
  const halfVisible = Math.floor(props.maxVisible / 2)
  let start = Math.max(1, props.currentPage - halfVisible)
  let end = Math.min(props.totalPages, start + props.maxVisible - 1)

  if (end - start + 1 < props.maxVisible) {
    start = Math.max(1, end - props.maxVisible + 1)
  }

  for (let i = start; i <= end; i++) {
    pages.push(i)
  }

  return pages
})

const showFirst = computed(() => {
  const firstPage = visiblePages.value[0]
  return firstPage !== undefined && firstPage > 1
})
const showLast = computed(() => {
  const lastPage = visiblePages.value[visiblePages.value.length - 1]
  return lastPage !== undefined && lastPage < props.totalPages
})

const goToPage = (page: number) => {
  if (page >= 1 && page <= props.totalPages && page !== props.currentPage) {
    emit('change', page)
  }
}
</script>

<style scoped>
.pagination {
  @apply flex items-center gap-1;
}

.pagination-btn {
  @apply flex items-center justify-center w-9 h-9 rounded-lg text-sm font-medium;
  @apply text-gray-600 bg-white border border-gray-300;
  @apply hover:bg-gray-50 hover:text-gray-900;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply dark:bg-gray-800 dark:border-gray-600 dark:text-gray-300;
  @apply dark:hover:bg-gray-700 dark:hover:text-white;
  @apply transition-colors duration-150;
}

.pagination-btn.active {
  @apply bg-primary-600 text-white border-primary-600;
  @apply dark:bg-primary-500 dark:border-primary-500;
}

.pagination-ellipsis {
  @apply px-2 text-gray-400 dark:text-gray-500;
}

.pagination-info {
  @apply ml-3 text-sm text-gray-500 dark:text-gray-400;
}
</style>
