'use client'

import { useEffect, useState } from 'react'
import {
  FONT_SCALE_KEY,
  GRID_COLUMNS_KEY,
  GRID_DENSITY_KEY,
  loadLocalDisplayPreferences,
} from '@/lib/uiPreferences'

const DISPLAY_KEYS = new Set([GRID_DENSITY_KEY, GRID_COLUMNS_KEY, FONT_SCALE_KEY])

export function useDisplayPreferences() {
  const [preferences, setPreferences] = useState(loadLocalDisplayPreferences)

  useEffect(() => {
    const refresh = (event?: StorageEvent) => {
      if (event && event.key && !DISPLAY_KEYS.has(event.key)) return
      setPreferences(loadLocalDisplayPreferences())
    }
    window.addEventListener('storage', refresh)
    return () => window.removeEventListener('storage', refresh)
  }, [])

  return preferences
}
