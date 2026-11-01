/**
 * RatingStars — the gallery page's only way to change a personal rating.
 *
 * A rating could be changed but never removed, although the API treats 0 as
 * "delete my rating". Removing one also exposed a stale hover: a tap fires
 * mouseenter but no mouseleave, and the preview outranks the rating.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { RatingStars } from '@/components/RatingStars'

function filledStars(container: HTMLElement) {
  return (container.textContent ?? '').split('').filter((glyph) => glyph === '★').length
}

describe('RatingStars', () => {
  it('sends 0 when the star matching the current rating is clicked again', () => {
    const onChange = vi.fn()
    render(<RatingStars rating={3} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Clear rating' }))

    expect(onChange).toHaveBeenCalledExactlyOnceWith(0)
  })

  it('sends the star value when a star other than the current rating is clicked', () => {
    const onChange = vi.fn()
    render(<RatingStars rating={3} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Rate 5 out of 5' }))

    expect(onChange).toHaveBeenCalledExactlyOnceWith(5)
  })

  it('shows no filled stars after clearing while the tap left a hover behind', () => {
    const { container, rerender } = render(<RatingStars rating={3} onChange={vi.fn()} />)
    const current = screen.getByRole('button', { name: 'Clear rating' })

    // A tap: emulated mouseenter, then click, and never a mouseleave.
    fireEvent.mouseEnter(current)
    fireEvent.click(current)
    rerender(<RatingStars rating={0} onChange={vi.fn()} />)

    expect(filledStars(container)).toBe(0)
  })

  it('still previews the hovered star for a mouse', () => {
    const { container } = render(<RatingStars rating={1} onChange={vi.fn()} />)

    fireEvent.mouseEnter(screen.getByRole('button', { name: 'Rate 4 out of 5' }))

    expect(filledStars(container)).toBe(4)
  })

  it('keeps the same buttons but ignores clicks while disabled', () => {
    const onChange = vi.fn()
    const { rerender } = render(<RatingStars rating={3} onChange={onChange} />)
    const before = screen.getByRole('button', { name: 'Rate 5 out of 5' })

    // Swapping them for read-only spans would change the row's size and drop
    // the mouseleave of the button under the pointer.
    rerender(<RatingStars rating={3} onChange={onChange} disabled />)
    const during = screen.getByRole('button', { name: 'Rate 5 out of 5' })
    fireEvent.click(during)

    expect(during).toBe(before)
    expect(during).toHaveAttribute('aria-disabled', 'true')
    expect(onChange).not.toHaveBeenCalled()
  })
})
