import useSWR from 'swr'
import { api } from '@/lib/api'

export function useProfile() {
  return useSWR('auth/profile', () => api.auth.getProfile(), {
    revalidateOnFocus: false,
    dedupingInterval: 60000,
  })
}
