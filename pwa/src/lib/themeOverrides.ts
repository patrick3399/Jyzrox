// Client-side theme override engine.
// - Accent override: inline custom property on <html>, wins over every theme class.
// - Custom (5th) theme: variables injected as a <style> block so next-themes'
//   class mechanism activates/deactivates them like any other theme.
// The boot script in app/layout.tsx duplicates the apply logic (it must run
// dependency-free before first paint) — keep both sides in sync.

export const ACCENT_KEY = 'vault-accent'
export const CUSTOM_THEME_KEY = 'vault-custom-theme'
export const CUSTOM_STYLE_ID = 'vault-custom-theme-style'

export interface CustomPalette {
  bg: string
  card: string
  text: string
}

export const DEFAULT_ACCENT = '#6366f1'
export const ACCENT_PRESETS = [
  '#6366f1', // indigo (default)
  '#3b82f6', // blue
  '#06b6d4', // cyan
  '#10b981', // emerald
  '#f59e0b', // amber
  '#ef4444', // red
  '#ec4899', // pink
  '#8b5cf6', // violet
]

export const DEFAULT_CUSTOM_PALETTE: CustomPalette = {
  bg: '#0a0a0a',
  card: '#141414',
  text: '#e5e5e5',
}

const HEX_RE = /^#[0-9a-fA-F]{6}$/

export function isHexColor(v: unknown): v is string {
  return typeof v === 'string' && HEX_RE.test(v)
}

// ── Accent override (global, applies to all themes) ────────────────────

export function loadAccent(): string | null {
  try {
    const v = localStorage.getItem(ACCENT_KEY)
    return isHexColor(v) ? v : null
  } catch {
    return null
  }
}

export function applyAccent(accent: string | null) {
  const style = document.documentElement.style
  if (accent && isHexColor(accent)) style.setProperty('--color-accent', accent)
  else style.removeProperty('--color-accent')
}

export function saveAccent(accent: string | null) {
  try {
    if (accent && isHexColor(accent)) localStorage.setItem(ACCENT_KEY, accent)
    else localStorage.removeItem(ACCENT_KEY)
    window.dispatchEvent(new StorageEvent('storage', { key: ACCENT_KEY, newValue: accent }))
  } catch {
    // localStorage unavailable (private mode) — still apply for this session
  }
  applyAccent(accent && isHexColor(accent) ? accent : null)
}

// ── Custom (5th) theme palette ──────────────────────────────────────────

export function loadCustomPalette(): CustomPalette {
  try {
    const raw = localStorage.getItem(CUSTOM_THEME_KEY)
    if (!raw) return DEFAULT_CUSTOM_PALETTE
    const p = JSON.parse(raw) as Partial<CustomPalette>
    if (isHexColor(p?.bg) && isHexColor(p?.card) && isHexColor(p?.text)) {
      return { bg: p.bg, card: p.card, text: p.text }
    }
    return DEFAULT_CUSTOM_PALETTE
  } catch {
    return DEFAULT_CUSTOM_PALETTE
  }
}

// Derived variables use color-mix so the whole palette stays coherent from
// just three user-picked colors. Keep in sync with the boot script.
export function customThemeCss(p: CustomPalette): string {
  return (
    `.custom{` +
    `--color-bg:${p.bg};` +
    `--color-card:${p.card};` +
    `--color-card-hover:color-mix(in srgb, ${p.card} 92%, ${p.text});` +
    `--color-border:color-mix(in srgb, ${p.bg} 86%, ${p.text});` +
    `--color-border-hover:color-mix(in srgb, ${p.bg} 72%, ${p.text});` +
    `--color-text:${p.text};` +
    `--color-text-secondary:color-mix(in srgb, ${p.text} 70%, ${p.bg});` +
    `--color-text-muted:color-mix(in srgb, ${p.text} 55%, ${p.bg});` +
    `--color-input:${p.card};` +
    `}`
  )
}

export function applyCustomPalette(p: CustomPalette) {
  if (!isHexColor(p.bg) || !isHexColor(p.card) || !isHexColor(p.text)) return
  let el = document.getElementById(CUSTOM_STYLE_ID) as HTMLStyleElement | null
  if (!el) {
    el = document.createElement('style')
    el.id = CUSTOM_STYLE_ID
    document.head.appendChild(el)
  }
  el.textContent = customThemeCss(p)
}

export function saveCustomPalette(p: CustomPalette) {
  try {
    localStorage.setItem(CUSTOM_THEME_KEY, JSON.stringify(p))
    window.dispatchEvent(
      new StorageEvent('storage', { key: CUSTOM_THEME_KEY, newValue: JSON.stringify(p) }),
    )
  } catch {
    // localStorage unavailable — still apply for this session
  }
  applyCustomPalette(p)
}

// ── WCAG contrast ───────────────────────────────────────────────────────

function channelLuminance(c: number): number {
  const s = c / 255
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
}

function relativeLuminance(hex: string): number {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return 0.2126 * channelLuminance(r) + 0.7152 * channelLuminance(g) + 0.0722 * channelLuminance(b)
}

/** WCAG 2.x contrast ratio between two #rrggbb colors, in [1, 21]. */
export function contrastRatio(hex1: string, hex2: string): number {
  if (!isHexColor(hex1) || !isHexColor(hex2)) return 21
  const l1 = relativeLuminance(hex1)
  const l2 = relativeLuminance(hex2)
  const [hi, lo] = l1 >= l2 ? [l1, l2] : [l2, l1]
  return (hi + 0.05) / (lo + 0.05)
}
