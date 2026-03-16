<template>
  <TransitionGroup
    tag="div"
    name="toast"
    class="toast-container"
  >
    <div
      v-for="toast in toasts"
      :key="toast.id"
      :class="['toast', `toast-${toast.type}`]"
    >
      <component :is="iconForType(toast.type)" class="w-5 h-5" />
      <span class="flex-1">{{ toast.message }}</span>
      <button
        @click="remove(toast.id)"
        class="toast-close"
      >
        <XMarkIcon class="w-4 h-4" />
      </button>
    </div>
  </TransitionGroup>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  CheckCircleIcon,
  XCircleIcon,
  InformationCircleIcon,
  ExclamationTriangleIcon,
  XMarkIcon,
} from '@heroicons/vue/24/solid'
import { useToastStore } from '@/stores/toast'

const toastStore = useToastStore()
const toasts = computed(() => toastStore.toasts)

const iconForType = (type: string) => {
  switch (type) {
    case 'success':
      return CheckCircleIcon
    case 'error':
      return XCircleIcon
    case 'warning':
      return ExclamationTriangleIcon
    default:
      return InformationCircleIcon
  }
}

const remove = (id: string) => {
  toastStore.remove(id)
}
</script>

<style scoped>
.toast-container {
  @apply fixed bottom-4 right-4 z-50 flex flex-col gap-2;
}

.toast {
  @apply flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg min-w-[300px] max-w-md;
  @apply text-white text-sm font-medium;
}

.toast-success {
  @apply bg-green-600;
}

.toast-error {
  @apply bg-red-600;
}

.toast-info {
  @apply bg-blue-600;
}

.toast-warning {
  @apply bg-yellow-600;
}

.toast-close {
  @apply p-1 rounded hover:bg-white/20 transition-colors;
}

/* Transitions */
.toast-enter-active,
.toast-leave-active {
  @apply transition-all duration-300;
}

.toast-enter-from {
  @apply opacity-0 translate-x-full;
}

.toast-leave-to {
  @apply opacity-0 translate-x-full;
}
</style>
