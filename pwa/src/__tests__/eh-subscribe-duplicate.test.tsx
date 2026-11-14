/**
 * Feature test: subscribing to an E-Hentai search that already has a
 * subscription asks before overwriting it.
 *
 * Guards: the first submit opts in to the server's refusal; cancelling sends
 * nothing else; only confirming resends without the flag; a different failure
 * keeps the existing toast.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/client'

const createSub = vi.hoisted(() => vi.fn())
const toastSuccess = vi.hoisted(() => vi.fn())
const toastInfo = vi.hoisted(() => vi.fn())
const toastError = vi.hoisted(() => vi.fn())

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams('q=artist'),
}))

vi.mock('@/hooks/useSubscriptions', () => ({
  useCreateSubscription: () => ({ trigger: createSub, isMutating: false }),
  useSubscriptions: () => ({ data: { subscriptions: [] }, mutate: vi.fn() }),
}))

vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({ data: { username: 'qa-user' }, isLoading: false }),
}))

vi.mock('swr', () => ({
  default: () => ({ data: { ehentai: { configured: true } }, isLoading: false }),
}))

vi.mock('@/hooks/useGridKeyboard', () => ({
  useGridKeyboard: () => ({ focusedIndex: -1 }),
}))

vi.mock('@/components/VirtualGrid', () => ({ VirtualGrid: () => null }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => null }))
vi.mock('@/components/CredentialBanner', () => ({ CredentialBanner: () => null }))

vi.mock('sonner', () => ({
  toast: { success: toastSuccess, info: toastInfo, error: toastError },
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) =>
    params ? `${key}:${Object.values(params).join(',')}` : key,
}))

vi.mock('@/lib/api', () => ({
  api: {
    savedSearches: { list: vi.fn(async () => ({ searches: [] })) },
    settings: { getCredentials: vi.fn(async () => ({ ehentai: { configured: true } })) },
    tags: { autocomplete: vi.fn(async () => []) },
    eh: {
      search: vi.fn(async () => ({ galleries: [], total: 0, next_gid: null })),
      getFavorites: vi.fn(async () => ({
        galleries: [],
        total: 0,
        has_next: false,
        next_cursor: null,
        categories: [],
      })),
      getPopular: vi.fn(async () => ({ galleries: [] })),
      getToplist: vi.fn(async () => ({ galleries: [], total: 0 })),
      getBrowseStatus: vi.fn(async () => ({ statuses: {} })),
    },
  },
}))

import Page from '@/app/e-hentai/page'

function exists() {
  return new ApiError('HTTP 409', 409, {
    code: 'subscription_exists',
    subscription_id: 7,
    name: 'Existing Search',
    url: 'https://e-hentai.org/?f_search=artist',
  })
}

async function submitSubscribe() {
  render(<Page />)
  fireEvent.click(await screen.findByTitle('browse.subscribeToSearch'))
  fireEvent.click(screen.getByRole('button', { name: 'subscriptions.add' }))
}

describe('E-Hentai subscribe with a search that is already subscribed', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    createSub.mockReset()
    toastSuccess.mockReset()
    toastInfo.mockReset()
    toastError.mockReset()
  })

  it('test_eh_subscribe_duplicate_asks_before_overwriting', async () => {
    createSub.mockRejectedValueOnce(exists())
    await submitSubscribe()

    const dialog = await screen.findByRole('alertdialog')
    expect(dialog.textContent).toContain('Existing Search')
    expect(createSub).toHaveBeenCalledTimes(1)
    expect(createSub.mock.calls[0][0]).toMatchObject({ reject_duplicate: true })
    expect(toastError).not.toHaveBeenCalled()
  })

  it('test_eh_subscribe_duplicate_cancel_sends_nothing_else', async () => {
    createSub.mockRejectedValueOnce(exists())
    await submitSubscribe()
    await screen.findByRole('alertdialog')

    fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(createSub).toHaveBeenCalledTimes(1)
    expect(toastSuccess).not.toHaveBeenCalled()
  })

  it('test_eh_subscribe_duplicate_confirm_resends_without_the_refusal_flag', async () => {
    createSub.mockRejectedValueOnce(exists())
    createSub.mockResolvedValueOnce({ status: 'ok', id: 7, source: 'ehentai', duplicate: true })
    await submitSubscribe()
    await screen.findByRole('alertdialog')

    fireEvent.click(screen.getByRole('button', { name: 'subscriptions.duplicateConfirm' }))

    await waitFor(() => expect(createSub).toHaveBeenCalledTimes(2))
    expect(createSub.mock.calls[1][0]).not.toHaveProperty('reject_duplicate')
    await waitFor(() => expect(toastInfo).toHaveBeenCalledWith('subscriptions.duplicateUpdated'))
    expect(toastSuccess).not.toHaveBeenCalled()
  })

  it('test_eh_subscribe_other_failure_keeps_the_failed_toast', async () => {
    createSub.mockRejectedValueOnce(new ApiError('Nope', 409, { code: 'something_else' }))
    await submitSubscribe()

    await waitFor(() => expect(toastError).toHaveBeenCalledWith('browse.subscribeFailed'))
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })
})
