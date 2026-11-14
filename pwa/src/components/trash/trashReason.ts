import { t } from '@/lib/i18n'
import type { TrashReason } from '@/lib/types'

export const REASON_TONE: Record<TrashReason, 'neutral' | 'accent' | 'warning'> = {
  user: 'neutral',
  merged: 'accent',
  source_missing: 'warning',
}

export function reasonLabel(reason: TrashReason): string {
  return t(`trash.reason.${reason}`)
}
