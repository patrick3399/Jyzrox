// ── E-Hentai (proxy browse) ──────────────────────────────────────────

export interface EhGallery {
  gid: number
  token: string
  title: string
  title_jpn: string
  category: string
  thumb: string
  uploader: string
  posted_at: number // Unix timestamp
  pages: number
  filesize?: number
  rating: number
  torrent_count?: number
  tags: string[]
  expunged: boolean
}

export interface EhSearchResult {
  galleries: EhGallery[]
  total: number
  page: number
  next_gid?: number | null // cursor for next page
  has_prev?: boolean // whether previous page exists
}

export interface EhBrowseGalleryStatus {
  gallery_id: number
  download_status: string
  downloaded: boolean
  last_page: number
  is_local_favorite: boolean
}

export interface EhFavCategory {
  index: number
  name: string
  count: number
}

export interface EhFavoritesResult {
  galleries: EhGallery[]
  total: number
  has_next: boolean
  has_prev: boolean
  next_cursor: string | null
  prev_cursor: string | null
  categories: EhFavCategory[]
}

export interface EhFavoriteState {
  is_favorited: boolean
  category: number | null
  note: string
}

export interface EhGalleryRelationship {
  gid: number
  token: string
  title: string
}

export interface EhGalleryRelationships {
  parent: EhGalleryRelationship | null
  newer_versions: EhGalleryRelationship[]
}

export interface EhImageMap {
  gid: number
  images: Record<string, string> // { "1": "image_page_token", ... }
  previews: Record<string, string> // { "1": "thumb_url" or "sprite_url|offsetX|w|h", ... }
}

// ── Download ──────────────────────────────────────────────────────────

/**
 * What a job is for, decided when it is enqueued. Only the subscription modes and
 * `repair` change what the user can do with a job (a repair is never discarded).
 */
export type DownloadJobMode =
  'download' | 'subscription_initial' | 'subscription_incremental' | 'repair'

export interface DownloadJob {
  id: string
  url: string
  source: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'paused' | 'partial'
  /** Absent on an API that predates download modes; treat as `download`. */
  mode?: DownloadJobMode
  /** Set once the user asked to stop and keep; the job still runs until the worker finishes it. */
  stop_requested_at?: string | null
  gallery_id?: number | null
  gallery_source?: string
  gallery_source_id?: string
  subscription_id?: number | null
  options?: Record<string, unknown>
  progress: {
    percent?: number
    downloaded?: number
    total?: number
    skipped?: number
    outcome?: 'already_saved' | 'stopped'
    existing_pages?: number | null
    status_text?: string
    speed?: number
    started_at?: string
    last_update_at?: string
    wait_reason?: 'source_slot' | 'persona_cooldown'
    wait_started_at?: string
    semaphore_key?: string
    queue_position?: number
    failed_pages?: number[]
    permanently_failed?: boolean
    gallery_id?: number
    title?: string
    current_file?: string
    current_file_page?: number
    gdl_state?:
      | 'starting'
      | 'downloading'
      | 'sleeping'
      | 'rate_limited'
      | 'retrying'
      | 'paused'
      | 'cancelled'
      | 'done'
    gdl_state_seconds?: number
    recent_log?: string[]
    import_skipped?: { duplicate: number; excluded: number; invalid: number }
    [key: string]: unknown
  }
  error: string | null
  created_at: string
  finished_at: string | null
  retry_count: number
  max_retries: number
  next_retry_at: string | null
  /** Egress persona the job runs under (ADR 0022); null/absent when not in persona mode. */
  persona?: string | null
}

// ── Tags ─────────────────────────────────────────────────────────────

export interface TagItem {
  id: number
  namespace: string
  name: string
  count: number
  translation?: string
}

export interface TagAlias {
  alias_namespace: string
  alias_name: string
  canonical_id: number
  canonical_namespace: string
  canonical_name: string
}

export interface TagImplication {
  antecedent_id: number
  consequent_id: number
  antecedent: string // "namespace:name"
  consequent: string // "namespace:name"
}

// ── Tag Health Report ───────────────────────────────────────────────

export interface TagHealthDuplicateGroup {
  key: string
  tags: TagItem[]
}

export interface TagHealthCycleNode {
  id: number
  namespace: string
  name: string
}

export interface TagHealthCycle {
  key: string
  path: TagHealthCycleNode[]
}

export interface TagHealthReport {
  orphans: TagItem[]
  orphans_total: number
  duplicates: TagHealthDuplicateGroup[]
  implication_cycles: TagHealthCycle[]
  ignored_count: number
}
