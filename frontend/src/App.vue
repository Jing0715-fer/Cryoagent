<script setup lang="ts">
import { onMounted } from 'vue'
import Sidebar from '@/components/common/Sidebar.vue'
import Toast from '@/components/common/Toast.vue'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()

onMounted(() => {
  themeStore.init()
})
</script>

<template>
  <div class="app">
    <Sidebar />

    <main class="main-content">
      <div class="content-wrapper">
        <RouterView v-slot="{ Component }">
          <Transition
            name="fade"
            mode="out-in"
          >
            <component :is="Component" />
          </Transition>
        </RouterView>
      </div>
    </main>

    <Toast />
  </div>
</template>

<style>
@import '@/assets/styles/base.css';

.app {
  @apply flex min-h-screen bg-gray-50 dark:bg-gray-900;
}

.main-content {
  @apply flex-1 ml-64 min-h-screen;
}

.content-wrapper {
  @apply p-6 max-w-7xl mx-auto;
}

/* Page transitions */
.fade-enter-active,
.fade-leave-active {
  @apply transition-opacity duration-200;
}

.fade-enter-from,
.fade-leave-to {
  @apply opacity-0;
}
</style>
