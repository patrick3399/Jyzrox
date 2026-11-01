'use client'

import { useRouter } from 'next/navigation'
import { t } from '@/lib/i18n'
import { smartBack } from '@/lib/navBack'

/**
 * Full-screen state shown before `<Reader />` mounts: loading, error, empty.
 *
 * Reader routes have no app chrome and the global swipe-back is disarmed on
 * them, so the only back control would otherwise be the one inside Reader —
 * which is not on screen yet. Every such state carries its own.
 *
 * The control resolves through `smartBack` like Reader's own exits: with a
 * one-entry history (share link, new tab, PWA relaunch) a bare `router.back()`
 * does nothing and would leave the user stuck here.
 */
export function ReaderFallbackScreen({
  children,
  backHref,
}: {
  children: React.ReactNode
  backHref: string
}) {
  const router = useRouter()
  return (
    <div className="relative flex h-screen w-full items-center justify-center bg-black text-white">
      <button
        onClick={() => smartBack(router, backHref)}
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
