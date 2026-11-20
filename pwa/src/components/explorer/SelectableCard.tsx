'use client'

import { type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { Check, FileImage, Folder, Image as ImageIcon, MoreHorizontal } from 'lucide-react'
import { AppImage } from '@/components/AppImage'
import { useLongPress } from '@/hooks/useLongPress'
import type { ExplorerGalleryItem, ExplorerPhysicalEntry } from '@/lib/api'
import { formatBytes, t } from '@/lib/i18n'
import { galleryName, type ContentView } from './shared'

export function SelectableCard({
  item,
  selected,
  selectionMode,
  coarse,
  view,
  previewUrl,
  elementRef,
  tabIndex,
  focused,
  onSelect,
  onToggle,
  onOpen,
  onFocus,
  onContextMenuAt,
}: {
  item: ExplorerGalleryItem | ExplorerPhysicalEntry
  selected: boolean
  selectionMode: boolean
  coarse: boolean
  view: ContentView
  previewUrl?: string
  elementRef: (element: HTMLElement | null) => void
  tabIndex: number
  focused: boolean
  onSelect: (event?: React.MouseEvent) => void
  onToggle: () => void
  onOpen: () => void
  onFocus: () => void
  onContextMenuAt: (x: number, y: number) => void
}) {
  const isGallery = 'id' in item
  const isFolder = isGallery || item.kind === 'folder'
  const name = isGallery ? galleryName(item) : item.name
  const size = isGallery
    ? item.logical_bytes
    : item.kind === 'folder'
      ? item.physical_bytes
      : item.size
  const preview = isGallery ? item.cover_thumb : previewUrl
  const isVideo = !isGallery && item.kind === 'media' && /\.(mp4|webm)$/i.test(item.name)
  const longPress = useLongPress({ onLongPress: () => onToggle() })
  // Fine pointers get the context menu; coarse pointers keep long-press selection.
  const interaction = {
    ...longPress,
    onContextMenu: coarse
      ? longPress.onContextMenu
      : (event: React.MouseEvent) => {
          event.preventDefault()
          onContextMenuAt(event.clientX, event.clientY)
        },
    onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => {
      if (event.target !== event.currentTarget) return
      if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
      event.preventDefault()
      const rect = event.currentTarget.getBoundingClientRect()
      onContextMenuAt(rect.left + rect.width / 2, rect.top + rect.height / 2)
    },
  }

  const handleClick = (event: React.MouseEvent) => {
    if (coarse) {
      if (selectionMode) onSelect(event)
      else if (isFolder) onOpen()
      else onSelect(event)
      return
    }
    onSelect(event)
  }

  if (view === 'list') {
    return (
      <div
        ref={elementRef}
        data-explorer-item
        role="button"
        tabIndex={tabIndex}
        aria-pressed={selected}
        onFocus={onFocus}
        onClick={handleClick}
        onDoubleClick={() => !coarse && onOpen()}
        {...interaction}
        className={`group grid grid-cols-[36px_minmax(0,1fr)_110px_100px] items-center gap-3 border-b border-vault-border px-3 py-2 text-sm outline-none ${selected ? 'bg-vault-accent/15 ring-1 ring-inset ring-vault-accent' : 'hover:bg-vault-card-hover'} ${focused ? 'ring-2 ring-inset ring-vault-accent' : ''}`}
      >
        <button
          type="button"
          aria-label={t('explorer.toggleSelection')}
          onClick={(event) => {
            event.stopPropagation()
            onToggle()
          }}
          className="flex h-8 w-8 items-center justify-center rounded text-vault-text-muted hover:bg-vault-border"
        >
          {selected ? (
            <Check size={18} className="text-vault-accent" />
          ) : isFolder ? (
            <Folder size={20} />
          ) : (
            <FileImage size={20} />
          )}
        </button>
        <span className="truncate font-medium text-vault-text">{name}</span>
        <span className="text-right text-vault-text-muted">
          {size == null ? t('explorer.calculating') : formatBytes(size)}
        </span>
        <span className="truncate text-right text-vault-text-muted">
          {isGallery ? item.source : item.kind}
        </span>
      </div>
    )
  }

  return (
    <div
      ref={elementRef}
      data-explorer-item
      role="button"
      tabIndex={tabIndex}
      aria-pressed={selected}
      onFocus={onFocus}
      onClick={handleClick}
      onDoubleClick={() => !coarse && onOpen()}
      {...interaction}
      className={`group relative overflow-hidden rounded-lg border bg-vault-card outline-none transition ${selected ? 'border-vault-accent ring-2 ring-vault-accent/40' : 'border-vault-border hover:border-vault-accent/50'} ${focused ? 'ring-2 ring-vault-accent ring-offset-2 ring-offset-vault-bg' : ''}`}
    >
      <div className="relative aspect-[4/3] bg-vault-bg-secondary">
        {preview && isVideo ? (
          <video src={preview} muted preload="metadata" className="h-full w-full object-cover" />
        ) : preview ? (
          <AppImage src={preview} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center text-vault-text-muted">
            {isFolder ? (
              <Folder size={48} strokeWidth={1.25} />
            ) : (
              <ImageIcon size={44} strokeWidth={1.25} />
            )}
          </div>
        )}
        <button
          type="button"
          aria-label={t('explorer.toggleSelection')}
          onClick={(event) => {
            event.stopPropagation()
            onToggle()
          }}
          className={`absolute left-2 top-2 flex h-7 w-7 items-center justify-center rounded-full border shadow-sm ${selected ? 'border-vault-accent bg-vault-accent text-white' : 'border-vault-border bg-vault-card/90 text-vault-text-muted opacity-100 lg:opacity-0 lg:group-hover:opacity-100'}`}
        >
          {selected ? (
            <Check size={15} />
          ) : isFolder ? (
            <Folder size={15} />
          ) : (
            <MoreHorizontal size={15} />
          )}
        </button>
      </div>
      <div className="p-3">
        <p className="truncate text-sm font-medium text-vault-text" title={name}>
          {name}
        </p>
        <div className="mt-1 flex items-center justify-between gap-2 text-xs text-vault-text-muted">
          <span>{isGallery ? `${item.pages ?? 0} ${t('explorer.pages')}` : item.kind}</span>
          <span>{size == null ? t('explorer.calculating') : formatBytes(size)}</span>
        </div>
      </div>
    </div>
  )
}
