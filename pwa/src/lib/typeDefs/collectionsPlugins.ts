import type { Gallery } from './library'
import type { TagItem } from './ehDownloadTags'

/** Page-based response (total always present) */
export interface GalleryListResponse {
  galleries: Gallery[]
  /** Present in page-based responses */
  total?: number
  /** Present in cursor-based responses */
  next_cursor?: string | null
  /** Present in cursor-based responses */
  has_next?: boolean
}

export interface Collection {
  id: number
  name: string
  description: string | null
  cover_gallery_id: number | null
  gallery_count: number
  cover_thumb: string | null
  /** Present only when the list was requested with `gallery_id`. */
  contains_gallery?: boolean
  created_at: string | null
  updated_at: string | null
}

export interface DatasetSelection {
  gallery_ids?: number[]
  collection_ids?: number[]
  image_ids?: number[]
  tag_query?: string
  tag_query_limit?: number
}

export interface DatasetFilterConfig {
  min_width: number | null
  min_height: number | null
  max_aspect_ratio: number | null
  phash_distance: number | null
}

export interface DatasetSelectionSpec extends DatasetSelection {
  filters?: DatasetFilterConfig
}

export interface DatasetFilterReport {
  status: 'ok'
  filters: DatasetFilterConfig
  total: number
  auto_excluded: number
  newly_excluded: number
  would_restore: number
  manual_excluded: number
  remaining: number
  unknown_dimensions: number
  unknown_phash: number
  reasons: {
    min_resolution: number
    aspect_ratio: number
    phash_duplicate: number
  }
  changed?: number
}

export interface Dataset {
  id: number
  name: string
  description: string | null
  selection_spec: DatasetSelectionSpec
  member_count: number
  gallery_count: number
  excluded_count: number
  created_at: string | null
  updated_at: string | null
}

export interface DatasetImage {
  id: number
  gallery_id: number
  gallery_title: string
  page_num: number
  filename: string
  width: number | null
  height: number | null
  caption: string | null
  thumb_url: string
  thumb_srcset?: string | null
  state: 'included' | 'excluded'
  source: 'gallery' | 'collection' | 'manual' | 'tag_query'
  exclusion_reason: 'manual' | 'min_resolution' | 'aspect_ratio' | 'phash_duplicate' | string | null
}

export interface DatasetDetail extends Dataset {
  images: DatasetImage[]
  state: 'included' | 'excluded'
  page: number
  has_next: boolean
  total: number
}

/** Page-based tag list response */
export interface TagListResponse {
  tags: TagItem[]
  total?: number
  next_cursor?: string | null
  has_next?: boolean
}

/** Row in the tag translations browse table. */
export interface TagTranslationBrowseItem {
  namespace: string
  name: string
  language: string
  translation: string
}

/** Response for GET /api/tags/translations/browse (offset pagination). */
export interface TagTranslationBrowseResponse {
  total: number
  items: TagTranslationBrowseItem[]
}

// ── Plugin System ────────────────────────────────────────────────────

export interface FieldDef {
  name: string
  field_type: 'text' | 'password' | 'textarea' | 'select'
  label: string
  required: boolean
  placeholder: string
}

export interface BrowseSchema {
  search_fields: FieldDef[]
  supports_favorites: boolean
  supports_popular: boolean
  supports_toplist: boolean
}

export interface OAuthConfig {
  auth_url_endpoint: string
  callback_endpoint: string
  display_name: string
}

export interface CredentialFlow {
  flow_type: 'fields' | 'oauth' | 'login'
  fields: FieldDef[]
  oauth_config: OAuthConfig | null
  login_endpoint: string | null
  verify_endpoint: string | null
}

export interface PluginInfo {
  name: string
  source_id: string
  version: string
  url_patterns: string[]
  credential_schema: FieldDef[]
  credential_flows: CredentialFlow[]
  has_browse: boolean
  browse_schema: BrowseSchema | null
  credential_configured: boolean
  enabled: boolean
}
