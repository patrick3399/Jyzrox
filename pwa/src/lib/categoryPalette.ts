import type { GalleryCategoryDef } from '@/lib/types'

export interface CategoryColorClasses {
  bg: string
  text: string
  badge: string
  swatch: string
}

// Keys mirror backend services/gallery_categories.PALETTE. Class names are
// spelled out in full so Tailwind's source scan can see them.
export const CATEGORY_PALETTE: Record<string, CategoryColorClasses> = {
  pink: { bg: 'from-pink-950 to-pink-900', text: 'text-pink-300', badge: 'bg-pink-700', swatch: 'bg-pink-500' },
  orange: { bg: 'from-orange-950 to-orange-900', text: 'text-orange-300', badge: 'bg-orange-700', swatch: 'bg-orange-500' },
  yellow: { bg: 'from-yellow-950 to-yellow-900', text: 'text-yellow-300', badge: 'bg-yellow-700', swatch: 'bg-yellow-500' },
  green: { bg: 'from-green-950 to-green-900', text: 'text-green-300', badge: 'bg-green-700', swatch: 'bg-green-500' },
  sky: { bg: 'from-sky-950 to-sky-900', text: 'text-sky-300', badge: 'bg-sky-700', swatch: 'bg-sky-500' },
  blue: { bg: 'from-blue-950 to-blue-900', text: 'text-blue-300', badge: 'bg-blue-700', swatch: 'bg-blue-500' },
  purple: { bg: 'from-purple-950 to-purple-900', text: 'text-purple-300', badge: 'bg-purple-700', swatch: 'bg-purple-500' },
  red: { bg: 'from-red-950 to-red-900', text: 'text-red-300', badge: 'bg-red-700', swatch: 'bg-red-500' },
  rose: { bg: 'from-rose-950 to-rose-900', text: 'text-rose-300', badge: 'bg-rose-700', swatch: 'bg-rose-500' },
  gray: { bg: 'from-gray-900 to-gray-800', text: 'text-gray-300', badge: 'bg-gray-600', swatch: 'bg-gray-500' },
  teal: { bg: 'from-teal-950 to-teal-900', text: 'text-teal-300', badge: 'bg-teal-700', swatch: 'bg-teal-500' },
  indigo: { bg: 'from-indigo-950 to-indigo-900', text: 'text-indigo-300', badge: 'bg-indigo-700', swatch: 'bg-indigo-500' },
  emerald: { bg: 'from-emerald-950 to-emerald-900', text: 'text-emerald-300', badge: 'bg-emerald-700', swatch: 'bg-emerald-500' },
  cyan: { bg: 'from-cyan-950 to-cyan-900', text: 'text-cyan-300', badge: 'bg-cyan-700', swatch: 'bg-cyan-500' },
}

// Used before the registry has loaded, and by E-Hentai browse cards that
// never consult the registry. Lower-case name -> palette key.
const BUILTIN_COLOR_KEYS: Record<string, string> = {
  doujinshi: 'pink',
  manga: 'orange',
  'artist cg': 'yellow',
  'game cg': 'green',
  western: 'sky',
  'non-h': 'blue',
  'image set': 'purple',
  cosplay: 'red',
  'asian porn': 'rose',
  misc: 'gray',
}

export function resolveCategoryColors(
  category: string | null | undefined,
  defs?: GalleryCategoryDef[],
): CategoryColorClasses {
  const key = (category ?? '').trim().toLowerCase()
  const fromRegistry = defs?.find((d) => d.name.toLowerCase() === key)?.color
  const paletteKey = fromRegistry ?? BUILTIN_COLOR_KEYS[key] ?? 'gray'
  return CATEGORY_PALETTE[paletteKey] ?? CATEGORY_PALETTE.gray
}
