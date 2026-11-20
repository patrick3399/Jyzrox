// ── Dedup ────────────────────────────────────────────────────────────

export interface DedupStats {
  total_blobs: number // blobs with phash
  needs_t2: number
  needs_t3: number
  same_gallery_only: number
  pending_review: number
  whitelisted: number
  resolved: number
}

export interface RelationshipBlob {
  sha256: string
  thumb_url: string | null
  thumb_srcset?: string | null
  image_url: string | null
  width: number | null
  height: number | null
  file_size: number | null
  extension: string
  media_type: string
  occurrences: RelationshipOccurrence[]
}

export interface RelationshipOccurrence {
  image_id: number
  gallery_id: number
  gallery_title: string | null
  source: string
  source_id: string
  page_num: number
  filename: string | null
}

export interface RelationshipItem {
  id: number
  relationship: 'needs_review' | 'quality_conflict' | 'variant'
  hamming_dist: number | null
  blob_a: RelationshipBlob
  blob_b: RelationshipBlob
  suggested_keep: string | null
  reason: string | null
  diff_score: number | null
  diff_type: string | null
}

export interface DedupReviewResponse {
  items: RelationshipItem[]
  next_cursor: string | null
}

export interface DedupScanProgress {
  status: 'idle' | 'running' | 'paused'
  current?: number
  total?: number
  tier?: 1 | 2 | 3
  mode?: 'reset' | 'pending'
  percent?: number
  last_status?: 'completed' | 'failed' | null
  last_started?: string | null
  last_finished?: string | null
  last_error?: string | null
}

// ── Rate Limits ───────────────────────────────────────────────────────

export interface SiteRateConfig {
  concurrency: number
  delay_ms: number | null
  image_concurrency: number | null
  page_delay_ms?: number | null
  pagination_delay_ms?: number | null
  illust_delay_ms?: number | null
}

export interface RateLimitSchedule {
  enabled: boolean
  start_hour: number
  end_hour: number
  mode: 'full_speed' | 'standard'
}

export interface RateLimitSettings {
  sites: Record<string, SiteRateConfig>
  schedule: RateLimitSchedule
  override_active: boolean
  schedule_active: boolean
}

// ── API Params ────────────────────────────────────────────────────────

export interface GallerySearchParams {
  q?: string
  tags?: string[]
  exclude_tags?: string[]
  favorited?: boolean
  in_reading_list?: boolean
  min_rating?: number
  source?: string
  artist?: string
  import_mode?: string
  page?: number
  cursor?: string
  limit?: number
  sort?: 'added_at' | 'content_updated_at' | 'rating' | 'pages'
  collection?: number
  category?: string
}

export interface EhSearchParams {
  q?: string
  page?: number
  next_gid?: number
  prev?: boolean
  category?: string
  f_cats?: number
  advance?: boolean
  adv_search?: number
  min_rating?: number
  page_from?: number
  page_to?: number
  language?: string
}

export interface JobListParams {
  status?: string
  page?: number
  limit?: number
  exclude_subscription?: boolean
  subscription_only?: boolean
  active_only?: boolean
}

// ── Download Preview ──────────────────────────────────────────────────

export interface DownloadPreview {
  source: string
  preview_available: boolean
  title?: string | null
  pages?: number | null
  tags?: string[] | null
  uploader?: string | null
  rating?: number | null
  thumb_url?: string | null
  category?: string | null
}
