import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TagBadge } from '@/components/TagBadge'

describe('TagBadge', () => {
  // ── Tag name rendering ─────────────────────────────────────────────

  it('test_tagbadge_no_namespace_renders_plain_name', () => {
    render(<TagBadge tag="schoolgirl" />)
    expect(screen.getByText('schoolgirl')).toBeInTheDocument()
  })

  it('test_tagbadge_with_namespace_renders_name_without_namespace_prefix_in_main_span', () => {
    render(<TagBadge tag="character:reimu" />)
    // The name part is the text after the colon
    expect(screen.getByText('reimu')).toBeInTheDocument()
  })

  it('test_tagbadge_with_namespace_renders_namespace_prefix_separately', () => {
    render(<TagBadge tag="artist:cloba" />)
    expect(screen.getByText('artist:')).toBeInTheDocument()
    expect(screen.getByText('cloba')).toBeInTheDocument()
  })

  it('test_tagbadge_no_namespace_does_not_render_colon_span', () => {
    render(<TagBadge tag="fantasy" />)
    // Without a colon in the tag there should be no "namespace:" prefix span
    expect(screen.queryByText(/:/)).not.toBeInTheDocument()
  })

  // ── Namespace CSS classes ──────────────────────────────────────────

  it('test_tagbadge_character_namespace_applies_purple_classes', () => {
    const { container } = render(<TagBadge tag="character:sakura" />)
    const badge = container.querySelector('span')!
    expect(badge.className).toContain('text-purple-300')
    expect(badge.className).toContain('bg-purple-900/30')
    expect(badge.className).toContain('border-purple-700')
  })

  it('test_tagbadge_artist_namespace_applies_orange_classes', () => {
    const { container } = render(<TagBadge tag="artist:cloba" />)
    const badge = container.querySelector('span')!
    expect(badge.className).toContain('text-orange-300')
    expect(badge.className).toContain('bg-orange-900/30')
    expect(badge.className).toContain('border-orange-700')
  })

  it('test_tagbadge_copyright_namespace_applies_green_classes', () => {
    const { container } = render(<TagBadge tag="copyright:touhou" />)
    const badge = container.querySelector('span')!
    expect(badge.className).toContain('text-green-300')
    expect(badge.className).toContain('bg-green-900/30')
    expect(badge.className).toContain('border-green-700')
  })

  it('test_tagbadge_general_namespace_applies_vault_secondary_classes', () => {
    const { container } = render(<TagBadge tag="general:outdoors" />)
    const badge = container.querySelector('span')!
    expect(badge.className).toContain('text-vault-text-secondary')
    expect(badge.className).toContain('bg-vault-input')
    expect(badge.className).toContain('border-vault-border')
  })

  it('test_tagbadge_unknown_namespace_falls_back_to_general_styles', () => {
    const { container } = render(<TagBadge tag="schoolgirl" />)
    const badge = container.querySelector('span')!
    expect(badge.className).toContain('text-vault-text-secondary')
  })

  // ── Variant CSS classes ────────────────────────────────────────────

  it('test_tagbadge_include_variant_applies_blue_ring', () => {
    const { container } = render(<TagBadge tag="schoolgirl" variant="include" />)
    const badge = container.querySelector('span')!
    expect(badge.className).toContain('ring-1')
    expect(badge.className).toContain('ring-blue-500')
  })

  it('test_tagbadge_exclude_variant_applies_red_ring', () => {
    const { container } = render(<TagBadge tag="schoolgirl" variant="exclude" />)
    const badge = container.querySelector('span')!
    expect(badge.className).toContain('ring-1')
    expect(badge.className).toContain('ring-red-500')
  })

  it('test_tagbadge_exclude_variant_applies_line_through_to_name', () => {
    render(<TagBadge tag="schoolgirl" variant="exclude" />)
    const nameSpan = screen.getByText('schoolgirl')
    expect(nameSpan.className).toContain('line-through')
  })

  it('test_tagbadge_default_variant_applies_no_ring', () => {
    const { container } = render(<TagBadge tag="schoolgirl" variant="default" />)
    const badge = container.querySelector('span')!
    expect(badge.className).not.toContain('ring-')
  })

  // ── onClick behaviour ──────────────────────────────────────────────

  it('test_tagbadge_with_onclick_has_button_role', () => {
    render(<TagBadge tag="schoolgirl" onClick={vi.fn()} />)
    expect(screen.getByRole('button', { name: /schoolgirl/ })).toBeInTheDocument()
  })

  it('test_tagbadge_without_onclick_has_no_button_role', () => {
    render(<TagBadge tag="schoolgirl" />)
    // The outer span should not carry role="button"
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('test_tagbadge_onclick_called_when_clicked', async () => {
    const user = userEvent.setup()
    const handleClick = vi.fn()
    render(<TagBadge tag="schoolgirl" onClick={handleClick} />)
    await user.click(screen.getByRole('button', { name: /schoolgirl/ }))
    expect(handleClick).toHaveBeenCalledOnce()
  })

  it('test_tagbadge_onclick_called_on_enter_keydown', async () => {
    const user = userEvent.setup()
    const handleClick = vi.fn()
    render(<TagBadge tag="schoolgirl" onClick={handleClick} />)
    const btn = screen.getByRole('button', { name: /schoolgirl/ })
    btn.focus()
    await user.keyboard('{Enter}')
    expect(handleClick).toHaveBeenCalledOnce()
  })

  // ── onRemove behaviour ─────────────────────────────────────────────

  it('test_tagbadge_onremove_renders_remove_button', () => {
    render(<TagBadge tag="schoolgirl" onRemove={vi.fn()} />)
    expect(screen.getByRole('button', { name: /Remove tag schoolgirl/ })).toBeInTheDocument()
  })

  it('test_tagbadge_onremove_called_when_remove_button_clicked', async () => {
    const user = userEvent.setup()
    const handleRemove = vi.fn()
    render(<TagBadge tag="schoolgirl" onRemove={handleRemove} />)
    await user.click(screen.getByRole('button', { name: /Remove tag schoolgirl/ }))
    expect(handleRemove).toHaveBeenCalledOnce()
  })

  it('test_tagbadge_without_onremove_does_not_render_remove_button', () => {
    render(<TagBadge tag="schoolgirl" />)
    expect(screen.queryByRole('button', { name: /Remove tag/ })).not.toBeInTheDocument()
  })
})
