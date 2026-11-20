// ── Settings ──────────────────────────────────────────────────────────

export interface CredentialStatus {
  configured: boolean
  /** Name of the active account. */
  account?: string
  /** How many accounts are stored for this source. */
  accounts?: number
}

export interface CredentialAccount {
  account: string
  credential_type: string
  is_active: boolean
}

export type Credentials = Record<string, CredentialStatus>

// ── Egress Personas (Admin, ADR 0022) ─────────────────────────────────

export interface EgressPersona {
  id: number
  name: string
  proxy_url: string | null
  user_agent: string | null
  browser_profile: 'chrome' | 'firefox' | null
  enabled: boolean
  last_exit_ip: string | null
  last_tested_at: string | null
  accounts: { source: string; account: string }[]
}

export interface PersonaTestResult {
  ip: string | null
  colo: string | null
  same_ip: string[]
  same_subnet: string[]
}

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
  token?: string // raw token, only present right after creation
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
  versions: {
    jyzrox: string | null
    python: string | null
    fastapi: string | null
    gallery_dl: string | null
    postgresql: string | null
    redis: string | null
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
  /** Redis used_memory in bytes. */
  total_memory: number
  /** Redis used_memory_human, e.g. "10.73M". */
  total_memory_human: string
  total_keys: number
  breakdown: Record<string, number>
}

// ── WebSocket ────────────────────────────────────────────────────────

/** Full original EventBus event carried on every WS message (lossless
 * passthrough). Top-level legacy fields on WsMessage are derived from this;
 * new consumers should prefer reading `event`. */
export interface WsEventPayload {
  event_type: string
  resource_type?: string | null
  resource_id?: string | number | null
  actor_user_id?: number | null
  data?: Record<string, unknown>
}

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
  // Lossless passthrough of the original EventBus event (BR-004):
  event?: WsEventPayload
  // Log entry payload
  log?: unknown
  // gdl_upgrade fields (gallery-dl upgrade/rollback outcome):
  old_version?: string | null
  new_version?: string | null
  error?: string | null
  rollback?: boolean
}

export interface GdlUpgradeEvent {
  status: 'ok' | 'failed' | 'rejected'
  old_version: string | null
  new_version: string | null
  error: string | null
  rollback: boolean
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
