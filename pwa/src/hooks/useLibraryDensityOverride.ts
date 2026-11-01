'use client'

import { useEffect, useState } from 'react'
import {
  GRID_DENSITY_OVERRIDE_KEY,
  loadLibraryDensityOverride,
  type GridDensityPreference,
} from '@/lib/uiPreferences'

export function useLibraryDensityOverride(): GridDensityPreference | null {
  const [override, setOverride] = useState(loadLibraryDensityOverride)

  useEffect(() => {
    const refresh = (event?: StorageEvent) => {
      if (event && event.key && event.key !== GRID_DENSITY_OVERRIDE_KEY) return
      setOverride(loadLibraryDensityOverride())
    }
    window.addEventListener('storage', refresh)
    return () => window.removeEventListener('storage', refresh)
  }, [])

  return override
}
