/**
 * BottomTabConfig — Vitest component test suite
 *
 * Covers:
 *   Renders all available tabs as buttons
 *   Default selection matches DEFAULT_TAB_HREFS (4 tabs selected)
 *   Selected tabs show position badge (1, 2, 3, 4)
 *   Unselected tabs are disabled when 4 already selected
 *   Clicking a selected tab deselects it
 *   Cannot deselect the last remaining tab
 *   Reset button restores defaults and calls localStorage.setItem
 *   localStorage.setItem is called with correct key when selection is valid
 *
 * Mock strategy:
 *   - @/lib/i18n → returns key as-is
 *   - @/components/LocaleProvider → useLocale is a no-op
 *   - @/components/BottomTabBar → spread real module, replace loadTabConfig only
 *
 * Notes on DOM structure:
 *   - Each tab's labelKey text appears TWICE: once in the order-preview chip at the
 *     top, and once in the main grid button. We always use getAllByText and pick the
 *     element that is a direct child of a <button> (the grid entry).
 *   - The counter paragraph "settings.bottomTabSelect (N/4)" is rendered as several
 *     adjacent text nodes so we match it with a regex on the parent element's
 *     textContent rather than screen.getByText.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ── Hoisted mock helpers ───────────────────────────────────────────────

const { mockLoadTabConfig } = vi.hoisted(() => ({
  mockLoadTabConfig: vi.fn(),
}))

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: () => ({}),
}))

// Partially mock BottomTabBar: keep all real exports but replace loadTabConfig
vi.mock('@/components/BottomTabBar', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/components/BottomTabBar')>()
  return {
    ...real,
    loadTabConfig: mockLoadTabConfig,
  }
})

// ── Import component after mocks ──────────────────────────────────────

import { BottomTabConfig } from '@/components/BottomTabConfig'
import {
  ALL_TABS,
  DEFAULT_TAB_HREFS,
  BOTTOM_TAB_CONFIG_KEY,
  TAB_COUNT,
} from '@/components/BottomTabBar'

// ── Helpers ───────────────────────────────────────────────────────────

function getDefaultTabDefs() {
  return DEFAULT_TAB_HREFS.map((href) => ALL_TABS.find((t) => t.href === href)!)
}

/**
 * Return the <button> element in the ALL_TABS grid for the given labelKey.
 * Because each labelKey text also appears in the order-preview chip, we find
 * all matching text nodes and pick the one whose closest <button> sits inside
 * the grid (identifiable by having a flex-1 truncate span as a sibling).
 */
function getGridButton(labelKey: string): HTMLElement {
  const spans = screen.getAllByText(labelKey)
  for (const span of spans) {
    const btn = span.closest('button')
    if (btn) return btn
  }
  throw new Error(`No grid button found for labelKey: ${labelKey}`)
}

/**
 * Check if the counter paragraph contains the expected count text.
 * The paragraph renders as "settings.bottomTabSelect (N/4)" with mixed
 * text nodes, so we match against the element's full textContent.
 */
function getCounterText(container: HTMLElement): string {
  // The counter <p> is the only paragraph that starts with 'settings.bottomTabSelect'
  const paras = container.querySelectorAll('p')
  for (const p of paras) {
    if (p.textContent?.includes('settings.bottomTabSelect')) {
      return p.textContent.replace(/\s+/g, ' ').trim()
    }
  }
  return ''
}

// ── Setup / Teardown ──────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  mockLoadTabConfig.mockReturnValue(getDefaultTabDefs())
})

afterEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('BottomTabConfig — tab grid renders', () => {
  it('test_bottomTabConfig_rendersAllAvailableTabs_asButtons', () => {
    render(<BottomTabConfig />)
    // Every tab in ALL_TABS must have a grid button entry
    for (const tab of ALL_TABS) {
      expect(getGridButton(tab.labelKey)).toBeInTheDocument()
    }
  })

  it('test_bottomTabConfig_rendersCorrectNumberOfTabButtons', () => {
    render(<BottomTabConfig />)
    // The grid renders ALL_TABS.length buttons; plus 1 reset button
    const allButtons = screen.getAllByRole('button')
    expect(allButtons.length).toBe(ALL_TABS.length + 1)
  })
})

describe('BottomTabConfig — default selection', () => {
  it('test_bottomTabConfig_defaultSelection_counterShowsFourOfFour', () => {
    const { container } = render(<BottomTabConfig />)
    const counter = getCounterText(container as HTMLElement)
    expect(counter).toContain(`(${TAB_COUNT}/${TAB_COUNT})`)
  })

  it('test_bottomTabConfig_defaultSelected_tabs_showPositionBadges', () => {
    render(<BottomTabConfig />)
    // Each selected tab button should contain a position badge span (1-indexed)
    DEFAULT_TAB_HREFS.forEach((href, idx) => {
      const tab = ALL_TABS.find((t) => t.href === href)!
      const btn = getGridButton(tab.labelKey)
      // The badge is a small rounded span containing the 1-based position number
      const badge = btn.querySelector('span.rounded-full')
      expect(badge).not.toBeNull()
      expect(badge!.textContent).toBe(String(idx + 1))
    })
  })

  it('test_bottomTabConfig_unselectedTabs_areDisabled_whenFourAlreadySelected', () => {
    render(<BottomTabConfig />)
    const unselectedTabs = ALL_TABS.filter((tab) => !DEFAULT_TAB_HREFS.includes(tab.href))
    for (const tab of unselectedTabs) {
      expect(getGridButton(tab.labelKey)).toBeDisabled()
    }
  })

  it('test_bottomTabConfig_selectedTabs_areNotDisabled', () => {
    render(<BottomTabConfig />)
    for (const href of DEFAULT_TAB_HREFS) {
      const tab = ALL_TABS.find((t) => t.href === href)!
      expect(getGridButton(tab.labelKey)).not.toBeDisabled()
    }
  })
})

describe('BottomTabConfig — toggle interaction', () => {
  it('test_bottomTabConfig_clickingSelectedTab_deselectsIt', async () => {
    const user = userEvent.setup()
    const { container } = render(<BottomTabConfig />)

    const firstDefaultTab = ALL_TABS.find((t) => t.href === DEFAULT_TAB_HREFS[0])!
    await user.click(getGridButton(firstDefaultTab.labelKey))

    // After deselecting one tab, count drops to 3
    expect(getCounterText(container as HTMLElement)).toContain(`(3/${TAB_COUNT})`)
  })

  it('test_bottomTabConfig_cannotDeselect_lastRemainingTab', async () => {
    const user = userEvent.setup()

    // Start with only 1 tab selected
    const singleTab = getDefaultTabDefs().slice(0, 1)
    mockLoadTabConfig.mockReturnValue(singleTab)
    const { container } = render(<BottomTabConfig />)

    await user.click(getGridButton(singleTab[0].labelKey))

    // Count stays at 1 because deselect is blocked
    expect(getCounterText(container as HTMLElement)).toContain(`(1/${TAB_COUNT})`)
  })

  it('test_bottomTabConfig_clickingUnselectedTab_whenBelowMax_selectsIt', async () => {
    const user = userEvent.setup()

    // Start with 3 tabs selected
    const threeTabs = getDefaultTabDefs().slice(0, 3)
    mockLoadTabConfig.mockReturnValue(threeTabs)
    const { container } = render(<BottomTabConfig />)

    const selectedHrefs = threeTabs.map((t) => t.href)
    const unselectedTab = ALL_TABS.find((t) => !selectedHrefs.includes(t.href))!
    const btn = getGridButton(unselectedTab.labelKey)
    expect(btn).not.toBeDisabled()

    await user.click(btn)

    expect(getCounterText(container as HTMLElement)).toContain(`(${TAB_COUNT}/${TAB_COUNT})`)
  })
})

describe('BottomTabConfig — reset button', () => {
  it('test_bottomTabConfig_resetButton_renders', () => {
    render(<BottomTabConfig />)
    expect(screen.getByText('settings.bottomTabReset')).toBeInTheDocument()
  })

  it('test_bottomTabConfig_resetButton_restoresDefaultSelection', async () => {
    const user = userEvent.setup()

    // Start with only 1 tab to make the reset observable
    mockLoadTabConfig.mockReturnValue(getDefaultTabDefs().slice(0, 1))
    const { container } = render(<BottomTabConfig />)

    expect(getCounterText(container as HTMLElement)).toContain(`(1/${TAB_COUNT})`)

    await user.click(screen.getByText('settings.bottomTabReset'))

    expect(getCounterText(container as HTMLElement)).toContain(`(${TAB_COUNT}/${TAB_COUNT})`)
  })

  it('test_bottomTabConfig_resetButton_callsLocalStorageSetItem_withCorrectKey', async () => {
    const user = userEvent.setup()
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')

    render(<BottomTabConfig />)
    await user.click(screen.getByText('settings.bottomTabReset'))

    expect(setItemSpy).toHaveBeenCalledWith(
      BOTTOM_TAB_CONFIG_KEY,
      JSON.stringify(DEFAULT_TAB_HREFS),
    )

    setItemSpy.mockRestore()
  })
})

describe('BottomTabConfig — localStorage persistence', () => {
  it('test_bottomTabConfig_selectingFourTabs_callsLocalStorageSetItem', async () => {
    const user = userEvent.setup()
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')

    // Start with 3 tabs so the next click reaches exactly 4
    const threeTabs = getDefaultTabDefs().slice(0, 3)
    mockLoadTabConfig.mockReturnValue(threeTabs)
    render(<BottomTabConfig />)

    const selectedHrefs = threeTabs.map((t) => t.href)
    const unselectedTab = ALL_TABS.find((t) => !selectedHrefs.includes(t.href))!
    await user.click(getGridButton(unselectedTab.labelKey))

    expect(setItemSpy).toHaveBeenCalledWith(BOTTOM_TAB_CONFIG_KEY, expect.any(String))

    setItemSpy.mockRestore()
  })

  it('test_bottomTabConfig_deselecting_belowFourTabs_doesNotCallLocalStorageSetItem', async () => {
    const user = userEvent.setup()

    render(<BottomTabConfig />)

    // Spy AFTER render so we only catch calls from the click interaction
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')

    // Deselect one tab — leaves 3 selected, which should NOT be persisted
    const firstDefaultTab = ALL_TABS.find((t) => t.href === DEFAULT_TAB_HREFS[0])!
    await user.click(getGridButton(firstDefaultTab.labelKey))

    expect(setItemSpy).not.toHaveBeenCalledWith(BOTTOM_TAB_CONFIG_KEY, expect.any(String))

    setItemSpy.mockRestore()
  })
})
