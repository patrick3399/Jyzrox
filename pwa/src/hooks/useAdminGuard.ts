import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useProfile } from '@/hooks/useProfile'

/**
 * Redirects non-admin users away from admin-only pages.
 * Returns true only after the profile confirms admin access.
 * Returns false while loading or when the user is confirmed non-admin.
 */
export function useAdminGuard(fallback = '/settings'): boolean {
  const router = useRouter()
  const { data: profile, isLoading } = useProfile()

  useEffect(() => {
    if (!isLoading && profile?.role !== 'admin') router.replace(fallback)
  }, [isLoading, profile, router, fallback])

  return !isLoading && profile?.role === 'admin'
}
