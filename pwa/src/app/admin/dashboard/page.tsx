'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Activity,
  Zap,
  HardDrive,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Pause,
  X,
  Play,
  ChevronDown,
} from 'lucide-react'
import { toast } from 'sonner'
import useSWR from 'swr'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useProfile } from '@/hooks/useProfile'
import { useDashboard } from '@/hooks/useDashboard'
import { api } from '@/lib/api'
import type { DashboardSiteStats, DashboardTiming, DownloadJob } from '@/lib/types'

// ── Helpers ───────────────────────────────────────────────────────────

function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatElapsed(ms: number): string {
  const secs = Math.floor(ms / 1000)
  const mins = Math.floor(secs / 60)
  const hrs = Math.floor(mins / 60)
  if (hrs > 0) return `${hrs}h ${mins % 60}m`
  if (mins > 0) return `${mins}m ${secs % 60}s`
  return `${secs}s`
}

function getSiteStatus(stats: DashboardSiteStats): {
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

function GlobalBar({
  running,
  queued,
  today,
  boostMode,
  diskOk,
  diskFreeGb,
  onToggleBoost,
  toggling,
}: {
  running: number
  queued: number
  today: number
  boostMode: boolean
  diskOk: boolean
  diskFreeGb: number
  onToggleBoost: () => void
  toggling: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-vault-card border border-vault-border text-sm">
        <Activity size={14} className="text-blue-400" />
        <span className="text-vault-text-secondary">{t('downloadDashboard.running')}</span>
        <span className="font-semibold text-vault-text">{running}</span>
      </div>
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-vault-card border border-vault-border text-sm">
        <Loader2 size={14} className="text-vault-text-muted" />
        <span className="text-vault-text-secondary">{t('downloadDashboard.queued')}</span>
        <span className="font-semibold text-vault-text">{queued}</span>
      </div>
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-vault-card border border-vault-border text-sm">
        <CheckCircle2 size={14} className="text-green-400" />
        <span className="text-vault-text-secondary">{t('downloadDashboard.today')}</span>
        <span className="font-semibold text-vault-text">{today}</span>
      </div>

      {/* Boost mode toggle */}
      <button
        onClick={onToggleBoost}
        disabled={toggling}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-sm transition-colors ${
          boostMode
            ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400 hover:bg-yellow-500/20'
            : 'bg-vault-card border-vault-border text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover'
        }`}
        title={boostMode ? t('downloadDashboard.boostModeOn') : t('downloadDashboard.boostModeOff')}
      >
        <Zap size={14} />
        <span>{t('downloadDashboard.boostMode')}</span>
        <span className="font-semibold">
          {boostMode ? t('downloadDashboard.toggleBoostOff') : t('downloadDashboard.toggleBoostOn')}
        </span>
      </button>

      {/* Disk indicator */}
      <div
        className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-sm ${
          diskOk
            ? 'bg-vault-card border-vault-border text-vault-text-secondary'
            : 'bg-red-500/10 border-red-500/30 text-red-400'
        }`}
      >
        <HardDrive size={14} />
        <span>{diskOk ? t('downloadDashboard.diskOk') : t('downloadDashboard.diskLow')}</span>
        <span className="font-semibold">
          {t('downloadDashboard.diskFreeGb', { gb: diskFreeGb.toFixed(1) })}
        </span>
      </div>
    </div>
  )
}

function SiteTable({ siteStats }: { siteStats: Record<string, DashboardSiteStats> }) {
  const entries = Object.entries(siteStats)
  if (entries.length === 0) return null

  return (
    <div>
      <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wider mb-3">
        {t('downloadDashboard.siteTable')}
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-vault-text-muted text-xs uppercase tracking-wider border-b border-vault-border">
              <th className="text-left pb-2 pr-4">{t('downloadDashboard.site')}</th>
              <th className="text-left pb-2 pr-4">{t('downloadDashboard.slots')}</th>
              <th className="text-right pb-2 pr-4">{t('downloadDashboard.queue')}</th>
              <th className="text-right pb-2 pr-4">{t('downloadDashboard.speed')}</th>
              <th className="text-right pb-2 pr-4">{t('downloadDashboard.delay')}</th>
              <th className="text-right pb-2">{t('downloadDashboard.status')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-vault-border/50">
            {entries.map(([site, stats]) => {
              const { label, color } = getSiteStatus(stats)
              const slotPct =
                stats.semaphore.max > 0 ? (stats.semaphore.used / stats.semaphore.max) * 100 : 0
              return (
                <tr key={site} className="hover:bg-vault-card-hover/30 transition-colors">
                  <td className="py-2.5 pr-4 font-medium text-vault-text">{site}</td>
                  <td className="py-2.5 pr-4">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 rounded-full bg-vault-input overflow-hidden">
                        <div
                          className="h-full rounded-full bg-blue-500 transition-all"
                          style={{ width: `${slotPct}%` }}
                        />
                      </div>
                      <span className="text-vault-text-secondary text-xs whitespace-nowrap">
                        {stats.semaphore.used}/{stats.semaphore.max}
                      </span>
                    </div>
                  </td>
                  <td className="py-2.5 pr-4 text-right text-vault-text-secondary">
                    {stats.queued}
                  </td>
                  <td className="py-2.5 pr-4 text-right text-vault-text-secondary">
                    {stats.avg_speed > 0
                      ? t('downloadDashboard.pagesPerSec', {
                          speed: stats.avg_speed.toFixed(2),
                        })
                      : '—'}
                  </td>
                  <td className="py-2.5 pr-4 text-right text-vault-text-secondary">
                    {stats.current_delay_ms > 0 ? formatMs(stats.current_delay_ms) : '—'}
                  </td>
                  <td className={`py-2.5 text-right font-medium ${color}`}>{label}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function JobTimingChips({
  semWaitMs,
  avgPageMs,
  idleMs,
  idleTimeoutMs,
}: {
  semWaitMs: number
  avgPageMs: number
  idleMs: number
  idleTimeoutMs: number
}) {
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {semWaitMs > 0 && (
        <span className="text-[11px] px-2 py-0.5 rounded-full bg-vault-input text-vault-text-secondary">
          {t('downloadDashboard.semWait')}: {formatMs(semWaitMs)}
        </span>
      )}
      {avgPageMs > 0 && (
        <span className="text-[11px] px-2 py-0.5 rounded-full bg-vault-input text-vault-text-secondary">
          {t('downloadDashboard.avgPage')}: {formatMs(avgPageMs)}
        </span>
      )}
      {idleMs > 0 && (
        <span className="text-[11px] px-2 py-0.5 rounded-full bg-vault-input text-vault-text-secondary">
          {t('downloadDashboard.idle')}: {formatMs(idleMs)} / {formatMs(idleTimeoutMs)}
        </span>
      )}
    </div>
  )
}

function ActiveJobCard({
  job,
  onPause,
  onResume,
  onCancel,
}: {
  job: DownloadJob
  onPause: (id: string) => void
  onResume: (id: string) => void
  onCancel: (id: string) => void
}) {
  const timing = job.progress?.timing as Partial<DashboardTiming> | undefined

  const isStalling =
    timing &&
    typeof timing.idle_ms === 'number' &&
    typeof timing.idle_timeout_ms === 'number' &&
    timing.idle_timeout_ms > 0 &&
    timing.idle_ms > timing.idle_timeout_ms * 0.6

  const downloaded = job.progress?.downloaded ?? 0
  const total = job.progress?.total ?? 0
  const percent = total > 0 ? Math.round((downloaded / total) * 100) : 0
  const speed = job.progress?.speed ?? 0
  const title = job.progress?.title ?? job.url
  const isPaused = job.status === 'paused'

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl p-4">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-vault-text truncate">{title}</span>
            {isStalling && (
              <span className="flex items-center gap-1 text-[11px] font-bold text-orange-400 bg-orange-500/10 border border-orange-500/20 px-1.5 py-0.5 rounded-full">
                <AlertTriangle size={10} />
                {t('downloadDashboard.stalling')}
              </span>
            )}
          </div>
          <p className="text-xs text-vault-text-muted mt-0.5 truncate">{job.source}</p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {isPaused ? (
            <button
              onClick={() => onResume(job.id)}
              className="p-1.5 rounded-lg text-vault-text-secondary hover:text-green-400 hover:bg-green-500/10 transition-colors"
              title={t('downloadDashboard.resume')}
            >
              <Play size={14} />
            </button>
          ) : (
            <button
              onClick={() => onPause(job.id)}
              className="p-1.5 rounded-lg text-vault-text-secondary hover:text-yellow-400 hover:bg-yellow-500/10 transition-colors"
              title={t('downloadDashboard.pause')}
            >
              <Pause size={14} />
            </button>
          )}
          <button
            onClick={() => onCancel(job.id)}
            className="p-1.5 rounded-lg text-vault-text-secondary hover:text-red-400 hover:bg-red-500/10 transition-colors"
            title={t('downloadDashboard.cancel')}
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 rounded-full bg-vault-input overflow-hidden mb-2">
        <div
          className="h-full rounded-full bg-blue-500 transition-all duration-500"
          style={{ width: `${Math.min(100, percent)}%` }}
        />
      </div>

      <div className="flex items-center justify-between text-xs text-vault-text-muted">
        <span>
          {downloaded}/{total > 0 ? total : '?'}
        </span>
        {speed > 0 && (
          <span>{t('downloadDashboard.pagesPerSec', { speed: speed.toFixed(2) })}</span>
        )}
        {timing?.elapsed_ms !== undefined && (
          <span>
            {t('downloadDashboard.elapsed')}: {formatElapsed(timing.elapsed_ms)}
          </span>
        )}
      </div>

      {timing && (
        <JobTimingChips
          semWaitMs={timing.semaphore_wait_ms ?? 0}
          avgPageMs={timing.avg_page_ms ?? 0}
          idleMs={timing.idle_ms ?? 0}
          idleTimeoutMs={timing.idle_timeout_ms ?? 0}
        />
      )}
    </div>
  )
}

function QueuedJobRow({
  job,
  siteStats,
}: {
  job: DownloadJob
  siteStats: Record<string, DashboardSiteStats>
}) {
  const stats = siteStats[job.source]
  const waitReason = stats
    ? t('downloadDashboard.waitingForSlot', {
        source: job.source,
        used: String(stats.semaphore.used),
        max: String(stats.semaphore.max),
      })
    : job.source

  const title = job.progress?.title ?? job.url

  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-vault-border/50 last:border-0">
      <div className="flex-1 min-w-0">
        <p className="text-sm text-vault-text truncate">{title}</p>
        <p className="text-xs text-vault-text-muted mt-0.5">{waitReason}</p>
      </div>
      <span className="text-xs text-vault-text-muted shrink-0">{job.source}</span>
    </div>
  )
}

// ── Event category filter helpers ─────────────────────────────────────

type EventCategory = 'all' | 'download' | 'gallery' | 'import' | 'system'

function getEventCategory(eventType: string): EventCategory {
  if (eventType.startsWith('download')) return 'download'
  if (eventType.startsWith('gallery')) return 'gallery'
  if (eventType.startsWith('import')) return 'import'
  return 'system'
}

const EVENT_CATEGORY_COLORS: Record<EventCategory, string> = {
  all: 'bg-vault-input text-vault-text-secondary',
  download: 'bg-blue-500/10 text-blue-400',
  gallery: 'bg-purple-500/10 text-purple-400',
  import: 'bg-green-500/10 text-green-400',
  system: 'bg-orange-500/10 text-orange-400',
}

function eventBadgeClass(eventType: string): string {
  const cat = getEventCategory(eventType)
  return EVENT_CATEGORY_COLORS[cat]
}

function RecentEvents() {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<EventCategory>('all')
  const { data } = useSWR(open ? 'system/events' : null, () => api.system.getEvents(50), {
    refreshInterval: 10000,
  })

  const categories: EventCategory[] = ['all', 'download', 'gallery', 'import', 'system']
  const filtered =
    data?.events.filter((e) => filter === 'all' || getEventCategory(e.event_type) === filter) ?? []

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
      {/* Collapsible header */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-vault-card-hover/30 transition-colors"
      >
        <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wider">
          {t('adminEvents.title')}
        </h2>
        <ChevronDown
          size={16}
          className={`text-vault-text-muted transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="border-t border-vault-border">
          {/* Category filter chips */}
          <div className="flex flex-wrap gap-1.5 px-4 pt-3 pb-2">
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setFilter(cat)}
                className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                  filter === cat
                    ? 'bg-vault-accent text-white'
                    : 'bg-vault-input text-vault-text-muted hover:text-vault-text'
                }`}
              >
                {t(
                  `adminEvents.filter${cat.charAt(0).toUpperCase()}${cat.slice(1)}` as Parameters<
                    typeof t
                  >[0],
                )}
              </button>
            ))}
          </div>

          {/* Table */}
          <div className="overflow-x-auto px-4 pb-4">
            {filtered.length === 0 ? (
              <p className="text-sm text-vault-text-muted py-4 text-center">
                {t('adminEvents.noEvents')}
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-vault-text-muted text-xs uppercase tracking-wider border-b border-vault-border">
                    <th className="text-left pb-2 pr-4 font-medium">{t('adminEvents.colTime')}</th>
                    <th className="text-left pb-2 pr-4 font-medium">{t('adminEvents.colType')}</th>
                    <th className="text-left pb-2 pr-4 font-medium">
                      {t('adminEvents.colResource')}
                    </th>
                    <th className="text-left pb-2 font-medium">{t('adminEvents.colActor')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-vault-border/50">
                  {filtered.map((event, idx) => (
                    <tr key={idx} className="hover:bg-vault-card-hover/30 transition-colors">
                      <td className="py-2 pr-4 text-vault-text-muted text-xs whitespace-nowrap tabular-nums">
                        {new Date(event.timestamp).toLocaleString()}
                      </td>
                      <td className="py-2 pr-4">
                        <span
                          className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-medium ${eventBadgeClass(event.event_type)}`}
                        >
                          {event.event_type}
                        </span>
                      </td>
                      <td className="py-2 pr-4 text-vault-text-secondary text-xs">
                        {event.resource_type && event.resource_id
                          ? `${event.resource_type}:${event.resource_id}`
                          : (event.resource_type ?? '—')}
                      </td>
                      <td className="py-2 text-vault-text-secondary text-xs">
                        {event.actor_user_id != null
                          ? `#${event.actor_user_id}`
                          : t('adminEvents.actorSystem')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────

export default function DownloadDashboardPage() {
  useLocale()
  const router = useRouter()
  const { data: profile, isLoading: profileLoading } = useProfile()
  const { data, isLoading, mutate } = useDashboard()
  const [toggling, setToggling] = useState(false)

  // Admin guard
  if (!profileLoading && profile?.role !== 'admin') {
    router.replace('/')
    return null
  }

  const handleToggleBoost = async () => {
    if (!data) return
    setToggling(true)
    try {
      await api.settings.setRateLimitOverride(!data.global.boost_mode)
      await mutate()
    } catch {
      toast.error(t('common.errorOccurred'))
    } finally {
      setToggling(false)
    }
  }

  const handleJobAction = async (id: string, action: 'pause' | 'resume' | 'cancel') => {
    try {
      if (action === 'pause') await api.download.pauseJob(id)
      else if (action === 'resume') await api.download.resumeJob(id)
      else await api.download.cancelJob(id)
      await mutate()
    } catch {
      toast.error(t(action === 'cancel' ? 'queue.cancelError' : 'queue.pauseError'))
    }
  }

  if (isLoading || profileLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Loader2 className="animate-spin text-vault-text-muted" size={24} />
      </div>
    )
  }

  if (!data) {
    return <div className="p-6 text-vault-text-muted text-sm">{t('common.failedToLoad')}</div>
  }

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Activity size={22} className="text-vault-accent shrink-0" />
        <h1 className="text-xl font-semibold text-vault-text">{t('downloadDashboard.title')}</h1>
      </div>

      {/* Global status bar */}
      <GlobalBar
        running={data.global.total_running}
        queued={data.global.total_queued}
        today={data.global.total_today}
        boostMode={data.global.boost_mode}
        diskOk={data.system.disk_ok}
        diskFreeGb={data.system.disk_free_gb}
        onToggleBoost={handleToggleBoost}
        toggling={toggling}
      />

      {/* Per-site table */}
      {Object.keys(data.site_stats).length > 0 && (
        <div className="bg-vault-card border border-vault-border rounded-xl p-4">
          <SiteTable siteStats={data.site_stats} />
        </div>
      )}

      {/* Active jobs */}
      <div>
        <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wider mb-3">
          {t('downloadDashboard.activeJobs')}
        </h2>
        {data.active_jobs.length === 0 ? (
          <p className="text-sm text-vault-text-muted py-4 text-center">
            {t('downloadDashboard.noActiveJobs')}
          </p>
        ) : (
          <div className="space-y-3">
            {data.active_jobs.map((job) => (
              <ActiveJobCard
                key={job.id}
                job={job}
                onPause={(id) => handleJobAction(id, 'pause')}
                onResume={(id) => handleJobAction(id, 'resume')}
                onCancel={(id) => handleJobAction(id, 'cancel')}
              />
            ))}
          </div>
        )}
      </div>

      {/* Queued jobs */}
      <div>
        <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wider mb-3">
          {t('downloadDashboard.queuedJobs')}
        </h2>
        {data.queued_jobs.length === 0 ? (
          <p className="text-sm text-vault-text-muted py-4 text-center">
            {t('downloadDashboard.noQueuedJobs')}
          </p>
        ) : (
          <div className="bg-vault-card border border-vault-border rounded-xl px-4">
            {data.queued_jobs.map((job) => (
              <QueuedJobRow key={job.id} job={job} siteStats={data.site_stats} />
            ))}
          </div>
        )}
      </div>

      {/* Recent events */}
      <RecentEvents />
    </div>
  )
}
