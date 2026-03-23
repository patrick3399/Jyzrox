/**
 * useNavigation — Vitest test suite
 *
 * Covers:
 *   visibleLinks — only includes pages the user's role can access
 *   visibleLinks — admin sees all pages, viewer sees fewer
 *   groupedLinks — groups pages by section (Browse, Manage, Admin)
 *   groupedLinks — filters out empty groups
 *   cycleTheme   — cycles through light → dark → amoled → system → light
 *   themeLabel   — returns localized theme name via t()
 *
 * Note: @/lib/pageRegistry is NOT mocked — the real registry is used for
 * filtering tests so role-based assertions reflect actual page definitions.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { act } from '@testing-library/react'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockSetTheme, mockLogout, mockLoadSidebarConfig } = vi.hoisted(() => ({
  mockSetTheme: vi.fn(),
  mockLogout: vi.fn(),
  mockLoadSidebarConfig: vi.fn(),
}))

// ── Module mocks ──────────────────────────────────────────────────────

vi.mock('next-themes', () => ({
  useTheme: vi.fn(() => ({ theme: 'light', setTheme: mockSetTheme })),
}))

vi.mock('@/hooks/useAuth', () => ({
  useAuth: vi.fn(() => ({ logout: mockLogout })),
}))

vi.mock('@/hooks/useProfile', () => ({
  useProfile: vi.fn(() => ({ data: { role: 'admin' } })),
}))

vi.mock('@/lib/i18n', () => ({
  t: vi.fn((key: string) => key),
}))

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: vi.fn(() => () => {}),
}))

vi.mock('@/components/SidebarConfig', () => ({
  loadSidebarConfig: mockLoadSidebarConfig,
  SIDEBAR_CONFIG_KEY: 'test-key',
}))

// ── Import after mocks ────────────────────────────────────────────────

import { useNavigation } from '@/hooks/useNavigation'
import { PAGE_REGISTRY } from '@/lib/pageRegistry'
import { useTheme } from 'next-themes'
import { useProfile } from '@/hooks/useProfile'

// ── Helpers ───────────────────────────────────────────────────────────

/** Returns all PAGE_REGISTRY hrefs that appear in sidebar. */
function allSidebarHrefs(): string[] {
  return PAGE_REGISTRY.filter((p) => p.sidebar).map((p) => p.href)
}

/** Returns hrefs that require at least 'member' role. */
function memberPlusHrefs(): string[] {
  return PAGE_REGISTRY.filter(
    (p) => p.sidebar && (p.minRole === 'member' || p.minRole === 'admin'),
  ).map((p) => p.href)
}

/** Returns hrefs that require 'admin' role. */
function adminOnlyHrefs(): string[] {
  return PAGE_REGISTRY.filter((p) => p.sidebar && p.minRole === 'admin').map((p) => p.href)
}

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  // Default: loadSidebarConfig returns all sidebar hrefs in default order
  mockLoadSidebarConfig.mockReturnValue({ order: allSidebarHrefs(), hidden: [] })
  // Default: theme is 'light'
  vi.mocked(useTheme).mockReturnValue({
    theme: 'light',
    setTheme: mockSetTheme,
  } as unknown as ReturnType<typeof useTheme>)
  // Default: profile is admin
  vi.mocked(useProfile).mockReturnValue({
    data: { role: 'admin' },
  } as ReturnType<typeof useProfile>)
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('useNavigation — visibleLinks', () => {
  it('test_visibleLinks_adminRole_includesAllSidebarPages', () => {
    vi.mocked(useProfile).mockReturnValue({
      data: { role: 'admin' },
    } as ReturnType<typeof useProfile>)

    const { result } = renderHook(() => useNavigation())

    const visibleHrefs = result.current.visibleLinks.map((p) => p.href)
    // Admin should see all sidebar pages
    for (const href of allSidebarHrefs()) {
      expect(visibleHrefs).toContain(href)
    }
  })

  it('test_visibleLinks_viewerRole_excludesMemberAndAdminPages', () => {
    vi.mocked(useProfile).mockReturnValue({
      data: { role: 'viewer' },
    } as ReturnType<typeof useProfile>)

    const { result } = renderHook(() => useNavigation())

    const visibleHrefs = result.current.visibleLinks.map((p) => p.href)
    // Viewer must not see member or admin pages
    for (const href of memberPlusHrefs()) {
      expect(visibleHrefs).not.toContain(href)
    }
  })

  it('test_visibleLinks_memberRole_includesMemberPagesButNotAdminPages', () => {
    vi.mocked(useProfile).mockReturnValue({
      data: { role: 'member' },
    } as ReturnType<typeof useProfile>)

    const { result } = renderHook(() => useNavigation())

    const visibleHrefs = result.current.visibleLinks.map((p) => p.href)
    // Member can see member pages
    for (const href of PAGE_REGISTRY.filter((p) => p.sidebar && p.minRole === 'member').map(
      (p) => p.href,
    )) {
      expect(visibleHrefs).toContain(href)
    }
    // Member cannot see admin-only pages
    for (const href of adminOnlyHrefs()) {
      expect(visibleHrefs).not.toContain(href)
    }
  })

  it('test_visibleLinks_sidebarConfigOrder_respectsCustomOrder', () => {
    const customOrder = ['/library', '/e-hentai']
    mockLoadSidebarConfig.mockReturnValue({ order: customOrder, hidden: [] })

    const { result } = renderHook(() => useNavigation())

    const visibleHrefs = result.current.visibleLinks.map((p) => p.href)
    expect(visibleHrefs).toEqual(['/library', '/e-hentai'])
  })

  it('test_visibleLinks_unknownHrefInOrder_isFiltered', () => {
    mockLoadSidebarConfig.mockReturnValue({
      order: ['/library', '/does-not-exist', '/e-hentai'],
      hidden: [],
    })

    const { result } = renderHook(() => useNavigation())

    const visibleHrefs = result.current.visibleLinks.map((p) => p.href)
    expect(visibleHrefs).not.toContain('/does-not-exist')
    expect(visibleHrefs).toContain('/library')
    expect(visibleHrefs).toContain('/e-hentai')
  })
})

describe('useNavigation — groupedLinks', () => {
  it('test_groupedLinks_adminRole_containsBrowseManageAdminSections', () => {
    vi.mocked(useProfile).mockReturnValue({
      data: { role: 'admin' },
    } as ReturnType<typeof useProfile>)

    const { result } = renderHook(() => useNavigation())

    const sectionKeys = result.current.groupedLinks.map((g) => g.labelKey)
    expect(sectionKeys).toContain('nav.sectionBrowse')
    expect(sectionKeys).toContain('nav.sectionManage')
    expect(sectionKeys).toContain('nav.sectionAdmin')
  })

  it('test_groupedLinks_viewerRole_containsOnlyBrowseSection', () => {
    vi.mocked(useProfile).mockReturnValue({
      data: { role: 'viewer' },
    } as ReturnType<typeof useProfile>)

    const { result } = renderHook(() => useNavigation())

    const sectionKeys = result.current.groupedLinks.map((g) => g.labelKey)
    expect(sectionKeys).toContain('nav.sectionBrowse')
    // Viewer has no member or admin pages, so those sections must be absent
    expect(sectionKeys).not.toContain('nav.sectionManage')
    expect(sectionKeys).not.toContain('nav.sectionAdmin')
  })

  it('test_groupedLinks_emptySections_areFiltered', () => {
    // Only supply viewer-level hrefs so Manage and Admin groups are empty
    const viewerHrefs = PAGE_REGISTRY.filter(
      (p) => p.sidebar && (!p.minRole || p.minRole === 'viewer'),
    ).map((p) => p.href)
    mockLoadSidebarConfig.mockReturnValue({ order: viewerHrefs, hidden: [] })

    vi.mocked(useProfile).mockReturnValue({
      data: { role: 'admin' },
    } as ReturnType<typeof useProfile>)

    const { result } = renderHook(() => useNavigation())

    // Every group returned must have at least one link
    for (const group of result.current.groupedLinks) {
      expect(group.links.length).toBeGreaterThan(0)
    }
    // Manage and Admin sections have no pages in the order → filtered out
    const sectionKeys = result.current.groupedLinks.map((g) => g.labelKey)
    expect(sectionKeys).not.toContain('nav.sectionManage')
    expect(sectionKeys).not.toContain('nav.sectionAdmin')
  })

  it('test_groupedLinks_eachGroup_containsCorrectMinRole', () => {
    vi.mocked(useProfile).mockReturnValue({
      data: { role: 'admin' },
    } as ReturnType<typeof useProfile>)

    const { result } = renderHook(() => useNavigation())

    for (const group of result.current.groupedLinks) {
      if (group.labelKey === 'nav.sectionManage') {
        for (const link of group.links) {
          expect(link.minRole).toBe('member')
        }
      }
      if (group.labelKey === 'nav.sectionAdmin') {
        for (const link of group.links) {
          expect(link.minRole).toBe('admin')
        }
      }
    }
  })
})

describe('useNavigation — cycleTheme', () => {
  it('test_cycleTheme_fromLight_setsThemeToDark', () => {
    vi.mocked(useTheme).mockReturnValue({ theme: 'light', setTheme: mockSetTheme } as unknown as ReturnType<typeof useTheme>)

    const { result } = renderHook(() => useNavigation())

    act(() => {
      result.current.cycleTheme()
    })

    expect(mockSetTheme).toHaveBeenCalledWith('dark')
  })

  it('test_cycleTheme_fromDark_setsThemeToAmoled', () => {
    vi.mocked(useTheme).mockReturnValue({ theme: 'dark', setTheme: mockSetTheme } as unknown as ReturnType<typeof useTheme>)

    const { result } = renderHook(() => useNavigation())

    act(() => {
      result.current.cycleTheme()
    })

    expect(mockSetTheme).toHaveBeenCalledWith('amoled')
  })

  it('test_cycleTheme_fromAmoled_setsThemeToSystem', () => {
    vi.mocked(useTheme).mockReturnValue({ theme: 'amoled', setTheme: mockSetTheme } as unknown as ReturnType<typeof useTheme>)

    const { result } = renderHook(() => useNavigation())

    act(() => {
      result.current.cycleTheme()
    })

    expect(mockSetTheme).toHaveBeenCalledWith('system')
  })

  it('test_cycleTheme_fromSystem_setsThemeToLight', () => {
    vi.mocked(useTheme).mockReturnValue({ theme: 'system', setTheme: mockSetTheme } as unknown as ReturnType<typeof useTheme>)

    const { result } = renderHook(() => useNavigation())

    act(() => {
      result.current.cycleTheme()
    })

    expect(mockSetTheme).toHaveBeenCalledWith('light')
  })

  it('test_cycleTheme_unknownTheme_wrapsToLight', () => {
    vi.mocked(useTheme).mockReturnValue({
      theme: 'unknown',
      setTheme: mockSetTheme,
    } as unknown as ReturnType<typeof useTheme>)

    const { result } = renderHook(() => useNavigation())

    act(() => {
      result.current.cycleTheme()
    })

    // indexOf returns -1 for unknown theme; (-1 + 1) % 4 = 0 → 'light'
    expect(mockSetTheme).toHaveBeenCalledWith('light')
  })
})

describe('useNavigation — themeLabel', () => {
  it('test_themeLabel_lightTheme_returnsCommonLightKey', () => {
    vi.mocked(useTheme).mockReturnValue({ theme: 'light', setTheme: mockSetTheme } as unknown as ReturnType<typeof useTheme>)

    const { result } = renderHook(() => useNavigation())

    expect(result.current.themeLabel).toBe('common.light')
  })

  it('test_themeLabel_darkTheme_returnsCommonDarkKey', () => {
    vi.mocked(useTheme).mockReturnValue({ theme: 'dark', setTheme: mockSetTheme } as unknown as ReturnType<typeof useTheme>)

    const { result } = renderHook(() => useNavigation())

    expect(result.current.themeLabel).toBe('common.dark')
  })

  it('test_themeLabel_amoledTheme_returnsCommonAmoledKey', () => {
    vi.mocked(useTheme).mockReturnValue({ theme: 'amoled', setTheme: mockSetTheme } as unknown as ReturnType<typeof useTheme>)

    const { result } = renderHook(() => useNavigation())

    expect(result.current.themeLabel).toBe('common.amoled')
  })

  it('test_themeLabel_systemTheme_returnsCommonSystemKey', () => {
    vi.mocked(useTheme).mockReturnValue({ theme: 'system', setTheme: mockSetTheme } as unknown as ReturnType<typeof useTheme>)

    const { result } = renderHook(() => useNavigation())

    expect(result.current.themeLabel).toBe('common.system')
  })

  it('test_themeLabel_undefinedTheme_fallsBackToSystemLabel', () => {
    vi.mocked(useTheme).mockReturnValue({
      theme: undefined,
      setTheme: mockSetTheme,
    } as unknown as ReturnType<typeof useTheme>)

    const { result } = renderHook(() => useNavigation())

    // undefined theme → themeKey becomes 'system' → returns 'common.system'
    expect(result.current.themeLabel).toBe('common.system')
  })
})
