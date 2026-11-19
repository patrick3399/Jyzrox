/**
 * Gallery page ↔ subscription: the "More" sheet entries and the follow-up of a manual check.
 *
 * Guards: viewers never fetch; a paused subscription cannot be checked from here;
 * a check hands its job to the page only on a *new* matching event; a 409 says
 * "paused"; subscribing creates an auto-download subscription without overwriting
 * an existing one.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { SWRConfig } from 'swr'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/client'
import { t } from '@/lib/i18n'
import type { SubCheckEvent } from '@/lib/ws'
import type { GallerySubscriptionLink, Subscription } from '@/lib/types'

const byGallery = vi.hoisted(() => vi.fn())
const check = vi.hoisted(() => vi.fn())
const create = vi.hoisted(() => vi.fn())
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))
const ws = vi.hoisted(() => ({ lastSubCheck: null as SubCheckEvent | null, lastJobUpdate: null }))

vi.mock('@/lib/api', () => ({ api: { subscriptions: { byGallery, check, create } } }))
vi.mock('sonner', () => ({ toast }))
vi.mock('@/lib/ws', () => ({ useWsJobs: () => ws }))

import { useGallerySubscriptionActions } from '@/hooks/useGallerySubscription'

const SUB: Subscription = {
  id: 7,
  name: 'Someone',
  url: 'https://weibo.cn/u/1',
  source: 'weibo',
  source_id: '1',
  avatar_url: null,
  enabled: true,
  auto_download: true,
  cron_expr: '0 0 * * 1',
  last_checked_at: null,
  last_item_id: null,
  last_status: 'ok',
  last_error: null,
  next_check_at: null,
  created_at: null,
  last_job_id: null,
  group_id: null,
  paused_at: null,
  checking: false,
}

const link = (overrides: Partial<GallerySubscriptionLink> = {}): GallerySubscriptionLink => ({
  subscription: SUB,
  can_subscribe: false,
  subscribe_url: null,
  ...overrides,
})

const wrapper = ({ children }: { children: ReactNode }) => (
  <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{children}</SWRConfig>
)

function setup(params: Partial<Parameters<typeof useGallerySubscriptionActions>[0]> = {}) {
  const onJobStarted = vi.fn()
  const hook = renderHook(
    () =>
      useGallerySubscriptionActions({
        galleryId: 42,
        enabled: true,
        busy: false,
        onJobStarted,
        ...params,
      }),
    { wrapper },
  )
  return { ...hook, onJobStarted }
}

beforeEach(() => {
  vi.clearAllMocks()
  ws.lastSubCheck = null
})

describe('useGallerySubscriptionActions', () => {
  it('fetches nothing and offers nothing to viewers', () => {
    const { result } = setup({ enabled: false })
    expect(byGallery).not.toHaveBeenCalled()
    expect(result.current.actions).toEqual([])
  })

  it('offers check + open for a covering subscription, with its name in the status line', async () => {
    byGallery.mockResolvedValue(link())
    const { result } = setup()
    await waitFor(() =>
      expect(result.current.actions.map((a) => a.id)).toEqual([
        'subscription-check',
        'subscription-open',
      ]),
    )
    expect(result.current.actions[0].description).toBe(
      t('library.subscriptionNeverChecked', { name: 'Someone' }),
    )
    expect(result.current.actions[0].disabled).toBe(false)
    expect(result.current.actions[1].href).toBe('/subscriptions')
  })

  it('disables the check for a paused subscription and says so', async () => {
    byGallery.mockResolvedValue(
      link({ subscription: { ...SUB, paused_at: '2026-11-01T00:00:00Z' } }),
    )
    const { result } = setup()
    await waitFor(() => expect(result.current.actions[0]?.disabled).toBe(true))
    expect(result.current.actions[0].description).toBe(
      t('library.subscriptionPausedShort', { name: 'Someone' }),
    )
  })

  it('disables the check while the page already runs a job for this gallery', async () => {
    byGallery.mockResolvedValue(link())
    const { result } = setup({ busy: true })
    await waitFor(() => expect(result.current.actions[0]?.disabled).toBe(true))
  })

  it('offers subscribe only for a subscribable account gallery', async () => {
    byGallery.mockResolvedValue(
      link({ subscription: null, can_subscribe: true, subscribe_url: 'https://weibo.com/u/1' }),
    )
    const { result } = setup()
    await waitFor(() =>
      expect(result.current.actions.map((a) => a.id)).toEqual(['subscription-create']),
    )

    byGallery.mockResolvedValue(link({ subscription: null }))
    const other = setup({ galleryId: 43 })
    await waitFor(() => expect(byGallery).toHaveBeenCalledWith(43))
    expect(other.result.current.actions).toEqual([])
  })

  it('hands the job of a new matching check event to the page and ignores the event that was already current', async () => {
    byGallery.mockResolvedValue(link())
    check.mockResolvedValue({ status: 'queued' })
    ws.lastSubCheck = { sub_id: 7, status: 'ok', new_works: 0, job_id: 'stale-job' }
    const { result, rerender, onJobStarted } = setup()
    await waitFor(() => expect(result.current.actions[0]?.id).toBe('subscription-check'))

    await act(async () => result.current.actions[0].onSelect?.())
    expect(check).toHaveBeenCalledWith(7)
    rerender()
    expect(onJobStarted).not.toHaveBeenCalled()

    ws.lastSubCheck = { sub_id: 99, status: 'ok', new_works: 0, job_id: 'other-sub' }
    rerender()
    ws.lastSubCheck = { sub_id: 7, status: 'checking', new_works: 0, job_id: null }
    rerender()
    expect(onJobStarted).not.toHaveBeenCalled()

    ws.lastSubCheck = { sub_id: 7, status: 'ok', new_works: 0, job_id: 'job-1' }
    rerender()
    expect(onJobStarted).toHaveBeenCalledWith('job-1')
  })

  it('reports a failed check and a check with no new posts', async () => {
    byGallery.mockResolvedValue(link())
    check.mockResolvedValue({ status: 'queued' })
    const { result, rerender } = setup()
    await waitFor(() => expect(result.current.actions[0]?.id).toBe('subscription-check'))

    await act(async () => result.current.actions[0].onSelect?.())
    ws.lastSubCheck = { sub_id: 7, status: 'failed', new_works: 0, job_id: null }
    rerender()
    expect(toast.error).toHaveBeenCalledWith(t('library.subscriptionCheckFailed'))

    await act(async () => result.current.actions[0].onSelect?.())
    ws.lastSubCheck = { sub_id: 7, status: 'ok', new_works: 0, job_id: null }
    rerender()
    expect(toast.info).toHaveBeenCalledWith(t('library.subscriptionCheckNoNew'))
  })

  it('says "paused" when the check endpoint answers 409', async () => {
    byGallery.mockResolvedValue(link())
    check.mockRejectedValue(new ApiError('Subscription is paused', 409, 'Subscription is paused'))
    const { result } = setup()
    await waitFor(() => expect(result.current.actions[0]?.id).toBe('subscription-check'))

    await act(async () => result.current.actions[0].onSelect?.())

    expect(toast.error).toHaveBeenCalledWith(t('library.subscriptionPaused'))
  })

  it('subscribes with auto-download without overwriting an existing subscription, then refetches', async () => {
    byGallery.mockResolvedValueOnce(
      link({ subscription: null, can_subscribe: true, subscribe_url: 'https://weibo.com/u/1' }),
    )
    byGallery.mockResolvedValue(link())
    create.mockResolvedValue({ status: 'ok', id: 7, source: 'weibo' })
    const { result } = setup()
    await waitFor(() => expect(result.current.actions[0]?.id).toBe('subscription-create'))

    act(() => result.current.actions[0].onSelect?.())
    expect(result.current.confirm.open).toBe(true)
    await act(async () => result.current.confirm.onConfirm())

    expect(create).toHaveBeenCalledWith({
      url: 'https://weibo.com/u/1',
      auto_download: true,
      reject_duplicate: true,
    })
    expect(toast.success).toHaveBeenCalledWith(t('library.subscribeAccountDone'))
    await waitFor(() => expect(result.current.actions[0]?.id).toBe('subscription-check'))
    expect(result.current.confirm.open).toBe(false)
  })

  it('treats subscription_exists as already subscribed and refetches', async () => {
    byGallery.mockResolvedValue(
      link({ subscription: null, can_subscribe: true, subscribe_url: 'https://weibo.com/u/1' }),
    )
    create.mockRejectedValue(
      new ApiError('exists', 409, {
        code: 'subscription_exists',
        subscription_id: 7,
        url: 'https://weibo.cn/u/1',
      }),
    )
    const { result } = setup()
    await waitFor(() => expect(result.current.actions[0]?.id).toBe('subscription-create'))

    act(() => result.current.actions[0].onSelect?.())
    await act(async () => result.current.confirm.onConfirm())

    expect(toast.info).toHaveBeenCalledWith(t('library.subscribeAccountExists'))
    expect(byGallery.mock.calls.length).toBeGreaterThanOrEqual(2)
  })
})
