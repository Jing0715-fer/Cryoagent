<template>
  <div class="placeholder-view">
    <div class="placeholder-content">
      <component :is="icon" class="placeholder-icon" />
      <h1 class="placeholder-title">{{ title }}</h1>
      <p class="placeholder-text">{{ description }}</p>
      <router-link to="/" class="btn-primary">
        返回首页
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  CubeIcon,
  ChatBubbleLeftRightIcon,
  ArrowsRightLeftIcon,
  ShareIcon,
  Cog6ToothIcon,
  DocumentTextIcon,
  ExclamationTriangleIcon,
} from '@heroicons/vue/24/outline'

const props = defineProps<{
  type?: 'structure' | 'qa' | 'alignment' | 'knowledge-graph' | 'settings' | 'feishu' | 'not-found'
}>()

const config = computed(() => {
  switch (props.type) {
    case 'structure':
      return {
        title: '结构管理',
        description: '蛋白质结构管理功能正在开发中',
        icon: CubeIcon,
      }
    case 'qa':
      return {
        title: '智能问答',
        description: '智能问答功能正在开发中',
        icon: ChatBubbleLeftRightIcon,
      }
    case 'alignment':
      return {
        title: '序列比对',
        description: '序列比对功能正在开发中',
        icon: ArrowsRightLeftIcon,
      }
    case 'knowledge-graph':
      return {
        title: '知识图谱',
        description: '知识图谱功能正在开发中',
        icon: ShareIcon,
      }
    case 'settings':
      return {
        title: '系统设置',
        description: '系统设置功能正在开发中',
        icon: Cog6ToothIcon,
      }
    case 'feishu':
      return {
        title: '飞书配置',
        description: '飞书配置功能正在开发中',
        icon: DocumentTextIcon,
      }
    case 'not-found':
      return {
        title: '页面未找到',
        description: '您访问的页面不存在',
        icon: ExclamationTriangleIcon,
      }
    default:
      return {
        title: '功能开发中',
        description: '该功能正在开发中，敬请期待',
        icon: DocumentTextIcon,
      }
  }
})

const title = computed(() => config.value.title)
const description = computed(() => config.value.description)
const icon = computed(() => config.value.icon)
</script>

<style scoped>
.placeholder-view {
  @apply flex items-center justify-center min-h-[60vh];
}

.placeholder-content {
  @apply text-center;
}

.placeholder-icon {
  @apply w-16 h-16 text-gray-400 dark:text-gray-500 mx-auto mb-4;
}

.placeholder-title {
  @apply text-2xl font-bold text-gray-900 dark:text-white mb-2;
}

.placeholder-text {
  @apply text-gray-500 dark:text-gray-400 mb-6;
}
</style>
