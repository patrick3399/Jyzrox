/**
 * i18n abstraction layer — simple key-value dictionary.
 *
 * To add a new language:
 *   1. Create a new file (e.g. `ja.ts`) with `export default { ... }`
 *   2. Add it to `localeLoaders` below and to `initialDictionaries.ts`
 *   3. Add the locale key to `SUPPORTED_LOCALES` in `locales.ts`
 *   4. Add `common.locale.ja` key to all locale files
 *
 * Usage:
 *   import { t } from '@/lib/i18n'
 *   <span>{t('nav.dashboard')}</span>
 */

import { use } from 'react'
import { initialDictionaries } from './initialDictionaries'
import { DEFAULT_LOCALE, resolveLocale, type Locale } from './locales'
import { SsrLocaleContext } from './ssrLocale'

export {
  DEFAULT_LOCALE,
  LOCALE_COOKIE,
  parseLocale,
  resolveLocale,
  SUPPORTED_LOCALES,
  type Locale,
} from './locales'

type Dictionary = Record<string, string>

const locales: Partial<Record<Locale, Dictionary>> = { ...initialDictionaries }

const localeLoaders: Record<Locale, () => Promise<{ default: Dictionary }>> = {
  en: () => import('./en'),
  'zh-TW': () => import('./zh-TW'),
  'zh-CN': () => import('./zh-CN'),
  ja: () => import('./ja'),
  ko: () => import('./ko'),
}

const pendingLocales = new Map<Locale, Promise<void>>()

let currentLocale: Locale = DEFAULT_LOCALE
let initialLocaleActive = false
let initialLocalePreparing: Promise<void> | null = null

/**
 * Concurrent server renders share this module, so the server takes the locale
 * from the render's context rather than module state. t() acts as a hook there;
 * `use` throws when no render is in progress, which leaves the default locale.
 */
function activeLocale(): Locale {
  if (typeof window === 'undefined') {
    try {
      // eslint-disable-next-line react-hooks/rules-of-hooks
      return use(SsrLocaleContext) ?? currentLocale
    } catch {
      return currentLocale
    }
  }
  return currentLocale
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
  return activeLocale()
}

/**
 * Make the server's locale active before the first client render, so hydration
 * matches the server HTML. Returns a promise to suspend on while the dictionary
 * loads, or null when it was active at once. A failed load falls back to English, and
 * React then replaces the mismatched HTML.
 */
export function prepareInitialLocale(locale: Locale): Promise<void> | null {
  if (typeof window === 'undefined') return null
  // A render that suspended must call use() again when it resumes, so a promise
  // handed out once keeps being returned; it is already settled by then.
  if (initialLocalePreparing) return initialLocalePreparing
  if (initialLocaleActive) return null
  if (locales[locale]) {
    currentLocale = locale
    initialLocaleActive = true
    return null
  }
  initialLocalePreparing = loadLocale(locale)
    .catch(() => loadLocale('en'))
    .catch(() => {})
    .then(() => {
      setLocale('en')
      setLocale(locale)
    })
  return initialLocalePreparing
}

export function t(key: string, params?: Record<string, string | number>): string {
  const locale = activeLocale()
  let value = locales[locale]?.[key] ?? locales.en?.[key] ?? key

  // Plural support: "singular|plural" format
  if (params && 'count' in params && value.includes('|')) {
    const forms = value.split('|')
    const count = Number(params.count)
    // CJK languages have no plural distinction — use first form
    if (locale === 'zh-TW' || locale === 'zh-CN' || locale === 'ja' || locale === 'ko') {
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
    const intlLocale = LOCALE_TO_INTL[activeLocale()] || 'en-US'
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
  const intlLocale = LOCALE_TO_INTL[activeLocale()] || 'en-US'
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
