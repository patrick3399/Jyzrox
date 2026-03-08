import { describe, it, expect } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import { LoadingSpinner, LoadingPage } from '@/components/LoadingSpinner'

describe('LoadingSpinner', () => {
  // ── Basic render ──────────────────────────────────────────────────

  it('test_loadingspinner_renders_without_crashing', () => {
    const { container } = render(<LoadingSpinner />)
    expect(container.firstChild).not.toBeNull()
  })

  it('test_loadingspinner_has_role_status', () => {
    render(<LoadingSpinner />)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('test_loadingspinner_has_loading_aria_label', () => {
    render(<LoadingSpinner />)
    expect(screen.getByLabelText('Loading')).toBeInTheDocument()
  })

  // ── Default size (md) ─────────────────────────────────────────────

  it('test_loadingspinner_default_size_applies_md_classes', () => {
    render(<LoadingSpinner />)
    const spinner = screen.getByRole('status')
    expect(spinner.className).toContain('w-8')
    expect(spinner.className).toContain('h-8')
  })

  // ── Size variants ─────────────────────────────────────────────────

  it('test_loadingspinner_size_sm_applies_sm_classes', () => {
    render(<LoadingSpinner size="sm" />)
    const spinner = screen.getByRole('status')
    expect(spinner.className).toContain('w-4')
    expect(spinner.className).toContain('h-4')
  })

  it('test_loadingspinner_size_lg_applies_lg_classes', () => {
    render(<LoadingSpinner size="lg" />)
    const spinner = screen.getByRole('status')
    expect(spinner.className).toContain('w-12')
    expect(spinner.className).toContain('h-12')
  })

  // ── className passthrough ─────────────────────────────────────────

  it('test_loadingspinner_custom_classname_is_applied', () => {
    render(<LoadingSpinner className="my-custom-class" />)
    const spinner = screen.getByRole('status')
    expect(spinner.className).toContain('my-custom-class')
  })

  // ── Spin animation ────────────────────────────────────────────────

  it('test_loadingspinner_applies_animate_spin_class', () => {
    render(<LoadingSpinner />)
    const spinner = screen.getByRole('status')
    expect(spinner.className).toContain('animate-spin')
  })

  // ── Renders as inline-block ───────────────────────────────────────

  it('test_loadingspinner_applies_inline_block_class', () => {
    render(<LoadingSpinner />)
    const spinner = screen.getByRole('status')
    expect(spinner.className).toContain('inline-block')
  })
})

describe('LoadingPage', () => {
  it('test_loadingpage_renders_without_crashing', () => {
    const { container } = render(<LoadingPage />)
    expect(container.firstChild).not.toBeNull()
  })

  it('test_loadingpage_contains_a_loading_spinner', () => {
    render(<LoadingPage />)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('test_loadingpage_spinner_is_large_size', () => {
    render(<LoadingPage />)
    const spinner = screen.getByRole('status')
    expect(spinner.className).toContain('w-12')
    expect(spinner.className).toContain('h-12')
  })
})
