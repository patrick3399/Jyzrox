'use client'

import { useState, useEffect, useMemo } from 'react'
import dynamic from 'next/dynamic'
import { Rss, Plus, X, Trash2, List, Search, FolderOpen, Download, Globe } from 'lucide-react'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useWsJobs, useWsConnection } from '@/lib/ws'
import { pollingRefreshInterval } from '@/lib/wsPolling'
import {
  useAllSubscriptions,
  useCreateSubscription,
  useUpdateSubscription,
  useDeleteSubscription,
  useCheckSubscription,
  useBackfillSubscription,
} from '@/hooks/useSubscriptions'
import {
  useSubscriptionGroups,
  useCreateGroup,
  useUpdateGroup,
  useDeleteGroup,
  useRunGroup,
  usePauseGroup,
  useResumeGroup,
  useBulkMove,
} from '@/hooks/useSubscriptionGroups'
import { useDownloadJobs, useCheckUrl } from '@/hooks/useDownloadQueue'
import { MediaPolicyFields } from '@/components/download/MediaPolicyFields'
import { DEFAULT_MEDIA_POLICY, withMediaPolicy } from '@/lib/mediaPolicy'
import { activeSubscriptionIds, sortActiveFirst } from '@/lib/downloadJobFilters'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { api } from '@/lib/api'
import type {
  Subscription,
  SubscriptionGroup,
  DownloadJob,
  JobListParams,
  MediaPolicy,
} from '@/lib/types'
import useSWR from 'swr'
import { GroupCard } from '@/components/subscriptions/GroupCard'
import { CRON_PRESETS, DEFAULT_SUBSCRIPTION_CRON } from '@/components/subscriptions/constants'
import {
  groupBySource,
  readSubscriptionView,
  sourceLabel,
  writeSubscriptionView,
  type SubscriptionView,
} from '@/components/subscriptions/sourceGrouping'

const GroupModal = dynamic(
  () => import('@/components/subscriptions/GroupModal').then((module) => module.GroupModal),
  { ssr: false },
)

// ── Constants ────────────────────────────────────────────────────────

// Module-level so the SWR key stays referentially stable across renders.
// Shares its cache entry with the queue page's subscription-active section.
const SUBSCRIPTION_ACTIVE_PARAMS: JobListParams = {
  subscription_only: true,
  active_only: true,
  limit: 100,
}

export default function SubscriptionsPage() {
  useLocale()

  // Subscriptions data
  const { data, mutate, isLoading } = useAllSubscriptions()
  const { trigger: createSub, isMutating: creating } = useCreateSubscription()
  const { trigger: updateSub } = useUpdateSubscription()
  const { trigger: deleteSub } = useDeleteSubscription()
  const { trigger: checkSub } = useCheckSubscription()
  const { trigger: backfillSub } = useBackfillSubscription()

  // Groups data
  const { data: groupsData, mutate: mutateGroups } = useSubscriptionGroups()
  const { trigger: createGroupTrigger } = useCreateGroup()
  const { trigger: updateGroupTrigger } = useUpdateGroup()
  const { trigger: deleteGroupTrigger } = useDeleteGroup()
  const { trigger: runGroupTrigger } = useRunGroup()
  const { trigger: pauseGroupTrigger } = usePauseGroup()
  const { trigger: resumeGroupTrigger } = useResumeGroup()
  const { trigger: bulkMoveTrigger } = useBulkMove()

  const { lastSubCheck, lastJobUpdate } = useWsJobs()
  const { connected } = useWsConnection()

  const groups = groupsData?.groups ?? []

  // Fetch latest job for each subscription that has a last_job_id
  const subIds = useMemo(
    () => (data?.subscriptions ?? []).filter((s) => s.last_job_id).map((s) => s.id),
    [data?.subscriptions],
  )

  const { data: jobsData, mutate: mutateJobs } = useSWR(
    subIds.length > 0 ? ['sub-jobs', ...subIds] : null,
    async () => {
      const results: Record<number, DownloadJob> = {}
      const promises = (data?.subscriptions ?? [])
        .filter((s) => s.last_job_id)
        .map(async (s) => {
          try {
            const res = await api.subscriptions.jobs(s.id, 1)
            if (res.jobs.length > 0) {
              results[s.id] = res.jobs[0]
            }
          } catch {
            /* ignore */
          }
        })
      await Promise.all(promises)
      return results
    },
    // Event-driven while connected (lastSubCheck/lastJobUpdate effects below +
    // wsInvalidation.tsx); poll as a fallback when WS is down.
    { refreshInterval: pollingRefreshInterval(connected, 5000) },
  )

  useEffect(() => {
    if (lastSubCheck) {
      mutate()
      mutateJobs()
      mutateGroups()
    }
  }, [lastSubCheck, mutate, mutateJobs, mutateGroups])

  useEffect(() => {
    if (!lastJobUpdate) return
    mutateJobs(
      (prev) => {
        if (!prev) return prev
        const updated = { ...prev }
        for (const [subIdStr, job] of Object.entries(updated)) {
          if (job.id === lastJobUpdate.job_id) {
            updated[Number(subIdStr)] = {
              ...job,
              status: lastJobUpdate.status as DownloadJob['status'],
              progress:
                lastJobUpdate.progress != null
                  ? (lastJobUpdate.progress as DownloadJob['progress'])
                  : job.progress,
            }
            break
          }
        }
        return updated
      },
      { revalidate: false },
    )
    if (['done', 'failed', 'partial'].includes(lastJobUpdate.status)) {
      mutateJobs()
    }
  }, [lastJobUpdate, mutateJobs])

  // Search
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
    return subs.filter(
      (s) =>
        s.name?.toLowerCase().includes(q) ||
        s.url.toLowerCase().includes(q) ||
        s.source?.toLowerCase().includes(q),
    )
  }, [data?.subscriptions, debouncedSearch])

  // Subscriptions that currently have an active download job
  const { data: activeJobsData } = useDownloadJobs(SUBSCRIPTION_ACTIVE_PARAMS)
  const activeIds = useMemo(
    () => activeSubscriptionIds(activeJobsData?.jobs ?? []),
    [activeJobsData?.jobs],
  )
  const activeCount = activeIds.size
  const [downloadingOnly, setDownloadingOnly] = useState(false)

  // Nothing is downloading any more: drop the filter so the list does not look empty.
  useEffect(() => {
    if (activeCount === 0) setDownloadingOnly(false)
  }, [activeCount])

  const showDownloadingOnly = downloadingOnly && activeCount > 0

  // Layout: by schedule group (default) or by site. Read after mount — storage is client-only.
  const [view, setView] = useState<SubscriptionView>('group')
  useEffect(() => setView(readSubscriptionView()), [])
  const changeView = (next: SubscriptionView) => {
    setView(next)
    writeSubscriptionView(next)
  }

  const visibleSubs = useMemo(
    () =>
      showDownloadingOnly
        ? filteredSubscriptions.filter((s) => activeIds.has(s.id))
        : filteredSubscriptions,
    [filteredSubscriptions, activeIds, showDownloadingOnly],
  )

  const sourceSections = useMemo(
    () => groupBySource(visibleSubs, activeIds),
    [visibleSubs, activeIds],
  )

  // Group subscriptions by group_id (active downloads first inside every group)
  const groupedSubs = useMemo(() => {
    const byGroup: Record<number, Subscription[]> = {}
    const ungrouped: Subscription[] = []
    for (const sub of visibleSubs) {
      if (sub.group_id !== null && sub.group_id !== undefined) {
        if (!byGroup[sub.group_id]) byGroup[sub.group_id] = []
        byGroup[sub.group_id].push(sub)
      } else {
        ungrouped.push(sub)
      }
    }
    for (const key of Object.keys(byGroup)) {
      byGroup[Number(key)] = sortActiveFirst(byGroup[Number(key)], activeIds)
    }
    return { byGroup, ungrouped: sortActiveFirst(ungrouped, activeIds) }
  }, [visibleSubs, activeIds])

  const hasVisibleSubs = visibleSubs.length > 0

  // Forms state
  const [showAdd, setShowAdd] = useState(false)
  const [showBatch, setShowBatch] = useState(false)
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [autoDownload, setAutoDownload] = useState(false)
  const [cronExpr, setCronExpr] = useState(DEFAULT_SUBSCRIPTION_CRON)
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null)
  const [fanboxSubscriptionContent, setFanboxSubscriptionContent] = useState<
    'free_only' | 'accessible' | 'paid_only' | 'price_range'
  >('accessible')
  const [fanboxSubscriptionFeeMin, setFanboxSubscriptionFeeMin] = useState('')
  const [fanboxSubscriptionFeeMax, setFanboxSubscriptionFeeMax] = useState('')
  const [mediaPolicy, setMediaPolicy] = useState<MediaPolicy>(DEFAULT_MEDIA_POLICY)
  const [debouncedAddUrl, setDebouncedAddUrl] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedAddUrl(url), 300)
    return () => clearTimeout(timer)
  }, [url])
  const { data: addUrlCheck } = useCheckUrl(showAdd ? debouncedAddUrl : '')
  const supportsMediaPolicy = addUrlCheck?.supports_media_policy === true
  const [checkingId, setCheckingId] = useState<number | null>(null)
  const [isDeletingAll, setIsDeletingAll] = useState(false)
  const [batchUrls, setBatchUrls] = useState('')
  const [batchAutoDownload, setBatchAutoDownload] = useState(false)
  const [batchCron, setBatchCron] = useState(DEFAULT_SUBSCRIPTION_CRON)
  const [batchProgress, setBatchProgress] = useState<{
    done: number
    total: number
    success: number
    failed: number
  } | null>(null)

  // Group modal state
  const [groupModalOpen, setGroupModalOpen] = useState(false)
  const [editingGroup, setEditingGroup] = useState<SubscriptionGroup | null>(null)

  // Handlers — subscriptions
  const handleAdd = async () => {
    if (!url.trim()) return
    const fanboxOptions: Record<string, unknown> = url.includes('fanbox.cc')
      ? {
          fanbox: {
            content: fanboxSubscriptionContent,
            ...(fanboxSubscriptionFeeMin ? { fee_min: Number(fanboxSubscriptionFeeMin) } : {}),
            ...(fanboxSubscriptionFeeMax ? { fee_max: Number(fanboxSubscriptionFeeMax) } : {}),
          },
        }
      : {}
    const downloadOptions = supportsMediaPolicy
      ? withMediaPolicy(fanboxOptions, mediaPolicy)
      : fanboxOptions
    try {
      const result = await createSub({
        url: url.trim(),
        name: name.trim() || undefined,
        auto_download: autoDownload,
        cron_expr: cronExpr,
        group_id: selectedGroupId,
        ...(Object.keys(downloadOptions).length > 0 ? { download_options: downloadOptions } : {}),
      })
      if (result?.duplicate) {
        toast.info(t('subscriptions.duplicateUpdated'))
      } else {
        toast.success(t('subscriptions.added'))
      }
      setUrl('')
      setName('')
      setAutoDownload(true)
      setCronExpr(DEFAULT_SUBSCRIPTION_CRON)
      setSelectedGroupId(null)
      setFanboxSubscriptionContent('accessible')
      setFanboxSubscriptionFeeMin('')
      setFanboxSubscriptionFeeMax('')
      setMediaPolicy(DEFAULT_MEDIA_POLICY)
      setShowAdd(false)
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('subscriptions.addFailed'))
    }
  }

  const handleBatchImport = async () => {
    const rawLines = batchUrls
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#'))
    if (rawLines.length === 0) {
      toast.error(t('subscriptions.batchEmpty'))
      return
    }
    const seen = new Set<string>()
    const unique: string[] = []
    for (const u of rawLines) {
      const normalized = u.replace(/\/+$/, '')
      if (!seen.has(normalized)) {
        seen.add(normalized)
        unique.push(u)
      }
    }
    const existingUrls = new Set((data?.subscriptions ?? []).map((s) => s.url.replace(/\/+$/, '')))
    const toImport = unique.filter((u) => !existingUrls.has(u.replace(/\/+$/, '')))
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
        await api.subscriptions.create({
          url: toImport[i],
          auto_download: batchAutoDownload,
          cron_expr: batchCron,
        })
        success++
      } catch {
        failed++
        failedUrls.push(toImport[i])
      }
      setBatchProgress({ done: success + failed, total: toImport.length, success, failed })
      if (i > 0 && i % 10 === 0) await new Promise((r) => setTimeout(r, 200))
    }
    toast.success(t('subscriptions.batchDone', { success, failed }))
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

  const handleCronChange = async (sub: Subscription, cron: string) => {
    try {
      await updateSub({ id: sub.id, data: { cron_expr: cron } })
      toast.success(t('subscriptions.intervalUpdated'))
      mutate()
    } catch {
      toast.error(t('subscriptions.updateFailed'))
    }
  }

  const handleDownloadOptionsChange = async (
    sub: Subscription,
    download_options: Record<string, unknown>,
  ) => {
    try {
      await updateSub({ id: sub.id, data: { download_options } })
      toast.success(t('mediaPolicy.saved'))
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('subscriptions.updateFailed'))
    }
  }

  const handleRename = async (sub: Subscription, name: string) => {
    try {
      await updateSub({ id: sub.id, data: { name } })
      toast.success(t('subscriptions.nameUpdated'))
      mutate()
    } catch {
      toast.error(t('subscriptions.updateFailed'))
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

  const handleBackfill = async (sub: Subscription) => {
    if (!confirm(t('subscriptions.backfillConfirm', { name: sub.name || sub.url }))) return
    setCheckingId(sub.id)
    try {
      await backfillSub(sub.id)
      toast.success(t('subscriptions.backfillQueued', { name: sub.name || sub.url }))
      mutate()
    } catch {
      toast.error(t('subscriptions.backfillFailed'))
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
        if (i > 0 && i % 10 === 0) await new Promise((r) => setTimeout(r, 200))
      }
      if (deleted > 0) toast.success(t('subscriptions.deleteAllDone', { deleted, failed }))
      if (failed > 0) toast.error(t('subscriptions.deleteAllFailed', { failed }))
      mutate()
    } finally {
      setIsDeletingAll(false)
    }
  }

  const handleMoveToGroup = async (sub: Subscription, groupId: number | null) => {
    try {
      await bulkMoveTrigger({ sub_ids: [sub.id], group_id: groupId })
      toast.success(t('subscriptions.bulkMoved', { count: '1' }))
      mutate()
    } catch {
      toast.error(t('subscriptions.bulkMoveFailed'))
    }
  }

  // Handlers — groups
  const handleGroupSave = async (data: {
    name: string
    schedule: string
    concurrency: number
    priority: number
    enabled: boolean
  }) => {
    if (editingGroup) {
      try {
        await updateGroupTrigger({ id: editingGroup.id, data })
        toast.success(t('subscriptions.groupUpdated'))
        mutateGroups()
      } catch {
        toast.error(t('subscriptions.groupUpdateFailed'))
        throw new Error('update failed')
      }
    } else {
      try {
        await createGroupTrigger({
          name: data.name,
          schedule: data.schedule,
          concurrency: data.concurrency,
          priority: data.priority,
        })
        toast.success(t('subscriptions.groupCreated'))
        mutateGroups()
      } catch {
        toast.error(t('subscriptions.groupCreateFailed'))
        throw new Error('create failed')
      }
    }
  }

  const handleGroupRun = async (group: SubscriptionGroup) => {
    try {
      await runGroupTrigger(group.id)
      toast.success(t('subscriptions.groupRunQueued'))
      mutateGroups()
    } catch {
      toast.error(t('subscriptions.groupRunFailed'))
    }
  }

  const handleGroupPauseResume = async (group: SubscriptionGroup) => {
    try {
      if (group.status === 'paused') {
        await resumeGroupTrigger(group.id)
        toast.success(t('subscriptions.groupResumed'))
      } else {
        await pauseGroupTrigger(group.id)
        toast.success(t('subscriptions.groupPaused'))
      }
      mutateGroups()
    } catch {
      toast.error(t('subscriptions.groupUpdateFailed'))
    }
  }

  const handleGroupDelete = async (group: SubscriptionGroup) => {
    if (!confirm(t('subscriptions.groupDeleteConfirm', { name: group.name }))) return
    try {
      await deleteGroupTrigger(group.id)
      toast.success(t('subscriptions.groupDeleted'))
      mutateGroups()
      mutate() // subscriptions' group_id will be cleared
    } catch {
      toast.error(t('subscriptions.groupDeleteFailed'))
    }
  }

  const openNewGroup = () => {
    setEditingGroup(null)
    setGroupModalOpen(true)
  }

  const openEditGroup = (group: SubscriptionGroup) => {
    setEditingGroup(group)
    setGroupModalOpen(true)
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
              <span className="hidden sm:inline">
                {isDeletingAll ? t('subscriptions.deletingAll') : t('subscriptions.deleteAll')}
              </span>
            </button>
          )}
          <button
            onClick={openNewGroup}
            className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs font-medium bg-vault-input border border-vault-border text-vault-text-secondary hover:text-vault-text transition-colors"
          >
            <FolderOpen size={14} />
            {t('subscriptions.groupNew')}
          </button>
          <button
            onClick={() => {
              setShowBatch(!showBatch)
              if (showAdd) setShowAdd(false)
            }}
            className={`flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              showBatch
                ? 'bg-vault-input border border-vault-border text-vault-text'
                : 'bg-vault-input border border-vault-border text-vault-text-secondary hover:text-vault-text'
            }`}
          >
            {showBatch ? <X size={14} /> : <List size={14} />}
            {showBatch ? t('common.cancel') : t('subscriptions.batchImport')}
          </button>
          <button
            onClick={() => {
              setShowAdd(!showAdd)
              if (showBatch) setShowBatch(false)
            }}
            className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs font-medium bg-vault-accent text-white hover:bg-vault-accent/90 transition-colors"
          >
            {showAdd ? <X size={14} /> : <Plus size={14} />}
            {showAdd ? t('common.cancel') : t('subscriptions.addNew')}
          </button>
        </div>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="bg-vault-card border border-vault-border rounded-xl p-4 mb-6 space-y-3">
          <div>
            <label className="text-xs text-vault-text-muted block mb-1">
              {t('subscriptions.url')}
            </label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t('subscriptions.urlPlaceholder')}
              className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder-vault-text-muted"
              autoFocus
            />
          </div>
          {url.includes('fanbox.cc') && (
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-xs text-vault-text-muted">{t('fanbox.contentPolicy')}</label>
              <select
                value={fanboxSubscriptionContent}
                onChange={(e) =>
                  setFanboxSubscriptionContent(
                    e.target.value as 'free_only' | 'accessible' | 'paid_only' | 'price_range',
                  )
                }
                className="px-2 py-1 bg-vault-input border border-vault-border rounded text-xs text-vault-text"
              >
                <option value="free_only">{t('fanbox.freeOnly')}</option>
                <option value="accessible">{t('fanbox.accessible')}</option>
                <option value="paid_only">{t('fanbox.paidOnly')}</option>
                <option value="price_range">{t('fanbox.priceRange')}</option>
              </select>
              {fanboxSubscriptionContent === 'price_range' && (
                <>
                  <input
                    type="number"
                    min="0"
                    value={fanboxSubscriptionFeeMin}
                    onChange={(e) => setFanboxSubscriptionFeeMin(e.target.value)}
                    placeholder={t('fanbox.feeMin')}
                    className="w-24 px-2 py-1 bg-vault-input border border-vault-border rounded text-xs text-vault-text"
                  />
                  <input
                    type="number"
                    min="0"
                    value={fanboxSubscriptionFeeMax}
                    onChange={(e) => setFanboxSubscriptionFeeMax(e.target.value)}
                    placeholder={t('fanbox.feeMax')}
                    className="w-24 px-2 py-1 bg-vault-input border border-vault-border rounded text-xs text-vault-text"
                  />
                </>
              )}
            </div>
          )}
          {supportsMediaPolicy && (
            <MediaPolicyFields value={mediaPolicy} onChange={setMediaPolicy} disabled={creating} />
          )}
          <div>
            <label className="text-xs text-vault-text-muted block mb-1">
              {t('subscriptions.name')}
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('subscriptions.namePlaceholder')}
              className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder-vault-text-muted"
            />
          </div>
          {groups.length > 0 && (
            <div>
              <label className="text-xs text-vault-text-muted block mb-1">
                {t('subscriptions.groups')}
              </label>
              <select
                value={selectedGroupId ?? ''}
                onChange={(e) =>
                  setSelectedGroupId(e.target.value === '' ? null : Number(e.target.value))
                }
                className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text"
              >
                <option value="">{t('subscriptions.noGroup')}</option>
                {groups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-xs text-vault-text-muted">
                {t('subscriptions.autoDownload')}
              </label>
              <button
                onClick={() => setAutoDownload(!autoDownload)}
                className={`relative w-9 h-5 rounded-full transition-colors ${autoDownload ? 'bg-vault-accent' : 'bg-vault-border'}`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${autoDownload ? 'translate-x-4' : ''}`}
                />
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
            <label className="text-xs text-vault-text-muted block mb-1">
              {t('subscriptions.batchImport')}
            </label>
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
              <label className="text-xs text-vault-text-muted">
                {t('subscriptions.autoDownload')}
              </label>
              <button
                onClick={() => setBatchAutoDownload(!batchAutoDownload)}
                className={`relative w-9 h-5 rounded-full transition-colors ${batchAutoDownload ? 'bg-vault-accent' : 'bg-vault-border'}`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${batchAutoDownload ? 'translate-x-4' : ''}`}
                />
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
                ? t('subscriptions.batchImporting', {
                    done: batchProgress.done,
                    total: batchProgress.total,
                  })
                : t('subscriptions.batchImport')}
            </button>
            {batchProgress && (
              <div className="flex-1 h-2 bg-vault-border rounded-full overflow-hidden">
                <div
                  className="h-full bg-vault-accent rounded-full transition-all duration-300"
                  style={{
                    width: `${Math.round((batchProgress.done / batchProgress.total) * 100)}%`,
                  }}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Search + downloading filter */}
      {(data?.subscriptions?.length ?? 0) > 0 && (
        <div className="flex items-center gap-2 mb-4">
          <div className="relative flex-1 min-w-0">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-vault-text-muted"
            />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder={t('subscriptions.searchPlaceholder')}
              className="w-full pl-9 pr-8 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder-vault-text-muted"
            />
            {searchInput && (
              <button
                onClick={() => {
                  setSearchInput('')
                  setDebouncedSearch('')
                }}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-vault-text-muted hover:text-vault-text"
              >
                <X size={14} />
              </button>
            )}
          </div>
          <div
            role="group"
            aria-label={t('subscriptions.viewLabel')}
            className="shrink-0 flex rounded-lg border border-vault-border bg-vault-input p-0.5"
          >
            {(
              [
                ['group', FolderOpen, t('subscriptions.viewByGroup')],
                ['source', Globe, t('subscriptions.viewBySource')],
              ] as const
            ).map(([value, Icon, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => changeView(value)}
                aria-pressed={view === value}
                title={label}
                aria-label={label}
                className={`rounded-md p-1.5 transition-colors ${
                  view === value
                    ? 'bg-vault-accent/20 text-vault-accent'
                    : 'text-vault-text-muted hover:text-vault-text'
                }`}
              >
                <Icon size={15} />
              </button>
            ))}
          </div>
          {(activeCount > 0 || downloadingOnly) && (
            <button
              type="button"
              onClick={() => setDownloadingOnly((on) => !on)}
              aria-pressed={showDownloadingOnly}
              className={`shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium border transition-colors ${
                showDownloadingOnly
                  ? 'bg-vault-accent/20 border-vault-accent/40 text-vault-accent'
                  : 'bg-vault-input border-vault-border text-vault-text-secondary hover:text-vault-text'
              }`}
            >
              <Download size={14} />
              {t('subscriptions.filterDownloading', { count: activeCount })}
            </button>
          )}
        </div>
      )}

      {/* Content */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <LoadingSpinner />
        </div>
      ) : !data?.subscriptions.length ? (
        <div className="text-center py-12">
          <Rss size={40} className="mx-auto text-vault-text-muted mb-3" />
          <p className="text-sm text-vault-text-muted">{t('subscriptions.noSubscriptions')}</p>
          <p className="text-xs text-vault-text-muted mt-1">
            {t('subscriptions.noSubscriptionsHint')}
          </p>
        </div>
      ) : filteredSubscriptions.length === 0 ? (
        <div className="text-center py-12">
          <Search size={40} className="mx-auto text-vault-text-muted mb-3" />
          <p className="text-sm text-vault-text-muted">{t('subscriptions.noResults')}</p>
        </div>
      ) : showDownloadingOnly && !hasVisibleSubs ? (
        <div className="text-center py-12">
          <Download size={40} className="mx-auto text-vault-text-muted mb-3" />
          <p className="text-sm text-vault-text-muted">{t('subscriptions.noDownloading')}</p>
        </div>
      ) : view === 'source' ? (
        <div className="space-y-3">
          {sourceSections.map((section) => (
            <GroupCard
              key={section.source ?? '__other'}
              group={null}
              title={sourceLabel(section.source)}
              showSubGroup
              subs={section.subs}
              jobsData={jobsData ?? {}}
              groups={groups}
              onEdit={openEditGroup}
              onRun={handleGroupRun}
              onPauseResume={handleGroupPauseResume}
              onDelete={handleGroupDelete}
              onToggleSub={handleToggle}
              onCheckSub={handleCheck}
              onBackfillSub={handleBackfill}
              onDeleteSub={handleDelete}
              onAutoDownloadToggle={handleAutoDownloadToggle}
              onMoveToGroup={handleMoveToGroup}
              onRenameSub={handleRename}
              onCronChangeSub={handleCronChange}
              onDownloadOptionsChangeSub={handleDownloadOptionsChange}
              checkingId={checkingId}
              defaultExpanded={true}
            />
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {/* Named groups (empty ones are hidden while filtering to active downloads) */}
          {groups
            .filter(
              (group) => !showDownloadingOnly || (groupedSubs.byGroup[group.id]?.length ?? 0) > 0,
            )
            .map((group) => (
              <GroupCard
                key={group.id}
                group={group}
                subs={groupedSubs.byGroup[group.id] ?? []}
                jobsData={jobsData ?? {}}
                groups={groups}
                onEdit={openEditGroup}
                onRun={handleGroupRun}
                onPauseResume={handleGroupPauseResume}
                onDelete={handleGroupDelete}
                onToggleSub={handleToggle}
                onCheckSub={handleCheck}
                onBackfillSub={handleBackfill}
                onDeleteSub={handleDelete}
                onAutoDownloadToggle={handleAutoDownloadToggle}
                onMoveToGroup={handleMoveToGroup}
                onRenameSub={handleRename}
                onCronChangeSub={handleCronChange}
                onDownloadOptionsChangeSub={handleDownloadOptionsChange}
                checkingId={checkingId}
                defaultExpanded={true}
              />
            ))}

          {/* Ungrouped section — only show when there are ungrouped subs */}
          {groupedSubs.ungrouped.length > 0 && (
            <GroupCard
              group={null}
              subs={groupedSubs.ungrouped}
              jobsData={jobsData ?? {}}
              groups={groups}
              onEdit={openEditGroup}
              onRun={handleGroupRun}
              onPauseResume={handleGroupPauseResume}
              onDelete={handleGroupDelete}
              onToggleSub={handleToggle}
              onCheckSub={handleCheck}
              onBackfillSub={handleBackfill}
              onDeleteSub={handleDelete}
              onAutoDownloadToggle={handleAutoDownloadToggle}
              onMoveToGroup={handleMoveToGroup}
              onRenameSub={handleRename}
              onCronChangeSub={handleCronChange}
              onDownloadOptionsChangeSub={handleDownloadOptionsChange}
              checkingId={checkingId}
              defaultExpanded={true}
            />
          )}
        </div>
      )}

      {/* Group modal */}
      {groupModalOpen && (
        <GroupModal
          group={editingGroup}
          onClose={() => {
            setGroupModalOpen(false)
            setEditingGroup(null)
          }}
          onSave={handleGroupSave}
        />
      )}
    </div>
  )
}
