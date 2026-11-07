'use client'

import { formatBytes, t } from '@/lib/i18n'
import type { TrashSummary } from '@/lib/types'

function formatExpiry(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString()
}

export function TrashSummaryBar({ summary }: { summary: TrashSummary }) {
  const { purge } = summary
  const percent = purge && purge.total > 0 ? Math.min(100, Math.round((purge.done / purge.total) * 100)) : 0
  return (
    <div
      className="bg-vault-card border border-vault-border rounded-lg p-3 space-y-2"
      data-testid="trash-summary"
    >
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <div className="min-w-0">
          <dt className="text-vault-text-muted">{t('trash.summaryCount')}</dt>
          <dd className="font-medium text-vault-text truncate">{summary.count}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-vault-text-muted">{t('trash.summarySize')}</dt>
          <dd className="font-medium text-vault-text truncate">{formatBytes(summary.logical_bytes)}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-vault-text-muted">{t('trash.summaryReclaimable')}</dt>
          <dd className="font-medium text-vault-text truncate">
            {formatBytes(summary.reclaimable_bytes)}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-vault-text-muted">{t('trash.summaryNextExpiry')}</dt>
          <dd className="font-medium text-vault-text truncate">{formatExpiry(summary.next_expiry_at)}</dd>
        </div>
      </dl>
      {purge && (
        <div data-testid="trash-purge-progress" className="space-y-1">
          <div className="text-xs text-vault-text-secondary">
            {t('trash.purgeProgress', { done: String(purge.done), total: String(purge.total) })}
          </div>
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={purge.total}
            aria-valuenow={purge.done}
            className="h-1.5 w-full overflow-hidden rounded bg-vault-input"
          >
            <div
              className="h-full bg-vault-danger transition-[width] duration-(--motion-base)"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
