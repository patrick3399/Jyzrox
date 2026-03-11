'use client'
import { t } from '@/lib/i18n'

export function timeAgo(dateStr: string | null): string {
  if (!dateStr) return ''
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return t('timeUtils.justNow')
  if (minutes < 60) return t('timeUtils.minutesAgo', { n: String(minutes) })
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return t('timeUtils.hoursAgo', { n: String(hours) })
  const days = Math.floor(hours / 24)
  return t('timeUtils.daysAgo', { n: String(days) })
}
