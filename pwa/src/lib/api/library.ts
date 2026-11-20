import { libraryGalleries } from './libraryGalleries'
import { libraryImages } from './libraryImages'
import { libraryTrash } from './libraryTrash'

// ── Library ───────────────────────────────────────────────────────────

export const library = {
  ...libraryGalleries,
  ...libraryImages,
  ...libraryTrash,
}
