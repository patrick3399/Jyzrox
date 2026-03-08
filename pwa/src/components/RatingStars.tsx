import { useState } from 'react'

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
      aria-label={readonly ? `Rating: ${rating} out of 5` : 'Set rating'}
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
            aria-label={`Rate ${starIndex} out of 5`}
          >
            {isFilled ? '★' : '☆'}
          </button>
        )
      })}
    </div>
  )
}
