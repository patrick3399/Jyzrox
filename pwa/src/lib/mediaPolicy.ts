import type { MediaPolicy } from './types'

export const DEFAULT_MEDIA_POLICY: MediaPolicy = { max_files: null, include_videos: true }

const MAX_FILES_LIMIT = 100_000

export function isDefaultMediaPolicy(p: MediaPolicy): boolean {
  return p.max_files === null && p.include_videos === true
}

/** Read `options.media` back into a policy; anything missing or malformed falls back to the default. */
export function mediaPolicyFromOptions(options: Record<string, unknown> | undefined): MediaPolicy {
  const raw = options?.media
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    return { ...DEFAULT_MEDIA_POLICY }
  }
  const { max_files, include_videos } = raw as Record<string, unknown>
  return {
    max_files:
      typeof max_files === 'number' && Number.isInteger(max_files) && max_files >= 1
        ? max_files
        : null,
    include_videos: include_videos === false ? false : true,
  }
}

/** Returns a new options object: sets `media`, or removes it when default; never touches other keys. */
export function withMediaPolicy(
  options: Record<string, unknown> | undefined,
  policy: MediaPolicy,
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...options }
  if (isDefaultMediaPolicy(policy)) {
    delete next.media
  } else {
    next.media = { max_files: policy.max_files, include_videos: policy.include_videos }
  }
  return next
}

/** '' (or whitespace) -> null (no cap); integer 1..100000 -> number; anything else -> undefined (invalid). */
export function parseMaxFiles(input: string): number | null | undefined {
  const trimmed = input.trim()
  if (trimmed === '') return null
  if (!/^\d+$/.test(trimmed)) return undefined
  const n = Number(trimmed)
  if (!Number.isSafeInteger(n) || n < 1 || n > MAX_FILES_LIMIT) return undefined
  return n
}
