/**
 * Regression test: the add-subscription form's Auto Download toggle starts off,
 * and must start off again after a subscription has been added.
 *
 * Guards: the post-success form reset used to set autoDownload to true, so the
 * second and later subscriptions silently got auto-download enabled while the
 * first one (fresh page) did not.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const createSub = vi.hoisted(() => vi.fn())

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}))

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

vi.mock('sonner', () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
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

function autoDownloadToggle(): HTMLButtonElement {
  const toggle = screen
    .getByText('subscriptions.autoDownload')
    .parentElement?.querySelector('button')
  if (!toggle) throw new Error('auto download toggle not found')
  return toggle as HTMLButtonElement
}

const isOn = (toggle: HTMLButtonElement) => toggle.className.includes('bg-vault-accent')

function openAddForm() {
  fireEvent.click(screen.getByRole('button', { name: 'subscriptions.addNew' }))
}

async function addSubscription(url: string) {
  fireEvent.change(screen.getByPlaceholderText('subscriptions.urlPlaceholder'), {
    target: { value: url },
  })
  fireEvent.click(screen.getByRole('button', { name: 'subscriptions.add' }))
  await waitFor(() =>
    expect(screen.queryByPlaceholderText('subscriptions.urlPlaceholder')).toBeNull(),
  )
}

describe('subscriptions add form auto download default', () => {
  beforeEach(() => {
    createSub.mockReset()
    createSub.mockResolvedValue({ status: 'ok', id: 1, source: null })
  })

  it('test_add_form_auto_download_starts_off', async () => {
    render(<SubscriptionsPage />)
    openAddForm()

    expect(isOn(autoDownloadToggle())).toBe(false)

    await addSubscription('https://example.com/a')
    expect(createSub.mock.calls[0][0]).toMatchObject({ auto_download: false })
  })

  it('test_add_form_auto_download_is_off_again_after_a_subscription_was_added', async () => {
    render(<SubscriptionsPage />)
    openAddForm()
    await addSubscription('https://example.com/a')

    openAddForm()
    expect(isOn(autoDownloadToggle())).toBe(false)

    await addSubscription('https://example.com/b')
    expect(createSub).toHaveBeenCalledTimes(2)
    expect(createSub.mock.calls[1][0]).toMatchObject({
      url: 'https://example.com/b',
      auto_download: false,
    })
  })

  it('test_add_form_auto_download_chosen_for_one_subscription_does_not_carry_over', async () => {
    render(<SubscriptionsPage />)
    openAddForm()
    fireEvent.click(autoDownloadToggle())
    expect(isOn(autoDownloadToggle())).toBe(true)
    await addSubscription('https://example.com/a')
    expect(createSub.mock.calls[0][0]).toMatchObject({ auto_download: true })

    openAddForm()
    expect(isOn(autoDownloadToggle())).toBe(false)
  })
})
