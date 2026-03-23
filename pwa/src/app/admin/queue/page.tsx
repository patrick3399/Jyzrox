'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import useSWR from 'swr'
import { toast } from 'sonner'
import { ListTodo, RotateCcw, XCircle, ChevronDown, ChevronUp, Activity } from 'lucide-react'
import { useProfile } from '@/hooks/useProfile'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import type { SaqJob, SaqWorker } from '@/lib/types'

// ── Helpers ────────────────────────────────────────────────────────────

function timeAgo(ms: number | null): string {
  if (!ms) return '—'
  const diff = Date.now() - ms
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  return `${Math.floor(diff / 3600000)}h ago`
}

function formatUptime(ms: number): string {
  const h = Math.floor(ms / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

const STATUSES = ['new', 'queued', 'active', 'aborting', 'aborted', 'failed', 'complete'] as const

const STATUS_STYLES: Record<string, string> = {
  new: 'bg-gray-500/20 text-gray-400',
  queued: 'bg-yellow-500/20 text-yellow-400',
  active: 'bg-blue-500/20 text-blue-400',
  aborting: 'bg-orange-500/20 text-orange-400',
  aborted: 'bg-vault-border/50 text-vault-text-muted',
  failed: 'bg-red-500/20 text-red-400',
  complete: 'bg-green-500/20 text-green-400',
}

// ── Sub-components ─────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${STATUS_STYLES[status] ?? 'bg-gray-500/20 text-gray-400'}`}
    >
      {status}
    </span>
  )
}

function WorkersSection({ workers }: { workers: SaqWorker[] }) {
  if (workers.length === 0) {
    return (
      <p className="text-sm text-vault-text-secondary px-1">{t('admin.queue.noWorkers')}</p>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-vault-border text-vault-text-secondary">
            <th className="px-3 py-2 text-left font-medium">ID</th>
            <th className="px-3 py-2 text-right font-medium">{t('admin.queue.completed')}</th>
            <th className="px-3 py-2 text-right font-medium">{t('admin.queue.failed')}</th>
            <th className="px-3 py-2 text-right font-medium">{t('admin.queue.retried')}</th>
            <th className="px-3 py-2 text-right font-medium">{t('admin.queue.uptime')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-vault-border">
          {workers.map((w) => (
            <tr key={w.id} className="hover:bg-vault-card-hover transition-colors">
              <td className="px-3 py-2 font-mono text-vault-text truncate max-w-[12rem]">
                {w.id}
              </td>
              <td className="px-3 py-2 text-right text-green-400">{w.stats.complete}</td>
              <td className="px-3 py-2 text-right text-red-400">{w.stats.failed}</td>
              <td className="px-3 py-2 text-right text-yellow-400">{w.stats.retried}</td>
              <td className="px-3 py-2 text-right text-vault-text-secondary">
                {formatUptime(w.stats.uptime)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function JobRow({
  job,
  onRetry,
  onAbort,
}: {
  job: SaqJob
  onRetry: (key: string) => void
  onAbort: (key: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const canRetry = job.status === 'failed' || job.status === 'aborted' || job.status === 'complete'
  const canAbort = job.status === 'active' || job.status === 'queued' || job.status === 'new'

  return (
    <div
      className="border-b border-vault-border hover:bg-vault-card-hover transition-colors cursor-pointer"
      onClick={() => setExpanded((v) => !v)}
    >
      {/* Collapsed row */}
      <div className="flex items-center gap-3 px-4 py-2.5 text-sm">
        <span className="text-vault-text font-mono truncate flex-1 min-w-0">{job.function}</span>
        <StatusBadge status={job.status} />
        <span className="text-vault-text-secondary text-xs shrink-0 hidden sm:inline">
          {timeAgo(job.queued)}
        </span>
        {job.progress > 0 && job.progress < 1 && (
          <div className="w-16 h-1.5 bg-vault-border rounded-full overflow-hidden shrink-0">
            <div
              className="h-full bg-blue-400 rounded-full"
              style={{ width: `${Math.round(job.progress * 100)}%` }}
            />
          </div>
        )}
        <span className="shrink-0 text-vault-text-muted">
          {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </span>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div
          className="px-4 pb-4 space-y-3"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Timestamps */}
          <div className="flex flex-wrap gap-4 text-xs text-vault-text-secondary">
            <span>
              {t('admin.queue.queued')}: {timeAgo(job.queued)}
            </span>
            {job.started && (
              <span>{t('admin.queue.startedAt')}: {timeAgo(job.started)}</span>
            )}
            {job.completed && (
              <span>{t('admin.queue.completedAt')}: {timeAgo(job.completed)}</span>
            )}
            <span>
              {t('admin.queue.attempts')}: {job.attempts}
            </span>
          </div>

          {/* kwargs */}
          {Object.keys(job.kwargs).length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase text-vault-text-muted mb-1">
                {t('admin.queue.kwargs')}
              </p>
              <pre className="text-xs text-vault-text whitespace-pre-wrap break-all bg-vault-bg rounded p-3 font-mono">
                {JSON.stringify(job.kwargs, null, 2)}
              </pre>
            </div>
          )}

          {/* error */}
          {job.error && (
            <div>
              <p className="text-[10px] font-bold uppercase text-vault-text-muted mb-1">
                {t('admin.queue.error')}
              </p>
              <pre className="text-xs text-red-400 whitespace-pre-wrap break-all bg-red-500/5 rounded p-3 font-mono">
                {job.error}
              </pre>
            </div>
          )}

          {/* result */}
          {job.result && (
            <div>
              <p className="text-[10px] font-bold uppercase text-vault-text-muted mb-1">
                {t('admin.queue.result')}
              </p>
              <pre className="text-xs text-vault-text whitespace-pre-wrap break-all bg-vault-bg rounded p-3 font-mono">
                {job.result}
              </pre>
            </div>
          )}

          {/* actions */}
          {(canRetry || canAbort) && (
            <div className="flex gap-2 pt-1">
              {canRetry && (
                <button
                  onClick={() => onRetry(job.key)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-vault-card-hover border border-vault-border text-vault-text hover:text-vault-accent hover:border-vault-accent/50 transition-colors"
                >
                  <RotateCcw size={12} />
                  {t('admin.queue.retry')}
                </button>
              )}
              {canAbort && (
                <button
                  onClick={() => onAbort(job.key)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-vault-card-hover border border-vault-border text-vault-text hover:text-red-400 hover:border-red-500/30 transition-colors"
                >
                  <XCircle size={12} />
                  {t('admin.queue.abort')}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────

const LIMIT = 25

export default function AdminQueuePage() {
  useLocale()
  const router = useRouter()
  const { data: profile, isLoading: profileLoading } = useProfile()

  const [statusFilter, setStatusFilter] = useState('')
  const [fnFilter, setFnFilter] = useState('')
  const [offset, setOffset] = useState(0)

  // Reset pagination when filters change
  useEffect(() => {
    setOffset(0)
  }, [statusFilter, fnFilter])

  const isAdmin = profile?.role === 'admin'

  useEffect(() => {
    if (!profileLoading && profile && !isAdmin) {
      router.replace('/forbidden')
    }
  }, [profileLoading, profile, isAdmin, router])

  const { data: overview } = useSWR(
    'admin/queue/overview',
    () => api.adminQueue.overview(),
    { refreshInterval: 3000 },
  )

  const {
    data: jobsData,
    isLoading: jobsLoading,
    mutate: mutateJobs,
  } = useSWR(
    ['admin/queue/jobs', statusFilter, fnFilter, offset],
    () =>
      api.adminQueue.jobs({
        status: statusFilter || undefined,
        function: fnFilter || undefined,
        offset,
        limit: LIMIT,
      }),
    { refreshInterval: 3000 },
  )

  if (profileLoading || !profile || !isAdmin) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-vault-text-secondary text-sm">{t('common.loading')}</div>
      </div>
    )
  }

  const handleRetry = async (key: string) => {
    try {
      await api.adminQueue.retryJob(key)
      toast.success(t('admin.queue.retrySuccess'))
      mutateJobs()
    } catch {
      toast.error(t('common.error'))
    }
  }

  const handleAbort = async (key: string) => {
    try {
      await api.adminQueue.abortJob(key)
      toast.success(t('admin.queue.abortSuccess'))
      mutateJobs()
    } catch {
      toast.error(t('common.error'))
    }
  }

  const jobs = jobsData?.jobs ?? []
  const total = jobsData?.total ?? 0
  const workers = overview?.workers ?? []
  const hasNext = offset + LIMIT < total
  const hasPrev = offset > 0

  // Derive unique function names from current job list for the filter dropdown
  const functionNames = Array.from(new Set(jobs.map((j) => j.function))).sort()

  return (
    <main className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <ListTodo size={24} className="text-vault-accent shrink-0" />
        <h1 className="text-2xl font-bold text-vault-text">{t('admin.queue.title')}</h1>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-vault-card border border-vault-border rounded-xl px-4 py-3">
          <p className="text-xs text-vault-text-secondary mb-1">{t('admin.queue.active')}</p>
          <p className="text-2xl font-bold text-blue-400">{overview?.active ?? '—'}</p>
        </div>
        <div className="bg-vault-card border border-vault-border rounded-xl px-4 py-3">
          <p className="text-xs text-vault-text-secondary mb-1">{t('admin.queue.queued')}</p>
          <p className="text-2xl font-bold text-yellow-400">{overview?.queued ?? '—'}</p>
        </div>
        <div className="bg-vault-card border border-vault-border rounded-xl px-4 py-3">
          <p className="text-xs text-vault-text-secondary mb-1">{t('admin.queue.scheduled')}</p>
          <p className="text-2xl font-bold text-vault-text-secondary">{overview?.scheduled ?? '—'}</p>
        </div>
      </div>

      {/* Workers section */}
      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-vault-border">
          <Activity size={14} className="text-vault-text-muted" />
          <h2 className="text-sm font-semibold text-vault-text">{t('admin.queue.workers')}</h2>
          <span className="ml-auto text-xs text-vault-text-secondary">{workers.length}</span>
        </div>
        <div className="p-4">
          <WorkersSection workers={workers} />
        </div>
      </div>

      {/* Jobs section */}
      <div className="space-y-3">
        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-vault-text mr-1">{t('admin.queue.jobs')}</h2>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-2 py-1.5 text-xs bg-vault-input border border-vault-border rounded text-vault-text"
            aria-label={t('admin.queue.status')}
          >
            <option value="">{t('admin.queue.allStatuses')}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            value={fnFilter}
            onChange={(e) => setFnFilter(e.target.value)}
            className="px-2 py-1.5 text-xs bg-vault-input border border-vault-border rounded text-vault-text"
            aria-label={t('admin.queue.function')}
          >
            <option value="">{t('admin.queue.allFunctions')}</option>
            {functionNames.map((fn) => (
              <option key={fn} value={fn}>
                {fn}
              </option>
            ))}
          </select>
          <span className="ml-auto text-xs text-vault-text-secondary">{total}</span>
        </div>

        {/* Job list */}
        <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
          {jobsLoading ? (
            <div className="px-4 py-10 text-center text-vault-text-secondary text-sm">
              {t('common.loading')}
            </div>
          ) : jobs.length === 0 ? (
            <div className="px-4 py-10 text-center text-vault-text-secondary text-sm">
              {t('admin.queue.noJobs')}
            </div>
          ) : (
            jobs.map((job) => (
              <JobRow key={job.key} job={job} onRetry={handleRetry} onAbort={handleAbort} />
            ))
          )}
        </div>

        {/* Pagination */}
        {(hasPrev || hasNext) && (
          <div className="flex justify-between items-center">
            <button
              onClick={() => setOffset((prev) => Math.max(0, prev - LIMIT))}
              disabled={!hasPrev}
              className="px-4 py-2 text-sm bg-vault-input border border-vault-border rounded text-vault-text-secondary hover:text-vault-text transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label={t('common.previousPage')}
            >
              {t('common.previousPage')}
            </button>
            <span className="text-xs text-vault-text-secondary">
              {offset + 1}–{Math.min(offset + LIMIT, total)} / {total}
            </span>
            <button
              onClick={() => setOffset((prev) => prev + LIMIT)}
              disabled={!hasNext}
              className="px-4 py-2 text-sm bg-vault-input border border-vault-border rounded text-vault-text-secondary hover:text-vault-text transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label={t('common.nextPage')}
            >
              {t('common.nextPage')}
            </button>
          </div>
        )}
      </div>
    </main>
  )
}
