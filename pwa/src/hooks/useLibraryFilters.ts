'use client'

import { useReducer, useEffect, useRef, useCallback } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'

export type SortValue = 'added_at' | 'rating' | 'pages'

export interface FilterState {
  searchQuery: string
  searchInput: string
  includeTags: string[]
  excludeTags: string[]
  includeInput: string
  excludeInput: string
  minRating: number | undefined
  onlyFavorited: boolean
  sourceFilter: string
  artistFilter: string
  sort: SortValue
  collectionFilter: number | undefined
  categoryFilter: string
  selectMode: boolean
  selectedIds: Set<number>
}

export type FilterAction =
  | { type: 'SET_SEARCH_INPUT'; payload: string }
  | { type: 'SET_SEARCH_QUERY'; payload: string }
  | { type: 'ADD_INCLUDE_TAG'; payload: string }
  | { type: 'REMOVE_INCLUDE_TAG'; payload: string }
  | { type: 'SET_INCLUDE_INPUT'; payload: string }
  | { type: 'ADD_EXCLUDE_TAG'; payload: string }
  | { type: 'REMOVE_EXCLUDE_TAG'; payload: string }
  | { type: 'SET_EXCLUDE_INPUT'; payload: string }
  | { type: 'SET_MIN_RATING'; payload: number | undefined }
  | { type: 'SET_ONLY_FAVORITED'; payload: boolean }
  | { type: 'SET_SOURCE_FILTER'; payload: string }
  | { type: 'SET_ARTIST_FILTER'; payload: string }
  | { type: 'SET_SORT'; payload: SortValue }
  | { type: 'SET_COLLECTION_FILTER'; payload: number | undefined }
  | { type: 'SET_CATEGORY'; payload: string }
  | { type: 'SET_SELECT_MODE'; payload: boolean }
  | { type: 'SET_SELECTED_IDS'; payload: Set<number> }
  | { type: 'TOGGLE_SELECTED_ID'; payload: number }
  | { type: 'CLEAR_SELECTION' }

function filterReducer(state: FilterState, action: FilterAction): FilterState {
  switch (action.type) {
    case 'SET_SEARCH_INPUT':
      return { ...state, searchInput: action.payload }
    case 'SET_SEARCH_QUERY':
      return { ...state, searchQuery: action.payload }
    case 'ADD_INCLUDE_TAG': {
      const tag = action.payload.trim()
      if (!tag || state.includeTags.includes(tag)) {
        return { ...state, includeInput: '' }
      }
      return { ...state, includeTags: [...state.includeTags, tag], includeInput: '' }
    }
    case 'REMOVE_INCLUDE_TAG':
      return { ...state, includeTags: state.includeTags.filter((t) => t !== action.payload) }
    case 'SET_INCLUDE_INPUT':
      return { ...state, includeInput: action.payload }
    case 'ADD_EXCLUDE_TAG': {
      const tag = action.payload.trim()
      if (!tag || state.excludeTags.includes(tag)) {
        return { ...state, excludeInput: '' }
      }
      return { ...state, excludeTags: [...state.excludeTags, tag], excludeInput: '' }
    }
    case 'REMOVE_EXCLUDE_TAG':
      return { ...state, excludeTags: state.excludeTags.filter((t) => t !== action.payload) }
    case 'SET_EXCLUDE_INPUT':
      return { ...state, excludeInput: action.payload }
    case 'SET_MIN_RATING':
      return { ...state, minRating: action.payload }
    case 'SET_ONLY_FAVORITED':
      return { ...state, onlyFavorited: action.payload }
    case 'SET_SOURCE_FILTER':
      return { ...state, sourceFilter: action.payload }
    case 'SET_ARTIST_FILTER':
      return { ...state, artistFilter: action.payload }
    case 'SET_SORT':
      return { ...state, sort: action.payload }
    case 'SET_COLLECTION_FILTER':
      return { ...state, collectionFilter: action.payload }
    case 'SET_CATEGORY':
      return { ...state, categoryFilter: action.payload }
    case 'SET_SELECT_MODE':
      return { ...state, selectMode: action.payload }
    case 'SET_SELECTED_IDS':
      return { ...state, selectedIds: action.payload }
    case 'TOGGLE_SELECTED_ID': {
      const next = new Set(state.selectedIds)
      if (next.has(action.payload)) {
        next.delete(action.payload)
      } else {
        next.add(action.payload)
      }
      return { ...state, selectedIds: next }
    }
    case 'CLEAR_SELECTION':
      return { ...state, selectedIds: new Set(), selectMode: false }
    default:
      return state
  }
}

function initFilterState(searchParams: URLSearchParams): FilterState {
  return {
    searchQuery: searchParams.get('q') ?? '',
    searchInput: searchParams.get('q') ?? '',
    includeTags: searchParams.get('tags')?.split(',').filter(Boolean) ?? [],
    excludeTags: searchParams.get('notags')?.split(',').filter(Boolean) ?? [],
    includeInput: '',
    excludeInput: '',
    minRating: searchParams.get('rating') ? Number(searchParams.get('rating')) : undefined,
    onlyFavorited: searchParams.get('fav') === '1',
    sourceFilter: searchParams.get('source') ?? '',
    artistFilter: searchParams.get('artist') ?? '',
    sort: (searchParams.get('sort') as SortValue) ?? 'added_at',
    collectionFilter: undefined,
    categoryFilter: searchParams.get('category') ?? '',
    selectMode: false,
    selectedIds: new Set(),
  }
}

export function useLibraryFilters() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [state, dispatch] = useReducer(
    filterReducer,
    searchParams,
    initFilterState,
  )

  // Debounced URL sync — 500ms after last relevant state change
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      const params = new URLSearchParams()
      if (state.searchQuery) params.set('q', state.searchQuery)
      if (state.sourceFilter) params.set('source', state.sourceFilter)
      if (state.sort !== 'added_at') params.set('sort', state.sort)
      if (state.minRating !== undefined) params.set('rating', String(state.minRating))
      if (state.onlyFavorited) params.set('fav', '1')
      if (state.artistFilter) params.set('artist', state.artistFilter)
      if (state.categoryFilter) params.set('category', state.categoryFilter)
      if (state.includeTags.length > 0) params.set('tags', state.includeTags.join(','))
      if (state.excludeTags.length > 0) params.set('notags', state.excludeTags.join(','))

      const qs = params.toString()
      const newUrl = qs ? `/library?${qs}` : '/library'
      router.replace(newUrl, { scroll: false })
    }, 500)

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [
    state.searchQuery,
    state.sourceFilter,
    state.sort,
    state.minRating,
    state.onlyFavorited,
    state.artistFilter,
    state.categoryFilter,
    state.includeTags,
    state.excludeTags,
    router,
  ])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  // Derived: parsed source filter
  const [parsedSource, parsedImportMode] = (() => {
    if (!state.sourceFilter) return [undefined, undefined]
    const colonIdx = state.sourceFilter.indexOf(':')
    if (colonIdx === -1) return [state.sourceFilter, undefined]
    return [state.sourceFilter.slice(0, colonIdx), state.sourceFilter.slice(colonIdx + 1)]
  })()

  // Convenience search handler with 400ms debounce for the query itself
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const handleSearchChange = useCallback((value: string) => {
    dispatch({ type: 'SET_SEARCH_INPUT', payload: value })
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
    searchDebounceRef.current = setTimeout(() => {
      dispatch({ type: 'SET_SEARCH_QUERY', payload: value })
    }, 400)
  }, [])

  const handleSearchCommit = useCallback((value: string) => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
    dispatch({ type: 'SET_SEARCH_QUERY', payload: value })
  }, [])

  return {
    state,
    dispatch,
    parsedSource,
    parsedImportMode,
    handleSearchChange,
    handleSearchCommit,
  }
}
