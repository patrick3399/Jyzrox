'use client'

import { useState, useEffect } from 'react'
import { t } from '@/lib/i18n'

interface PaginatorProps {
  page: number
  hasNext: boolean
  hasPrev: boolean
  onFirst: () => void
  onPrev: () => void
  onNext: () => void
  onJump?: (page: number) => void
  loading?: boolean
}

export default function Paginator({
  page,
  hasNext,
  hasPrev,
  onFirst,
  onPrev,
  onNext,
  onJump,
  loading = false,
}: PaginatorProps) {
  const [inputValue, setInputValue] = useState(String(page + 1))

  useEffect(() => {
    setInputValue(String(page + 1))
  }, [page])

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      const parsed = parseInt(inputValue, 10)
      if (!isNaN(parsed) && parsed >= 1) {
        onJump!(parsed - 1)
      } else {
        setInputValue(String(page + 1))
      }
    }
  }

  function handleBlur() {
    setInputValue(String(page + 1))
  }

  const btnClass =
    'px-3 py-2 rounded-lg bg-vault-card border border-vault-border text-sm ' +
    'disabled:opacity-30 disabled:cursor-not-allowed hover:border-vault-accent transition-colors'

  return (
    <div className="flex justify-center items-center gap-2 pt-2">
      <button
        onClick={onFirst}
        disabled={loading || page === 0}
        title={t('common.firstPage')}
        className={btnClass}
      >
        «
      </button>

      <button
        onClick={onPrev}
        disabled={loading || !hasPrev}
        title={t('common.previousPage')}
        className={btnClass}
      >
        ‹
      </button>

      {onJump ? (
        <input
          type="number"
          min={1}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={handleBlur}
          disabled={loading}
          className={
            'w-14 text-center bg-vault-card border border-vault-border rounded-lg py-2 text-sm text-vault-text ' +
            'focus:outline-none focus:border-vault-accent [appearance:textfield] ' +
            '[&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none'
          }
        />
      ) : (
        <span className="inline-flex items-center justify-center w-14 text-center py-2 text-sm text-vault-text-muted">
          {page + 1}
        </span>
      )}

      <button
        onClick={onNext}
        disabled={loading || !hasNext}
        title={t('common.nextPage')}
        className={btnClass}
      >
        ›
      </button>
    </div>
  )
}
