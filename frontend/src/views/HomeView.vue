<template>
  <div class="home">
    <!-- Hero Section -->
    <div class="hero">
      <div class="hero-content">
        <h1 class="hero-title">
          <span class="hero-icon">❄️</span>
          CryoAgent Pro
        </h1>
        <p class="hero-subtitle">
          智能冷冻电镜文献管理与结构分析平台
        </p>
        <div class="hero-stats">
          <div class="stat-card">
            <BookOpenIcon class="w-6 h-6 text-primary-500" />
            <div class="stat-value">{{ stats.literature_count || 0 }}</div>
            <div class="stat-label">文献</div>
          </div>
          <div class="stat-card">
            <CubeIcon class="w-6 h-6 text-primary-500" />
            <div class="stat-value">{{ stats.structure_count || 0 }}</div>
            <div class="stat-label">结构</div>
          </div>
          <div class="stat-card">
            <ChatBubbleLeftRightIcon class="w-6 h-6 text-primary-500" />
            <div class="stat-value">{{ stats.qa_count || 0 }}</div>
            <div class="stat-label">问答</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Quick Actions -->
    <div class="quick-actions">
      <h2 class="section-title">快速操作</h2>
      <div class="action-grid">
        <router-link to="/literature" class="action-card">
          <div class="action-icon bg-blue-100 dark:bg-blue-900/30">
            <BookOpenIcon class="w-6 h-6 text-blue-600 dark:text-blue-400" />
          </div>
          <div class="action-content">
            <h3>浏览文献</h3>
            <p>查看和管理您的文献库</p>
          </div>
          <ChevronRightIcon class="action-arrow" />
        </router-link>

        <router-link to="/structures" class="action-card">
          <div class="action-icon bg-green-100 dark:bg-green-900/30">
            <CubeIcon class="w-6 h-6 text-green-600 dark:text-green-400" />
          </div>
          <div class="action-content">
            <h3>查看结构</h3>
            <p>浏览蛋白质结构数据</p>
          </div>
          <ChevronRightIcon class="action-arrow" />
        </router-link>

        <router-link to="/qa" class="action-card">
          <div class="action-icon bg-purple-100 dark:bg-purple-900/30">
            <ChatBubbleLeftRightIcon class="w-6 h-6 text-purple-600 dark:text-purple-400" />
          </div>
          <div class="action-content">
            <h3>智能问答</h3>
            <p>向AI助手提问</p>
          </div>
          <ChevronRightIcon class="action-arrow" />
        </router-link>

        <router-link to="/alignment" class="action-card">
          <div class="action-icon bg-orange-100 dark:bg-orange-900/30">
            <ArrowsRightLeftIcon class="w-6 h-6 text-orange-600 dark:text-orange-400" />
          </div>
          <div class="action-content">
            <h3>序列比对</h3>
            <p>分析蛋白质序列</p>
          </div>
          <ChevronRightIcon class="action-arrow" />
        </router-link>
      </div>
    </div>

    <!-- Recent Activity -->
    <div class="recent-activity">
      <h2 class="section-title">最近活动</h2>
      <div class="activity-list">
        <div v-if="recentActivity.length === 0" class="activity-empty">
          <InboxIcon class="w-12 h-12 text-gray-400" />
          <p>暂无最近活动</p>
        </div>
        <div
          v-for="activity in recentActivity"
          :key="activity.id"
          class="activity-item"
        >
          <div class="activity-icon" :class="activity.type">
            <component :is="iconForType(activity.type)" class="w-5 h-5" />
          </div>
          <div class="activity-content">
            <p class="activity-text">{{ activity.text }}</p>
            <p class="activity-time">{{ activity.time }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Upload Section -->
    <div class="upload-section">
      <h2 class="section-title">上传文献</h2>
      <UploadZone />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  BookOpenIcon,
  CubeIcon,
  ChatBubbleLeftRightIcon,
  ArrowsRightLeftIcon,
  ChevronRightIcon,
  InboxIcon,
  DocumentPlusIcon,
  QuestionMarkCircleIcon,
} from '@heroicons/vue/24/outline'
import UploadZone from '@/components/common/UploadZone.vue'
import { api } from '@/api/client'

interface Stats {
  literature_count: number
  structure_count: number
  qa_count: number
}

interface Activity {
  id: string
  type: string
  text: string
  time: string
}

const stats = ref<Stats>({
  literature_count: 0,
  structure_count: 0,
  qa_count: 0,
})

const recentActivity = ref<Activity[]>([])

const iconForType = (type: string) => {
  switch (type) {
    case 'upload':
      return DocumentPlusIcon
    case 'qa':
      return QuestionMarkCircleIcon
    default:
      return DocumentPlusIcon
  }
}

const fetchStats = async () => {
  try {
    const response = await api.get<Stats>('/stats')
    stats.value = response
  } catch (error) {
    console.error('Failed to fetch stats:', error)
  }
}

onMounted(() => {
  fetchStats()
})
</script>

<style scoped>
.hero {
  @apply relative bg-gradient-to-br from-primary-600 to-primary-800 rounded-2xl p-8 mb-8;
  @apply text-white overflow-hidden;
}

.hero::before {
  content: '';
  @apply absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAiIGhlaWdodD0iMjAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGNpcmNsZSBjeD0iMiIgY3k9IjIiIHI9IjEiIGZpbGw9InJnYmEoMjU1LDI1NSwyNTUsMC4xKSIvPjwvc3ZnPg==')] opacity-30;
}

.hero-content {
  @apply relative z-10;
}

.hero-title {
  @apply text-3xl font-bold mb-2 flex items-center gap-3;
}

.hero-icon {
  @apply text-4xl;
}

.hero-subtitle {
  @apply text-primary-100 text-lg mb-6;
}

.hero-stats {
  @apply flex gap-4 flex-wrap;
}

.stat-card {
  @apply flex items-center gap-3 bg-white/10 backdrop-blur rounded-xl px-4 py-3;
}

.stat-value {
  @apply text-2xl font-bold;
}

.stat-label {
  @apply text-sm text-primary-100;
}

/* Section Title */
.section-title {
  @apply text-xl font-semibold text-gray-900 dark:text-white mb-4;
}

/* Quick Actions */
.quick-actions {
  @apply mb-8;
}

.action-grid {
  @apply grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4;
}

.action-card {
  @apply flex items-center gap-4 p-4 bg-white dark:bg-gray-800 rounded-xl;
  @apply border border-gray-200 dark:border-gray-700;
  @apply hover:shadow-md hover:border-primary-300 dark:hover:border-primary-700;
  @apply transition-all duration-200;
}

.action-icon {
  @apply w-12 h-12 rounded-lg flex items-center justify-center flex-shrink-0;
}

.action-content {
  @apply flex-1 min-w-0;
}

.action-content h3 {
  @apply font-medium text-gray-900 dark:text-white;
}

.action-content p {
  @apply text-sm text-gray-500 dark:text-gray-400;
}

.action-arrow {
  @apply w-5 h-5 text-gray-400 dark:text-gray-500;
}

/* Recent Activity */
.recent-activity {
  @apply mb-8;
}

.activity-list {
  @apply bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700;
  @apply divide-y divide-gray-200 dark:divide-gray-700;
}

.activity-empty {
  @apply flex flex-col items-center justify-center py-12 text-gray-500 dark:text-gray-400;
}

.activity-item {
  @apply flex items-center gap-4 p-4;
}

.activity-icon {
  @apply w-10 h-10 rounded-lg flex items-center justify-center;
}

.activity-icon.upload {
  @apply bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400;
}

.activity-icon.qa {
  @apply bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400;
}

.activity-content {
  @apply flex-1;
}

.activity-text {
  @apply text-sm text-gray-900 dark:text-white;
}

.activity-time {
  @apply text-xs text-gray-500 dark:text-gray-400;
}

/* Upload Section */
.upload-section {
  @apply mb-8;
}
</style>
