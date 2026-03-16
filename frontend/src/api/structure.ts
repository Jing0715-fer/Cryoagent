import { api } from './client'

export interface Structure {
  id: number
  pdb_id?: string
  emdb_id?: string
  uniprot_id?: string
  title?: string
  method?: string
  resolution?: number
  year?: number
  literature_id?: number
  literature_title?: string
  created_at: string
}

export interface StructureListResponse {
  items: Structure[]
  total: number
  page: number
  per_page: number
  total_pages: number
}

export interface StructureFilters {
  search?: string
  method?: string
  year_from?: number
  year_to?: number
  has_literature?: boolean
}

export const structureApi = {
  // Get structure list
  getList: (page = 1, perPage = 20, filters?: StructureFilters) =>
    api.get<StructureListResponse>('/structures', {
      params: { page, per_page: perPage, ...filters },
    }),

  // Get single structure
  getById: (id: number) =>
    api.get<Structure>(`/structures/${id}`),

  // Search structures
  search: (query: string, page = 1, perPage = 20) =>
    api.get<StructureListResponse>('/structures/search', {
      params: { q: query, page, per_page: perPage },
    }),

  // Get structure files
  getCifUrl: (id: number) => `/structures/${id}/cif`,
  getPdbUrl: (id: number) => `/structures/${id}/pdb`,

  // Get filters
  getFilters: () =>
    api.get<{ methods: string[]; years: number[] }>('/structures/filters'),
}
