export interface SWCacheConfig {
  mediaCacheTTLHours: number
  mediaCacheSizeMB: number
  pageCacheTTLHours: number
}

export const DEFAULT_SW_CACHE_CONFIG: SWCacheConfig = {
  mediaCacheTTLHours: 72,
  mediaCacheSizeMB: 8192,
  pageCacheTTLHours: 24,
}

const STORAGE_KEY = 'sw-cache-config'

export function loadSWCacheConfig(): SWCacheConfig {
  if (typeof window === 'undefined') return DEFAULT_SW_CACHE_CONFIG
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_SW_CACHE_CONFIG
    const parsed = JSON.parse(raw)
    return { ...DEFAULT_SW_CACHE_CONFIG, ...parsed }
  } catch {
    return DEFAULT_SW_CACHE_CONFIG
  }
}

export function saveSWCacheConfig(config: SWCacheConfig): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
  sendConfigToSW(config)
}

export function sendConfigToSW(config: SWCacheConfig): void {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return
  navigator.serviceWorker.ready.then((reg) => {
    reg.active?.postMessage({ type: 'SW_CACHE_CONFIG', config })
  })
}
