/**
 * The browser bundle must not carry the English dictionary for everyone: a
 * non-English user downloads only their own locale.
 */

import { expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n/initialDictionaries', () => ({ initialDictionaries: {} }))
vi.mock('@/lib/i18n/en', () => {
  throw new Error('en dictionary imported')
})

import { getLocale, loadLocale, setLocale, t } from '@/lib/i18n'
import zhTW from '@/lib/i18n/zh-TW'

it('loads a non-English locale without importing the English dictionary', async () => {
  await loadLocale('zh-TW')
  setLocale('zh-TW')

  expect(getLocale()).toBe('zh-TW')
  expect(t('nav.dashboard')).toBe(zhTW['nav.dashboard'])
})

it('rejects a load of English when its chunk fails', async () => {
  await expect(loadLocale('en')).rejects.toThrow()
})
