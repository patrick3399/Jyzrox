import { qs } from './client'

// ── Export ────────────────────────────────────────────────────────────

export const exportApi = {
  kohyaUrl: (galleryId: number): string => `/api/export/kohya/${galleryId}`,
  datasetUrl: (
    datasetId: number,
    options: {
      trigger_word?: string
      validation_percent: number
      include_metadata: boolean
    },
  ): string => `/api/export/dataset/${datasetId}${qs(options as Record<string, unknown>)}`,
}
