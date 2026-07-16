import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  FONT_SCALE_KEY,
  GRID_COLUMNS_KEY,
  GRID_DENSITY_KEY,
  applyUiPreferences,
  collectLocalUiPreferences,
  loadLocalDisplayPreferences,
  saveLocalDisplayPreferences,
} from '@/lib/uiPreferences'
import { ACCENT_KEY, CUSTOM_STYLE_ID, CUSTOM_THEME_KEY } from '@/lib/themeOverrides'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('style')
  document.getElementById(CUSTOM_STYLE_ID)?.remove()
})

describe('UI preference migration', () => {
  it('collects existing device-only appearance and navigation values', () => {
    localStorage.setItem('theme', 'amoled')
    localStorage.setItem(ACCENT_KEY, '#112233')
    localStorage.setItem('bottom_tab_config', JSON.stringify(['/e-hentai', '/pixiv', '/library', '/queue']))
    localStorage.setItem(GRID_DENSITY_KEY, 'compact')
    localStorage.setItem(GRID_COLUMNS_KEY, '9')
    localStorage.setItem(FONT_SCALE_KEY, '1.125')

    expect(collectLocalUiPreferences()).toMatchObject({
      theme: 'amoled',
      accent: '#112233',
      bottom_tabs: ['/e-hentai', '/pixiv', '/library', '/queue'],
      gallery_grid_density: 'compact',
      gallery_grid_columns: 9,
      font_scale: 1.125,
    })
  })

  it('applies the server document authoritatively and clears stale managed values', () => {
    localStorage.setItem(ACCENT_KEY, '#ff0000')
    localStorage.setItem(CUSTOM_THEME_KEY, JSON.stringify({ bg: '#000000', card: '#111111', text: '#ffffff' }))
    localStorage.setItem('sidebar_nav_order', JSON.stringify({ order: ['/old'], hidden: [] }))
    const setTheme = vi.fn()

    applyUiPreferences({ theme: 'light', font_scale: 1.25 }, setTheme)

    expect(setTheme).toHaveBeenCalledWith('light')
    expect(localStorage.getItem(ACCENT_KEY)).toBeNull()
    expect(localStorage.getItem(CUSTOM_THEME_KEY)).toBeNull()
    expect(localStorage.getItem('sidebar_nav_order')).toBeNull()
    expect(document.documentElement.style.fontSize).toBe('125%')
  })
})

describe('display preferences', () => {
  it('updates local values immediately for same-device feedback', () => {
    saveLocalDisplayPreferences({
      gallery_grid_density: 'spacious',
      gallery_grid_columns: 7,
      font_scale: 0.875,
    })
    expect(loadLocalDisplayPreferences()).toEqual({
      gallery_grid_density: 'spacious',
      gallery_grid_columns: 7,
      font_scale: 0.875,
    })
    expect(document.documentElement.style.fontSize).toBe('87.5%')
  })
})
