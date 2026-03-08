'use client'
import { useRouter } from 'next/navigation'
import { useCallback } from 'react'
import { mutate } from 'swr'
import { toast } from 'sonner'
import { api } from '@/lib/api'

export function useAuth() {
  const router = useRouter()

  const login = useCallback(async (username: string, password: string) => {
    await api.auth.login(username, password)
    router.push('/')
    router.refresh()
  }, [router])

  const logout = useCallback(async () => {
    try {
      await api.auth.logout()
    } catch {
      toast.error('Logout failed. Please try again.')
      return
    }
    await mutate(() => true, undefined, { revalidate: false })
    router.push('/login')
    router.refresh()
  }, [router])

  return { login, logout }
}
