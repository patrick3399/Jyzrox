'use client'
import { t } from '@/lib/i18n'

interface StatusBadgeProps {
  status: string | null
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = (() => {
    switch (status) {
      case 'ok':
        return { color: 'text-green-400', label: t('settings.tasks.statusOk') }
      case 'failed':
        return { color: 'text-red-400', label: t('settings.tasks.statusFailed') }
      case 'running':
        return { color: 'text-blue-400', label: t('settings.tasks.statusRunning') }
      case 'skipped':
        return { color: 'text-yellow-400', label: t('settings.tasks.statusSkipped') }
      default:
        return { color: 'text-vault-text-muted', label: t('settings.tasks.never') }
    }
  })()

  return (
    <span className={`text-[10px] font-medium ${config.color}`}>
      {config.label}
    </span>
  )
}
