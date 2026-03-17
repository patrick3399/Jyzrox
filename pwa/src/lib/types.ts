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
  posted_at: string | null
  added_at: string
  rating: number // 0–5 (legacy global, kept for backward compat)
  favorited: boolean // legacy, always false now
  is_favorited: boolean // per-user favorite status
  my_rating: number | null // per-user rating, null if not rated
  in_reading_list: boolean
  uploader: string
  artist_id: string | null
  download_status: 'proxy_only' | 'partial' | 'complete' | 'downloading'
  import_mode: string | null
  tags_array: string[]
  cover_thumb?: string | null
  display_order?: 'asc' | 'desc'
  source_url?: string | null
  deleted_at?: string | null
  metadata_updated_at?: string | null
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
  file_size: number | null
  file_hash: string | null
  media_type: 'image' | 'video' | 'gif'
  duration: number | null
  thumbhash?: string | null
}

export interface BrowseImage {
  id: number
  gallery_id: number
  page_num: number
  width: number | null
  height: number | null
  thumb_path: string | null
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
  rating: number
  tags: string[]
  expunged: boolean
}

export interface EhSearchResult {
  galleries: EhGallery[]
  total: number
  page: number
  next_gid?: number | null  // cursor for next page
  has_prev?: boolean         // whether previous page exists
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

export interface EhImageMap {
  gid: number
  images: Record<string, string> // { "1": "image_page_token", ... }
  previews: Record<string, string> // { "1": "thumb_url" or "sprite_url|offsetX|w|h", ... }
}

// ── Download ──────────────────────────────────────────────────────────

export interface DownloadJob {
  id: string
  url: string
  source: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'paused' | 'partial'
  gallery_id?: number | null
  gallery_source?: string
  gallery_source_id?: string
  subscription_id?: number | null
  progress: {
    percent?: number
    downloaded?: number
    total?: number
    status_text?: string
    speed?: number
    started_at?: string
    last_update_at?: string
    failed_pages?: number[]
    permanently_failed?: boolean
    gallery_id?: number
    title?: string
    [key: string]: unknown
  }
  error: string | null
  created_at: string
  finished_at: string | null
  retry_count: number
  max_retries: number
  next_retry_at: string | null
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

// ── Settings ──────────────────────────────────────────────────────────

export interface CredentialStatus {
  configured: boolean
}

export type Credentials = Record<string, CredentialStatus>

export interface EhAccount {
  valid: boolean
  credits?: number
  hath_perks?: number
  error?: string
  use_ex?: boolean
}

// ── API Tokens ──────────────────────────────────────────────────────

export interface ApiTokenInfo {
  id: string
  name: string | null
  token?: string        // raw token, only present right after creation
  token_prefix?: string // first 8 chars of hash, from list API
  created_at: string | null
  last_used_at: string | null
  expires_at: string | null
}

// ── Sessions ─────────────────────────────────────────────────────

export interface SessionInfo {
  token_prefix: string
  ip: string
  user_agent: string
  created_at: string | null
  ttl: number
  is_current: boolean
}

// ── System ────────────────────────────────────────────────────────────

export interface SystemHealth {
  status: string
  services: { postgres: string; redis: string }
}

export interface SystemInfo {
  version: string
  eh_max_concurrency: number
  tag_model_enabled: boolean
  versions: {
    jyzrox: string | null
    python: string | null
    fastapi: string | null
    gallery_dl: string | null
    postgresql: string | null
    redis: string | null
    onnxruntime: string | null
  }
}

export interface StorageMount {
  label: string
  path: string
  total: number
  used: number
  free: number
  percent: number
}

export interface StorageInfo {
  mounts: StorageMount[]
}

// ── EH Comments ──────────────────────────────────────────────────────

export interface EhComment {
  poster: string
  posted_at: string
  text: string
  score: number | null
}

// ── Browse History ────────────────────────────────────────────────────

export interface BrowseHistoryItem {
  id: number
  source: string
  source_id: string
  title: string
  thumb: string | null
  gid: number | null
  token: string | null
  viewed_at: string
}

// ── Saved Searches ────────────────────────────────────────────────────

export interface SavedSearch {
  id: number
  name: string
  query: string
  params: Record<string, unknown>
  created_at: string
}

// ── Tag Blocking ──────────────────────────────────────────────────────

export interface BlockedTag {
  id: number
  namespace: string
  name: string
}

// ── Cache Stats ───────────────────────────────────────────────────────

export interface CacheStats {
  total_memory: string
  total_keys: number
  breakdown: Record<string, number>
}

// ── WebSocket ────────────────────────────────────────────────────────

export interface WsMessage {
  type: 'alert' | 'ping' | 'job_update' | 'subscription_checked' | string
  message?: string
  ts?: string
  // job_update fields:
  job_id?: string
  status?: string
  progress?: Record<string, unknown>
  // subscription_checked fields:
  sub_id?: number
  new_works?: number
  user_id?: number
  // New EventBus fields:
  event_type?: string
  resource_type?: string
  resource_id?: number | string
  data?: Record<string, unknown>
  // Log entry payload
  log?: unknown
}

export interface LogEntry {
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'
  source: string
  logger: string
  message: string
  timestamp: string
  traceback?: string | null
}

export interface LogLevelConfig {
  levels: Record<string, string>
}

// ── Pagination responses ──────────────────────────────────────────────

export interface ArtistSummary {
  artist_id: string
  artist_name: string
  source: string
  gallery_count: number
  total_pages: number
  cover_thumb: string | null
  latest_added_at: string | null
}

/** Page-based response (total always present) */
export interface GalleryListResponse {
  galleries: Gallery[]
  /** Present in page-based responses */
  total?: number
  /** Present in cursor-based responses */
  next_cursor?: string | null
  /** Present in cursor-based responses */
  has_next?: boolean
}

export interface Collection {
  id: number
  name: string
  description: string | null
  cover_gallery_id: number | null
  gallery_count: number
  cover_thumb: string | null
  created_at: string | null
  updated_at: string | null
}

/** Page-based tag list response */
export interface TagListResponse {
  tags: TagItem[]
  total?: number
  next_cursor?: string | null
  has_next?: boolean
}

// ── Plugin System ────────────────────────────────────────────────────

export interface FieldDef {
  name: string
  field_type: 'text' | 'password' | 'textarea' | 'select'
  label: string
  required: boolean
  placeholder: string
}

export interface BrowseSchema {
  search_fields: FieldDef[]
  supports_favorites: boolean
  supports_popular: boolean
  supports_toplist: boolean
}

export interface OAuthConfig {
  auth_url_endpoint: string
  callback_endpoint: string
  display_name: string
}

export interface CredentialFlow {
  flow_type: 'fields' | 'oauth' | 'login'
  fields: FieldDef[]
  oauth_config: OAuthConfig | null
  login_endpoint: string | null
  verify_endpoint: string | null
}

export interface PluginInfo {
  name: string
  source_id: string
  version: string
  url_patterns: string[]
  credential_schema: FieldDef[]
  credential_flows: CredentialFlow[]
  has_browse: boolean
  browse_schema: BrowseSchema | null
  credential_configured: boolean
  enabled: boolean
}

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

export interface PixivUserPreview {
  user: {
    id: number
    name: string
    account: string
    profile_image: string
  }
  illusts: PixivIllust[]
}

export interface FollowedArtist {
  id: number
  source: string
  artist_id: string
  artist_name: string | null
  artist_avatar: string | null
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
  last_run: string | null
  last_status: string | null
  last_error: string | null
}

// ── Subscriptions ───────────────────────────────────────────────────

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
  file_path: string | null
  is_symlink: boolean
  is_broken: boolean
  symlink_target: string | null
}

// ── Dedup ────────────────────────────────────────────────────────────

export interface DedupStats {
  total_blobs: number     // blobs with phash
  needs_t2: number
  needs_t3: number
  pending_review: number
  whitelisted: number
  resolved: number
}

export interface RelationshipBlob {
  sha256: string
  thumb_url: string | null
  image_url: string | null
  width: number | null
  height: number | null
  file_size: number | null
}

export interface RelationshipItem {
  id: number
  relationship: 'quality_conflict' | 'variant'
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
  sort?: 'added_at' | 'rating' | 'pages'
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
}

export interface JobListParams {
  status?: string
  page?: number
  limit?: number
  exclude_subscription?: boolean
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
