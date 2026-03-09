/**
 * i18n abstraction layer — simple key-value dictionary.
 *
 * To add a new language:
 *   1. Create a new file (e.g. `ja.ts`) with `export default { ... }`
 *   2. Import it below and add to `locales`
 *   3. Add the locale key to `SUPPORTED_LOCALES`
 *   4. Add `common.locale.ja` key to all locale files
 *
 * Usage:
 *   import { t } from '@/lib/i18n'
 *   <span>{t('nav.dashboard')}</span>
 */

import en from './en'
import zhTW from './zh-TW'
import ja from './ja'
import ko from './ko'

export const SUPPORTED_LOCALES = ['en', 'zh-TW', 'ja', 'ko'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

const locales: Record<string, Record<string, string>> = {
  en,
  'zh-TW': zhTW,
  ja,
  ko,
}

let currentLocale: string = 'en'

export function setLocale(locale: Locale) {
  if (locales[locale]) currentLocale = locale
}

export function getLocale(): Locale {
  return currentLocale as Locale
}

export function t(key: string, params?: Record<string, string | number>): string {
  let value = locales[currentLocale]?.[key] ?? locales['en']?.[key] ?? key

  // Plural support: "singular|plural" format
  if (params && 'count' in params && value.includes('|')) {
    const forms = value.split('|')
    const count = Number(params.count)
    // CJK languages have no plural distinction — use first form
    if (currentLocale === 'zh-TW' || currentLocale === 'ja' || currentLocale === 'ko') {
      value = forms[0]
    } else {
      value = count === 1 ? forms[0] : (forms[1] || forms[0])
    }
  }

  if (params) {
    for (const [k, v] of Object.entries(params)) {
      value = value.replaceAll(`{${k}}`, String(v))
    }
  }
  return value
}

const LOCALE_TO_INTL: Record<string, string> = {
  'en': 'en-US',
  'zh-TW': 'zh-TW',
  'ja': 'ja-JP',
  'ko': 'ko-KR',
}

/** Format a date string or Date object according to the current locale */
export function formatDate(date: string | Date, options?: Intl.DateTimeFormatOptions): string {
  const d = typeof date === 'string' ? new Date(date) : date
  const intlLocale = LOCALE_TO_INTL[currentLocale] || 'en-US'
  return new Intl.DateTimeFormat(intlLocale, options ?? {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(d)
}

/** Format a number according to the current locale */
export function formatNumber(n: number, options?: Intl.NumberFormatOptions): string {
  const intlLocale = LOCALE_TO_INTL[currentLocale] || 'en-US'
  return new Intl.NumberFormat(intlLocale, options).format(n)
}

/** Format bytes into a human-readable size string */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  const value = bytes / Math.pow(1024, i)
  return `${formatNumber(value, { maximumFractionDigits: 1 })} ${units[i]}`
}
