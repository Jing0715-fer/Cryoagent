<template>
  <aside class="sidebar">
    <!-- Logo -->
    <div class="logo">
      <svg class="logo-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
      </svg>
      <span class="logo-text">CryoAgent</span>
      <span class="logo-pro">Pro</span>
    </div>

    <!-- Navigation -->
    <nav class="nav">
      <router-link
        v-for="item in navItems"
        :key="item.name"
        :to="item.path"
        :class="['nav-link', { active: isActive(item.path) }]"
      >
        <component :is="item.icon" class="w-5 h-5" />
        <span>{{ item.label }}</span>
      </router-link>
    </nav>

    <!-- Bottom section -->
    <div class="sidebar-footer">
      <ThemeSwitcher />

      <router-link to="/settings" class="nav-link">
        <Cog6ToothIcon class="w-5 h-5" />
        <span>设置</span>
      </router-link>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  HomeIcon,
  BookOpenIcon,
  CubeIcon,
  ChatBubbleLeftRightIcon,
  ArrowsRightLeftIcon,
  ShareIcon,
  Cog6ToothIcon,
} from '@heroicons/vue/24/outline'
import ThemeSwitcher from './ThemeSwitcher.vue'

const route = useRoute()

const navItems = [
  { name: 'home', path: '/', label: '首页', icon: HomeIcon },
  { name: 'literature', path: '/literature', label: '文献管理', icon: BookOpenIcon },
  { name: 'structures', path: '/structures', label: '结构管理', icon: CubeIcon },
  { name: 'qa', path: '/qa', label: '智能问答', icon: ChatBubbleLeftRightIcon },
  { name: 'alignment', path: '/alignment', label: '序列比对', icon: ArrowsRightLeftIcon },
  { name: 'knowledge-graph', path: '/knowledge-graph', label: '知识图谱', icon: ShareIcon },
]

const isActive = (path: string) => {
  if (path === '/') {
    return route.path === '/'
  }
  return route.path.startsWith(path)
}
</script>

<style scoped>
.sidebar {
  @apply fixed left-0 top-0 h-full w-64 bg-white dark:bg-gray-900;
  @apply border-r border-gray-200 dark:border-gray-800;
  @apply flex flex-col z-40;
}

.logo {
  @apply flex items-center gap-2 px-6 py-5 border-b border-gray-200 dark:border-gray-800;
}

.logo-icon {
  @apply w-8 h-8 text-primary-600 dark:text-primary-400;
}

.logo-text {
  @apply text-xl font-bold text-gray-900 dark:text-white;
}

.logo-pro {
  @apply text-xs px-2 py-0.5 bg-primary-100 dark:bg-primary-900/30;
  @apply text-primary-700 dark:text-primary-400 rounded-full font-semibold;
}

.nav {
  @apply flex-1 px-3 py-4 space-y-1 overflow-y-auto;
}

.sidebar-footer {
  @apply px-3 py-4 border-t border-gray-200 dark:border-gray-800 space-y-1;
}

.nav-link {
  @apply flex items-center gap-3 px-4 py-3 text-sm font-medium rounded-lg;
  @apply text-gray-600 hover:bg-gray-100 hover:text-gray-900;
  @apply dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100;
  @apply transition-colors duration-150;
}

.nav-link.active {
  @apply bg-primary-50 text-primary-700;
  @apply dark:bg-primary-900/20 dark:text-primary-400;
}
</style>
