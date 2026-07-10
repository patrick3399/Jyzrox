import type { Locale } from '@/lib/i18n'

export type TagTranslationPreference = 'auto' | 'off' | 'zh' | 'zh-TW'

const STORAGE_KEY = 'jyzrox-tag-translation-language'
export const TAG_TRANSLATION_CHANGE_EVENT = 'jyzrox:tag-translation-change'

export function getTagTranslationPreference(): TagTranslationPreference {
  if (typeof window === 'undefined') return 'auto'
  const value = localStorage.getItem(STORAGE_KEY)
  return value === 'off' || value === 'zh' || value === 'zh-TW' ? value : 'auto'
}

export function setTagTranslationPreference(preference: TagTranslationPreference) {
  if (typeof window === 'undefined') return
  localStorage.setItem(STORAGE_KEY, preference)
  window.dispatchEvent(new Event(TAG_TRANSLATION_CHANGE_EVENT))
}

/** Automatic tag labels only exist for Chinese UI locales. */
export function resolveTagTranslationLanguage(
  preference: TagTranslationPreference,
  locale: Locale,
): 'zh' | 'zh-TW' | null {
  if (preference === 'off') return null
  if (preference === 'zh' || preference === 'zh-TW') return preference
  if (locale === 'zh-TW') return 'zh-TW'
  if (locale === 'zh-CN') return 'zh'
  return null
}
