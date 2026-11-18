/**
 * Feature test: subscribing to an account that an earlier plain download
 * already holds says so before creating the subscription.
 *
 * Guards: the first submit opts in to the notice; the notice names the held
 * gallery and links to it; cancelling sends nothing else; only confirming
 * resends without the opt-in flag; an unrelated 409 stays a plain error toast.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/client'
import { existingGalleryHint } from '@/components/subscriptions/existingGallery'

const createSub = vi.hoisted(() => vi.fn())
const toastSuccess = vi.hoisted(() => vi.fn())
const toastInfo = vi.hoisted(() => vi.fn())
const toastError = vi.hoisted(() => vi.fn())
const idle = vi.hoisted(() => ({ trigger: vi.fn(), isMutating: false }))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(''),
}))

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

vi.mock('@/hooks/useSubscriptions', () => ({
  useAllSubscriptions: () => ({ data: { subscriptions: [] }, mutate: vi.fn(), isLoading: false }),
  useCreateSubscription: () => ({ trigger: createSub, isMutating: false }),
  useUpdateSubscription: () => idle,
  useDeleteSubscription: () => idle,
  useCheckSubscription: () => idle,
  useBackfillSubscription: () => idle,
}))

vi.mock('@/hooks/useSubscriptionGroups', () => ({
  useSubscriptionGroups: () => ({ data: { groups: [] }, mutate: vi.fn() }),
  useCreateGroup: () => idle,
  useUpdateGroup: () => idle,
  useDeleteGroup: () => idle,
  useRunGroup: () => idle,
  usePauseGroup: () => idle,
  useResumeGroup: () => idle,
  useBulkMove: () => idle,
}))

vi.mock('@/hooks/useDownloadQueue', () => ({
  useDownloadJobs: () => ({ data: { jobs: [] } }),
  useCheckUrl: () => ({ data: undefined }),
}))

vi.mock('@/lib/ws', () => ({
  useWsJobs: () => ({ lastSubCheck: null, lastJobUpdate: null }),
  useWsConnection: () => ({ connected: false }),
}))

vi.mock('sonner', () => ({
  toast: { success: toastSuccess, info: toastInfo, error: toastError },
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) =>
    params ? `${key}:${Object.values(params).join(',')}` : key,
}))

vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))

import Page from '@/app/subscriptions/page'

function held() {
  return new ApiError('HTTP 409', 409, {
    code: 'gallery_exists',
    url: 'https://weibo.cn/u/3802725779',
    gallery_id: 97807,
    source: 'weibo',
    source_id: '3802725779',
    title: 'Held Gallery',
    pages: 8827,
    download_status: 'complete',
  })
}

async function submitAdd() {
  render(<Page />)
  fireEvent.click(await screen.findByRole('button', { name: 'subscriptions.addNew' }))
  fireEvent.change(screen.getByPlaceholderText('subscriptions.urlPlaceholder'), {
    target: { value: 'https://weibo.cn/u/3802725779' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'subscriptions.add' }))
}

describe('existingGalleryHint', () => {
  it('test_existing_gallery_hint_reads_only_the_gallery_exists_code', () => {
    expect(existingGalleryHint(held())).toEqual({
      source: 'weibo',
      sourceId: '3802725779',
      title: 'Held Gallery',
      pages: 8827,
    })
    expect(
      existingGalleryHint(new ApiError('x', 409, { code: 'subscription_exists', url: 'u' })),
    ).toBeNull()
    expect(existingGalleryHint(new Error('plain'))).toBeNull()
  })
})

describe('Subscribing to an account an earlier download already holds', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    createSub.mockReset()
    toastSuccess.mockReset()
    toastInfo.mockReset()
    toastError.mockReset()
  })

  it('test_subscribe_held_account_first_submit_opts_in_and_names_the_gallery', async () => {
    createSub.mockRejectedValueOnce(held())
    await submitAdd()

    const dialog = await screen.findByRole('alertdialog')
    expect(dialog.textContent).toContain('Held Gallery')
    expect(dialog.querySelector('a')?.getAttribute('href')).toBe('/library/weibo/3802725779')
    expect(createSub).toHaveBeenCalledTimes(1)
    expect(createSub.mock.calls[0][0]).toMatchObject({
      reject_duplicate: true,
      warn_existing_gallery: true,
    })
    expect(toastError).not.toHaveBeenCalled()
  })

  it('test_subscribe_held_account_cancel_creates_nothing', async () => {
    createSub.mockRejectedValueOnce(held())
    await submitAdd()
    await screen.findByRole('alertdialog')

    fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(createSub).toHaveBeenCalledTimes(1)
    expect(toastSuccess).not.toHaveBeenCalled()
  })

  it('test_subscribe_held_account_confirm_resends_without_the_notice_flag', async () => {
    createSub.mockRejectedValueOnce(held())
    createSub.mockResolvedValueOnce({ status: 'ok', id: 9, source: 'weibo' })
    await submitAdd()
    await screen.findByRole('alertdialog')

    fireEvent.click(screen.getByRole('button', { name: 'subscriptions.existingGalleryConfirm' }))

    await waitFor(() => expect(createSub).toHaveBeenCalledTimes(2))
    expect(createSub.mock.calls[1][0]).not.toHaveProperty('warn_existing_gallery')
    expect(createSub.mock.calls[1][0]).toMatchObject({ reject_duplicate: true })
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('subscriptions.added'))
  })

  it('test_subscribe_other_409_keeps_the_failed_toast', async () => {
    createSub.mockRejectedValueOnce(new ApiError('Nope', 409, { code: 'something_else' }))
    await submitAdd()

    await waitFor(() => expect(toastError).toHaveBeenCalled())
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })
})
