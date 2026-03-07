'use client'
import { useRouter } from 'next/navigation'
import { useCallback } from 'react'
import { api } from '@/lib/api'

export function useAuth() {
  const router = useRouter()

  const login = useCallback(async (username: string, password: string) => {
    await api.auth.login(username, password)
    router.push('/')
    router.refresh()
  }, [router])

  const logout = useCallback(async () => {
    await api.auth.logout()
    router.push('/login')
    router.refresh()
  }, [router])

  return { login, logout }
}
