import type { DownloadJob } from '@/lib/types'

interface JobStatusBadgeProps {
  status: DownloadJob['status']
}

const statusConfig: Record<DownloadJob['status'], { label: string; className: string }> = {
  queued: {
    label: 'Queued',
    className: 'bg-yellow-900/50 text-yellow-300 border-yellow-800',
  },
  running: {
    label: 'Running...',
    className: 'bg-blue-900/50 text-blue-300 border-blue-800 animate-pulse',
  },
  done: {
    label: 'Done',
    className: 'bg-green-900/50 text-green-300 border-green-800',
  },
  failed: {
    label: 'Failed',
    className: 'bg-red-900/50 text-red-300 border-red-800',
  },
  cancelled: {
    label: 'Cancelled',
    className: 'bg-gray-800/80 text-gray-400 border-gray-700',
  },
}

export function JobStatusBadge({ status }: JobStatusBadgeProps) {
  const { label, className } = statusConfig[status]

  return (
    <span
      className={`
        inline-block px-1.5 py-0.5
        rounded border text-xs font-medium
        ${className}
      `}
    >
      {label}
    </span>
  )
}
