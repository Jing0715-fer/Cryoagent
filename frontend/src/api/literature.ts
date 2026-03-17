import { api } from './client'

export interface Literature {
  id: number
  title: string
  authors?: string
  journal?: string
  year?: number
  doi?: string
  pmid?: string
  pmcid?: string
  abstract?: string
  keywords?: string
  has_pdf: boolean
  has_structure: boolean
  created_at: string
  updated_at: string
}

export interface LiteratureFilters {
  search?: string
  year?: number
  year_from?: number
  year_to?: number
  journal?: string
  author?: string
  has_pdf?: boolean
  has_structure?: boolean
}

export interface LiteratureListResponse {
  items: Literature[]
  total: number
  page: number
  per_page: number
  total_pages: number
}

export interface LiteratureDetail extends Literature {
  sections?: Record<string, string>
  full_text?: string
  references?: string[]
}

export const literatureApi = {
  // Get literature list
  getList: (page = 1, perPage = 20, filters?: LiteratureFilters) =>
    api.get<LiteratureListResponse>('/literature', {
      params: { page, per_page: perPage, ...filters },
    }),

  // Get single literature
  getById: (id: number) =>
    api.get<LiteratureDetail>(`/literature/${id}`),

  // Search literature
  search: (query: string, page = 1, perPage = 20) =>
    api.get<LiteratureListResponse>('/literature/search', {
      params: { q: query, page, per_page: perPage },
    }),

  // Delete literature
  delete: (id: number) =>
    api.delete(`/literature/${id}`),

  // Get PDF URL
  getPdfUrl: (id: number) => `/literature/${id}/pdf`,

  // Get filters (years, journals, etc.)
  getFilters: () =>
    api.get<{ years: number[]; journals: string[] }>('/literature/filters'),
}
