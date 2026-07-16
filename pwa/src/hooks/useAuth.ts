'use client'
import { useRouter } from 'next/navigation'
import { useCallback } from 'react'
import { mutate } from 'swr'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { clearSWUserCaches } from '@/lib/swCacheConfig'

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
    // Cached media/pages hold private content — drop them with the session.
    clearSWUserCaches()
    router.push('/login')
    router.refresh()
  }, [router])

  return { login, logout }
}
