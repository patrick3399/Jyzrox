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
  rating: number           // 0–5
  favorited: boolean
  uploader: string
  download_status: 'proxy_only' | 'partial' | 'complete'
  tags_array: string[]
}

export interface GalleryImage {
  id: number
  gallery_id: number
  page_num: number
  filename: string | null
  width: number | null
  height: number | null
  file_path: string | null   // e.g. /data/gallery/ehentai/1234567/0001.jpg
  thumb_path: string | null  // e.g. /data/thumbs/ab/abcdef.../thumb_160.webp
  file_size: number | null
  file_hash: string | null
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
  posted_at: number      // Unix timestamp
  pages: number
  rating: number
  tags: string[]
  expunged: boolean
}

export interface EhSearchResult {
  galleries: EhGallery[]
  total: number
  page: number
}

export interface EhImageMap {
  gid: number
  images: Record<string, string>  // { "1": "image_page_token", ... }
}

// ── Download ──────────────────────────────────────────────────────────

export interface DownloadJob {
  id: string
  url: string
  source: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  progress: Record<string, unknown>
  error: string | null
  created_at: string
  finished_at: string | null
}

// ── Settings ──────────────────────────────────────────────────────────

export interface CredentialStatus {
  configured: boolean
}

export interface Credentials {
  ehentai: CredentialStatus
  pixiv: CredentialStatus
}

export interface EhAccount {
  valid: boolean
  credits?: number
  hath_perks?: number
  error?: string
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
}

// ── WebSocket ────────────────────────────────────────────────────────

export interface WsMessage {
  type: 'alert' | 'ping'
  message?: string
  ts?: string
}

// ── API Params ────────────────────────────────────────────────────────

export interface GallerySearchParams {
  q?: string
  tags?: string[]
  exclude_tags?: string[]
  favorited?: boolean
  min_rating?: number
  source?: string
  page?: number
  limit?: number
  sort?: 'added_at' | 'rating' | 'pages'
}

export interface EhSearchParams {
  q?: string
  page?: number
  category?: string
}

export interface JobListParams {
  status?: string
  page?: number
  limit?: number
}
