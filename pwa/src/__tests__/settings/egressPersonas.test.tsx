/**
 * Settings > Egress Personas (admin) — Vitest suite (ADR 0022)
 *
 * Real SWR runs against a mocked `api`, so the page may fetch through any hook
 * or inline useSWR as long as the data comes from api.adminPersonas.* and
 * api.settings.*.
 */
import type { ReactNode } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { SWRConfig } from 'swr'

const m = vi.hoisted(() => ({
  guard: vi.fn(),
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  bindAccount: vi.fn(),
  unbindAccount: vi.fn(),
  test: vi.fn(),
  getCredentials: vi.fn(),
  listCredentialAccounts: vi.fn(),
}))

vi.mock('@/hooks/useAdminGuard', () => ({ useAdminGuard: () => m.guard() }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))
vi.mock('@/lib/api', () => ({
  api: {
    adminPersonas: {
      list: m.list,
      create: m.create,
      update: m.update,
      remove: m.remove,
      bindAccount: m.bindAccount,
      unbindAccount: m.unbindAccount,
      test: m.test,
    },
    settings: {
      getCredentials: m.getCredentials,
      listCredentialAccounts: m.listCredentialAccounts,
    },
  },
}))
vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) =>
    params ? `${key}:${JSON.stringify(params)}` : key,
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/components/BackButton', () => ({ BackButton: () => null }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}))

import EgressPersonasPage from '@/app/settings/egress-personas/page'

const base = {
  proxy_url: 'http://egress-11:8888',
  user_agent: null,
  browser_profile: null,
  enabled: true,
  last_exit_ip: null,
  last_tested_at: null,
  accounts: [],
}
const gw11 = {
  ...base,
  id: 1,
  name: 'gw11',
  browser_profile: 'firefox',
  accounts: [{ source: 'twitter', account: 'main' }],
}
const gw12 = { ...base, id: 2, name: 'gw12', proxy_url: 'http://egress-12:8888' }

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{children}</SWRConfig>
  )
}

async function renderPage() {
  render(<EgressPersonasPage />, { wrapper: Wrapper })
}

beforeEach(() => {
  vi.clearAllMocks()
  m.guard.mockReturnValue(true)
  m.list.mockResolvedValue([gw11, gw12])
  m.create.mockResolvedValue({ ...base, id: 3, name: 'gw20' })
  m.test.mockResolvedValue({ ip: '203.0.113.7', colo: 'TPE', same_ip: [], same_subnet: ['gw12'] })
  m.bindAccount.mockResolvedValue({ ...gw12, accounts: [{ source: 'twitter', account: 'alt1' }] })
  m.unbindAccount.mockResolvedValue(undefined)
  m.getCredentials.mockResolvedValue({
    twitter: { configured: true, account: 'main', accounts: 2 },
  })
  m.listCredentialAccounts.mockResolvedValue({
    source: 'twitter',
    accounts: [
      { account: 'main', credential_type: 'cookies', is_active: true },
      { account: 'alt1', credential_type: 'cookies', is_active: false },
    ],
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('EgressPersonasPage', () => {
  it('test_egress_personas_non_admin_renders_nothing', () => {
    m.guard.mockReturnValue(false)
    const { container } = render(<EgressPersonasPage />, { wrapper: Wrapper })
    expect(container.innerHTML).toBe('')
  })

  it('test_egress_personas_lists_rows_from_admin_api', async () => {
    await renderPage()
    expect(await screen.findByText('gw11')).toBeInTheDocument()
    expect(screen.getByText('gw12')).toBeInTheDocument()
    expect(screen.getByTestId('persona-card-1')).toHaveTextContent('main')
  })

  it('test_egress_personas_user_agent_input_disabled_while_browser_profile_selected', async () => {
    m.list.mockResolvedValue([])
    await renderPage()
    const browser = await screen.findByLabelText('personas.browserProfile')
    const ua = screen.getByLabelText('personas.userAgent')
    expect(ua).toBeEnabled()

    fireEvent.change(browser, { target: { value: 'chrome' } })

    expect(ua).toBeDisabled()
  })

  it('test_egress_personas_create_with_browser_profile_sends_no_user_agent', async () => {
    m.list.mockResolvedValue([])
    await renderPage()
    fireEvent.change(await screen.findByLabelText('personas.name'), { target: { value: 'gw20' } })
    fireEvent.change(screen.getByLabelText('personas.userAgent'), { target: { value: 'UA/1.0' } })
    fireEvent.change(screen.getByLabelText('personas.browserProfile'), {
      target: { value: 'chrome' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'personas.create' }))

    await waitFor(() => expect(m.create).toHaveBeenCalledTimes(1))
    const payload = m.create.mock.calls[0][0]
    expect(payload).toMatchObject({ name: 'gw20', browser_profile: 'chrome' })
    expect(payload.user_agent ?? null).toBeNull()
  })

  it('test_egress_personas_test_button_shows_exit_ip_and_same_subnet_warning', async () => {
    await renderPage()
    const card = await screen.findByTestId('persona-card-1')
    fireEvent.click(within(card).getByRole('button', { name: 'personas.test' }))

    await waitFor(() => expect(m.test).toHaveBeenCalledWith(1))
    await waitFor(() => expect(card.textContent).toMatch(/203\.0\.113\.7/))
    expect(card.textContent).toMatch(/personas\.sameSubnet.*gw12/)
  })

  it('test_egress_personas_binder_lists_accounts_and_binds_selected_one', async () => {
    await renderPage()
    const card = await screen.findByTestId('persona-card-2')
    const option = await within(card).findByRole('option', { name: 'alt1' })
    expect(m.listCredentialAccounts).toHaveBeenCalledWith('twitter')

    fireEvent.change(option.closest('select')!, { target: { value: 'alt1' } })
    fireEvent.click(within(card).getByRole('button', { name: 'personas.bind' }))

    await waitFor(() => expect(m.bindAccount).toHaveBeenCalledWith(2, 'twitter', 'alt1'))
  })

  it('test_egress_personas_unbind_button_removes_the_bound_account', async () => {
    await renderPage()
    const card = await screen.findByTestId('persona-card-1')
    fireEvent.click(within(card).getByRole('button', { name: 'personas.unbind' }))

    await waitFor(() => expect(m.unbindAccount).toHaveBeenCalledWith(1, 'twitter'))
  })
})
