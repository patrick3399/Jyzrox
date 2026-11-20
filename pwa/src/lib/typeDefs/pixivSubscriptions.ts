// ── Pixiv Types ──────────────────────────────────────────────────────

export interface PixivImageUrls {
  square_medium: string
  medium: string
  large: string
  original?: string
}

export interface PixivTag {
  name: string
  translated_name: string | null
}

export interface PixivUser {
  id: number
  name: string
  account: string
  profile_image: string
}

export interface PixivIllust {
  id: number
  title: string
  type: string
  image_urls: PixivImageUrls
  caption: string
  user: PixivUser
  tags: PixivTag[]
  create_date: string
  page_count: number
  width: number
  height: number
  sanity_level: number
  total_view: number
  total_bookmarks: number
  is_bookmarked: boolean
}

export interface PixivSearchResult {
  illusts: PixivIllust[]
  next_offset: number | null
}

export interface PixivUserDetail {
  id: number
  name: string
  account: string
  profile_image: string
  comment: string
  total_illusts: number
  total_manga: number
  total_novels: number
  is_followed: boolean
}

export interface PixivUserResult {
  user: PixivUserDetail
  recent_illusts: PixivIllust[]
  next_offset: number | null
}

export interface PixivCollectionState {
  gallery_id: number | null
  gallery_source_id: string | null
  subscribed: boolean
  subscription_id: number | null
  job_id: string | null
  job_status: string | null
  work_count: number
  missing_count: number
}

export interface PixivUserPreview {
  user: {
    id: number
    name: string
    account: string
    profile_image: string
    is_followed?: boolean
  }
  illusts: PixivIllust[]
}

export interface FollowedArtist {
  id: number
  source: string
  artist_id: string
  artist_name: string | null
  artist_avatar: string | null
  cover_thumb: string | null
  last_checked_at: string | null
  last_illust_id: string | null
  auto_download: boolean
  added_at: string | null
}

// ── Scheduled Tasks ─────────────────────────────────────────────────

export interface ScheduledTask {
  id: string
  name: string
  description: string
  enabled: boolean
  cron_expr: string
  default_cron: string
  next_run: string | null
  last_run: string | null
  last_status: string | null
  last_error: string | null
}

export interface DatabaseBackup {
  id: string
  status: string
  created_at: string | null
  filename: string | null
  manifest: string
  size_bytes: number | null
  sha256: string | null
  app_version: string | null
  database: string | null
  exists: boolean
  error: string | null
}

// ── Subscription Groups ─────────────────────────────────────────────

export interface SubscriptionGroup {
  id: number
  name: string
  schedule: string
  concurrency: number
  enabled: boolean
  priority: number
  is_system: boolean
  status: string
  last_run_at: string | null
  last_completed_at: string | null
  created_at: string | null
  updated_at: string | null
  sub_count: number
}

// ── Subscriptions ───────────────────────────────────────────────────

/** Per-job media selection carried in `options.media` / `download_options.media`. */
export interface MediaPolicy {
  max_files: number | null
  include_videos: boolean
}

export type SubscriptionPauseReason = 'manual' | 'rate_limited' | 'auth'

export interface SubscriptionRun {
  total: number
  queued: number
  running: number
  paused: number
  done: number
  stopped: number
  failed: number
  partial: number
  cancelled: number
}

export interface Subscription {
  id: number
  name: string | null
  url: string
  source: string | null
  source_id: string | null
  avatar_url: string | null
  enabled: boolean
  auto_download: boolean
  cron_expr: string | null
  last_checked_at: string | null
  last_item_id: string | null
  last_status: string
  last_error: string | null
  next_check_at: string | null
  created_at: string | null
  last_job_id: string | null
  group_id: number | null
  paused_at?: string | null
  paused_reason?: SubscriptionPauseReason | null
  paused_until?: string | null
  checking?: boolean
  download_options?: Record<string, unknown>
  gallery_id?: number | null
  gallery_source?: string | null
  gallery_source_id?: string | null
  gallery_title?: string | null
}

/** GET /api/subscriptions/by-gallery/{id}: the caller's subscription covering a gallery. */
export interface GallerySubscriptionLink {
  subscription: Subscription | null
  /** True only without a subscription, when the gallery is an account the caller can subscribe to. */
  can_subscribe: boolean
  subscribe_url: string | null
}

// ── File Explorer ────────────────────────────────────────────────────

export interface LibraryDirectory {
  gallery_id: number
  source_id: string
  title: string
  category: string | null
  file_count: number
  rating: number // legacy
  favorited: boolean // legacy
  is_favorited: boolean // per-user
  my_rating: number | null // per-user
  source: string | null
  import_mode?: string | null
  artist_id?: string | null
  uploader?: string | null
  library_path?: string | null
  source_path?: string | null
  disk_size: number
}

export interface SourceStat {
  source: string
  import_mode: string | null
  gallery_count: number
  file_count: number
  disk_size: number
}

export interface LibraryFile {
  filename: string
  page_num: number | null
  width: number | null
  height: number | null
  file_size: number | null
  media_type: string
  thumb_path: string | null
  thumb_srcset?: string | null
  file_path: string | null
  is_symlink: boolean
  is_broken: boolean
  symlink_target: string | null
}
