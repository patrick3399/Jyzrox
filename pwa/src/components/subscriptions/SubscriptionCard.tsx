'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import {
  AlertCircle,
  CheckCircle,
  Download,
  ExternalLink,
  Rss,
  ScanSearch,
  Trash2,
  Users,
} from 'lucide-react'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import type { DownloadJob, Subscription, SubscriptionGroup } from '@/lib/types'

const SOURCE_COLORS: Record<string, string> = {
  pixiv: 'bg-blue-500/20 text-blue-400',
  twitter: 'bg-sky-500/20 text-sky-400',
  ehentai: 'bg-purple-500/20 text-purple-400',
  weibo: 'bg-red-500/20 text-red-300',
}

function sourceBadge(source: string | null) {
  const cls = SOURCE_COLORS[source || ''] || 'bg-vault-border text-vault-text-muted'
  const label = source
    ? source === 'pixiv'
      ? 'Pixiv'
      : source === 'twitter'
        ? 'Twitter'
        : source === 'ehentai'
          ? 'E-Hentai'
          : source === 'weibo'
            ? 'Weibo'
            : source
    : t('subscriptions.sourceOther')
  return <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${cls}`}>{label}</span>
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

function JobStatusBadge({ job, hasGalleryTitle }: { job: DownloadJob; hasGalleryTitle: boolean }) {
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

  return <div className={hasGalleryTitle ? 'mt-1' : 'mt-2'}>{status}</div>
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
  checkingId,
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
  checkingId: number | null
}) {
  const [showMoveMenu, setShowMoveMenu] = useState(false)
  const [editingName, setEditingName] = useState(false)
  const [nameValue, setNameValue] = useState('')
  const moveMenuRef = useRef<HTMLDivElement | null>(null)
  const galleryHref = subscriptionGalleryHref(sub, latestJob)
  const galleryTitle = sub.gallery_title?.trim() || latestJob?.progress?.title?.trim()

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
                className="min-w-0 text-left text-sm font-medium text-vault-text break-all cursor-pointer hover:text-vault-accent transition-colors"
                title={t('subscriptions.editName')}
              >
                {sub.name || sub.url}
              </button>
            )}
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
      {galleryTitle &&
        (galleryHref ? (
          <Link
            href={galleryHref}
            className="mt-2 block truncate text-xs font-medium text-vault-accent hover:underline"
            title={galleryTitle}
          >
            {galleryTitle}
          </Link>
        ) : (
          <p className="mt-2 truncate text-xs font-medium text-vault-text" title={galleryTitle}>
            {galleryTitle}
          </p>
        ))}
      {latestJob && <JobStatusBadge job={latestJob} hasGalleryTitle={Boolean(galleryTitle)} />}
      {galleryHref && !galleryTitle && (
        <Link
          href={galleryHref}
          className="mt-1.5 inline-block text-[10px] text-vault-accent hover:underline"
        >
          {t('subscriptions.viewGallery')}
        </Link>
      )}

      {/* Bottom action row */}
      <div className="flex items-center gap-0.5 mt-2 pt-2 border-t border-vault-border/50">
        <button
          onClick={() => onCheck(sub)}
          disabled={checkingId === sub.id}
          className="p-1.5 rounded text-vault-text-muted hover:text-emerald-400 transition-colors disabled:opacity-60"
          title={t('subscriptions.downloadNow')}
          aria-label={t('subscriptions.downloadNow')}
        >
          <Download size={14} className={checkingId === sub.id ? 'animate-pulse' : ''} />
        </button>
        <button
          onClick={() => onBackfill(sub)}
          disabled={checkingId === sub.id}
          className="p-1.5 rounded text-vault-text-muted hover:text-amber-400 transition-colors disabled:opacity-60"
          title={t('subscriptions.backfill')}
          aria-label={t('subscriptions.backfillTitle')}
        >
          <ScanSearch size={14} />
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
