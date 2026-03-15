import { t } from '@/lib/i18n'
import type { Gallery } from '@/lib/types'

export function getSourceStyle(gallery: Gallery) {
  if (gallery.source === 'ehentai')
    return { label: 'E-Hentai', className: 'bg-purple-900/50 text-purple-300 border-purple-800' }
  if (gallery.source === 'pixiv')
    return { label: 'Pixiv', className: 'bg-blue-900/50 text-blue-300 border-blue-800' }
  if (gallery.source === 'local' && gallery.import_mode === 'link')
    return { label: t('library.monitored'), className: 'bg-teal-900/50 text-teal-300 border-teal-800' }
  if (gallery.source === 'local' && gallery.import_mode === 'copy')
    return { label: t('library.imported'), className: 'bg-amber-900/50 text-amber-300 border-amber-800' }
  if (gallery.source === 'local')
    return { label: 'Local', className: 'bg-green-900/50 text-green-300 border-green-800' }
  return {
    label: gallery.source.charAt(0).toUpperCase() + gallery.source.slice(1),
    className: 'bg-vault-card text-vault-text-muted border-vault-border',
  }
}

export function getEventPosition(e: React.TouchEvent | React.MouseEvent): { x: number; y: number } {
  if ('touches' in e && e.touches.length > 0) {
    return { x: e.touches[0].clientX, y: e.touches[0].clientY }
  }
  if ('changedTouches' in e && e.changedTouches.length > 0) {
    return { x: e.changedTouches[0].clientX, y: e.changedTouches[0].clientY }
  }
  const me = e as React.MouseEvent
  return { x: me.clientX, y: me.clientY }
}
