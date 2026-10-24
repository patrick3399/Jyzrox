/**
 * Credentials page — the generic site list must only hold gallery-dl sites.
 *
 * SauceNAO's API key has its own section; listing it under generic site
 * cookies as well made it look like a login cookie with an account panel.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }))
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
    plugins: { list: async () => ({ plugins: [] }) },
    settings: {
      getCredentials: async () => ({
        saucenao: { configured: true, account: 'default', accounts: 1 },
        ehentai: { configured: true, account: 'default', accounts: 1 },
        pixiv: { configured: true, account: 'default', accounts: 1 },
        fanbox: { configured: true, account: 'default', accounts: 1 },
      }),
      listCredentialAccounts: async () => ({ source: 'x', accounts: [] }),
    },
  },
}))

import CredentialsPage from '@/app/credentials/page'

beforeEach(() => vi.clearAllMocks())

describe('CredentialsPage generic site list', () => {
  it('does not list saucenao, ehentai or pixiv as generic site cookies', async () => {
    const { container } = render(<CredentialsPage />)
    await userEvent.click(await screen.findByRole('button', { name: /credentials.genericCookies/ }))

    await screen.findByText('fanbox')
    expect(container.querySelector('[data-site="fanbox"]')).not.toBeNull()
    expect(container.querySelector('[data-site="saucenao"]')).toBeNull()
    expect(container.querySelector('[data-site="ehentai"]')).toBeNull()
    expect(container.querySelector('[data-site="pixiv"]')).toBeNull()
  })
})
