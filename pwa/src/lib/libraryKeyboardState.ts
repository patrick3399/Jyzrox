const STORAGE_KEY = 'library_keyboard_return'

type LibraryKeyboardTarget = {
  version: 1
  query: string
  galleryId: number
}

export function saveLibraryKeyboardTarget(query: string, galleryId: number): void {
  if (typeof window === 'undefined') return
  try {
    const target: LibraryKeyboardTarget = { version: 1, query, galleryId }
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(target))
  } catch {
    // Keyboard navigation remains usable without session storage.
  }
}

export function consumeLibraryKeyboardTarget(query: string): number | null {
  if (typeof window === 'undefined') return null
  const raw = sessionStorage.getItem(STORAGE_KEY)
  sessionStorage.removeItem(STORAGE_KEY)
  if (!raw) return null

  try {
    const target = JSON.parse(raw) as Partial<LibraryKeyboardTarget>
    if (
      target.version !== 1 ||
      target.query !== query ||
      !Number.isInteger(target.galleryId) ||
      (target.galleryId ?? -1) < 0
    ) {
      return null
    }
    return target.galleryId ?? null
  } catch {
    return null
  }
}

export function clearLibraryKeyboardTarget(): void {
  if (typeof window === 'undefined') return
  sessionStorage.removeItem(STORAGE_KEY)
}
