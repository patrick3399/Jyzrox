'use client'

import { useState, useEffect } from 'react'
import { t } from '@/lib/i18n'
import { Button } from '@/components/ui/button'

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


  return (
    <div className="flex justify-center items-center gap-2 pt-2">
      <Button
        variant="secondary"
        onClick={onFirst}
        disabled={loading || page === 0}
        title={t('common.firstPage')}
      >
        «
      </Button>

      <Button
        variant="secondary"
        onClick={onPrev}
        disabled={loading || !hasPrev}
        title={t('common.previousPage')}
      >
        ‹
      </Button>

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

      <Button
        variant="secondary"
        onClick={onNext}
        disabled={loading || !hasNext}
        title={t('common.nextPage')}
      >
        ›
      </Button>
    </div>
  )
}
