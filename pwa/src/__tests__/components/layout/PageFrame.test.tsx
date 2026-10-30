import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'

describe('PageContainer', () => {
  it('leaves primary pages unbounded so grid row heights keep their width', () => {
    render(<PageContainer><p>x</p></PageContainer>)
    const root = screen.getByText('x').parentElement
    expect(root?.dataset.pageVariant).toBe('primary')
    expect(root?.className ?? '').not.toMatch(/max-w-|mx-auto|\bp[xy]?-\d/)
  })

  it('bounds secondary pages to max-w-5xl, centred, without adding padding', () => {
    render(<PageContainer variant="secondary"><p>y</p></PageContainer>)
    const root = screen.getByText('y').parentElement
    expect(root?.className).toContain('max-w-5xl')
    expect(root?.className).toContain('mx-auto')
    expect(root?.className ?? '').not.toMatch(/\bp[xy]?-\d/)
  })
})

describe('PageHeader', () => {
  it('renders one h1 that is xl on phones and 2xl from sm', () => {
    render(<PageHeader title="Trash" />)
    const h1 = screen.getByRole('heading', { level: 1, name: 'Trash' })
    expect(h1.className).toContain('text-xl')
    expect(h1.className).toContain('sm:text-2xl')
    expect(h1.className).toContain('font-bold')
  })

  it('uses mb-4/sm:mb-6 by default, mb-2 when dense, and no margin when none', () => {
    const { container, rerender } = render(<PageHeader title="A" />)
    const cls = () => container.querySelector('header')?.className ?? ''
    expect(cls()).toMatch(/\bmb-4\b/)
    expect(cls()).toContain('sm:mb-6')
    rerender(<PageHeader title="A" spacing="dense" />)
    expect(cls()).toContain('mb-2')
    expect(cls()).not.toContain('mb-4')
    rerender(<PageHeader title="A" spacing="none" />)
    expect(cls()).not.toMatch(/\bmb-|sm:mb-/)
  })

  it('test_page_header_actions_wrap_instead_of_overflowing_on_narrow_screens', () => {
    const { container } = render(<PageHeader title="A" actions={<button>Go</button>} />)
    expect(container.querySelector('header')?.className).toContain('flex-wrap')
    const actions = screen.getByRole('button', { name: 'Go' }).parentElement
    expect(actions?.className).toContain('flex-wrap')
    expect(actions?.className).not.toContain('shrink-0')
  })

  it('renders subtitle, meta and actions', () => {
    render(<PageHeader title="Library" meta={<span>12 galleries</span>} subtitle="sub" actions={<button>Go</button>} />)
    expect(screen.getByText('12 galleries')).toBeTruthy()
    expect(screen.getByText('sub')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Go' })).toBeTruthy()
  })
})
