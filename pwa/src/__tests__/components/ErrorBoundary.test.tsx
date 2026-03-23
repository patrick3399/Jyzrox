/**
 * Regression tests: ErrorBoundary resets on route change.
 *
 * Bug: ErrorBoundary had no mechanism to clear caught errors when the user
 * navigated to a different route. The fix adds a PathnameReset child that
 * watches usePathname() and calls reset() when the pathname changes.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { ErrorBoundary } from '@/components/ErrorBoundary'

// ── Mock next/navigation ──────────────────────────────────────────────

let mockPathname = '/explorer'

vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

// ── Mock @/lib/i18n so keys are predictable ───────────────────────────

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => {
    const map: Record<string, string> = {
      'common.errorOccurred': 'Something went wrong',
      'common.retry': 'Try again',
    }
    return map[key] ?? key
  },
}))

// ── Helpers ───────────────────────────────────────────────────────────

let shouldThrow = true

function BuggyComponent() {
  if (shouldThrow) throw new Error('Test crash')
  return <div>Children rendered OK</div>
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('ErrorBoundary', () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    mockPathname = '/explorer'
    shouldThrow = true
    // Suppress React's error boundary console.error noise
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    consoleErrorSpy.mockRestore()
  })

  it('test_error_boundary_renders_children_normally', () => {
    shouldThrow = false
    render(
      <ErrorBoundary>
        <div>Hello world</div>
      </ErrorBoundary>,
    )
    expect(screen.getByText('Hello world')).toBeDefined()
  })

  it('test_error_boundary_shows_error_fallback_on_throw', () => {
    render(
      <ErrorBoundary>
        <BuggyComponent />
      </ErrorBoundary>,
    )

    expect(screen.getByText('Something went wrong')).toBeDefined()
    expect(screen.getByText('Test crash')).toBeDefined()
  })

  it('test_error_boundary_resets_on_pathname_change', () => {
    // shouldThrow starts as true — BuggyComponent will throw on first render.
    // After the error is caught, we allow it to render successfully.
    const { rerender } = render(
      <ErrorBoundary>
        <BuggyComponent />
      </ErrorBoundary>,
    )

    // Confirm error state is shown
    expect(screen.getByText('Something went wrong')).toBeDefined()

    // Allow BuggyComponent to render successfully on next attempt
    shouldThrow = false

    // Simulate navigation: change the pathname and re-render so that
    // PathnameReset's useEffect fires with the new value.
    act(() => {
      mockPathname = '/library'
    })

    rerender(
      <ErrorBoundary>
        <BuggyComponent />
      </ErrorBoundary>,
    )

    // The pathname change should have triggered reset(), clearing the error.
    expect(screen.getByText('Children rendered OK')).toBeDefined()
    expect(screen.queryByText('Something went wrong')).toBeNull()
  })

  it('test_error_boundary_retry_button_resets_error', () => {
    render(
      <ErrorBoundary>
        <BuggyComponent />
      </ErrorBoundary>,
    )

    // Error fallback is visible
    expect(screen.getByText('Something went wrong')).toBeDefined()

    // Allow successful re-render after reset
    shouldThrow = false

    const retryButton = screen.getByText('Try again')
    fireEvent.click(retryButton)

    // After reset, children should render successfully
    expect(screen.getByText('Children rendered OK')).toBeDefined()
    expect(screen.queryByText('Something went wrong')).toBeNull()
  })
})
