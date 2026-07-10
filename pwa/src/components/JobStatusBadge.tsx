import type { DownloadJob } from '@/lib/types'
import { t } from '@/lib/i18n'

interface JobStatusBadgeProps {
  status: DownloadJob['status']
}

const statusConfig: Record<DownloadJob['status'], { labelKey: string; className: string }> = {
  queued: {
    labelKey: 'admin.queue.queued',
    className: 'bg-yellow-900/50 text-yellow-300 border-yellow-800',
  },
  running: {
    labelKey: 'settings.tasks.statusRunning',
    className: 'bg-blue-900/50 text-blue-300 border-blue-800 animate-pulse',
  },
  done: {
    labelKey: 'admin.queue.completed',
    className: 'bg-green-900/50 text-green-300 border-green-800',
  },
  failed: {
    labelKey: 'admin.queue.failed',
    className: 'bg-red-900/50 text-red-300 border-red-800',
  },
  cancelled: {
    labelKey: 'queue.gdlStateCancelled',
    className: 'bg-gray-800/80 text-gray-400 border-gray-700',
  },
  paused: {
    labelKey: 'queue.gdlStatePaused',
    className: 'bg-orange-900/50 text-orange-300 border-orange-800',
  },
  partial: {
    labelKey: 'library.statusPartial',
    className: 'bg-amber-900/50 text-amber-300 border-amber-800',
  },
}

export function JobStatusBadge({ status }: JobStatusBadgeProps) {
  const { labelKey, className } = statusConfig[status]

  return (
    <span
      className={`
        inline-block px-1.5 py-0.5
        rounded border text-xs font-medium
        ${className}
      `}
    >
      {t(labelKey)}
    </span>
  )
}
