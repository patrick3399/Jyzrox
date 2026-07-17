import { qs } from './client'

// ── Export ────────────────────────────────────────────────────────────

export const exportApi = {
  kohyaUrl: (galleryId: number): string => `/api/export/kohya/${galleryId}`,
  datasetUrl: (
    datasetId: number,
    options: {
      preset: 'kohya' | 'ai_toolkit'
      trigger_word?: string
      repeats: number
      validation_percent: number
      resolution?: number
      precompute_buckets: boolean
      include_metadata: boolean
    },
  ): string => `/api/export/dataset/${datasetId}${qs(options as Record<string, unknown>)}`,
}
