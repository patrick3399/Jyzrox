import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

// next/navigation and next/link are not relevant to loadTabConfig — mock to prevent
// module resolution errors when the module is imported in jsdom
vi.mock('next/link', () => ({ default: () => null }))
vi.mock('next/navigation', () => ({ usePathname: () => '/' }))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/hooks/useDownloadQueue', () => ({ useDownloadStats: () => ({ data: null }) }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))
vi.mock('lucide-react', () => {
  const stub = () => null
  return {
    Compass: stub,
    Palette: stub,
    BookOpen: stub,
    Download: stub,
    Menu: stub,
    LayoutDashboard: stub,
    Images: stub,
    FolderTree: stub,
    Rss: stub,
    Settings: stub,
  }
})

import {
  loadTabConfig,
  ALL_TABS,
  DEFAULT_TAB_HREFS,
  BOTTOM_TAB_CONFIG_KEY,
} from '@/components/BottomTabBar'

describe('loadTabConfig', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('test_loadTabConfig_empty_localStorage_returns_default_tabs', () => {
    const result = loadTabConfig()
    const expectedHrefs = DEFAULT_TAB_HREFS
    expect(result.map((t) => t.href)).toEqual(expectedHrefs)
  })

  it('test_loadTabConfig_malformed_json_returns_default_tabs', () => {
    localStorage.setItem(BOTTOM_TAB_CONFIG_KEY, '{not valid json}}}')
    const result = loadTabConfig()
    expect(result.map((t) => t.href)).toEqual(DEFAULT_TAB_HREFS)
  })

  it('test_loadTabConfig_wrong_array_length_returns_default_tabs', () => {
    // Only 3 items instead of the required 4
    localStorage.setItem(
      BOTTOM_TAB_CONFIG_KEY,
      JSON.stringify(['/e-hentai', '/pixiv', '/library']),
    )
    const result = loadTabConfig()
    expect(result.map((t) => t.href)).toEqual(DEFAULT_TAB_HREFS)
  })

  it('test_loadTabConfig_unknown_href_returns_default_tabs', () => {
    // One href not present in ALL_TABS
    localStorage.setItem(
      BOTTOM_TAB_CONFIG_KEY,
      JSON.stringify(['/e-hentai', '/pixiv', '/library', '/unknown-route']),
    )
    const result = loadTabConfig()
    expect(result.map((t) => t.href)).toEqual(DEFAULT_TAB_HREFS)
  })

  it('test_loadTabConfig_valid_hrefs_returns_correct_tab_definitions', () => {
    const hrefs = ['/settings', '/images', '/subscriptions', '/explorer']
    localStorage.setItem(BOTTOM_TAB_CONFIG_KEY, JSON.stringify(hrefs))
    const result = loadTabConfig()
    expect(result.map((t) => t.href)).toEqual(hrefs)
    // Each resolved TabDefinition should be the exact object from ALL_TABS
    for (const tab of result) {
      expect(ALL_TABS).toContain(tab)
    }
  })

  it('test_loadTabConfig_non_string_element_returns_default_tabs', () => {
    // Second element is a number, not a string
    localStorage.setItem(
      BOTTOM_TAB_CONFIG_KEY,
      JSON.stringify(['/e-hentai', 42, '/library', '/queue']),
    )
    const result = loadTabConfig()
    expect(result.map((t) => t.href)).toEqual(DEFAULT_TAB_HREFS)
  })
})
