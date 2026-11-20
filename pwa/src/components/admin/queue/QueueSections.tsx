'use client'

import { useState } from 'react'
import { RotateCcw, XCircle, ChevronDown, ChevronUp } from 'lucide-react'
import { t } from '@/lib/i18n'
import type { SaqJob, SaqWorker } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { timeAgo, formatUptime, STATUS_STYLES } from '@/components/admin/queue/helpers'

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${STATUS_STYLES[status] ?? 'bg-gray-500/20 text-gray-400'}`}
    >
      {status}
    </span>
  )
}

export function WorkersSection({ workers }: { workers: SaqWorker[] }) {
  if (workers.length === 0) {
    return <p className="text-sm text-vault-text-secondary px-1">{t('admin.queue.noWorkers')}</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-vault-border text-vault-text-secondary">
            <th className="px-3 py-2 text-left font-medium">ID</th>
            <th className="px-3 py-2 text-right font-medium">{t('admin.queue.completed')}</th>
            <th className="px-3 py-2 text-right font-medium">{t('admin.queue.failed')}</th>
            <th className="px-3 py-2 text-right font-medium">{t('admin.queue.retried')}</th>
            <th className="px-3 py-2 text-right font-medium">{t('admin.queue.uptime')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-vault-border">
          {workers.map((w) => (
            <tr key={w.id} className="hover:bg-vault-card-hover transition-colors">
              <td className="px-3 py-2 font-mono text-vault-text truncate max-w-[12rem]">{w.id}</td>
              <td className="px-3 py-2 text-right text-green-400">{w.stats.complete}</td>
              <td className="px-3 py-2 text-right text-red-400">{w.stats.failed}</td>
              <td className="px-3 py-2 text-right text-yellow-400">{w.stats.retried}</td>
              <td className="px-3 py-2 text-right text-vault-text-secondary">
                {formatUptime(w.stats.uptime)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function JobRow({
  job,
  onRetry,
  onAbort,
}: {
  job: SaqJob
  onRetry: (key: string) => void
  onAbort: (key: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const canRetry = job.status === 'failed' || job.status === 'aborted' || job.status === 'complete'
  const canAbort = job.status === 'active' || job.status === 'queued' || job.status === 'new'

  return (
    <div
      className="border-b border-vault-border hover:bg-vault-card-hover transition-colors cursor-pointer"
      onClick={() => setExpanded((v) => !v)}
    >
      {/* Collapsed row */}
      <div className="flex items-center gap-3 px-4 py-2.5 text-sm">
        <span className="text-vault-text font-mono truncate flex-1 min-w-0">{job.function}</span>
        {job.is_cron && (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-vault-border/50 text-vault-text-muted">
            cron
          </span>
        )}
        <StatusBadge status={job.status} />
        <span className="text-vault-text-secondary text-xs shrink-0 hidden sm:inline">
          {timeAgo(job.queued)}
        </span>
        {job.progress > 0 && job.progress < 1 && (
          <div className="w-16 h-1.5 bg-vault-border rounded-full overflow-hidden shrink-0">
            <div
              className="h-full bg-blue-400 rounded-full"
              style={{ width: `${Math.round(job.progress * 100)}%` }}
            />
          </div>
        )}
        <span className="shrink-0 text-vault-text-muted">
          {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </span>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 space-y-3" onClick={(e) => e.stopPropagation()}>
          {/* Timestamps */}
          <div className="flex flex-wrap gap-4 text-xs text-vault-text-secondary">
            <span>
              {t('admin.queue.queued')}: {timeAgo(job.queued)}
            </span>
            {job.started && (
              <span>
                {t('admin.queue.startedAt')}: {timeAgo(job.started)}
              </span>
            )}
            {job.completed && (
              <span>
                {t('admin.queue.completedAt')}: {timeAgo(job.completed)}
              </span>
            )}
            <span>
              {t('admin.queue.attempts')}: {job.attempts}
            </span>
          </div>

          {/* kwargs */}
          {Object.keys(job.kwargs).length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase text-vault-text-muted mb-1">
                {t('admin.queue.kwargs')}
              </p>
              <pre className="text-xs text-vault-text whitespace-pre-wrap break-all bg-vault-bg rounded p-3 font-mono">
                {JSON.stringify(job.kwargs, null, 2)}
              </pre>
            </div>
          )}

          {/* error */}
          {job.error && (
            <div>
              <p className="text-[10px] font-bold uppercase text-vault-text-muted mb-1">
                {t('admin.queue.error')}
              </p>
              <pre className="text-xs text-red-400 whitespace-pre-wrap break-all bg-red-500/5 rounded p-3 font-mono">
                {job.error}
              </pre>
            </div>
          )}

          {/* result */}
          {job.result && (
            <div>
              <p className="text-[10px] font-bold uppercase text-vault-text-muted mb-1">
                {t('admin.queue.result')}
              </p>
              <pre className="text-xs text-vault-text whitespace-pre-wrap break-all bg-vault-bg rounded p-3 font-mono">
                {job.result}
              </pre>
            </div>
          )}

          {/* actions */}
          {(canRetry || canAbort) && (
            <div className="flex gap-2 pt-1">
              {canRetry && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onRetry(job.key)}
                  className="text-xs text-vault-text hover:text-vault-accent hover:border-vault-accent/50"
                >
                  <RotateCcw size={12} />
                  {t('admin.queue.retry')}
                </Button>
              )}
              {canAbort && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onAbort(job.key)}
                  className="text-xs text-vault-text hover:text-red-400 hover:border-red-500/30"
                >
                  <XCircle size={12} />
                  {t('admin.queue.abort')}
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────
