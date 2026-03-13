import { useState } from 'react'
import { t } from '@/lib/i18n'

interface RatingStarsProps {
  rating: number
  readonly?: boolean
  onChange?: (rating: number) => void
}

export function RatingStars({ rating, readonly = false, onChange }: RatingStarsProps) {
  const [hovered, setHovered] = useState<number | null>(null)

  const displayRating = hovered ?? Math.round(rating)

  return (
    <div
      className="inline-flex items-center gap-0.5"
      role={readonly ? undefined : 'group'}
      aria-label={readonly ? t('common.ratingOf', { rating: String(rating) }) : t('common.setRating')}
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

        return (
          <button
            key={i}
            type="button"
            onClick={() => onChange?.(starIndex)}
            onMouseEnter={() => setHovered(starIndex)}
            onMouseLeave={() => setHovered(null)}
            className={`text-base leading-none transition-colors duration-100 cursor-pointer ${
              isFilled
                ? 'text-yellow-400 hover:text-yellow-300'
                : 'text-vault-text-muted/40 hover:text-yellow-500'
            }`}
            aria-label={t('common.rateN', { n: String(starIndex) })}
          >
            {isFilled ? '★' : '☆'}
          </button>
        )
      })}
    </div>
  )
}
