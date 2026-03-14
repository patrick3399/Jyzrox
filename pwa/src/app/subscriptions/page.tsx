'use client'

import { useState, useEffect, useMemo } from 'react'
import { Rss, Plus, X, RefreshCw, Trash2, ExternalLink, Download, CheckCircle, AlertCircle } from 'lucide-react'
import { toast } from 'sonner'
import Link from 'next/link'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useWs } from '@/lib/ws'
import { useSubscriptions, useCreateSubscription, useUpdateSubscription, useDeleteSubscription, useCheckSubscription } from '@/hooks/useSubscriptions'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { api } from '@/lib/api'
import type { Subscription, DownloadJob } from '@/lib/types'
import useSWR from 'swr'

const SOURCE_COLORS: Record<string, string> = {
  pixiv: 'bg-blue-500/20 text-blue-400',
  twitter: 'bg-sky-500/20 text-sky-400',
  ehentai: 'bg-purple-500/20 text-purple-400',
}

function sourceBadge(source: string | null) {
  const cls = SOURCE_COLORS[source || ''] || 'bg-vault-border text-vault-text-muted'
  const label = source
    ? source === 'pixiv' ? 'Pixiv'
    : source === 'twitter' ? 'Twitter'
    : source === 'ehentai' ? 'E-Hentai'
    : source
    : t('subscriptions.sourceOther')
  return <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${cls}`}>{label}</span>
}

function timeAgo(iso: string | null): string {
  if (!iso) return t('settings.tasks.never')
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return t('history.justNow')
  if (mins < 60) return t('history.minutesAgo', { n: String(mins) })
  const hours = Math.floor(mins / 60)
  if (hours < 24) return t('history.hoursAgo', { n: String(hours) })
  const days = Math.floor(hours / 24)
  return t('history.daysAgo', { n: String(days) })
}

const CRON_PRESETS = [
  { label: '2h', value: '0 */2 * * *' },
  { label: '6h', value: '0 */6 * * *' },
  { label: '1d', value: '0 0 * * *' },
  { label: '3d', value: '0 0 */3 * *' },
  { label: '1w', value: '0 0 * * 1' },
]

function JobStatusBadge({ job }: { job: DownloadJob }) {
  if (job.status === 'running') {
    const pct = job.progress?.percent ?? 0
    return (
      <div className="mt-2">
        <div className="flex items-center justify-between text-[10px] text-vault-text-muted mb-1">
          <span className="text-blue-400 flex items-center gap-1">
            <Download size={10} />
            {t('subscriptions.downloading')}
          </span>
          <span>{pct}%{job.progress?.downloaded != null && job.progress?.total != null ? ` (${job.progress.downloaded}/${job.progress.total})` : ''}</span>
        </div>
        <div className="h-1.5 bg-vault-border rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    )
  }
  if (job.status === 'done') {
    const gallerySource = job.gallery_source
    const gallerySourceId = job.gallery_source_id
    return (
      <div className="mt-1.5 flex items-center gap-1.5 text-[10px]">
        <CheckCircle size={12} className="text-green-400" />
        <span className="text-green-400">{t('subscriptions.downloadComplete')}</span>
        {gallerySource && gallerySourceId && (
          <Link
            href={`/library/${encodeURIComponent(gallerySource)}/${encodeURIComponent(gallerySourceId)}`}
            className="text-vault-accent hover:underline ml-1"
          >
            {t('subscriptions.viewGallery')}
          </Link>
        )}
      </div>
    )
  }
  if (job.status === 'failed') {
    return (
      <div className="mt-1.5 flex items-center gap-1.5 text-[10px]">
        <AlertCircle size={12} className="text-red-400" />
        <span className="text-red-400 truncate" title={job.error || undefined}>
          {job.error || t('subscriptions.downloadFailed')}
        </span>
      </div>
    )
  }
  if (job.status === 'queued') {
    return (
      <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-vault-text-muted">
        <Download size={10} />
        <span>{t('subscriptions.queued')}</span>
      </div>
    )
  }
  return null
}

function SubscriptionCard({
  sub,
  latestJob,
  onToggle,
  onCheck,
  onDelete,
  onCronUpdate,
  checkingId,
}: {
  sub: Subscription
  latestJob: DownloadJob | null
  onToggle: (sub: Subscription) => void
  onCheck: (sub: Subscription) => void
  onDelete: (sub: Subscription) => void
  onCronUpdate: (sub: Subscription, cron: string) => void
  checkingId: number | null
}) {
  const [editingCron, setEditingCron] = useState<string | undefined>(undefined)
  const cronValue = editingCron ?? sub.cron_expr ?? '0 */2 * * *'

  const handleCronBlur = () => {
    if (editingCron !== undefined && editingCron !== sub.cron_expr) {
      onCronUpdate(sub, editingCron)
    }
    setEditingCron(undefined)
  }

  const handleCronKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && editingCron !== undefined) {
      e.preventDefault()
      onCronUpdate(sub, editingCron)
      setEditingCron(undefined)
    }
    if (e.key === 'Escape') {
      setEditingCron(undefined)
    }
  }

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-medium text-vault-text truncate">
              {sub.name || sub.url}
            </span>
            {sourceBadge(sub.source)}
            {!sub.enabled && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-vault-border text-vault-text-muted">
                {t('subscriptions.disabled')}
              </span>
            )}
          </div>
          {sub.name && (
            <p className="text-xs text-vault-text-muted truncate mb-1">{sub.url}</p>
          )}

          {/* Inline cron editor */}
          <div className="flex flex-wrap items-center gap-1.5 mb-1">
            <input
              type="text"
              value={cronValue}
              onChange={(e) => setEditingCron(e.target.value)}
              onBlur={handleCronBlur}
              onKeyDown={handleCronKeyDown}
              className="w-28 px-1.5 py-0.5 bg-vault-input border border-vault-border rounded text-[11px] font-mono text-vault-text"
            />
            {CRON_PRESETS.map((p) => (
              <button
                key={p.value}
                onClick={() => onCronUpdate(sub, p.value)}
                className={`px-1.5 py-0.5 rounded text-[10px] transition-colors ${
                  sub.cron_expr === p.value
                    ? 'bg-vault-accent/20 text-vault-accent'
                    : 'bg-vault-bg border border-vault-border text-vault-text-muted hover:text-vault-text'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-3 text-[10px] text-vault-text-muted">
            {sub.last_checked_at && (
              <span>{t('subscriptions.lastChecked')}: {timeAgo(sub.last_checked_at)}</span>
            )}
            {sub.auto_download && (
              <span className="text-vault-accent">{t('subscriptions.autoDownload')}</span>
            )}
          </div>
          {sub.last_error && !latestJob && (
            <p className="text-[10px] text-red-400 mt-1 truncate" title={sub.last_error}>
              {sub.last_error}
            </p>
          )}
          {latestJob && <JobStatusBadge job={latestJob} />}
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => onToggle(sub)}
            className={`relative w-9 h-5 rounded-full transition-colors ${sub.enabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
          >
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${sub.enabled ? 'translate-x-4' : ''}`} />
          </button>
          <button
            onClick={() => onCheck(sub)}
            disabled={checkingId === sub.id}
            className="p-1.5 rounded text-vault-text-muted hover:text-vault-accent transition-colors"
            title={t('subscriptions.downloadNow')}
          >
            <RefreshCw size={14} className={checkingId === sub.id ? 'animate-spin' : ''} />
          </button>
          <a
            href={sub.url}
            target="_blank"
            rel="noopener noreferrer"
            className="p-1.5 rounded text-vault-text-muted hover:text-vault-text transition-colors"
          >
            <ExternalLink size={14} />
          </a>
          <button
            onClick={() => onDelete(sub)}
            className="p-1.5 rounded text-vault-text-muted hover:text-red-400 transition-colors"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}

export default function SubscriptionsPage() {
  useLocale()
  const { data, mutate, isLoading } = useSubscriptions()
  const { trigger: createSub, isMutating: creating } = useCreateSubscription()
  const { trigger: updateSub } = useUpdateSubscription()
  const { trigger: deleteSub } = useDeleteSubscription()
  const { trigger: checkSub } = useCheckSubscription()
  const { lastSubCheck, lastJobUpdate } = useWs()

  // Fetch latest job for each subscription that has a last_job_id
  const subIds = useMemo(() =>
    (data?.subscriptions ?? []).filter(s => s.last_job_id).map(s => s.id),
    [data?.subscriptions]
  )

  const { data: jobsData, mutate: mutateJobs } = useSWR(
    subIds.length > 0 ? ['sub-jobs', ...subIds] : null,
    async () => {
      const results: Record<number, DownloadJob> = {}
      // Fetch the latest job for each sub in parallel
      const promises = (data?.subscriptions ?? [])
        .filter(s => s.last_job_id)
        .map(async (s) => {
          try {
            const res = await api.subscriptions.jobs(s.id, 1)
            if (res.jobs.length > 0) {
              results[s.id] = res.jobs[0]
            }
          } catch { /* ignore */ }
        })
      await Promise.all(promises)
      return results
    },
    { refreshInterval: 5000 },
  )

  useEffect(() => {
    if (lastSubCheck) {
      mutate()
      mutateJobs()
    }
  }, [lastSubCheck, mutate, mutateJobs])

  useEffect(() => {
    if (!lastJobUpdate) return
    // Optimistically update the matching job in cache so the progress bar animates
    // immediately without waiting for an HTTP round-trip.
    mutateJobs((prev) => {
      if (!prev) return prev
      const updated = { ...prev }
      for (const [subIdStr, job] of Object.entries(updated)) {
        if (job.id === lastJobUpdate.job_id) {
          updated[Number(subIdStr)] = {
            ...job,
            status: lastJobUpdate.status as DownloadJob['status'],
            progress: lastJobUpdate.progress != null
              ? (lastJobUpdate.progress as DownloadJob['progress'])
              : job.progress,
          }
          break
        }
      }
      return updated
    }, { revalidate: false })
    // On terminal states do a real re-fetch to pick up gallery_source / gallery_source_id.
    if (['done', 'failed', 'partial'].includes(lastJobUpdate.status)) {
      mutateJobs()
    }
  }, [lastJobUpdate, mutateJobs])

  const [showAdd, setShowAdd] = useState(false)
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [autoDownload, setAutoDownload] = useState(true)
  const [cronExpr, setCronExpr] = useState('0 */2 * * *')
  const [checkingId, setCheckingId] = useState<number | null>(null)

  const handleAdd = async () => {
    if (!url.trim()) return
    try {
      await createSub({ url: url.trim(), name: name.trim() || undefined, auto_download: autoDownload, cron_expr: cronExpr })
      toast.success(t('subscriptions.added'))
      setUrl('')
      setName('')
      setAutoDownload(true)
      setCronExpr('0 */2 * * *')
      setShowAdd(false)
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('subscriptions.addFailed'))
    }
  }

  const handleCronUpdate = async (sub: Subscription, cron: string) => {
    try {
      await updateSub({ id: sub.id, data: { cron_expr: cron } })
      toast.success(t('subscriptions.updated'))
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('subscriptions.updateFailed'))
    }
  }

  const handleDelete = async (sub: Subscription) => {
    if (!confirm(t('subscriptions.deleteConfirm', { name: sub.name || sub.url }))) return
    try {
      await deleteSub(sub.id)
      toast.success(t('subscriptions.deleted'))
      mutate()
    } catch {
      toast.error(t('subscriptions.deleteFailed'))
    }
  }

  const handleToggle = async (sub: Subscription) => {
    try {
      await updateSub({ id: sub.id, data: { enabled: !sub.enabled } })
      toast.success(t('subscriptions.updated'))
      mutate()
    } catch {
      toast.error(t('subscriptions.updateFailed'))
    }
  }

  const handleCheck = async (sub: Subscription) => {
    setCheckingId(sub.id)
    try {
      await checkSub(sub.id)
      toast.success(t('subscriptions.downloadQueued'))
      mutate()
    } catch {
      toast.error(t('subscriptions.checkFailed'))
    } finally {
      setCheckingId(null)
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Rss size={24} className="text-vault-accent" />
          <h1 className="text-xl font-bold text-vault-text">{t('subscriptions.title')}</h1>
        </div>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium bg-vault-accent text-white hover:bg-vault-accent/90 transition-colors"
        >
          {showAdd ? <X size={16} /> : <Plus size={16} />}
          {showAdd ? t('common.cancel') : t('subscriptions.addNew')}
        </button>
      </div>

      {/* Add form — simplified (no preview) */}
      {showAdd && (
        <div className="bg-vault-card border border-vault-border rounded-xl p-4 mb-6 space-y-3">
          <div>
            <label className="text-xs text-vault-text-muted block mb-1">{t('subscriptions.url')}</label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t('subscriptions.urlPlaceholder')}
              className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder-vault-text-muted"
              autoFocus
            />
          </div>
          <div>
            <label className="text-xs text-vault-text-muted block mb-1">{t('subscriptions.name')}</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('subscriptions.namePlaceholder')}
              className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder-vault-text-muted"
            />
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-xs text-vault-text-muted">{t('subscriptions.autoDownload')}</label>
              <button
                onClick={() => setAutoDownload(!autoDownload)}
                className={`relative w-9 h-5 rounded-full transition-colors ${autoDownload ? 'bg-vault-accent' : 'bg-vault-border'}`}
              >
                <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${autoDownload ? 'translate-x-4' : ''}`} />
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <label className="text-xs text-vault-text-muted">{t('subscriptions.cronExpr')}</label>
              <input
                type="text"
                value={cronExpr}
                onChange={(e) => setCronExpr(e.target.value)}
                className="w-28 px-1.5 py-0.5 bg-vault-input border border-vault-border rounded text-xs font-mono text-vault-text"
              />
              {CRON_PRESETS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => setCronExpr(p.value)}
                  className={`px-1.5 py-0.5 rounded text-[10px] transition-colors ${
                    cronExpr === p.value
                      ? 'bg-vault-accent/20 text-vault-accent'
                      : 'bg-vault-bg border border-vault-border text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={handleAdd}
            disabled={creating || !url.trim()}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-vault-accent text-white hover:bg-vault-accent/90 transition-colors disabled:opacity-50"
          >
            {creating ? t('subscriptions.adding') : t('subscriptions.add')}
          </button>
        </div>
      )}

      {/* List */}
      {isLoading ? (
        <div className="flex justify-center py-12"><LoadingSpinner /></div>
      ) : !data?.subscriptions.length ? (
        <div className="text-center py-12">
          <Rss size={40} className="mx-auto text-vault-text-muted mb-3" />
          <p className="text-sm text-vault-text-muted">{t('subscriptions.noSubscriptions')}</p>
          <p className="text-xs text-vault-text-muted mt-1">{t('subscriptions.noSubscriptionsHint')}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {data.subscriptions.map((sub) => (
            <SubscriptionCard
              key={sub.id}
              sub={sub}
              latestJob={jobsData?.[sub.id] ?? null}
              onToggle={handleToggle}
              onCheck={handleCheck}
              onDelete={handleDelete}
              onCronUpdate={handleCronUpdate}
              checkingId={checkingId}
            />
          ))}
        </div>
      )}
    </div>
  )
}
