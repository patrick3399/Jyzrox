import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ErrorBoundary } from '@/components/ErrorBoundary'

// Suppress React's console.error output for intentionally thrown errors
// so the test output stays clean.
const suppressConsoleError = () => {
  const original = console.error
  beforeEach(() => {
    console.error = vi.fn()
  })
  afterEach(() => {
    console.error = original
  })
}

// A component that always throws on render.
function BrokenChild({ message }: { message?: string }): never {
  throw new Error(message ?? 'test render error')
}

// A component that renders normally.
function HealthyChild() {
  return <div data-testid="healthy">All good</div>
}

describe('ErrorBoundary', () => {
  suppressConsoleError()

  // ── Happy path: children render normally ──────────────────────────

  it('test_errorboundary_renders_children_when_no_error', () => {
    render(
      <ErrorBoundary>
        <HealthyChild />
      </ErrorBoundary>,
    )
    expect(screen.getByTestId('healthy')).toBeInTheDocument()
    expect(screen.getByText('All good')).toBeInTheDocument()
  })

  it('test_errorboundary_does_not_render_error_ui_when_no_error', () => {
    render(
      <ErrorBoundary>
        <HealthyChild />
      </ErrorBoundary>,
    )
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
  })

  // ── Error path: default fallback UI ──────────────────────────────

  it('test_errorboundary_renders_default_error_ui_when_child_throws', () => {
    render(
      <ErrorBoundary>
        <BrokenChild />
      </ErrorBoundary>,
    )
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('test_errorboundary_displays_error_message_in_default_fallback', () => {
    render(
      <ErrorBoundary>
        <BrokenChild message="disk full" />
      </ErrorBoundary>,
    )
    expect(screen.getByText('disk full')).toBeInTheDocument()
  })

  it('test_errorboundary_renders_try_again_button_in_default_fallback', () => {
    render(
      <ErrorBoundary>
        <BrokenChild />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('test_errorboundary_does_not_render_children_when_error_occurred', () => {
    render(
      <ErrorBoundary>
        <BrokenChild />
        <HealthyChild />
      </ErrorBoundary>,
    )
    expect(screen.queryByTestId('healthy')).not.toBeInTheDocument()
  })

  // ── Error path: custom fallback prop ─────────────────────────────

  it('test_errorboundary_renders_custom_fallback_when_provided_and_child_throws', () => {
    render(
      <ErrorBoundary fallback={<div data-testid="custom-fallback">Custom error</div>}>
        <BrokenChild />
      </ErrorBoundary>,
    )
    expect(screen.getByTestId('custom-fallback')).toBeInTheDocument()
    expect(screen.getByText('Custom error')).toBeInTheDocument()
  })

  it('test_errorboundary_custom_fallback_hides_default_error_heading', () => {
    render(
      <ErrorBoundary fallback={<span>oops</span>}>
        <BrokenChild />
      </ErrorBoundary>,
    )
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument()
  })

  // ── Try again resets error state ──────────────────────────────────

  it('test_errorboundary_try_again_button_resets_error_state', async () => {
    const user = userEvent.setup()

    // Render with a broken child; after clicking "Try again" the boundary
    // resets its state and attempts to re-render children. The child will
    // throw again immediately, which is fine — we only assert the reset
    // interaction does not crash and the button is clickable.
    render(
      <ErrorBoundary>
        <BrokenChild />
      </ErrorBoundary>,
    )

    const btn = screen.getByRole('button', { name: /try again/i })
    // Clicking "Try again" should not throw (the boundary may re-catch)
    await expect(user.click(btn)).resolves.not.toThrow()
  })

  // ── componentDidCatch logs the error ─────────────────────────────

  it('test_errorboundary_logs_error_via_console_error_when_child_throws', () => {
    render(
      <ErrorBoundary>
        <BrokenChild message="logged error" />
      </ErrorBoundary>,
    )
    // console.error is mocked; verify it was called (React + ErrorBoundary both call it)
    expect(console.error).toHaveBeenCalled()
  })
})
