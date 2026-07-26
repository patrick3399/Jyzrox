import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))
vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}))

const h = vi.hoisted(() => ({
  outline: {
    path: '作品A/參考/大綱.md',
    canonical_path: '作品A/參考/大綱.md',
    nodes: [
      {
        order: 0,
        level: 3,
        title: '第1章：開場',
        line: 1,
        chapter_no: 1,
        preview: '張三抵達城門。',
        beats: [{ title: '第一幕：抵達', line: 4 }],
        chapter_path: '作品A/01.md',
      },
      {
        order: 1,
        level: 3,
        title: '第2章：未寫',
        line: 8,
        chapter_no: 2,
        preview: '構想中。',
        beats: [],
        chapter_path: null,
      },
    ],
  } as {
    path: string | null
    canonical_path: string
    nodes: unknown[]
  },
  fetched: 0,
}))

vi.mock('swr', () => ({
  default: (key: unknown) => {
    if (!key) return { data: undefined }
    h.fetched += 1
    return { data: h.outline }
  },
}))
vi.mock('@/lib/api', () => ({ api: { novels: { outline: vi.fn() } } }))

import { OutlineSection } from '@/components/novels/OutlineSection'

describe('OutlineSection', () => {
  beforeEach(() => {
    h.fetched = 0
    h.outline = {
      path: '作品A/參考/大綱.md',
      canonical_path: '作品A/參考/大綱.md',
      nodes: h.outline.nodes,
    }
  })

  it('does not fetch the outline until the section is opened', async () => {
    render(<OutlineSection work="作品A" />)
    expect(h.fetched).toBe(0)
    expect(screen.queryByTestId('outline-nodes')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /novels.outline/ }))
    expect(h.fetched).toBeGreaterThan(0)
  })

  it('marks each node written or planned and links only the written ones', async () => {
    render(<OutlineSection work="作品A" />)
    await userEvent.click(screen.getByRole('button', { name: /novels.outline/ }))
    expect(screen.getByTestId('outline-state-0')).toHaveTextContent('novels.outlineWritten')
    expect(screen.getByTestId('outline-state-1')).toHaveTextContent('novels.outlinePlanned')
    const written = screen.getByRole('link', { name: '第1章：開場' })
    expect(written).toHaveAttribute('href', expect.stringContaining('01.md'))
    expect(screen.queryByRole('link', { name: '第2章：未寫' })).not.toBeInTheDocument()
    // Beats are shown as the node's scene breakdown.
    expect(screen.getByText('第一幕：抵達')).toBeInTheDocument()
  })

  it('points at the canonical path when the work has no outline file', async () => {
    h.outline = { path: null, canonical_path: '作品A/參考/大綱.md', nodes: [] }
    render(<OutlineSection work="作品A" />)
    await userEvent.click(screen.getByRole('button', { name: /novels.outline/ }))
    expect(screen.getByText(/novels.outlineMissing 作品A\/參考\/大綱.md/)).toBeInTheDocument()
  })
})
