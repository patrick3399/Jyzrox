// ── Library Workbench ────────────────────────────────────────────────

export interface ExplorerQuery {
  node_kind?:
    'all' | 'source' | 'category' | 'collection' | 'artist' | 'saved_search' | 'smart' | 'trash'
  node_id?: string | null
  query?: string
  sort?: 'added_at' | 'content_updated_at' | 'posted_at' | 'title' | 'rating' | 'pages' | 'size'
  direction?: 'asc' | 'desc'
  offset?: number
  limit?: number
  /** Category filter on top of the node; '__uncategorized__' means no category. */
  category?: string | null
  /** Ask for per-category counts (ignoring the category filter). */
  facets?: boolean
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
    categories?: {
      uncategorized: number
      items: Array<{ id: string; label: string; gallery_count: number; registered: boolean }>
    }
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
      hidden_images?: number
      hidden_bytes?: number
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

export type ExplorerImageVisibility = 'active' | 'hidden' | 'all'
export type ExplorerImageMedia = 'all' | 'image' | 'video' | 'gif'
export type ExplorerImageSort = 'page' | 'size'

export interface ExplorerImagesParams {
  visibility?: ExplorerImageVisibility
  media?: ExplorerImageMedia
  sort?: ExplorerImageSort
  direction?: 'asc' | 'desc'
  offset?: number
  limit?: number
}

export interface ExplorerImageItem {
  image_id: number
  /** Null for hidden images (they no longer occupy a page slot). */
  page_num: number | null
  /** Original page position, kept for hidden images. */
  source_position: number | null
  filename: string
  visibility: 'active' | 'hidden' | string
  hidden_at: string | null
  media_type: string
  file_size: number | null
  width: number | null
  height: number | null
  duration: number | null
  storage: 'cas' | 'external' | 'pending'
  shared: boolean
  thumb_path: string | null
  thumb_srcset: string | null
  file_path: string | null
}

export interface ExplorerImageSummary {
  active_count: number
  hidden_count: number
  active_bytes: number
  hidden_bytes: number
  hidden_reclaimable_bytes: number
}

export interface ExplorerGalleryImages {
  gallery_id: number
  source: string
  source_id: string
  total: number
  offset: number
  limit: number
  can_edit: boolean
  summary: ExplorerImageSummary
  items: ExplorerImageItem[]
}

export interface ExplorerPurgeResult {
  gallery_id: number
  dry_run: boolean
  purgeable: number
  purged: number
  reclaim_bytes: number
  shared_kept: number
  skipped_external: number
  skipped_not_hidden: number
  skipped_pending: number
  skipped_missing: number
  blobs_deleted: number
  operation_id: string | null
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
