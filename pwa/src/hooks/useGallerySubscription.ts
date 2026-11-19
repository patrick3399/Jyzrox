import useSWR from 'swr'
import { api } from '@/lib/api'
import { useCallback, useEffect, useState } from 'react'
import { BellPlus, ExternalLink as OpenIcon, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import type { GalleryAction } from '@/components/library/GalleryActionsSheet'
import { duplicateSubscriptionHint } from '@/components/subscriptions/duplicateSubscription'
import { ApiError } from '@/lib/api/client'
import { t } from '@/lib/i18n'
import { timeAgo } from '@/lib/timeUtils'
import type { Subscription } from '@/lib/types'
import { useWsJobs, type SubCheckEvent } from '@/lib/ws'

/** Key under the `subscriptions` prefix so `subscription.*` WS events refetch it (lib/wsInvalidation.tsx). */
export function gallerySubscriptionKey(galleryId: number) {
  return ['subscriptions', 'by-gallery', galleryId] as const
}

/** Members only: viewers cannot subscribe and the endpoint answers them 403. */
export function useGallerySubscription(galleryId: number | undefined, enabled: boolean) {
  return useSWR(enabled && galleryId != null ? gallerySubscriptionKey(galleryId) : null, () =>
    api.subscriptions.byGallery(galleryId as number),
  )
}

/** Checks that end in a worker skip publish no result event; stop waiting after this long. */
const PENDING_TIMEOUT_MS = 120_000

function statusLine(sub: Subscription): string {
  const name = sub.name || sub.url
  if (sub.paused_at) return t('library.subscriptionPausedShort', { name })
  if (!sub.last_checked_at) return t('library.subscriptionNeverChecked', { name })
  return t('library.subscriptionLastChecked', { name, time: timeAgo(sub.last_checked_at) })
}

/**
 * Gallery page "More" entries for the subscription covering this gallery: check it
 * now (and hand the resulting job to the page), open the subscriptions page, or
 * subscribe to the account when nothing covers it.
 */
export function useGallerySubscriptionActions({
  galleryId,
  enabled,
  busy,
  onJobStarted,
}: {
  galleryId: number | undefined
  enabled: boolean
  busy: boolean
  onJobStarted: (jobId: string) => void
}) {
  const { data, mutate } = useGallerySubscription(galleryId, enabled)
  const { lastSubCheck } = useWsJobs()
  const [requesting, setRequesting] = useState(false)
  // `baseline` is the event that was current when the check was requested; only a later one answers it.
  const [pending, setPending] = useState<{ subId: number; baseline: SubCheckEvent | null } | null>(
    null,
  )
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [subscribing, setSubscribing] = useState(false)

  const sub = data?.subscription ?? null

  useEffect(() => {
    if (pending == null || !lastSubCheck || lastSubCheck === pending.baseline) return
    if (lastSubCheck.sub_id !== pending.subId || lastSubCheck.status === 'checking') return
    setPending(null)
    void mutate()
    if (lastSubCheck.status === 'failed') {
      toast.error(t('library.subscriptionCheckFailed'))
    } else if (lastSubCheck.job_id) {
      onJobStarted(lastSubCheck.job_id)
    } else {
      toast.info(t('library.subscriptionCheckNoNew'))
    }
  }, [lastSubCheck, pending, mutate, onJobStarted])

  useEffect(() => {
    if (pending == null) return
    const timer = setTimeout(() => {
      setPending(null)
      void mutate()
    }, PENDING_TIMEOUT_MS)
    return () => clearTimeout(timer)
  }, [pending, mutate])

  const runCheck = useCallback(async () => {
    if (!sub || requesting) return
    const baseline = lastSubCheck
    setRequesting(true)
    try {
      await api.subscriptions.check(sub.id)
      setPending({ subId: sub.id, baseline })
      toast.success(t('library.subscriptionCheckQueued'))
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.error(t('library.subscriptionPaused'))
        void mutate()
      } else {
        toast.error(err instanceof Error && err.message ? err.message : t('library.updateFailed'))
      }
    } finally {
      setRequesting(false)
    }
  }, [sub, requesting, lastSubCheck, mutate])

  const subscribe = useCallback(async () => {
    const url = data?.subscribe_url
    if (!url || subscribing) return
    setSubscribing(true)
    try {
      await api.subscriptions.create({ url, auto_download: true, reject_duplicate: true })
      toast.success(t('library.subscribeAccountDone'))
      setConfirmOpen(false)
    } catch (err) {
      if (duplicateSubscriptionHint(err)) {
        toast.info(t('library.subscribeAccountExists'))
        setConfirmOpen(false)
      } else {
        toast.error(err instanceof Error && err.message ? err.message : t('library.updateFailed'))
      }
    } finally {
      setSubscribing(false)
      void mutate()
    }
  }, [data?.subscribe_url, subscribing, mutate])

  const actions: GalleryAction[] = []
  if (enabled && sub) {
    const checking = requesting || pending != null || !!sub.checking
    actions.push(
      {
        id: 'subscription-check',
        label: checking ? t('library.subscriptionChecking') : t('library.subscriptionCheckNow'),
        description: statusLine(sub),
        icon: RefreshCw,
        disabled: !!sub.paused_at || checking || busy,
        onSelect: () => void runCheck(),
      },
      {
        id: 'subscription-open',
        label: t('library.subscriptionOpen'),
        icon: OpenIcon,
        href: '/subscriptions',
      },
    )
  } else if (enabled && data?.can_subscribe) {
    actions.push({
      id: 'subscription-create',
      label: t('library.subscribeAccount'),
      icon: BellPlus,
      onSelect: () => setConfirmOpen(true),
    })
  }

  return {
    actions,
    confirm: {
      open: confirmOpen,
      busy: subscribing,
      onConfirm: () => void subscribe(),
      onCancel: () => setConfirmOpen(false),
    },
  }
}
