import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  GRID_DENSITY_OVERRIDE_KEY,
  applyUiPreferences,
  collectLocalUiPreferences,
  loadLibraryDensityOverride,
  saveLibraryDensityOverride,
} from '@/lib/uiPreferences'

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('library density override storage', () => {
  it('test_invalid_stored_override_value_loads_as_null', () => {
    for (const bad of ['huge', '', '4', 'COMPACT', '{"a":1}']) {
      localStorage.setItem(GRID_DENSITY_OVERRIDE_KEY, bad)
      expect(loadLibraryDensityOverride()).toBeNull()
    }
  })

  it('test_missing_override_loads_as_null', () => {
    expect(loadLibraryDensityOverride()).toBeNull()
  })

  it('test_valid_override_round_trips_and_null_removes_the_key', () => {
    saveLibraryDensityOverride('compact')
    expect(localStorage.getItem(GRID_DENSITY_OVERRIDE_KEY)).toBe('compact')
    expect(loadLibraryDensityOverride()).toBe('compact')

    saveLibraryDensityOverride(null)
    expect(localStorage.getItem(GRID_DENSITY_OVERRIDE_KEY)).toBeNull()
    expect(loadLibraryDensityOverride()).toBeNull()
  })

  it('test_save_dispatches_a_storage_event_for_same_tab_listeners', () => {
    const seen: Array<{ key: string | null; newValue: string | null }> = []
    const listener = (event: Event) => {
      const e = event as StorageEvent
      seen.push({ key: e.key, newValue: e.newValue })
    }
    window.addEventListener('storage', listener)
    saveLibraryDensityOverride('spacious')
    window.removeEventListener('storage', listener)

    expect(seen).toEqual([{ key: GRID_DENSITY_OVERRIDE_KEY, newValue: 'spacious' }])
  })

  it('test_unavailable_storage_does_not_throw_on_save_or_load', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota')
    })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })

    expect(() => saveLibraryDensityOverride('compact')).not.toThrow()
    expect(() => saveLibraryDensityOverride(null)).not.toThrow()
    expect(loadLibraryDensityOverride()).toBeNull()
  })

  it('test_applying_a_server_document_leaves_the_device_override_alone', () => {
    saveLibraryDensityOverride('compact')

    applyUiPreferences(
      { theme: 'dark', gallery_grid_density: 'spacious', gallery_grid_columns: 6 },
      vi.fn(),
    )
    expect(loadLibraryDensityOverride()).toBe('compact')

    // Even a document with no display values at all must not clear it.
    applyUiPreferences({ theme: 'dark' }, vi.fn())
    expect(loadLibraryDensityOverride()).toBe('compact')
  })

  it('test_override_is_never_collected_for_server_sync', () => {
    saveLibraryDensityOverride('compact')

    expect(JSON.stringify(collectLocalUiPreferences())).not.toContain('compact')
    expect(Object.keys(collectLocalUiPreferences())).not.toContain(GRID_DENSITY_OVERRIDE_KEY)
  })
})
