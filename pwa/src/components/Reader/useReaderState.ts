'use client'
import { useCallback, useEffect, useReducer } from 'react'
import type { ReaderState, ReaderAction, ViewMode, ScaleMode, ReadingDirection } from './types'
import { nearestPage, stepPage } from './pageOrder'
import { loadReaderSettings, loadDirection, saveDirection } from './readerSettings'

// ── useReaderState ────────────────────────────────────────────────────

function readerReducer(state: ReaderState, action: ReaderAction): ReaderState {
  switch (action.type) {
    case 'SET_PAGE':
      return { ...state, currentPage: action.page }
    case 'SET_VIEW_MODE':
      return { ...state, viewMode: action.mode }
    case 'TOGGLE_OVERLAY':
      return { ...state, showOverlay: !state.showOverlay }
    case 'SHOW_OVERLAY':
      return { ...state, showOverlay: true }
    case 'HIDE_OVERLAY':
      return { ...state, showOverlay: false }
    case 'SET_SCALE_MODE':
      return { ...state, scaleMode: action.mode }
    case 'SET_READING_DIRECTION':
      return { ...state, readingDirection: action.direction }
    case 'SHOW_GRID':
      return { ...state, isGridOpen: true }
    case 'HIDE_GRID':
      return { ...state, isGridOpen: false }
    default:
      return state
  }
}

export function useReaderState(
  initialPage: number,
  totalPages: number,
  source: string,
  sourceId: string,
  /**
   * The pages that exist, sorted, once the set is final: navigation then walks
   * this list. Null while pages may still arrive (download in flight, EH proxy),
   * where a number missing from the list can be a page worth waiting on.
   */
  settledPages: readonly number[] | null = null,
) {
  const settings = loadReaderSettings()
  const savedDirection = loadDirection(source, sourceId)

  const [state, dispatch] = useReducer(readerReducer, {
    currentPage: settledPages ? nearestPage(settledPages, initialPage) : initialPage,
    viewMode: settings.defaultViewMode,
    showOverlay: false,
    scaleMode: settings.defaultScaleMode,
    readingDirection: savedDirection ?? settings.defaultReadingDirection,
    isGridOpen: false,
  } as ReaderState)

  const setPage = useCallback(
    (page: number) => {
      const target = settledPages
        ? nearestPage(settledPages, page)
        : Math.max(1, Math.min(totalPages, page))
      dispatch({ type: 'SET_PAGE', page: target })
    },
    [settledPages, totalPages],
  )

  const nextPage = useCallback(
    () =>
      setPage(settledPages ? stepPage(settledPages, state.currentPage, 1) : state.currentPage + 1),
    [settledPages, state.currentPage, setPage],
  )

  const prevPage = useCallback(
    () =>
      setPage(settledPages ? stepPage(settledPages, state.currentPage, -1) : state.currentPage - 1),
    [settledPages, state.currentPage, setPage],
  )

  // The current page can stop existing: a refresh after its file was deleted,
  // or a download settling with this page among the ones that failed.
  useEffect(() => {
    if (!settledPages) return
    const page = nearestPage(settledPages, state.currentPage)
    if (page !== state.currentPage) dispatch({ type: 'SET_PAGE', page })
  }, [settledPages, state.currentPage])

  const setViewMode = useCallback((mode: ViewMode) => dispatch({ type: 'SET_VIEW_MODE', mode }), [])

  const toggleOverlay = useCallback(() => dispatch({ type: 'TOGGLE_OVERLAY' }), [])

  const showGrid = useCallback(() => dispatch({ type: 'SHOW_GRID' }), [])

  const hideGrid = useCallback(() => dispatch({ type: 'HIDE_GRID' }), [])

  const setScaleMode = useCallback(
    (mode: ScaleMode) => dispatch({ type: 'SET_SCALE_MODE', mode }),
    [],
  )

  const setReadingDirection = useCallback(
    (direction: ReadingDirection) => {
      dispatch({ type: 'SET_READING_DIRECTION', direction })
      saveDirection(source, sourceId, direction)
    },
    [source, sourceId],
  )

  return {
    state,
    setPage,
    nextPage,
    prevPage,
    setViewMode,
    toggleOverlay,
    setScaleMode,
    setReadingDirection,
    showGrid,
    hideGrid,
  }
}
