'use client'

import { useEffect, useRef } from 'react'
import useSWR from 'swr'
import { useTheme } from 'next-themes'
import { api } from '@/lib/api'
import {
  UI_PREFERENCES_SWR_KEY,
  applyUiPreferences,
  collectLocalUiPreferences,
  persistUiPreferences,
  type ThemePreference,
} from '@/lib/uiPreferences'

export function UiPreferencesSync() {
  const { setTheme } = useTheme()
  const { data } = useSWR(UI_PREFERENCES_SWR_KEY, () => api.auth.getUiPreferences(), {
    revalidateOnFocus: false,
  })
  const appliedRef = useRef('')

  useEffect(() => {
    if (!data) return
    const serverPreferences = data.preferences ?? {}
    const signature = JSON.stringify(serverPreferences)
    if (appliedRef.current === signature) return
    appliedRef.current = signature

    if (Object.keys(serverPreferences).length === 0) {
      const localPreferences = collectLocalUiPreferences()
      if (Object.keys(localPreferences).length > 0) {
        void persistUiPreferences(localPreferences)
      }
      return
    }

    applyUiPreferences(serverPreferences, (theme: ThemePreference) => setTheme(theme))
  }, [data, setTheme])

  return null
}
