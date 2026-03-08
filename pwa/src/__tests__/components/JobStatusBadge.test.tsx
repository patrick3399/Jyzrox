import { describe, it, expect } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import { JobStatusBadge } from '@/components/JobStatusBadge'
import type { DownloadJob } from '@/lib/types'

type JobStatus = DownloadJob['status']

describe('JobStatusBadge', () => {
  // ── Label text per status ─────────────────────────────────────────

  it('test_jobstatusbadge_queued_renders_queued_label', () => {
    render(<JobStatusBadge status="queued" />)
    expect(screen.getByText('Queued')).toBeInTheDocument()
  })

  it('test_jobstatusbadge_running_renders_running_label', () => {
    render(<JobStatusBadge status="running" />)
    expect(screen.getByText('Running...')).toBeInTheDocument()
  })

  it('test_jobstatusbadge_done_renders_done_label', () => {
    render(<JobStatusBadge status="done" />)
    expect(screen.getByText('Done')).toBeInTheDocument()
  })

  it('test_jobstatusbadge_failed_renders_failed_label', () => {
    render(<JobStatusBadge status="failed" />)
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('test_jobstatusbadge_cancelled_renders_cancelled_label', () => {
    render(<JobStatusBadge status="cancelled" />)
    expect(screen.getByText('Cancelled')).toBeInTheDocument()
  })

  it('test_jobstatusbadge_paused_renders_paused_label', () => {
    render(<JobStatusBadge status="paused" />)
    expect(screen.getByText('Paused')).toBeInTheDocument()
  })

  // ── CSS classes per status ────────────────────────────────────────

  it('test_jobstatusbadge_queued_applies_yellow_classes', () => {
    render(<JobStatusBadge status="queued" />)
    const badge = screen.getByText('Queued')
    expect(badge.className).toContain('bg-yellow-900/50')
    expect(badge.className).toContain('text-yellow-300')
    expect(badge.className).toContain('border-yellow-800')
  })

  it('test_jobstatusbadge_running_applies_blue_and_pulse_classes', () => {
    render(<JobStatusBadge status="running" />)
    const badge = screen.getByText('Running...')
    expect(badge.className).toContain('bg-blue-900/50')
    expect(badge.className).toContain('text-blue-300')
    expect(badge.className).toContain('border-blue-800')
    expect(badge.className).toContain('animate-pulse')
  })

  it('test_jobstatusbadge_done_applies_green_classes', () => {
    render(<JobStatusBadge status="done" />)
    const badge = screen.getByText('Done')
    expect(badge.className).toContain('bg-green-900/50')
    expect(badge.className).toContain('text-green-300')
    expect(badge.className).toContain('border-green-800')
  })

  it('test_jobstatusbadge_failed_applies_red_classes', () => {
    render(<JobStatusBadge status="failed" />)
    const badge = screen.getByText('Failed')
    expect(badge.className).toContain('bg-red-900/50')
    expect(badge.className).toContain('text-red-300')
    expect(badge.className).toContain('border-red-800')
  })

  it('test_jobstatusbadge_cancelled_applies_gray_classes', () => {
    render(<JobStatusBadge status="cancelled" />)
    const badge = screen.getByText('Cancelled')
    expect(badge.className).toContain('bg-gray-800/80')
    expect(badge.className).toContain('text-gray-400')
    expect(badge.className).toContain('border-gray-700')
  })

  it('test_jobstatusbadge_paused_applies_orange_classes', () => {
    render(<JobStatusBadge status="paused" />)
    const badge = screen.getByText('Paused')
    expect(badge.className).toContain('bg-orange-900/50')
    expect(badge.className).toContain('text-orange-300')
    expect(badge.className).toContain('border-orange-800')
  })

  // ── Renders exactly one badge element per call ────────────────────

  it('test_jobstatusbadge_renders_single_span_element', () => {
    const { container } = render(<JobStatusBadge status="done" />)
    expect(container.querySelectorAll('span')).toHaveLength(1)
  })

  // ── All status values covered (parametric safety check) ──────────

  const allStatuses: JobStatus[] = ['queued', 'running', 'done', 'failed', 'cancelled', 'paused']

  it('test_jobstatusbadge_all_statuses_render_without_crashing', () => {
    for (const status of allStatuses) {
      const { unmount } = render(<JobStatusBadge status={status} />)
      unmount()
    }
  })
})
