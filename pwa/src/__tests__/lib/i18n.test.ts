/**
 * i18n.test.ts — Vitest suite
 *
 * Tests the runtime logic of the i18n abstraction layer:
 *   - t() key lookup, parameter replacement, plural handling, fallback
 *   - setLocale / getLocale state management
 *   - formatDate, formatNumber, formatBytes utilities
 */

import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import {
  t,
  setLocale,
  getLocale,
  formatDate,
  formatNumber,
  formatBytes,
  resolveLocale,
  loadLocale,
} from '../../lib/i18n'

// Stub out the ja dictionary so fallback behavior can be tested: real locale
// files have full key parity with en.ts (enforced by i18n-keys.test.ts), so no
// genuine key gap exists to exercise the en fallback path.
vi.mock('../../lib/i18n/ja', () => ({ default: {} }))

// F4 regression: a failed locale chunk import must not permanently poison the
// in-flight cache. `koLoad.fail` flips to simulate a transient chunk-load error
// followed by a successful retry.
const koLoad = vi.hoisted(() => ({ fail: true }))
vi.mock('../../lib/i18n/ko', () => {
  if (koLoad.fail) throw new Error('simulated chunk load failure')
  return { default: { 'test.f4RetryKey': 'ko-loaded' } }
})

beforeAll(async () => {
  await Promise.all([loadLocale('zh-TW'), loadLocale('ja')])
})

// ---------------------------------------------------------------------------
// Reset locale before each test to prevent cross-test pollution
// ---------------------------------------------------------------------------
beforeEach(() => {
  setLocale('en')
})

// ---------------------------------------------------------------------------
// t() — key lookup
// ---------------------------------------------------------------------------

describe('t() key lookup', () => {
  it('test_t_knownKey_returnsEnglishValue', () => {
    expect(t('nav.dashboard')).toBe('Dashboard')
  })

  it('test_t_unknownKey_returnsKeyItself', () => {
    expect(t('this.key.does.not.exist')).toBe('this.key.does.not.exist')
  })

  it('test_t_keyMissingFromCurrentLocale_fallsBackToEnglish', () => {
    // ja is mocked as an empty dictionary above, so every key misses ja
    setLocale('ja')
    expect(t('settingsCategory.general')).toBe('General')
  })
})

// ---------------------------------------------------------------------------
// loadLocale() — failure recovery (F4 regression)
// ---------------------------------------------------------------------------

describe('loadLocale() failure recovery', () => {
  it('test_loadLocale_afterFailedChunkImport_allowsSuccessfulRetry', async () => {
    // First attempt fails (transient chunk-load error).
    koLoad.fail = true
    await expect(loadLocale('ko')).rejects.toThrow()

    // Before the fix, the rejected promise stayed cached in pendingLocales, so
    // every later loadLocale('ko') returned that same rejection — retry was
    // impossible without a full reload. The finally-clear must allow re-import.
    koLoad.fail = false
    await expect(loadLocale('ko')).resolves.toBeUndefined()

    setLocale('ko')
    expect(t('test.f4RetryKey')).toBe('ko-loaded')
  })
})

// ---------------------------------------------------------------------------
// t() — parameter replacement
// ---------------------------------------------------------------------------

describe('t() parameter replacement', () => {
  it('test_t_singleParam_replacesPlaceholder', () => {
    // Use a key with {param} or construct via unknown key that returns itself.
    // 'browse.pageN' uses {page} placeholder — verify via direct key pattern.
    // Since we cannot guarantee a specific param key exists, use the key-as-fallback
    // path: an unknown key containing a placeholder returns itself, then replaces.
    expect(t('Hello {name}!', { name: 'World' })).toBe('Hello World!')
  })

  it('test_t_multipleParams_replacesAllPlaceholders', () => {
    expect(t('{a} and {b}', { a: 'foo', b: 'bar' })).toBe('foo and bar')
  })

  it('test_t_missingParam_leavesPlaceholderIntact', () => {
    expect(t('Hello {name}!', {})).toBe('Hello {name}!')
  })
})

// ---------------------------------------------------------------------------
// t() — plural handling
// Plural logic activates when the resolved value contains '|'.
// Keys not found in any locale fall back to the key string itself.
// Using unknown keys with embedded '|' tests the plural branch directly.
// ---------------------------------------------------------------------------

describe('t() plural handling', () => {
  it('test_t_pluralEnglish_count1_returnsSingularForm', () => {
    // Key not in any locale → value becomes the key itself ("cat|cats")
    expect(t('cat|cats', { count: 1 })).toBe('cat')
  })

  it('test_t_pluralEnglish_count2_returnsPluralForm', () => {
    expect(t('cat|cats', { count: 2 })).toBe('cats')
  })

  it('test_t_pluralEnglish_count0_returnsPluralForm', () => {
    // count=0 is not 1, so plural form is used
    expect(t('cat|cats', { count: 0 })).toBe('cats')
  })

  it('test_t_pluralCjkZhTW_alwaysReturnsFirstForm_anyCount', () => {
    setLocale('zh-TW')
    expect(t('貓|貓們', { count: 5 })).toBe('貓')
  })

  it('test_t_pluralCjkJa_alwaysReturnsFirstForm_anyCount', () => {
    setLocale('ja')
    expect(t('ねこ|ねこたち', { count: 99 })).toBe('ねこ')
  })

  it('test_t_nonPipeStringWithCountParam_doesParamReplacementOnly', () => {
    // No pipe in value → no plural splitting, count treated as a normal param
    expect(t('{count} item', { count: 7 })).toBe('7 item')
  })

  it('test_t_onlyOnePluralForm_fallsBackToFirstForm', () => {
    // split('|') on "onlyone" → ["onlyone"], forms[1] is undefined
    // The code does: forms[1] || forms[0] → falls back to forms[0]
    // But "onlyone" has no pipe, so the plural branch is never entered.
    // Test the code path: single form with no pipe → just returns value as-is.
    expect(t('onlyone', { count: 2 })).toBe('onlyone')
  })

  it('test_t_pluralWithOnlyOnePipeForm_fallsBackToFirstFormForPluralCount', () => {
    // Provide a value that has a pipe but only one meaningful form:
    // e.g., "sole|" → forms = ["sole", ""] → forms[1] is "" (falsy) → falls back to forms[0]
    expect(t('sole|', { count: 2 })).toBe('sole')
  })
})

// ---------------------------------------------------------------------------
// setLocale / getLocale
// ---------------------------------------------------------------------------

describe('setLocale / getLocale', () => {
  it('test_getLocale_defaultsToEn', () => {
    expect(getLocale()).toBe('en')
  })

  it('test_setLocale_changesLocaleReturnedByGetLocale', () => {
    setLocale('zh-TW')
    expect(getLocale()).toBe('zh-TW')
  })

  it('test_setLocale_invalidLocale_keepsCurrentLocale', () => {
    setLocale('en')
    // 'xx' is not a valid Locale type, cast to bypass TypeScript
    setLocale('xx' as Parameters<typeof setLocale>[0])
    expect(getLocale()).toBe('en')
  })
})

describe('resolveLocale', () => {
  it('maps traditional and simplified Chinese variants', () => {
    expect(resolveLocale('en-US;q=0.8,zh-Hant-HK;q=0.9')).toBe('zh-TW')
    expect(resolveLocale(['zh-Hans-SG', 'en-US'])).toBe('zh-CN')
  })

  it('uses the first supported browser preference and falls back to English', () => {
    expect(resolveLocale(['fr-FR', 'ja-JP', 'en-US'])).toBe('ja')
    expect(resolveLocale('fr-FR,de-DE')).toBe('en')
  })
})

// ---------------------------------------------------------------------------
// formatDate
// ---------------------------------------------------------------------------

describe('formatDate', () => {
  it('test_formatDate_dateObject_returnsNonEmptyString', () => {
    const result = formatDate(new Date('2024-06-15'))
    expect(typeof result).toBe('string')
    expect(result.length).toBeGreaterThan(0)
  })

  it('test_formatDate_isoDateString_returnsNonEmptyString', () => {
    const result = formatDate('2024-06-15T00:00:00Z')
    expect(typeof result).toBe('string')
    expect(result.length).toBeGreaterThan(0)
  })

  it('test_formatDate_invalidDateString_returnsEmptyString', () => {
    expect(formatDate('not-a-date')).toBe('')
  })

  it('test_formatDate_nanDate_returnsEmptyString', () => {
    expect(formatDate(new Date(NaN))).toBe('')
  })
})

// ---------------------------------------------------------------------------
// formatNumber
// ---------------------------------------------------------------------------

describe('formatNumber', () => {
  it('test_formatNumber_integer_returnsFormattedString', () => {
    // en-US formats 1000 as "1,000"
    const result = formatNumber(1000)
    expect(typeof result).toBe('string')
    expect(result.length).toBeGreaterThan(0)
    expect(result).toContain('1')
  })

  it('test_formatNumber_withMaximumFractionDigits_limitsDecimals', () => {
    const result = formatNumber(3.14159, { maximumFractionDigits: 2 })
    // Should not produce more than 2 decimal places
    const decimalPart = result.split('.')[1] ?? ''
    expect(decimalPart.length).toBeLessThanOrEqual(2)
  })
})

// ---------------------------------------------------------------------------
// formatBytes
// ---------------------------------------------------------------------------

describe('formatBytes', () => {
  it('test_formatBytes_zero_returns0B', () => {
    expect(formatBytes(0)).toBe('0 B')
  })

  it('test_formatBytes_exactly1024_returns1KiB', () => {
    // 1024 bytes = 1 KiB, maximumFractionDigits: 1, so "1 KiB"
    expect(formatBytes(1024)).toBe('1 KiB')
  })

  it('test_formatBytes_1536_returns1point5KiB', () => {
    // 1536 / 1024 = 1.5 KiB
    expect(formatBytes(1536)).toBe('1.5 KiB')
  })

  it('test_formatBytes_1048576_returns1MiB', () => {
    // 1048576 = 1024^2 = 1 MiB
    expect(formatBytes(1048576)).toBe('1 MiB')
  })

  it('test_formatBytes_scalesBy1024_soUnitsAreBinaryNotSI', () => {
    // The divisor is 1024, so labelling these as KB/MB would overstate the
    // value by 2.4% per step. 1000 bytes stays below the first binary step.
    expect(formatBytes(1000)).toBe('1,000 B')
    expect(formatBytes(1_000_000)).toBe('976.6 KiB')
  })
})
