import { canonicalIdentityKey } from './identity'

export type BrowsePageResult<Item, Cursor> = {
  items: Item[]
  cursor: Cursor | null
  hasMore: boolean
  total: number | null
  meta?: unknown
}

export type BrowseHydration<Item, Cursor> = {
  pages: Item[][]
  cursor: Cursor | null
  hasMore: boolean
  total: number | null
  meta?: unknown
}

export type BrowseRequestKind = 'initial' | 'append' | 'refresh'

export type BrowseRequestPlan<Cursor> =
  | { kind: 'initial'; cursor: null; targetDepth: 1 }
  | { kind: 'append'; cursor: Cursor | null; targetDepth: 1 }
  | { kind: 'refresh'; cursor: null; targetDepth: number }

export type BrowseState<Item, Cursor> = BrowseHydration<Item, Cursor> & {
  identityKey: string
  items: Item[]
  generation: number
  status: 'idle' | 'loading' | 'error'
  error: Error | null
  requestKind: BrowseRequestKind | null
  failedRequest: BrowseRequestPlan<Cursor> | null
  terminal: { kind: 'expired'; replayable: boolean } | null
  meta: unknown
}

export type BrowseAction<Item, Cursor> =
  | { type: 'HYDRATE'; snapshot: BrowseHydration<Item, Cursor> }
  | { type: 'IDENTITY_CHANGED'; identityKey: string; generation?: number }
  | { type: 'REQUEST_STARTED'; generation?: number; request?: BrowseRequestPlan<Cursor> }
  | {
      type: 'PAGE_SUCCEEDED'
      identityKey: string
      generation: number
      mode: 'replace' | 'append'
      page: BrowsePageResult<Item, Cursor>
    }
  | {
      type: 'BUFFER_SUCCEEDED'
      identityKey: string
      generation: number
      buffer: BrowseHydration<Item, Cursor>
    }
  | {
      type: 'PAGE_FAILED'
      identityKey: string
      generation: number
      error: Error
      request?: BrowseRequestPlan<Cursor>
    }
  | { type: 'TERMINAL_EXPIRED'; replayable: boolean; generation?: number }

export function createBrowseState<Item, Cursor>(identityKey: string): BrowseState<Item, Cursor> {
  return {
    identityKey,
    pages: [],
    items: [],
    cursor: null,
    hasMore: true,
    total: null,
    generation: 0,
    status: 'idle',
    error: null,
    requestKind: null,
    failedRequest: null,
    terminal: null,
    meta: null,
  }
}

function cursorMatches<Cursor>(left: Cursor | null, right: Cursor | null): boolean {
  return canonicalIdentityKey(left) === canonicalIdentityKey(right)
}

export function createBrowseReducer<Item, Cursor>(getItemId: (item: Item) => string | number) {
  function unique(items: readonly Item[], seen = new Set<string | number>()): Item[] {
    const result: Item[] = []
    for (const item of items) {
      const id = getItemId(item)
      if (seen.has(id)) continue
      seen.add(id)
      result.push(item)
    }
    return result
  }

  return function browseReducer(
    state: BrowseState<Item, Cursor>,
    action: BrowseAction<Item, Cursor>,
  ): BrowseState<Item, Cursor> {
    switch (action.type) {
      case 'HYDRATE': {
        const pages = action.snapshot.pages.map((page) => [...page])
        return {
          ...state,
          ...action.snapshot,
          pages,
          items: unique(pages.flat()),
          status: 'idle',
          error: null,
          requestKind: null,
          failedRequest: null,
          terminal: null,
        }
      }
      case 'IDENTITY_CHANGED':
        return {
          ...createBrowseState<Item, Cursor>(action.identityKey),
          generation: action.generation ?? state.generation + 1,
        }
      case 'REQUEST_STARTED':
        return {
          ...state,
          generation: action.generation ?? state.generation + 1,
          status: 'loading',
          error: null,
          requestKind: action.request?.kind ?? null,
          failedRequest: null,
          terminal: null,
        }
      case 'PAGE_SUCCEEDED': {
        if (
          action.identityKey !== state.identityKey ||
          action.generation !== state.generation
        ) {
          return state
        }
        if (action.mode === 'replace') {
          const fresh = unique(action.page.items)
          return {
            ...state,
            pages: [fresh],
            items: fresh,
            cursor: action.page.cursor,
            hasMore: action.page.hasMore,
            total: action.page.total,
            status: 'idle',
            error: null,
            requestKind: null,
            failedRequest: null,
            terminal: null,
            meta: action.page.meta ?? state.meta,
          }
        }

        const seen = new Set(state.items.map(getItemId))
        const fresh = unique(action.page.items, seen)
        const cursorAdvanced = !cursorMatches(state.cursor, action.page.cursor)
        return {
          ...state,
          pages: [...state.pages, fresh],
          items: [...state.items, ...fresh],
          cursor: action.page.cursor,
          hasMore: fresh.length === 0 && !cursorAdvanced ? false : action.page.hasMore,
          total: action.page.total,
          status: 'idle',
          error: null,
          requestKind: null,
          failedRequest: null,
          terminal: null,
          meta: action.page.meta ?? state.meta,
        }
      }
      case 'BUFFER_SUCCEEDED': {
        if (
          action.identityKey !== state.identityKey ||
          action.generation !== state.generation
        ) {
          return state
        }
        const seen = new Set<string | number>()
        const pages = action.buffer.pages.map((page) => unique(page, seen))
        return {
          ...state,
          ...action.buffer,
          pages,
          items: pages.flat(),
          status: 'idle',
          error: null,
          requestKind: null,
          failedRequest: null,
          terminal: null,
          meta: action.buffer.meta ?? state.meta,
        }
      }
      case 'PAGE_FAILED':
        if (
          action.identityKey !== state.identityKey ||
          action.generation !== state.generation
        ) {
          return state
        }
        return {
          ...state,
          status: 'error',
          error: action.error,
          requestKind: null,
          failedRequest: action.request ?? null,
        }
      case 'TERMINAL_EXPIRED':
        return {
          ...state,
          generation: action.generation ?? state.generation,
          status: 'idle',
          error: null,
          requestKind: null,
          failedRequest: null,
          terminal: { kind: 'expired', replayable: action.replayable },
          pages: [],
          items: [],
          cursor: null,
          hasMore: false,
          total: null,
        }
    }
  }
}
