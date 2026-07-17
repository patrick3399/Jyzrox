import { apiFetch, qs } from './client'

// ── Library Workbench ────────────────────────────────────────────────

export interface ExplorerQuery {
  node_kind?: 'all' | 'source' | 'collection' | 'artist' | 'saved_search' | 'smart' | 'trash'
  node_id?: string | null
  query?: string
  sort?: 'added_at' | 'posted_at' | 'title' | 'rating' | 'pages'
  direction?: 'asc' | 'desc'
  offset?: number
  limit?: number
}

export interface ExplorerGalleryItem {
  id: number
  source: string
  source_id: string
  title: string | null
  title_jpn: string | null
  category: string | null
  language: string | null
  artist_id: string | null
  uploader: string | null
  visibility: 'public' | 'private'
  pages: number | null
  cover_thumb: string | null
  logical_bytes: number
  unique_cas_bytes: number
  is_favorited: boolean
  my_rating: number | null
  in_reading_list: boolean
  deleted_at: string | null
}

export interface ExplorerRoots {
  virtual: {
    sources: Array<{
      id: string
      label: string
      gallery_count: number
      logical_bytes: number
      unique_cas_bytes: number
    }>
    collections: {
      count: number
      items: Array<{ id: number; name: string; gallery_count: number }>
    }
    artists: {
      count: number
      items: Array<{ id: string; name: string; gallery_count: number }>
    }
    saved_searches: {
      count: number
      items: Array<{ id: number; name: string; query: string }>
    }
    smart_views: {
      missing_metadata: number
      empty_galleries: number
      duplicate_pairs: number
      trash: boolean
    }
  }
  physical: Array<{
    id: number
    label: string
    import_mode: string
    pattern: string
    size_status: 'ready' | 'pending'
    physical_bytes: number | null
    size_updated_at: string | null
  }>
}

export interface ExplorerPhysicalEntry {
  kind: 'folder' | 'media'
  name: string
  path: string
  has_children?: boolean
  gallery_id?: number | null
  size_status?: 'ready' | 'pending'
  physical_bytes?: number | null
  media_count?: number | null
  size_updated_at?: string | null
  size?: number
  modified_at: number
}

export const explorer = {
  roots: () => apiFetch<ExplorerRoots>('/api/explorer/roots'),
  query: (query: ExplorerQuery) =>
    apiFetch<{ total: number; offset: number; limit: number; items: ExplorerGalleryItem[] }>(
      '/api/explorer/query',
      { method: 'POST', body: JSON.stringify(query) },
    ),
  createSelection: (query: ExplorerQuery) =>
    apiFetch<{ selection_token: string; count: number; expires_in: number }>(
      '/api/explorer/selections',
      { method: 'POST', body: JSON.stringify({ query }) },
    ),
  bulkMetadata: (body: {
    gallery_ids?: number[]
    selection_token?: string
    excluded_ids?: number[]
    fields: Record<string, { mode: 'keep' | 'set' | 'clear'; value?: unknown }>
    lock_fields?: boolean
  }) =>
    apiFetch<{
      operation_id: string
      status: string
      selection_count: number
      changed_fields: number
    }>('/api/explorer/operations/metadata', { method: 'POST', body: JSON.stringify(body) }),
  deleteSelection: (body: {
    gallery_ids?: number[]
    selection_token?: string
    excluded_ids?: number[]
  }) =>
    apiFetch<{
      operation_id: string
      status: string
      affected: number
      skipped_active_downloads: number[]
    }>('/api/explorer/operations/delete', { method: 'POST', body: JSON.stringify(body) }),
  bulkAction: (body: {
    gallery_ids?: number[]
    selection_token?: string
    excluded_ids?: number[]
    action:
      | 'favorite'
      | 'unfavorite'
      | 'rate'
      | 'add_read_later'
      | 'remove_read_later'
      | 'add_collection'
      | 'remove_collection'
      | 'add_tags'
      | 'remove_tags'
    rating?: number
    collection_id?: number
    tags?: string[]
  }) =>
    apiFetch<{ operation_id: string; status: string; affected: number }>(
      '/api/explorer/operations/action',
      { method: 'POST', body: JSON.stringify(body) },
    ),
  mergePreview: (body: { gallery_ids: number[]; target_id: number }) =>
    apiFetch<{
      target_id: number
      source_ids: number[]
      scalar_conflicts: Record<string, Array<{ gallery_id: number; value: unknown }>>
      images: { add: number; exact_sha_skipped: number; similar_kept_for_review: number }
      result: {
        source_routes: '404'
        sources_moved_to_trash: number
        restore_reverses_merge: false
      }
    }>('/api/explorer/merge/preview', { method: 'POST', body: JSON.stringify(body) }),
  merge: (body: {
    gallery_ids: number[]
    target_id: number
    scalar_sources?: Record<string, number>
  }) =>
    apiFetch<{
      operation_id: string
      status: string
      target_id: number
      source_ids: number[]
      images_added: number
      exact_sha_skipped: number
      similar_kept_for_review: number
      source_routes: '404'
    }>('/api/explorer/merge', { method: 'POST', body: JSON.stringify(body) }),
  metadataHistory: (galleryId: number) =>
    apiFetch<{
      gallery_id: number
      fields: Record<
        string,
        { origin: string; locked: boolean; source_value: unknown; updated_at: string }
      >
      changes: Array<{
        id: number
        field: string
        old_value: unknown
        new_value: unknown
        origin: string
        created_at: string
      }>
    }>(`/api/explorer/galleries/${galleryId}/metadata-history`),
  physicalEntries: (libraryId: number, path = '', offset = 0, limit = 100) =>
    apiFetch<{
      library_id: number
      path: string
      read_only: true
      total: number
      entries: ExplorerPhysicalEntry[]
      folder_stats: {
        physical_bytes: number
        file_count: number
        media_count: number
        updated_at: string
      } | null
      size_status: 'ready' | 'pending'
    }>(`/api/explorer/physical/${libraryId}/entries${qs({ path, offset, limit })}`),
  physicalPreviewUrl: (libraryId: number, path: string) =>
    `/api/explorer/physical/${libraryId}/preview${qs({ path })}`,
  refreshPhysicalSize: (libraryId: number, path = '') =>
    apiFetch<{ status: string; path: string }>(
      `/api/explorer/physical/${libraryId}/refresh-size${qs({ path })}`,
      { method: 'POST' },
    ),
  importPhysicalFolder: (libraryId: number, path: string) =>
    apiFetch<{ status: string; path: string; job_id: string | null }>(
      `/api/explorer/physical/${libraryId}/import${qs({ path })}`,
      { method: 'POST' },
    ),
}
