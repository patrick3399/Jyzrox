'use client'
import { useRouter } from 'next/navigation'
import { useCallback } from 'react'
import { mutate } from 'swr'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { clearSWUserCaches } from '@/lib/swCacheConfig'
import { clearBrowseSessionStorage } from '@/lib/browse/snapshotStore'

export function useAuth() {
  const router = useRouter()

  const login = useCallback(
    async (username: string, password: string) => {
      await api.auth.login(username, password)
      router.push('/')
      router.refresh()
    },
    [router],
  )

  const logout = useCallback(async () => {
    try {
      await api.auth.logout()
    } catch {
      toast.error(t('login.logoutFailed'))
      return
    }
    await mutate(() => true, undefined, { revalidate: false })
    if (typeof window !== 'undefined') {
      try {
        clearBrowseSessionStorage(sessionStorage)
      } catch {
        // Storage cleanup is best effort and must not strand a completed logout.
      }
    }
    // Cached media/pages hold private content — drop them with the session.
    clearSWUserCaches()
    router.push('/login')
    router.refresh()
  }, [router])

  return { login, logout }
}
