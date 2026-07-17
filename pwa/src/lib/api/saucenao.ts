import { apiFetch } from './client'

// ── SauceNAO ─────────────────────────────────────────────────────────

export interface SauceNaoResult {
  similarity: number
  source_url: string
  title: string
  author: string
  source_name: string
  thumbnail: string
  ext_urls: string[]
}

export const saucenao = {
  search: (imageId: number) =>
    apiFetch<{ results: SauceNaoResult[] }>('/api/saucenao/search', {
      method: 'POST',
      body: JSON.stringify({ image_id: imageId }),
    }),
  batch: (imageIds: number[], autoFillSource = true, minSimilarity = 80) =>
    apiFetch<{
      results: Array<{
        image_id: number
        gallery_id?: number
        best?: SauceNaoResult | null
        source_applied?: boolean
        error?: string
      }>
    }>('/api/saucenao/batch', {
      method: 'POST',
      body: JSON.stringify({
        image_ids: imageIds,
        auto_fill_source: autoFillSource,
        min_similarity: minSimilarity,
      }),
    }),
}
