'use client'

import { useState, useCallback } from 'react'
import { useDownloadJobs, useEnqueueDownload, useCancelJob } from '@/hooks/useDownloadQueue'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { AlertBanner } from '@/components/AlertBanner'
import type { DownloadJob } from '@/lib/types'

const STATUS_STYLES: Record<string, string> = {
  queued: 'bg-yellow-900/40 border-yellow-700/50 text-yellow-400',
  running: 'bg-blue-900/40 border-blue-700/50 text-blue-400',
  done: 'bg-green-900/40 border-green-700/50 text-green-400',
  failed: 'bg-red-900/40 border-red-700/50 text-red-400',
  cancelled: 'bg-gray-800 border-gray-600 text-gray-500',
}

const SOURCE_OPTIONS = [
  { value: 'ehentai', label: 'E-Hentai' },
  { value: 'pixiv', label: 'Pixiv' },
]

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
    <div className="bg-[#111111] border border-[#2a2a2a] rounded-lg p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm text-white truncate mb-1" title={job.url}>
            {job.url}
          </p>
          <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
            <span>Source: <span className="text-gray-400">{job.source || 'auto'}</span></span>
            <span>Created: <span className="text-gray-400">{createdAt}</span></span>
            {finishedAt && <span>Finished: <span className="text-gray-400">{finishedAt}</span></span>}
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
              className="px-2 py-0.5 bg-red-900/30 border border-red-700/50 hover:bg-red-900/50 text-red-400 rounded text-xs transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function QueuePage() {
  const [urlInput, setUrlInput] = useState('')
  const [sourceInput, setSourceInput] = useState('ehentai')
  const [enqueueError, setEnqueueError] = useState<string | null>(null)
  const [enqueueSuccess, setEnqueueSuccess] = useState<string | null>(null)
  const [completedOpen, setCompletedOpen] = useState(false)

  const { data, isLoading, error, mutate } = useDownloadJobs({})
  const { trigger: enqueue, isMutating: isEnqueuing } = useEnqueueDownload()
  const { trigger: cancelJob } = useCancelJob()

  const handleEnqueue = useCallback(async () => {
    const url = urlInput.trim()
    if (!url) return
    setEnqueueError(null)
    setEnqueueSuccess(null)
    try {
      const result = await enqueue({ url, source: sourceInput })
      setEnqueueSuccess(`Queued successfully (job: ${result.job_id})`)
      setUrlInput('')
      mutate()
    } catch (err) {
      setEnqueueError(err instanceof Error ? err.message : 'Failed to enqueue download')
    }
  }, [urlInput, sourceInput, enqueue, mutate])

  const handleCancel = useCallback(async (id: string) => {
    try {
      await cancelJob(id)
      mutate()
    } catch {
      // silently ignore
    }
  }, [cancelJob, mutate])

  const allJobs = data?.jobs ?? []
  const activeJobs = allJobs.filter((j) => j.status === 'queued' || j.status === 'running')
  const completedJobs = allJobs.filter((j) => j.status === 'done' || j.status === 'failed' || j.status === 'cancelled')

  // Sort: running first, then queued (by created_at asc); completed by finished_at desc
  const sortedActive = [...activeJobs].sort((a, b) => {
    if (a.status === 'running' && b.status !== 'running') return -1
    if (b.status === 'running' && a.status !== 'running') return 1
    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  })
  const sortedCompleted = [...completedJobs].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  )

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <div className="max-w-4xl mx-auto px-4 py-6">
        <h1 className="text-2xl font-bold mb-6 text-white">Download Queue</h1>

        {/* Add Download Form */}
        <div className="bg-[#111111] border border-[#2a2a2a] rounded-lg p-4 mb-6">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Add Download
          </h2>
          <div className="flex gap-2">
            <input
              type="text"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleEnqueue()}
              placeholder="https://e-hentai.org/g/... or https://www.pixiv.net/..."
              className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-[#444] text-sm"
            />
            <select
              value={sourceInput}
              onChange={(e) => setSourceInput(e.target.value)}
              className="bg-[#1a1a1a] border border-[#2a2a2a] rounded px-2 py-2 text-white text-sm focus:outline-none"
            >
              {SOURCE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <button
              onClick={handleEnqueue}
              disabled={isEnqueuing || !urlInput.trim()}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-900 disabled:text-blue-600 rounded text-white text-sm font-medium transition-colors"
            >
              {isEnqueuing ? 'Adding...' : 'Add'}
            </button>
          </div>

          {enqueueSuccess && (
            <div className="mt-3">
              <AlertBanner alerts={[enqueueSuccess]} onDismiss={() => setEnqueueSuccess(null)} />
            </div>
          )}
          {enqueueError && (
            <div className="mt-3">
              <AlertBanner alerts={[enqueueError]} onDismiss={() => setEnqueueError(null)} />
            </div>
          )}
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="flex justify-center py-16">
            <LoadingSpinner />
          </div>
        )}

        {/* Fetch Error */}
        {error && (
          <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 mb-4 text-red-400 text-sm">
            {error.message || 'Failed to load jobs'}
          </div>
        )}

        {/* Active Jobs */}
        {!isLoading && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide">
                Active ({sortedActive.length})
              </h2>
              <span className="text-xs text-gray-600">Auto-refreshes every 3s</span>
            </div>

            {sortedActive.length === 0 ? (
              <div className="text-center py-10 text-gray-600 bg-[#111111] border border-[#2a2a2a] rounded-lg">
                No active downloads
              </div>
            ) : (
              <div className="space-y-2">
                {sortedActive.map((job) => (
                  <JobRow
                    key={job.id}
                    job={job}
                    onCancel={handleCancel}
                    isCancelling={false}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Completed Jobs (collapsible) */}
        {!isLoading && sortedCompleted.length > 0 && (
          <div>
            <button
              onClick={() => setCompletedOpen((o) => !o)}
              className="flex items-center justify-between w-full text-left mb-3"
            >
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide">
                Completed / Failed ({sortedCompleted.length})
              </h2>
              <span className="text-gray-500 text-sm">
                {completedOpen ? '▲ Collapse' : '▼ Expand'}
              </span>
            </button>

            {completedOpen && (
              <div className="space-y-2">
                {sortedCompleted.map((job) => (
                  <JobRow
                    key={job.id}
                    job={job}
                    onCancel={handleCancel}
                    isCancelling={false}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
