/**
 * Admin > Sites — download settings editor (diff save, reset, defaults, re-sync).
 *
 * Real SWR hooks run against a mocked `api.adminSites`, so the page ->
 * hook -> api call path is exercised end to end.
 */
import type { ReactNode } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import type { SiteConfigItem } from '@/lib/types'

const m = vi.hoisted(() => ({
  list: vi.fn(),
  update: vi.fn(),
  reset: vi.fn(),
  resetAdaptive: vi.fn(),
}))

vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { role: 'admin' }, isLoading: false }),
}))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))
vi.mock('@/lib/api', () => ({
  api: {
    adminSites: {
      list: m.list,
      update: m.update,
      probe: vi.fn(),
      updateFieldMapping: vi.fn(),
      reset: m.reset,
      resetAdaptive: m.resetAdaptive,
    },
  },
}))
vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) =>
    params ? `${key}:${JSON.stringify(params)}` : key,
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}))

import AdminSitesPage from '@/app/admin/sites/page'

const baseDownload = {
  retries: 4,
  http_timeout: 30,
  sleep_request: null,
  sleep_download: null,
  concurrency: 2,
  inactivity_timeout: 300,
  spread_personas: false,
}

const site: SiteConfigItem = {
  source_id: 'twitter',
  name: 'Twitter',
  domain: 'x.com',
  category: 'social',
  download: baseDownload,
  defaults: baseDownload,
  overridden: [],
  adaptive: [],
  extractor_defaults: { sleep_request: null, sleep_download: null },
}

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{children}</SWRConfig>
  )
}

async function openEditor() {
  render(<AdminSitesPage />, { wrapper: Wrapper })
  fireEvent.click(await screen.findByRole('button', { name: 'admin.sites.edit' }))
  await screen.findByRole('dialog')
}

const RETRIES = /admin\.sites\.retries(?![A-Za-z])/
const SLEEP_REQUEST = /admin\.sites\.sleepRequest(?![A-Za-z])/
const SLEEP_DOWNLOAD = /admin\.sites\.sleepDownload(?![A-Za-z])/

beforeEach(() => {
  vi.clearAllMocks()
  m.list.mockResolvedValue([site])
  m.update.mockResolvedValue(site)
  m.reset.mockResolvedValue(site)
  m.resetAdaptive.mockResolvedValue(site)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('AdminSitesPage download editor', () => {
  it('save sends only changed download fields', async () => {
    await openEditor()
    fireEvent.change(screen.getByRole('spinbutton', { name: RETRIES }), { target: { value: '6' } })
    fireEvent.click(screen.getByRole('button', { name: 'admin.sites.save' }))

    await waitFor(() => expect(m.update).toHaveBeenCalledTimes(1))
    expect(m.update).toHaveBeenCalledWith('twitter', { download: { retries: 6 } })
  })

  it('clearing an overridden sleep field resets it instead of sending null', async () => {
    const overriddenSite: SiteConfigItem = {
      ...site,
      download: { ...baseDownload, sleep_request: [1, 5] },
      overridden: ['sleep_request'],
    }
    m.list.mockResolvedValue([overriddenSite])
    await openEditor()

    const input = screen.getByRole('textbox', { name: SLEEP_REQUEST })
    expect(input).toHaveValue('1-5')
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'admin.sites.save' }))

    await waitFor(() => expect(m.reset).toHaveBeenCalledWith('twitter', 'download.sleep_request'))
    expect(m.update).not.toHaveBeenCalled()
  })

  it('sleep_download accepts a range and is sent as a [min, max] pair', async () => {
    await openEditor()
    fireEvent.change(screen.getByRole('textbox', { name: SLEEP_DOWNLOAD }), {
      target: { value: '1-3' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'admin.sites.save' }))

    await waitFor(() =>
      expect(m.update).toHaveBeenCalledWith('twitter', { download: { sleep_download: [1, 3] } }),
    )
  })

  it('reset all posts field_path download', async () => {
    await openEditor()
    fireEvent.click(screen.getByRole('button', { name: 'admin.sites.resetToDefault' }))

    await waitFor(() => expect(m.reset).toHaveBeenCalledWith('twitter', 'download'))
  })

  it('overridden field shows a marker and a per-field reset that posts download.<key>', async () => {
    m.list.mockResolvedValue([
      {
        ...site,
        download: { ...baseDownload, retries: 9 },
        overridden: ['retries'],
        adaptive: ['concurrency'],
      },
    ])
    await openEditor()

    expect(screen.getAllByText('admin.sites.overridden')).toHaveLength(1)
    expect(screen.getAllByText('admin.sites.autoTuned')).toHaveLength(1)

    const buttons = screen.getAllByRole('button', { name: /admin\.sites\.resetField/ })
    expect(buttons).toHaveLength(1)
    fireEvent.click(buttons[0])

    await waitFor(() => expect(m.reset).toHaveBeenCalledWith('twitter', 'download.retries'))
  })

  it('form shows API response values after save', async () => {
    m.update.mockResolvedValue({ ...site, download: { ...baseDownload, retries: 7 } })
    await openEditor()

    const input = screen.getByRole('spinbutton', { name: RETRIES })
    fireEvent.change(input, { target: { value: '6' } })
    fireEvent.click(screen.getByRole('button', { name: 'admin.sites.save' }))

    await waitFor(() => expect(m.update).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByRole('spinbutton', { name: RETRIES })).toHaveValue(7))
  })

  it('form shows API response values after reset all', async () => {
    m.list.mockResolvedValue([
      { ...site, download: { ...baseDownload, retries: 9 }, overridden: ['retries'] },
    ])
    m.reset.mockResolvedValue(site)
    await openEditor()
    expect(screen.getByRole('spinbutton', { name: RETRIES })).toHaveValue(9)

    fireEvent.click(screen.getByRole('button', { name: 'admin.sites.resetToDefault' }))

    await waitFor(() => expect(screen.getByRole('spinbutton', { name: RETRIES })).toHaveValue(4))
  })

  it('editor dialog is height-capped and pads the bottom safe-area so it clears the status bar and home indicator', async () => {
    await openEditor()

    // viewport-fit=cover: max-h-[90dvh] keeps the top from reaching the iOS status
    // bar; pb-(--sab) keeps the last buttons above the home indicator.
    const panel = screen.getByRole('dialog')
    expect(panel.className).toContain('max-h-[90dvh]')
    expect(panel.className).toContain('pb-(--sab)')
  })

  it('shows gallery-dl extractor default when sleep default is null', async () => {
    m.list.mockResolvedValue([
      { ...site, extractor_defaults: { sleep_request: [6, 12], sleep_download: null } },
    ])
    await openEditor()

    const extractor = screen.getAllByText(/admin\.sites\.defaultExtractor/)
    expect(extractor).toHaveLength(1)
    expect(extractor[0].textContent).toContain('\\"min\\":\\"6\\"')
    expect(extractor[0].textContent).toContain('\\"max\\":\\"12\\"')
    // sleep_download has neither a Jyzrox default nor an extractor default
    expect(screen.getAllByText(/admin\.sites\.defaultNone/)).toHaveLength(1)
  })
})
