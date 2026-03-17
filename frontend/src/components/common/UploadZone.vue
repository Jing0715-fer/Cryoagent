<template>
  <div
    :class="['upload-zone', { 'drag-over': isDragOver, 'uploading': isUploading }]"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
    @click="triggerFileInput"
  >
    <input
      ref="fileInput"
      type="file"
      multiple
      accept=".pdf,.cif,.pdb,.txt,.doc,.docx"
      class="hidden"
      @change="onFileSelect"
    />

    <div v-if="isUploading" class="upload-progress">
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: `${uploadProgress}%` }"></div>
      </div>
      <span class="progress-text">上传中... {{ uploadProgress }}%</span>
    </div>

    <template v-else>
      <CloudArrowUpIcon class="upload-icon" />
      <div class="upload-text">
        <p class="upload-title">拖拽文件到此处或点击上传</p>
        <p class="upload-hint">支持 PDF、CIF、PDB、TXT、DOC、DOCX 格式</p>
      </div>
      <button
        v-if="files.length > 0"
        @click.stop="uploadFiles"
        class="upload-btn"
      >
        <ArrowUpTrayIcon class="w-4 h-4" />
        上传 {{ files.length }} 个文件
      </button>

      <!-- Selected files list -->
      <div v-if="files.length > 0" class="file-list" @click.stop>
        <div
          v-for="(file, index) in files"
          :key="index"
          class="file-item"
        >
          <DocumentIcon class="w-4 h-4 text-gray-500" />
          <span class="file-name">{{ file.name }}</span>
          <span class="file-size">{{ formatFileSize(file.size) }}</span>
          <button
            @click.stop="removeFile(index)"
            class="file-remove"
            title="移除"
          >
            <XMarkIcon class="w-4 h-4" />
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import {
  CloudArrowUpIcon,
  ArrowUpTrayIcon,
  DocumentIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import { uploadApi } from '@/api/upload'
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()

const fileInput = ref<HTMLInputElement | null>(null)
const files = ref<File[]>([])
const isDragOver = ref(false)
const isUploading = ref(false)
const uploadProgress = ref(0)

const triggerFileInput = () => {
  fileInput.value?.click()
}

const onDragEnter = () => {
  isDragOver.value = true
}

const onDragOver = () => {
  isDragOver.value = true
}

const onDragLeave = () => {
  isDragOver.value = false
}

const onDrop = (event: DragEvent) => {
  isDragOver.value = false
  const droppedFiles = event.dataTransfer?.files
  if (droppedFiles) {
    addFiles(Array.from(droppedFiles))
  }
}

const onFileSelect = (event: Event) => {
  const target = event.target as HTMLInputElement
  const selectedFiles = target.files
  if (selectedFiles) {
    addFiles(Array.from(selectedFiles))
  }
}

const addFiles = (newFiles: File[]) => {
  const validFiles = newFiles.filter(file => {
    const validTypes = ['.pdf', '.cif', '.pdb', '.txt', '.doc', '.docx']
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    return validTypes.includes(ext)
  })

  if (validFiles.length < newFiles.length) {
    toast.warning('部分文件格式不支持，已自动过滤')
  }

  files.value.push(...validFiles)
}

const removeFile = (index: number) => {
  files.value.splice(index, 1)
}

const formatFileSize = (bytes: number) => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

const uploadFiles = async () => {
  if (files.value.length === 0) return

  isUploading.value = true
  uploadProgress.value = 0

  try {
    const result = await uploadApi.uploadFiles(files.value, (progress) => {
      uploadProgress.value = progress
    })

    toast.success(`成功上传 ${result.length} 个文件`)
    files.value = []
  } catch (error) {
    toast.error('上传失败：' + (error as Error).message)
  } finally {
    isUploading.value = false
    uploadProgress.value = 0
  }
}
</script>

<style scoped>
.upload-zone {
  @apply relative border-2 border-dashed border-gray-300 rounded-xl;
  @apply p-8 text-center cursor-pointer;
  @apply transition-all duration-200;
  @apply dark:border-gray-600;
  @apply hover:border-primary-400 hover:bg-primary-50/50;
  @apply dark:hover:border-primary-500 dark:hover:bg-primary-900/10;
}

.upload-zone.drag-over {
  @apply border-primary-500 bg-primary-50;
  @apply dark:border-primary-400 dark:bg-primary-900/20;
}

.upload-zone.uploading {
  @apply cursor-default border-primary-500 bg-primary-50/30;
  @apply dark:bg-primary-900/10;
}

.upload-icon {
  @apply w-12 h-12 mx-auto text-gray-400 dark:text-gray-500 mb-4;
}

.upload-text {
  @apply space-y-1;
}

.upload-title {
  @apply text-base font-medium text-gray-900 dark:text-white;
}

.upload-hint {
  @apply text-sm text-gray-500 dark:text-gray-400;
}

.upload-btn {
  @apply inline-flex items-center gap-2 mt-4 px-4 py-2;
  @apply bg-primary-600 text-white text-sm font-medium rounded-lg;
  @apply hover:bg-primary-700 transition-colors;
}

/* Progress */
.upload-progress {
  @apply space-y-3;
}

.progress-bar {
  @apply w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden;
}

.progress-fill {
  @apply h-full bg-primary-600 rounded-full transition-all duration-300;
}

.progress-text {
  @apply text-sm text-gray-600 dark:text-gray-400;
}

/* File list */
.file-list {
  @apply mt-4 space-y-2;
}

.file-item {
  @apply flex items-center gap-3 px-3 py-2;
  @apply bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700;
}

.file-name {
  @apply flex-1 text-sm text-gray-700 dark:text-gray-300 truncate;
}

.file-size {
  @apply text-xs text-gray-500 dark:text-gray-500;
}

.file-remove {
  @apply p-1 text-gray-400 hover:text-red-500 dark:hover:text-red-400;
  @apply transition-colors;
}
</style>
