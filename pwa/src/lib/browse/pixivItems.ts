import type { PixivBrowseIdentity, PixivBrowseItem, PixivCursor } from '@/lib/browse/pixiv'
import type { BrowsePageResult } from '@/lib/browse/reducer'

export type SearchResponse = {
  illusts?: unknown[]
  next_offset?: number | null
  total?: number
}

export type FollowingResponse = {
  user_previews?: unknown[]
  next_offset?: number | null
  total?: number
}

export type RankingResponse = {
  contents?: unknown[]
  has_next?: boolean
  rank_total?: number
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

export function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

export function finiteTotal(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
}

function isIllustRecord(value: unknown): value is { id: number } & Record<string, unknown> {
  return isRecord(value) && isPositiveInteger(value.id)
}

function isUserPreviewRecord(
  value: unknown,
): value is { user: { id: number } & Record<string, unknown> } & Record<string, unknown> {
  return isRecord(value) && isRecord(value.user) && isPositiveInteger(value.user.id)
}

function isRankingRecord(value: unknown): value is { illust_id: number } & Record<string, unknown> {
  return isRecord(value) && isPositiveInteger(value.illust_id)
}

type IllustRecord = { id: number } & Record<string, unknown>
type UserPreviewRecord = { user: { id: number } & Record<string, unknown> } & Record<
  string,
  unknown
>
type RankingRecord = { illust_id: number } & Record<string, unknown>

// Items are persisted in the browse snapshot (sessionStorage, ~2 MB per source
// partition), so each one keeps only what the list cards read: a raw illust
// carries its caption HTML and, for a 50-page manga, ~200 image urls, and a
// few pages of those overflow the partition. Keep these projections in step
// with IllustCard / RankingCard / UserPreviewCard in app/pixiv/page.tsx and
// with useIllustActions.

/** Copy `key` from `source` into `target` when it holds a value of `type`. */
function copyField(
  target: Record<string, unknown>,
  source: Record<string, unknown>,
  key: string,
  type: 'string' | 'number' | 'boolean',
): void {
  if (typeof source[key] === type) target[key] = source[key]
}

function squareImageUrls(value: unknown): { square_medium: string } | undefined {
  if (!isRecord(value) || typeof value.square_medium !== 'string') return undefined
  return { square_medium: value.square_medium }
}

/** Tags arrive as `{ name, translated_name }` (App API) or bare strings (public
 *  search); the cards only render `name`. */
function slimTags(value: unknown): Array<{ name: string }> | undefined {
  if (!Array.isArray(value)) return undefined
  const tags: Array<{ name: string }> = []
  for (const tag of value) {
    if (typeof tag === 'string') tags.push({ name: tag })
    else if (isRecord(tag) && typeof tag.name === 'string') tags.push({ name: tag.name })
  }
  return tags
}

function slimIllust(illust: IllustRecord): IllustRecord {
  const slim: IllustRecord = { id: illust.id }
  copyField(slim, illust, 'title', 'string')
  const imageUrls = squareImageUrls(illust.image_urls)
  if (imageUrls) slim.image_urls = imageUrls
  if (isRecord(illust.user)) {
    const user: Record<string, unknown> = {}
    copyField(user, illust.user, 'id', 'number')
    copyField(user, illust.user, 'name', 'string')
    slim.user = user
  }
  const tags = slimTags(illust.tags)
  if (tags) slim.tags = tags
  copyField(slim, illust, 'page_count', 'number')
  copyField(slim, illust, 'total_view', 'number')
  copyField(slim, illust, 'total_bookmarks', 'number')
  copyField(slim, illust, 'is_bookmarked', 'boolean')
  return slim
}

// UserPreviewCard renders the first three thumbnails.
const USER_PREVIEW_ILLUST_LIMIT = 3

function slimUserPreview(preview: UserPreviewRecord): UserPreviewRecord {
  const user: UserPreviewRecord['user'] = { id: preview.user.id }
  copyField(user, preview.user, 'name', 'string')
  copyField(user, preview.user, 'profile_image', 'string')
  copyField(user, preview.user, 'is_followed', 'boolean')
  const illusts: Array<{ id: number; image_urls?: { square_medium: string } }> = []
  for (const illust of Array.isArray(preview.illusts) ? preview.illusts : []) {
    if (illusts.length >= USER_PREVIEW_ILLUST_LIMIT) break
    if (!isIllustRecord(illust)) continue
    const entry: { id: number; image_urls?: { square_medium: string } } = { id: illust.id }
    const imageUrls = squareImageUrls(illust.image_urls)
    if (imageUrls) entry.image_urls = imageUrls
    illusts.push(entry)
  }
  return { user, illusts }
}

function slimRankingEntry(entry: RankingRecord): RankingRecord {
  const slim: RankingRecord = { illust_id: entry.illust_id }
  copyField(slim, entry, 'title', 'string')
  copyField(slim, entry, 'user_name', 'string')
  copyField(slim, entry, 'url', 'string')
  if (typeof entry.rank === 'number' || typeof entry.rank === 'string') slim.rank = entry.rank
  return slim
}

export function toIllustItems(values: readonly unknown[] | undefined): PixivBrowseItem[] {
  return (values ?? [])
    .filter(isIllustRecord)
    .map((illust) => ({ kind: 'illust' as const, illust: slimIllust(illust) }))
}

export function toUserItems(values: readonly unknown[] | undefined): PixivBrowseItem[] {
  return (values ?? [])
    .filter(isUserPreviewRecord)
    .map((preview) => ({ kind: 'user' as const, preview: slimUserPreview(preview) }))
}

export function toRankingItems(values: readonly unknown[] | undefined): PixivBrowseItem[] {
  return (values ?? [])
    .filter(isRankingRecord)
    .map((entry) => ({ kind: 'ranking' as const, entry: slimRankingEntry(entry) }))
}

export function offsetValue(cursor: PixivCursor | null): number {
  return cursor?.kind === 'offset' ? cursor.value : 0
}

export function pageValue(cursor: PixivCursor | null): number {
  return cursor?.kind === 'page' ? cursor.value : 1
}

export function nextOffsetPage(
  response: SearchResponse | FollowingResponse,
  items: PixivBrowseItem[],
): BrowsePageResult<PixivBrowseItem, PixivCursor> {
  const nextOffset = isNonNegativeInteger(response.next_offset) ? response.next_offset : null
  return {
    items,
    cursor: nextOffset === null ? null : { kind: 'offset', value: nextOffset },
    hasMore: nextOffset !== null,
    total: finiteTotal(response.total),
  }
}

export function getItemId(item: PixivBrowseItem): string {
  switch (item.kind) {
    case 'illust':
      return `illust:${item.illust.id}`
    case 'ranking':
      return `ranking:${item.entry.illust_id}`
    case 'user':
      return `user:${item.preview.user.id}`
  }
}

export function canLoadIdentity(
  identity: PixivBrowseIdentity,
  credentialsConfigured: boolean,
): boolean {
  if (identity.surface === 'ranking') return true
  if (identity.surface === 'search' && identity.backend === 'public') return true
  return credentialsConfigured
}
