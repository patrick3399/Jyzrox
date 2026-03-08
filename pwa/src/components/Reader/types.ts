export type ViewMode = 'single' | 'webtoon' | 'double'

export type ScaleMode = 'fit-both' | 'fit-width' | 'fit-height' | 'original'

export type ReadingDirection = 'ltr' | 'rtl' | 'ttb'

export interface ReaderImage {
  pageNum: number // 1-indexed
  url: string // resolved URL (local path or proxy API)
  isLocal: boolean // true = served from /media/gallery/
  width?: number
  height?: number
  mediaType: 'image' | 'video' | 'gif'
}

export interface ReaderState {
  currentPage: number // 1-indexed
  viewMode: ViewMode
  showOverlay: boolean // show top/bottom controls
  scaleMode: ScaleMode
  readingDirection: ReadingDirection
}

export type ReaderAction =
  | { type: 'SET_PAGE'; page: number }
  | { type: 'SET_VIEW_MODE'; mode: ViewMode }
  | { type: 'TOGGLE_OVERLAY' }
  | { type: 'SHOW_OVERLAY' }
  | { type: 'HIDE_OVERLAY' }
  | { type: 'SET_SCALE_MODE'; mode: ScaleMode }
  | { type: 'SET_READING_DIRECTION'; direction: ReadingDirection }

// localStorage-persisted reader settings (from settings page)
export interface ReaderSettings {
  autoAdvanceEnabled: boolean
  autoAdvanceSeconds: number // 2-30
  statusBarEnabled: boolean
  statusBarShowClock: boolean
  statusBarShowProgress: boolean
  statusBarShowPageCount: boolean
  defaultViewMode: ViewMode
  defaultReadingDirection: ReadingDirection
  defaultScaleMode: ScaleMode
}

export const DEFAULT_READER_SETTINGS: ReaderSettings = {
  autoAdvanceEnabled: false,
  autoAdvanceSeconds: 5,
  statusBarEnabled: true,
  statusBarShowClock: true,
  statusBarShowProgress: true,
  statusBarShowPageCount: true,
  defaultViewMode: 'single',
  defaultReadingDirection: 'ltr',
  defaultScaleMode: 'fit-both',
}
