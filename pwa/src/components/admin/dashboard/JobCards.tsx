'use client'

import { AlertTriangle, Pause, X, Play, Square } from 'lucide-react'
import { t } from '@/lib/i18n'
import type { DashboardSiteStats, DashboardTiming, DownloadJob } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { formatMs, formatElapsed } from '@/components/admin/dashboard/helpers'

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

const MODE_LABEL_KEY: Partial<Record<NonNullable<DownloadJob['mode']>, string>> = {
  subscription_initial: 'queue.modeInitial',
  subscription_incremental: 'queue.modeIncremental',
  repair: 'queue.modeRepair',
}

export function ActiveJobCard({
  job,
  onPause,
  onResume,
  onStop,
  onDiscard,
}: {
  job: DownloadJob
  onPause: (id: string) => void
  onResume: (id: string) => void
  onStop: (job: DownloadJob) => void
  onDiscard: (job: DownloadJob) => void
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
  // The job stays active until the worker has kept what it fetched.
  const isStopping = !!job.stop_requested_at
  // A repair's files are wanted, so it has no discard (the server treats cancel as stop).
  const canDiscard = job.mode !== 'repair'
  const modeLabelKey = job.mode ? MODE_LABEL_KEY[job.mode] : undefined

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl p-4">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-vault-text truncate">{title}</span>
            {modeLabelKey && (
              <span className="text-[11px] font-medium text-vault-text-secondary border border-vault-border px-1.5 py-0.5 rounded">
                {t(modeLabelKey)}
              </span>
            )}
            {isStopping && (
              <span className="text-[11px] font-medium text-vault-accent bg-vault-accent/10 px-1.5 py-0.5 rounded">
                {t('queue.stopping')}
              </span>
            )}
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
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onResume(job.id)}
              disabled={isStopping}
              className="hover:text-green-400 hover:bg-green-500/10"
              title={t('downloadDashboard.resume')}
            >
              <Play size={14} />
            </Button>
          ) : (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onPause(job.id)}
              disabled={isStopping}
              className="hover:text-yellow-400 hover:bg-yellow-500/10"
              title={t('downloadDashboard.pause')}
            >
              <Pause size={14} />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onStop(job)}
            disabled={isStopping}
            className="text-vault-accent hover:text-vault-accent hover:bg-vault-accent/10"
            title={isStopping ? t('queue.stopping') : t('queue.stop')}
            aria-label={isStopping ? t('queue.stopping') : t('queue.stop')}
          >
            <Square size={14} />
          </Button>
          {canDiscard && (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onDiscard(job)}
              disabled={isStopping}
              className="hover:text-red-400 hover:bg-red-500/10"
              title={t('queue.discard')}
              aria-label={t('queue.discard')}
            >
              <X size={14} />
            </Button>
          )}
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

export function QueuedJobRow({
  job,
  siteStats,
}: {
  job: DownloadJob
  siteStats: Record<string, DashboardSiteStats>
}) {
  const isWaitingForSourceSlot = job.progress?.wait_reason === 'source_slot'
  const semaphoreKey =
    typeof job.progress?.semaphore_key === 'string' && job.progress.semaphore_key
      ? job.progress.semaphore_key
      : null
  const stats = semaphoreKey ? siteStats[semaphoreKey] : undefined
  const detail = isWaitingForSourceSlot
    ? t('downloadDashboard.waitingForSlot', {
        source: semaphoreKey ?? job.source,
        used: stats ? String(stats.semaphore.used) : '?',
        max: stats ? String(stats.semaphore.max) : '?',
      })
    : job.source

  const title = job.progress?.title ?? job.url

  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-vault-border/50 last:border-0">
      <div className="flex-1 min-w-0">
        <p className="text-sm text-vault-text truncate">{title}</p>
        <p className="text-xs text-vault-text-muted mt-0.5">{detail}</p>
      </div>
      <span className="text-xs text-vault-text-muted shrink-0">{job.source}</span>
    </div>
  )
}
