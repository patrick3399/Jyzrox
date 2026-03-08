'use client'

import { useState, useCallback } from 'react'
import { Download, ChevronUp, ChevronDown, X, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { useDownloadJobs, useEnqueueDownload, useCancelJob } from '@/hooks/useDownloadQueue'
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
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs font-medium ${STATUS_STYLES[status] ?? STATUS_STYLES.cancelled}`}>
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

function JobRow({
  job,
  onCancel,
  isCancelling,
}: {
  job: DownloadJob
  onCancel: (id: string) => void
  isCancelling: boolean
}) {
  const canCancel = job.status === 'queued' || job.status === 'running'
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
            <span>{t('queue.source')}: <span className="text-vault-text-secondary">{job.source || t('common.auto')}</span></span>
            <span>{t('queue.created')}: <span className="text-vault-text-secondary">{createdAt}</span></span>
            {finishedAt && <span>{t('queue.finished')}: <span className="text-vault-text-secondary">{finishedAt}</span></span>}
          </div>
          {job.error && (
            <p className="mt-1 text-xs text-red-400 break-words">{job.error}</p>
          )}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          <StatusBadge status={job.status} />
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
  const [completedOpen, setCompletedOpen] = useState(false)

  const { data, isLoading, error, mutate } = useDownloadJobs({})
  const { trigger: enqueue, isMutating: isEnqueuing } = useEnqueueDownload()
  const { trigger: cancelJob } = useCancelJob()

  const handleEnqueue = useCallback(async () => {
    const url = urlInput.trim()
    if (!url) return
    try {
      const result = await enqueue({ url })
      toast.success(`${t('queue.queuedSuccess')} (job: ${result.job_id})`)
      setUrlInput('')
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to enqueue download')
    }
  }, [urlInput, enqueue, mutate])

  const handleCancel = useCallback(async (id: string) => {
    try {
      await cancelJob(id)
      mutate()
    } catch {
      toast.error(t('queue.cancelError'))
    }
  }, [cancelJob, mutate])

  const allJobs = data?.jobs ?? []
  const activeJobs = allJobs.filter((j) => j.status === 'queued' || j.status === 'running')
  const completedJobs = allJobs.filter((j) => j.status === 'done' || j.status === 'failed' || j.status === 'cancelled')

  const sortedActive = [...activeJobs].sort((a, b) => {
    if (a.status === 'running' && b.status !== 'running') return -1
    if (b.status === 'running' && a.status !== 'running') return 1
    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  })
  const sortedCompleted = [...completedJobs].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  )

  return (
    <div className="min-h-screen">
      <div className="max-w-4xl mx-auto px-4 py-6">
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
                  <JobRow key={job.id} job={job} onCancel={handleCancel} isCancelling={false} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Completed Jobs */}
        {!isLoading && sortedCompleted.length > 0 && (
          <div>
            <button
              onClick={() => setCompletedOpen((o) => !o)}
              className="flex items-center justify-between w-full text-left mb-3"
            >
              <h2 className="text-sm font-semibold text-vault-text-muted uppercase tracking-wide">
                {t('queue.completedFailed')} ({sortedCompleted.length})
              </h2>
              {completedOpen ? <ChevronUp size={16} className="text-vault-text-muted" /> : <ChevronDown size={16} className="text-vault-text-muted" />}
            </button>

            {completedOpen && (
              <div className="space-y-2">
                {sortedCompleted.map((job) => (
                  <JobRow key={job.id} job={job} onCancel={handleCancel} isCancelling={false} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
