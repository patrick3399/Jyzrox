/**
 * Credentials page — Vitest suite
 *
 * Regression coverage for the schema-driven credential flow rendering:
 * the page used to render flow bodies only behind hardcoded `isEh` / `isPixiv`
 * checks, so any other credential-providing plugin (Fanbox) rendered an empty
 * card body and its credential could never be entered.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CredentialFlow, PluginInfo } from '@/lib/types'

const mockSetGenericCookie = vi.fn(async (_source: string, _cookies: Record<string, string>) => ({
  status: 'ok',
  source: 'fanbox',
}))
const mockListPlugins = vi.fn()
const mockGetCredentials = vi.fn(async () => ({}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))

vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { role: 'admin' }, isLoading: false }),
}))

vi.mock('@/lib/api', () => ({
  api: {
    plugins: { list: () => mockListPlugins() },
    settings: {
      getCredentials: () => mockGetCredentials(),
      setGenericCookie: (source: string, cookies: Record<string, string>) =>
        mockSetGenericCookie(source, cookies),
      getEhSite: vi.fn(async () => ({ use_ex: false })),
      deleteCredential: vi.fn(async () => ({ status: 'ok' })),
    },
  },
}))

import CredentialsPage from '@/app/credentials/page'

const fanboxFlow: CredentialFlow = {
  flow_type: 'fields',
  fields: [
    {
      name: 'fanboxsessid',
      label: 'FANBOXSESSID Cookie',
      field_type: 'password',
      required: false,
      placeholder: 'Paste the FANBOXSESSID cookie value',
    },
  ],
  oauth_config: null,
  login_endpoint: null,
  verify_endpoint: null,
}

const fanboxPlugin: PluginInfo = {
  name: 'Pixiv Fanbox',
  source_id: 'fanbox',
  version: '1.0',
  url_patterns: [],
  credential_schema: [],
  credential_flows: [fanboxFlow],
  has_browse: false,
  has_process: false,
  browse_schema: null,
  credential_configured: false,
  enabled: true,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockListPlugins.mockResolvedValue({ plugins: [fanboxPlugin] })
  mockGetCredentials.mockResolvedValue({})
})

describe('CredentialsPage plugin flows', () => {
  it('renders the declared fields for a plugin that is neither EH nor Pixiv', async () => {
    render(<CredentialsPage />)

    const header = await screen.findByRole('button', { name: /Pixiv Fanbox/ })
    await userEvent.click(header)

    expect(
      await screen.findByPlaceholderText('Paste the FANBOXSESSID cookie value'),
    ).toBeInTheDocument()
    expect(screen.getByText('FANBOXSESSID Cookie')).toBeInTheDocument()
  })

  it('submits the entered field under the name the plugin declared', async () => {
    render(<CredentialsPage />)

    await userEvent.click(await screen.findByRole('button', { name: /Pixiv Fanbox/ }))
    const input = await screen.findByPlaceholderText('Paste the FANBOXSESSID cookie value')
    await userEvent.type(input, '  session-value  ')
    await userEvent.click(screen.getByRole('button', { name: 'credentials.save' }))

    await waitFor(() =>
      expect(mockSetGenericCookie).toHaveBeenCalledWith('fanbox', {
        fanboxsessid: 'session-value',
      }),
    )
  })

  it('keeps save disabled until a required field is filled', async () => {
    mockListPlugins.mockResolvedValue({
      plugins: [
        {
          ...fanboxPlugin,
          credential_flows: [
            { ...fanboxFlow, fields: [{ ...fanboxFlow.fields[0], required: true }] },
          ],
        },
      ],
    })
    render(<CredentialsPage />)

    await userEvent.click(await screen.findByRole('button', { name: /Pixiv Fanbox/ }))
    const save = await screen.findByRole('button', { name: 'credentials.save' })
    expect(save).toBeDisabled()

    await userEvent.type(
      screen.getByPlaceholderText('Paste the FANBOXSESSID cookie value'),
      'value',
    )
    expect(save).toBeEnabled()
    expect(mockSetGenericCookie).not.toHaveBeenCalled()
  })
})
