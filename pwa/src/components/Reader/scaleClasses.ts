import type { ScaleMode } from './types'

// The Reader's own chrome (top bar, thumbnail strip, status bar). Touches and
// wheel events that start there are its controls' input, not page gestures.
export const READER_CHROME_SELECTOR = '.reader-overlay'

export function getScaleContainerClass(scaleMode: ScaleMode): string {
  switch (scaleMode) {
    case 'fit-width':
      return 'relative w-full overflow-y-auto overflow-x-hidden'
    case 'fit-height':
      return 'relative h-full overflow-x-auto overflow-y-hidden flex items-center'
    case 'original':
      return 'relative overflow-auto flex items-center justify-center'
    case 'fit-both':
    default:
      return 'relative flex h-full w-full items-center justify-center overflow-hidden'
  }
}

export function getScaleImageClass(scaleMode: ScaleMode): string {
  switch (scaleMode) {
    case 'fit-width':
      return 'w-full h-auto block pointer-events-none'
    case 'fit-height':
      return 'h-screen w-auto block pointer-events-none'
    case 'original':
      return 'block pointer-events-none'
    case 'fit-both':
    default:
      return 'max-h-full max-w-full object-contain pointer-events-none'
  }
}
