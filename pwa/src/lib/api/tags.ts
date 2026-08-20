import { apiFetch, qs } from './client'

import type {
  TagListResponse,
  TagAlias,
  TagImplication,
  TagItem,
  TagHealthReport,
  TagTranslationBrowseResponse,
  BlockedTag,
} from '../types'

// ── Tags ─────────────────────────────────────────────────────────────

export const tags = {
  list: (
    params: {
      prefix?: string
      namespace?: string
      limit?: number
      offset?: number
      cursor?: string
    } = {},
  ) => apiFetch<TagListResponse>(`/api/tags/${qs(params as Record<string, unknown>)}`),

  listAliases: (params: { tag_id?: number; limit?: number } = {}) =>
    apiFetch<TagAlias[]>(`/api/tags/aliases${qs(params as Record<string, unknown>)}`),

  createAlias: (alias_namespace: string, alias_name: string, canonical_id: number) =>
    apiFetch<{ status: string }>('/api/tags/aliases', {
      method: 'POST',
      body: JSON.stringify({ alias_namespace, alias_name, canonical_id }),
    }),

  deleteAlias: (alias_namespace: string, alias_name: string) =>
    apiFetch<{ status: string }>(`/api/tags/aliases${qs({ alias_namespace, alias_name })}`, {
      method: 'DELETE',
    }),

  listImplications: (params: { tag_id?: number; limit?: number } = {}) =>
    apiFetch<TagImplication[]>(`/api/tags/implications${qs(params as Record<string, unknown>)}`),

  createImplication: (antecedent_id: number, consequent_id: number) =>
    apiFetch<{ status: string }>('/api/tags/implications', {
      method: 'POST',
      body: JSON.stringify({ antecedent_id, consequent_id }),
    }),

  deleteImplication: (antecedent_id: number, consequent_id: number) =>
    apiFetch<{ status: string }>(`/api/tags/implications${qs({ antecedent_id, consequent_id })}`, {
      method: 'DELETE',
    }),

  autocomplete: (q: string, limit = 10) =>
    apiFetch<TagItem[]>(`/api/tags/autocomplete${qs({ q, limit })}`),

  getTranslations: (tags: string[], language = 'zh') =>
    apiFetch<Record<string, string>>(
      `/api/tags/translations${qs({ tags: tags.join(','), language })}`,
    ),

  translationsBrowse: (
    params: {
      q?: string
      namespace?: string
      language?: string
      limit?: number
      offset?: number
    } = {},
  ) =>
    apiFetch<TagTranslationBrowseResponse>(
      `/api/tags/translations/browse${qs(params as Record<string, unknown>)}`,
    ),

  listBlocked: () => apiFetch<BlockedTag[]>('/api/tags/blocked'),

  addBlocked: (namespace: string, name: string) =>
    apiFetch<{ status: string }>('/api/tags/blocked', {
      method: 'POST',
      body: JSON.stringify({ namespace, name }),
    }),

  removeBlocked: (id: number) =>
    apiFetch<{ status: string }>(`/api/tags/blocked/${id}`, { method: 'DELETE' }),

  importEhtag: () =>
    apiFetch<{ status: string; count: number }>('/api/tags/import-ehtag', { method: 'POST' }),

  updateGalleryTags: (galleryId: number, body: { tags: string[]; action: 'add' | 'remove' }) =>
    apiFetch<{ status: string; affected: number }>(`/api/tags/gallery/${galleryId}`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  upsertTranslation: (body: {
    namespace: string
    name: string
    language: string
    translation: string
  }) =>
    apiFetch<{ status: string }>('/api/tags/translations', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  batchImportTranslations: (
    translations: Array<{ namespace: string; name: string; language: string; translation: string }>,
  ) =>
    apiFetch<{ status: string; count: number }>('/api/tags/translations/batch', {
      method: 'POST',
      body: JSON.stringify({ translations }),
    }),

  health: (limit?: number) => apiFetch<TagHealthReport>(`/api/tags/health${qs({ limit })}`),

  healthIgnore: (key: string) =>
    apiFetch<{ status: string }>('/api/tags/health/ignore', {
      method: 'POST',
      body: JSON.stringify({ key }),
    }),

  healthUnignore: (key: string) =>
    apiFetch<{ status: string }>(`/api/tags/health/ignore${qs({ key })}`, {
      method: 'DELETE',
    }),

  healthIgnored: () => apiFetch<{ keys: string[] }>('/api/tags/health/ignored'),

  deleteTag: (tagId: number) =>
    apiFetch<{ status: string }>(`/api/tags/${tagId}`, { method: 'DELETE' }),
}
