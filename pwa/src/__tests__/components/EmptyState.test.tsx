import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import { EmptyState } from '@/components/EmptyState'
import type { LucideIcon } from 'lucide-react'

// next/link renders an <a> tag in the jsdom environment.
// No extra mocking needed — the href is tested as-is.

describe('EmptyState', () => {
  // ── Title prop ────────────────────────────────────────────────────

  it('test_emptystate_renders_title_text', () => {
    render(<EmptyState title="Nothing here yet" />)
    expect(screen.getByText('Nothing here yet')).toBeInTheDocument()
  })

  // ── Description prop ──────────────────────────────────────────────

  it('test_emptystate_renders_description_when_provided', () => {
    render(<EmptyState title="Empty" description="Try adding some items." />)
    expect(screen.getByText('Try adding some items.')).toBeInTheDocument()
  })

  it('test_emptystate_does_not_render_description_paragraph_when_omitted', () => {
    render(<EmptyState title="Empty" />)
    // Only the title paragraph should exist; description uses xs/muted class
    const paras = document.querySelectorAll('p')
    // title is the only <p>; there should be exactly one
    expect(paras).toHaveLength(1)
  })

  // ── Action prop ───────────────────────────────────────────────────

  it('test_emptystate_renders_action_link_with_correct_href', () => {
    render(
      <EmptyState
        title="Empty"
        action={{ label: 'Go to library', href: '/library' }}
      />,
    )
    const link = screen.getByRole('link', { name: 'Go to library' })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/library')
  })

  it('test_emptystate_renders_action_link_with_correct_label', () => {
    render(
      <EmptyState
        title="Empty"
        action={{ label: 'Browse now', href: '/browse' }}
      />,
    )
    expect(screen.getByText('Browse now')).toBeInTheDocument()
  })

  it('test_emptystate_does_not_render_link_when_action_omitted', () => {
    render(<EmptyState title="Empty" />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  // ── Icon prop ─────────────────────────────────────────────────────

  it('test_emptystate_renders_icon_container_when_icon_provided', () => {
    // Minimal LucideIcon-compatible stub
    const FakeIcon: LucideIcon = vi.fn().mockImplementation(({ size }: { size: number }) => (
      <svg data-testid="fake-icon" width={size} height={size} />
    )) as unknown as LucideIcon

    render(<EmptyState title="Empty" icon={FakeIcon} />)
    expect(screen.getByTestId('fake-icon')).toBeInTheDocument()
  })

  it('test_emptystate_does_not_render_icon_container_when_icon_omitted', () => {
    render(<EmptyState title="Empty" />)
    // Without icon the icon wrapper div should not be in the DOM
    expect(document.querySelector('.rounded-full')).not.toBeInTheDocument()
  })

  // ── Full props render ─────────────────────────────────────────────

  it('test_emptystate_renders_all_props_together_without_crashing', () => {
    const FakeIcon: LucideIcon = vi.fn().mockImplementation(() => (
      <svg data-testid="icon" />
    )) as unknown as LucideIcon

    render(
      <EmptyState
        title="No results"
        description="Your search returned nothing."
        icon={FakeIcon}
        action={{ label: 'Clear filters', href: '/library' }}
      />,
    )

    expect(screen.getByText('No results')).toBeInTheDocument()
    expect(screen.getByText('Your search returned nothing.')).toBeInTheDocument()
    expect(screen.getByTestId('icon')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Clear filters' })).toBeInTheDocument()
  })
})
