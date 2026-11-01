import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

import { MediaPolicyFields } from '@/components/download/MediaPolicyFields'
import type { MediaPolicy } from '@/lib/types'

const DEFAULT: MediaPolicy = { max_files: null, include_videos: true }

describe('MediaPolicyFields', () => {
  const onChange = vi.fn()

  beforeEach(() => {
    onChange.mockClear()
  })

  it('MediaPolicyFields_does_not_emit_invalid_max_files', () => {
    render(<MediaPolicyFields value={DEFAULT} onChange={onChange} />)
    const input = screen.getByLabelText('mediaPolicy.maxFiles')

    for (const bad of ['0', '-1', '1.5', '100001']) {
      fireEvent.change(input, { target: { value: bad } })
    }

    expect(onChange).not.toHaveBeenCalled()
  })

  it('MediaPolicyFields_shows_inline_error_when_max_files_is_zero', () => {
    render(<MediaPolicyFields value={DEFAULT} onChange={onChange} />)

    fireEvent.change(screen.getByLabelText('mediaPolicy.maxFiles'), { target: { value: '0' } })

    expect(screen.getByRole('alert').textContent).toBe('mediaPolicy.invalidMaxFiles')
  })

  it('MediaPolicyFields_valid_max_files_emits_number_and_keeps_include_videos', () => {
    const value: MediaPolicy = { max_files: null, include_videos: false }
    render(<MediaPolicyFields value={value} onChange={onChange} />)

    fireEvent.change(screen.getByLabelText('mediaPolicy.maxFiles'), { target: { value: '200' } })

    expect(onChange).toHaveBeenCalledWith({ max_files: 200, include_videos: false })
  })

  it('MediaPolicyFields_clearing_max_files_emits_null', () => {
    render(
      <MediaPolicyFields value={{ max_files: 20, include_videos: true }} onChange={onChange} />,
    )

    fireEvent.change(screen.getByLabelText('mediaPolicy.maxFiles'), { target: { value: '' } })

    expect(onChange).toHaveBeenCalledWith({ max_files: null, include_videos: true })
  })

  it('MediaPolicyFields_toggling_checkbox_emits_include_videos_flipped', () => {
    render(
      <MediaPolicyFields value={{ max_files: 20, include_videos: true }} onChange={onChange} />,
    )

    fireEvent.click(screen.getByLabelText('mediaPolicy.includeVideos'))

    expect(onChange).toHaveBeenCalledWith({ max_files: 20, include_videos: false })
  })

  it('MediaPolicyFields_disabled_disables_both_controls', () => {
    render(<MediaPolicyFields value={DEFAULT} onChange={onChange} disabled />)

    expect((screen.getByLabelText('mediaPolicy.maxFiles') as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByLabelText('mediaPolicy.includeVideos') as HTMLInputElement).disabled).toBe(
      true,
    )
  })
})
