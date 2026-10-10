/**
 * CredentialAccounts — the per-source account list on the credentials page.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CredentialAccount } from '@/lib/types'

const mockList = vi.fn()
const mockActivate = vi.fn(async (_source: string, account: string) => ({ status: 'ok', account }))
const mockDelete = vi.fn(async (_source: string, _account: string) => ({ status: 'ok' }))

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

vi.mock('@/lib/api', () => ({
  api: {
    settings: {
      listCredentialAccounts: (source: string) => mockList(source),
      activateCredentialAccount: (source: string, account: string) => mockActivate(source, account),
      deleteCredentialAccount: (source: string, account: string) => mockDelete(source, account),
    },
  },
}))

import { CredentialAccounts, sanitizeAccountName } from '@/components/CredentialAccounts'

const twoAccounts: CredentialAccount[] = [
  { account: 'default', credential_type: 'cookie', is_active: true },
  { account: 'alt', credential_type: 'cookie', is_active: false },
]

beforeEach(() => {
  vi.clearAllMocks()
  mockList.mockResolvedValue({ source: 'twitter', accounts: twoAccounts })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

describe('CredentialAccounts', () => {
  it('lists every account and marks the active one', async () => {
    render(<CredentialAccounts source="twitter" refreshKey={0} onChanged={vi.fn()} />)

    expect(await screen.findByText('default')).toBeInTheDocument()
    expect(screen.getByText('alt')).toBeInTheDocument()
    expect(screen.getAllByText('credentials.accountActive')).toHaveLength(1)
    expect(mockList).toHaveBeenCalledWith('twitter')
  })

  it('switches the active account, reloads the list and notifies the parent', async () => {
    const onChanged = vi.fn()
    render(<CredentialAccounts source="twitter" refreshKey={0} onChanged={onChanged} />)

    await userEvent.click(await screen.findByRole('button', { name: 'credentials.setActive' }))

    await waitFor(() => expect(mockActivate).toHaveBeenCalledWith('twitter', 'alt'))
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2))
  })

  it('offers delete only on accounts that are not active', async () => {
    render(<CredentialAccounts source="twitter" refreshKey={0} onChanged={vi.fn()} />)

    expect(
      await screen.findByRole('button', { name: 'credentials.deleteAccount alt' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'credentials.deleteAccount default' }),
    ).not.toBeInTheDocument()
  })

  it('deletes an inactive account after confirmation', async () => {
    const onChanged = vi.fn()
    render(<CredentialAccounts source="twitter" refreshKey={0} onChanged={onChanged} />)

    await userEvent.click(
      await screen.findByRole('button', { name: 'credentials.deleteAccount alt' }),
    )

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('twitter', 'alt'))
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1))
  })

  it('does not delete when the confirmation is dismissed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<CredentialAccounts source="twitter" refreshKey={0} onChanged={vi.fn()} />)

    await userEvent.click(
      await screen.findByRole('button', { name: 'credentials.deleteAccount alt' }),
    )

    expect(mockDelete).not.toHaveBeenCalled()
  })

  it('reports only backend-valid characters from the new-account input', async () => {
    const onNewAccountChange = vi.fn()
    render(
      <CredentialAccounts
        source="twitter"
        refreshKey={0}
        onChanged={vi.fn()}
        newAccount=""
        onNewAccountChange={onNewAccountChange}
      />,
    )

    await userEvent.type(await screen.findByLabelText('credentials.newAccountName'), 'a/')

    expect(onNewAccountChange).toHaveBeenNthCalledWith(1, 'a')
    expect(onNewAccountChange).toHaveBeenNthCalledWith(2, '')
  })

  it('hides the new-account input when the parent does not manage a name', async () => {
    render(<CredentialAccounts source="twitter" refreshKey={0} onChanged={vi.fn()} />)

    await screen.findByText('default')
    expect(screen.queryByLabelText('credentials.newAccountName')).not.toBeInTheDocument()
  })
})

describe('sanitizeAccountName', () => {
  it.each([
    ['backup', 'backup'],
    [' -my acc/ount!', 'myaccount'],
    ['user@example.com', 'user@example.com'],
    ['a'.repeat(50), 'a'.repeat(40)],
    ['___', ''],
  ])('%s -> %s', (raw, expected) => {
    expect(sanitizeAccountName(raw)).toBe(expected)
  })
})
