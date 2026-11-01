'use client'

import { useCallback, useLayoutEffect, useMemo, useRef } from 'react'
import { useSearchParams } from 'next/navigation'

import type { ExplorerImageMedia, ExplorerImageSort, ExplorerImageVisibility, ExplorerQuery } from '@/lib/api/explorer'

import { canStepBackInHistory, commitExplorerUrl, stepBackInHistory } from './explorerHistory'

export type ExplorerNodeKind = 'root' | 'source' | 'category' | 'collection' | 'artist' | 'saved_search' | 'smart' | 'trash' | 'physical' | 'gallery'

export interface ExplorerNode {
  kind: ExplorerNodeKind
  id?: string
  path?: string
  source?: string
  sourceId?: string
  label?: string
}

type Sort = NonNullable<ExplorerQuery['sort']>
type Direction = NonNullable<ExplorerQuery['direction']>

export interface ExplorerRefinements {
  q: string
  offset: number
  cat: string | null
  sort: Sort
  dir: Direction
  ivis: ExplorerImageVisibility
  imedia: ExplorerImageMedia
  isort: ExplorerImageSort
  idir: Direction
  ioffset: number
}

export type ExplorerPatch = Partial<ExplorerRefinements> & { view?: 'grid' | 'list' }

const DEFAULTS: ExplorerRefinements = {
  q: '',
  offset: 0,
  cat: null,
  sort: 'added_at',
  dir: 'desc',
  ivis: 'active',
  imedia: 'all',
  isort: 'page',
  idir: 'asc',
  ioffset: 0,
}

const SORTS: readonly Sort[] = ['added_at', 'content_updated_at', 'posted_at', 'title', 'rating', 'pages', 'size']
const DIRECTIONS: readonly Direction[] = ['asc', 'desc']
const VISIBILITIES: readonly ExplorerImageVisibility[] = ['active', 'hidden', 'all']
const MEDIAS: readonly ExplorerImageMedia[] = ['all', 'image', 'video', 'gif']
const IMAGE_SORTS: readonly ExplorerImageSort[] = ['page', 'size']

function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}

function count(value: string | null): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0
}

export function nodeFromParams(params: URLSearchParams): ExplorerNode {
  return {
    kind: (params.get('kind') || 'root') as ExplorerNodeKind,
    id: params.get('id') || undefined,
    path: params.get('path') || undefined,
    source: params.get('source') || undefined,
    sourceId: params.get('sourceId') || undefined,
    label: params.get('label') || undefined,
  }
}

function refinementsFromParams(params: URLSearchParams): ExplorerRefinements {
  return {
    q: params.get('q') || '',
    offset: count(params.get('offset')),
    cat: params.get('cat') || null,
    sort: pick(params.get('sort'), SORTS, DEFAULTS.sort),
    dir: pick(params.get('dir'), DIRECTIONS, DEFAULTS.dir),
    ivis: pick(params.get('ivis'), VISIBILITIES, DEFAULTS.ivis),
    imedia: pick(params.get('imedia'), MEDIAS, DEFAULTS.imedia),
    isort: pick(params.get('isort'), IMAGE_SORTS, DEFAULTS.isort),
    idir: pick(params.get('idir'), DIRECTIONS, DEFAULTS.idir),
    ioffset: count(params.get('ioffset')),
  }
}

/** Params that survive a node change so the user can, for example, look at
 *  uncategorized galleries across several sources. */
const CARRIED_PARAMS = ['cat', 'sort', 'dir'] as const

function urlOf(search: string): string {
  return `/explorer${search ? `?${search}` : ''}`
}

function applyPatch(params: URLSearchParams, patch: ExplorerPatch): void {
  for (const key of Object.keys(DEFAULTS) as Array<keyof ExplorerRefinements>) {
    if (!(key in patch)) continue
    const value = patch[key]
    if (value === undefined || value === null || value === DEFAULTS[key]) params.delete(key)
    else params.set(key, String(value))
  }
  if (patch.view) params.set('view', patch.view)
}

/** The Explorer's single source of truth: node, filters, sort, paging and the
 *  image pane's filters all live in the URL. Refinements replace the current
 *  history entry; node changes push a new one. */
export function useExplorerUrlState() {
  const params = useSearchParams()
  const search = params.toString()
  const searchRef = useRef(search)
  useLayoutEffect(() => { searchRef.current = search }, [search])

  const state = useMemo(() => {
    const parsed = new URLSearchParams(search)
    return { node: nodeFromParams(parsed), viewParam: parsed.get('view'), ...refinementsFromParams(parsed) }
  }, [search])

  const refine = useCallback((patch: ExplorerPatch) => {
    const from = searchRef.current
    const next = new URLSearchParams(from)
    applyPatch(next, patch)
    const to = next.toString()
    searchRef.current = to
    commitExplorerUrl(urlOf(from), urlOf(to), 'replace')
  }, [])

  const pushNode = useCallback((node: ExplorerNode, view: 'grid' | 'list') => {
    const from = searchRef.current
    const current = new URLSearchParams(from)
    const next = new URLSearchParams()
    next.set('view', view)
    if (node.kind !== 'root') next.set('kind', node.kind)
    if (node.id) next.set('id', node.id)
    if (node.path) next.set('path', node.path)
    if (node.source) next.set('source', node.source)
    if (node.sourceId) next.set('sourceId', node.sourceId)
    if (node.label) next.set('label', node.label)
    for (const key of CARRIED_PARAMS) {
      const value = current.get(key)
      if (value) next.set(key, value)
    }
    const to = next.toString()
    searchRef.current = to
    commitExplorerUrl(urlOf(from), urlOf(to), 'push')
  }, [])

  /** Workbench back: return to the list we pushed from when history has it,
   *  otherwise push `fallback` (the node's parent). */
  const stepBack = useCallback((fallback: ExplorerNode, view: 'grid' | 'list') => {
    if (canStepBackInHistory(urlOf(searchRef.current))) {
      stepBackInHistory()
      return
    }
    pushNode(fallback, view)
  }, [pushNode])

  return { ...state, urlKey: urlOf(search), refine, pushNode, stepBack }
}
