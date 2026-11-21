/**
 * One colour and one display name per site, shared by every source badge
 * (library cards, artists, subscriptions) so a site looks the same everywhere.
 *
 * Only colours live here: each badge keeps its own shape and size for its spot.
 */

// Full class strings listed explicitly so Tailwind detects them at build time.
// Known sites get a fixed colour so two common sites never share one.
const KNOWN_SOURCE_COLORS: Record<string, string> = {
  pixiv: 'bg-blue-900/50 text-blue-300 border-blue-800',
  twitter: 'bg-sky-900/50 text-sky-300 border-sky-800',
  x: 'bg-sky-900/50 text-sky-300 border-sky-800',
  ehentai: 'bg-orange-900/50 text-orange-300 border-orange-800',
  exhentai: 'bg-orange-900/50 text-orange-300 border-orange-800',
  weibo: 'bg-red-900/50 text-red-300 border-red-800',
  instagram: 'bg-pink-900/50 text-pink-300 border-pink-800',
  facebook: 'bg-indigo-900/50 text-indigo-300 border-indigo-800',
  fanbox: 'bg-yellow-900/50 text-yellow-300 border-yellow-800',
  local: 'bg-teal-900/50 text-teal-300 border-teal-800',
}

// Any other site hashes into this spectrum (red → … → rose).
export const SOURCE_COLOR_PALETTE = [
  'bg-red-900/50 text-red-300 border-red-800',
  'bg-orange-900/50 text-orange-300 border-orange-800',
  'bg-amber-900/50 text-amber-300 border-amber-800',
  'bg-yellow-900/50 text-yellow-300 border-yellow-800',
  'bg-lime-900/50 text-lime-300 border-lime-800',
  'bg-green-900/50 text-green-300 border-green-800',
  'bg-emerald-900/50 text-emerald-300 border-emerald-800',
  'bg-teal-900/50 text-teal-300 border-teal-800',
  'bg-cyan-900/50 text-cyan-300 border-cyan-800',
  'bg-sky-900/50 text-sky-300 border-sky-800',
  'bg-blue-900/50 text-blue-300 border-blue-800',
  'bg-indigo-900/50 text-indigo-300 border-indigo-800',
  'bg-violet-900/50 text-violet-300 border-violet-800',
  'bg-purple-900/50 text-purple-300 border-purple-800',
  'bg-fuchsia-900/50 text-fuchsia-300 border-fuchsia-800',
  'bg-pink-900/50 text-pink-300 border-pink-800',
  'bg-rose-900/50 text-rose-300 border-rose-800',
] as const

/** Colour for a badge whose site is unknown (no source detected). */
export const UNKNOWN_SOURCE_COLOR = 'bg-vault-border/60 text-vault-text-muted border-vault-border'

/** FNV-1a hash — better distribution than djb2 for short strings. */
function hashSource(source: string): number {
  let hash = 0x811c9dc5
  for (let i = 0; i < source.length; i++) {
    hash ^= source.charCodeAt(i)
    hash = (hash * 0x01000193) | 0
  }
  return Math.abs(hash)
}

/** Tailwind background, text and border classes for a site's badge. */
export function sourceColorClass(source: string | null | undefined): string {
  if (!source) return UNKNOWN_SOURCE_COLOR
  return (
    KNOWN_SOURCE_COLORS[source] ??
    SOURCE_COLOR_PALETTE[hashSource(source) % SOURCE_COLOR_PALETTE.length]
  )
}

const SOURCE_NAMES: Record<string, string> = {
  pixiv: 'Pixiv',
  twitter: 'Twitter',
  x: 'X',
  ehentai: 'E-Hentai',
  exhentai: 'ExHentai',
  weibo: 'Weibo',
  instagram: 'Instagram',
  facebook: 'Facebook',
  fanbox: 'Fanbox',
}

/** Display name of a site key; unlisted keys are shown capitalised. */
export function sourceDisplayName(source: string): string {
  return SOURCE_NAMES[source] ?? source.charAt(0).toUpperCase() + source.slice(1)
}
