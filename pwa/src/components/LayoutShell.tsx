'use client'

import { useState, useCallback, Suspense } from 'react'
import { usePathname } from 'next/navigation'
import { Sidebar } from './Sidebar'
import { NavMemoryTracker } from './NavMemoryTracker'
import { MobileNav } from './MobileNav'
import { BottomTabBar } from './BottomTabBar'
import { Toaster } from 'sonner'
import { SWUpdatePrompt } from './SWUpdatePrompt'
import { FloatingActions } from './FloatingActions'
import { WsProvider } from '@/lib/ws'
import { WsInvalidationBridge } from '@/lib/wsInvalidation'
import { useSwipeBack } from '@/hooks/useSwipeBack'
import { isReaderPath } from '@/lib/readerRoutes'
import { useDownloadStats } from '@/hooks/useDownloadQueue'
import { useLocale } from '@/components/LocaleProvider'
import { UiPreferencesSync } from '@/components/UiPreferencesSync'

const AUTH_PATHS = ['/login', '/setup']
const PUBLIC_PATH_PREFIXES = ['/share/']

export function LayoutShell({ children }: { children: React.ReactNode }) {
  // Subscribe at the shell boundary so legacy direct t() call sites refresh.
  // The locale value can stay unchanged while its lazy dictionary finishes
  // loading, so dictionaryVersion must also invalidate the shell.
  const { locale, dictionaryVersion } = useLocale()
  const pathname = usePathname()
  const isAuth = AUTH_PATHS.includes(pathname)
  const isPublic = PUBLIC_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix))
  const isReader = isReaderPath(pathname)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const handleDrawerClose = useCallback(() => setDrawerOpen(false), [])
  const handleDrawerOpen = useCallback(() => setDrawerOpen(true), [])

  useSwipeBack({ enabled: !isReader && !isAuth && !isPublic })

  if (isAuth || isPublic) {
    return (
      <>
        {children}
        <Toaster position="bottom-right" theme="dark" richColors />
        <SWUpdatePrompt />
      </>
    )
  }

  return (
    <WsProvider>
      <WsInvalidationBridge />
      <LayoutShellInner
        key={`${locale}:${dictionaryVersion}`}
        isReader={isReader}
        drawerOpen={drawerOpen}
        onDrawerClose={handleDrawerClose}
        onDrawerOpen={handleDrawerOpen}
      >
        {children}
      </LayoutShellInner>
    </WsProvider>
  )
}

/** Inner component lives inside WsProvider so it can call useDownloadStats */
function LayoutShellInner({
  children,
  isReader,
  drawerOpen,
  onDrawerClose,
  onDrawerOpen,
}: {
  children: React.ReactNode
  isReader: boolean
  drawerOpen: boolean
  onDrawerClose: () => void
  onDrawerOpen: () => void
}) {
  const { data: downloadStats } = useDownloadStats()

  return (
    <>
      <UiPreferencesSync />
      {/* Records per-tab last location for BottomTabBar restoration */}
      <Suspense fallback={null}>
        <NavMemoryTracker />
      </Suspense>

      {/* Desktop sidebar — hidden on mobile */}
      <Sidebar downloadStats={downloadStats} />

      {/* Mobile drawer nav — controlled by BottomTabBar More button */}
      <MobileNav open={drawerOpen} onClose={onDrawerClose} downloadStats={downloadStats} />

      {/* Mobile bottom tab bar — hidden on desktop, skip on reader pages */}
      {!isReader && <BottomTabBar onMoreClick={onDrawerOpen} downloadStats={downloadStats} />}

      {/* Main content */}
      <main className="lg:pl-56 pb-[calc(4rem+var(--sab))] lg:pb-0 min-h-screen bg-vault-bg text-vault-text">
        <div className="px-4 lg:px-6 xl:px-8 py-6 pt-[calc(1.5rem+var(--sat)/2)] lg:pt-6">
          {children}
        </div>
      </main>

      <Toaster position="bottom-right" richColors />
      <SWUpdatePrompt />
      {!isReader && <FloatingActions />}
    </>
  )
}
