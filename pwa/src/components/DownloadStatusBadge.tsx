import type { ComponentProps } from 'react'
import { t } from '@/lib/i18n'
import { Badge } from '@/components/ui/badge'

interface DownloadStatusBadgeProps {
  status: 'proxy_only' | 'partial' | 'complete'
}

type Tone = NonNullable<ComponentProps<typeof Badge>['tone']>

const statusConfig: Record<DownloadStatusBadgeProps['status'], { labelKey: string; tone: Tone }> = {
  complete: { labelKey: 'library.statusComplete', tone: 'success' },
  partial: { labelKey: 'library.statusPartial', tone: 'warning' },
  proxy_only: { labelKey: 'library.statusProxyOnly', tone: 'accent' },
}

export function DownloadStatusBadge({ status }: DownloadStatusBadgeProps) {
  const { labelKey, tone } = statusConfig[status]

  return <Badge tone={tone}>{t(labelKey)}</Badge>
}
