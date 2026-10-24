'use client'

import { useState } from 'react'
import Link from 'next/link'
import {
  AlertCircle,
  Check,
  CheckCircle,
  Clock,
  ChevronDown,
  Download,
  ExternalLink,
  SlidersHorizontal,
  MoreHorizontal,
  Rss,
  ScanSearch,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { useCheckUrl } from '@/hooks/useDownloadQueue'
import { MediaPolicyFields } from '@/components/download/MediaPolicyFields'
import { isDefaultMediaPolicy, mediaPolicyFromOptions, withMediaPolicy } from '@/lib/mediaPolicy'
import { CRON_PRESETS } from './constants'
import { sourceLabel } from './sourceGrouping'
import type { DownloadJob, MediaPolicy, Subscription, SubscriptionGroup } from '@/lib/types'

const SOURCE_COLORS: Record<string, string> = {
  pixiv: 'bg-blue-500/20 text-blue-400',
  twitter: 'bg-sky-500/20 text-sky-400',
  ehentai: 'bg-purple-500/20 text-purple-400',
  weibo: 'bg-red-500/20 text-red-300',
}

function sourceBadge(source: string | null) {
  const cls = SOURCE_COLORS[source || ''] || 'bg-vault-border text-vault-text-muted'
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${cls}`}>
      {sourceLabel(source)}
    </span>
  )
}

export function timeAgo(iso: string | null): string {
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

// ── Sub-components ───────────────────────────────────────────────────

function JobStatusBadge({ job }: { job: DownloadJob }) {
  let status: React.ReactNode = null

  if (job.status === 'running') {
    const downloaded = job.progress?.downloaded ?? 0
    const total = job.progress?.total
    const pct = total ? Math.min(100, Math.round((downloaded / total) * 100)) : 0
    status = (
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
    )
  } else if (job.status === 'done') {
    status = (
      <div className="flex items-center gap-1.5 text-[10px]">
        <CheckCircle size={12} className="text-green-400" />
        <span className="text-green-400">{t('subscriptions.downloadComplete')}</span>
      </div>
    )
  } else if (job.status === 'failed') {
    status = (
      <div className="flex items-center gap-1.5 text-[10px]">
        <AlertCircle size={12} className="text-red-400" />
        <span className="text-red-400 truncate" title={job.error || undefined}>
          {job.error || t('subscriptions.downloadFailed')}
        </span>
      </div>
    )
  } else if (job.status === 'queued') {
    status = (
      <div className="flex items-center gap-1.5 text-[10px] text-vault-text-muted">
        <Download size={10} />
        <span>{t('subscriptions.queued')}</span>
      </div>
    )
  }

  if (!status) return null

  return status
}

/**
 * Check interval of one subscription.
 *
 * A grouped subscription is scheduled by its group, so its own cron_expr is
 * inert: show the group's schedule read-only instead of a value that would be
 * silently ignored. An ungrouped one is scheduled by its own cron_expr, which
 * is editable here.
 */
function IntervalRow({
  sub,
  group,
  onCronChange,
}: {
  sub: Subscription
  group: SubscriptionGroup | null
  onCronChange?: (sub: Subscription, cron: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  if (sub.group_id !== null && sub.group_id !== undefined) {
    return (
      <div
        data-testid="subscription-interval"
        className="flex min-w-0 items-center gap-1.5 text-[10px] text-vault-text-muted"
      >
        <Clock size={11} className="shrink-0" />
        <span className="truncate">
          {t('subscriptions.intervalFromGroup', {
            name: group?.name ?? String(sub.group_id),
            schedule: group?.schedule ?? '',
          })}
        </span>
      </div>
    )
  }

  const current = sub.cron_expr ?? ''
  const commit = () => {
    const next = draft.trim()
    setEditing(false)
    if (next && next !== current) onCronChange?.(sub, next)
  }

  if (!editing) {
    return (
      <div
        data-testid="subscription-interval"
        className="flex min-w-0 items-center gap-1.5 text-[10px] text-vault-text-muted"
      >
        <Clock size={11} className="shrink-0" />
        <span>{t('subscriptions.cronExpr')}:</span>
        {onCronChange ? (
          <button
            type="button"
            onClick={() => {
              setDraft(current)
              setEditing(true)
            }}
            className="rounded bg-vault-input px-1.5 py-0.5 font-mono text-vault-text transition-colors hover:text-vault-accent"
            title={t('subscriptions.editInterval')}
          >
            {current || '—'}
          </button>
        ) : (
          <span className="font-mono text-vault-text">{current || '—'}</span>
        )}
      </div>
    )
  }

  return (
    <div
      data-testid="subscription-interval"
      className="flex flex-wrap items-center gap-1.5 text-[10px] text-vault-text-muted"
    >
      <Clock size={11} className="shrink-0" />
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') setEditing(false)
        }}
        aria-label={t('subscriptions.cronExpr')}
        className="w-28 rounded border border-vault-border bg-vault-input px-1.5 py-0.5 font-mono text-xs text-vault-text focus:border-vault-accent focus:outline-none"
      />
      {CRON_PRESETS.map((p) => (
        <button
          key={p.value}
          type="button"
          onClick={() => setDraft(p.value)}
          className={`rounded px-1.5 py-0.5 transition-colors ${
            draft === p.value
              ? 'bg-vault-accent/20 text-vault-accent'
              : 'border border-vault-border bg-vault-bg hover:text-vault-text'
          }`}
        >
          {p.label}
        </button>
      ))}
      <button
        type="button"
        onClick={commit}
        className="rounded p-1 text-emerald-400 hover:bg-vault-card"
        aria-label={t('common.save')}
      >
        <Check size={12} />
      </button>
      <button
        type="button"
        onClick={() => setEditing(false)}
        className="rounded p-1 hover:bg-vault-card hover:text-vault-text"
        aria-label={t('common.cancel')}
      >
        <X size={12} />
      </button>
    </div>
  )
}

/**
 * Collapsible per-subscription download options (newest N files, include videos).
 *
 * Support is resolved by URL on the server, so the check only runs while the row
 * is expanded. Save sends the whole `download_options` object because the PATCH
 * replaces it wholesale; `withMediaPolicy` keeps every other key (e.g. `fanbox`).
 */
function DownloadOptionsRow({
  sub,
  onDownloadOptionsChange,
}: {
  sub: Subscription
  onDownloadOptionsChange?: (sub: Subscription, options: Record<string, unknown>) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const stored = mediaPolicyFromOptions(sub.download_options)
  const [policy, setPolicy] = useState<MediaPolicy>(stored)
  const { data: check } = useCheckUrl(expanded ? sub.url : '')
  const supported = check?.supports_media_policy === true
  const dirty =
    policy.max_files !== stored.max_files || policy.include_videos !== stored.include_videos

  return (
    <div data-testid="subscription-download-options" className="text-[10px] text-vault-text-muted">
      <button
        type="button"
        onClick={() => {
          if (!expanded) setPolicy(stored)
          setExpanded((value) => !value)
        }}
        aria-expanded={expanded}
        className="flex items-center gap-1.5 transition-colors hover:text-vault-text"
      >
        <SlidersHorizontal size={11} className="shrink-0" />
        <span>{t('mediaPolicy.title')}</span>
        {!isDefaultMediaPolicy(stored) && (
          <span className="rounded bg-vault-accent/15 px-1.5 py-0.5 text-vault-accent">
            {stored.max_files !== null ? stored.max_files : t('mediaPolicy.allPlaceholder')}
            {stored.include_videos ? '' : ' · ' + t('mediaPolicy.noVideos')}
          </span>
        )}
        <ChevronDown
          size={11}
          className={`shrink-0 transition-transform ${expanded ? 'rotate-180' : ''}`}
        />
      </button>
      {expanded && supported && (
        <div>
          <MediaPolicyFields value={policy} onChange={setPolicy} />
          <button
            type="button"
            disabled={!dirty || !onDownloadOptionsChange}
            onClick={() =>
              onDownloadOptionsChange?.(sub, withMediaPolicy(sub.download_options, policy))
            }
            className="mt-2 rounded bg-vault-accent px-2 py-1 text-xs text-white transition-colors hover:bg-vault-accent/90 disabled:opacity-40"
          >
            {t('common.save')}
          </button>
        </div>
      )}
    </div>
  )
}

function subscriptionGalleryHref(sub: Subscription, latestJob: DownloadJob | null): string | null {
  const source = latestJob?.gallery_source ?? sub.gallery_source
  const sourceId = latestJob?.gallery_source_id ?? sub.gallery_source_id
  if (!source || !sourceId) return null
  return `/library/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`
}

export function SubscriptionCard({
  sub,
  latestJob,
  groups,
  onToggle,
  onCheck,
  onBackfill,
  onDelete,
  onAutoDownloadToggle,
  onMoveToGroup,
  onRename,
  onCronChange,
  onDownloadOptionsChange,
  checkingId,
  showGroup = false,
}: {
  sub: Subscription
  latestJob: DownloadJob | null
  groups: SubscriptionGroup[]
  onToggle: (sub: Subscription) => void
  onCheck: (sub: Subscription) => void
  onBackfill: (sub: Subscription) => void
  onDelete: (sub: Subscription) => void
  onAutoDownloadToggle: (sub: Subscription) => void
  onMoveToGroup: (sub: Subscription, groupId: number | null) => void
  onRename: (sub: Subscription, name: string) => void
  onCronChange?: (sub: Subscription, cron: string) => void
  onDownloadOptionsChange?: (sub: Subscription, options: Record<string, unknown>) => void
  checkingId: number | null
  /** Show the schedule group on the card itself (the list is not laid out by group). */
  showGroup?: boolean
}) {
  const [showActions, setShowActions] = useState(false)
  const isGrouped = sub.group_id !== null && sub.group_id !== undefined
  const group = groups.find((g) => g.id === sub.group_id) ?? null
  const [editingName, setEditingName] = useState(false)
  const [nameValue, setNameValue] = useState('')
  const galleryHref = subscriptionGalleryHref(sub, latestJob)
  const galleryTitle = sub.gallery_title?.trim() || latestJob?.progress?.title?.trim()
  const isRunning = latestJob?.status === 'running'

  return (
    <div className="bg-vault-bg border border-vault-border/50 rounded-lg p-3">
      {/* Top row: name + badges on left, toggle on right */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          {editingName ? (
            <input
              autoFocus
              value={nameValue}
              placeholder={t('subscriptions.namePlaceholder')}
              onChange={(e) => setNameValue(e.target.value)}
              onBlur={() => {
                const next = nameValue.trim()
                if (next !== (sub.name ?? '')) onRename(sub, next)
                setEditingName(false)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') e.currentTarget.blur()
                if (e.key === 'Escape') setEditingName(false)
              }}
              className="text-sm font-medium text-vault-text bg-vault-input border border-vault-border rounded px-1.5 py-0.5 min-w-0 flex-1 focus:outline-none focus:border-vault-accent"
            />
          ) : (
            <button
              type="button"
              onClick={() => {
                setNameValue(sub.name ?? '')
                setEditingName(true)
              }}
              className="min-w-0 max-w-full truncate text-left text-sm font-medium text-vault-text cursor-pointer hover:text-vault-accent transition-colors"
              title={t('subscriptions.editName')}
            >
              {sub.name || sub.url}
            </button>
          )}
          {sourceBadge(sub.source)}
          {showGroup && isGrouped && (
            <span
              data-testid="subscription-group-badge"
              className="flex min-w-0 items-center gap-1 rounded bg-vault-accent/15 px-1.5 py-0.5 text-[10px] text-vault-accent"
              title={t('subscriptions.intervalFromGroup', {
                name: group?.name ?? String(sub.group_id),
                schedule: group?.schedule ?? '',
              })}
            >
              <Users size={10} className="shrink-0" />
              <span className="truncate">{group?.name ?? `#${sub.group_id}`}</span>
              {group && <span className="shrink-0 font-mono">{group.schedule}</span>}
            </span>
          )}
          <button
            onClick={() => onAutoDownloadToggle(sub)}
            className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${sub.auto_download ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/15 text-red-400/70'}`}
            title={
              sub.auto_download
                ? t('subscriptions.autoDownloadOn')
                : t('subscriptions.autoDownloadOff')
            }
          >
            {t('subscriptions.autoDownload')}
          </button>
        </div>

        <button
          onClick={() => onToggle(sub)}
          role="switch"
          aria-checked={sub.enabled}
          aria-label={sub.name || sub.url}
          className={`relative w-9 h-5 rounded-full transition-colors shrink-0 mt-0.5 ${sub.enabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${sub.enabled ? 'translate-x-4' : ''}`}
          />
        </button>
      </div>

      {/* Gallery identity + compact terminal status */}
      {(galleryTitle || galleryHref || (latestJob && !isRunning)) && (
        <div className="mt-2 flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <div className="min-w-0 flex-1 basis-48">
            {galleryTitle && galleryHref ? (
              <Link
                href={galleryHref}
                className="block truncate text-xs font-medium text-vault-accent hover:underline"
                title={galleryTitle}
              >
                {galleryTitle}
              </Link>
            ) : galleryTitle ? (
              <p className="truncate text-xs font-medium text-vault-text" title={galleryTitle}>
                {galleryTitle}
              </p>
            ) : galleryHref ? (
              <Link href={galleryHref} className="text-xs text-vault-accent hover:underline">
                {t('subscriptions.viewGallery')}
              </Link>
            ) : null}
          </div>
          {latestJob && !isRunning && (
            <div className="min-w-0 max-w-full shrink-0">
              <JobStatusBadge job={latestJob} />
            </div>
          )}
        </div>
      )}

      {/* Running progress and errors expand only while relevant. */}
      {latestJob && isRunning && (
        <div className="mt-1">
          <JobStatusBadge job={latestJob} />
        </div>
      )}
      {sub.last_error && !latestJob && (
        <p className="mt-1 truncate text-[10px] text-red-400" title={sub.last_error}>
          {sub.last_error}
        </p>
      )}

      {/* Compact footer: recency on the left, frequent actions on the right. */}
      <div className="mt-2 flex min-h-7 items-center justify-between gap-2 border-t border-vault-border/50 pt-2">
        <span
          className={`min-w-0 truncate text-[10px] ${
            sub.last_status === 'ok'
              ? 'text-emerald-400'
              : sub.last_status === 'failed'
                ? 'text-red-400'
                : 'text-vault-text-muted'
          }`}
        >
          {sub.last_checked_at
            ? `${t('subscriptions.lastChecked')}: ${timeAgo(sub.last_checked_at)}`
            : t('settings.tasks.never')}
        </span>
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            onClick={() => onCheck(sub)}
            disabled={checkingId === sub.id}
            className="rounded p-1.5 text-vault-text-muted transition-colors hover:text-emerald-400 disabled:opacity-60"
            title={t('subscriptions.downloadNow')}
            aria-label={t('subscriptions.downloadNow')}
          >
            <Download size={14} className={checkingId === sub.id ? 'animate-pulse' : ''} />
          </button>
          <button
            type="button"
            onClick={() => setShowActions((value) => !value)}
            className={`rounded p-1.5 transition-colors ${showActions ? 'bg-vault-border text-vault-text' : 'text-vault-text-muted hover:text-vault-text'}`}
            title={t('common.more')}
            aria-label={t('common.more')}
            aria-expanded={showActions}
          >
            <MoreHorizontal size={14} />
          </button>
        </div>
      </div>

      {showActions && (
        <div className="mt-2 grid grid-cols-2 gap-1 border-t border-vault-border/50 pt-2 text-xs">
          <button
            onClick={() => onBackfill(sub)}
            disabled={checkingId === sub.id}
            className="flex items-center gap-1.5 rounded px-2 py-1.5 text-vault-text-muted transition-colors hover:bg-vault-card hover:text-amber-400 disabled:opacity-60"
          >
            <ScanSearch size={13} />
            {t('subscriptions.backfill')}
          </button>
          <a
            href={sub.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 rounded px-2 py-1.5 text-vault-text-muted transition-colors hover:bg-vault-card hover:text-vault-text"
          >
            <ExternalLink size={13} />
            {t('subscriptions.url')}
          </a>
          <button
            onClick={() => {
              navigator.clipboard.writeText(
                `${window.location.origin}/api/rss/subscriptions/${sub.id}?token=YOUR_API_TOKEN`,
              )
              toast.success(t('rss.copied'))
            }}
            className="flex items-center gap-1.5 rounded px-2 py-1.5 text-vault-text-muted transition-colors hover:bg-vault-card hover:text-orange-400"
          >
            <Rss size={13} />
            {t('rss.subscriptionFeed')}
          </button>
          <button
            onClick={() => onDelete(sub)}
            className="flex items-center gap-1.5 rounded px-2 py-1.5 text-vault-text-muted transition-colors hover:bg-red-900/20 hover:text-red-400"
          >
            <Trash2 size={13} />
            {t('common.delete')}
          </button>
          <div className="col-span-2 mt-1 border-t border-vault-border/50 px-2 pt-2">
            <IntervalRow sub={sub} group={group} onCronChange={onCronChange} />
          </div>
          <div className="col-span-2 px-2 pt-1">
            <DownloadOptionsRow sub={sub} onDownloadOptionsChange={onDownloadOptionsChange} />
          </div>
          {groups.length > 0 && (
            <label className="col-span-2 flex items-center gap-2 px-2 pt-1 text-vault-text-muted">
              <Users size={13} className="shrink-0" />
              <span className="shrink-0">{t('subscriptions.moveTo')}</span>
              <select
                value={sub.group_id ?? ''}
                onChange={(event) => {
                  onMoveToGroup(sub, event.target.value ? Number(event.target.value) : null)
                  setShowActions(false)
                }}
                className="min-w-0 flex-1 rounded border border-vault-border bg-vault-input px-2 py-1 text-xs text-vault-text"
              >
                <option value="">{t('subscriptions.noGroup')}</option>
                {groups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}
    </div>
  )
}
