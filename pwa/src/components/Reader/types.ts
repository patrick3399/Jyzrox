export type ViewMode = 'single' | 'webtoon' | 'double'

export interface ReaderImage {
  pageNum: number      // 1-indexed
  url: string          // resolved URL (local path or proxy API)
  isLocal: boolean     // true = served from /media/gallery/
  width?: number
  height?: number
}

export interface ReaderState {
  currentPage: number   // 1-indexed
  viewMode: ViewMode
  isFullscreen: boolean
  brightness: number    // 0.3 – 1.0, default 1.0
  bgColor: string       // CSS color, default '#000000'
  showOverlay: boolean  // show top/bottom controls
}

export type ReaderAction =
  | { type: 'SET_PAGE'; page: number }
  | { type: 'SET_VIEW_MODE'; mode: ViewMode }
  | { type: 'TOGGLE_FULLSCREEN' }
  | { type: 'SET_BRIGHTNESS'; value: number }
  | { type: 'SET_BG_COLOR'; color: string }
  | { type: 'TOGGLE_OVERLAY' }
  | { type: 'SHOW_OVERLAY' }
  | { type: 'HIDE_OVERLAY' }
