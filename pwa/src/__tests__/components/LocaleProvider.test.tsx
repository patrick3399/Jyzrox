import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { i18nState, mockDetectBrowserLocale, mockLoadLocale, mockSetI18nLocale, mockUseProfile } =
  vi.hoisted(() => {
    const i18nState = { current: 'en' }
    return {
      i18nState,
      mockDetectBrowserLocale: vi.fn(() => 'en'),
      mockLoadLocale: vi.fn(() => Promise.resolve()),
      mockSetI18nLocale: vi.fn((locale: string) => {
        i18nState.current = locale
      }),
      mockUseProfile: vi.fn<() => { data: { locale: string | null } | undefined }>(() => ({
        data: undefined,
      })),
    }
  })

vi.mock('@/lib/i18n', () => ({
  detectBrowserLocale: mockDetectBrowserLocale,
  getLocale: () => i18nState.current,
  loadLocale: mockLoadLocale,
  LOCALE_COOKIE: 'jyzrox_locale',
  prepareInitialLocale: () => null,
  setLocale: mockSetI18nLocale,
  SUPPORTED_LOCALES: ['en', 'zh-TW', 'zh-CN', 'ja', 'ko'],
}))

vi.mock('@/lib/api', () => ({
  api: {
    auth: {
      updateProfile: vi.fn(() => Promise.resolve()),
    },
  },
}))

vi.mock('@/hooks/useProfile', () => ({
  useProfile: mockUseProfile,
}))

import { act } from 'react'
import { LocaleProvider, useLocale } from '@/components/LocaleProvider'

function LocaleProbe() {
  const { locale, isAutomatic } = useLocale()
  return <div>{`${locale}:${isAutomatic ? 'automatic' : 'manual'}`}</div>
}

describe('LocaleProvider refresh initialization', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    document.cookie = 'jyzrox_locale=; Path=/; Max-Age=0'
    i18nState.current = 'en'
    mockDetectBrowserLocale.mockReturnValue('en')
    mockLoadLocale.mockResolvedValue(undefined)
    mockUseProfile.mockReturnValue({ data: undefined })
  })

  it('restores a saved manual locale when the server seed is English and profile is unavailable', async () => {
    localStorage.setItem('jyzrox-locale-override', 'zh-TW')

    render(
      <LocaleProvider initialLocale="en">
        <LocaleProbe />
      </LocaleProvider>,
    )

    await waitFor(() => {
      expect(screen.getByText('zh-TW:manual')).toBeInTheDocument()
    })
    expect(mockSetI18nLocale).toHaveBeenCalledWith('zh-TW')
  })

  it('uses browser detection in automatic mode after hydration', async () => {
    mockDetectBrowserLocale.mockReturnValue('ja')

    render(
      <LocaleProvider initialLocale="en">
        <LocaleProbe />
      </LocaleProvider>,
    )

    await waitFor(() => {
      expect(screen.getByText('ja:automatic')).toBeInTheDocument()
    })
  })

  it('does not bump dictionaryVersion when the seeded dictionary is already active', async () => {
    function VersionProbe() {
      return <div>{`version:${useLocale().dictionaryVersion}`}</div>
    }

    render(
      <LocaleProvider initialLocale="en">
        <VersionProbe />
      </LocaleProvider>,
    )
    await act(async () => {
      await Promise.resolve()
    })

    expect(screen.getByText('version:0')).toBeInTheDocument()
  })

  it('copies a saved manual locale to the cookie for the next server render', async () => {
    localStorage.setItem('jyzrox-locale-override', 'zh-TW')

    render(
      <LocaleProvider initialLocale="en">
        <LocaleProbe />
      </LocaleProvider>,
    )

    await waitFor(() => expect(document.cookie).toContain('jyzrox_locale=zh-TW'))
  })

  it('clears a stale locale cookie when the locale is automatic', async () => {
    document.cookie = 'jyzrox_locale=ja; Path=/'

    render(
      <LocaleProvider initialLocale="en">
        <LocaleProbe />
      </LocaleProvider>,
    )

    await waitFor(() => expect(document.cookie).not.toContain('jyzrox_locale'))
  })

  it('writes the profile locale to the cookie and clears it for an automatic profile', async () => {
    mockUseProfile.mockReturnValue({ data: { locale: 'ko' } })
    const { unmount } = render(
      <LocaleProvider initialLocale="en">
        <LocaleProbe />
      </LocaleProvider>,
    )
    await waitFor(() => expect(document.cookie).toContain('jyzrox_locale=ko'))
    unmount()

    mockUseProfile.mockReturnValue({ data: { locale: null } })
    render(
      <LocaleProvider initialLocale="en">
        <LocaleProbe />
      </LocaleProvider>,
    )
    await waitFor(() => expect(document.cookie).not.toContain('jyzrox_locale'))
  })

  it('keeps the active dictionary when switching fails and English is not loaded either', async () => {
    i18nState.current = 'zh-TW'
    mockLoadLocale.mockRejectedValue(new Error('chunk failed'))

    render(
      <LocaleProvider initialLocale="zh-TW">
        <LocaleProbe />
      </LocaleProvider>,
    )
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    expect(i18nState.current).toBe('zh-TW')
    expect(mockSetI18nLocale).not.toHaveBeenCalledWith('en')
  })
})
