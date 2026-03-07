'use client'

import { usePathname } from 'next/navigation'
import { NavBar } from './NavBar'

const AUTH_PATHS = ['/login', '/setup']

export function LayoutShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const isAuth = AUTH_PATHS.includes(pathname)

  if (isAuth) {
    return <>{children}</>
  }

  return (
    <>
      <NavBar />
      <main className="pt-14 min-h-screen bg-vault-bg">
        {children}
      </main>
    </>
  )
}
