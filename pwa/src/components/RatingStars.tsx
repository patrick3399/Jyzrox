import { useState } from 'react'
import { t } from '@/lib/i18n'

interface RatingStarsProps {
  rating: number
  readonly?: boolean
  /** Ignores clicks while a save is in flight; the buttons stay mounted so the row keeps its size. */
  disabled?: boolean
  onChange?: (rating: number) => void
}

export function RatingStars({
  rating,
  readonly = false,
  disabled = false,
  onChange,
}: RatingStarsProps) {
  const [hovered, setHovered] = useState<number | null>(null)

  const currentRating = Math.round(rating)
  const displayRating = hovered ?? currentRating

  return (
    <div
      className={`inline-flex items-center ${readonly ? 'gap-0.5' : ''}`}
      role={readonly ? undefined : 'group'}
      aria-label={
        readonly ? t('common.ratingOf', { rating: String(rating) }) : t('common.setRating')
      }
    >
      {Array.from({ length: 5 }, (_, i) => {
        const starIndex = i + 1
        const isFilled = starIndex <= displayRating

        if (readonly) {
          return (
            <span
              key={i}
              className={`text-base leading-none select-none ${
                isFilled ? 'text-yellow-400' : 'text-vault-text-muted/40'
              }`}
              aria-hidden="true"
            >
              {isFilled ? '★' : '☆'}
            </span>
          )
        }

        const isCurrent = starIndex === currentRating

        return (
          <button
            key={i}
            type="button"
            aria-disabled={disabled || undefined}
            aria-pressed={isCurrent}
            onClick={() => {
              // A tap fires mouseenter but never mouseleave, so drop the preview here.
              setHovered(null)
              if (!disabled) onChange?.(isCurrent ? 0 : starIndex)
            }}
            onMouseEnter={() => setHovered(starIndex)}
            onMouseLeave={() => setHovered(null)}
            className={`inline-flex h-10 w-10 items-center justify-center text-2xl leading-none transition-colors duration-100 md:h-6 md:w-6 md:text-base ${
              disabled ? 'cursor-default opacity-60' : 'cursor-pointer'
            } ${
              isFilled
                ? 'text-yellow-400 hover:text-yellow-300'
                : 'text-vault-text-muted/40 hover:text-yellow-500'
            }`}
            aria-label={
              isCurrent ? t('common.clearRating') : t('common.rateN', { n: String(starIndex) })
            }
          >
            {isFilled ? '★' : '☆'}
          </button>
        )
      })}
    </div>
  )
}
