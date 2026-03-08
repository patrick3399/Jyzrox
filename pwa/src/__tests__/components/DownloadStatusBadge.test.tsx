import { describe, it, expect } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import { DownloadStatusBadge } from '@/components/DownloadStatusBadge'

type DownloadStatus = 'proxy_only' | 'partial' | 'complete'

describe('DownloadStatusBadge', () => {
  // ── Label text per status ─────────────────────────────────────────

  it('test_downloadstatusbadge_complete_renders_local_label', () => {
    render(<DownloadStatusBadge status="complete" />)
    expect(screen.getByText('Local')).toBeInTheDocument()
  })

  it('test_downloadstatusbadge_partial_renders_partial_label', () => {
    render(<DownloadStatusBadge status="partial" />)
    expect(screen.getByText('Partial')).toBeInTheDocument()
  })

  it('test_downloadstatusbadge_proxy_only_renders_proxy_label', () => {
    render(<DownloadStatusBadge status="proxy_only" />)
    expect(screen.getByText('Proxy')).toBeInTheDocument()
  })

  // ── CSS classes per status ────────────────────────────────────────

  it('test_downloadstatusbadge_complete_applies_green_classes', () => {
    render(<DownloadStatusBadge status="complete" />)
    const badge = screen.getByText('Local')
    expect(badge.className).toContain('bg-green-900/50')
    expect(badge.className).toContain('text-green-300')
    expect(badge.className).toContain('border-green-800')
  })

  it('test_downloadstatusbadge_partial_applies_yellow_classes', () => {
    render(<DownloadStatusBadge status="partial" />)
    const badge = screen.getByText('Partial')
    expect(badge.className).toContain('bg-yellow-900/50')
    expect(badge.className).toContain('text-yellow-300')
    expect(badge.className).toContain('border-yellow-800')
  })

  it('test_downloadstatusbadge_proxy_only_applies_blue_classes', () => {
    render(<DownloadStatusBadge status="proxy_only" />)
    const badge = screen.getByText('Proxy')
    expect(badge.className).toContain('bg-blue-900/50')
    expect(badge.className).toContain('text-blue-300')
    expect(badge.className).toContain('border-blue-800')
  })

  // ── Common structural checks ──────────────────────────────────────

  it('test_downloadstatusbadge_renders_single_span_element', () => {
    const { container } = render(<DownloadStatusBadge status="complete" />)
    expect(container.querySelectorAll('span')).toHaveLength(1)
  })

  // ── All status values render without crashing ─────────────────────

  it('test_downloadstatusbadge_all_statuses_render_without_crashing', () => {
    const statuses: DownloadStatus[] = ['complete', 'partial', 'proxy_only']
    for (const status of statuses) {
      const { unmount } = render(<DownloadStatusBadge status={status} />)
      unmount()
    }
  })
})
