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
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      value = value.replace(`{${k}}`, String(v))
    }
  }
  return value
}
