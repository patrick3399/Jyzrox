import { apiFetch } from './client'

// ── Search ────────────────────────────────────────────────────────────

export type SearchGalleryItem = {
  id: number
  title: string
  title_jpn: string | null
  source: string
  source_id: string
  category: string | null
  language: string | null
  pages: number
  rating: number
  favorited: boolean
  is_favorited: boolean
  my_rating: number | null
  in_reading_list: boolean
  artist_id: string | null
  artist_name?: string | null
  import_mode: string | null
  source_url: string | null
  tags_array: string[]
  uploader: string | null
  download_status: string
  added_at: string | null
  posted_at: string | null
  tags: string[]
  cover_thumb?: string | null
}

export type SearchGalleriesResponse = {
  query: string
  items: SearchGalleryItem[]
  next_cursor?: string
  has_next?: boolean
  total?: number
  page?: number
}

export const search = {
  galleries: (
    q: string,
    options?: { cursor?: string; page?: number; limit?: number; sort?: string },
  ): Promise<SearchGalleriesResponse> => {
    const params = new URLSearchParams({ q })
    if (options?.cursor) params.set('cursor', options.cursor)
    if (options?.page) params.set('page', String(options.page))
    if (options?.limit) params.set('limit', String(options.limit))
    if (options?.sort) params.set('sort', options.sort)
    return apiFetch(`/api/search/?${params}`)
  },
}
