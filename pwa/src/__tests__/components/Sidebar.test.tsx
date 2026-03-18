/**
 * Sidebar — Vitest test suite
 *
 * Covers:
 *   - Renders Jyzrox logo
 *   - Renders navigation links visible to current role
 *   - Admin-only links not shown to viewer
 *   - Admin-only links shown to admin
 *   - Member-only links shown to member
 *   - Member-only links not shown to viewer
 *   - Active link is highlighted (aria-current via class inspection)
 *   - Settings link is always rendered
 *   - Logout button is rendered
 *   - Clicking logout calls logout function
 *   - User profile section rendered when profile available
 *   - Theme toggle button rendered
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'

// ── Hoisted mock helpers ───────────────────────────────────────────────

const {
  mockUsePathname,
  mockLogout,
  mockUseProfile,
  mockUseDownloadStats,
  mockUseTheme,
  mockUseLocale,
} = vi.hoisted(() => ({
  mockUsePathname: vi.fn(() => '/'),
  mockLogout: vi.fn(),
  mockUseProfile: vi.fn(() => ({ data: null as Record<string, unknown> | null })),
  mockUseDownloadStats: vi.fn(() => ({ data: null })),
  mockUseTheme: vi.fn(() => ({ theme: 'dark', setTheme: vi.fn() })),
  mockUseLocale: vi.fn(() => ({})),
}))

// ── Module mocks ───────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

vi.mock('next/navigation', () => ({
  usePathname: mockUsePathname,
}))

vi.mock('next/link', () => ({
  default: ({ children, href, className }: { children: React.ReactNode; href: string; className?: string }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}))

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ logout: mockLogout }),
}))

vi.mock('@/hooks/useProfile', () => ({
  useProfile: mockUseProfile,
}))

vi.mock('@/hooks/useDownloadQueue', () => ({
  useDownloadStats: mockUseDownloadStats,
}))

vi.mock('next-themes', () => ({
  useTheme: mockUseTheme,
}))

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: mockUseLocale,
}))

// ── Import component after mocks ───────────────────────────────────────

import { Sidebar } from '@/components/Sidebar'

// ── Profile factory ────────────────────────────────────────────────────

function makeProfile(role: 'admin' | 'member' | 'viewer' = 'viewer') {
  return {
    id: 1,
    username: 'testuser',
    email: 'test@example.com',
    role,
    avatar_url: 'https://example.com/avatar.jpg',
    created_at: '2024-01-01T00:00:00Z',
    last_login_at: null,
  }
}

// ── Setup ──────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  mockUsePathname.mockReturnValue('/')
  mockUseProfile.mockReturnValue({ data: null })
  mockUseDownloadStats.mockReturnValue({ data: null })
  mockUseTheme.mockReturnValue({ theme: 'dark', setTheme: vi.fn() })
})

// ── Tests ──────────────────────────────────────────────────────────────

describe('Sidebar', () => {
  describe('branding', () => {
    it('test_sidebar_rendersJyzroxLogo', () => {
      render(<Sidebar />)
      expect(screen.getByText('Jyzrox')).toBeInTheDocument()
    })
  })

  describe('navigation links — viewer role', () => {
    beforeEach(() => {
      mockUseProfile.mockReturnValue({ data: makeProfile('viewer') })
    })

    it('test_sidebar_viewer_rendersLibraryLink', () => {
      render(<Sidebar />)
      expect(screen.getByText('nav.library')).toBeInTheDocument()
    })

    it('test_sidebar_viewer_rendersDashboardLink', () => {
      render(<Sidebar />)
      expect(screen.getByText('nav.dashboard')).toBeInTheDocument()
    })

    it('test_sidebar_viewer_doesNotRenderAdminOnlyLinks', () => {
      render(<Sidebar />)
      // admin-only links
      expect(screen.queryByText('nav.credentials')).not.toBeInTheDocument()
      expect(screen.queryByText('nav.users')).not.toBeInTheDocument()
    })

    it('test_sidebar_viewer_doesNotRenderMemberOnlyLinks', () => {
      render(<Sidebar />)
      expect(screen.queryByText('nav.queue')).not.toBeInTheDocument()
      expect(screen.queryByText('nav.subscriptions')).not.toBeInTheDocument()
    })
  })

  describe('navigation links — member role', () => {
    beforeEach(() => {
      mockUseProfile.mockReturnValue({ data: makeProfile('member') })
    })

    it('test_sidebar_member_rendersMemberLinks', () => {
      render(<Sidebar />)
      expect(screen.getByText('nav.queue')).toBeInTheDocument()
      expect(screen.getByText('nav.subscriptions')).toBeInTheDocument()
    })

    it('test_sidebar_member_doesNotRenderAdminLinks', () => {
      render(<Sidebar />)
      expect(screen.queryByText('nav.credentials')).not.toBeInTheDocument()
    })
  })

  describe('navigation links — admin role', () => {
    beforeEach(() => {
      mockUseProfile.mockReturnValue({ data: makeProfile('admin') })
    })

    it('test_sidebar_admin_rendersAdminLinks', () => {
      render(<Sidebar />)
      expect(screen.getByText('nav.credentials')).toBeInTheDocument()
      expect(screen.getByText('nav.users')).toBeInTheDocument()
    })

    it('test_sidebar_admin_rendersMemberLinks', () => {
      render(<Sidebar />)
      expect(screen.getByText('nav.queue')).toBeInTheDocument()
    })
  })

  describe('settings and logout', () => {
    it('test_sidebar_alwaysRendersSettingsLink', () => {
      render(<Sidebar />)
      expect(screen.getByText('nav.settings')).toBeInTheDocument()
    })

    it('test_sidebar_alwaysRendersLogoutButton', () => {
      render(<Sidebar />)
      expect(screen.getByText('nav.logout')).toBeInTheDocument()
    })

    it('test_sidebar_clickLogout_callsLogoutFunction', () => {
      render(<Sidebar />)
      fireEvent.click(screen.getByText('nav.logout'))
      expect(mockLogout).toHaveBeenCalledOnce()
    })
  })

  describe('user profile section', () => {
    it('test_sidebar_withProfile_rendersUsername', () => {
      mockUseProfile.mockReturnValue({ data: makeProfile() })
      render(<Sidebar />)
      expect(screen.getByText('testuser')).toBeInTheDocument()
    })

    it('test_sidebar_withProfile_rendersAvatar', () => {
      mockUseProfile.mockReturnValue({ data: makeProfile() })
      const { container } = render(<Sidebar />)
      // The avatar is an img with empty alt (decorative), query via querySelector
      const avatarImg = container.querySelector('img[src*="example.com/avatar"]') as HTMLImageElement
      expect(avatarImg).not.toBeNull()
      expect(avatarImg).toHaveAttribute('src', 'https://example.com/avatar.jpg')
    })

    it('test_sidebar_withoutProfile_doesNotRenderUsername', () => {
      mockUseProfile.mockReturnValue({ data: null })
      render(<Sidebar />)
      expect(screen.queryByText('testuser')).not.toBeInTheDocument()
    })
  })

  describe('theme toggle', () => {
    it('test_sidebar_rendersThemeToggleButton', () => {
      render(<Sidebar />)
      // Theme label key rendered inside the toggle button
      expect(screen.getByText('common.dark')).toBeInTheDocument()
    })

    it('test_sidebar_clickThemeToggle_callsSetTheme', () => {
      const setTheme = vi.fn()
      mockUseTheme.mockReturnValue({ theme: 'dark', setTheme })
      render(<Sidebar />)
      fireEvent.click(screen.getByText('common.dark'))
      expect(setTheme).toHaveBeenCalledOnce()
    })
  })

  describe('active link highlighting', () => {
    it('test_sidebar_activePathname_linkHasActiveClass', () => {
      mockUsePathname.mockReturnValue('/library')
      mockUseProfile.mockReturnValue({ data: makeProfile('viewer') })
      render(<Sidebar />)
      const libraryLink = screen.getByText('nav.library').closest('a')
      expect(libraryLink?.className).toContain('vault-accent')
    })

    it('test_sidebar_inactivePathname_linkDoesNotHaveActiveClass', () => {
      mockUsePathname.mockReturnValue('/library')
      mockUseProfile.mockReturnValue({ data: makeProfile('viewer') })
      render(<Sidebar />)
      const dashboardLink = screen.getByText('nav.dashboard').closest('a')
      // Dashboard link is active only when pathname === '/'
      expect(dashboardLink?.className).not.toContain('font-medium')
    })
  })
})
