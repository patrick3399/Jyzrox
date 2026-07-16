import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, waitFor } from '@testing-library/react'

const mocks = vi.hoisted(() => ({
  response: undefined as { preferences: Record<string, unknown> } | undefined,
  setTheme: vi.fn(),
  updateUiPreferences: vi.fn(),
  mutate: vi.fn(),
}))

vi.mock('next-themes', () => ({ useTheme: () => ({ setTheme: mocks.setTheme }) }))
vi.mock('swr', () => ({
  default: () => ({ data: mocks.response }),
  mutate: mocks.mutate,
}))
vi.mock('@/lib/api', () => ({
  api: {
    auth: {
      getUiPreferences: vi.fn(),
      updateUiPreferences: mocks.updateUiPreferences,
    },
  },
}))

import { UiPreferencesSync } from '@/components/UiPreferencesSync'
import { ACCENT_KEY } from '@/lib/themeOverrides'

beforeEach(() => {
  mocks.response = undefined
  vi.clearAllMocks()
  localStorage.clear()
  document.documentElement.removeAttribute('style')
})

describe('UiPreferencesSync', () => {
  it('applies a non-empty server document as the authoritative device state', async () => {
    localStorage.setItem(ACCENT_KEY, '#ff0000')
    mocks.response = { preferences: { theme: 'amoled', font_scale: 1.125 } }

    render(<UiPreferencesSync />)

    await waitFor(() => expect(mocks.setTheme).toHaveBeenCalledWith('amoled'))
    expect(localStorage.getItem(ACCENT_KEY)).toBeNull()
    expect(document.documentElement.style.fontSize).toBe('112.5%')
  })

  it('migrates existing local preferences when the server document is empty', async () => {
    localStorage.setItem('theme', 'dark')
    localStorage.setItem(ACCENT_KEY, '#112233')
    mocks.response = { preferences: {} }
    mocks.updateUiPreferences.mockResolvedValue({
      status: 'ok',
      preferences: { theme: 'dark', accent: '#112233' },
    })

    render(<UiPreferencesSync />)

    await waitFor(() =>
      expect(mocks.updateUiPreferences).toHaveBeenCalledWith({ theme: 'dark', accent: '#112233' }),
    )
  })
})
