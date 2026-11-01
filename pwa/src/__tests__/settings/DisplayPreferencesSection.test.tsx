import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const updateUiPreferences = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api', () => ({
  api: { auth: { updateUiPreferences } },
}))

import { DisplayPreferencesSection } from '@/components/settings/DisplayPreferencesSection'
import {
  loadLibraryDensityOverride,
  saveLibraryDensityOverride,
  GRID_DENSITY_OVERRIDE_KEY,
} from '@/lib/uiPreferences'

beforeEach(() => {
  localStorage.clear()
  updateUiPreferences.mockReset()
  updateUiPreferences.mockResolvedValue({ preferences: {} })
  saveLibraryDensityOverride('compact')
})

describe('DisplayPreferencesSection vs the Library density override', () => {
  it('test_choosing_a_settings_density_clears_the_library_override', () => {
    render(<DisplayPreferencesSection />)

    fireEvent.click(screen.getByRole('radio', { name: 'Spacious' }))

    expect(loadLibraryDensityOverride()).toBeNull()
  })

  it('test_choosing_settings_columns_clears_the_library_override', () => {
    render(<DisplayPreferencesSection />)

    fireEvent.change(screen.getByRole('combobox'), { target: { value: '6' } })

    expect(loadLibraryDensityOverride()).toBeNull()
  })

  it('test_changing_font_scale_keeps_the_library_override', () => {
    render(<DisplayPreferencesSection />)

    fireEvent.click(screen.getByRole('radio', { name: '125%' }))

    expect(loadLibraryDensityOverride()).toBe('compact')
  })

  it('test_override_is_never_sent_to_the_server', () => {
    render(<DisplayPreferencesSection />)

    fireEvent.click(screen.getByRole('radio', { name: 'Spacious' }))

    expect(updateUiPreferences).toHaveBeenCalledWith({ gallery_grid_density: 'spacious' })
    expect(JSON.stringify(updateUiPreferences.mock.calls)).not.toContain(GRID_DENSITY_OVERRIDE_KEY)
  })
})
