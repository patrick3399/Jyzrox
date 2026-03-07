'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const navLinks = [
  { href: '/', label: 'Dashboard' },
  { href: '/browse', label: 'Browse' },
  { href: '/library', label: 'Library' },
  { href: '/queue', label: 'Queue' },
  { href: '/tags', label: 'Tags' },
  { href: '/settings', label: 'Settings' },
]

export function NavBar() {
  const pathname = usePathname()

  async function handleLogout() {
    await fetch('/api/auth/logout', { method: 'POST' })
    window.location.href = '/login'
  }

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-vault-card border-b border-vault-border h-14 flex items-center px-4">
      <span className="text-vault-accent font-bold text-lg tracking-wide mr-8 shrink-0">
        Jyzrox
      </span>
      <div className="flex items-center gap-1 overflow-x-auto flex-1">
        {navLinks.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={`px-3 py-1.5 rounded text-sm transition-colors whitespace-nowrap ${
              pathname === link.href
                ? 'text-neutral-100 bg-white/10'
                : 'text-neutral-400 hover:text-neutral-100 hover:bg-white/5'
            }`}
          >
            {link.label}
          </Link>
        ))}
      </div>
      <button
        onClick={handleLogout}
        className="ml-4 shrink-0 px-3 py-1.5 rounded text-sm text-neutral-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
      >
        Logout
      </button>
    </nav>
  )
}
