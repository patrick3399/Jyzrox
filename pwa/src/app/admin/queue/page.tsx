'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import useSWR from 'swr'
import { toast } from 'sonner'
import { ListTodo, Activity } from 'lucide-react'
import { useProfile } from '@/hooks/useProfile'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'
import { STATUSES } from '@/components/admin/queue/helpers'
import { WorkersSection, JobRow } from '@/components/admin/queue/QueueSections'

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

  const { data: overview } = useSWR('admin/queue/overview', () => api.adminQueue.overview(), {
    refreshInterval: 3000,
  })

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
      <PageContainer variant="secondary">
        <div className="flex items-center justify-center min-h-[60vh]">
          <div className="text-vault-text-secondary text-sm">{t('common.loading')}</div>
        </div>
      </PageContainer>
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
    <PageContainer variant="secondary">
      <PageHeader
        title={t('admin.queue.title')}
        icon={<ListTodo size={24} className="text-vault-accent shrink-0" />}
      />
      <main className="space-y-6">
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
            <p className="text-2xl font-bold text-vault-text-secondary">
              {overview?.scheduled ?? '—'}
            </p>
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
              <Button
                variant="secondary"
                onClick={() => setOffset((prev) => Math.max(0, prev - LIMIT))}
                disabled={!hasPrev}
                aria-label={t('common.previousPage')}
              >
                {t('common.previousPage')}
              </Button>
              <span className="text-xs text-vault-text-secondary">
                {offset + 1}–{Math.min(offset + LIMIT, total)} / {total}
              </span>
              <Button
                variant="secondary"
                onClick={() => setOffset((prev) => prev + LIMIT)}
                disabled={!hasNext}
                aria-label={t('common.nextPage')}
              >
                {t('common.nextPage')}
              </Button>
            </div>
          )}
        </div>
      </main>
    </PageContainer>
  )
}
