import { describe, expect, it } from 'vitest'
import { resolveTagTranslationLanguage } from '../../lib/tagTranslation'

describe('resolveTagTranslationLanguage', () => {
  it('enables automatic Chinese tag labels only for Chinese UI locales', () => {
    expect(resolveTagTranslationLanguage('auto', 'zh-TW')).toBe('zh-TW')
    expect(resolveTagTranslationLanguage('auto', 'zh-CN')).toBe('zh')
    expect(resolveTagTranslationLanguage('auto', 'en')).toBeNull()
    expect(resolveTagTranslationLanguage('auto', 'ja')).toBeNull()
    expect(resolveTagTranslationLanguage('auto', 'ko')).toBeNull()
  })

  it('honors an explicit tag language independently from the UI locale', () => {
    expect(resolveTagTranslationLanguage('zh-TW', 'en')).toBe('zh-TW')
    expect(resolveTagTranslationLanguage('zh', 'ja')).toBe('zh')
    expect(resolveTagTranslationLanguage('off', 'zh-TW')).toBeNull()
  })
})
