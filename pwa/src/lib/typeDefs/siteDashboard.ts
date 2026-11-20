import type { DownloadJob } from './ehDownloadTags'

// ── Site Config (Admin) ──────────────────────────────────────────────

/** Pacing value in seconds: fixed, a [min, max] range, or null (nothing set). */
export type SiteSleepValue = number | [number, number] | null

export interface SiteDownloadParams {
  retries: number
  http_timeout: number
  /** Pause between gallery-dl API / page requests. */
  sleep_request: SiteSleepValue
  /** Pause between individual file downloads (gallery-dl `extractor.<cat>.sleep`). */
  sleep_download: SiteSleepValue
  concurrency: number
  inactivity_timeout: number
  /** ADR 0022: spread manual downloads across egress personas (concurrency becomes per-persona). */
  spread_personas: boolean
}

export type SiteDownloadKey = keyof SiteDownloadParams

export interface SiteConfigItem {
  source_id: string
  name: string
  domain: string
  category: string
  /** Effective values. */
  download: SiteDownloadParams
  /** Jyzrox-layer defaults (same keys as `download`). */
  defaults: SiteDownloadParams
  /** Keys present in the stored override. */
  overridden: SiteDownloadKey[]
  /** Keys auto-tuned by the adaptive layer (and not overridden). */
  adaptive: SiteDownloadKey[]
  /** gallery-dl built-in pacing, applies when the effective sleep value is null. */
  extractor_defaults: {
    sleep_request: SiteSleepValue
    sleep_download: SiteSleepValue
  }
  field_mapping?: Record<string, string | null>
  auto_probe?: ProbeResult | null
}

export interface ProbeField {
  key: string
  field_type: string
  sample_value: string
  level: string
}

export interface ProbeFieldMapping {
  jyzrox_field: string
  gdl_field: string | null
  confidence: number
  suggested: boolean
}

export interface ProbeResult {
  success: boolean
  error?: string
  raw_metadata: Record<string, unknown>[]
  fields: ProbeField[]
  suggested_mappings: ProbeFieldMapping[]
  detected_source?: string
}

// ── Download Dashboard ──────────────────────────────────────────────

export interface DashboardTiming {
  semaphore_wait_ms: number
  total_pause_ms: number
  avg_page_ms: number
  last_page_ms: number
  idle_ms: number
  idle_timeout_ms: number
  started_at: string
  elapsed_ms: number
}

export interface DashboardSiteStats {
  semaphore: { used: number; max: number }
  queued: number
  running: number
  avg_speed: number
  current_delay_ms: number
  adaptive: {
    sleep_multiplier: number
    last_429_at: string | null
  }
}

export interface DashboardGlobal {
  boost_mode: boolean
  total_running: number
  total_queued: number
  total_today: number
}

export interface DashboardSystem {
  disk_free_gb: number
  disk_ok: boolean
}

export interface DashboardResponse {
  active_jobs: DownloadJob[]
  queued_jobs: DownloadJob[]
  site_stats: Record<string, DashboardSiteStats>
  global: DashboardGlobal
  system: DashboardSystem
}

// ── SAQ Queue Admin ──────────────────────────────────────────────────

export interface SaqJob {
  key: string
  function: string
  status: string
  is_cron: boolean
  kwargs: Record<string, unknown>
  result: string | null
  error: string | null
  queued: number | null
  started: number | null
  completed: number | null
  progress: number
  attempts: number
  meta: Record<string, unknown>
}

export interface SaqWorker {
  id: string
  stats: { complete: number; failed: number; retried: number; aborted: number; uptime: number }
}

export interface QueueOverview {
  name: string
  queued: number
  active: number
  scheduled: number
  workers: SaqWorker[]
}

export interface LibraryFacets {
  sources: { value: string; label: string; count: number }[]
  categories: { name: string; count: number }[]
  uncategorized: number
}

export interface GalleryCategoryDef {
  id: number
  name: string
  color: string
  sort_order: number
  is_builtin: boolean
  gallery_count: number
}

export interface GalleryCategoriesResponse {
  categories: GalleryCategoryDef[]
  palette: string[]
  uncategorized_count: number
}

export interface CategoryBackfillResult {
  dry_run: boolean
  matched: number
  applied: number
}
