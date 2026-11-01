/**
 * Credentials page — saving under a named account.
 *
 * A typed account name must reach the API; an empty one must send no account
 * at all, because "no account" means "update the active account".
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CredentialAccount, CredentialFlow, PluginInfo } from '@/lib/types'

const mockSetGenericCookie = vi.fn(
  async (_source: string, _cookies: Record<string, string>, _account?: string) => ({
    status: 'ok',
    source: 'fanbox',
  }),
)
const mockSetSiteCredential = vi.fn(
  async (source: string, _data: Record<string, string | undefined>) => ({ status: 'ok', source }),
)
const mockSetPixivToken = vi.fn(async (_token: string, _account?: string) => ({
  status: 'ok',
  username: 'pixiv-user',
}))
const mockListPlugins = vi.fn()
const mockGetCredentials = vi.fn()
const mockListAccounts = vi.fn()

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
      setGenericCookie: (source: string, cookies: Record<string, string>, account?: string) =>
        mockSetGenericCookie(source, cookies, account),
      setSiteCredential: (source: string, data: Record<string, string | undefined>) =>
        mockSetSiteCredential(source, data),
      setPixivToken: (token: string, account?: string) => mockSetPixivToken(token, account),
      listCredentialAccounts: (source: string) => mockListAccounts(source),
      activateCredentialAccount: vi.fn(async () => ({ status: 'ok', account: 'alt' })),
      deleteCredentialAccount: vi.fn(async () => ({ status: 'ok' })),
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
  browse_schema: null,
  credential_configured: true,
  enabled: true,
}

const defaultOnly: CredentialAccount[] = [
  { account: 'default', credential_type: 'cookie', is_active: true },
]

beforeEach(() => {
  vi.clearAllMocks()
  mockListPlugins.mockResolvedValue({ plugins: [fanboxPlugin] })
  mockGetCredentials.mockResolvedValue({
    fanbox: { configured: true, account: 'default', accounts: 1 },
  })
  mockListAccounts.mockResolvedValue({ source: 'fanbox', accounts: defaultOnly })
})

async function openFanbox() {
  render(<CredentialsPage />)
  await userEvent.click(await screen.findByRole('button', { name: /Pixiv Fanbox/ }))
}

describe('CredentialsPage accounts', () => {
  it('saves under the typed account name instead of overwriting the active account', async () => {
    await openFanbox()

    await userEvent.type(await screen.findByLabelText('credentials.newAccountName'), 'alt')
    await userEvent.type(
      screen.getByPlaceholderText('Paste the FANBOXSESSID cookie value'),
      'session-value',
    )
    await userEvent.click(screen.getByRole('button', { name: 'credentials.save' }))

    await waitFor(() =>
      expect(mockSetGenericCookie).toHaveBeenCalledWith(
        'fanbox',
        { fanboxsessid: 'session-value' },
        'alt',
      ),
    )
  })

  it('sends no account when the name is left empty so the active account is updated', async () => {
    await openFanbox()

    await userEvent.type(
      await screen.findByPlaceholderText('Paste the FANBOXSESSID cookie value'),
      'session-value',
    )
    await userEvent.click(screen.getByRole('button', { name: 'credentials.save' }))

    await waitFor(() =>
      expect(mockSetGenericCookie).toHaveBeenCalledWith(
        'fanbox',
        { fanboxsessid: 'session-value' },
        undefined,
      ),
    )
  })

  it('keeps the section-level clear button while a source has a single account', async () => {
    await openFanbox()

    expect(
      await screen.findByRole('button', { name: 'credentials.clearCredential' }),
    ).toBeInTheDocument()
  })

  it('hides the section-level clear button when a source has several accounts', async () => {
    mockGetCredentials.mockResolvedValue({
      fanbox: { configured: true, account: 'default', accounts: 2 },
    })
    mockListAccounts.mockResolvedValue({
      source: 'fanbox',
      accounts: [...defaultOnly, { account: 'alt', credential_type: 'cookie', is_active: false }],
    })
    await openFanbox()

    await screen.findByText('alt')
    expect(
      screen.queryByRole('button', { name: 'credentials.clearCredential' }),
    ).not.toBeInTheDocument()
  })

  it('passes the account name when saving a site credential', async () => {
    mockGetCredentials.mockResolvedValue({})
    render(<CredentialsPage />)
    await userEvent.click(
      await screen.findByRole('button', { name: /credentials\.genericCookies/ }),
    )

    await userEvent.type(screen.getByPlaceholderText('credentials.siteNamePlaceholder'), 'twitter')
    await userEvent.type(screen.getByLabelText('credentials.newAccountName'), 'alt')
    await userEvent.type(
      screen.getByPlaceholderText('credentials.cookiesMultiFormat'),
      'auth_token=abc',
    )
    await userEvent.click(screen.getByRole('button', { name: 'credentials.save' }))

    await waitFor(() =>
      expect(mockSetSiteCredential).toHaveBeenCalledWith('twitter', {
        cookies: 'auth_token=abc',
        account: 'alt',
      }),
    )
  })

  it('hides the per-site clear button when that site has several accounts', async () => {
    mockGetCredentials.mockResolvedValue({
      twitter: { configured: true, account: 'default', accounts: 2 },
      weibo: { configured: true, account: 'default', accounts: 1 },
    })
    render(<CredentialsPage />)
    await userEvent.click(
      await screen.findByRole('button', { name: /credentials\.genericCookies/ }),
    )

    expect(
      await screen.findByRole('button', { name: 'credentials.clearConfirm weibo' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'credentials.clearConfirm twitter' }),
    ).not.toBeInTheDocument()
  })

  it('saves a Pixiv token under the typed account without showing it as the current account', async () => {
    const pixivPlugin: PluginInfo = {
      ...fanboxPlugin,
      name: 'Pixiv',
      source_id: 'pixiv',
      credential_flows: [{ ...fanboxFlow, fields: [] }],
    }
    mockListPlugins.mockResolvedValue({ plugins: [pixivPlugin] })
    mockGetCredentials.mockResolvedValue({
      pixiv: { configured: true, account: 'default', accounts: 1 },
    })
    mockListAccounts.mockResolvedValue({ source: 'pixiv', accounts: defaultOnly })
    render(<CredentialsPage />)
    await userEvent.click(await screen.findByRole('button', { name: /^Pixiv/ }))

    await userEvent.type(await screen.findByLabelText('credentials.newAccountName'), 'alt')
    await userEvent.type(
      screen.getByPlaceholderText('settings.enterPixivRefreshToken'),
      'refresh-token',
    )
    await userEvent.click(screen.getByRole('button', { name: 'settings.saveToken' }))

    await waitFor(() => expect(mockSetPixivToken).toHaveBeenCalledWith('refresh-token', 'alt'))
    expect(screen.queryByText('pixiv-user')).not.toBeInTheDocument()
  })

  describe('configured sites list', () => {
    const twitterAccounts: CredentialAccount[] = [
      { account: 'main', credential_type: 'cookies', is_active: true },
      { account: 'backup', credential_type: 'cookies', is_active: false },
    ]

    async function openSiteList() {
      mockGetCredentials.mockResolvedValue({
        twitter: { configured: true, account: 'main', accounts: 2 },
        weibo: { configured: true, account: 'default', accounts: 1 },
      })
      mockListAccounts.mockResolvedValue({ source: 'twitter', accounts: twitterAccounts })
      render(<CredentialsPage />)
      await userEvent.click(
        await screen.findByRole('button', { name: /credentials\.genericCookies/ }),
      )
    }

    it('shows the active account and the account count on each site row', async () => {
      await openSiteList()

      const toggle = await screen.findByRole('button', { name: 'credentials.showAccounts twitter' })
      expect(within(toggle).getByText('main')).toBeInTheDocument()
      expect(within(toggle).getByText('credentials.accountCount 2')).toBeInTheDocument()
    })

    it('names the site on the expanded account panel and keeps it inside that site card', async () => {
      await openSiteList()

      const toggle = await screen.findByRole('button', { name: 'credentials.showAccounts twitter' })
      await userEvent.click(toggle)

      const panel = await screen.findByRole('region', { name: 'credentials.accountsOf twitter' })
      expect(within(panel).getByText('credentials.accountsOf twitter')).toBeInTheDocument()
      expect(await within(panel).findByText('backup')).toBeInTheDocument()
      // Same card as the row that opened it, and not the neighbouring site's.
      expect(panel.closest('[data-site]')).toHaveAttribute('data-site', 'twitter')
      expect(toggle.closest('[data-site]')).toBe(panel.closest('[data-site]'))
    })

    it('points the add form at the site when adding an account from its panel', async () => {
      await openSiteList()
      await userEvent.click(
        await screen.findByRole('button', { name: 'credentials.showAccounts twitter' }),
      )

      await userEvent.click(
        await screen.findByRole('button', { name: 'credentials.addAccountTo twitter' }),
      )

      expect(screen.getByPlaceholderText('credentials.siteNamePlaceholder')).toHaveValue('twitter')
      expect(screen.getByLabelText('credentials.newAccountName')).toHaveFocus()
      expect(screen.getByText('credentials.existingSiteHint twitter main')).toBeInTheDocument()
    })
  })
})
