/**
 * i18n.test.ts — Vitest suite
 *
 * Tests the runtime logic of the i18n abstraction layer:
 *   - t() key lookup, parameter replacement, plural handling, fallback
 *   - setLocale / getLocale state management
 *   - formatDate, formatNumber, formatBytes utilities
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { t, setLocale, getLocale, formatDate, formatNumber, formatBytes } from '../../lib/i18n'

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
    // 'settingsCategory.general' exists in en.ts but not in ja.ts
    setLocale('ja')
    expect(t('settingsCategory.general')).toBe('General')
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

  it('test_formatBytes_exactly1024_returns1KB', () => {
    // 1024 bytes = 1 KB, maximumFractionDigits: 1, so "1 KB"
    expect(formatBytes(1024)).toBe('1 KB')
  })

  it('test_formatBytes_1536_returns1point5KB', () => {
    // 1536 / 1024 = 1.5 KB
    expect(formatBytes(1536)).toBe('1.5 KB')
  })

  it('test_formatBytes_1048576_returns1MB', () => {
    // 1048576 = 1024^2 = 1 MB
    expect(formatBytes(1048576)).toBe('1 MB')
  })
})
