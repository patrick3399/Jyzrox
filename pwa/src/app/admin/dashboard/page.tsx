'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Activity, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useProfile } from '@/hooks/useProfile'
import { useDashboard } from '@/hooks/useDashboard'
import { api } from '@/lib/api'
import type { DownloadJob } from '@/lib/types'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { GlobalBar, SiteTable } from '@/components/admin/dashboard/SiteStats'
import { ActiveJobCard, QueuedJobRow } from '@/components/admin/dashboard/JobCards'
import { RecentEvents } from '@/components/admin/dashboard/RecentEvents'

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
      const next = !data.global.boost_mode
      await api.settings.setRateLimitOverride(next)
      // Write the new state locally first: with the WebSocket connected the
      // dashboard has no polling, so a plain refetch could show the old state.
      await mutate(
        (prev) => (prev ? { ...prev, global: { ...prev.global, boost_mode: next } } : prev),
        { revalidate: true },
      )
    } catch {
      toast.error(t('common.errorOccurred'))
    } finally {
      setToggling(false)
    }
  }

  const handleJobAction = async (id: string, action: 'pause' | 'resume' | 'stop' | 'cancel') => {
    try {
      if (action === 'pause') await api.download.pauseJob(id)
      else if (action === 'resume') await api.download.resumeJob(id)
      else if (action === 'stop') await api.download.stopJob(id)
      else await api.download.cancelJob(id)
      await mutate()
    } catch {
      toast.error(
        t(
          action === 'cancel'
            ? 'queue.cancelError'
            : action === 'stop'
              ? 'queue.stopError'
              : 'queue.pauseError',
        ),
      )
    }
  }

  const handleStop = (job: DownloadJob) => {
    // Stopping a subscription run gives up the posts it has not reached yet, for good.
    const givesUpHistory =
      job.mode === 'subscription_initial' ||
      job.mode === 'subscription_incremental' ||
      (!job.mode && !!job.subscription_id)
    if (givesUpHistory && !confirm(t('queue.stopConfirm'))) return
    void handleJobAction(job.id, 'stop')
  }

  const handleDiscard = (job: DownloadJob) => {
    if (!confirm(t('queue.discardConfirm'))) return
    void handleJobAction(job.id, 'cancel')
  }

  if (isLoading || profileLoading) {
    return (
      <PageContainer variant="secondary">
        <div className="flex items-center justify-center h-48">
          <Loader2 className="animate-spin text-vault-text-muted" size={24} />
        </div>
      </PageContainer>
    )
  }

  if (!data) {
    return (
      <PageContainer variant="secondary">
        <div className="text-vault-text-muted text-sm">{t('common.failedToLoad')}</div>
      </PageContainer>
    )
  }

  return (
    <PageContainer variant="secondary" className="space-y-6">
      <PageHeader
        spacing="none"
        title={t('downloadDashboard.title')}
        icon={<Activity size={22} className="text-vault-accent shrink-0" />}
      />

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
                onStop={handleStop}
                onDiscard={handleDiscard}
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
    </PageContainer>
  )
}
