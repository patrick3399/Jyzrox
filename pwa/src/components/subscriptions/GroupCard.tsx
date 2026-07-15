'use client'

import { useState } from 'react'
import { ChevronDown, ChevronRight, FolderOpen, Pause, Play, Settings2, Trash2 } from 'lucide-react'
import { SubscriptionCard, timeAgo } from './SubscriptionCard'
import { t } from '@/lib/i18n'
import type { DownloadJob, Subscription, SubscriptionGroup } from '@/lib/types'

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

export function GroupCard({
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
  onBackfillSub,
  onDeleteSub,
  onAutoDownloadToggle,
  onMoveToGroup,
  onRenameSub,
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
  onBackfillSub: (sub: Subscription) => void
  onDeleteSub: (sub: Subscription) => void
  onAutoDownloadToggle: (sub: Subscription) => void
  onMoveToGroup: (sub: Subscription, groupId: number | null) => void
  onRenameSub: (sub: Subscription, name: string) => void
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
                onBackfill={onBackfillSub}
                onDelete={onDeleteSub}
                onAutoDownloadToggle={onAutoDownloadToggle}
                onMoveToGroup={onMoveToGroup}
                onRename={onRenameSub}
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
