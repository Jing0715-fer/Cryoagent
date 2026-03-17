import { api } from './client'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  sources?: Array<{
    id: number
    title: string
    relevance: number
  }>
  images?: string[]
  isStreaming?: boolean
}

export interface QARequest {
  question: string
  session_id?: string
  context_filter?: {
    literature_ids?: number[]
    structure_ids?: number[]
    year_range?: [number, number]
  }
}

export interface QAResponse {
  answer: string
  session_id: string
  sources?: Array<{
    id: number
    title: string
    relevance: number
    excerpt?: string
  }>
  images?: string[]
}

export const qaApi = {
  // Send question
  ask: (data: QARequest) =>
    api.post<QAResponse>('/qa/ask', data),

  // Get chat history
  getHistory: (sessionId: string) =>
    api.get<ChatMessage[]>(`/qa/history/${sessionId}`),

  // Clear chat
  clearChat: (sessionId: string) =>
    api.delete(`/qa/session/${sessionId}`),

  // Stream response (returns event source)
  stream: (data: QARequest) => {
    const url = new URL('/api/qa/stream', window.location.origin)
    url.searchParams.append('question', data.question)
    if (data.session_id) {
      url.searchParams.append('session_id', data.session_id)
    }
    return new EventSource(url.toString())
  },
}
