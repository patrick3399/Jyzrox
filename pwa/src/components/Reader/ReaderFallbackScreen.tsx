'use client'

import { useRouter } from 'next/navigation'
import { t } from '@/lib/i18n'

/**
 * Full-screen state shown before `<Reader />` mounts: loading, error, empty.
 *
 * Reader routes have no app chrome and the global swipe-back is disarmed on
 * them, so the only back control would otherwise be the one inside Reader —
 * which is not on screen yet. Every such state carries its own.
 */
export function ReaderFallbackScreen({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  return (
    <div className="relative flex h-screen w-full items-center justify-center bg-black text-white">
      <button
        onClick={() => router.back()}
        title={t('reader.goBack')}
        aria-label={t('reader.goBack')}
        className="absolute left-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-xl"
      >
        ✕
      </button>
      {children}
    </div>
  )
}
