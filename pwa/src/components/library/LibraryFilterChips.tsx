'use client'

import { X } from 'lucide-react'
import { t } from '@/lib/i18n'
import type { LibraryFilterChip, LibraryFilterChipKey } from '@/lib/libraryFilterChips'
import { Button } from '@/components/ui/button'

interface LibraryFilterChipsProps {
  chips: LibraryFilterChip[]
  onRemove: (key: LibraryFilterChipKey) => void
  onClearAll: () => void
}

export function LibraryFilterChips({ chips, onRemove, onClearAll }: LibraryFilterChipsProps) {
  if (chips.length === 0) return null

  return (
    <div className="mt-2 flex items-center gap-2 overflow-x-auto pb-1">
      {chips.map((chip) => (
        <span
          key={chip.key}
          className="flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-vault-accent/30 bg-vault-accent/10 pl-3 pr-1 py-0.5 text-xs text-vault-accent"
        >
          {chip.label}
          <button
            type="button"
            onClick={() => onRemove(chip.key)}
            aria-label={t('library.removeFilter', { name: chip.label })}
            className="flex h-6 w-6 items-center justify-center rounded-full hover:text-red-400 transition-colors"
          >
            <X size={12} />
          </button>
        </span>
      ))}
      {chips.length >= 2 && (
        <Button
          variant="ghost"
          size="sm"
          type="button"
          onClick={onClearAll}
          className="h-auto shrink-0 px-2 py-1 text-xs"
        >
          {t('library.clearAllFilters')}
        </Button>
      )}
    </div>
  )
}
