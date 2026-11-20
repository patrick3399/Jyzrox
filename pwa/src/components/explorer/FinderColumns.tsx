'use client'

import {
  AlertTriangle,
  Archive,
  ChevronRight,
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

import {
  CategoryNavItems,
  NavButton,
  UNCATEGORIZED_ID,
  handleNavigationKeyDown,
} from './ExplorerNavigation'

type WorkbenchNode = ExplorerNode

export function FinderColumns({
  roots,
  node,
  navigate,
}: {
  roots: ExplorerRoots
  node: WorkbenchNode
  navigate: (node: WorkbenchNode) => void
}) {
  const section =
    node.kind === 'source'
      ? 'sources'
      : node.kind === 'collection'
        ? 'collections'
        : node.kind === 'artist'
          ? 'artists'
          : node.kind === 'saved_search'
            ? 'searches'
            : node.kind === 'category'
              ? 'categories'
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
    ...(roots.virtual.categories
      ? [{ id: 'categories', label: t('explorer.categories'), Icon: Tags }]
      : []),
    { id: 'smart', label: t('explorer.smartViews'), Icon: AlertTriangle },
    { id: 'physical', label: t('explorer.physicalLibraries'), Icon: HardDrive },
  ]
  return (
    <nav
      data-explorer-navigation
      onKeyDown={handleNavigationKeyDown}
      className="grid h-full grid-cols-2 overflow-hidden border-r border-vault-border bg-vault-card/40"
      aria-label={t('explorer.finderColumns')}
    >
      <div
        data-explorer-nav-pane="sections"
        className="overflow-y-auto border-r border-vault-border p-2"
      >
        {sections.map(({ id, label, Icon }) => (
          <button
            key={id}
            type="button"
            aria-current={section === id ? 'page' : undefined}
            onClick={() => {
              if (id === 'sources' && roots.virtual.sources[0])
                navigate({
                  kind: 'source',
                  id: roots.virtual.sources[0].id,
                  label: roots.virtual.sources[0].label,
                })
              else if (id === 'collections' && roots.virtual.collections.items[0])
                navigate({
                  kind: 'collection',
                  id: String(roots.virtual.collections.items[0].id),
                  label: roots.virtual.collections.items[0].name,
                })
              else if (id === 'artists' && roots.virtual.artists.items[0])
                navigate({
                  kind: 'artist',
                  id: roots.virtual.artists.items[0].id,
                  label: roots.virtual.artists.items[0].name,
                })
              else if (id === 'searches' && roots.virtual.saved_searches.items[0])
                navigate({
                  kind: 'saved_search',
                  id: String(roots.virtual.saved_searches.items[0].id),
                  label: roots.virtual.saved_searches.items[0].name,
                })
              else if (id === 'categories')
                navigate({
                  kind: 'category',
                  id: UNCATEGORIZED_ID,
                  label: t('explorer.uncategorized'),
                })
              else if (id === 'smart')
                navigate({
                  kind: 'smart',
                  id: 'missing_metadata',
                  label: t('explorer.missingMetadata'),
                })
              else if (id === 'physical' && roots.physical[0])
                navigate({
                  kind: 'physical',
                  id: String(roots.physical[0].id),
                  label: roots.physical[0].label,
                })
            }}
            className={`flex w-full items-center gap-2 rounded px-2 py-2 text-left text-sm ${section === id ? 'bg-vault-accent/15 text-vault-accent' : 'text-vault-text hover:bg-vault-card-hover'}`}
          >
            <Icon size={15} />
            <span className="min-w-0 flex-1 truncate">{label}</span>
            <ChevronRight size={14} />
          </button>
        ))}
      </div>
      <div data-explorer-nav-pane="items" className="overflow-y-auto p-2">
        {section === 'sources' &&
          roots.virtual.sources.map((item) => (
            <NavButton
              key={item.id}
              active={node.id === item.id}
              icon={Archive}
              label={item.label}
              count={item.gallery_count}
              onClick={() => navigate({ kind: 'source', id: item.id, label: item.label })}
            />
          ))}
        {section === 'collections' &&
          roots.virtual.collections.items.map((item) => (
            <NavButton
              key={item.id}
              active={node.id === String(item.id)}
              icon={Layers3}
              label={item.name}
              count={item.gallery_count}
              onClick={() =>
                navigate({ kind: 'collection', id: String(item.id), label: item.name })
              }
            />
          ))}
        {section === 'artists' &&
          roots.virtual.artists.items.map((item) => (
            <NavButton
              key={item.id}
              active={node.id === item.id}
              icon={Users}
              label={item.name.replace(/^[^:]+:/, '')}
              count={item.gallery_count}
              onClick={() => navigate({ kind: 'artist', id: item.id, label: item.name })}
            />
          ))}
        {section === 'searches' &&
          roots.virtual.saved_searches.items.map((item) => (
            <NavButton
              key={item.id}
              active={node.id === String(item.id)}
              icon={Search}
              label={item.name}
              onClick={() =>
                navigate({ kind: 'saved_search', id: String(item.id), label: item.name })
              }
            />
          ))}
        {section === 'categories' && (
          <CategoryNavItems roots={roots} node={node} navigate={navigate} />
        )}
        {section === 'smart' && (
          <>
            <NavButton
              active={node.id === 'missing_metadata'}
              icon={AlertTriangle}
              label={t('explorer.missingMetadata')}
              onClick={() =>
                navigate({
                  kind: 'smart',
                  id: 'missing_metadata',
                  label: t('explorer.missingMetadata'),
                })
              }
            />
            <NavButton
              active={node.id === 'duplicates'}
              icon={Merge}
              label={t('explorer.duplicates')}
              onClick={() =>
                navigate({ kind: 'smart', id: 'duplicates', label: t('explorer.duplicates') })
              }
            />
            <NavButton
              active={node.id === 'hidden_images'}
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
          </>
        )}
        {section === 'physical' &&
          roots.physical.map((item) => (
            <NavButton
              key={item.id}
              active={node.id === String(item.id)}
              icon={HardDrive}
              label={item.label}
              onClick={() => navigate({ kind: 'physical', id: String(item.id), label: item.label })}
            />
          ))}
      </div>
    </nav>
  )
}
