/**
 * Admin > Sites — "spread across personas" switch (ADR 0022)
 *
 * Real SWR hooks (useSiteConfigs / useUpdateSiteConfig) run against a mocked
 * `api.adminSites`, so the save path is exercised end to end.
 */
import type { ReactNode } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'

const m = vi.hoisted(() => ({
  list: vi.fn(),
  update: vi.fn(),
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
      reset: vi.fn(),
      resetAdaptive: vi.fn(),
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

const twitterDownload = {
  retries: 4,
  http_timeout: 30,
  sleep_request: null,
  sleep_download: null,
  concurrency: 2,
  inactivity_timeout: 300,
  spread_personas: false,
}

const twitter = {
  source_id: 'twitter',
  name: 'Twitter',
  domain: 'x.com',
  category: 'social',
  download: twitterDownload,
  defaults: twitterDownload,
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

// The label may or may not wrap the hint text, so exclude the *Hint key.
const SWITCH_NAME = /admin\.sites\.spreadPersonas(?!Hint)/

beforeEach(() => {
  vi.clearAllMocks()
  m.list.mockResolvedValue([twitter])
  m.update.mockResolvedValue(twitter)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('AdminSitesPage spread personas switch', () => {
  it('test_sites_editor_spread_personas_checkbox_reflects_saved_value', async () => {
    m.list.mockResolvedValue([
      { ...twitter, download: { ...twitter.download, spread_personas: true } },
    ])
    await openEditor()
    expect(screen.getByRole('checkbox', { name: SWITCH_NAME })).toBeChecked()
  })

  it('test_sites_editor_toggle_spread_personas_and_save_sends_true', async () => {
    await openEditor()
    const box = screen.getByRole('checkbox', { name: SWITCH_NAME })
    expect(box).not.toBeChecked()

    fireEvent.click(box)
    fireEvent.click(screen.getByRole('button', { name: 'admin.sites.save' }))

    await waitFor(() =>
      expect(m.update).toHaveBeenCalledWith('twitter', {
        download: expect.objectContaining({ spread_personas: true }),
      }),
    )
  })

  it('test_sites_editor_save_without_changes_sends_no_request', async () => {
    await openEditor()
    fireEvent.click(screen.getByRole('button', { name: 'admin.sites.save' }))

    // Diff save: an untouched form must not write a snapshot of every field.
    await new Promise((r) => setTimeout(r, 20))
    expect(m.update).not.toHaveBeenCalled()
  })
})
