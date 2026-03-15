import useSWR from 'swr'
import { api } from '@/lib/api'
import { useLocale } from '@/components/LocaleProvider'
import type { Locale } from '@/lib/i18n'

const LOCALE_TO_LANG: Record<Locale, string> = {
  'zh-TW': 'zh',
  'zh-CN': 'zh',
  'ja': 'ja',
  'ko': 'ko',
  'en': 'zh',
}

/**
 * Fetches translations for a list of tags in the current locale's language.
 * Tags should be in "namespace:name" format.
 * Returns a Record<string, string> mapping tag → translation.
 */
export function useTagTranslations(tags: string[]) {
  const { locale } = useLocale()
  const language = LOCALE_TO_LANG[locale] ?? 'zh'
  const key = tags.length > 0 ? ['tags/translations', language, tags.slice().sort().join(',')] : null
  return useSWR(key, () => api.tags.getTranslations(tags, language), {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    dedupingInterval: 86400_000, // 24h
  })
}
