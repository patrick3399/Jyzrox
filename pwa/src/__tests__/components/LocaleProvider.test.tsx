import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockDetectBrowserLocale, mockLoadLocale, mockSetI18nLocale, mockUseProfile } = vi.hoisted(
  () => ({
    mockDetectBrowserLocale: vi.fn(() => 'en'),
    mockLoadLocale: vi.fn(() => Promise.resolve()),
    mockSetI18nLocale: vi.fn(),
    mockUseProfile: vi.fn(() => ({ data: undefined })),
  }),
)

vi.mock('@/lib/i18n', () => ({
  detectBrowserLocale: mockDetectBrowserLocale,
  loadLocale: mockLoadLocale,
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

import { LocaleProvider, useLocale } from '@/components/LocaleProvider'

function LocaleProbe() {
  const { locale, isAutomatic } = useLocale()
  return <div>{`${locale}:${isAutomatic ? 'automatic' : 'manual'}`}</div>
}

describe('LocaleProvider refresh initialization', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
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
})
