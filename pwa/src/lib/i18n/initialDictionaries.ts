import type { Locale } from './locales'

type Dictionary = Record<string, string>

/* eslint-disable @typescript-eslint/no-require-imports */
// The server renders any request's locale synchronously. `typeof window` is a
// compile-time constant in Next, so these requires are not in the browser build,
// which loads only the user's own dictionary through loadLocale().
export const initialDictionaries: Partial<Record<Locale, Dictionary>> =
  typeof window === 'undefined'
    ? {
        en: require('./en').default,
        'zh-TW': require('./zh-TW').default,
        'zh-CN': require('./zh-CN').default,
        ja: require('./ja').default,
        ko: require('./ko').default,
      }
    : {}
/* eslint-enable @typescript-eslint/no-require-imports */
