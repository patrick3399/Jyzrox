'use client'

import { useState, useCallback, useEffect } from 'react'
import { Download, X, Plus, Trash2, Pause, Play, ChevronRight, Globe } from 'lucide-react'
import { toast } from 'sonner'
import {
  useDownloadJobs,
  useEnqueueDownload,
  useCancelJob,
  useClearFinishedJobs,
  usePauseJob,
  useCheckUrl,
  useSupportedSites,
} from '@/hooks/useDownloadQueue'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { t } from '@/lib/i18n'
import type { DownloadJob } from '@/lib/types'

const STATUS_STYLES: Record<string, string> = {
  queued: 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400',
  running: 'bg-blue-500/10 border-blue-500/30 text-blue-400',
  done: 'bg-green-500/10 border-green-500/30 text-green-400',
  failed: 'bg-red-500/10 border-red-500/30 text-red-400',
  cancelled: 'bg-vault-card border-vault-border text-vault-text-muted',
  paused: 'bg-orange-500/10 border-orange-500/30 text-orange-400',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs font-medium ${STATUS_STYLES[status] ?? STATUS_STYLES.cancelled}`}
    >
      {status === 'running' && (
        <span className="flex gap-0.5">
          <span className="w-1 h-1 rounded-full bg-blue-400 animate-bounce [animation-delay:0ms]" />
          <span className="w-1 h-1 rounded-full bg-blue-400 animate-bounce [animation-delay:150ms]" />
          <span className="w-1 h-1 rounded-full bg-blue-400 animate-bounce [animation-delay:300ms]" />
        </span>
      )}
      {status}
    </span>
  )
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

function JobRow({
  job,
  onCancel,
  onPause,
  isCancelling,
}: {
  job: DownloadJob
  onCancel: (id: string) => void
  onPause: (id: string, action: 'pause' | 'resume') => void
  isCancelling: boolean
}) {
  const canCancel = job.status === 'queued' || job.status === 'running' || job.status === 'paused'
  const createdAt = new Date(job.created_at).toLocaleString()
  const finishedAt = job.finished_at ? new Date(job.finished_at).toLocaleString() : null

  return (
    <div className="bg-vault-card border border-vault-border rounded-lg p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm truncate mb-1" title={job.url}>
            {job.url}
          </p>
          <div className="flex flex-wrap items-center gap-3 text-xs text-vault-text-muted">
            <span>
              {t('queue.source')}:{' '}
              <span className="text-vault-text-secondary">{job.source || t('common.auto')}</span>
            </span>
            <span>
              {t('queue.created')}: <span className="text-vault-text-secondary">{createdAt}</span>
            </span>
            {finishedAt && (
              <span>
                {t('queue.finished')}:{' '}
                <span className="text-vault-text-secondary">{finishedAt}</span>
              </span>
            )}
          </div>
          {job.error && <p className="mt-1 text-xs text-red-400 break-words">{job.error}</p>}
          {job.status === 'running' && job.progress && (
            <div className="mt-2">
              {typeof job.progress.downloaded === 'number' && (
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 bg-vault-border rounded-full overflow-hidden">
                    {job.progress.total ? (
                      <div
                        className="h-full bg-blue-500 rounded-full transition-all duration-300"
                        style={{
                          width: `${Math.min(100, (job.progress.downloaded / job.progress.total) * 100)}%`,
                        }}
                      />
                    ) : (
                      <div className="h-full bg-blue-500/30 rounded-full overflow-hidden relative">
                        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-blue-500/60 to-transparent animate-[shimmer_1.5s_infinite]" />
                      </div>
                    )}
                  </div>
                  <span className="text-xs text-vault-text-muted whitespace-nowrap">
                    {job.progress.downloaded}
                    {job.progress.total ? ` / ${job.progress.total}` : ''} {t('queue.files')}
                  </span>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-3 mt-1">
                {typeof job.progress.speed === 'number' && job.progress.speed > 0 && (
                  <span className="text-xs text-vault-text-muted">
                    {t('queue.filesPerMin', { count: (job.progress.speed * 60).toFixed(1) })}
                  </span>
                )}
                {job.progress.started_at && job.progress.last_update_at && (
                  <span className="text-xs text-vault-text-muted">
                    {t('queue.elapsed', {
                      time: formatDuration(
                        (new Date(job.progress.last_update_at).getTime() -
                          new Date(job.progress.started_at).getTime()) /
                          1000,
                      ),
                    })}
                  </span>
                )}
                {job.progress.total &&
                  typeof job.progress.speed === 'number' &&
                  job.progress.speed > 0 &&
                  typeof job.progress.downloaded === 'number' &&
                  job.progress.downloaded < job.progress.total && (
                    <span className="text-xs text-vault-text-muted">
                      {t('queue.remaining', {
                        time: formatDuration(
                          (job.progress.total - job.progress.downloaded) / job.progress.speed,
                        ),
                      })}
                    </span>
                  )}
                {job.progress.status_text && (
                  <span className="text-xs text-vault-text-muted">{job.progress.status_text}</span>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <StatusBadge status={job.status} />
          {job.status === 'running' && (
            <button
              onClick={() => onPause(job.id, 'pause')}
              className="p-1.5 rounded-lg bg-orange-500/10 border border-orange-500/30 hover:bg-orange-500/20 text-orange-400 transition-colors"
              title={t('queue.pause')}
            >
              <Pause size={14} />
            </button>
          )}
          {job.status === 'paused' && (
            <button
              onClick={() => onPause(job.id, 'resume')}
              className="p-1.5 rounded-lg bg-green-500/10 border border-green-500/30 hover:bg-green-500/20 text-green-400 transition-colors"
              title={t('queue.resume')}
            >
              <Play size={14} />
            </button>
          )}
          {canCancel && (
            <button
              onClick={() => onCancel(job.id)}
              disabled={isCancelling}
              className="p-1.5 rounded-lg bg-red-500/10 border border-red-500/30 hover:bg-red-500/20 text-red-400 transition-colors disabled:opacity-50"
              title={t('queue.cancel')}
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function QueuePage() {
  const [urlInput, setUrlInput] = useState('')
  const [sitesOpen, setSitesOpen] = useState(false)
  const [debouncedUrl, setDebouncedUrl] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedUrl(urlInput), 300)
    return () => clearTimeout(timer)
  }, [urlInput])

  const { data: checkResult } = useCheckUrl(debouncedUrl)
  const { data: sitesData } = useSupportedSites()

  const { data, isLoading, error, mutate } = useDownloadJobs({})
  const { trigger: enqueue, isMutating: isEnqueuing } = useEnqueueDownload()
  const { trigger: cancelJob } = useCancelJob()
  const { trigger: clearJobs, isMutating: isClearing } = useClearFinishedJobs()
  const { trigger: pauseJob } = usePauseJob()

  const handleEnqueue = useCallback(async () => {
    const url = urlInput.trim()
    if (!url) return
    try {
      const result = await enqueue({ url })
      toast.success(`${t('queue.queuedSuccess')} (job: ${result.job_id})`)
      setUrlInput('')
      await mutate()
      if (result.warning) {
        const warningMap: Record<string, string> = {
          'eh_credentials_recommended': 'credential.ehRecommended',
          'pixiv_credentials_required': 'credential.pixivRequired',
        }
        const i18nKey = warningMap[result.warning] || result.warning
        toast(t(i18nKey), { icon: '⚠️' })
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to enqueue download')
    }
  }, [urlInput, enqueue, mutate])

  const handleCancel = useCallback(
    async (id: string) => {
      try {
        await cancelJob(id)
        await mutate()
      } catch {
        toast.error(t('queue.cancelError'))
      }
    },
    [cancelJob, mutate],
  )

  const handlePause = useCallback(
    async (id: string, action: 'pause' | 'resume') => {
      try {
        await pauseJob({ id, action })
        await mutate()
      } catch {
        toast.error(t('queue.pauseError'))
      }
    },
    [pauseJob, mutate],
  )

  const handleClear = useCallback(async () => {
    try {
      const result = await clearJobs()
      toast.success(t('queue.cleared', { count: String(result.deleted) }))
      await mutate()
    } catch {
      toast.error(t('queue.clearError'))
    }
  }, [clearJobs, mutate])

  const allJobs = data?.jobs ?? []
  const activeJobs = allJobs.filter(
    (j) => j.status === 'queued' || j.status === 'running' || j.status === 'paused',
  )
  const completedJobs = allJobs.filter(
    (j) => j.status === 'done' || j.status === 'failed' || j.status === 'cancelled',
  )

  const statusOrder: Record<string, number> = { running: 0, paused: 1, queued: 2 }
  const sortedActive = [...activeJobs].sort((a, b) => {
    const orderDiff = (statusOrder[a.status] ?? 3) - (statusOrder[b.status] ?? 3)
    if (orderDiff !== 0) return orderDiff
    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  })
  const sortedCompleted = [...completedJobs].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">{t('queue.title')}</h1>

        {/* Add Download Form */}
        <div className="bg-vault-card border border-vault-border rounded-lg p-4 mb-6">
          <h2 className="text-sm font-semibold text-vault-text-muted uppercase tracking-wide mb-3">
            {t('queue.addDownload')}
          </h2>
          <div className="flex gap-2">
            <input
              type="text"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleEnqueue()}
              placeholder={t('queue.urlPlaceholder')}
              className="flex-1 bg-vault-input border border-vault-border rounded-lg px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-border-hover text-sm"
            />
            <button
              onClick={handleEnqueue}
              disabled={isEnqueuing || !urlInput.trim()}
              className="flex items-center gap-1.5 px-4 py-2 bg-vault-accent hover:bg-vault-accent/90 disabled:opacity-40 rounded-lg text-white text-sm font-medium transition-colors"
            >
              <Plus size={16} />
              {isEnqueuing ? t('queue.adding') : t('queue.add')}
            </button>
          </div>
          {/* URL Recognition Badge */}
          {debouncedUrl.trim() && checkResult && (
            <div className="mt-2 flex items-center gap-2">
              {checkResult.supported ? (
                checkResult.source_id !== 'gallery_dl' ? (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-500/10 border border-green-500/30 text-green-400 text-xs font-medium">
                    <Globe size={12} />
                    {checkResult.name}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 text-xs font-medium">
                    <Globe size={12} />
                    {t('queue.supportedViaGalleryDl')}
                  </span>
                )
              ) : null}
            </div>
          )}
        </div>

        {/* Supported Sites */}
        <div className="bg-vault-card border border-vault-border rounded-lg mb-6 overflow-hidden">
          <button
            onClick={() => setSitesOpen((o) => !o)}
            className="w-full flex items-center justify-between px-4 py-3 text-sm text-vault-text-muted hover:text-vault-text-secondary transition-colors"
          >
            <span className="flex items-center gap-2">
              <Globe size={14} />
              {t('queue.supportedSites')}
            </span>
            <ChevronRight
              size={14}
              className={`transition-transform ${sitesOpen ? 'rotate-90' : ''}`}
            />
          </button>
          {sitesOpen && sitesData?.categories && (
            <div className="px-4 pb-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {Object.entries(sitesData.categories).map(([category, sites]) => (
                <div key={category}>
                  <h3 className="text-xs font-semibold text-vault-text-muted uppercase tracking-wide mb-2">
                    {t(`queue.category${category.charAt(0).toUpperCase() + category.slice(1)}`)}
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {sites.map((site) => (
                      <span
                        key={site.source_id}
                        className="inline-flex items-center px-2 py-0.5 rounded bg-vault-border/50 text-xs text-vault-text-secondary"
                      >
                        {site.name}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
              <div className="col-span-full text-xs text-vault-text-muted mt-1">
                {t('queue.moreViaGalleryDl')}
              </div>
            </div>
          )}
        </div>

        {isLoading && (
          <div className="flex justify-center py-16">
            <LoadingSpinner />
          </div>
        )}

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-4 text-red-400 text-sm">
            {error.message || t('common.failedToLoad')}
          </div>
        )}

        {/* Active Jobs */}
        {!isLoading && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-vault-text-muted uppercase tracking-wide">
                {t('queue.active')} ({sortedActive.length})
              </h2>
              <span className="text-xs text-vault-text-muted">{t('queue.autoRefresh')}</span>
            </div>

            {sortedActive.length === 0 ? (
              <EmptyState icon={Download} title={t('queue.noActive')} />
            ) : (
              <div className="space-y-2">
                {sortedActive.map((job) => (
                  <JobRow
                    key={job.id}
                    job={job}
                    onCancel={handleCancel}
                    onPause={handlePause}
                    isCancelling={false}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Completed Jobs */}
        {!isLoading && sortedCompleted.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-vault-text-muted uppercase tracking-wide">
                {t('queue.completedFailed')} ({sortedCompleted.length})
              </h2>
              <button
                onClick={handleClear}
                disabled={isClearing || sortedCompleted.length === 0}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-vault-card border border-vault-border hover:bg-red-500/10 hover:border-red-500/30 hover:text-red-400 text-vault-text-muted transition-colors disabled:opacity-40"
              >
                <Trash2 size={13} />
                {isClearing ? t('queue.clearing') : t('queue.clear')}
              </button>
            </div>

            <div className="space-y-2">
              {sortedCompleted.map((job) => (
                <JobRow
                  key={job.id}
                  job={job}
                  onCancel={handleCancel}
                  onPause={handlePause}
                  isCancelling={false}
                />
              ))}
            </div>
          </div>
        )}
    </div>
  )
}
