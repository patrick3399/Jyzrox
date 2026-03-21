import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useProfile } from '@/hooks/useProfile'

/**
 * Redirects non-admin users away from admin-only pages.
 * Returns true if the user is authorized (admin) or still loading.
 * Returns false if the user is confirmed non-admin (caller should render null).
 */
export function useAdminGuard(fallback = '/settings'): boolean {
  const router = useRouter()
  const { data: profile, isLoading } = useProfile()

  useEffect(() => {
    if (!isLoading && profile?.role !== 'admin') router.replace(fallback)
  }, [isLoading, profile, router, fallback])

  return isLoading || profile?.role === 'admin'
}
