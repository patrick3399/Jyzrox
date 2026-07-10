import { t } from '@/lib/i18n'

interface DownloadStatusBadgeProps {
  status: 'proxy_only' | 'partial' | 'complete'
}

const statusConfig: Record<
  DownloadStatusBadgeProps['status'],
  { labelKey: string; className: string }
> = {
  complete: {
    labelKey: 'library.statusComplete',
    className: 'bg-green-900/50 text-green-300 border-green-800',
  },
  partial: {
    labelKey: 'library.statusPartial',
    className: 'bg-yellow-900/50 text-yellow-300 border-yellow-800',
  },
  proxy_only: {
    labelKey: 'library.statusProxyOnly',
    className: 'bg-blue-900/50 text-blue-300 border-blue-800',
  },
}

export function DownloadStatusBadge({ status }: DownloadStatusBadgeProps) {
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
