import { api } from './client'

export interface UploadStatus {
  id: string
  filename: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress: number
  message?: string
  literature_id?: number
}

export const uploadApi = {
  // Upload files
  uploadFiles: (files: File[], onProgress?: (progress: number) => void) => {
    const formData = new FormData()
    files.forEach(file => formData.append('files', file))
    return api.upload<UploadStatus[]>('/upload', formData, onProgress)
  },

  // Upload from URL
  uploadFromUrl: (url: string) =>
    api.post<UploadStatus>('/upload/url', { url }),

  // Get upload status
  getStatus: (uploadId: string) =>
    api.get<UploadStatus>(`/upload/status/${uploadId}`),

  // Get all uploads
  getAll: () =>
    api.get<UploadStatus[]>('/uploads'),
}
