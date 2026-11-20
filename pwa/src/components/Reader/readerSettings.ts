'use client'
import type { ReadingDirection, ReaderSettings } from './types'
import { DEFAULT_READER_SETTINGS } from './types'

// ── localStorage helpers ───────────────────────────────────────────────

export function loadReaderSettings(): ReaderSettings {
  if (typeof window === 'undefined') return DEFAULT_READER_SETTINGS
  try {
    const raw = localStorage.getItem('reader_settings')
    if (!raw) return DEFAULT_READER_SETTINGS
    return { ...DEFAULT_READER_SETTINGS, ...JSON.parse(raw) }
  } catch {
    return DEFAULT_READER_SETTINGS
  }
}

export function saveReaderSettings(settings: Partial<ReaderSettings>) {
  if (typeof window === 'undefined') return
  const current = loadReaderSettings()
  localStorage.setItem('reader_settings', JSON.stringify({ ...current, ...settings }))
}

export function loadDirection(source: string, sourceId: string): ReadingDirection | null {
  if (typeof window === 'undefined') return null
  const val = localStorage.getItem(`reader_direction_${source}_${sourceId}`)
  if (val === 'ltr' || val === 'rtl' || val === 'vertical') return val
  return null
}

export function saveDirection(source: string, sourceId: string, dir: ReadingDirection) {
  if (typeof window === 'undefined') return
  localStorage.setItem(`reader_direction_${source}_${sourceId}`, dir)
}
