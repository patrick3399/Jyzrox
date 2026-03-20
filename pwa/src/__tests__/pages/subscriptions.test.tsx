/**
 * Subscriptions page — Vitest test suite
 *
 * Covers:
 *   Page renders without crashing
 *   Page title visible
 *   Loading state shows spinner
 *   Empty state shows empty message
 *   Subscription cards rendered when data exists
 *   Subscription card shows name
 *   Subscription card shows source badge
 *   Add button visible
 *   Subscription with last_status 'error' shows last_error text
 *   Subscription with enabled=false shows disabled badge
 *
 * Mock strategy:
 *   - @/hooks/useSubscriptions → controlled per test via hoisted mocks
 *   - @/lib/ws → stub returning no events
 *   - swr → stub so useSWR (jobs fetcher) returns empty
 *   - @/lib/api → stub subscriptions.jobs
 *   - @/lib/i18n → t() returns key as-is
 *   - sonner → stub toast helpers
 *   - next/navigation, next/link → minimal stubs
 *   - @/components/LocaleProvider, @/components/LoadingSpinner → minimal stubs
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'

// ── Hoisted mock helpers ───────────────────────────────────────────────

const { mockUseSubscriptions, mockCreateSub, mockDeleteSub, mockUpdateSub, mockCheckSub } =
  vi.hoisted(() => ({
    mockUseSubscriptions: vi.fn(),
    mockCreateSub: vi.fn(),
    mockDeleteSub: vi.fn(),
    mockUpdateSub: vi.fn(),
    mockCheckSub: vi.fn(),
  }))

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: () => ({ locale: 'en', setLocale: vi.fn() }),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

vi.mock('@/lib/api', () => ({
  api: {
    downloads: {
      list: vi.fn().mockResolvedValue({ jobs: [] }),
    },
    subscriptions: {
      jobs: vi.fn().mockResolvedValue({ jobs: [] }),
      create: vi.fn(),
    },
  },
}))

vi.mock('@/lib/ws', () => ({
  useWs: () => ({ lastMessage: null, isConnected: false, lastSubCheck: null, lastJobUpdate: null }),
}))

vi.mock('swr', async (importOriginal) => {
  // Keep useSWRMutation if needed, but stub the default useSWR
  const actual = await importOriginal<typeof import('swr')>()
  return {
    ...actual,
    default: vi
      .fn()
      .mockReturnValue({ data: undefined, error: undefined, isLoading: false, mutate: vi.fn() }),
  }
})

vi.mock('@/hooks/useSubscriptions', () => ({
  useSubscriptions: mockUseSubscriptions,
  useCreateSubscription: () => ({ trigger: mockCreateSub, isMutating: false }),
  useUpdateSubscription: () => ({ trigger: mockUpdateSub, isMutating: false }),
  useDeleteSubscription: () => ({ trigger: mockDeleteSub, isMutating: false }),
  useCheckSubscription: () => ({ trigger: mockCheckSub, isMutating: false }),
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="loading-spinner" />,
}))

// ── Import page after mocks ────────────────────────────────────────────

import SubscriptionsPage from '@/app/subscriptions/page'

// ── Factories ─────────────────────────────────────────────────────────

function makeSubscription(id: number, overrides: Record<string, unknown> = {}): any {
  return {
    id,
    name: `Sub ${id}`,
    url: `https://example.com/${id}`,
    source: 'ehentai',
    source_id: String(id),
    avatar_url: null,
    enabled: true,
    auto_download: true,
    cron_expr: '0 */2 * * *',
    last_checked_at: null,
    last_status: 'pending',
    last_error: null,
    next_check_at: null,
    created_at: new Date().toISOString(),
    batch_total: 0,
    batch_enqueued: 0,
    last_job_id: null,
    ...overrides,
  }
}

// ── State helpers ──────────────────────────────────────────────────────

function setEmptyState() {
  mockUseSubscriptions.mockReturnValue({
    data: { subscriptions: [] },
    error: undefined,
    isLoading: false,
    mutate: vi.fn(),
  })
}

function setLoadingState() {
  mockUseSubscriptions.mockReturnValue({
    data: undefined,
    error: undefined,
    isLoading: true,
    mutate: vi.fn(),
  })
}

function setSubscriptionsState(subs: ReturnType<typeof makeSubscription>[]) {
  mockUseSubscriptions.mockReturnValue({
    data: { subscriptions: subs },
    error: undefined,
    isLoading: false,
    mutate: vi.fn(),
  })
}

// ── Setup / Teardown ──────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  setEmptyState()
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('Subscriptions page — initial render', () => {
  it('test_subscriptions_renders_withoutCrashing', () => {
    expect(() => render(<SubscriptionsPage />)).not.toThrow()
  })

  it('test_subscriptions_renders_pageTitle', () => {
    render(<SubscriptionsPage />)
    expect(screen.getByText('subscriptions.title')).toBeInTheDocument()
  })

  it('test_subscriptions_renders_addButton_visible', () => {
    render(<SubscriptionsPage />)
    // The add-new button shows subscriptions.addNew text
    expect(screen.getByText('subscriptions.addNew')).toBeInTheDocument()
  })
})

describe('Subscriptions page — loading state', () => {
  it('test_subscriptions_loading_rendersSpinner', () => {
    setLoadingState()
    render(<SubscriptionsPage />)
    expect(screen.getByTestId('loading-spinner')).toBeInTheDocument()
  })

  it('test_subscriptions_loading_doesNotRenderEmptyMessage', () => {
    setLoadingState()
    render(<SubscriptionsPage />)
    expect(screen.queryByText('subscriptions.noSubscriptions')).not.toBeInTheDocument()
  })
})

describe('Subscriptions page — empty state', () => {
  it('test_subscriptions_empty_rendersNoSubscriptionsMessage', () => {
    setEmptyState()
    render(<SubscriptionsPage />)
    expect(screen.getByText('subscriptions.noSubscriptions')).toBeInTheDocument()
  })

  it('test_subscriptions_empty_rendersNoSubscriptionsHint', () => {
    setEmptyState()
    render(<SubscriptionsPage />)
    expect(screen.getByText('subscriptions.noSubscriptionsHint')).toBeInTheDocument()
  })
})

describe('Subscriptions page — subscription list', () => {
  it('test_subscriptions_withData_rendersSubscriptionCardName', () => {
    setSubscriptionsState([makeSubscription(1)])
    render(<SubscriptionsPage />)
    expect(screen.getByText('Sub 1')).toBeInTheDocument()
  })

  it('test_subscriptions_withData_rendersMultipleCards', () => {
    setSubscriptionsState([makeSubscription(1), makeSubscription(2)])
    render(<SubscriptionsPage />)
    expect(screen.getByText('Sub 1')).toBeInTheDocument()
    expect(screen.getByText('Sub 2')).toBeInTheDocument()
  })

  it('test_subscriptions_withData_rendersEhentaiSourceBadge', () => {
    setSubscriptionsState([makeSubscription(1, { source: 'ehentai' })])
    render(<SubscriptionsPage />)
    // The sourceBadge renders 'E-Hentai' for source 'ehentai'
    expect(screen.getByText('E-Hentai')).toBeInTheDocument()
  })

  it('test_subscriptions_withData_rendersPixivSourceBadge', () => {
    setSubscriptionsState([makeSubscription(1, { source: 'pixiv' })])
    render(<SubscriptionsPage />)
    expect(screen.getByText('Pixiv')).toBeInTheDocument()
  })
})

describe('Subscriptions page — subscription card states', () => {
  it('test_subscriptions_withErrorStatus_rendersLastErrorText', () => {
    setSubscriptionsState([
      makeSubscription(1, { last_status: 'failed', last_error: 'Connection timeout' }),
    ])
    render(<SubscriptionsPage />)
    expect(screen.getByText('Connection timeout')).toBeInTheDocument()
  })

  it('test_subscriptions_withEnabledFalse_rendersDisabledBadge', () => {
    setSubscriptionsState([makeSubscription(1, { enabled: false })])
    render(<SubscriptionsPage />)
    // The card renders t('subscriptions.disabled') when enabled is false
    expect(screen.getByText('subscriptions.disabled')).toBeInTheDocument()
  })

  it('test_subscriptions_withEnabledTrue_doesNotRenderDisabledBadge', () => {
    setSubscriptionsState([makeSubscription(1, { enabled: true })])
    render(<SubscriptionsPage />)
    expect(screen.queryByText('subscriptions.disabled')).not.toBeInTheDocument()
  })
})
