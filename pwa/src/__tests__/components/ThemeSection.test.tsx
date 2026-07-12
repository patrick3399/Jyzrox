import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const mockSetTheme = vi.fn()
let mockTheme = 'dark'

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: mockTheme, setTheme: mockSetTheme }),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

import { ThemeSection } from '@/components/settings/ThemeSection'
import { ACCENT_KEY, CUSTOM_STYLE_ID, CUSTOM_THEME_KEY } from '@/lib/themeOverrides'

beforeEach(() => {
  vi.clearAllMocks()
  mockTheme = 'dark'
  localStorage.clear()
  document.documentElement.style.removeProperty('--color-accent')
  document.getElementById(CUSTOM_STYLE_ID)?.remove()
})

describe('ThemeSection — theme choice', () => {
  it('test_rendersFiveThemeRadios', () => {
    render(<ThemeSection />)
    expect(screen.getAllByRole('radio')).toHaveLength(5)
  })

  it('test_clickLightRadio_callsSetThemeLight', () => {
    render(<ThemeSection />)
    fireEvent.click(screen.getByRole('radio', { name: /common\.light/ }))
    expect(mockSetTheme).toHaveBeenCalledWith('light')
  })

  it('test_currentTheme_isCheckedRadio', () => {
    render(<ThemeSection />)
    expect(screen.getByRole('radio', { name: /common\.dark/ })).toHaveAttribute(
      'aria-checked',
      'true',
    )
  })
})

describe('ThemeSection — accent', () => {
  it('test_clickAccentPreset_persistsAndAppliesProperty', () => {
    render(<ThemeSection />)
    fireEvent.click(screen.getByRole('button', { name: '#ef4444' }))
    expect(localStorage.getItem(ACCENT_KEY)).toBe('#ef4444')
    expect(document.documentElement.style.getPropertyValue('--color-accent')).toBe('#ef4444')
  })

  it('test_clickDefaultAccentPreset_clearsOverride', () => {
    localStorage.setItem(ACCENT_KEY, '#ef4444')
    render(<ThemeSection />)
    fireEvent.click(screen.getByRole('button', { name: '#6366f1' }))
    expect(localStorage.getItem(ACCENT_KEY)).toBeNull()
    expect(document.documentElement.style.getPropertyValue('--color-accent')).toBe('')
  })

  it('test_accentResetButton_onlyShownWithOverride_clearsIt', () => {
    localStorage.setItem(ACCENT_KEY, '#ef4444')
    render(<ThemeSection />)
    fireEvent.click(screen.getByRole('button', { name: /settings\.accentReset/ }))
    expect(localStorage.getItem(ACCENT_KEY)).toBeNull()
  })

  it('test_lowContrastAccent_showsWarning', () => {
    // amber #f59e0b: white-on-accent contrast < 3 → warning must render
    localStorage.setItem(ACCENT_KEY, '#f59e0b')
    render(<ThemeSection />)
    expect(screen.getByText('settings.contrastWarningAccent')).toBeTruthy()
  })

  it('test_defaultAccent_noWarning', () => {
    render(<ThemeSection />)
    expect(screen.queryByText('settings.contrastWarningAccent')).toBeNull()
  })
})

describe('ThemeSection — custom palette editor', () => {
  it('test_editorHidden_whenThemeNotCustom', () => {
    render(<ThemeSection />)
    expect(screen.queryByText('settings.customThemeColors')).toBeNull()
  })

  it('test_editorVisible_whenThemeCustom', () => {
    mockTheme = 'custom'
    render(<ThemeSection />)
    expect(screen.getByText('settings.customThemeColors')).toBeTruthy()
  })

  it('test_changeBgColor_persistsPaletteAndInjectsStyle', () => {
    mockTheme = 'custom'
    render(<ThemeSection />)
    fireEvent.change(screen.getByLabelText('settings.customThemeBg'), {
      target: { value: '#112233' },
    })
    expect(JSON.parse(localStorage.getItem(CUSTOM_THEME_KEY) ?? '{}').bg).toBe('#112233')
    expect(document.getElementById(CUSTOM_STYLE_ID)?.textContent).toContain('--color-bg:#112233')
  })

  it('test_lowContrastCustomPalette_showsTextWarning', () => {
    mockTheme = 'custom'
    localStorage.setItem(
      CUSTOM_THEME_KEY,
      JSON.stringify({ bg: '#ffffff', card: '#f5f5f5', text: '#cccccc' }),
    )
    render(<ThemeSection />)
    expect(screen.getByText('settings.contrastWarningText')).toBeTruthy()
  })

  it('test_resetPalette_restoresDefaults', () => {
    mockTheme = 'custom'
    localStorage.setItem(
      CUSTOM_THEME_KEY,
      JSON.stringify({ bg: '#112233', card: '#223344', text: '#ffffff' }),
    )
    render(<ThemeSection />)
    fireEvent.click(screen.getByRole('button', { name: /settings\.customThemeReset/ }))
    expect(JSON.parse(localStorage.getItem(CUSTOM_THEME_KEY) ?? '{}').bg).toBe('#0a0a0a')
  })
})
