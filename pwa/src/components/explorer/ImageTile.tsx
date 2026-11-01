'use client'

import type { KeyboardEvent, MouseEvent } from 'react'
import { Check, EyeOff, FileImage, Film, HardDrive, Link2 } from 'lucide-react'

import { AppImage } from '@/components/AppImage'
import { useLongPress } from '@/hooks/useLongPress'
import type { ExplorerImageItem } from '@/lib/api/explorer'
import { formatBytes, t } from '@/lib/i18n'

import type { ContentView } from './shared'
import { formatDuration } from './shared'

export const imageKey = (image: ExplorerImageItem) => `image:${image.image_id}`
export const isImageHidden = (image: ExplorerImageItem) => image.visibility === 'hidden'

interface ImageTileProps {
  image: ExplorerImageItem
  view: ContentView
  selected: boolean
  selectionMode: boolean
  coarse: boolean
  focused: boolean
  tabIndex: number
  elementRef: (element: HTMLElement | null) => void
  onFocus: () => void
  onClick: (event: MouseEvent) => void
  onToggle: () => void
  onOpen: () => void
  onContextMenuAt: (x: number, y: number) => void
}

function Badges({ image }: { image: ExplorerImageItem }) {
  return (
    <>
      {isImageHidden(image) && (
        <span data-testid="image-hidden-badge" className="inline-flex items-center gap-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-amber-300">
          <EyeOff size={11} />{t('explorer.hiddenBadge')}
        </span>
      )}
      {image.shared && (
        <span data-testid="image-shared-badge" title={t('explorer.sharedHint')} className="inline-flex items-center gap-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-sky-300">
          <Link2 size={11} />{t('explorer.sharedBadge')}
        </span>
      )}
      {image.storage === 'external' && (
        <span title={t('explorer.externalHint')} className="inline-flex items-center gap-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-vault-text-muted">
          <HardDrive size={11} />{t('explorer.externalBadge')}
        </span>
      )}
    </>
  )
}

function MediaBadge({ image }: { image: ExplorerImageItem }) {
  if (image.media_type === 'video') {
    return (
      <span data-testid="image-video-badge" className="inline-flex items-center gap-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
        <Film size={11} />{image.duration != null ? formatDuration(image.duration) : t('explorer.mediaVideo')}
      </span>
    )
  }
  if (image.media_type === 'gif') {
    return <span className="rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">{t('explorer.mediaGif')}</span>
  }
  return null
}

/** One image of a Gallery in the Workbench grid or list. */
export function ImageTile({
  image,
  view,
  selected,
  selectionMode,
  coarse,
  focused,
  tabIndex,
  elementRef,
  onFocus,
  onClick,
  onToggle,
  onOpen,
  onContextMenuAt,
}: ImageTileProps) {
  const longPress = useLongPress({ onLongPress: () => onToggle() })
  const hidden = isImageHidden(image)
  const size = image.file_size != null ? formatBytes(image.file_size) : '—'
  const position = image.page_num ?? image.source_position
  const dimensions = image.width && image.height ? `${image.width} × ${image.height}` : null

  const handleClick = (event: MouseEvent) => {
    if (coarse && !selectionMode) onOpen()
    else onClick(event)
  }
  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
    event.preventDefault()
    const rect = event.currentTarget.getBoundingClientRect()
    onContextMenuAt(rect.left + rect.width / 2, rect.top + rect.height / 2)
  }
  const interaction = {
    ref: elementRef,
    'data-explorer-item': true,
    'data-testid': 'explorer-image-tile',
    'data-image-id': image.image_id,
    role: 'button',
    tabIndex,
    'aria-pressed': selected,
    onFocus,
    onClick: handleClick,
    onDoubleClick: () => { if (!coarse) onOpen() },
    onKeyDown: handleKeyDown,
    ...longPress,
    onContextMenu: coarse
      ? longPress.onContextMenu
      : (event: MouseEvent) => { event.preventDefault(); onContextMenuAt(event.clientX, event.clientY) },
  }
  const checkButton = (
    <button
      type="button"
      aria-label={t('explorer.toggleSelection')}
      onClick={(event) => { event.stopPropagation(); onToggle() }}
      className={`flex h-7 w-7 items-center justify-center rounded-full border shadow-sm ${selected ? 'border-vault-accent bg-vault-accent text-white' : 'border-vault-border bg-vault-card/90 text-vault-text-muted opacity-100 lg:opacity-0 lg:group-hover:opacity-100 lg:group-focus-visible:opacity-100'}`}
    >
      {selected ? <Check size={15} /> : <FileImage size={15} />}
    </button>
  )
  const thumb = image.thumb_path
    ? <AppImage src={image.thumb_path} alt="" loading="lazy" draggable={false} className={`h-full w-full ${view === 'grid' ? 'object-cover' : 'object-contain'} ${hidden ? 'opacity-50 grayscale' : ''}`} sizes={view === 'grid' ? undefined : '112px'} />
    : <span className="flex h-full w-full items-center justify-center text-vault-text-muted"><FileImage size={view === 'grid' ? 40 : 28} /></span>

  if (view === 'list') {
    return (
      <div
        {...interaction}
        className={`group flex w-full items-center gap-3 border-b border-vault-border px-3 py-2 text-left outline-none transition-colors ${selected ? 'bg-vault-accent/15 ring-1 ring-inset ring-vault-accent' : 'hover:bg-vault-card-hover'} ${focused ? 'ring-2 ring-inset ring-vault-accent' : ''}`}
      >
        {checkButton}
        <span className="flex h-16 w-24 shrink-0 overflow-hidden rounded-md bg-vault-bg-secondary sm:h-20 sm:w-28">{thumb}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-vault-text" title={image.filename}>{image.filename}</span>
          <span className="mt-1 block truncate text-xs text-vault-text-muted">{[position != null ? `#${position}` : null, dimensions, size].filter(Boolean).join(' · ')}</span>
          <span className="mt-1 flex flex-wrap items-center gap-1"><MediaBadge image={image} /><Badges image={image} /></span>
        </span>
      </div>
    )
  }

  return (
    <div
      {...interaction}
      className={`group relative overflow-hidden rounded-lg border bg-vault-card text-left outline-none transition ${selected ? 'border-vault-accent ring-2 ring-vault-accent/40' : 'border-vault-border hover:border-vault-accent/50'} ${focused ? 'ring-2 ring-vault-accent ring-offset-2 ring-offset-vault-bg' : ''}`}
    >
      <div className="relative aspect-[4/3] bg-vault-bg-secondary">
        {thumb}
        <div className="absolute left-2 top-2">{checkButton}</div>
        <div className="absolute right-2 top-2 flex flex-col items-end gap-1"><MediaBadge image={image} /></div>
        <div className="absolute bottom-2 left-2 flex flex-wrap items-center gap-1"><Badges image={image} /></div>
      </div>
      <div className="flex items-center justify-between gap-2 p-2 text-xs">
        <span className="min-w-0 truncate text-vault-text" title={image.filename}>{position != null ? `#${position} · ` : ''}{image.filename}</span>
        <span className="shrink-0 text-vault-text-muted">{size}</span>
      </div>
    </div>
  )
}
