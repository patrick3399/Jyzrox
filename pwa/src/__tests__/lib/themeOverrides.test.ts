import { describe, it, expect, beforeEach } from 'vitest'
import {
  ACCENT_KEY,
  CUSTOM_STYLE_ID,
  CUSTOM_THEME_KEY,
  DEFAULT_CUSTOM_PALETTE,
  applyAccent,
  applyCustomPalette,
  contrastRatio,
  customThemeCss,
  isHexColor,
  loadAccent,
  loadCustomPalette,
  saveAccent,
  saveCustomPalette,
} from '@/lib/themeOverrides'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.style.removeProperty('--color-accent')
  document.getElementById(CUSTOM_STYLE_ID)?.remove()
})

describe('themeOverrides — accent', () => {
  it('test_saveAccent_roundTrip_persistsAndApplies', () => {
    saveAccent('#ff0000')
    expect(localStorage.getItem(ACCENT_KEY)).toBe('#ff0000')
    expect(loadAccent()).toBe('#ff0000')
    expect(document.documentElement.style.getPropertyValue('--color-accent')).toBe('#ff0000')
  })

  it('test_saveAccent_null_removesKeyAndProperty', () => {
    saveAccent('#ff0000')
    saveAccent(null)
    expect(localStorage.getItem(ACCENT_KEY)).toBeNull()
    expect(document.documentElement.style.getPropertyValue('--color-accent')).toBe('')
  })

  it('test_loadAccent_invalidHexInStorage_returnsNull', () => {
    localStorage.setItem(ACCENT_KEY, 'red; } body { display: none')
    expect(loadAccent()).toBeNull()
  })

  it('test_applyAccent_rejectsNonHexValue', () => {
    applyAccent('url(javascript:1)')
    expect(document.documentElement.style.getPropertyValue('--color-accent')).toBe('')
  })
})

describe('themeOverrides — custom palette', () => {
  it('test_loadCustomPalette_missingKey_returnsDefaults', () => {
    expect(loadCustomPalette()).toEqual(DEFAULT_CUSTOM_PALETTE)
  })

  it('test_loadCustomPalette_corruptJson_returnsDefaults', () => {
    localStorage.setItem(CUSTOM_THEME_KEY, '{not json')
    expect(loadCustomPalette()).toEqual(DEFAULT_CUSTOM_PALETTE)
  })

  it('test_loadCustomPalette_invalidHexField_returnsDefaults', () => {
    localStorage.setItem(
      CUSTOM_THEME_KEY,
      JSON.stringify({ bg: '#000000', card: '#111111', text: 'evil' }),
    )
    expect(loadCustomPalette()).toEqual(DEFAULT_CUSTOM_PALETTE)
  })

  it('test_saveCustomPalette_roundTrip', () => {
    const p = { bg: '#101020', card: '#181828', text: '#f0f0ff' }
    saveCustomPalette(p)
    expect(loadCustomPalette()).toEqual(p)
  })

  it('test_customThemeCss_containsAllTenVariablesAndDerivations', () => {
    const css = customThemeCss({ bg: '#101020', card: '#181828', text: '#f0f0ff' })
    for (const v of [
      '--color-bg:#101020',
      '--color-card:#181828',
      '--color-text:#f0f0ff',
      '--color-input:#181828',
    ]) {
      expect(css).toContain(v)
    }
    for (const derived of [
      '--color-card-hover:color-mix',
      '--color-border:color-mix',
      '--color-border-hover:color-mix',
      '--color-text-secondary:color-mix',
      '--color-text-muted:color-mix',
    ]) {
      expect(css).toContain(derived)
    }
    expect(css.startsWith('.custom{')).toBe(true)
  })

  it('test_applyCustomPalette_updatesInPlace_noDuplicateStyleElements', () => {
    applyCustomPalette({ bg: '#101020', card: '#181828', text: '#f0f0ff' })
    applyCustomPalette({ bg: '#202030', card: '#282838', text: '#ffffff' })
    const els = document.querySelectorAll(`#${CUSTOM_STYLE_ID}`)
    expect(els.length).toBe(1)
    expect(els[0].textContent).toContain('--color-bg:#202030')
  })

  it('test_applyCustomPalette_invalidHex_doesNotInjectStyle', () => {
    applyCustomPalette({ bg: 'red', card: '#181828', text: '#f0f0ff' })
    expect(document.getElementById(CUSTOM_STYLE_ID)).toBeNull()
  })
})

describe('themeOverrides — contrastRatio', () => {
  it('test_contrastRatio_mutedOldLightValue_failsAA', () => {
    // The pre-fix light-theme muted color: ~2.5:1 on white — the bug we fixed.
    expect(contrastRatio('#a3a3a3', '#ffffff')).toBeLessThan(4.5)
  })

  it('test_contrastRatio_mutedNewLightValue_passesAA', () => {
    expect(contrastRatio('#767676', '#ffffff')).toBeGreaterThanOrEqual(4.5)
  })

  it('test_contrastRatio_blackOnWhite_is21', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 0)
  })

  it('test_contrastRatio_sameColor_is1', () => {
    expect(contrastRatio('#123456', '#123456')).toBeCloseTo(1, 5)
  })

  it('test_contrastRatio_isSymmetric', () => {
    expect(contrastRatio('#e5e5e5', '#0a0a0a')).toBeCloseTo(contrastRatio('#0a0a0a', '#e5e5e5'), 5)
  })

  it('test_isHexColor_rejectsShortHexAndNonString', () => {
    expect(isHexColor('#fff')).toBe(false)
    expect(isHexColor('ffffff')).toBe(false)
    expect(isHexColor(null)).toBe(false)
    expect(isHexColor('#a3a3a3')).toBe(true)
  })
})
