import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <span data-testid="loading-spinner" />,
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const h = vi.hoisted(() => {
  const mockFile = {
    path: '作品A/第01章.md',
    // 1:# / 3:### 幕一 / 5:正文一 [[張三]]。 / 7:### 幕二 / 9:正文二。
    content: '# 第一章\n\n### 幕一\n\n正文一 [[張三]]。\n\n### 幕二\n\n正文二。\n',
    base_sha: 'abc1234',
    acts: [
      { index: 0, title: '幕一', line: 2 },
      { index: 1, title: '幕二', line: 6 },
    ],
    backlinks: ['張三'],
  }
  return { mockFile, writeFile: vi.fn(), mutate: vi.fn() }
})

vi.mock('swr', () => ({
  default: () => ({ data: h.mockFile, isLoading: false }),
  mutate: h.mutate,
}))

vi.mock('@/lib/api', () => ({
  api: {
    novels: {
      readFile: vi.fn().mockResolvedValue(h.mockFile),
      getPrefs: vi.fn().mockResolvedValue({ preferences: {} }),
      putPrefs: vi.fn().mockResolvedValue({ ok: true }),
      getProgress: vi.fn().mockResolvedValue({ position: null }),
      putProgress: vi.fn().mockResolvedValue({ ok: true }),
      writeFile: h.writeFile,
    },
  },
}))

import { Reader } from '@/components/novels/Reader'

describe('Reader authoring (raw toggle + inline block edit)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('toggles between rendered and raw source view', () => {
    render(<Reader path="作品A/第01章.md" />)
    // rendered: the ### markers are gone (heading text only)
    expect(screen.queryByText(/### 幕一/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'novels.viewRaw' }))
    // raw: the literal markdown source is shown verbatim
    expect(screen.getByText(/### 幕一/)).toBeInTheDocument()
  })

  it('inline edit patches only the right-clicked block back into the whole file', async () => {
    h.writeFile.mockResolvedValue({ ok: true, head: 'newsha', pushed: true })
    render(<Reader path="作品A/第01章.md" canEdit />)

    const para = screen.getByText(/正文一/).closest('[data-line-start]') as HTMLElement
    fireEvent.contextMenu(para)

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    expect(textarea.value).toBe('正文一 [[張三]]。')
    fireEvent.change(textarea, { target: { value: '改寫的正文' } })
    fireEvent.click(screen.getByRole('button', { name: 'novels.save' }))

    await waitFor(() => expect(h.writeFile).toHaveBeenCalledTimes(1))
    const body = h.writeFile.mock.calls[0][0]
    expect(body.path).toBe('作品A/第01章.md')
    expect(body.base_sha).toBe('abc1234')
    // patched block replaced, everything else (line 1 heading, 幕二) untouched
    expect(body.content).toContain('改寫的正文')
    expect(body.content).not.toContain('正文一')
    expect(body.content).toContain('### 幕二')
    expect(body.content).toContain('正文二。')
  })

  it('does not show inline edit affordance for non-editors', () => {
    render(<Reader path="作品A/第01章.md" />)
    const para = screen.getByText(/正文一/).closest('[data-line-start]') as HTMLElement
    fireEvent.contextMenu(para)
    // no editor opened
    expect(screen.queryByRole('textbox')).toBeNull()
  })
})
