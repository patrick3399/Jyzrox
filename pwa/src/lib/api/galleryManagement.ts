import { apiFetch } from './client'

// ── Gallery Management ───────────────────────────────────────────────

export const galleryManagement = {
  sharing: (galleryId: number) =>
    apiFetch<{
      visibility: 'public' | 'private'
      permissions: Array<{ user_id: number; username: string; can_edit: boolean }>
      links: Array<{ id: number; expires_at: string | null; filter_r18: boolean; created_at: string }>
    }>(`/api/gallery-management/galleries/${galleryId}/sharing`),
  updateSharing: (
    galleryId: number,
    body: { visibility: 'public' | 'private'; permissions: Array<{ user_id: number; can_edit: boolean }> },
  ) =>
    apiFetch<{ status: string }>(`/api/gallery-management/galleries/${galleryId}/sharing`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  createShare: (galleryId: number, expiresInHours: number | null, filterR18: boolean) =>
    apiFetch<{ id: number; token: string; url: string; expires_at: string | null }>(
      `/api/gallery-management/galleries/${galleryId}/shares`,
      { method: 'POST', body: JSON.stringify({ expires_in_hours: expiresInHours, filter_r18: filterR18 }) },
    ),
  versions: (galleryId: number) =>
    apiFetch<{
      group_id: string | null
      versions: Array<{ id: number; source: string; source_id: string; title: string | null; posted_at: string | null }>
    }>(`/api/gallery-management/galleries/${galleryId}/versions`),
  linkVersion: (galleryId: number, linkedGalleryId: number) =>
    apiFetch<{ status: string }>(`/api/gallery-management/galleries/${galleryId}/versions`, {
      method: 'POST',
      body: JSON.stringify({ gallery_id: linkedGalleryId }),
    }),
  merge: (targetGalleryId: number, sourceGalleryId: number) =>
    apiFetch<{ status: string; pages: number }>(`/api/gallery-management/galleries/${targetGalleryId}/merge`, {
      method: 'POST',
      body: JSON.stringify({ source_gallery_id: sourceGalleryId }),
    }),
  publicShare: (token: string) =>
    apiFetch<{
      gallery: { id: number; title: string | null; source: string; source_id: string; pages: number; tags: string[] }
      images: Array<{ id: number; page_num: number; url: string }>
    }>(`/api/gallery-management/shares/${encodeURIComponent(token)}`),
}
