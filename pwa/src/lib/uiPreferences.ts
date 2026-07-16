import { mutate } from 'swr'
import { api } from '@/lib/api'
import {
  ACCENT_KEY,
  CUSTOM_STYLE_ID,
  CUSTOM_THEME_KEY,
  applyAccent,
  applyCustomPalette,
  isHexColor,
  type CustomPalette,
} from '@/lib/themeOverrides'

const BOTTOM_TAB_KEY = 'bottom_tab_config'
const SIDEBAR_KEY = 'sidebar_nav_order'
const DASHBOARD_LINKS_KEY = 'dashboard_quick_links'
export const GRID_DENSITY_KEY = 'library_grid_density'
export const GRID_COLUMNS_KEY = 'library_grid_columns'
export const FONT_SCALE_KEY = 'vault_font_scale'

export const UI_PREFERENCES_SWR_KEY = 'auth/ui-preferences'

export type ThemePreference = 'light' | 'dark' | 'amoled' | 'custom' | 'system'
export type GridDensityPreference = 'comfortable' | 'compact' | 'spacious'

export interface SidebarPreference {
  order: string[]
  hidden: string[]
}

export interface UiPreferences {
  theme?: ThemePreference
  accent?: string
  custom_palette?: CustomPalette
  bottom_tabs?: string[]
  sidebar?: SidebarPreference
  dashboard_links?: string[]
  gallery_grid_density?: GridDensityPreference
  gallery_grid_columns?: number
  font_scale?: number
}

export type UiPreferencesPatch = {
  [K in keyof UiPreferences]?: UiPreferences[K] | null
}

function readJson<T>(key: string): T | undefined {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : undefined
  } catch {
    return undefined
  }
}

function writeStorage(key: string, value: unknown | undefined) {
  const serialized = value === undefined ? null : JSON.stringify(value)
  if (serialized === null) localStorage.removeItem(key)
  else localStorage.setItem(key, serialized)
  window.dispatchEvent(new StorageEvent('storage', { key, newValue: serialized }))
}

/** Capture existing device-only values for the one-time server migration. */
export function collectLocalUiPreferences(): UiPreferences {
  const preferences: UiPreferences = {}
  const theme = localStorage.getItem('theme')
  if (theme && ['light', 'dark', 'amoled', 'custom', 'system'].includes(theme)) {
    preferences.theme = theme as ThemePreference
  }
  const accent = localStorage.getItem(ACCENT_KEY)
  if (isHexColor(accent)) preferences.accent = accent
  const palette = readJson<CustomPalette>(CUSTOM_THEME_KEY)
  if (palette && isHexColor(palette.bg) && isHexColor(palette.card) && isHexColor(palette.text)) {
    preferences.custom_palette = palette
  }
  const bottomTabs = readJson<string[]>(BOTTOM_TAB_KEY)
  if (Array.isArray(bottomTabs) && bottomTabs.length === 4) preferences.bottom_tabs = bottomTabs
  const sidebar = readJson<SidebarPreference>(SIDEBAR_KEY)
  if (sidebar && Array.isArray(sidebar.order) && Array.isArray(sidebar.hidden)) {
    preferences.sidebar = sidebar
  }
  const dashboardLinks = readJson<string[]>(DASHBOARD_LINKS_KEY)
  if (Array.isArray(dashboardLinks) && dashboardLinks.length > 0) {
    preferences.dashboard_links = dashboardLinks
  }
  const density = localStorage.getItem(GRID_DENSITY_KEY)
  if (density && ['comfortable', 'compact', 'spacious'].includes(density)) {
    preferences.gallery_grid_density = density as GridDensityPreference
  }
  const columnsRaw = localStorage.getItem(GRID_COLUMNS_KEY)
  const columns = Number(columnsRaw)
  if (columnsRaw !== null && Number.isInteger(columns) && columns >= 0 && columns <= 12) {
    preferences.gallery_grid_columns = columns
  }
  const fontScaleRaw = localStorage.getItem(FONT_SCALE_KEY)
  const fontScale = Number(fontScaleRaw)
  if (fontScaleRaw !== null && Number.isFinite(fontScale) && fontScale >= 0.8 && fontScale <= 1.3) {
    preferences.font_scale = fontScale
  }
  return preferences
}

/** Apply the server document as the authoritative state for all managed keys. */
export function applyUiPreferences(
  preferences: UiPreferences,
  setTheme: (theme: ThemePreference) => void,
) {
  setTheme(preferences.theme ?? 'dark')
  applyAccent(preferences.accent ?? null)
  if (preferences.accent) localStorage.setItem(ACCENT_KEY, preferences.accent)
  else localStorage.removeItem(ACCENT_KEY)

  if (preferences.custom_palette) {
    localStorage.setItem(CUSTOM_THEME_KEY, JSON.stringify(preferences.custom_palette))
    applyCustomPalette(preferences.custom_palette)
  } else {
    localStorage.removeItem(CUSTOM_THEME_KEY)
    document.getElementById(CUSTOM_STYLE_ID)?.remove()
  }

  writeStorage(BOTTOM_TAB_KEY, preferences.bottom_tabs)
  writeStorage(SIDEBAR_KEY, preferences.sidebar)
  writeStorage(DASHBOARD_LINKS_KEY, preferences.dashboard_links)
  writeScalarStorage(GRID_DENSITY_KEY, preferences.gallery_grid_density)
  writeScalarStorage(GRID_COLUMNS_KEY, preferences.gallery_grid_columns)
  writeScalarStorage(FONT_SCALE_KEY, preferences.font_scale)
  applyFontScale(preferences.font_scale)
}

function writeScalarStorage(key: string, value: string | number | undefined) {
  const serialized = value === undefined ? null : String(value)
  if (serialized === null) localStorage.removeItem(key)
  else localStorage.setItem(key, serialized)
  window.dispatchEvent(new StorageEvent('storage', { key, newValue: serialized }))
}

export function applyFontScale(scale: number | undefined) {
  if (scale !== undefined && Number.isFinite(scale) && scale >= 0.8 && scale <= 1.3) {
    document.documentElement.style.fontSize = `${scale * 100}%`
  } else {
    document.documentElement.style.removeProperty('font-size')
  }
}

export function saveLocalDisplayPreferences(
  patch: Pick<UiPreferencesPatch, 'gallery_grid_density' | 'gallery_grid_columns' | 'font_scale'>,
) {
  if ('gallery_grid_density' in patch) {
    writeScalarStorage(GRID_DENSITY_KEY, patch.gallery_grid_density ?? undefined)
  }
  if ('gallery_grid_columns' in patch) {
    writeScalarStorage(GRID_COLUMNS_KEY, patch.gallery_grid_columns ?? undefined)
  }
  if ('font_scale' in patch) {
    writeScalarStorage(FONT_SCALE_KEY, patch.font_scale ?? undefined)
    applyFontScale(patch.font_scale ?? undefined)
  }
}

export function loadLocalDisplayPreferences() {
  const density = localStorage.getItem(GRID_DENSITY_KEY)
  const columns = Number(localStorage.getItem(GRID_COLUMNS_KEY))
  const fontScale = Number(localStorage.getItem(FONT_SCALE_KEY))
  return {
    gallery_grid_density: (['comfortable', 'compact', 'spacious'].includes(density ?? '')
      ? density
      : 'comfortable') as GridDensityPreference,
    gallery_grid_columns:
      Number.isInteger(columns) && columns >= 0 && columns <= 12 ? columns : 0,
    font_scale: Number.isFinite(fontScale) && fontScale >= 0.8 && fontScale <= 1.3 ? fontScale : 1,
  }
}

export async function persistUiPreferences(patch: UiPreferencesPatch): Promise<boolean> {
  try {
    const response = await api.auth.updateUiPreferences(patch)
    await mutate(UI_PREFERENCES_SWR_KEY, { preferences: response.preferences }, false)
    return true
  } catch {
    return false
  }
}
