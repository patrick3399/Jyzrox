'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import useSWR from 'swr'
import {
  AlertTriangle,
  Archive,
  Check,
  ChevronRight,
  Columns3,
  Database,
  Edit3,
  FileImage,
  Folder,
  FolderOpen,
  FolderTree,
  Grid2X2,
  HardDrive,
  Image as ImageIcon,
  Keyboard,
  Layers3,
  List,
  Loader2,
  Merge,
  MoreHorizontal,
  RefreshCw,
  Search,
  Star,
  Tags,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import { toast } from 'sonner'

import { SkeletonGrid } from '@/components/Skeleton'
import { useLongPress } from '@/hooks/useLongPress'
import { useWorkbenchKeyboard } from '@/hooks/useWorkbenchKeyboard'
import { api } from '@/lib/api'
import type {
  ExplorerGalleryItem,
  ExplorerPhysicalEntry,
  ExplorerQuery,
  ExplorerRoots,
} from '@/lib/api'
import { readerHref } from '@/lib/galleryRoutes'
import { formatBytes, t } from '@/lib/i18n'
import type { LibraryFile } from '@/lib/types'

type LayoutMode = 'xnview' | 'finder'
type ContentView = 'grid' | 'list'
type NodeKind = 'root' | 'source' | 'collection' | 'artist' | 'saved_search' | 'smart' | 'trash' | 'physical' | 'gallery'

interface WorkbenchNode {
  kind: NodeKind
  id?: string
  path?: string
  source?: string
  sourceId?: string
  label?: string
}

interface QuerySelection {
  token: string
  count: number
  excluded: Set<number>
}

function useCoarsePointer(): boolean {
  const [coarse, setCoarse] = useState(false)
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const media = window.matchMedia('(pointer: coarse)')
    const update = () => setCoarse(media.matches)
    update()
    media.addEventListener?.('change', update)
    return () => media.removeEventListener?.('change', update)
  }, [])
  return coarse
}

function nodeFromParams(params: URLSearchParams): WorkbenchNode {
  const kind = (params.get('kind') || 'root') as NodeKind
  return {
    kind,
    id: params.get('id') || undefined,
    path: params.get('path') || undefined,
    source: params.get('source') || undefined,
    sourceId: params.get('sourceId') || undefined,
    label: params.get('label') || undefined,
  }
}

function galleryQuery(node: WorkbenchNode, query: string, offset: number): ExplorerQuery | null {
  const kind = node.kind
  if (kind !== 'source' && kind !== 'collection' && kind !== 'artist' && kind !== 'saved_search' && kind !== 'smart' && kind !== 'trash') return null
  return {
    node_kind: kind,
    node_id: node.id,
    query,
    sort: 'added_at',
    direction: 'desc',
    offset,
    limit: 60,
  }
}

function itemKey(item: ExplorerGalleryItem | ExplorerPhysicalEntry): string {
  return 'id' in item ? `gallery:${item.id}` : `physical:${item.path}`
}

function galleryName(item: ExplorerGalleryItem): string {
  return item.title || item.title_jpn || item.source_id
}

function NavButton({
  active,
  icon: Icon,
  label,
  count,
  onClick,
}: {
  active?: boolean
  icon: typeof Folder
  label: string
  count?: number
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-current={active ? 'page' : undefined}
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
        active ? 'bg-vault-accent/15 text-vault-accent' : 'text-vault-text hover:bg-vault-card-hover'
      }`}
    >
      <Icon size={15} className="shrink-0" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {count !== undefined && <span className="text-xs text-vault-text-muted">{count}</span>}
    </button>
  )
}

function handleNavigationKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
  if (!(event.target instanceof HTMLButtonElement)) return
  const navigation = event.currentTarget
  const pane = event.target.closest<HTMLElement>('[data-explorer-nav-pane]') ?? navigation
  const paneName = pane.dataset.explorerNavPane
  if (event.key === 'ArrowRight' && paneName === 'sections') {
    event.preventDefault()
    event.target.click()
    window.requestAnimationFrame(() => {
      navigation.querySelector<HTMLButtonElement>('[data-explorer-nav-pane="items"] button')?.focus()
    })
    return
  }
  if (event.key === 'ArrowLeft' && paneName === 'items') {
    event.preventDefault()
    const sectionPane = navigation.querySelector<HTMLElement>('[data-explorer-nav-pane="sections"]')
    const sectionButton = sectionPane?.querySelector<HTMLButtonElement>('button[aria-current="page"]') ?? sectionPane?.querySelector<HTMLButtonElement>('button')
    sectionButton?.focus()
    return
  }
  const buttons = [...pane.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')]
  const current = buttons.indexOf(event.target)
  if (current < 0) return
  let next: number | null = null
  if (event.key === 'ArrowDown') next = Math.min(current + 1, buttons.length - 1)
  else if (event.key === 'ArrowUp') next = Math.max(current - 1, 0)
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = buttons.length - 1
  if (next === null) return
  event.preventDefault()
  buttons[next]?.focus()
}

function NavigationTree({
  roots,
  node,
  navigate,
}: {
  roots: ExplorerRoots
  node: WorkbenchNode
  navigate: (node: WorkbenchNode) => void
}) {
  return (
    <nav data-explorer-navigation data-explorer-nav-pane onKeyDown={handleNavigationKeyDown} className="h-full overflow-y-auto border-r border-vault-border bg-vault-card/40 p-3" aria-label={t('explorer.libraryTree')}>
      <NavButton active={node.kind === 'root'} icon={Database} label={t('explorer.library')} onClick={() => navigate({ kind: 'root' })} />
      <p className="mb-1 mt-4 px-2 text-[11px] font-semibold uppercase tracking-wider text-vault-text-muted">{t('explorer.sources')}</p>
      {roots.virtual.sources.map((source) => (
        <NavButton
          key={source.id}
          active={node.kind === 'source' && node.id === source.id}
          icon={Archive}
          label={source.label}
          count={source.gallery_count}
          onClick={() => navigate({ kind: 'source', id: source.id, label: source.label })}
        />
      ))}
      <p className="mb-1 mt-4 px-2 text-[11px] font-semibold uppercase tracking-wider text-vault-text-muted">{t('explorer.organize')}</p>
      {roots.virtual.collections.items.map((collection) => (
        <NavButton
          key={collection.id}
          active={node.kind === 'collection' && node.id === String(collection.id)}
          icon={Layers3}
          label={collection.name}
          count={collection.gallery_count}
          onClick={() => navigate({ kind: 'collection', id: String(collection.id), label: collection.name })}
        />
      ))}
      {roots.virtual.artists.items.slice(0, 100).map((artist) => (
        <NavButton
          key={artist.id}
          active={node.kind === 'artist' && node.id === artist.id}
          icon={Users}
          label={artist.name.replace(/^[^:]+:/, '')}
          count={artist.gallery_count}
          onClick={() => navigate({ kind: 'artist', id: artist.id, label: artist.name })}
        />
      ))}
      {roots.virtual.saved_searches.items.map((search) => (
        <NavButton
          key={search.id}
          active={node.kind === 'saved_search' && node.id === String(search.id)}
          icon={Search}
          label={search.name}
          onClick={() => navigate({ kind: 'saved_search', id: String(search.id), label: search.name })}
        />
      ))}
      <p className="mb-1 mt-4 px-2 text-[11px] font-semibold uppercase tracking-wider text-vault-text-muted">{t('explorer.smartViews')}</p>
      <NavButton
        active={node.kind === 'smart' && node.id === 'missing_metadata'}
        icon={AlertTriangle}
        label={t('explorer.missingMetadata')}
        count={roots.virtual.smart_views.missing_metadata}
        onClick={() => navigate({ kind: 'smart', id: 'missing_metadata', label: t('explorer.missingMetadata') })}
      />
      <NavButton
        active={node.kind === 'smart' && node.id === 'duplicates'}
        icon={Merge}
        label={t('explorer.duplicates')}
        count={roots.virtual.smart_views.duplicate_pairs}
        onClick={() => navigate({ kind: 'smart', id: 'duplicates', label: t('explorer.duplicates') })}
      />
      <NavButton active={node.kind === 'trash'} icon={Trash2} label={t('explorer.trash')} onClick={() => navigate({ kind: 'trash', label: t('explorer.trash') })} />
      {roots.physical.length > 0 && (
        <p className="mb-1 mt-4 px-2 text-[11px] font-semibold uppercase tracking-wider text-vault-text-muted">{t('explorer.physicalLibraries')}</p>
      )}
      {roots.physical.map((library) => (
        <NavButton
          key={library.id}
          active={node.kind === 'physical' && node.id === String(library.id)}
          icon={HardDrive}
          label={library.label}
          onClick={() => navigate({ kind: 'physical', id: String(library.id), label: library.label, path: '' })}
        />
      ))}
    </nav>
  )
}

function FinderColumns({
  roots,
  node,
  navigate,
}: {
  roots: ExplorerRoots
  node: WorkbenchNode
  navigate: (node: WorkbenchNode) => void
}) {
  const section = node.kind === 'source'
    ? 'sources'
    : node.kind === 'collection'
      ? 'collections'
      : node.kind === 'artist'
        ? 'artists'
        : node.kind === 'saved_search'
          ? 'searches'
          : node.kind === 'physical'
            ? 'physical'
            : node.kind === 'smart' || node.kind === 'trash'
              ? 'smart'
              : 'sources'
  const sections: Array<{ id: string; label: string; Icon: typeof Folder }> = [
    { id: 'sources', label: t('explorer.sources'), Icon: Archive },
    { id: 'collections', label: t('explorer.collections'), Icon: Layers3 },
    { id: 'artists', label: t('explorer.artists'), Icon: Users },
    { id: 'searches', label: t('explorer.savedSearches'), Icon: Search },
    { id: 'smart', label: t('explorer.smartViews'), Icon: AlertTriangle },
    { id: 'physical', label: t('explorer.physicalLibraries'), Icon: HardDrive },
  ]
  return (
    <nav data-explorer-navigation onKeyDown={handleNavigationKeyDown} className="grid h-full grid-cols-2 overflow-hidden border-r border-vault-border bg-vault-card/40" aria-label={t('explorer.finderColumns')}>
      <div data-explorer-nav-pane="sections" className="overflow-y-auto border-r border-vault-border p-2">
        {sections.map(({ id, label, Icon }) => (
          <button key={id} type="button" aria-current={section === id ? 'page' : undefined} onClick={() => {
            if (id === 'sources' && roots.virtual.sources[0]) navigate({ kind: 'source', id: roots.virtual.sources[0].id, label: roots.virtual.sources[0].label })
            else if (id === 'collections' && roots.virtual.collections.items[0]) navigate({ kind: 'collection', id: String(roots.virtual.collections.items[0].id), label: roots.virtual.collections.items[0].name })
            else if (id === 'artists' && roots.virtual.artists.items[0]) navigate({ kind: 'artist', id: roots.virtual.artists.items[0].id, label: roots.virtual.artists.items[0].name })
            else if (id === 'searches' && roots.virtual.saved_searches.items[0]) navigate({ kind: 'saved_search', id: String(roots.virtual.saved_searches.items[0].id), label: roots.virtual.saved_searches.items[0].name })
            else if (id === 'smart') navigate({ kind: 'smart', id: 'missing_metadata', label: t('explorer.missingMetadata') })
            else if (id === 'physical' && roots.physical[0]) navigate({ kind: 'physical', id: String(roots.physical[0].id), label: roots.physical[0].label })
          }} className={`flex w-full items-center gap-2 rounded px-2 py-2 text-left text-sm ${section === id ? 'bg-vault-accent/15 text-vault-accent' : 'text-vault-text hover:bg-vault-card-hover'}`}>
            <Icon size={15} /><span className="min-w-0 flex-1 truncate">{label}</span><ChevronRight size={14} />
          </button>
        ))}
      </div>
      <div data-explorer-nav-pane="items" className="overflow-y-auto p-2">
        {section === 'sources' && roots.virtual.sources.map((item) => <NavButton key={item.id} active={node.id === item.id} icon={Archive} label={item.label} count={item.gallery_count} onClick={() => navigate({ kind: 'source', id: item.id, label: item.label })} />)}
        {section === 'collections' && roots.virtual.collections.items.map((item) => <NavButton key={item.id} active={node.id === String(item.id)} icon={Layers3} label={item.name} count={item.gallery_count} onClick={() => navigate({ kind: 'collection', id: String(item.id), label: item.name })} />)}
        {section === 'artists' && roots.virtual.artists.items.map((item) => <NavButton key={item.id} active={node.id === item.id} icon={Users} label={item.name.replace(/^[^:]+:/, '')} count={item.gallery_count} onClick={() => navigate({ kind: 'artist', id: item.id, label: item.name })} />)}
        {section === 'searches' && roots.virtual.saved_searches.items.map((item) => <NavButton key={item.id} active={node.id === String(item.id)} icon={Search} label={item.name} onClick={() => navigate({ kind: 'saved_search', id: String(item.id), label: item.name })} />)}
        {section === 'smart' && <><NavButton active={node.id === 'missing_metadata'} icon={AlertTriangle} label={t('explorer.missingMetadata')} onClick={() => navigate({ kind: 'smart', id: 'missing_metadata', label: t('explorer.missingMetadata') })} /><NavButton active={node.id === 'duplicates'} icon={Merge} label={t('explorer.duplicates')} onClick={() => navigate({ kind: 'smart', id: 'duplicates', label: t('explorer.duplicates') })} /><NavButton active={node.kind === 'trash'} icon={Trash2} label={t('explorer.trash')} onClick={() => navigate({ kind: 'trash', label: t('explorer.trash') })} /></>}
        {section === 'physical' && roots.physical.map((item) => <NavButton key={item.id} active={node.id === String(item.id)} icon={HardDrive} label={item.label} onClick={() => navigate({ kind: 'physical', id: String(item.id), label: item.label })} />)}
      </div>
    </nav>
  )
}

function SelectableCard({
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
  onOpen,
  onFocus,
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
  onOpen: () => void
  onFocus: () => void
}) {
  const isGallery = 'id' in item
  const isFolder = isGallery || item.kind === 'folder'
  const name = isGallery ? galleryName(item) : item.name
  const size = isGallery ? item.logical_bytes : item.kind === 'folder' ? item.physical_bytes : item.size
  const preview = isGallery ? item.cover_thumb : previewUrl
  const isVideo = !isGallery && item.kind === 'media' && /\.(mp4|webm)$/i.test(item.name)
  const longPress = useLongPress({ onLongPress: () => onSelect() })

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
        {...longPress}
        className={`group grid grid-cols-[36px_minmax(0,1fr)_110px_100px] items-center gap-3 border-b border-vault-border px-3 py-2 text-sm outline-none ${selected ? 'bg-vault-accent/15 ring-1 ring-inset ring-vault-accent' : 'hover:bg-vault-card-hover'} ${focused ? 'ring-2 ring-inset ring-vault-accent' : ''}`}
      >
        <button
          type="button"
          aria-label={t('explorer.toggleSelection')}
          onClick={(event) => { event.stopPropagation(); onSelect(event) }}
          className="flex h-8 w-8 items-center justify-center rounded text-vault-text-muted hover:bg-vault-border"
        >
          {selected ? <Check size={18} className="text-vault-accent" /> : isFolder ? <Folder size={20} /> : <FileImage size={20} />}
        </button>
        <span className="truncate font-medium text-vault-text">{name}</span>
        <span className="text-right text-vault-text-muted">{size == null ? t('explorer.calculating') : formatBytes(size)}</span>
        <span className="truncate text-right text-vault-text-muted">{isGallery ? item.source : item.kind}</span>
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
      {...longPress}
      className={`group relative overflow-hidden rounded-lg border bg-vault-card outline-none transition ${selected ? 'border-vault-accent ring-2 ring-vault-accent/40' : 'border-vault-border hover:border-vault-accent/50'} ${focused ? 'ring-2 ring-vault-accent ring-offset-2 ring-offset-vault-bg' : ''}`}
    >
      <div className="relative aspect-[4/3] bg-vault-bg-secondary">
        {preview && isVideo ? (
          <video src={preview} muted preload="metadata" className="h-full w-full object-cover" />
        ) : preview ? (
          <img src={preview} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center text-vault-text-muted">
            {isFolder ? <Folder size={48} strokeWidth={1.25} /> : <ImageIcon size={44} strokeWidth={1.25} />}
          </div>
        )}
        <button
          type="button"
          aria-label={t('explorer.toggleSelection')}
          onClick={(event) => { event.stopPropagation(); onSelect(event) }}
          className={`absolute left-2 top-2 flex h-7 w-7 items-center justify-center rounded-full border shadow-sm ${selected ? 'border-vault-accent bg-vault-accent text-white' : 'border-vault-border bg-vault-card/90 text-vault-text-muted opacity-100 lg:opacity-0 lg:group-hover:opacity-100'}`}
        >
          {selected ? <Check size={15} /> : isFolder ? <Folder size={15} /> : <MoreHorizontal size={15} />}
        </button>
      </div>
      <div className="p-3">
        <p className="truncate text-sm font-medium text-vault-text" title={name}>{name}</p>
        <div className="mt-1 flex items-center justify-between gap-2 text-xs text-vault-text-muted">
          <span>{isGallery ? `${item.pages ?? 0} ${t('explorer.pages')}` : item.kind}</span>
          <span>{size == null ? t('explorer.calculating') : formatBytes(size)}</span>
        </div>
      </div>
    </div>
  )
}

function GalleryFileItem({
  file,
  view,
  coarse,
  focused,
  tabIndex,
  elementRef,
  onFocus,
  onOpen,
}: {
  file: LibraryFile
  view: ContentView
  coarse: boolean
  focused: boolean
  tabIndex: number
  elementRef: (element: HTMLButtonElement | null) => void
  onFocus: () => void
  onOpen: () => void
}) {
  const dimensions = file.width && file.height ? `${file.width} × ${file.height}` : null
  const meta = [file.page_num != null ? `#${file.page_num}` : null, dimensions, file.file_size != null ? formatBytes(file.file_size) : null]
    .filter(Boolean)
    .join(' · ')

  if (view === 'list') {
    return (
      <button
        ref={elementRef}
        data-explorer-item
        data-explorer-file-view="list"
        type="button"
        tabIndex={tabIndex}
        onFocus={onFocus}
        onClick={coarse ? onOpen : undefined}
        onDoubleClick={coarse ? undefined : onOpen}
        className={`flex w-full items-center gap-3 border-b border-vault-border px-3 py-2 text-left outline-none transition-colors hover:bg-vault-card-hover ${focused ? 'bg-vault-accent/10 ring-2 ring-inset ring-vault-accent' : ''}`}
      >
        <span className="flex h-16 w-24 shrink-0 overflow-hidden rounded-md bg-vault-bg-secondary sm:h-20 sm:w-28">
          {file.thumb_path ? <img src={file.thumb_path} alt="" loading="lazy" className="h-full w-full object-contain" /> : <span className="flex h-full w-full items-center justify-center text-vault-text-muted"><FileImage size={28} /></span>}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-vault-text" title={file.filename}>{file.filename}</span>
          {meta && <span className="mt-1 block truncate text-xs text-vault-text-muted">{meta}</span>}
          <span className="mt-1 block truncate text-[11px] uppercase tracking-wide text-vault-text-muted/80">{file.media_type}</span>
        </span>
        <ChevronRight size={18} className="shrink-0 text-vault-text-muted" aria-hidden="true" />
      </button>
    )
  }

  return (
    <button
      ref={elementRef}
      data-explorer-item
      data-explorer-file-view="grid"
      type="button"
      tabIndex={tabIndex}
      onFocus={onFocus}
      onClick={coarse ? onOpen : undefined}
      onDoubleClick={coarse ? undefined : onOpen}
      className={`overflow-hidden rounded-lg border border-vault-border bg-vault-card text-left outline-none ${focused ? 'ring-2 ring-vault-accent ring-offset-2 ring-offset-vault-bg' : ''}`}
    >
      {file.thumb_path ? <img src={file.thumb_path} alt="" loading="lazy" className="aspect-[4/3] w-full object-cover" /> : <span className="flex aspect-[4/3] items-center justify-center"><FileImage size={40} /></span>}
      <span className="block truncate p-2 text-xs text-vault-text" title={file.filename}>{file.filename}</span>
    </button>
  )
}

function Inspector({
  item,
  physicalRoot,
}: {
  item?: ExplorerGalleryItem | ExplorerPhysicalEntry
  physicalRoot?: ExplorerRoots['physical'][number]
}) {
  const gallery = item && 'id' in item ? item : null
  const galleryId = gallery?.id ?? 0
  const { data: metadataHistory } = useSWR(
    galleryId > 0 ? ['explorer-metadata-history', galleryId] : null,
    () => api.explorer.metadataHistory(galleryId),
  )
  if (!item && !physicalRoot) {
    return <aside data-explorer-inspector tabIndex={-1} className="h-full border-l border-vault-border p-5 text-sm text-vault-text-muted outline-none focus:ring-2 focus:ring-inset focus:ring-vault-accent">{t('explorer.inspectorEmpty')}</aside>
  }
  if (physicalRoot && !item) {
    return (
      <aside data-explorer-inspector tabIndex={-1} className="h-full overflow-y-auto border-l border-vault-border p-5 outline-none focus:ring-2 focus:ring-inset focus:ring-vault-accent">
        <HardDrive size={28} className="mb-3 text-vault-accent" />
        <h2 className="font-semibold text-vault-text">{physicalRoot.label}</h2>
        <p className="mt-4 text-xs uppercase text-vault-text-muted">{t('explorer.physicalSize')}</p>
        <p className="mt-1 text-lg text-vault-text">{physicalRoot.physical_bytes == null ? t('explorer.calculating') : formatBytes(physicalRoot.physical_bytes)}</p>
        <p className="mt-2 text-xs text-vault-text-muted">{t('explorer.readOnlyPhysical')}</p>
      </aside>
    )
  }
  if (!item) return null
  const physical = 'id' in item ? null : item
  const name = gallery ? galleryName(gallery) : physical?.name ?? ''
  return (
    <aside data-explorer-inspector tabIndex={-1} className="h-full overflow-y-auto border-l border-vault-border p-5 outline-none focus:ring-2 focus:ring-inset focus:ring-vault-accent">
      <h2 className="break-words font-semibold text-vault-text">{name}</h2>
      {gallery ? (
        <dl className="mt-5 space-y-4 text-sm">
          <div><dt className="text-xs uppercase text-vault-text-muted">{t('explorer.source')}</dt><dd className="mt-1 text-vault-text">{gallery.source}</dd></div>
          <div><dt className="text-xs uppercase text-vault-text-muted">{t('explorer.logicalSize')}</dt><dd className="mt-1 text-vault-text">{formatBytes(gallery.logical_bytes)}</dd></div>
          <div><dt className="text-xs uppercase text-vault-text-muted">{t('explorer.uniqueCasSize')}</dt><dd className="mt-1 text-vault-text">{formatBytes(gallery.unique_cas_bytes)}</dd></div>
          <div><dt className="text-xs uppercase text-vault-text-muted">{t('explorer.metadata')}</dt><dd className="mt-1 text-vault-text">{[gallery.artist_id, gallery.category, gallery.language].filter(Boolean).join(' · ') || '—'}</dd></div>
          <div><dt className="text-xs uppercase text-vault-text-muted">{t('explorer.visibility')}</dt><dd className="mt-1 text-vault-text">{gallery.visibility}</dd></div>
          {metadataHistory && Object.entries(metadataHistory.fields).length > 0 && <div><dt className="text-xs uppercase text-vault-text-muted">{t('explorer.provenance')}</dt><dd className="mt-2 space-y-2">{Object.entries(metadataHistory.fields).map(([field, state]) => {
            const current = gallery[field as keyof ExplorerGalleryItem]
            const pending = state.locked && state.source_value !== null && String(state.source_value) !== String(current ?? '')
            return <div key={field} className="rounded border border-vault-border p-2"><div className="flex items-center justify-between"><span className="text-vault-text">{field}</span><span className="text-[10px] uppercase text-vault-text-muted">{state.origin}{state.locked ? ' · locked' : ''}</span></div>{pending && <p className="mt-1 text-xs text-amber-400">{t('explorer.sourceProposal')}: {String(state.source_value)}</p>}</div>
          })}</dd></div>}
          {metadataHistory && metadataHistory.changes.length > 0 && <div><dt className="text-xs uppercase text-vault-text-muted">{t('explorer.history')}</dt><dd className="mt-2 space-y-2">{metadataHistory.changes.slice(0, 5).map((change) => <div key={change.id} className="text-xs text-vault-text-muted"><span className="text-vault-text">{change.field}</span> · {change.origin}</div>)}</dd></div>}
        </dl>
      ) : physical ? (
        <dl className="mt-5 space-y-4 text-sm">
          <div><dt className="text-xs uppercase text-vault-text-muted">{t('explorer.type')}</dt><dd className="mt-1 text-vault-text">{physical.kind}</dd></div>
          <div><dt className="text-xs uppercase text-vault-text-muted">{t('explorer.physicalSize')}</dt><dd className="mt-1 text-vault-text">{physical.kind === 'folder' ? physical.physical_bytes == null ? t('explorer.calculating') : formatBytes(physical.physical_bytes) : formatBytes(physical.size || 0)}</dd></div>
          {physical.kind === 'folder' && <div><dt className="text-xs uppercase text-vault-text-muted">{t('explorer.importStatus')}</dt><dd className="mt-1 text-vault-text">{physical.gallery_id ? t('explorer.imported') : t('explorer.notImported')}</dd></div>}
        </dl>
      ) : null}
    </aside>
  )
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-[100] flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4" onMouseDown={onClose}>
      <section role="dialog" aria-modal="true" aria-label={title} className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-t-xl border border-vault-border bg-vault-card shadow-2xl sm:rounded-xl" onMouseDown={(event) => event.stopPropagation()}>
        <header className="sticky top-0 flex items-center justify-between border-b border-vault-border bg-vault-card px-5 py-4">
          <h2 className="font-semibold text-vault-text">{title}</h2>
          <button type="button" onClick={onClose} className="rounded p-1 text-vault-text-muted hover:bg-vault-card-hover"><X size={18} /></button>
        </header>
        {children}
      </section>
    </div>
  )
}

const METADATA_FIELDS = ['title', 'title_jpn', 'category', 'language', 'artist_id', 'uploader', 'visibility'] as const

function MetadataDialog({
  selection,
  querySelection,
  onClose,
  onDone,
}: {
  selection: ExplorerGalleryItem[]
  querySelection: QuerySelection | null
  onClose: () => void
  onDone: () => void
}) {
  const [modes, setModes] = useState<Record<string, 'keep' | 'set' | 'clear'>>({})
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const commonValues = useMemo(
    () => Object.fromEntries(
      METADATA_FIELDS.map((field) => [
        field,
        selection.length > 0 && selection.every((item) => String(item[field] ?? '') === String(selection[0][field] ?? ''))
          ? String(selection[0][field] ?? '')
          : '',
      ]),
    ),
    [selection],
  )

  const submit = async () => {
    const fields: Record<string, { mode: 'set' | 'clear'; value?: string }> = {}
    for (const field of METADATA_FIELDS) {
      const mode = modes[field] || 'keep'
      if (mode === 'set') fields[field] = { mode, value: values[field] ?? commonValues[field] }
      if (mode === 'clear') fields[field] = { mode }
    }
    if (Object.keys(fields).length === 0) return
    setSaving(true)
    try {
      await api.explorer.bulkMetadata({
        ...(querySelection
          ? { selection_token: querySelection.token, excluded_ids: [...querySelection.excluded] }
          : { gallery_ids: selection.map((item) => item.id) }),
        fields,
        lock_fields: true,
      })
      toast.success(t('explorer.metadataUpdated'))
      onDone()
      onClose()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={t('explorer.editMetadata')} onClose={onClose}>
      <div className="space-y-4 p-5">
        <p className="text-sm text-vault-text-muted">{t('explorer.manualFieldsLocked')}</p>
        {METADATA_FIELDS.map((field) => {
          const common = commonValues[field]
          return (
            <div key={field} className="grid grid-cols-[110px_minmax(0,1fr)] gap-3">
              <select
                aria-label={`${field} mode`}
                value={modes[field] || 'keep'}
                onChange={(event) => setModes((current) => ({ ...current, [field]: event.target.value as 'keep' | 'set' | 'clear' }))}
                className="rounded-md border border-vault-border bg-vault-bg px-2 py-2 text-sm text-vault-text"
              >
                <option value="keep">{t('explorer.keep')}</option>
                <option value="set">{t('explorer.set')}</option>
                {field !== 'visibility' && <option value="clear">{t('explorer.clear')}</option>}
              </select>
              {field === 'visibility' ? (
                <select
                  aria-label={field}
                  disabled={(modes[field] || 'keep') !== 'set'}
                  value={values[field] || common || 'public'}
                  onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))}
                  className="rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text disabled:opacity-50"
                >
                  <option value="public">public</option><option value="private">private</option>
                </select>
              ) : (
                <input
                  aria-label={field}
                  disabled={(modes[field] || 'keep') !== 'set'}
                  defaultValue={common}
                  placeholder={common ? undefined : t('explorer.mixedValues')}
                  onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))}
                  className="rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text disabled:opacity-50"
                />
              )}
            </div>
          )
        })}
      </div>
      <footer className="flex justify-end gap-2 border-t border-vault-border px-5 py-4">
        <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-vault-text-muted hover:bg-vault-card-hover">{t('common.cancel')}</button>
        <button type="button" disabled={saving} onClick={submit} className="rounded-md bg-vault-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{saving ? t('common.loading') : t('common.save')}</button>
      </footer>
    </Modal>
  )
}

function MergeDialog({ selection, onClose, onDone }: { selection: ExplorerGalleryItem[]; onClose: () => void; onDone: () => void }) {
  const [targetId, setTargetId] = useState(selection[0]?.id ?? 0)
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof api.explorer.mergePreview>> | null>(null)
  const [scalarSources, setScalarSources] = useState<Record<string, number>>({})
  const [working, setWorking] = useState(false)

  useEffect(() => {
    let active = true
    setPreview(null)
    api.explorer.mergePreview({ gallery_ids: selection.map((item) => item.id), target_id: targetId })
      .then((value) => {
        if (!active) return
        setPreview(value)
        setScalarSources(Object.fromEntries(Object.keys(value.scalar_conflicts).map((field) => [field, targetId])))
      })
      .catch((error) => toast.error(error instanceof Error ? error.message : t('common.errorOccurred')))
    return () => { active = false }
  }, [selection, targetId])

  const merge = async () => {
    setWorking(true)
    try {
      await api.explorer.merge({ gallery_ids: selection.map((item) => item.id), target_id: targetId, scalar_sources: scalarSources })
      toast.success(t('explorer.mergeComplete'))
      onDone()
      onClose()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    } finally {
      setWorking(false)
    }
  }

  return (
    <Modal title={t('explorer.mergeGalleries')} onClose={onClose}>
      <div className="space-y-5 p-5">
        <label className="block text-sm text-vault-text">{t('explorer.mergeTarget')}
          <select value={targetId} onChange={(event) => setTargetId(Number(event.target.value))} className="mt-2 w-full rounded-md border border-vault-border bg-vault-bg px-3 py-2">
            {selection.map((item) => <option key={item.id} value={item.id}>{galleryName(item)}</option>)}
          </select>
        </label>
        {preview ? (
          <>
            <div className="grid grid-cols-3 gap-3 rounded-lg border border-vault-border p-4 text-center">
              <div><p className="text-xl font-semibold text-vault-text">{preview.images.add}</p><p className="text-xs text-vault-text-muted">{t('explorer.imagesAdded')}</p></div>
              <div><p className="text-xl font-semibold text-vault-text">{preview.images.exact_sha_skipped}</p><p className="text-xs text-vault-text-muted">{t('explorer.exactSkipped')}</p></div>
              <div><p className="text-xl font-semibold text-vault-text">{preview.images.similar_kept_for_review}</p><p className="text-xs text-vault-text-muted">{t('explorer.similarReview')}</p></div>
            </div>
            {Object.entries(preview.scalar_conflicts).length > 0 && (
              <div className="space-y-3">
                <p className="text-sm font-medium text-vault-text">{t('explorer.resolveConflicts')}</p>
                {Object.entries(preview.scalar_conflicts).map(([field, choices]) => (
                  <label key={field} className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-3 text-sm text-vault-text-muted">
                    <span>{field}</span>
                    <select value={scalarSources[field] || targetId} onChange={(event) => setScalarSources((current) => ({ ...current, [field]: Number(event.target.value) }))} className="rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-vault-text">
                      {choices.map((choice) => <option key={choice.gallery_id} value={choice.gallery_id}>{String(choice.value ?? '—')}</option>)}
                    </select>
                  </label>
                ))}
              </div>
            )}
          </>
        ) : <div className="flex justify-center p-6"><Loader2 className="animate-spin" /></div>}
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
          {t('explorer.merge404Warning')}
        </div>
      </div>
      <footer className="flex justify-end gap-2 border-t border-vault-border px-5 py-4">
        <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-vault-text-muted hover:bg-vault-card-hover">{t('common.cancel')}</button>
        <button type="button" disabled={!preview || working} onClick={merge} className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{working ? t('common.loading') : t('explorer.mergeGalleries')}</button>
      </footer>
    </Modal>
  )
}

function OrganizeDialog({
  kind,
  selectionBody,
  onClose,
  onDone,
}: {
  kind: 'tags' | 'collections'
  selectionBody: { gallery_ids?: number[]; selection_token?: string; excluded_ids?: number[] }
  onClose: () => void
  onDone: () => void
}) {
  const [operation, setOperation] = useState<'add' | 'remove'>('add')
  const [tagsValue, setTagsValue] = useState('')
  const [collectionId, setCollectionId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const { data: collectionData } = useSWR(kind === 'collections' ? 'explorer-action-collections' : null, api.collections.list)

  const submit = async () => {
    setSaving(true)
    try {
      if (kind === 'tags') {
        const tags = tagsValue.split(/[\n,]+/).map((value) => value.trim()).filter(Boolean)
        await api.explorer.bulkAction({ ...selectionBody, action: operation === 'add' ? 'add_tags' : 'remove_tags', tags })
      } else {
        if (collectionId === null) return
        await api.explorer.bulkAction({ ...selectionBody, action: operation === 'add' ? 'add_collection' : 'remove_collection', collection_id: collectionId })
      }
      toast.success(t('explorer.bulkActionComplete'))
      onDone()
      onClose()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={kind === 'tags' ? t('explorer.manageTags') : t('explorer.manageCollections')} onClose={onClose}>
      <div className="space-y-4 p-5">
        <div className="flex rounded-md border border-vault-border p-1">
          <button type="button" onClick={() => setOperation('add')} className={`flex-1 rounded px-3 py-2 text-sm ${operation === 'add' ? 'bg-vault-accent text-white' : 'text-vault-text-muted'}`}>{t('explorer.add')}</button>
          <button type="button" onClick={() => setOperation('remove')} className={`flex-1 rounded px-3 py-2 text-sm ${operation === 'remove' ? 'bg-vault-accent text-white' : 'text-vault-text-muted'}`}>{t('explorer.remove')}</button>
        </div>
        {kind === 'tags' ? (
          <textarea value={tagsValue} onChange={(event) => setTagsValue(event.target.value)} placeholder="artist:name, language:english" rows={5} className="w-full rounded-md border border-vault-border bg-vault-bg p-3 text-sm text-vault-text" />
        ) : (
          <select value={collectionId ?? ''} onChange={(event) => setCollectionId(Number(event.target.value))} className="w-full rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text">
            <option value="">{t('explorer.chooseCollection')}</option>
            {(collectionData?.collections || []).map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}
          </select>
        )}
      </div>
      <footer className="flex justify-end gap-2 border-t border-vault-border px-5 py-4">
        <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-vault-text-muted hover:bg-vault-card-hover">{t('common.cancel')}</button>
        <button type="button" disabled={saving} onClick={submit} className="rounded-md bg-vault-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{saving ? t('common.loading') : t('common.save')}</button>
      </footer>
    </Modal>
  )
}

export function ExplorerWorkbench() {
  const router = useRouter()
  const params = useSearchParams()
  const coarse = useCoarsePointer()
  const node = useMemo(() => nodeFromParams(new URLSearchParams(params.toString())), [params])
  const viewParam = params.get('view')
  const [layout, setLayout] = useState<LayoutMode>('xnview')
  const [view, setView] = useState<ContentView>(() => viewParam === 'list' ? 'list' : 'grid')
  const [query, setQuery] = useState(params.get('q') || '')
  const [debouncedQuery, setDebouncedQuery] = useState(query)
  const [offset, setOffset] = useState(Number(params.get('offset') || 0))
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set())
  const [querySelection, setQuerySelection] = useState<QuerySelection | null>(null)
  const [metadataOpen, setMetadataOpen] = useState(false)
  const [mergeOpen, setMergeOpen] = useState(false)
  const [organizeOpen, setOrganizeOpen] = useState<'tags' | 'collections' | null>(null)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const anchorRef = useRef<number | null>(null)
  const searchInputRef = useRef<HTMLInputElement | null>(null)
  const contentGridRef = useRef<HTMLDivElement | null>(null)
  const [contentColumnCount, setContentColumnCount] = useState(1)
  const selectionModeActive = selectedKeys.size > 0 || querySelection !== null

  useEffect(() => {
    const device = coarse ? 'mobile' : 'desktop'
    const savedLayout = localStorage.getItem(`explorer_layout_mode:${device}`) as LayoutMode | null
    const savedView = localStorage.getItem(`explorer_content_view:${device}`) as ContentView | null
    if (savedLayout) setLayout(savedLayout)
    if (viewParam === 'grid' || viewParam === 'list') setView(viewParam)
    else if (savedView) setView(savedView)
  }, [coarse, viewParam])

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 250)
    return () => window.clearTimeout(timer)
  }, [query])

  useEffect(() => {
    const currentQuery = params.get('q') || ''
    const currentOffset = Number(params.get('offset') || 0)
    if (currentQuery === debouncedQuery && currentOffset === offset) return
    const next = new URLSearchParams(params.toString())
    if (debouncedQuery) next.set('q', debouncedQuery)
    else next.delete('q')
    if (offset) next.set('offset', String(offset))
    else next.delete('offset')
    router.replace(`/explorer${next.size ? `?${next}` : ''}`)
  }, [debouncedQuery, offset, params, router])

  useEffect(() => {
    if (!coarse || !selectionModeActive) return
    window.history.pushState({ explorerSelection: true }, '')
    const clear = () => { setSelectedKeys(new Set()); setQuerySelection(null) }
    window.addEventListener('popstate', clear, { once: true })
    return () => window.removeEventListener('popstate', clear)
  }, [coarse, selectionModeActive])

  const navigate = useCallback((next: WorkbenchNode) => {
    const nextParams = new URLSearchParams()
    nextParams.set('view', view)
    if (next.kind !== 'root') nextParams.set('kind', next.kind)
    if (next.id) nextParams.set('id', next.id)
    if (next.path) nextParams.set('path', next.path)
    if (next.source) nextParams.set('source', next.source)
    if (next.sourceId) nextParams.set('sourceId', next.sourceId)
    if (next.label) nextParams.set('label', next.label)
    router.replace(`/explorer${nextParams.size ? `?${nextParams}` : ''}`)
    setSelectedKeys(new Set())
    setQuerySelection(null)
    setOffset(0)
    setQuery('')
  }, [router, view])

  const { data: roots, error: rootsError, isLoading: rootsLoading, mutate: mutateRoots } = useSWR('explorer-roots', api.explorer.roots)
  const querySpec = galleryQuery(node, debouncedQuery, offset)
  const { data: galleries, error: galleryError, isLoading: galleryLoading, mutate: mutateGalleries } = useSWR(
    querySpec ? ['explorer-query', JSON.stringify(querySpec)] : null,
    () => api.explorer.query(querySpec ?? {}),
  )
  const physicalId = node.kind === 'physical' ? Number(node.id) : 0
  const { data: physical, error: physicalError, isLoading: physicalLoading, mutate: mutatePhysical } = useSWR(
    physicalId ? ['explorer-physical', physicalId, node.path || ''] : null,
    () => api.explorer.physicalEntries(physicalId, node.path || ''),
  )
  const gallerySource = node.source ?? ''
  const gallerySourceId = node.sourceId ?? ''
  const { data: galleryFiles, error: filesError, isLoading: filesLoading } = useSWR(
    node.kind === 'gallery' && gallerySource && gallerySourceId ? ['explorer-gallery-files', gallerySource, gallerySourceId] : null,
    () => api.library.listGalleryFiles(gallerySource, gallerySourceId),
  )

  const rootItems = useMemo(() => {
    if (!roots || node.kind !== 'root') return []
    const virtual = roots.virtual.sources.map((source) => ({
      id: -Math.abs(source.id.split('').reduce((value, char) => value + char.charCodeAt(0), 0)),
      source: source.id,
      source_id: source.id,
      title: source.label,
      title_jpn: null,
      category: null,
      language: null,
      artist_id: null,
      uploader: null,
      visibility: 'public' as const,
      pages: source.gallery_count,
      cover_thumb: null,
      logical_bytes: source.logical_bytes,
      unique_cas_bytes: source.unique_cas_bytes,
      is_favorited: false,
      my_rating: null,
      in_reading_list: false,
      deleted_at: null,
    }))
    const physicalRoots: ExplorerPhysicalEntry[] = roots.physical.map((library) => ({
      kind: 'folder',
      name: library.label,
      path: `@library:${library.id}`,
      physical_bytes: library.physical_bytes,
      size_status: library.size_status,
      modified_at: 0,
    }))
    return [...virtual, ...physicalRoots]
  }, [roots, node.kind])

  const contentItems = useMemo<Array<ExplorerGalleryItem | ExplorerPhysicalEntry>>(() => {
    if (node.kind === 'root') return rootItems
    if (node.kind === 'physical') return physical?.entries || []
    return galleries?.items || []
  }, [node.kind, rootItems, physical?.entries, galleries?.items])

  const selectedGalleries = useMemo(
    () => contentItems.filter((item): item is ExplorerGalleryItem => 'id' in item && item.id > 0 && selectedKeys.has(itemKey(item))),
    [contentItems, selectedKeys],
  )
  const selectedPhysicalFolders = useMemo(
    () => contentItems.filter((item): item is ExplorerPhysicalEntry => !('id' in item) && item.kind === 'folder' && selectedKeys.has(itemKey(item))),
    [contentItems, selectedKeys],
  )
  const selectedItem = contentItems.find((item) => selectedKeys.has(itemKey(item)))
  const physicalRoot = roots?.physical.find((root) => node.kind === 'physical' && String(root.id) === node.id)
  const effectiveSelectedCount = querySelection ? querySelection.count - querySelection.excluded.size : selectedKeys.size

  const isItemSelected = (item: ExplorerGalleryItem | ExplorerPhysicalEntry) => {
    if (querySelection && 'id' in item && item.id > 0) return !querySelection.excluded.has(item.id)
    return selectedKeys.has(itemKey(item))
  }

  const selectItem = (item: ExplorerGalleryItem | ExplorerPhysicalEntry, index: number, event?: React.MouseEvent) => {
    focusIndex(index)
    const key = itemKey(item)
    if (querySelection && 'id' in item && item.id > 0) {
      setQuerySelection((current) => {
        if (!current) return current
        const excluded = new Set(current.excluded)
        if (excluded.has(item.id)) excluded.delete(item.id)
        else excluded.add(item.id)
        return { ...current, excluded }
      })
      return
    }
    setQuerySelection(null)
    setSelectedKeys((current) => {
      const next = new Set(current)
      if (event?.shiftKey && anchorRef.current !== null) {
        const start = Math.min(anchorRef.current, index)
        const end = Math.max(anchorRef.current, index)
        for (let position = start; position <= end; position += 1) next.add(itemKey(contentItems[position]))
      } else if (event?.ctrlKey || event?.metaKey || coarse || current.has(key)) {
        if (next.has(key)) next.delete(key)
        else next.add(key)
        anchorRef.current = index
      } else {
        next.clear()
        next.add(key)
        anchorRef.current = index
      }
      return next
    })
  }

  const openItem = (item: ExplorerGalleryItem | ExplorerPhysicalEntry) => {
    if ('id' in item) {
      if (node.kind === 'root' && item.id < 0) navigate({ kind: 'source', id: item.source, label: galleryName(item) })
      else navigate({ kind: 'gallery', id: String(item.id), source: item.source, sourceId: item.source_id, label: galleryName(item) })
      return
    }
    if (item.kind === 'folder') {
      if (item.path.startsWith('@library:')) {
        const id = item.path.split(':')[1]
        const root = roots?.physical.find((value) => String(value.id) === id)
        navigate({ kind: 'physical', id, path: '', label: root?.label })
      } else navigate({ ...node, path: item.path })
    }
  }

  const selectAllQuery = async () => {
    if (!querySpec) return
    try {
      const result = await api.explorer.createSelection(querySpec)
      setQuerySelection({ token: result.selection_token, count: result.count, excluded: new Set() })
      setSelectedKeys(new Set())
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    }
  }

  const deleteSelection = async () => {
    if (!window.confirm(t('explorer.deleteGalleriesConfirm', { count: effectiveSelectedCount }))) return
    try {
      const result = await api.explorer.deleteSelection(
        querySelection
          ? { selection_token: querySelection.token, excluded_ids: [...querySelection.excluded] }
          : { gallery_ids: selectedGalleries.map((item) => item.id) },
      )
      toast.success(t('explorer.galleriesDeleted', { count: result.affected }))
      setSelectedKeys(new Set())
      setQuerySelection(null)
      await Promise.all([mutateGalleries(), mutateRoots()])
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    }
  }

  const actionSelectionBody = querySelection
    ? { selection_token: querySelection.token, excluded_ids: [...querySelection.excluded] }
    : { gallery_ids: selectedGalleries.map((item) => item.id) }

  const runQuickAction = async (
    action: 'favorite' | 'unfavorite' | 'add_read_later' | 'remove_read_later' | 'rate',
    rating?: number,
  ) => {
    try {
      await api.explorer.bulkAction({ ...actionSelectionBody, action, rating })
      toast.success(t('explorer.bulkActionComplete'))
      await refresh()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    }
  }

  const importSelectedFolder = async () => {
    const folder = selectedPhysicalFolders[0]
    if (!folder || !physicalId) return
    try {
      await api.explorer.importPhysicalFolder(physicalId, folder.path)
      toast.success(t('explorer.importQueued'))
      setSelectedKeys(new Set())
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    }
  }

  const changeLayout = (next: LayoutMode) => {
    setLayout(next)
    localStorage.setItem(`explorer_layout_mode:${coarse ? 'mobile' : 'desktop'}`, next)
  }
  const changeView = (next: ContentView) => {
    setView(next)
    localStorage.setItem(`explorer_content_view:${coarse ? 'mobile' : 'desktop'}`, next)
    const nextParams = new URLSearchParams(params.toString())
    nextParams.set('view', next)
    router.replace(`/explorer?${nextParams.toString()}`)
  }

  useEffect(() => {
    if (view === 'list') {
      setContentColumnCount(1)
      return
    }
    const element = contentGridRef.current
    if (!element) return
    const update = () => {
      const columns = window.getComputedStyle(element).gridTemplateColumns.split(' ').filter(Boolean).length
      setContentColumnCount(Math.max(1, columns))
    }
    update()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [contentItems.length, galleryFiles?.files.length, layout, view])

  const goBack = useCallback(() => {
    if (node.kind === 'root') return
    if (node.kind === 'physical' && node.path) {
      navigate({ ...node, path: node.path.split('/').slice(0, -1).join('/') })
      return
    }
    if (node.kind === 'gallery' && node.source) {
      navigate({ kind: 'source', id: node.source, label: node.source })
      return
    }
    navigate({ kind: 'root' })
  }, [navigate, node])

  const keyboardItemCount = node.kind === 'gallery' ? galleryFiles?.files.length ?? 0 : contentItems.length
  const keyboardEnabled = !coarse && !metadataOpen && !mergeOpen && organizeOpen === null && !shortcutsOpen
  const { focusedIndex, focusIndex, registerElement } = useWorkbenchKeyboard({
    itemCount: keyboardItemCount,
    columnCount: contentColumnCount,
    listMode: view === 'list',
    enabled: keyboardEnabled,
    onOpen: (index) => {
      if (node.kind === 'gallery') {
        const file = galleryFiles?.files[index]
        if (file) router.push(readerHref(gallerySource, gallerySourceId, file.page_num || undefined))
        return
      }
      const item = contentItems[index]
      if (item) openItem(item)
    },
    onToggleSelection: (index) => {
      if (node.kind === 'gallery') return
      const item = contentItems[index]
      if (!item) return
      if (querySelection && 'id' in item && item.id > 0) {
        setQuerySelection((current) => {
          if (!current) return current
          const excluded = new Set(current.excluded)
          if (excluded.has(item.id)) excluded.delete(item.id)
          else excluded.add(item.id)
          return { ...current, excluded }
        })
        return
      }
      setQuerySelection(null)
      setSelectedKeys((current) => {
        const next = new Set(current)
        const key = itemKey(item)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return next
      })
      anchorRef.current = index
    },
    onExtendSelection: (fromIndex, toIndex) => {
      if (node.kind === 'gallery') return
      const anchor = anchorRef.current ?? fromIndex
      anchorRef.current = anchor
      const start = Math.min(anchor, toIndex)
      const end = Math.max(anchor, toIndex)
      const next = new Set<string>()
      for (let position = start; position <= end; position += 1) {
        const item = contentItems[position]
        if (item) next.add(itemKey(item))
      }
      setQuerySelection(null)
      setSelectedKeys(next)
    },
    onSelectAll: () => {
      if (node.kind === 'gallery') return
      if (querySpec) void selectAllQuery()
      else setSelectedKeys(new Set(contentItems.map(itemKey)))
    },
    onClearSelection: () => {
      if (!selectionModeActive) return false
      setSelectedKeys(new Set())
      setQuerySelection(null)
      anchorRef.current = null
      return true
    },
    onBack: goBack,
    onFocusSearch: () => searchInputRef.current?.focus(),
    onDelete: () => {
      if (querySelection || selectedGalleries.length > 0) void deleteSelection()
    },
    onEditMetadata: () => {
      if (querySelection || selectedGalleries.length > 0) setMetadataOpen(true)
    },
    onTreeLayout: () => changeLayout('xnview'),
    onColumnLayout: () => changeLayout('finder'),
    onGridView: () => changeView('grid'),
    onListView: () => changeView('list'),
    onShowShortcuts: () => setShortcutsOpen(true),
    onCyclePane: () => {
      const navigation = document.querySelector<HTMLElement>('[data-explorer-navigation]')
      const content = document.querySelector<HTMLElement>('[data-explorer-item][tabindex="0"]')
      const inspector = document.querySelector<HTMLElement>('[data-explorer-inspector]')
      const active = document.activeElement
      if (active instanceof HTMLElement && active.closest('[data-explorer-navigation]')) content?.focus()
      else if (active instanceof HTMLElement && active.closest('[data-explorer-item]')) inspector?.focus()
      else (navigation?.querySelector<HTMLButtonElement>('button[aria-current="page"]') ?? navigation?.querySelector<HTMLButtonElement>('button'))?.focus()
    },
  })

  const activeItem = selectedItem ?? (node.kind !== 'gallery' && focusedIndex !== null ? contentItems[focusedIndex] : undefined)

  useEffect(() => {
    focusIndex(null)
    anchorRef.current = null
  }, [focusIndex, node.id, node.kind, node.path])

  const error = rootsError || galleryError || physicalError || filesError
  const loading = rootsLoading || galleryLoading || physicalLoading || filesLoading
  const refresh = () => Promise.all([mutateRoots(), mutateGalleries(), mutatePhysical()])

  if (error) {
    return (
      <div className="m-6 rounded-lg border border-red-500/40 bg-red-500/10 p-6 text-red-300">
        <p>{error instanceof Error ? error.message : t('common.errorOccurred')}</p>
        <button type="button" onClick={() => void refresh()} className="mt-4 rounded bg-vault-card px-3 py-2 text-sm text-vault-text">{t('common.retry')}</button>
      </div>
    )
  }
  if (!roots && loading) return <div className="p-6"><SkeletonGrid /></div>
  if (!roots) return null

  const currentLabel = node.kind === 'root' ? t('explorer.library') : node.label || node.id || t('explorer.library')
  const finderCrumbs: Array<{ label: string; target: WorkbenchNode }> = [
    { label: t('explorer.library'), target: { kind: 'root' } },
  ]
  if (node.kind !== 'root') {
    finderCrumbs.push({ label: currentLabel, target: { ...node, path: '' } })
    if (node.kind === 'physical' && node.path) {
      const parts = node.path.split('/').filter(Boolean)
      parts.forEach((part, index) => finderCrumbs.push({
        label: part,
        target: { ...node, path: parts.slice(0, index + 1).join('/') },
      }))
    }
  }

  return (
    <main className="flex h-[calc(100dvh-7rem-var(--sab)-var(--sat)/2)] min-h-0 flex-col overflow-hidden bg-vault-bg [container-type:inline-size] lg:h-[calc(100dvh-3rem)] lg:min-h-[560px]">
      <header className="flex flex-wrap items-center gap-2 border-b border-vault-border bg-vault-card px-3 py-2">
        <div className="mr-2 flex min-w-0 items-center gap-2">
          <Database size={20} className="text-vault-accent" />
          <h1 className="truncate font-semibold text-vault-text">{t('explorer.workbench')}</h1>
        </div>
        <div className="relative min-w-[180px] flex-1 sm:max-w-md">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-vault-text-muted" />
          <input ref={searchInputRef} aria-keyshortcuts="/" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('explorer.searchPlaceholder')} className="w-full rounded-md border border-vault-border bg-vault-bg py-2 pl-9 pr-3 text-sm text-vault-text" />
        </div>
        <div role="group" aria-label={t('explorer.layoutMode')} className="hidden rounded-md border border-vault-border p-0.5 sm:flex">
          <button type="button" aria-label={t('explorer.treeLayout')} title={t('explorer.treeLayout')} aria-pressed={layout === 'xnview'} onClick={() => changeLayout('xnview')} className={`rounded p-1.5 ${layout === 'xnview' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:bg-vault-card-hover'}`}><FolderTree size={17} /></button>
          <button type="button" aria-label={t('explorer.columnLayout')} title={t('explorer.columnLayout')} aria-pressed={layout === 'finder'} onClick={() => changeLayout('finder')} className={`rounded p-1.5 ${layout === 'finder' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:bg-vault-card-hover'}`}><Columns3 size={17} /></button>
        </div>
        <button type="button" aria-label={t('explorer.gridView')} onClick={() => changeView('grid')} className={`rounded p-2 ${view === 'grid' ? 'bg-vault-accent/15 text-vault-accent' : 'text-vault-text-muted'}`}><Grid2X2 size={17} /></button>
        <button type="button" aria-label={t('explorer.listView')} onClick={() => changeView('list')} className={`rounded p-2 ${view === 'list' ? 'bg-vault-accent/15 text-vault-accent' : 'text-vault-text-muted'}`}><List size={18} /></button>
        <button type="button" aria-label={t('explorer.keyboardShortcuts')} title={t('explorer.keyboardShortcuts')} onClick={() => setShortcutsOpen(true)} className="hidden rounded p-2 text-vault-text-muted hover:bg-vault-card-hover sm:block"><Keyboard size={18} /></button>
        <select
          aria-label={t('explorer.libraryTree')}
          value={`${node.kind}:${node.id || ''}`}
          onChange={(event) => {
            const [kind, ...idParts] = event.target.value.split(':')
            const id = idParts.join(':')
            if (kind === 'root') navigate({ kind: 'root' })
            else if (kind === 'trash') navigate({ kind: 'trash', label: t('explorer.trash') })
            else if (kind === 'physical') navigate({ kind: 'physical', id, label: roots.physical.find((item) => String(item.id) === id)?.label })
            else navigate({ kind: kind as WorkbenchNode['kind'], id })
          }}
          className="w-full rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text lg:hidden"
        >
          <option value="root:">{t('explorer.library')}</option>
          <optgroup label={t('explorer.sources')}>{roots.virtual.sources.map((item) => <option key={item.id} value={`source:${item.id}`}>{item.label}</option>)}</optgroup>
          <optgroup label={t('explorer.collections')}>{roots.virtual.collections.items.map((item) => <option key={item.id} value={`collection:${item.id}`}>{item.name}</option>)}</optgroup>
          <optgroup label={t('explorer.artists')}>{roots.virtual.artists.items.map((item) => <option key={item.id} value={`artist:${item.id}`}>{item.name.replace(/^[^:]+:/, '')}</option>)}</optgroup>
          <optgroup label={t('explorer.savedSearches')}>{roots.virtual.saved_searches.items.map((item) => <option key={item.id} value={`saved_search:${item.id}`}>{item.name}</option>)}</optgroup>
          <optgroup label={t('explorer.smartViews')}><option value="smart:missing_metadata">{t('explorer.missingMetadata')}</option><option value="smart:duplicates">{t('explorer.duplicates')}</option><option value="trash:">{t('explorer.trash')}</option></optgroup>
          {roots.physical.length > 0 && <optgroup label={t('explorer.physicalLibraries')}>{roots.physical.map((item) => <option key={item.id} value={`physical:${item.id}`}>{item.label}</option>)}</optgroup>}
        </select>
      </header>

      {layout === 'finder' && (
        <div className="hidden items-stretch border-b border-vault-border bg-vault-card/50 lg:flex">
          {finderCrumbs.map((crumb, index) => (
            <button key={`${crumb.label}-${index}`} type="button" onClick={() => navigate(crumb.target)} className="flex min-w-[180px] items-center justify-between border-r border-vault-border px-4 py-2 text-sm text-vault-text"><span className="truncate">{crumb.label}</span><ChevronRight size={14} /></button>
          ))}
        </div>
      )}

      <div className={`min-h-0 flex-1 overflow-hidden ${layout === 'xnview' ? 'lg:grid lg:grid-cols-[260px_minmax(0,1fr)_300px]' : 'lg:grid lg:grid-cols-[420px_minmax(0,1fr)_300px]'}`}>
        <div className="hidden min-h-0 lg:block">{layout === 'xnview' ? <NavigationTree roots={roots} node={node} navigate={navigate} /> : <FinderColumns roots={roots} node={node} navigate={navigate} />}</div>
        <section data-explorer-content-pane className="flex h-full min-h-0 flex-col overflow-hidden">
          <div className="flex items-center gap-2 border-b border-vault-border px-4 py-2 text-sm">
            {node.kind !== 'root' && <button type="button" onClick={goBack} className="text-vault-accent">{t('explorer.backToRoot')}</button>}
            <FolderOpen size={16} className="text-vault-text-muted" />
            <span className="truncate font-medium text-vault-text">{currentLabel}{node.path ? ` / ${node.path}` : ''}</span>
            <span className="ml-auto text-xs text-vault-text-muted">{node.kind === 'physical' ? physical?.total ?? 0 : node.kind === 'root' ? rootItems.length : galleries?.total ?? galleryFiles?.total_files ?? 0}</span>
            {querySpec && (galleries?.total || 0) > 0 && (
              <button type="button" onClick={selectAllQuery} className="rounded border border-vault-border px-2 py-1 text-xs text-vault-text hover:bg-vault-card-hover">{t('explorer.selectAllResults')}</button>
            )}
            {node.kind === 'smart' && node.id === 'duplicates' && <button type="button" onClick={() => router.push('/dedup')} className="rounded border border-vault-border px-2 py-1 text-xs text-vault-text hover:bg-vault-card-hover">{t('explorer.reviewPairs')}</button>}
            {node.kind === 'physical' && <button type="button" aria-label={t('explorer.refreshSize')} onClick={async () => { await api.explorer.refreshPhysicalSize(physicalId, node.path || ''); await mutatePhysical() }} className="rounded p-1 text-vault-text-muted hover:bg-vault-card-hover"><RefreshCw size={15} /></button>}
          </div>

          {layout === 'finder' && activeItem && (
            <div className="hidden h-[42%] min-h-[240px] items-center justify-center border-b border-vault-border bg-black/20 p-5 lg:flex">
              {'id' in activeItem ? (
                activeItem.cover_thumb ? <img src={activeItem.cover_thumb} alt="" className="h-full max-w-full object-contain" /> : <Folder size={80} strokeWidth={1} className="text-vault-text-muted" />
              ) : activeItem.kind === 'media' ? (
                /\.(mp4|webm)$/i.test(activeItem.name)
                  ? <video controls src={api.explorer.physicalPreviewUrl(physicalId, activeItem.path)} className="h-full max-w-full" />
                  : <img src={api.explorer.physicalPreviewUrl(physicalId, activeItem.path)} alt={activeItem.name} className="h-full max-w-full object-contain" />
              ) : <Folder size={80} strokeWidth={1} className="text-vault-text-muted" />}
            </div>
          )}

          <div className="min-h-0 flex-1 overflow-y-auto pb-24 lg:pb-4">
            {node.kind === 'gallery' ? (
              <div ref={contentGridRef} className={view === 'grid' ? 'grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 xl:grid-cols-5' : 'p-2'}>
                {(galleryFiles?.files || []).map((file: LibraryFile, index: number) => (
                  <GalleryFileItem
                    key={file.filename}
                    file={file}
                    view={view}
                    coarse={coarse}
                    focused={focusedIndex === index}
                    tabIndex={focusedIndex === null ? (index === 0 ? 0 : -1) : (focusedIndex === index ? 0 : -1)}
                    elementRef={(element) => registerElement(index, element)}
                    onFocus={() => focusIndex(index)}
                    onOpen={() => router.push(readerHref(gallerySource, gallerySourceId, file.page_num || undefined))}
                  />
                ))}
              </div>
            ) : loading ? <div className="p-4"><SkeletonGrid /></div> : contentItems.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-vault-text-muted"><Folder size={42} strokeWidth={1.2} /><p>{t('explorer.emptyDir')}</p></div>
            ) : view === 'grid' ? (
              <div ref={contentGridRef} className="grid grid-cols-2 gap-3 p-3 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
                {contentItems.map((item, index) => <SelectableCard key={itemKey(item)} item={item} selected={isItemSelected(item)} selectionMode={selectedKeys.size > 0 || Boolean(querySelection)} coarse={coarse} view={view} previewUrl={'id' in item || item.kind !== 'media' ? undefined : api.explorer.physicalPreviewUrl(physicalId, item.path)} elementRef={(element) => registerElement(index, element)} tabIndex={focusedIndex === null ? (index === 0 ? 0 : -1) : (focusedIndex === index ? 0 : -1)} focused={focusedIndex === index} onFocus={() => focusIndex(index)} onSelect={(event) => selectItem(item, index, event)} onOpen={() => openItem(item)} />)}
              </div>
            ) : (
              <div ref={contentGridRef}>{contentItems.map((item, index) => <SelectableCard key={itemKey(item)} item={item} selected={isItemSelected(item)} selectionMode={selectedKeys.size > 0 || Boolean(querySelection)} coarse={coarse} view={view} previewUrl={'id' in item || item.kind !== 'media' ? undefined : api.explorer.physicalPreviewUrl(physicalId, item.path)} elementRef={(element) => registerElement(index, element)} tabIndex={focusedIndex === null ? (index === 0 ? 0 : -1) : (focusedIndex === index ? 0 : -1)} focused={focusedIndex === index} onFocus={() => focusIndex(index)} onSelect={(event) => selectItem(item, index, event)} onOpen={() => openItem(item)} />)}</div>
            )}
            {querySpec && galleries && galleries.total > galleries.limit && (
              <div className="flex items-center justify-center gap-3 p-4">
                <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - galleries.limit))} className="rounded-md border border-vault-border px-3 py-2 text-sm text-vault-text disabled:opacity-30">{t('common.prev')}</button>
                <span className="text-sm text-vault-text-muted">{offset + 1}–{Math.min(offset + galleries.limit, galleries.total)} / {galleries.total}</span>
                <button type="button" disabled={offset + galleries.limit >= galleries.total} onClick={() => setOffset(offset + galleries.limit)} className="rounded-md border border-vault-border px-3 py-2 text-sm text-vault-text disabled:opacity-30">{t('common.next')}</button>
              </div>
            )}
          </div>
        </section>
        <div className="hidden min-h-0 lg:block"><Inspector item={activeItem} physicalRoot={physicalRoot} /></div>
      </div>

      {effectiveSelectedCount > 0 && (
        <div className="fixed inset-x-2 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-50 flex max-w-[calc(100vw-1rem)] items-center gap-1 overflow-x-auto rounded-xl border border-vault-border bg-vault-card p-2 shadow-2xl lg:inset-x-auto lg:bottom-5 lg:left-1/2 lg:-translate-x-1/2">
          <button type="button" onClick={() => { setSelectedKeys(new Set()); setQuerySelection(null) }} className="rounded p-2 text-vault-text-muted"><X size={18} /></button>
          <span className="mr-2 whitespace-nowrap text-sm font-medium text-vault-text">{t('explorer.selectedCount', { count: effectiveSelectedCount })}</span>
          {selectedPhysicalFolders.length === 1 && !selectedPhysicalFolders[0].gallery_id && <button type="button" onClick={importSelectedFolder} className="flex items-center gap-1 rounded-md px-3 py-2 text-sm text-vault-text hover:bg-vault-card-hover"><Archive size={16} /><span className="hidden sm:inline">{t('explorer.importFolder')}</span></button>}
          <button type="button" disabled={!querySelection && selectedGalleries.length === 0} onClick={() => setMetadataOpen(true)} className="flex items-center gap-1 rounded-md px-3 py-2 text-sm text-vault-text hover:bg-vault-card-hover disabled:opacity-30"><Edit3 size={16} /><span className="hidden sm:inline">{t('explorer.editMetadata')}</span></button>
          <button type="button" disabled={Boolean(querySelection) || selectedGalleries.length < 2 || selectedGalleries.length > 50} onClick={() => setMergeOpen(true)} className="flex items-center gap-1 rounded-md px-3 py-2 text-sm text-vault-text hover:bg-vault-card-hover disabled:opacity-30"><Merge size={16} /><span className="hidden sm:inline">{t('explorer.merge')}</span></button>
          <button type="button" disabled={!querySelection && selectedGalleries.length === 0} onClick={() => setOrganizeOpen('tags')} className="flex items-center gap-1 rounded-md px-3 py-2 text-sm text-vault-text hover:bg-vault-card-hover disabled:opacity-30"><Tags size={16} /><span className="hidden sm:inline">{t('explorer.tags')}</span></button>
          <button type="button" disabled={!querySelection && selectedGalleries.length === 0} onClick={() => setOrganizeOpen('collections')} className="flex items-center gap-1 rounded-md px-3 py-2 text-sm text-vault-text hover:bg-vault-card-hover disabled:opacity-30"><Layers3 size={16} /><span className="hidden sm:inline">{t('explorer.collections')}</span></button>
          <button type="button" disabled={!querySelection && selectedGalleries.length === 0} onClick={() => void runQuickAction('favorite')} className="rounded-md p-2 text-vault-text hover:bg-vault-card-hover disabled:opacity-30" aria-label={t('explorer.favorite')}><Star size={16} /></button>
          <button type="button" disabled={!querySelection && selectedGalleries.length === 0} onClick={() => void runQuickAction('add_read_later')} className="rounded-md p-2 text-vault-text hover:bg-vault-card-hover disabled:opacity-30" aria-label={t('explorer.readLater')}><Archive size={16} /></button>
          <select aria-label={t('explorer.rating')} disabled={!querySelection && selectedGalleries.length === 0} defaultValue="" onChange={(event) => { if (event.target.value) void runQuickAction('rate', Number(event.target.value)); event.target.value = '' }} className="hidden rounded-md border border-vault-border bg-vault-card px-2 py-1 text-sm text-vault-text sm:block disabled:opacity-30"><option value="">{t('explorer.rating')}</option>{[0, 1, 2, 3, 4, 5].map((rating) => <option key={rating} value={rating}>{rating}</option>)}</select>
          <select aria-label={t('explorer.moreActions')} disabled={!querySelection && selectedGalleries.length === 0} defaultValue="" onChange={(event) => { const action = event.target.value as 'unfavorite' | 'remove_read_later'; if (action) void runQuickAction(action); event.target.value = '' }} className="rounded-md border border-vault-border bg-vault-card px-2 py-1 text-sm text-vault-text disabled:opacity-30"><option value="">{t('explorer.moreActions')}</option><option value="unfavorite">{t('explorer.unfavorite')}</option><option value="remove_read_later">{t('explorer.removeReadLater')}</option></select>
          <button type="button" disabled={!querySelection && selectedGalleries.length === 0} onClick={deleteSelection} className="flex items-center gap-1 rounded-md px-3 py-2 text-sm text-red-400 hover:bg-red-500/10 disabled:opacity-30"><Trash2 size={16} /><span className="hidden sm:inline">{t('explorer.deleteFiles')}</span></button>
        </div>
      )}

      {metadataOpen && <MetadataDialog selection={selectedGalleries} querySelection={querySelection} onClose={() => setMetadataOpen(false)} onDone={() => void refresh()} />}
      {mergeOpen && <MergeDialog selection={selectedGalleries} onClose={() => setMergeOpen(false)} onDone={() => void refresh()} />}
      {organizeOpen && <OrganizeDialog kind={organizeOpen} selectionBody={actionSelectionBody} onClose={() => setOrganizeOpen(null)} onDone={() => void refresh()} />}
      {shortcutsOpen && (
        <Modal title={t('explorer.keyboardShortcuts')} onClose={() => setShortcutsOpen(false)}>
          <div className="grid gap-2 p-5 text-sm">
            {[
              ['↑ ↓ ← → · Home · End', t('explorer.navigateItems')],
              ['Enter', t('explorer.openItem')],
              ['Space', t('explorer.toggleSelection')],
              ['Shift + ↑ ↓ ← →', t('explorer.extendSelection')],
              ['Ctrl/⌘ + A', t('explorer.selectAllResults')],
              ['Esc', t('explorer.clearSelection')],
              ['Backspace', t('explorer.back')],
              ['/ · Ctrl/⌘ + K', t('explorer.focusSearch')],
              ['Delete · ⌘ + Backspace', t('explorer.deleteFiles')],
              ['F2', t('explorer.editMetadata')],
              ['Alt + 1 / 2', t('explorer.switchLayout')],
              ['Ctrl/⌘ + 1 / 2', t('explorer.switchView')],
              ['F6', t('explorer.cyclePane')],
            ].map(([keys, label]) => (
              <div key={keys} className="flex items-center justify-between gap-5 rounded border border-vault-border px-3 py-2">
                <span className="text-vault-text-muted">{label}</span>
                <kbd className="whitespace-nowrap rounded bg-vault-bg px-2 py-1 font-mono text-xs text-vault-text">{keys}</kbd>
              </div>
            ))}
          </div>
        </Modal>
      )}
    </main>
  )
}
