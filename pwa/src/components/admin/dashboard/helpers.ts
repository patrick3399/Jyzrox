import { t } from '@/lib/i18n'
import type { DashboardSiteStats } from '@/lib/types'

export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export function formatElapsed(ms: number): string {
  const secs = Math.floor(ms / 1000)
  const mins = Math.floor(secs / 60)
  const hrs = Math.floor(mins / 60)
  if (hrs > 0) return `${hrs}h ${mins % 60}m`
  if (mins > 0) return `${mins}m ${secs % 60}s`
  return `${secs}s`
}

export function getSiteStatus(stats: DashboardSiteStats): {
  label: string
  color: string
} {
  if (stats.running === 0 && stats.queued === 0)
    return { label: t('downloadDashboard.statusIdle'), color: 'text-vault-text-muted' }
  if (stats.adaptive.sleep_multiplier >= 4)
    return { label: t('downloadDashboard.statusThrottled'), color: 'text-red-400' }
  if (stats.adaptive.sleep_multiplier > 1)
    return { label: t('downloadDashboard.statusBackingOff'), color: 'text-orange-400' }
  if (stats.semaphore.used >= stats.semaphore.max)
    return { label: t('downloadDashboard.statusBusy'), color: 'text-yellow-400' }
  return { label: t('downloadDashboard.statusOk'), color: 'text-green-400' }
}

// ── Sub-components ────────────────────────────────────────────────────
