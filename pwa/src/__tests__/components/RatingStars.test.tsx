import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RatingStars } from '@/components/RatingStars'

// The component renders ★ for filled stars and ☆ for empty ones.
// All star characters are aria-hidden in readonly mode; in interactive mode
// each star is a button with aria-label "Rate N out of 5".

describe('RatingStars', () => {
  // ── Readonly mode ─────────────────────────────────────────────────

  it('test_ratingstars_readonly_rating_zero_renders_five_empty_stars', () => {
    render(<RatingStars rating={0} readonly />)
    const stars = screen.getAllByText(/[★☆]/)
    expect(stars.filter((s) => s.textContent === '☆')).toHaveLength(5)
    expect(stars.filter((s) => s.textContent === '★')).toHaveLength(0)
  })

  it('test_ratingstars_readonly_rating_three_renders_three_filled_two_empty', () => {
    render(<RatingStars rating={3} readonly />)
    const stars = screen.getAllByText(/[★☆]/)
    expect(stars.filter((s) => s.textContent === '★')).toHaveLength(3)
    expect(stars.filter((s) => s.textContent === '☆')).toHaveLength(2)
  })

  it('test_ratingstars_readonly_rating_five_renders_five_filled_stars', () => {
    render(<RatingStars rating={5} readonly />)
    const stars = screen.getAllByText(/[★☆]/)
    expect(stars.filter((s) => s.textContent === '★')).toHaveLength(5)
    expect(stars.filter((s) => s.textContent === '☆')).toHaveLength(0)
  })

  it('test_ratingstars_readonly_fractional_rating_rounds_to_nearest', () => {
    // rating 3.7 → Math.round → 4 filled stars
    render(<RatingStars rating={3.7} readonly />)
    const stars = screen.getAllByText(/[★☆]/)
    expect(stars.filter((s) => s.textContent === '★')).toHaveLength(4)
  })

  it('test_ratingstars_readonly_has_accessible_aria_label', () => {
    render(<RatingStars rating={3} readonly />)
    expect(screen.getByLabelText('Rating: 3 out of 5')).toBeInTheDocument()
  })

  it('test_ratingstars_readonly_renders_no_buttons', () => {
    render(<RatingStars rating={3} readonly />)
    expect(screen.queryAllByRole('button')).toHaveLength(0)
  })

  // ── Interactive mode ──────────────────────────────────────────────

  it('test_ratingstars_interactive_renders_five_buttons', () => {
    render(<RatingStars rating={0} onChange={vi.fn()} />)
    expect(screen.getAllByRole('button')).toHaveLength(5)
  })

  it('test_ratingstars_interactive_buttons_have_correct_aria_labels', () => {
    render(<RatingStars rating={0} onChange={vi.fn()} />)
    for (let i = 1; i <= 5; i++) {
      expect(screen.getByLabelText(`Rate ${i} out of 5`)).toBeInTheDocument()
    }
  })

  it('test_ratingstars_interactive_group_has_set_rating_aria_label', () => {
    render(<RatingStars rating={2} onChange={vi.fn()} />)
    expect(screen.getByRole('group', { name: 'Set rating' })).toBeInTheDocument()
  })

  it('test_ratingstars_interactive_onclick_calls_onchange_with_star_index', async () => {
    const user = userEvent.setup()
    const handleChange = vi.fn()
    render(<RatingStars rating={0} onChange={handleChange} />)
    await user.click(screen.getByLabelText('Rate 3 out of 5'))
    expect(handleChange).toHaveBeenCalledOnce()
    expect(handleChange).toHaveBeenCalledWith(3)
  })

  it('test_ratingstars_interactive_clicking_first_star_calls_onchange_with_one', async () => {
    const user = userEvent.setup()
    const handleChange = vi.fn()
    render(<RatingStars rating={4} onChange={handleChange} />)
    await user.click(screen.getByLabelText('Rate 1 out of 5'))
    expect(handleChange).toHaveBeenCalledWith(1)
  })

  it('test_ratingstars_interactive_clicking_fifth_star_calls_onchange_with_five', async () => {
    const user = userEvent.setup()
    const handleChange = vi.fn()
    render(<RatingStars rating={0} onChange={handleChange} />)
    await user.click(screen.getByLabelText('Rate 5 out of 5'))
    expect(handleChange).toHaveBeenCalledWith(5)
  })

  it('test_ratingstars_interactive_no_onchange_does_not_throw_on_click', async () => {
    const user = userEvent.setup()
    // onChange is optional; clicking without it should not throw
    render(<RatingStars rating={2} />)
    await expect(user.click(screen.getByLabelText('Rate 3 out of 5'))).resolves.not.toThrow()
  })

  it('test_ratingstars_interactive_displays_correct_filled_stars_for_rating', () => {
    render(<RatingStars rating={2} onChange={vi.fn()} />)
    const buttons = screen.getAllByRole('button')
    const filledCount = buttons.filter((b) => b.textContent === '★').length
    const emptyCount = buttons.filter((b) => b.textContent === '☆').length
    expect(filledCount).toBe(2)
    expect(emptyCount).toBe(3)
  })
})
