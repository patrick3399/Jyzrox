'use client'

import { type KeyboardEvent as ReactKeyboardEvent } from 'react'
import {
  AlertTriangle,
  Archive,
  Database,
  Folder,
  HardDrive,
  EyeOff,
  Layers3,
  Merge,
  Search,
  Tags,
  Trash2,
  Users,
} from 'lucide-react'
import { type ExplorerNode } from '@/hooks/useExplorerUrlState'
import type { ExplorerRoots } from '@/lib/api'
import { t } from '@/lib/i18n'

type WorkbenchNode = ExplorerNode

export function NavButton({
  active,
  icon: Icon,
  label,
  count,
  emphasize,
  muted,
  title,
  onClick,
}: {
  active?: boolean
  icon: typeof Folder
  label: string
  count?: number
  emphasize?: boolean
  muted?: boolean
  title?: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-current={active ? 'page' : undefined}
      title={title}
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
        active
          ? 'bg-vault-accent/15 text-vault-accent'
          : 'text-vault-text hover:bg-vault-card-hover'
      }`}
    >
      <Icon size={15} className="shrink-0" />
      <span className={`min-w-0 flex-1 truncate ${muted ? 'italic text-vault-text-muted' : ''}`}>
        {label}
      </span>
      {count !== undefined && (
        <span
          className={`text-xs ${emphasize ? 'font-semibold text-vault-accent' : 'text-vault-text-muted'}`}
        >
          {count}
        </span>
      )}
    </button>
  )
}

export const UNCATEGORIZED_ID = '__uncategorized__'

export function categoryNodeLabel(id: string | undefined): string {
  return id === UNCATEGORIZED_ID ? t('explorer.uncategorized') : (id ?? '')
}

export function CategoryNavItems({
  roots,
  node,
  navigate,
}: {
  roots: ExplorerRoots
  node: WorkbenchNode
  navigate: (node: WorkbenchNode) => void
}) {
  const categories = roots.virtual.categories
  if (!categories) return null
  return (
    <>
      <NavButton
        active={node.kind === 'category' && node.id === UNCATEGORIZED_ID}
        icon={Tags}
        label={t('explorer.uncategorized')}
        count={categories.uncategorized}
        emphasize={categories.uncategorized > 0}
        onClick={() =>
          navigate({ kind: 'category', id: UNCATEGORIZED_ID, label: t('explorer.uncategorized') })
        }
      />
      {categories.items.map((item) => (
        <NavButton
          key={item.id}
          active={node.kind === 'category' && node.id === item.id}
          icon={Tags}
          label={item.label}
          count={item.gallery_count}
          muted={!item.registered}
          title={item.registered ? undefined : t('explorer.unregisteredCategory')}
          onClick={() => navigate({ kind: 'category', id: item.id, label: item.label })}
        />
      ))}
    </>
  )
}

export function handleNavigationKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
  if (!(event.target instanceof HTMLButtonElement)) return
  const navigation = event.currentTarget
  const pane = event.target.closest<HTMLElement>('[data-explorer-nav-pane]') ?? navigation
  const paneName = pane.dataset.explorerNavPane
  if (event.key === 'ArrowRight' && paneName === 'sections') {
    event.preventDefault()
    event.target.click()
    window.requestAnimationFrame(() => {
      navigation
        .querySelector<HTMLButtonElement>('[data-explorer-nav-pane="items"] button')
        ?.focus()
    })
    return
  }
  if (event.key === 'ArrowLeft' && paneName === 'items') {
    event.preventDefault()
    const sectionPane = navigation.querySelector<HTMLElement>('[data-explorer-nav-pane="sections"]')
    const sectionButton =
      sectionPane?.querySelector<HTMLButtonElement>('button[aria-current="page"]') ??
      sectionPane?.querySelector<HTMLButtonElement>('button')
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

export function NavigationTree({
  roots,
  node,
  navigate,
}: {
  roots: ExplorerRoots
  node: WorkbenchNode
  navigate: (node: WorkbenchNode) => void
}) {
  return (
    <nav
      data-explorer-navigation
      data-explorer-nav-pane
      onKeyDown={handleNavigationKeyDown}
      className="h-full overflow-y-auto border-r border-vault-border bg-vault-card/40 p-3"
      aria-label={t('explorer.libraryTree')}
    >
      <NavButton
        active={node.kind === 'root'}
        icon={Database}
        label={t('explorer.library')}
        onClick={() => navigate({ kind: 'root' })}
      />
      <p className="mb-1 mt-4 px-2 text-[11px] font-semibold uppercase tracking-wider text-vault-text-muted">
        {t('explorer.sources')}
      </p>
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
      <p className="mb-1 mt-4 px-2 text-[11px] font-semibold uppercase tracking-wider text-vault-text-muted">
        {t('explorer.organize')}
      </p>
      {roots.virtual.collections.items.map((collection) => (
        <NavButton
          key={collection.id}
          active={node.kind === 'collection' && node.id === String(collection.id)}
          icon={Layers3}
          label={collection.name}
          count={collection.gallery_count}
          onClick={() =>
            navigate({ kind: 'collection', id: String(collection.id), label: collection.name })
          }
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
          onClick={() =>
            navigate({ kind: 'saved_search', id: String(search.id), label: search.name })
          }
        />
      ))}
      {roots.virtual.categories && (
        <>
          <p className="mb-1 mt-4 px-2 text-[11px] font-semibold uppercase tracking-wider text-vault-text-muted">
            {t('explorer.categories')}
          </p>
          <CategoryNavItems roots={roots} node={node} navigate={navigate} />
        </>
      )}
      <p className="mb-1 mt-4 px-2 text-[11px] font-semibold uppercase tracking-wider text-vault-text-muted">
        {t('explorer.smartViews')}
      </p>
      <NavButton
        active={node.kind === 'smart' && node.id === 'missing_metadata'}
        icon={AlertTriangle}
        label={t('explorer.missingMetadata')}
        count={roots.virtual.smart_views.missing_metadata}
        onClick={() =>
          navigate({ kind: 'smart', id: 'missing_metadata', label: t('explorer.missingMetadata') })
        }
      />
      <NavButton
        active={node.kind === 'smart' && node.id === 'duplicates'}
        icon={Merge}
        label={t('explorer.duplicates')}
        count={roots.virtual.smart_views.duplicate_pairs}
        onClick={() =>
          navigate({ kind: 'smart', id: 'duplicates', label: t('explorer.duplicates') })
        }
      />
      <NavButton
        active={node.kind === 'smart' && node.id === 'hidden_images'}
        icon={EyeOff}
        label={t('explorer.hiddenImages')}
        count={roots.virtual.smart_views.hidden_images ?? 0}
        onClick={() =>
          navigate({ kind: 'smart', id: 'hidden_images', label: t('explorer.hiddenImages') })
        }
      />
      <NavButton
        active={node.kind === 'trash'}
        icon={Trash2}
        label={t('explorer.trash')}
        onClick={() => navigate({ kind: 'trash', label: t('explorer.trash') })}
      />
      {roots.physical.length > 0 && (
        <p className="mb-1 mt-4 px-2 text-[11px] font-semibold uppercase tracking-wider text-vault-text-muted">
          {t('explorer.physicalLibraries')}
        </p>
      )}
      {roots.physical.map((library) => (
        <NavButton
          key={library.id}
          active={node.kind === 'physical' && node.id === String(library.id)}
          icon={HardDrive}
          label={library.label}
          onClick={() =>
            navigate({ kind: 'physical', id: String(library.id), label: library.label, path: '' })
          }
        />
      ))}
    </nav>
  )
}
