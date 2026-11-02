/**
 * Feature test: submitting the add form with a URL that already has a
 * subscription asks before overwriting it.
 *
 * Guards: the first submit opts in to the server's refusal; cancelling sends
 * nothing else and keeps the form; only confirming resends without the flag.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/client'

const createSub = vi.hoisted(() => vi.fn())
const toastInfo = vi.hoisted(() => vi.fn())
const toastError = vi.hoisted(() => vi.fn())

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}))

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

vi.mock('sonner', () => ({
  toast: { info: toastInfo, success: vi.fn(), error: toastError },
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) =>
    params ? `${key}:${Object.values(params).join(',')}` : key,
}))

vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))

vi.mock('@/lib/ws', () => ({
  useWsConnection: () => ({ connected: true }),
  useWsJobs: () => ({ lastSubCheck: null, lastJobUpdate: null }),
}))

vi.mock('@/lib/api', () => ({ api: { subscriptions: {} } }))

vi.mock('@/hooks/useSubscriptions', () => {
  const trigger = { trigger: vi.fn(), isMutating: false }
  return {
    useAllSubscriptions: () => ({
      data: { subscriptions: [], total: 0 },
      mutate: vi.fn(),
      isLoading: false,
    }),
    useCreateSubscription: () => ({ trigger: createSub, isMutating: false }),
    useUpdateSubscription: () => trigger,
    useDeleteSubscription: () => trigger,
    useCheckSubscription: () => trigger,
    useBackfillSubscription: () => trigger,
  }
})

vi.mock('@/hooks/useSubscriptionGroups', () => {
  const trigger = { trigger: vi.fn() }
  return {
    useSubscriptionGroups: () => ({ data: { groups: [] }, mutate: vi.fn() }),
    useCreateGroup: () => trigger,
    useUpdateGroup: () => trigger,
    useDeleteGroup: () => trigger,
    useRunGroup: () => trigger,
    usePauseGroup: () => trigger,
    useResumeGroup: () => trigger,
    useBulkMove: () => trigger,
  }
})

vi.mock('@/hooks/useDownloadQueue', () => ({
  useDownloadJobs: () => ({ data: { jobs: [] }, mutate: vi.fn() }),
  useCheckUrl: () => ({ data: undefined }),
}))

import SubscriptionsPage from '@/app/subscriptions/page'

const URL_WITH_SLASH = 'https://example.com/artist/'

function exists() {
  return new ApiError('HTTP 409', 409, {
    code: 'subscription_exists',
    subscription_id: 7,
    name: 'Existing Artist',
    url: 'https://example.com/artist',
  })
}

async function submitDuplicate() {
  render(<SubscriptionsPage />)
  fireEvent.click(screen.getByRole('button', { name: 'subscriptions.addNew' }))
  fireEvent.change(screen.getByPlaceholderText('subscriptions.urlPlaceholder'), {
    target: { value: URL_WITH_SLASH },
  })
  fireEvent.click(screen.getByRole('button', { name: 'subscriptions.add' }))
  await screen.findByRole('alertdialog')
}

describe('subscriptions add form with a duplicate URL', () => {
  beforeEach(() => {
    createSub.mockReset()
    toastInfo.mockReset()
    toastError.mockReset()
    createSub.mockRejectedValueOnce(exists())
  })

  it('test_add_duplicate_url_asks_before_overwriting_and_names_the_existing_subscription', async () => {
    await submitDuplicate()

    expect(createSub).toHaveBeenCalledTimes(1)
    expect(createSub.mock.calls[0][0]).toMatchObject({
      url: URL_WITH_SLASH,
      reject_duplicate: true,
    })
    expect(screen.getByRole('alertdialog').textContent).toContain('Existing Artist')
    expect(toastError).not.toHaveBeenCalled()
    expect(toastInfo).not.toHaveBeenCalled()
  })

  it('test_add_duplicate_url_cancel_sends_nothing_and_keeps_the_form', async () => {
    await submitDuplicate()

    fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(createSub).toHaveBeenCalledTimes(1)
    expect(screen.getByPlaceholderText('subscriptions.urlPlaceholder')).toHaveProperty(
      'value',
      URL_WITH_SLASH,
    )
  })

  it('test_add_duplicate_url_confirm_resends_without_the_refusal_flag', async () => {
    createSub.mockResolvedValueOnce({ status: 'ok', id: 7, source: null, duplicate: true })
    await submitDuplicate()

    fireEvent.click(screen.getByRole('button', { name: 'subscriptions.duplicateConfirm' }))

    await waitFor(() => expect(createSub).toHaveBeenCalledTimes(2))
    expect(createSub.mock.calls[1][0]).toMatchObject({ url: URL_WITH_SLASH })
    expect(createSub.mock.calls[1][0]).not.toHaveProperty('reject_duplicate')
    await waitFor(() => expect(toastInfo).toHaveBeenCalledWith('subscriptions.duplicateUpdated'))
    expect(screen.queryByPlaceholderText('subscriptions.urlPlaceholder')).toBeNull()
  })

  it('test_add_other_conflict_error_shows_a_toast_instead_of_the_dialog', async () => {
    createSub.mockReset()
    createSub.mockRejectedValueOnce(new ApiError('Nope', 409, { code: 'something_else' }))
    render(<SubscriptionsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'subscriptions.addNew' }))
    fireEvent.change(screen.getByPlaceholderText('subscriptions.urlPlaceholder'), {
      target: { value: URL_WITH_SLASH },
    })
    fireEvent.click(screen.getByRole('button', { name: 'subscriptions.add' }))

    await waitFor(() => expect(toastError).toHaveBeenCalledWith('Nope'))
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })
})
