import { useState, useCallback } from 'react'
import { api } from '@/lib/api'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import type { PixivIllust } from '@/lib/types'

export function useIllustActions(
  illust: PixivIllust,
  onBookmarkChanged?: (bookmarked: boolean) => void | Promise<void>,
) {
  const [downloading, setDownloading] = useState(false)
  const [bookmarked, setBookmarked] = useState(illust.is_bookmarked)
  const [bookmarking, setBookmarking] = useState(false)

  const handleDownload = useCallback(
    async (e: React.MouseEvent) => {
      e.preventDefault()
      e.stopPropagation()
      if (downloading) return
      setDownloading(true)
      try {
        await api.download.enqueue(`https://www.pixiv.net/artworks/${illust.id}`)
        toast.success(t('browse.addedToQueue'))
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
      } finally {
        setDownloading(false)
      }
    },
    [illust.id, downloading],
  )

  const handleBookmark = useCallback(
    async (e: React.MouseEvent) => {
      e.preventDefault()
      e.stopPropagation()
      if (bookmarking) return
      setBookmarking(true)
      try {
        if (bookmarked) {
          await api.pixiv.deleteBookmark(illust.id)
          setBookmarked(false)
          await onBookmarkChanged?.(false)
        } else {
          await api.pixiv.addBookmark(illust.id)
          setBookmarked(true)
          await onBookmarkChanged?.(true)
        }
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
      } finally {
        setBookmarking(false)
      }
    },
    [illust.id, bookmarked, bookmarking, onBookmarkChanged],
  )

  return { downloading, bookmarked, bookmarking, handleDownload, handleBookmark }
}
