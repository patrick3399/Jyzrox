import useSWR from 'swr'
import { api } from '@/lib/api'
import { useLocale } from '@/components/LocaleProvider'
import {
  getTagTranslationPreference,
  resolveTagTranslationLanguage,
  TAG_TRANSLATION_CHANGE_EVENT,
  type TagTranslationPreference,
} from '@/lib/tagTranslation'
import { useEffect, useState } from 'react'

/**
 * Fetches Chinese tag translations only for Chinese UI locales.
 *
 * The tag database is sourced in simplified Chinese and OpenCC derives zh-TW;
 * it is not a substitute for Japanese, Korean, or English tag translations.
 * Tags should be in "namespace:name" format.
 * Returns a Record<string, string> mapping tag → translation.
 * When tag_translation_enabled feature is disabled, returns undefined data without fetching.
 */
export function useTagTranslations(tags: string[]) {
  const { locale } = useLocale()
  const [preference, setPreference] = useState<TagTranslationPreference>(getTagTranslationPreference)
  const language = resolveTagTranslationLanguage(preference, locale)

  useEffect(() => {
    const refresh = () => setPreference(getTagTranslationPreference())
    window.addEventListener(TAG_TRANSLATION_CHANGE_EVENT, refresh)
    return () => window.removeEventListener(TAG_TRANSLATION_CHANGE_EVENT, refresh)
  }, [])

  // Read feature toggle from SWR cache (shared with settings page)
  const { data: features } = useSWR('settings/features', () => api.settings.getFeatures(), {
    revalidateOnFocus: false,
    dedupingInterval: 300_000, // 5 min
  })
  const enabled = features?.tag_translation_enabled ?? true

  const key =
    enabled && language && tags.length > 0
      ? ['tags/translations', language, tags.slice().sort().join(',')]
      : null

  return useSWR(key, () => api.tags.getTranslations(tags, language ?? 'zh'), {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    dedupingInterval: 86400_000, // 24h
  })
}
