'use client'

import { useState, useEffect, useMemo, useRef } from 'react'
import {
  Rss,
  Plus,
  X,
  RefreshCw,
  Trash2,
  ExternalLink,
  Download,
  CheckCircle,
  AlertCircle,
  List,
  Search,
  FolderOpen,
  ChevronDown,
  ChevronRight,
  Play,
  Pause,
  Settings2,
  Users,
} from 'lucide-react'
import { toast } from 'sonner'
import Link from 'next/link'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useWs } from '@/lib/ws'
import {
  useSubscriptions,
  useCreateSubscription,
  useUpdateSubscription,
  useDeleteSubscription,
  useCheckSubscription,
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
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { api } from '@/lib/api'
import type { Subscription, SubscriptionGroup, DownloadJob } from '@/lib/types'
import useSWR from 'swr'

// ── Constants ────────────────────────────────────────────────────────

const SOURCE_COLORS: Record<string, string> = {
  pixiv: 'bg-blue-500/20 text-blue-400',
  twitter: 'bg-sky-500/20 text-sky-400',
  ehentai: 'bg-purple-500/20 text-purple-400',
}

const CRON_PRESETS = [
  { label: '2h', value: '0 */2 * * *' },
  { label: '6h', value: '0 */6 * * *' },
  { label: '1d', value: '0 0 * * *' },
  { label: '3d', value: '0 0 */3 * *' },
  { label: '1w', value: '0 0 * * 1' },
]

// ── Helper functions ─────────────────────────────────────────────────

function sourceBadge(source: string | null) {
  const cls = SOURCE_COLORS[source || ''] || 'bg-vault-border text-vault-text-muted'
  const label = source
    ? source === 'pixiv'
      ? 'Pixiv'
      : source === 'twitter'
        ? 'Twitter'
        : source === 'ehentai'
          ? 'E-Hentai'
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

function groupStatusBadge(status: string) {
  if (status === 'running') {
    return (
      <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400">
        <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
        {t('subscriptions.statusRunning')}
      </span>
    )
  }
  if (status === 'paused') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400">
        {t('subscriptions.statusPaused')}
      </span>
    )
  }
  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">
      {t('subscriptions.statusIdle')}
    </span>
  )
}

// ── Sub-components ───────────────────────────────────────────────────

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
            {downloaded}
            {total ? ` / ${total}` : ''} {t('queue.files')}
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
  groups,
  onToggle,
  onCheck,
  onDelete,
  onAutoDownloadToggle,
  onMoveToGroup,
  checkingId,
}: {
  sub: Subscription
  latestJob: DownloadJob | null
  groups: SubscriptionGroup[]
  onToggle: (sub: Subscription) => void
  onCheck: (sub: Subscription) => void
  onDelete: (sub: Subscription) => void
  onAutoDownloadToggle: (sub: Subscription) => void
  onMoveToGroup: (sub: Subscription, groupId: number | null) => void
  checkingId: number | null
}) {
  const [showMoveMenu, setShowMoveMenu] = useState(false)
  const moveMenuRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!showMoveMenu) return
    function handleClick(e: MouseEvent) {
      if (moveMenuRef.current && !moveMenuRef.current.contains(e.target as Node)) {
        setShowMoveMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [showMoveMenu])

  return (
    <div className="bg-vault-bg border border-vault-border/50 rounded-lg p-3 overflow-hidden">
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
          {sub.name && <p className="text-xs text-vault-text-muted truncate mb-1">{sub.url}</p>}
        </div>

        <button
          onClick={() => onToggle(sub)}
          className={`relative w-9 h-5 rounded-full transition-colors shrink-0 mt-0.5 ${sub.enabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${sub.enabled ? 'translate-x-4' : ''}`}
          />
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-[10px] text-vault-text-muted">
        <button
          onClick={() => onAutoDownloadToggle(sub)}
          className={`px-1.5 py-0.5 rounded transition-colors ${sub.auto_download ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/15 text-red-400/70'}`}
          title={
            sub.auto_download
              ? t('subscriptions.autoDownloadOn')
              : t('subscriptions.autoDownloadOff')
          }
        >
          {t('subscriptions.autoDownload')}
        </button>
        {sub.last_checked_at && (
          <span
            className={
              sub.last_status === 'ok'
                ? 'text-emerald-400'
                : sub.last_status === 'failed'
                  ? 'text-red-400'
                  : undefined
            }
          >
            {t('subscriptions.lastChecked')}: {timeAgo(sub.last_checked_at)}
          </span>
        )}
      </div>
      {sub.last_error && !latestJob && (
        <p className="text-[10px] text-red-400 mt-1 truncate" title={sub.last_error}>
          {sub.last_error}
        </p>
      )}
      {latestJob && <JobStatusBadge job={latestJob} />}

      {/* Bottom action row */}
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
              `${window.location.origin}/api/rss/subscriptions/${sub.id}?token=YOUR_API_TOKEN`,
            )
            toast.success(t('rss.copied'))
          }}
          className="p-1.5 rounded text-vault-text-muted hover:text-orange-400 transition-colors"
          title={t('rss.subscriptionFeed')}
        >
          <Rss size={14} />
        </button>

        {/* Move to group dropdown */}
        {groups.length > 0 && (
          <div className="relative" ref={moveMenuRef}>
            <button
              onClick={() => setShowMoveMenu(!showMoveMenu)}
              className="p-1.5 rounded text-vault-text-muted hover:text-vault-accent transition-colors"
              title={t('subscriptions.moveTo')}
            >
              <Users size={14} />
            </button>
            {showMoveMenu && (
              <div className="absolute left-0 bottom-full mb-1 z-20 bg-vault-card border border-vault-border rounded-lg shadow-lg py-1 min-w-[140px]">
                <button
                  onClick={() => {
                    onMoveToGroup(sub, null)
                    setShowMoveMenu(false)
                  }}
                  className={`w-full text-left px-3 py-1.5 text-xs hover:bg-vault-bg transition-colors ${sub.group_id === null ? 'text-vault-accent' : 'text-vault-text-muted'}`}
                >
                  {t('subscriptions.noGroup')}
                </button>
                {groups.map((g) => (
                  <button
                    key={g.id}
                    onClick={() => {
                      onMoveToGroup(sub, g.id)
                      setShowMoveMenu(false)
                    }}
                    className={`w-full text-left px-3 py-1.5 text-xs hover:bg-vault-bg transition-colors truncate ${sub.group_id === g.id ? 'text-vault-accent' : 'text-vault-text-muted'}`}
                  >
                    {g.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

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

// ── Group modal ──────────────────────────────────────────────────────

function GroupModal({
  group,
  onClose,
  onSave,
}: {
  group: SubscriptionGroup | null
  onClose: () => void
  onSave: (data: {
    name: string
    schedule: string
    concurrency: number
    priority: number
    enabled: boolean
  }) => Promise<void>
}) {
  const [name, setName] = useState(group?.name ?? '')
  const [schedule, setSchedule] = useState(group?.schedule ?? '0 */2 * * *')
  const [concurrency, setConcurrency] = useState(group?.concurrency ?? 2)
  const [priority, setPriority] = useState(group?.priority ?? 0)
  const [enabled, setEnabled] = useState(group?.enabled ?? true)
  const [saving, setSaving] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      await onSave({ name: name.trim(), schedule, concurrency, priority, enabled })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div className="bg-vault-card border border-vault-border rounded-xl w-full max-w-md shadow-xl">
        <div className="flex items-center justify-between p-4 border-b border-vault-border">
          <h2 className="text-sm font-semibold text-vault-text">
            {group ? t('subscriptions.groupEdit') : t('subscriptions.groupNew')}
          </h2>
          <button onClick={onClose} className="text-vault-text-muted hover:text-vault-text">
            <X size={16} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-3">
          <div>
            <label className="text-xs text-vault-text-muted block mb-1">
              {t('subscriptions.groupName')}
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('subscriptions.groupNamePlaceholder')}
              className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder-vault-text-muted"
              autoFocus
              disabled={group?.is_system}
            />
          </div>
          <div>
            <label className="text-xs text-vault-text-muted block mb-1">
              {t('subscriptions.groupSchedule')}
            </label>
            <div className="flex flex-wrap items-center gap-1.5">
              <input
                type="text"
                value={schedule}
                onChange={(e) => setSchedule(e.target.value)}
                className="w-32 px-2 py-1.5 bg-vault-input border border-vault-border rounded-lg text-xs font-mono text-vault-text"
              />
              {CRON_PRESETS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => setSchedule(p.value)}
                  className={`px-1.5 py-0.5 rounded text-[10px] transition-colors ${
                    schedule === p.value
                      ? 'bg-vault-accent/20 text-vault-accent'
                      : 'bg-vault-bg border border-vault-border text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <label className="text-xs text-vault-text-muted block mb-1">
                {t('subscriptions.groupConcurrency')}
              </label>
              <input
                type="number"
                min={1}
                max={10}
                value={concurrency}
                onChange={(e) => setConcurrency(Number(e.target.value))}
                className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text"
              />
            </div>
            <div className="flex-1">
              <label className="text-xs text-vault-text-muted block mb-1">
                {t('subscriptions.groupPriority')}
              </label>
              <input
                type="number"
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
                className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-vault-text-muted">
              {t('subscriptions.groupEnabled')}
            </label>
            <button
              type="button"
              onClick={() => setEnabled(!enabled)}
              className={`relative w-9 h-5 rounded-full transition-colors ${enabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${enabled ? 'translate-x-4' : ''}`}
              />
            </button>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg text-xs text-vault-text-muted bg-vault-input border border-vault-border hover:text-vault-text transition-colors"
            >
              {t('common.cancel')}
            </button>
            <button
              type="submit"
              disabled={saving || !name.trim()}
              className="px-4 py-1.5 rounded-lg text-xs font-medium bg-vault-accent text-white hover:bg-vault-accent/90 transition-colors disabled:opacity-50"
            >
              {saving ? t('settings.saving') : t('common.save')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Group card ───────────────────────────────────────────────────────

function GroupCard({
  group,
  subs,
  jobsData,
  groups,
  onEdit,
  onRun,
  onPauseResume,
  onDelete,
  onToggleSub,
  onCheckSub,
  onDeleteSub,
  onAutoDownloadToggle,
  onMoveToGroup,
  checkingId,
  defaultExpanded,
}: {
  group: SubscriptionGroup | null // null = ungrouped section
  subs: Subscription[]
  jobsData: Record<number, DownloadJob>
  groups: SubscriptionGroup[]
  onEdit: (group: SubscriptionGroup) => void
  onRun: (group: SubscriptionGroup) => void
  onPauseResume: (group: SubscriptionGroup) => void
  onDelete: (group: SubscriptionGroup) => void
  onToggleSub: (sub: Subscription) => void
  onCheckSub: (sub: Subscription) => void
  onDeleteSub: (sub: Subscription) => void
  onAutoDownloadToggle: (sub: Subscription) => void
  onMoveToGroup: (sub: Subscription, groupId: number | null) => void
  checkingId: number | null
  defaultExpanded: boolean
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  const isUngrouped = group === null

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
      {/* Group header */}
      <div
        className="flex items-center gap-2 px-4 py-3 cursor-pointer select-none hover:bg-vault-bg/50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-vault-text-muted shrink-0">
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </span>
        <FolderOpen
          size={16}
          className={isUngrouped ? 'text-vault-text-muted' : 'text-vault-accent'}
        />
        <span className="flex-1 font-medium text-sm text-vault-text truncate">
          {isUngrouped ? t('subscriptions.ungrouped') : group.name}
        </span>

        {/* Group meta */}
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[10px] text-vault-text-muted hidden sm:block">
            {t('subscriptions.groupSubCount', { count: String(subs.length) })}
          </span>

          {!isUngrouped && (
            <>
              {group.is_system && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-vault-border text-vault-text-muted">
                  {t('subscriptions.groupSystemTag')}
                </span>
              )}
              {groupStatusBadge(group.status)}
              {group.last_run_at && (
                <span className="text-[10px] text-vault-text-muted hidden md:block">
                  {t('subscriptions.groupLastRun')}: {timeAgo(group.last_run_at)}
                </span>
              )}
            </>
          )}
        </div>

        {/* Group actions — stop propagation so clicking them doesn't toggle accordion */}
        {!isUngrouped && (
          <div className="flex items-center gap-0.5 shrink-0" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => onRun(group)}
              className="p-1.5 rounded text-vault-text-muted hover:text-emerald-400 transition-colors"
              title={t('subscriptions.groupRunNow')}
            >
              <Play size={13} />
            </button>
            <button
              onClick={() => onPauseResume(group)}
              className="p-1.5 rounded text-vault-text-muted hover:text-yellow-400 transition-colors"
              title={
                group.status === 'paused'
                  ? t('subscriptions.groupResume')
                  : t('subscriptions.groupPause')
              }
            >
              <Pause size={13} />
            </button>
            <button
              onClick={() => onEdit(group)}
              className="p-1.5 rounded text-vault-text-muted hover:text-vault-accent transition-colors"
              title={t('subscriptions.groupEdit')}
            >
              <Settings2 size={13} />
            </button>
            {!group.is_system && (
              <button
                onClick={() => onDelete(group)}
                className="p-1.5 rounded text-vault-text-muted hover:text-red-400 transition-colors"
                title={t('subscriptions.groupDelete')}
              >
                <Trash2 size={13} />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Group schedule info */}
      {!isUngrouped && expanded && (
        <div className="px-4 pb-2 flex flex-wrap gap-3 text-[10px] text-vault-text-muted border-b border-vault-border/50">
          <span className="font-mono">{group.schedule}</span>
          <span>
            {t('subscriptions.groupConcurrency')}: {group.concurrency}
          </span>
          <span>
            {t('subscriptions.groupPriority')}: {group.priority}
          </span>
        </div>
      )}

      {/* Subscriptions inside group */}
      {expanded && (
        <div className="p-3 space-y-2">
          {subs.length === 0 ? (
            <p className="text-xs text-vault-text-muted text-center py-4">
              {t('subscriptions.noSubscriptions')}
            </p>
          ) : (
            subs.map((sub) => (
              <SubscriptionCard
                key={sub.id}
                sub={sub}
                latestJob={jobsData[sub.id] ?? null}
                groups={groups}
                onToggle={onToggleSub}
                onCheck={onCheckSub}
                onDelete={onDeleteSub}
                onAutoDownloadToggle={onAutoDownloadToggle}
                onMoveToGroup={onMoveToGroup}
                checkingId={checkingId}
              />
            ))
          )}
        </div>
      )}
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────

export default function SubscriptionsPage() {
  useLocale()

  // Subscriptions data
  const { data, mutate, isLoading } = useSubscriptions({ limit: 200 })
  const { trigger: createSub, isMutating: creating } = useCreateSubscription()
  const { trigger: updateSub } = useUpdateSubscription()
  const { trigger: deleteSub } = useDeleteSubscription()
  const { trigger: checkSub } = useCheckSubscription()

  // Groups data
  const { data: groupsData, mutate: mutateGroups } = useSubscriptionGroups()
  const { trigger: createGroupTrigger } = useCreateGroup()
  const { trigger: updateGroupTrigger } = useUpdateGroup()
  const { trigger: deleteGroupTrigger } = useDeleteGroup()
  const { trigger: runGroupTrigger } = useRunGroup()
  const { trigger: pauseGroupTrigger } = usePauseGroup()
  const { trigger: resumeGroupTrigger } = useResumeGroup()
  const { trigger: bulkMoveTrigger } = useBulkMove()

  const { lastSubCheck, lastJobUpdate } = useWs()

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
    { refreshInterval: 5000 },
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

  // Group subscriptions by group_id
  const groupedSubs = useMemo(() => {
    const byGroup: Record<number, Subscription[]> = {}
    const ungrouped: Subscription[] = []
    for (const sub of filteredSubscriptions) {
      if (sub.group_id !== null && sub.group_id !== undefined) {
        if (!byGroup[sub.group_id]) byGroup[sub.group_id] = []
        byGroup[sub.group_id].push(sub)
      } else {
        ungrouped.push(sub)
      }
    }
    return { byGroup, ungrouped }
  }, [filteredSubscriptions])

  // Forms state
  const [showAdd, setShowAdd] = useState(false)
  const [showBatch, setShowBatch] = useState(false)
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [autoDownload, setAutoDownload] = useState(true)
  const [cronExpr, setCronExpr] = useState('0 */2 * * *')
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null)
  const [checkingId, setCheckingId] = useState<number | null>(null)
  const [isDeletingAll, setIsDeletingAll] = useState(false)
  const [batchUrls, setBatchUrls] = useState('')
  const [batchAutoDownload, setBatchAutoDownload] = useState(true)
  const [batchCron, setBatchCron] = useState('0 */2 * * *')
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
    try {
      const result = await createSub({
        url: url.trim(),
        name: name.trim() || undefined,
        auto_download: autoDownload,
        cron_expr: cronExpr,
        group_id: selectedGroupId,
      })
      if (result?.duplicate) {
        toast.info(t('subscriptions.duplicateUpdated'))
      } else {
        toast.success(t('subscriptions.added'))
      }
      setUrl('')
      setName('')
      setAutoDownload(true)
      setCronExpr('0 */2 * * *')
      setSelectedGroupId(null)
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

      {/* Search */}
      {(data?.subscriptions?.length ?? 0) > 0 && (
        <div className="relative mb-4">
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
      ) : (
        <div className="space-y-3">
          {/* Named groups */}
          {groups.map((group) => (
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
              onDeleteSub={handleDelete}
              onAutoDownloadToggle={handleAutoDownloadToggle}
              onMoveToGroup={handleMoveToGroup}
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
              onDeleteSub={handleDelete}
              onAutoDownloadToggle={handleAutoDownloadToggle}
              onMoveToGroup={handleMoveToGroup}
              checkingId={checkingId}
              defaultExpanded={groups.length === 0}
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
