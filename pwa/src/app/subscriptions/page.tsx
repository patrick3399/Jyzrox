'use client'

import { useState, useEffect, useMemo } from 'react'
import { Rss, Plus, X, RefreshCw, Trash2, ExternalLink, Download, CheckCircle, AlertCircle, List, Search } from 'lucide-react'
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
    const downloaded = job.progress?.downloaded ?? 0
    const total = job.progress?.total
    const pct = total ? Math.min(100, Math.round((downloaded / total) * 100)) : 0
    const gallerySource = job.gallery_source
    const gallerySourceId = job.gallery_source_id
    const title = job.progress?.title
    return (
      <div className="mt-2">
        {title && gallerySource && gallerySourceId && (
          <Link
            href={`/library/${encodeURIComponent(gallerySource)}/${encodeURIComponent(gallerySourceId)}`}
            className="text-[10px] text-vault-accent hover:underline truncate block mb-1"
          >
            {title}
          </Link>
        )}
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1.5 bg-vault-border rounded-full overflow-hidden">
            {total ? (
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            ) : (
              <div className="h-full bg-blue-500/30 rounded-full overflow-hidden relative">
                <div className="absolute inset-0 bg-gradient-to-r from-transparent via-blue-500/60 to-transparent animate-[shimmer_1.5s_infinite]" />
              </div>
            )}
          </div>
          <span className="text-[10px] text-vault-text-muted whitespace-nowrap">
            {downloaded}{total ? ` / ${total}` : ''} {t('queue.files')}
          </span>
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
  onAutoDownloadToggle,
  checkingId,
}: {
  sub: Subscription
  latestJob: DownloadJob | null
  onToggle: (sub: Subscription) => void
  onCheck: (sub: Subscription) => void
  onDelete: (sub: Subscription) => void
  onCronUpdate: (sub: Subscription, cron: string) => void
  onAutoDownloadToggle: (sub: Subscription) => void
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
    <div className="bg-vault-card border border-vault-border rounded-xl p-3 overflow-hidden">
      {/* Top row: name + badges on left, toggle on right */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-1.5 mb-1">
            <span className="text-sm font-medium text-vault-text break-all">
              {sub.name || sub.url}
            </span>
            {sourceBadge(sub.source)}
            {!sub.enabled && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-vault-border text-vault-text-muted shrink-0">
                {t('subscriptions.disabled')}
              </span>
            )}
          </div>
          {sub.name && (
            <p className="text-xs text-vault-text-muted truncate mb-1">{sub.url}</p>
          )}
        </div>

        {/* Toggle switch — stays top-right */}
        <button
          onClick={() => onToggle(sub)}
          className={`relative w-9 h-5 rounded-full transition-colors shrink-0 mt-0.5 ${sub.enabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
        >
          <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${sub.enabled ? 'translate-x-4' : ''}`} />
        </button>
      </div>

      {/* Inline cron editor */}
      <div className="flex flex-wrap items-center gap-1 mb-1">
        <input
          type="text"
          value={cronValue}
          onChange={(e) => setEditingCron(e.target.value)}
          onBlur={handleCronBlur}
          onKeyDown={handleCronKeyDown}
          className="w-24 px-1.5 py-0.5 bg-vault-input border border-vault-border rounded text-[11px] font-mono text-vault-text"
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
        <button
          onClick={() => onAutoDownloadToggle(sub)}
          className={`px-1.5 py-0.5 rounded transition-colors ${sub.auto_download ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/15 text-red-400/70'}`}
          title={sub.auto_download ? t('subscriptions.autoDownloadOn') : t('subscriptions.autoDownloadOff')}
        >
          {t('subscriptions.autoDownload')}
        </button>
        {sub.last_checked_at && (
          <span className={sub.last_status === 'ok' ? 'text-emerald-400' : sub.last_status === 'failed' ? 'text-red-400' : undefined}>{t('subscriptions.lastChecked')}: {timeAgo(sub.last_checked_at)}</span>
        )}
      </div>
      {sub.last_error && !latestJob && (
        <p className="text-[10px] text-red-400 mt-1 truncate" title={sub.last_error}>
          {sub.last_error}
        </p>
      )}
      {latestJob && <JobStatusBadge job={latestJob} />}

      {/* Bottom action row: secondary buttons */}
      <div className="flex items-center gap-0.5 mt-2 pt-2 border-t border-vault-border/50">
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
          onClick={() => {
            navigator.clipboard.writeText(
              `${window.location.origin}/api/rss/subscriptions/${sub.id}?token=YOUR_API_TOKEN`
            )
            toast.success(t('rss.copied'))
          }}
          className="p-1.5 rounded text-vault-text-muted hover:text-orange-400 transition-colors"
          title={t('rss.subscriptionFeed')}
        >
          <Rss size={14} />
        </button>
        <button
          onClick={() => onDelete(sub)}
          className="p-1.5 rounded text-vault-text-muted hover:text-red-400 transition-colors ml-auto"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  )
}

export default function SubscriptionsPage() {
  useLocale()
  const { data, mutate, isLoading } = useSubscriptions({ limit: 200 })
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

  const [searchInput, setSearchInput] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchInput), 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  const filteredSubscriptions = useMemo(() => {
    const subs = data?.subscriptions ?? []
    if (!debouncedSearch.trim()) return subs
    const q = debouncedSearch.toLowerCase()
    return subs.filter(s =>
      s.name?.toLowerCase().includes(q) ||
      s.url.toLowerCase().includes(q) ||
      s.source?.toLowerCase().includes(q)
    )
  }, [data?.subscriptions, debouncedSearch])

  const [showAdd, setShowAdd] = useState(false)
  const [showBatch, setShowBatch] = useState(false)
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [autoDownload, setAutoDownload] = useState(true)
  const [cronExpr, setCronExpr] = useState('0 */2 * * *')
  const [checkingId, setCheckingId] = useState<number | null>(null)
  const [isDeletingAll, setIsDeletingAll] = useState(false)
  const [batchUrls, setBatchUrls] = useState('')
  const [batchAutoDownload, setBatchAutoDownload] = useState(true)
  const [batchCron, setBatchCron] = useState('0 */2 * * *')
  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number; success: number; failed: number } | null>(null)

  const handleAdd = async () => {
    if (!url.trim()) return
    try {
      const result = await createSub({ url: url.trim(), name: name.trim() || undefined, auto_download: autoDownload, cron_expr: cronExpr })
      if (result?.duplicate) {
        toast.info(t('subscriptions.duplicateUpdated'))
      } else {
        toast.success(t('subscriptions.added'))
      }
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

  const handleBatchImport = async () => {
    // Parse and deduplicate URLs
    const rawLines = batchUrls.split('\n').map(l => l.trim()).filter(l => l && !l.startsWith('#'))
    if (rawLines.length === 0) {
      toast.error(t('subscriptions.batchEmpty'))
      return
    }

    // Dedup within input list
    const seen = new Set<string>()
    const unique: string[] = []
    for (const url of rawLines) {
      const normalized = url.replace(/\/+$/, '')
      if (!seen.has(normalized)) {
        seen.add(normalized)
        unique.push(url)
      }
    }

    // Dedup against existing subscriptions
    const existingUrls = new Set(
      (data?.subscriptions ?? []).map(s => s.url.replace(/\/+$/, ''))
    )
    const toImport = unique.filter(u => !existingUrls.has(u.replace(/\/+$/, '')))
    const dupsRemoved = rawLines.length - toImport.length
    if (dupsRemoved > 0) {
      toast.info(t('subscriptions.batchDuplicatesRemoved', { count: dupsRemoved }))
    }
    if (toImport.length === 0) {
      toast.error(t('subscriptions.batchEmpty'))
      return
    }

    setBatchProgress({ done: 0, total: toImport.length, success: 0, failed: 0 })
    let success = 0
    let failed = 0
    const failedUrls: string[] = []
    for (let i = 0; i < toImport.length; i++) {
      try {
        await api.subscriptions.create({ url: toImport[i], auto_download: batchAutoDownload, cron_expr: batchCron })
        success++
      } catch {
        failed++
        failedUrls.push(toImport[i])
      }
      setBatchProgress({ done: success + failed, total: toImport.length, success, failed })
      // Small delay every 10 requests to avoid rate limiting
      if (i > 0 && i % 10 === 0) await new Promise(r => setTimeout(r, 200))
    }
    toast.success(t('subscriptions.batchDone', { success, failed }))
    // If some failed, keep them in the textarea for retry
    if (failedUrls.length > 0) {
      setBatchUrls(failedUrls.join('\n'))
    }
    setBatchProgress(null)
    if (failedUrls.length === 0) {
      setBatchUrls('')
      setShowBatch(false)
    }
    mutate()
  }

  const handleAutoDownloadToggle = async (sub: Subscription) => {
    try {
      await updateSub({ id: sub.id, data: { auto_download: !sub.auto_download } })
      mutate()
    } catch {
      toast.error(t('subscriptions.updateFailed'))
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

  const handleDeleteAll = async () => {
    const subs = data?.subscriptions ?? []
    if (subs.length === 0) return
    if (!confirm(t('subscriptions.deleteAllConfirm', { count: subs.length }))) return
    setIsDeletingAll(true)
    let deleted = 0
    let failed = 0
    try {
      for (let i = 0; i < subs.length; i++) {
        try {
          await deleteSub(subs[i].id)
          deleted++
        } catch {
          failed++
        }
        if (i > 0 && i % 10 === 0) await new Promise(r => setTimeout(r, 200))
      }
      if (deleted > 0) toast.success(t('subscriptions.deleteAllDone', { deleted, failed }))
      if (failed > 0) toast.error(t('subscriptions.deleteAllFailed', { failed }))
      mutate()
    } finally {
      setIsDeletingAll(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 overflow-x-hidden">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 mb-6 flex-wrap">
        <div className="flex items-center gap-3">
          <Rss size={24} className="text-vault-accent shrink-0" />
          <h1 className="text-xl font-bold text-vault-text">{t('subscriptions.title')}</h1>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {(data?.subscriptions?.length ?? 0) > 0 && (
            <button
              onClick={handleDeleteAll}
              disabled={isDeletingAll}
              className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs font-medium bg-vault-input border border-vault-border text-red-400 hover:bg-red-900/30 hover:border-red-700/50 transition-colors disabled:opacity-50"
            >
              <Trash2 size={14} />
              <span className="hidden sm:inline">{isDeletingAll ? t('subscriptions.deletingAll') : t('subscriptions.deleteAll')}</span>
            </button>
          )}
          <button
            onClick={() => { setShowBatch(!showBatch); if (showAdd) setShowAdd(false) }}
            className={`flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              showBatch ? 'bg-vault-input border border-vault-border text-vault-text' : 'bg-vault-input border border-vault-border text-vault-text-secondary hover:text-vault-text'
            }`}
          >
            {showBatch ? <X size={14} /> : <List size={14} />}
            {showBatch ? t('common.cancel') : t('subscriptions.batchImport')}
          </button>
          <button
            onClick={() => { setShowAdd(!showAdd); if (showBatch) setShowBatch(false) }}
            className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs font-medium bg-vault-accent text-white hover:bg-vault-accent/90 transition-colors"
          >
            {showAdd ? <X size={14} /> : <Plus size={14} />}
            {showAdd ? t('common.cancel') : t('subscriptions.addNew')}
          </button>
        </div>
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

      {/* Batch import form */}
      {showBatch && (
        <div className="bg-vault-card border border-vault-border rounded-xl p-4 mb-6 space-y-3">
          <div>
            <label className="text-xs text-vault-text-muted block mb-1">{t('subscriptions.batchImport')}</label>
            <textarea
              value={batchUrls}
              onChange={(e) => setBatchUrls(e.target.value)}
              placeholder={t('subscriptions.batchPlaceholder')}
              rows={8}
              className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder-vault-text-muted font-mono resize-y"
              autoFocus
            />
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-xs text-vault-text-muted">{t('subscriptions.autoDownload')}</label>
              <button
                onClick={() => setBatchAutoDownload(!batchAutoDownload)}
                className={`relative w-9 h-5 rounded-full transition-colors ${batchAutoDownload ? 'bg-vault-accent' : 'bg-vault-border'}`}
              >
                <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${batchAutoDownload ? 'translate-x-4' : ''}`} />
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <label className="text-xs text-vault-text-muted">{t('subscriptions.cronExpr')}</label>
              <input
                type="text"
                value={batchCron}
                onChange={(e) => setBatchCron(e.target.value)}
                className="w-28 px-1.5 py-0.5 bg-vault-input border border-vault-border rounded text-xs font-mono text-vault-text"
              />
              {CRON_PRESETS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => setBatchCron(p.value)}
                  className={`px-1.5 py-0.5 rounded text-[10px] transition-colors ${
                    batchCron === p.value
                      ? 'bg-vault-accent/20 text-vault-accent'
                      : 'bg-vault-bg border border-vault-border text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleBatchImport}
              disabled={!!batchProgress || !batchUrls.trim()}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-vault-accent text-white hover:bg-vault-accent/90 transition-colors disabled:opacity-50"
            >
              {batchProgress
                ? t('subscriptions.batchImporting', { done: batchProgress.done, total: batchProgress.total })
                : t('subscriptions.batchImport')
              }
            </button>
            {batchProgress && (
              <div className="flex-1 h-2 bg-vault-border rounded-full overflow-hidden">
                <div
                  className="h-full bg-vault-accent rounded-full transition-all duration-300"
                  style={{ width: `${Math.round((batchProgress.done / batchProgress.total) * 100)}%` }}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Search */}
      {(data?.subscriptions?.length ?? 0) > 0 && (
        <div className="relative mb-4">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-vault-text-muted" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder={t('subscriptions.searchPlaceholder')}
            className="w-full pl-9 pr-8 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder-vault-text-muted"
          />
          {searchInput && (
            <button
              onClick={() => { setSearchInput(''); setDebouncedSearch('') }}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-vault-text-muted hover:text-vault-text"
            >
              <X size={14} />
            </button>
          )}
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
      ) : filteredSubscriptions.length === 0 ? (
        <div className="text-center py-12">
          <Search size={40} className="mx-auto text-vault-text-muted mb-3" />
          <p className="text-sm text-vault-text-muted">{t('subscriptions.noResults')}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {filteredSubscriptions.map((sub) => (
            <SubscriptionCard
              key={sub.id}
              sub={sub}
              latestJob={jobsData?.[sub.id] ?? null}
              onToggle={handleToggle}
              onCheck={handleCheck}
              onDelete={handleDelete}
              onCronUpdate={handleCronUpdate}
              onAutoDownloadToggle={handleAutoDownloadToggle}
              checkingId={checkingId}
            />
          ))}
        </div>
      )}
    </div>
  )
}
