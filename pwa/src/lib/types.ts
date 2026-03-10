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
  rating: number // 0–5
  favorited: boolean
  uploader: string
  artist_id: string | null
  download_status: 'proxy_only' | 'partial' | 'complete'
  import_mode: string | null
  tags_array: string[]
  cover_thumb?: string | null
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
}

export interface ArtistImageItem extends GalleryImage {
  gallery_title: string
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
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'paused'
  progress: {
    percent?: number
    downloaded?: number
    total?: number
    status_text?: string
    speed?: number
    started_at?: string
    last_update_at?: string
    [key: string]: unknown
  }
  error: string | null
  created_at: string
  finished_at: string | null
}

// ── Tags ─────────────────────────────────────────────────────────────

export interface TagItem {
  id: number
  namespace: string
  name: string
  count: number
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
  type: 'alert' | 'ping'
  message?: string
  ts?: string
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

export interface PluginInfo {
  name: string
  source_id: string
  version: string
  url_patterns: string[]
  credential_schema: FieldDef[]
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
}

export interface PixivUserResult {
  user: PixivUserDetail
  recent_illusts: PixivIllust[]
  next_offset: number | null
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
}

// ── File Explorer ────────────────────────────────────────────────────

export interface LibraryDirectory {
  gallery_id: number
  title: string
  category: string | null
  file_count: number
  rating: number
  favorited: boolean
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

// ── API Params ────────────────────────────────────────────────────────

export interface GallerySearchParams {
  q?: string
  tags?: string[]
  exclude_tags?: string[]
  favorited?: boolean
  min_rating?: number
  source?: string
  artist?: string
  import_mode?: string
  page?: number
  cursor?: string
  limit?: number
  sort?: 'added_at' | 'rating' | 'pages'
  collection?: number
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
}
