import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

import { MarkdownView, blankFrontmatter } from '@/components/novels/MarkdownView'

// 1:# 第一章 / 3:### 幕一 / 5:正文一 [[張三]]。 / 7:**粗體** / 9-10:list / 12:--- / 14:正文二
const CONTENT =
  '# 第一章\n\n### 幕一\n\n正文一 [[張三]]。\n\n**粗體** 文字\n\n- 一\n- 二\n\n---\n\n正文二\n'
const ACTS = [{ index: 0, title: '幕一', line: 2 }]

describe('MarkdownView', () => {
  it('renders real markdown: bold, list, and horizontal rule', () => {
    const { container } = render(<MarkdownView content={CONTENT} acts={ACTS} />)
    expect(container.querySelector('strong')?.textContent).toBe('粗體')
    expect(container.querySelectorAll('ul li')).toHaveLength(2)
    expect(container.querySelector('hr')).not.toBeNull()
  })

  it('gives ### 幕 headings an act-{index} anchor for TOC/progress', () => {
    const { container } = render(<MarkdownView content={CONTENT} acts={ACTS} />)
    const anchor = container.querySelector('#act-0')
    expect(anchor).not.toBeNull()
    expect(anchor?.textContent).toBe('幕一')
  })

  it('renders [[wikilink]] as a highlighted span', () => {
    const { container } = render(<MarkdownView content={CONTENT} acts={ACTS} />)
    const link = container.querySelector('[data-wikilink="張三"]')
    expect(link).not.toBeNull()
    expect(link?.textContent).toBe('張三')
  })

  it('tags every top-level block with its source line range', () => {
    render(<MarkdownView content={CONTENT} acts={ACTS} />)
    // the wikilink paragraph is source line 5
    const para = screen.getByText(/正文一/).closest('[data-line-start]') as HTMLElement
    expect(para.dataset.lineStart).toBe('5')
    expect(para.dataset.lineEnd).toBe('5')
  })

  it('right-click on a block requests edit for that exact source range (editable)', () => {
    const onRequestEdit = vi.fn()
    render(
      <MarkdownView
        content={CONTENT}
        acts={ACTS}
        editable
        path="作品A/第01章.md"
        baseSha="abc1234"
        onRequestEdit={onRequestEdit}
      />,
    )
    const para = screen.getByText(/正文一/).closest('[data-line-start]') as HTMLElement
    fireEvent.contextMenu(para)
    expect(onRequestEdit).toHaveBeenCalledWith({ start: 5, end: 5 })
  })

  it('does not intercept right-click when not editable', () => {
    const onRequestEdit = vi.fn()
    render(<MarkdownView content={CONTENT} acts={ACTS} onRequestEdit={onRequestEdit} />)
    const para = screen.getByText(/正文一/).closest('[data-line-start]') as HTMLElement
    fireEvent.contextMenu(para)
    expect(onRequestEdit).not.toHaveBeenCalled()
  })

  it('renders an in-place editor seeded with the block source when editing', () => {
    render(
      <MarkdownView
        content={CONTENT}
        acts={ACTS}
        editable
        path="作品A/第01章.md"
        baseSha="abc1234"
        editingRange={{ start: 5, end: 5 }}
      />,
    )
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    expect(textarea.value).toBe('正文一 [[張三]]。')
  })

  it('does not render leading frontmatter as a rule plus a stray heading', () => {
    const withFm = '---\nsummary: 張三離開\n---\n\n' + CONTENT
    const { container } = render(<MarkdownView content={withFm} acts={[]} />)
    expect(container.textContent).not.toContain('summary')
    // The one hr in the body is still rendered; the fence adds none.
    expect(container.querySelectorAll('hr')).toHaveLength(1)
  })

  it('keeps source line numbers pointing at the real file when frontmatter is present', () => {
    // 4 frontmatter lines shift every block down by 4: 正文一 moves 5 → 9.
    const withFm = '---\nsummary: 張三離開\n---\n\n' + CONTENT
    render(<MarkdownView content={withFm} acts={[]} />)
    const para = screen.getByText(/正文一/).closest('[data-line-start]') as HTMLElement
    expect(para.dataset.lineStart).toBe('9')
  })

  it('seeds the block editor from the real file, frontmatter offset included', () => {
    const withFm = '---\nsummary: 張三離開\n---\n\n' + CONTENT
    render(
      <MarkdownView
        content={withFm}
        acts={[]}
        editable
        path="作品A/第01章.md"
        baseSha="abc1234"
        editingRange={{ start: 9, end: 9 }}
      />,
    )
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('正文一 [[張三]]。')
  })

  it('blankFrontmatter preserves the line count so ranges never drift', () => {
    expect(blankFrontmatter('---\na: 1\nb: 2\n---\n\n本文\n')).toBe('\n\n\n\n\n本文\n')
    // No fence, or an unterminated one, is left completely alone.
    expect(blankFrontmatter('本文\n')).toBe('本文\n')
    expect(blankFrontmatter('---\na: 1\n本文\n')).toBe('---\na: 1\n本文\n')
  })
})
