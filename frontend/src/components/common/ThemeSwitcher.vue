<template>
  <div class="theme-switcher">
    <button
      @click="toggleDropdown"
      class="theme-btn"
      :title="currentThemeLabel"
    >
      <SwatchIcon class="w-5 h-5" />
      <span class="flex-1 text-left">{{ currentThemeLabel }}</span>
      <ChevronDownIcon
        class="w-4 h-4 transition-transform"
        :class="{ 'rotate-180': isOpen }"
      />
    </button>

    <Transition
      enter-active-class="transition ease-out duration-100"
      enter-from-class="transform opacity-0 scale-95"
      enter-to-class="transform opacity-100 scale-100"
      leave-active-class="transition ease-in duration-75"
      leave-from-class="transform opacity-100 scale-100"
      leave-to-class="transform opacity-0 scale-95"
    >
      <div v-if="isOpen" class="theme-dropdown">
        <button
          v-for="(theme, key) in themeStore.themes"
          :key="key"
          @click="selectTheme(key as ThemeName)"
          :class="['theme-option', { active: themeStore.currentTheme === key }]"
        >
          <span class="theme-indicator" :class="`theme-${key}`"></span>
          <span>{{ theme.name }}</span>
          <CheckIcon
            v-if="themeStore.currentTheme === key"
            class="w-4 h-4 ml-auto text-primary-600"
          />
        </button>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { SwatchIcon, ChevronDownIcon, CheckIcon } from '@heroicons/vue/24/outline'
import { useThemeStore, type ThemeName } from '@/stores/theme'

const themeStore = useThemeStore()
const isOpen = ref(false)

const currentThemeLabel = computed(() => {
  return themeStore.themes[themeStore.currentTheme]?.name || '主题'
})

const toggleDropdown = () => {
  isOpen.value = !isOpen.value
}

const selectTheme = (theme: ThemeName) => {
  themeStore.setTheme(theme)
  isOpen.value = false
}

// Close dropdown when clicking outside
const handleClickOutside = (event: MouseEvent) => {
  const target = event.target as HTMLElement
  if (!target.closest('.theme-switcher')) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  themeStore.init()
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<style scoped>
.theme-switcher {
  @apply relative;
}

.theme-btn {
  @apply w-full flex items-center gap-3 px-4 py-3 text-sm font-medium rounded-lg;
  @apply text-gray-600 hover:bg-gray-100 hover:text-gray-900;
  @apply dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100;
  @apply transition-colors duration-150;
}

.theme-dropdown {
  @apply absolute bottom-full left-0 right-0 mb-2;
  @apply bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700;
  @apply py-1 z-50;
}

.theme-option {
  @apply w-full flex items-center gap-3 px-4 py-2 text-sm;
  @apply text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700;
  @apply transition-colors duration-150;
}

.theme-option.active {
  @apply bg-primary-50 dark:bg-primary-900/20 text-primary-700 dark:text-primary-400;
}

.theme-indicator {
  @apply w-4 h-4 rounded-full border-2 border-gray-300 dark:border-gray-600;
}

.theme-indicator.theme-original {
  @apply bg-gradient-to-br from-blue-400 to-purple-500;
}

.theme-indicator.theme-dark {
  @apply bg-gray-900;
}

.theme-indicator.theme-cyberpunk {
  @apply bg-gradient-to-br from-cyan-400 to-magenta-500;
}

.theme-indicator.theme-matrix {
  @apply bg-black border-green-500;
}

.theme-indicator.theme-persona5 {
  @apply bg-red-600;
}

.theme-indicator.theme-persona4 {
  @apply bg-yellow-500;
}

.theme-indicator.theme-persona3 {
  @apply bg-blue-600;
}
</style>
