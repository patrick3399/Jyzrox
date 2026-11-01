/**
 * Locale identifiers and resolution. Free of dictionaries and React so the root
 * layout (a Server Component) can resolve the request locale.
 */

export const SUPPORTED_LOCALES = ['en', 'zh-TW', 'zh-CN', 'ja', 'ko'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]
export const DEFAULT_LOCALE: Locale = 'en'

/** Mirrors the manual locale choice so the server can render in it. Not a security boundary. */
export const LOCALE_COOKIE = 'jyzrox_locale'

export function parseLocale(value: string | null | undefined): Locale | null {
  return SUPPORTED_LOCALES.includes(value as Locale) ? (value as Locale) : null
}

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
