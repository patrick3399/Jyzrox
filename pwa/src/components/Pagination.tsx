import { ChevronLeft, ChevronRight } from 'lucide-react'
import { t } from '@/lib/i18n'

interface PaginationProps {
  page: number // 0-indexed
  total: number
  pageSize?: number
  onChange: (page: number) => void
}

export function Pagination({ page, total, pageSize = 20, onChange }: PaginationProps) {
  const totalPages = Math.ceil(total / pageSize)

  if (totalPages <= 1) return null

  const start = page * pageSize + 1
  const end = Math.min((page + 1) * pageSize, total)

  const pageNumbers: (number | 'ellipsis-start' | 'ellipsis-end')[] = []
  const WINDOW = 2
  const windowStart = Math.max(0, page - WINDOW)
  const windowEnd = Math.min(totalPages - 1, page + WINDOW)

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
          onClick={() => onChange(page - 1)}
          disabled={page === 0}
          aria-label="Previous page"
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
          return (
            <button
              key={`${item}-${idx}`}
              type="button"
              className={btnPage(item === page)}
              onClick={() => onChange(item)}
              aria-label={`Page ${item + 1}`}
              aria-current={item === page ? 'page' : undefined}
            >
              {item + 1}
            </button>
          )
        })}

        <button
          type="button"
          className={btnNav}
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages - 1}
          aria-label="Next page"
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  )
}
