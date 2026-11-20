export type UserRole = 'admin' | 'member' | 'viewer'

export interface UserInfo {
  id: number
  username: string
  email: string | null
  role: UserRole
  created_at: string | null
  last_login_at: string | null
}

// ── Local Library ────────────────────────────────────────────────────

export interface Gallery {
  id: number
  source: string
  source_id: string
  title: string
  title_jpn: string
  category: string
  language: string
  pages: number
  source_pages?: number | null
  missing_pages?: number | null
  posted_at: string | null
  added_at: string
  content_updated_at?: string | null
  rating: number // 0–5 (legacy global, kept for backward compat)
  favorited: boolean // legacy, always false now
  is_favorited: boolean // per-user favorite status
  my_rating: number | null // per-user rating, null if not rated
  in_reading_list: boolean
  uploader: string
  artist_id: string | null
  artist_name?: string | null
  download_status:
    'proxy_only' | 'partial' | 'complete' | 'downloading' | 'importing' | 'failed' | 'missing'
  import_mode: string | null
  tags_array: string[]
  cover_thumb?: string | null
  display_order?: 'asc' | 'desc'
  source_url?: string | null
  source_path?: string | null
  deleted_at?: string | null
  metadata_updated_at?: string | null
  media_stats?: GalleryMediaStats
}

export type TrashReason = 'user' | 'merged' | 'source_missing'

/** Reason filter values accepted by the trash endpoints ("unknown" = no recorded reason). */
export type TrashReasonFilter = TrashReason | 'unknown'
export type TrashSort = 'deleted_at' | 'title' | 'pages' | 'size'
export type TrashSortDirection = 'asc' | 'desc'

/** Filter params shared by GET /trash, GET /trash/summary and POST /trash/empty. */
export interface TrashFilters {
  q?: string
  source?: string
  reason?: TrashReasonFilter
}

/** Response of GET /api/library/trash/summary. */
export interface TrashSummary {
  count: number
  logical_bytes: number
  reclaimable_bytes: number
  next_expiry_at: string | null
  sources: string[]
  purge: { done: number; total: number } | null
}

/** Response of POST /trash/empty and /trash/purge (202 queued, or 200 ok with total 0). */
export interface TrashPurgeQueued {
  status: 'queued' | 'ok'
  total: number
}

/** Item of GET /api/library/trash. */
export interface TrashGallery extends Gallery {
  deleted_at: string
  /** null = trashed before the reason column existed. */
  deleted_reason: TrashReason | null
  deleted_by: { id: number; username: string } | null
  merged_into: { source: string; source_id: string; title: string | null } | null
  cover_thumb: string | null
}

export interface TrashPreviewImage {
  id: number
  page_num: number
  thumb_path: string | null
  thumb_srcset: string | null
  media_type: string
  pending: boolean
}

/** Response of GET /api/library/trash/{gallery_id}/preview. */
export interface TrashPreview {
  gallery: TrashGallery
  media: { total_size: number; counts: { image: number; gif: number; video: number } }
  images: TrashPreviewImage[]
  images_total: number
  page: number
}

/** Size and per-type counts over the pages the Reader shows (detail endpoint only). */
export interface GalleryMediaStats {
  total_size: number
  image_count: number
  gif_count: number
  video_count: number
}

export interface GallerySyncResult {
  status:
    | 'synced'
    | 'unchanged'
    | 'busy'
    | 'not_link'
    | 'not_found'
    | 'skipped_trashed'
    | 'root_unavailable'
    | 'source_missing'
  changed: boolean
  added: number
  removed: number
  renamed: number
  replaced: number
  pending: number
  pages: number | null
}

export interface GalleryImage {
  id: number
  gallery_id: number
  page_num: number
  filename: string | null
  width: number | null
  height: number | null
  file_path: string | null
  thumb_path: string | null
  thumb_srcset?: string | null
  file_size: number | null
  file_hash: string | null
  media_type: 'image' | 'video' | 'gif'
  duration: number | null
  thumbhash?: string | null
  /** Link page registered but not hashed yet: original file readable, no thumbnail. */
  pending?: boolean
  visibility?: 'active' | 'user_hidden' | 'source_missing' | 'replaced'
  source_item_id?: string | null
  source_item_url?: string | null
  source_position?: number | null
  source_seen_at?: string | null
  hidden_at?: string | null
  source_work?: {
    id: number
    source_item_id: string
    source_item_url: string | null
    title: string | null
    published_at: string | null
    page_count: number
    position: number | null
    status: 'active' | 'source_missing'
    metadata: Record<string, unknown>
  }
  source_work_page?: number | null
}

export interface BrowseImage {
  id: number
  gallery_id: number
  page_num: number
  width: number | null
  height: number | null
  thumb_path: string | null
  thumb_srcset?: string | null
  file_path: string | null
  thumbhash: string | null
  media_type: 'image' | 'video' | 'gif'
  added_at: string | null
  source: string | null
  source_id: string | null
}

export interface ImageBrowserResponse {
  images: BrowseImage[]
  next_cursor: string | null
  has_next: boolean
  favorited_image_ids: number[]
}

export interface ImageTimeRangeResponse {
  min_at: string | null
  max_at: string | null
}

export interface TimelinePercentilesResponse {
  timestamps: string[]
  total_buckets: number
}

export interface ArtistImageItem extends GalleryImage {
  gallery_title: string
  gallery_source: string
  gallery_source_id: string
}

export interface ArtistDetail {
  artist_id: string
  artist_name: string
  source: string
  gallery_count: number
  total_pages: number
  total_images: number
  latest_added_at: string | null
  cover_thumb: string | null
}

export interface ReadProgress {
  gallery_id: number
  last_page: number
  last_read_at: string | null
}
