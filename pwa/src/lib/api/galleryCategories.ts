import { apiFetch } from './client'

import type {
  CategoryBackfillResult,
  GalleryCategoriesResponse,
  GalleryCategoryDef,
} from '../types'

// ── Gallery category registry ─────────────────────────────────────────

export const galleryCategories = {
  list: (init?: RequestInit) =>
    apiFetch<GalleryCategoriesResponse>('/api/gallery-categories/', init),

  create: (data: { name: string; color: string }) =>
    apiFetch<GalleryCategoryDef>('/api/gallery-categories/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateColor: (id: number, color: string) =>
    apiFetch<GalleryCategoryDef>(`/api/gallery-categories/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ color }),
    }),

  remove: (id: number) =>
    apiFetch<{ deleted: string; galleries_cleared: number }>(`/api/gallery-categories/${id}`, {
      method: 'DELETE',
    }),

  backfill: (dryRun: boolean) =>
    apiFetch<CategoryBackfillResult>('/api/gallery-categories/backfill', {
      method: 'POST',
      body: JSON.stringify({ dry_run: dryRun }),
    }),
}
