import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <span data-testid="loading-spinner" />,
}))

const h = vi.hoisted(() => {
  const mockFile = {
    path: '作品A/第01章.md',
    content: '# 第一章\n\n### 幕一\n\n正文一 [[張三]]。\n\n### 幕二\n\n正文二。\n',
    base_sha: 'abc1234',
    acts: [
      { index: 0, title: '幕一', line: 2 },
      { index: 1, title: '幕二', line: 6 },
    ],
    backlinks: ['張三'],
  }
  return { mockFile, putProgress: vi.fn(), putPrefs: vi.fn() }
})
const { putProgress, putPrefs } = h

vi.mock('swr', () => ({
  default: () => ({ data: h.mockFile, isLoading: false }),
}))

vi.mock('@/lib/api', () => ({
  api: {
    novels: {
      readFile: vi.fn().mockResolvedValue(h.mockFile),
      getPrefs: vi.fn().mockResolvedValue({ preferences: {} }),
      putPrefs: h.putPrefs.mockResolvedValue({ ok: true }),
      getProgress: vi.fn().mockResolvedValue({ position: null }),
      putProgress: h.putProgress.mockResolvedValue({ ok: true }),
    },
  },
}))

import { Reader } from '@/components/novels/Reader'

describe('Reader', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders chapter content and act TOC', () => {
    render(<Reader path="作品A/第01章.md" />)
    expect(screen.getByText(/正文一/)).toBeInTheDocument()
    // act headings become anchors in the TOC (there are 2 acts)
    const toc = screen.getByRole('navigation', { name: 'novels.tableOfContents' })
    expect(toc).toBeInTheDocument()
  })

  it('changing font size updates the rendered size and persists', () => {
    render(<Reader path="作品A/第01章.md" />)
    const before = screen.getByTestId('reader-font-size').textContent
    fireEvent.click(screen.getByRole('button', { name: 'novels.fontSize +' }))
    const after = screen.getByTestId('reader-font-size').textContent
    expect(Number(after)).toBe(Number(before) + 1)
    expect(putPrefs).toHaveBeenCalled()
  })

  it('switching theme updates the reader data-theme attribute', () => {
    render(<Reader path="作品A/第01章.md" />)
    fireEvent.click(screen.getByRole('button', { name: 'novels.themeLight' }))
    expect(screen.getByTestId('reader-content').getAttribute('data-theme')).toBe('light')
  })

  it('scrolling reports progress after debounce', () => {
    render(<Reader path="作品A/第01章.md" />)
    act(() => {
      window.dispatchEvent(new Event('scroll'))
      vi.advanceTimersByTime(1000)
    })
    expect(putProgress).toHaveBeenCalledWith('作品A/第01章.md', expect.stringContaining('act:'))
  })
})
