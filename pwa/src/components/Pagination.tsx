import { useState, useEffect } from 'react'
import { ChevronLeft, ChevronRight, Loader2 } from 'lucide-react'
import { t } from '@/lib/i18n'

interface PaginationProps {
  page: number // 0-indexed (confirmed/committed page from data)
  total: number
  pageSize?: number
  onChange: (page: number) => void
  isLoading?: boolean
}

export function Pagination({
  page,
  total,
  pageSize = 20,
  onChange,
  isLoading = false,
}: PaginationProps) {
  const totalPages = Math.ceil(total / pageSize)

  // Optimistic display page: immediately reflects the clicked page before data arrives
  const [displayPage, setDisplayPage] = useState(page)

  // Sync displayPage back when confirmed page changes (e.g. external navigation)
  useEffect(() => {
    setDisplayPage(page)
  }, [page])

  if (totalPages <= 1) return null

  const activePage = displayPage
  const start = page * pageSize + 1
  const end = Math.min((page + 1) * pageSize, total)

  const pageNumbers: (number | 'ellipsis-start' | 'ellipsis-end')[] = []
  const WINDOW = 2
  const windowStart = Math.max(0, activePage - WINDOW)
  const windowEnd = Math.min(totalPages - 1, activePage + WINDOW)

  if (windowStart > 0) {
    pageNumbers.push(0)
    if (windowStart > 1) pageNumbers.push('ellipsis-start')
  }
  for (let i = windowStart; i <= windowEnd; i++) pageNumbers.push(i)
  if (windowEnd < totalPages - 1) {
    if (windowEnd < totalPages - 2) pageNumbers.push('ellipsis-end')
    pageNumbers.push(totalPages - 1)
  }

  const btnBase =
    'min-w-[2rem] h-8 px-2 rounded-lg text-sm font-medium transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed'

  const btnPage = (isActive: boolean) =>
    `${btnBase} ${
      isActive
        ? 'bg-vault-accent text-white'
        : 'bg-vault-card text-vault-text-secondary border border-vault-border hover:border-vault-accent hover:text-vault-text'
    }`

  const btnNav = `${btnBase} bg-vault-card text-vault-text-secondary border border-vault-border hover:border-vault-accent hover:text-vault-text`

  const handlePageClick = (p: number) => {
    setDisplayPage(p)
    onChange(p)
  }

  return (
    <div className="flex flex-col items-center gap-3 py-4">
      <p className="text-xs text-vault-text-muted">
        {t('common.showing')} <span className="text-vault-text-secondary">{start}</span>
        {' – '}
        <span className="text-vault-text-secondary">{end}</span> {t('common.of')}{' '}
        <span className="text-vault-text-secondary">{total}</span>
      </p>

      <div className="flex items-center gap-1">
        <button
          type="button"
          className={btnNav}
          onClick={() => handlePageClick(activePage - 1)}
          disabled={isLoading || activePage === 0}
          aria-label={t('common.previousPage')}
        >
          <ChevronLeft size={16} />
        </button>

        {pageNumbers.map((item, idx) => {
          if (item === 'ellipsis-start' || item === 'ellipsis-end') {
            return (
              <span key={item} className="px-1 text-vault-text-muted select-none">
                …
              </span>
            )
          }
          const isActive = item === activePage
          const isLoadingActive = isActive && isLoading
          return (
            <button
              key={`${item}-${idx}`}
              type="button"
              className={`${btnPage(isActive)} ${isLoadingActive ? 'opacity-80' : ''}`}
              onClick={() => handlePageClick(item)}
              disabled={isLoading}
              aria-label={t('browse.pageN', { page: String(item + 1) })}
              aria-current={isActive ? 'page' : undefined}
              aria-busy={isLoadingActive}
            >
              {isLoadingActive ? <Loader2 size={14} className="animate-spin" /> : item + 1}
            </button>
          )
        })}

        <button
          type="button"
          className={btnNav}
          onClick={() => handlePageClick(activePage + 1)}
          disabled={isLoading || activePage >= totalPages - 1}
          aria-label={t('common.nextPage')}
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  )
}
