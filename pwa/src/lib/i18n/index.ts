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

export const SUPPORTED_LOCALES = ['en', 'zh-TW', 'zh-CN', 'ja', 'ko'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]
export const DEFAULT_LOCALE: Locale = 'en'

type Dictionary = Record<string, string>

const locales: Partial<Record<Locale, Dictionary>> = {
  en,
}

const localeLoaders: Record<Exclude<Locale, 'en'>, () => Promise<{ default: Dictionary }>> = {
  'zh-TW': () => import('./zh-TW'),
  'zh-CN': () => import('./zh-CN'),
  ja: () => import('./ja'),
  ko: () => import('./ko'),
}

const pendingLocales = new Map<Locale, Promise<void>>()

let currentLocale: Locale = DEFAULT_LOCALE

/** Resolve browser or HTTP language preferences to one of the shipped UI locales. */
export function resolveLocale(preferences?: string | readonly string[] | null): Locale {
  const candidates = Array.isArray(preferences)
    ? preferences
    : typeof preferences === 'string'
      ? preferences
          .split(',')
          .map((part, index) => {
            const [language, ...parameters] = part.trim().split(';')
            const q = parameters.find((parameter) => parameter.trim().startsWith('q='))
            const weight = q ? Number(q.trim().slice(2)) : 1
            return { language, weight: Number.isFinite(weight) ? weight : 0, index }
          })
          .sort((a, b) => b.weight - a.weight || a.index - b.index)
          .map(({ language }) => language)
      : []

  for (const candidate of candidates) {
    const language = candidate.toLowerCase()
    if (language === 'zh-cn' || language.startsWith('zh-hans')) return 'zh-CN'
    if (language === 'zh-tw' || language === 'zh-hk' || language.startsWith('zh-hant'))
      return 'zh-TW'
    if (language.startsWith('zh')) return 'zh-TW'
    if (language.startsWith('ja')) return 'ja'
    if (language.startsWith('ko')) return 'ko'
    if (language.startsWith('en')) return 'en'
  }
  return DEFAULT_LOCALE
}

/** Resolve the browser preference for client-side and offline use. */
export function detectBrowserLocale(): Locale {
  if (typeof navigator === 'undefined') return DEFAULT_LOCALE
  return resolveLocale(navigator.languages?.length ? navigator.languages : navigator.language)
}

export async function loadLocale(locale: Locale): Promise<void> {
  if (locales[locale]) return
  const existing = pendingLocales.get(locale)
  if (existing) return existing
  if (locale === 'en') return

  const pending = localeLoaders[locale]()
    .then((module) => {
      locales[locale] = module.default
    })
    .finally(() => {
      // Always clear the in-flight entry — including on a failed import — so a
      // transient chunk-load error does not permanently cache a rejected
      // promise and block every later retry until a full reload.
      pendingLocales.delete(locale)
    })
  pendingLocales.set(locale, pending)
  return pending
}

export function setLocale(locale: Locale) {
  if (locales[locale]) currentLocale = locale
}

export function getLocale(): Locale {
  return currentLocale
}

export function t(key: string, params?: Record<string, string | number>): string {
  let value = locales[currentLocale]?.[key] ?? en[key] ?? key

  // Plural support: "singular|plural" format
  if (params && 'count' in params && value.includes('|')) {
    const forms = value.split('|')
    const count = Number(params.count)
    // CJK languages have no plural distinction — use first form
    if (
      currentLocale === 'zh-TW' ||
      currentLocale === 'zh-CN' ||
      currentLocale === 'ja' ||
      currentLocale === 'ko'
    ) {
      value = forms[0]
    } else {
      value = count === 1 ? forms[0] : forms[1] || forms[0]
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
  en: 'en-US',
  'zh-TW': 'zh-TW',
  'zh-CN': 'zh-CN',
  ja: 'ja-JP',
  ko: 'ko-KR',
}

/** Format a date string or Date object according to the current locale */
export function formatDate(date: string | Date, options?: Intl.DateTimeFormatOptions): string {
  try {
    const d = typeof date === 'string' ? new Date(date) : date
    if (isNaN(d.getTime())) return ''
    const intlLocale = LOCALE_TO_INTL[currentLocale] || 'en-US'
    return new Intl.DateTimeFormat(
      intlLocale,
      options ?? {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      },
    ).format(d)
  } catch {
    return ''
  }
}

/** Format a number according to the current locale */
export function formatNumber(n: number, options?: Intl.NumberFormatOptions): string {
  const intlLocale = LOCALE_TO_INTL[currentLocale] || 'en-US'
  return new Intl.NumberFormat(intlLocale, options).format(n)
}

/**
 * Format bytes into a human-readable size string.
 *
 * Scales by 1024, so the units are the binary ones (KiB/MiB/GiB) rather than
 * the SI ones -- same basis as `free -h`, which also labels them with the "i".
 */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  const value = bytes / Math.pow(1024, i)
  return `${formatNumber(value, { maximumFractionDigits: 1 })} ${units[i]}`
}
