/**
 * Pagination — Vitest test suite
 *
 * Covers:
 *   - Returns null when totalPages <= 1
 *   - Renders page buttons for small page count
 *   - Renders showing range text
 *   - Current page has aria-current="page"
 *   - Previous button disabled on first page
 *   - Next button disabled on last page
 *   - Clicking a page number calls onChange
 *   - Clicking previous/next calls onChange with adjacent page
 *   - Disabled state on both nav buttons when isLoading
 *   - Ellipsis rendered for large page counts
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) => {
    if (params) return `${key}(${Object.values(params).join(',')})`
    return key
  },
}))

// ── Import component after mocks ───────────────────────────────────────

import { Pagination } from '@/components/Pagination'

// ── Setup ──────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

// ── Tests ──────────────────────────────────────────────────────────────

describe('Pagination', () => {
  describe('rendering guard', () => {
    it('test_pagination_singlePage_rendersNull', () => {
      const { container } = render(
        <Pagination page={0} total={10} pageSize={20} onChange={vi.fn()} />,
      )
      // totalPages = ceil(10/20) = 1 => returns null
      expect(container.firstChild).toBeNull()
    })

    it('test_pagination_zeroTotal_rendersNull', () => {
      const { container } = render(
        <Pagination page={0} total={0} pageSize={20} onChange={vi.fn()} />,
      )
      expect(container.firstChild).toBeNull()
    })

    it('test_pagination_exactlyOnePage_rendersNull', () => {
      const { container } = render(
        <Pagination page={0} total={20} pageSize={20} onChange={vi.fn()} />,
      )
      expect(container.firstChild).toBeNull()
    })

    it('test_pagination_twoPagesTotal_renders', () => {
      const { container } = render(
        <Pagination page={0} total={21} pageSize={20} onChange={vi.fn()} />,
      )
      expect(container.firstChild).not.toBeNull()
    })
  })

  describe('showing range text', () => {
    it('test_pagination_firstPage_showsCorrectRange', () => {
      render(<Pagination page={0} total={50} pageSize={20} onChange={vi.fn()} />)
      // The range text paragraph contains "start – end of total"
      const p = document.querySelector('p.text-xs') as HTMLElement
      expect(p).not.toBeNull()
      expect(p.textContent).toContain('1')
      expect(p.textContent).toContain('20')
      expect(p.textContent).toContain('50')
    })

    it('test_pagination_lastPage_showsCorrectRangeEnd', () => {
      // page=2 (0-indexed), total=50, pageSize=20 => start=41, end=50
      render(<Pagination page={2} total={50} pageSize={20} onChange={vi.fn()} />)
      const p = document.querySelector('p.text-xs') as HTMLElement
      expect(p).not.toBeNull()
      expect(p.textContent).toContain('41')
      expect(p.textContent).toContain('50')
    })
  })

  describe('page buttons', () => {
    it('test_pagination_firstPage_hasAriaCurrentPage', () => {
      render(<Pagination page={0} total={60} pageSize={20} onChange={vi.fn()} />)
      // Page 1 button (0-indexed = page 0) should have aria-current="page"
      const page1Btn = screen.getByRole('button', { name: /browse\.pageN\(1\)/i })
      expect(page1Btn).toHaveAttribute('aria-current', 'page')
    })

    it('test_pagination_secondPage_secondButtonHasAriaCurrentPage', () => {
      render(<Pagination page={1} total={60} pageSize={20} onChange={vi.fn()} />)
      const page2Btn = screen.getByRole('button', { name: /browse\.pageN\(2\)/i })
      expect(page2Btn).toHaveAttribute('aria-current', 'page')
    })

    it('test_pagination_withThreePages_rendersAllThreePageButtons', () => {
      render(<Pagination page={0} total={60} pageSize={20} onChange={vi.fn()} />)
      // WINDOW=2 so all 3 pages are in window
      expect(screen.getByRole('button', { name: /browse\.pageN\(1\)/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /browse\.pageN\(2\)/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /browse\.pageN\(3\)/i })).toBeInTheDocument()
    })
  })

  describe('navigation buttons', () => {
    it('test_pagination_firstPage_previousButtonDisabled', () => {
      render(<Pagination page={0} total={60} pageSize={20} onChange={vi.fn()} />)
      const prevBtn = screen.getByRole('button', { name: 'common.previousPage' })
      expect(prevBtn).toBeDisabled()
    })

    it('test_pagination_lastPage_nextButtonDisabled', () => {
      render(<Pagination page={2} total={60} pageSize={20} onChange={vi.fn()} />)
      const nextBtn = screen.getByRole('button', { name: 'common.nextPage' })
      expect(nextBtn).toBeDisabled()
    })

    it('test_pagination_middlePage_bothNavButtonsEnabled', () => {
      render(<Pagination page={1} total={60} pageSize={20} onChange={vi.fn()} />)
      const prevBtn = screen.getByRole('button', { name: 'common.previousPage' })
      const nextBtn = screen.getByRole('button', { name: 'common.nextPage' })
      expect(prevBtn).not.toBeDisabled()
      expect(nextBtn).not.toBeDisabled()
    })
  })

  describe('onChange callbacks', () => {
    it('test_pagination_clickNextButton_callsOnChangeWithNextPage', () => {
      const onChange = vi.fn()
      render(<Pagination page={0} total={60} pageSize={20} onChange={onChange} />)
      const nextBtn = screen.getByRole('button', { name: 'common.nextPage' })
      fireEvent.click(nextBtn)
      expect(onChange).toHaveBeenCalledWith(1)
    })

    it('test_pagination_clickPreviousButton_callsOnChangeWithPreviousPage', () => {
      const onChange = vi.fn()
      render(<Pagination page={2} total={60} pageSize={20} onChange={onChange} />)
      const prevBtn = screen.getByRole('button', { name: 'common.previousPage' })
      fireEvent.click(prevBtn)
      expect(onChange).toHaveBeenCalledWith(1)
    })

    it('test_pagination_clickPageButton_callsOnChangeWithPageIndex', () => {
      const onChange = vi.fn()
      render(<Pagination page={0} total={60} pageSize={20} onChange={onChange} />)
      const page2Btn = screen.getByRole('button', { name: /browse\.pageN\(2\)/i })
      fireEvent.click(page2Btn)
      expect(onChange).toHaveBeenCalledWith(1)
    })
  })

  describe('loading state', () => {
    it('test_pagination_isLoading_allPageButtonsDisabled', () => {
      render(<Pagination page={1} total={60} pageSize={20} onChange={vi.fn()} isLoading={true} />)
      const prevBtn = screen.getByRole('button', { name: 'common.previousPage' })
      const nextBtn = screen.getByRole('button', { name: 'common.nextPage' })
      expect(prevBtn).toBeDisabled()
      expect(nextBtn).toBeDisabled()
    })
  })

  describe('ellipsis for large page counts', () => {
    it('test_pagination_manyPages_rendersEllipsis', () => {
      // 200 total, 20 per page = 10 pages; page 0, window covers 0-2, so pages 4-9 need ellipsis
      render(<Pagination page={0} total={200} pageSize={20} onChange={vi.fn()} />)
      expect(screen.getByText('…')).toBeInTheDocument()
    })

    it('test_pagination_manyPages_rendersLastPageButton', () => {
      render(<Pagination page={0} total={200} pageSize={20} onChange={vi.fn()} />)
      // Last page is page 10 (1-indexed), 0-indexed page 9
      expect(screen.getByRole('button', { name: /browse\.pageN\(10\)/i })).toBeInTheDocument()
    })
  })
})
