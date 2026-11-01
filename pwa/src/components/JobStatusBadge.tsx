import type { ComponentProps } from 'react'
import type { DownloadJob } from '@/lib/types'
import { t } from '@/lib/i18n'
import { Badge } from '@/components/ui/badge'

interface JobStatusBadgeProps {
  status: DownloadJob['status']
}

type Tone = NonNullable<ComponentProps<typeof Badge>['tone']>

const statusConfig: Record<DownloadJob['status'], { labelKey: string; tone: Tone; className?: string }> = {
  queued: { labelKey: 'admin.queue.queued', tone: 'neutral' },
  running: { labelKey: 'settings.tasks.statusRunning', tone: 'accent', className: 'animate-pulse' },
  done: { labelKey: 'admin.queue.completed', tone: 'success' },
  failed: { labelKey: 'admin.queue.failed', tone: 'danger' },
  cancelled: { labelKey: 'queue.gdlStateCancelled', tone: 'neutral' },
  paused: { labelKey: 'queue.gdlStatePaused', tone: 'neutral' },
  partial: { labelKey: 'library.statusPartial', tone: 'warning' },
}

export function JobStatusBadge({ status }: JobStatusBadgeProps) {
  const { labelKey, tone, className } = statusConfig[status]

  return (
    <Badge tone={tone} className={className}>
      {t(labelKey)}
    </Badge>
  )
}
