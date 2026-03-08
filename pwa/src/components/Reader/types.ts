export type ViewMode = 'single' | 'webtoon' | 'double'

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
}

export type ReaderAction =
  | { type: 'SET_PAGE'; page: number }
  | { type: 'SET_VIEW_MODE'; mode: ViewMode }
  | { type: 'TOGGLE_OVERLAY' }
  | { type: 'SHOW_OVERLAY' }
  | { type: 'HIDE_OVERLAY' }
