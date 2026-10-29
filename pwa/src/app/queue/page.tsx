'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import {
  Download,
  X,
  Plus,
  Trash2,
  Pause,
  Play,
  ChevronRight,
  Globe,
  WifiOff,
  RotateCcw,
  RefreshCw,
  Network,
  Square,
} from 'lucide-react'
import { toast } from 'sonner'
import { galleryHref } from '@/lib/galleryRoutes'
import {
  useDownloadJobs,
  useEnqueueDownload,
  useCancelJob,
  useStopJob,
  useClearFinishedJobs,
  usePauseJob,
  useRetryJob,
  useCheckUrl,
  useSupportedSites,
  useDownloadPreview,
} from '@/hooks/useDownloadQueue'
import { api } from '@/lib/api'
import {
  SubscribedUrlDialog,
  subscribedHint,
  type SubscribedUrlHint,
} from '@/components/download/DownloadActionDialogs'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { t } from '@/lib/i18n'
import { MediaPolicyFields } from '@/components/download/MediaPolicyFields'
import { DEFAULT_MEDIA_POLICY, withMediaPolicy } from '@/lib/mediaPolicy'
import { SUBSCRIPTION_ACTIVE_ANCHOR, isActiveJob } from '@/lib/downloadJobFilters'
import { useWsConnection } from '@/lib/ws'
import type {
  DownloadJob,
  DownloadJobMode,
  DownloadPreview,
  JobListParams,
  MediaPolicy,
} from '@/lib/types'

// Module-level so the SWR key stays referentially stable across renders.
const MANUAL_JOBS_PARAMS: JobListParams = { exclude_subscription: true }
const SUBSCRIPTION_ACTIVE_PARAMS: JobListParams = {
  subscription_only: true,
  active_only: true,
  limit: 100,
}

const STATUS_ORDER: Record<string, number> = { running: 0, paused: 1, queued: 2 }

function compareActiveJobs(a: DownloadJob, b: DownloadJob): number {
  const orderDiff = (STATUS_ORDER[a.status] ?? 3) - (STATUS_ORDER[b.status] ?? 3)
  if (orderDiff !== 0) return orderDiff
  return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
}

const STATUS_STYLES: Record<string, string> = {
  queued: 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400',
  running: 'bg-blue-500/10 border-blue-500/30 text-blue-400',
  done: 'bg-green-500/10 border-green-500/30 text-green-400',
  failed: 'bg-red-500/10 border-red-500/30 text-red-400',
  cancelled: 'bg-vault-card border-vault-border text-vault-text-muted',
  paused: 'bg-orange-500/10 border-orange-500/30 text-orange-400',
  partial: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
}

function StatusBadge({
  status,
  alreadySaved,
  stopped,
}: {
  status: string
  alreadySaved?: boolean
  stopped?: boolean
}) {
  // A "done" run that fetched nothing new only confirmed what is stored.
  const shown = status === 'done' && alreadySaved ? 'cancelled' : status
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs font-medium ${STATUS_STYLES[shown] ?? STATUS_STYLES.cancelled}`}
    >
      {status === 'running' && (
        <span className="flex gap-0.5">
          <span className="w-1 h-1 rounded-full bg-blue-400 animate-bounce [animation-delay:0ms]" />
          <span className="w-1 h-1 rounded-full bg-blue-400 animate-bounce [animation-delay:150ms]" />
          <span className="w-1 h-1 rounded-full bg-blue-400 animate-bounce [animation-delay:300ms]" />
        </span>
      )}
      {status === 'done' && alreadySaved
        ? t('queue.statusAlreadySaved')
        : status === 'done' && stopped
          ? t('queue.stopped')
          : status}
    </span>
  )
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

const MODE_LABEL_KEY: Partial<Record<DownloadJobMode, string>> = {
  subscription_initial: 'queue.modeInitial',
  subscription_incremental: 'queue.modeIncremental',
  repair: 'queue.modeRepair',
}

/** Plain downloads (and jobs from an API without modes) need no badge. */
function ModeBadge({ mode }: { mode: DownloadJob['mode'] }) {
  const labelKey = mode ? MODE_LABEL_KEY[mode] : undefined
  if (!labelKey) return null
  return (
    <span
      data-testid="job-mode-badge"
      className="inline-flex items-center px-1.5 py-0.5 rounded border border-vault-border text-vault-text-secondary text-[11px] font-medium"
    >
      {t(labelKey)}
    </span>
  )
}

const GDL_STATE_KEY: Record<string, string> = {
  starting: 'queue.gdlStateStarting',
  downloading: 'queue.gdlStateDownloading',
  sleeping: 'queue.gdlStateSleeping',
  rate_limited: 'queue.gdlStateRateLimited',
  retrying: 'queue.gdlStateRetrying',
  paused: 'queue.gdlStatePaused',
  cancelled: 'queue.gdlStateCancelled',
  done: 'queue.gdlStateDone',
}

function JobDetailPanel({ job }: { job: DownloadJob }) {
  const p = job.progress ?? {}
  const gdlState = typeof p.gdl_state === 'string' ? p.gdl_state : undefined
  const stateLabel = gdlState ? t(GDL_STATE_KEY[gdlState] ?? 'queue.gdlStateDownloading') : null
  const currentFile = typeof p.current_file === 'string' ? p.current_file : null
  const currentPage = typeof p.current_file_page === 'number' ? p.current_file_page : null
  const skipped = typeof p.skipped === 'number' ? p.skipped : 0
  const alreadySaved = p.outcome === 'already_saved'
  const existingPages = typeof p.existing_pages === 'number' ? p.existing_pages : null
  const importSkipped = p.import_skipped
  const recentLog = Array.isArray(p.recent_log) ? p.recent_log : null

  return (
    <div className="px-4 py-3 bg-vault-bg border-t border-vault-border space-y-2 text-sm">
      {job.error && (
        <div className="text-red-400">
          <span className="font-medium">{t('queue.jobError')}:</span> {job.error}
        </div>
      )}
      {typeof p.percent === 'number' && (
        <div className="text-vault-text-muted">
          <span className="font-medium">{t('queue.jobProgress')}:</span> {p.percent}%
        </div>
      )}
      {stateLabel && (
        <div className="text-vault-text-muted">
          <span className="font-medium">{t('queue.jobGdlState')}:</span>{' '}
          <span
            className={
              gdlState === 'rate_limited' || gdlState === 'sleeping'
                ? 'text-yellow-400'
                : gdlState === 'retrying' || gdlState === 'cancelled'
                  ? 'text-red-400'
                  : 'text-vault-text'
            }
          >
            {stateLabel}
            {typeof p.gdl_state_seconds === 'number' && p.gdl_state_seconds > 0 && (
              <> · {Math.round(p.gdl_state_seconds)}s</>
            )}
          </span>
        </div>
      )}
      {currentFile && (
        <div className="text-vault-text-muted">
          <span className="font-medium">{t('queue.jobCurrentFile')}:</span>{' '}
          <span className="font-mono text-xs">
            {currentPage !== null && <>#{currentPage} </>}
            {currentFile}
          </span>
        </div>
      )}
      {alreadySaved && (
        <div className="text-vault-text-muted">
          {existingPages !== null
            ? t('queue.alreadySavedNote', { pages: String(existingPages) })
            : t('queue.alreadySavedNoteNoPages')}
        </div>
      )}
      {!alreadySaved && skipped > 0 && (
        <div className="text-vault-text-muted">
          <span className="font-medium">{t('queue.jobSkipped')}:</span> {skipped}
        </div>
      )}
      {importSkipped &&
        typeof importSkipped === 'object' &&
        (importSkipped.duplicate > 0 ||
          importSkipped.excluded > 0 ||
          importSkipped.invalid > 0) && (
          <div className="text-vault-text-muted">
            <span className="font-medium">{t('queue.jobImportSkipped')}:</span>{' '}
            <span className="font-mono text-xs">
              dup={importSkipped.duplicate} excl={importSkipped.excluded} inv=
              {importSkipped.invalid}
            </span>
          </div>
        )}
      {recentLog && recentLog.length > 0 && (
        <div className="text-vault-text-muted">
          <span className="font-medium">{t('queue.jobRecentLog')}:</span>
          <pre className="mt-1 text-xs bg-vault-card rounded p-2 overflow-auto max-h-32 whitespace-pre-wrap break-all">
            {recentLog.join('\n')}
          </pre>
        </div>
      )}
      {Object.keys(p).length > 0 && (
        <details className="text-vault-text-muted">
          <summary className="cursor-pointer font-medium">{t('queue.jobMeta')}</summary>
          <pre className="mt-1 text-xs bg-vault-card rounded p-2 overflow-auto max-h-40">
            {JSON.stringify(p, null, 2)}
          </pre>
        </details>
      )}
    </div>
  )
}

function JobRow({
  job,
  onStop,
  onDiscard,
  onPause,
  onRetry,
  isStopping,
  expandedJobId,
  onToggleExpand,
}: {
  job: DownloadJob
  onStop: (job: DownloadJob) => void
  onDiscard: (job: DownloadJob) => void
  onPause: (id: string, action: 'pause' | 'resume') => void
  onRetry: (id: string) => void
  /** A stop was just requested here and the list has not caught up yet. */
  isStopping: boolean
  expandedJobId: string | null
  onToggleExpand: (id: string) => void
}) {
  const isActive = job.status === 'queued' || job.status === 'running' || job.status === 'paused'
  // The server keeps the job active until the worker has finished keeping what it fetched.
  const stopping = isActive && (isStopping || !!job.stop_requested_at)
  // A repair's files are wanted, so it has no discard: the server treats cancel as stop.
  const canDiscard = job.mode !== 'repair'
  const wasStopped = job.status === 'done' && job.progress?.outcome === 'stopped'
  const stoppedText =
    wasStopped && typeof job.progress?.status_text === 'string' ? job.progress.status_text : null
  const createdAt = new Date(job.created_at).toLocaleString()
  const finishedAt = job.finished_at ? new Date(job.finished_at).toLocaleString() : null
  const gallerySource = job.gallery_source
  const gallerySourceId = job.gallery_source_id
  const galleryTitle = job.progress?.title
  const isWaitingForSourceSlot =
    job.status === 'queued' && job.progress?.wait_reason === 'source_slot'
  const isWaitingForPersonaCooldown =
    job.status === 'queued' && job.progress?.wait_reason === 'persona_cooldown'
  const semaphoreKey =
    typeof job.progress?.semaphore_key === 'string' && job.progress.semaphore_key
      ? job.progress.semaphore_key
      : job.source || t('common.auto')
  const queuePosition = job.progress?.queue_position

  const isExpanded = expandedJobId === job.id

  return (
    <div
      className="bg-vault-card border border-vault-border rounded-lg overflow-hidden cursor-pointer"
      onClick={() => onToggleExpand(job.id)}
    >
      <div className="flex items-start justify-between gap-3 p-4">
        <div className="flex-1 min-w-0">
          {galleryTitle ? (
            <div className="mb-1">
              <p className="text-sm font-medium truncate" title={galleryTitle}>
                {gallerySource && gallerySourceId ? (
                  <a
                    href={galleryHref(gallerySource, gallerySourceId)}
                    onClick={(e) => e.stopPropagation()}
                    className="text-vault-accent hover:underline"
                  >
                    {galleryTitle}
                  </a>
                ) : (
                  galleryTitle
                )}
              </p>
              <p className="text-xs text-vault-text-muted truncate" title={job.url}>
                {job.url}
              </p>
            </div>
          ) : (
            <p className="text-sm truncate mb-1" title={job.url}>
              {job.url}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-3 text-xs text-vault-text-muted">
            {job.subscription_id && (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-vault-accent/15 text-vault-accent text-[11px] font-medium">
                <RefreshCw className="w-3 h-3" />
                {t('queue.subscription')}
              </span>
            )}
            <ModeBadge mode={job.mode} />
            <span>
              {t('queue.source')}:{' '}
              <span className="text-vault-text-secondary">{job.source || t('common.auto')}</span>
            </span>
            {job.persona && (
              <span
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-vault-accent/15 text-vault-accent text-[11px] font-medium"
                title={t('queue.persona')}
              >
                <Network className="w-3 h-3" />
                {job.persona}
              </span>
            )}
            <span>
              {t('queue.created')}: <span className="text-vault-text-secondary">{createdAt}</span>
            </span>
            {finishedAt && (
              <span>
                {t('queue.finished')}:{' '}
                <span className="text-vault-text-secondary">{finishedAt}</span>
              </span>
            )}
          </div>
          {job.error && <p className="mt-1 text-xs text-red-400 break-words">{job.error}</p>}
          {stoppedText && (
            <p className="mt-1 text-xs text-vault-text-muted break-words">{stoppedText}</p>
          )}
          {isWaitingForSourceSlot && (
            <p className="mt-1 text-xs text-yellow-400">
              {t('queue.waitingForSourceSlot', { source: semaphoreKey })}
              {typeof queuePosition === 'number' && queuePosition > 0 && (
                <> · {t('queue.queuePosition', { position: queuePosition })}</>
              )}
            </p>
          )}
          {isWaitingForPersonaCooldown && (
            <p className="mt-1 text-xs text-yellow-400">{t('queue.waitingPersonaCooldown')}</p>
          )}
          {/* Retry info */}
          {job.retry_count > 0 && (
            <p className="mt-1 text-xs text-vault-text-muted">
              {t('queue.retryCount', {
                count: String(job.retry_count),
                max: String(job.max_retries),
              })}
            </p>
          )}
          {/* Failed pages info */}
          {job.progress?.failed_pages && job.progress.failed_pages.length > 0 && (
            <p className="mt-1 text-xs text-amber-400">
              {t('queue.failedPages', { count: String(job.progress.failed_pages.length) })}
            </p>
          )}
          {/* Permanently failed notice */}
          {job.retry_count >= job.max_retries &&
            (job.status === 'failed' || job.status === 'partial') && (
              <p className="mt-1 text-xs text-red-400/70">{t('queue.permanentlyFailed')}</p>
            )}
          {job.status === 'running' && job.progress && (
            <div className="mt-2">
              {typeof job.progress.downloaded === 'number' && (
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 bg-vault-border rounded-full overflow-hidden">
                    {job.progress.total ? (
                      <div
                        className="h-full bg-blue-500 rounded-full transition-all duration-300"
                        style={{
                          width: `${Math.min(100, (job.progress.downloaded / job.progress.total) * 100)}%`,
                        }}
                      />
                    ) : (
                      <div className="h-full bg-blue-500/30 rounded-full overflow-hidden relative">
                        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-blue-500/60 to-transparent animate-[shimmer_1.5s_infinite]" />
                      </div>
                    )}
                  </div>
                  <span className="text-xs text-vault-text-muted whitespace-nowrap">
                    {job.progress.downloaded}
                    {job.progress.total ? ` / ${job.progress.total}` : ''} {t('queue.files')}
                  </span>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-3 mt-1">
                {typeof job.progress.speed === 'number' && job.progress.speed > 0 && (
                  <span className="text-xs text-vault-text-muted">
                    {t('queue.filesPerMin', { count: (job.progress.speed * 60).toFixed(1) })}
                  </span>
                )}
                {job.progress.started_at && job.progress.last_update_at && (
                  <span className="text-xs text-vault-text-muted">
                    {t('queue.elapsed', {
                      time: formatDuration(
                        (new Date(job.progress.last_update_at).getTime() -
                          new Date(job.progress.started_at).getTime()) /
                          1000,
                      ),
                    })}
                  </span>
                )}
                {job.progress.total &&
                  typeof job.progress.speed === 'number' &&
                  job.progress.speed > 0 &&
                  typeof job.progress.downloaded === 'number' &&
                  job.progress.downloaded < job.progress.total && (
                    <span className="text-xs text-vault-text-muted">
                      {t('queue.remaining', {
                        time: formatDuration(
                          (job.progress.total - job.progress.downloaded) / job.progress.speed,
                        ),
                      })}
                    </span>
                  )}
                {job.progress.status_text && (
                  <span className="text-xs text-vault-text-muted">{job.progress.status_text}</span>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
          <StatusBadge
            status={job.status}
            alreadySaved={job.progress?.outcome === 'already_saved'}
            stopped={job.progress?.outcome === 'stopped'}
          />
          {job.status === 'running' && (
            <button
              onClick={() => onPause(job.id, 'pause')}
              disabled={stopping}
              className="p-1.5 rounded-lg bg-orange-500/10 border border-orange-500/30 hover:bg-orange-500/20 text-orange-400 transition-colors disabled:opacity-50"
              title={t('queue.pause')}
            >
              <Pause size={14} />
            </button>
          )}
          {job.status === 'paused' && (
            <button
              onClick={() => onPause(job.id, 'resume')}
              disabled={stopping}
              className="p-1.5 rounded-lg bg-green-500/10 border border-green-500/30 hover:bg-green-500/20 text-green-400 transition-colors disabled:opacity-50"
              title={t('queue.resume')}
            >
              <Play size={14} />
            </button>
          )}
          {isActive && (
            <button
              data-testid="job-stop"
              onClick={() => onStop(job)}
              disabled={stopping}
              className="inline-flex items-center gap-1 px-2 py-1.5 rounded-lg bg-vault-accent/10 border border-vault-accent/30 hover:bg-vault-accent/20 text-vault-accent text-xs font-medium transition-colors disabled:opacity-60"
              title={t('queue.stop')}
              aria-label={stopping ? t('queue.stopping') : t('queue.stop')}
            >
              <Square size={12} />
              <span className="hidden sm:inline">
                {stopping ? t('queue.stopping') : t('queue.stop')}
              </span>
            </button>
          )}
          {isActive && canDiscard && (
            <button
              data-testid="job-discard"
              onClick={() => onDiscard(job)}
              disabled={stopping}
              className="p-1.5 rounded-lg bg-red-500/10 border border-red-500/30 hover:bg-red-500/20 text-red-400 transition-colors disabled:opacity-50"
              title={t('queue.discard')}
              aria-label={t('queue.discard')}
            >
              <X size={14} />
            </button>
          )}
          {(job.status === 'failed' || job.status === 'partial') &&
            job.retry_count < job.max_retries && (
              <button
                onClick={() => onRetry(job.id)}
                className="p-1.5 rounded-lg bg-vault-accent/10 border border-vault-accent/30 hover:bg-vault-accent/20 text-vault-accent transition-colors"
                title={t('queue.retry')}
              >
                <RotateCcw size={14} />
              </button>
            )}
        </div>
      </div>
      {isExpanded && <JobDetailPanel job={job} />}
    </div>
  )
}

function DownloadPreviewPanel({ preview }: { preview: DownloadPreview }) {
  if (!preview.preview_available) {
    return (
      <div className="mt-3 p-3 bg-vault-input/50 border border-vault-border rounded-lg">
        <p className="text-xs text-vault-text-muted">{t('queue.previewNotAvailable')}</p>
        {preview.title && (
          <p className="text-xs text-vault-text-secondary mt-1">
            {preview.source}: {preview.title}
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="mt-3 flex gap-3 p-3 bg-vault-input/50 border border-vault-border rounded-lg">
      {preview.thumb_url && preview.source === 'ehentai' && (
        <img
          src={api.eh.thumbProxyUrl(preview.thumb_url)}
          alt=""
          className="w-16 h-20 object-cover rounded shrink-0"
        />
      )}
      {preview.thumb_url && preview.source === 'pixiv' && (
        <img
          src={api.pixiv.imageProxyUrl(preview.thumb_url)}
          alt=""
          className="w-16 h-16 object-cover rounded shrink-0"
        />
      )}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-vault-text font-medium truncate">{preview.title}</p>
        <div className="flex flex-wrap items-center gap-2 mt-1 text-xs text-vault-text-muted">
          {preview.pages && (
            <span>{t('queue.previewPages', { count: String(preview.pages) })}</span>
          )}
          {preview.uploader && (
            <span>{t('queue.previewUploader', { name: preview.uploader })}</span>
          )}
          {preview.rating && <span>★ {preview.rating.toFixed(1)}</span>}
          {preview.category && (
            <span className="px-1.5 py-0.5 rounded bg-vault-border text-[10px]">
              {preview.category}
            </span>
          )}
        </div>
        {preview.tags && preview.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {preview.tags.slice(0, 10).map((tag) => (
              <span
                key={tag}
                className="px-1.5 py-0.5 rounded bg-vault-border/60 text-[10px] text-vault-text-muted"
              >
                {tag}
              </span>
            ))}
            {preview.tags.length > 10 && (
              <span className="text-[10px] text-vault-text-muted">+{preview.tags.length - 10}</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default function QueuePage() {
  const [urlInput, setUrlInput] = useState('')
  const [sitesOpen, setSitesOpen] = useState(false)
  const [debouncedUrl, setDebouncedUrl] = useState('')
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null)
  const [fanboxContent, setFanboxContent] = useState<
    'free_only' | 'accessible' | 'paid_only' | 'price_range'
  >('accessible')
  const [fanboxFeeMin, setFanboxFeeMin] = useState('')
  const [fanboxFeeMax, setFanboxFeeMax] = useState('')
  const [mediaPolicy, setMediaPolicy] = useState<MediaPolicy>(DEFAULT_MEDIA_POLICY)
  const isFanboxUrl = /fanbox\.cc\/(?:@[^/]+\/)?posts\/\d+/i.test(urlInput)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedUrl(urlInput), 300)
    return () => clearTimeout(timer)
  }, [urlInput])

  const { data: checkResult } = useCheckUrl(debouncedUrl)
  const supportsMediaPolicy = checkResult?.supports_media_policy === true
  const { data: sitesData } = useSupportedSites()
  const { data: downloadPreview, isLoading: previewLoading } = useDownloadPreview(debouncedUrl)

  const { data, isLoading, error, mutate: mutateManual } = useDownloadJobs(MANUAL_JOBS_PARAMS)
  const { data: subActiveData, mutate: mutateSubActive } = useDownloadJobs(
    SUBSCRIPTION_ACTIVE_PARAMS,
  )
  const { trigger: enqueue, isMutating: isEnqueuing } = useEnqueueDownload()
  const { trigger: cancelJob } = useCancelJob()
  const { trigger: stopJob } = useStopJob()
  const { trigger: clearJobs, isMutating: isClearing } = useClearFinishedJobs()
  const { trigger: pauseJob } = usePauseJob()
  const { trigger: retryJob } = useRetryJob()

  const { connected } = useWsConnection()
  const [showFallbackWarning, setShowFallbackWarning] = useState(false)

  useEffect(() => {
    if (connected) {
      setShowFallbackWarning(false)
      return
    }
    const timer = setTimeout(() => setShowFallbackWarning(true), 6000)
    return () => clearTimeout(timer)
  }, [connected])

  // Cancel / pause / retry / clear can move a job between the two lists.
  const mutate = useCallback(
    () => Promise.all([mutateManual(), mutateSubActive()]),
    [mutateManual, mutateSubActive],
  )

  // A URL the user already subscribes to is refused until they choose: check the
  // subscription (new posts only) or download anyway (may resume given-up history).
  const [subscribedPrompt, setSubscribedPrompt] = useState<{
    url: string
    options: Record<string, unknown>
    hint: SubscribedUrlHint
  } | null>(null)
  const [subscribedBusy, setSubscribedBusy] = useState(false)

  const submitEnqueue = useCallback(
    async (
      url: string,
      options: Record<string, unknown>,
      confirmSubscribed: boolean,
    ): Promise<boolean> => {
      try {
        const result = await enqueue({
          url,
          ...(Object.keys(options).length > 0 ? { options } : {}),
          ...(confirmSubscribed ? { confirmSubscribed: true } : {}),
        })
        toast.success(t('queue.queuedSuccessWithJob', { id: result.job_id }))
        setUrlInput('')
        setMediaPolicy(DEFAULT_MEDIA_POLICY)
        await mutate()
        if (result.warning) {
          const warningMap: Record<string, string> = {
            eh_credentials_recommended: 'credential.ehRecommended',
            pixiv_credentials_required: 'credential.pixivRequired',
          }
          const i18nKey = warningMap[result.warning] || result.warning
          toast(t(i18nKey), { icon: '⚠️' })
        }
        return true
      } catch (err) {
        const hint = confirmSubscribed ? null : subscribedHint(err)
        if (hint) {
          setSubscribedPrompt({ url, options, hint })
          return false
        }
        toast.error(err instanceof Error ? err.message : 'Failed to enqueue download')
        return false
      }
    },
    [enqueue, mutate],
  )

  const handleEnqueue = useCallback(async () => {
    const url = urlInput.trim()
    if (!url) return
    const baseOptions: Record<string, unknown> = isFanboxUrl
      ? {
          fanbox: {
            content: fanboxContent,
            ...(fanboxFeeMin ? { fee_min: Number(fanboxFeeMin) } : {}),
            ...(fanboxFeeMax ? { fee_max: Number(fanboxFeeMax) } : {}),
          },
        }
      : {}
    // The policy only applies to URLs the server says honour it.
    const options = supportsMediaPolicy ? withMediaPolicy(baseOptions, mediaPolicy) : baseOptions
    await submitEnqueue(url, options, false)
  }, [
    urlInput,
    submitEnqueue,
    isFanboxUrl,
    fanboxContent,
    fanboxFeeMin,
    fanboxFeeMax,
    supportsMediaPolicy,
    mediaPolicy,
  ])

  const handleCheckSubscribed = useCallback(async () => {
    const subscriptionId = subscribedPrompt?.hint.subscriptionId
    if (subscriptionId == null) return
    setSubscribedBusy(true)
    try {
      await api.subscriptions.check(subscriptionId)
      toast.success(t('queue.subscriptionCheckQueued'))
      setSubscribedPrompt(null)
      setUrlInput('')
      setMediaPolicy(DEFAULT_MEDIA_POLICY)
      await mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('subscriptions.checkFailed'))
    } finally {
      setSubscribedBusy(false)
    }
  }, [subscribedPrompt, mutate])

  const handleDownloadAnyway = useCallback(async () => {
    if (!subscribedPrompt) return
    setSubscribedBusy(true)
    try {
      const queued = await submitEnqueue(subscribedPrompt.url, subscribedPrompt.options, true)
      if (queued) setSubscribedPrompt(null)
    } finally {
      setSubscribedBusy(false)
    }
  }, [subscribedPrompt, submitEnqueue])

  // Jobs a stop was requested for this session; the server's `stop_requested_at` takes over on the next list refresh.
  const [stoppingIds, setStoppingIds] = useState<ReadonlySet<string>>(new Set())

  const handleStop = useCallback(
    async (job: DownloadJob) => {
      // Stopping a subscription run gives up the posts it has not reached yet, for good.
      const givesUpHistory =
        job.mode === 'subscription_initial' ||
        job.mode === 'subscription_incremental' ||
        (!job.mode && !!job.subscription_id)
      if (givesUpHistory && !confirm(t('queue.stopConfirm'))) return
      setStoppingIds((prev) => new Set(prev).add(job.id))
      try {
        await stopJob(job.id)
        await mutate()
      } catch (err) {
        setStoppingIds((prev) => {
          const next = new Set(prev)
          next.delete(job.id)
          return next
        })
        toast.error(err instanceof Error ? err.message : t('queue.stopError'))
      }
    },
    [stopJob, mutate],
  )

  const handleDiscard = useCallback(
    async (job: DownloadJob) => {
      if (!confirm(t('queue.discardConfirm'))) return
      try {
        await cancelJob(job.id)
        await mutate()
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t('queue.cancelError'))
      }
    },
    [cancelJob, mutate],
  )

  const handlePause = useCallback(
    async (id: string, action: 'pause' | 'resume') => {
      try {
        await pauseJob({ id, action })
        await mutate()
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t('queue.pauseError'))
      }
    },
    [pauseJob, mutate],
  )

  const handleRetry = useCallback(
    async (id: string) => {
      try {
        await retryJob(id)
        toast.success(t('queue.retryQueued'))
        await mutate()
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t('queue.retryError'))
      }
    },
    [retryJob, mutate],
  )

  const handleClear = useCallback(async () => {
    try {
      const result = await clearJobs()
      toast.success(t('queue.cleared', { count: String(result.deleted) }))
      await mutate()
    } catch {
      toast.error(t('queue.clearError'))
    }
  }, [clearJobs, mutate])

  const allJobs = data?.jobs ?? []
  const activeJobs = allJobs.filter(
    (j) => j.status === 'queued' || j.status === 'running' || j.status === 'paused',
  )
  const completedJobs = allJobs.filter(
    (j) =>
      j.status === 'done' ||
      j.status === 'failed' ||
      j.status === 'cancelled' ||
      j.status === 'partial',
  )

  const sortedActive = [...activeJobs].sort(compareActiveJobs)
  const sortedCompleted = [...completedJobs].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )

  // The server only returns active jobs, but a cached list can still hold a job that has just
  // finished; drop those client-side and keep `total` consistent with what is rendered.
  const subActiveRaw = subActiveData?.jobs ?? []
  const subActiveJobs = subActiveRaw.filter(isActiveJob).sort(compareActiveJobs)
  const subActiveTotal = Math.max(
    subActiveJobs.length,
    (subActiveData?.total ?? 0) - (subActiveRaw.length - subActiveJobs.length),
  )
  const subActiveVisible = !isLoading && subActiveJobs.length > 0

  // Scroll to the subscription section once when arriving via /queue#subscription-active.
  const hashScrolledRef = useRef(false)
  useEffect(() => {
    if (!subActiveVisible || hashScrolledRef.current) return
    if (window.location.hash !== `#${SUBSCRIPTION_ACTIVE_ANCHOR}`) return
    const el = document.getElementById(SUBSCRIPTION_ACTIVE_ANCHOR)
    if (!el) return
    hashScrolledRef.current = true
    el.scrollIntoView({ block: 'start' })
  }, [subActiveVisible])

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">{t('queue.title')}</h1>

      {/* Add Download Form */}
      <div className="bg-vault-card border border-vault-border rounded-lg p-4 mb-6">
        <h2 className="text-sm font-semibold text-vault-text-muted uppercase tracking-wide mb-3">
          {t('queue.addDownload')}
        </h2>
        <div className="flex gap-2">
          <input
            type="text"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleEnqueue()}
            placeholder={t('queue.urlPlaceholder')}
            className="flex-1 bg-vault-input border border-vault-border rounded-lg px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-border-hover text-sm"
          />
          <button
            onClick={handleEnqueue}
            disabled={isEnqueuing || !urlInput.trim()}
            className="flex items-center gap-1.5 px-4 py-2 bg-vault-accent hover:bg-vault-accent/90 disabled:opacity-40 rounded-lg text-white text-sm font-medium transition-colors"
          >
            <Plus size={16} />
            {isEnqueuing ? t('queue.adding') : t('queue.add')}
          </button>
        </div>
        {isFanboxUrl && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-vault-text-muted">
            <span>{t('fanbox.contentPolicy')}</span>
            <select
              value={fanboxContent}
              onChange={(e) =>
                setFanboxContent(
                  e.target.value as 'free_only' | 'accessible' | 'paid_only' | 'price_range',
                )
              }
              className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text"
            >
              <option value="free_only">{t('fanbox.freeOnly')}</option>
              <option value="accessible">{t('fanbox.accessible')}</option>
              <option value="paid_only">{t('fanbox.paidOnly')}</option>
              <option value="price_range">{t('fanbox.priceRange')}</option>
            </select>
            {fanboxContent === 'price_range' && (
              <>
                <input
                  type="number"
                  min="0"
                  value={fanboxFeeMin}
                  onChange={(e) => setFanboxFeeMin(e.target.value)}
                  placeholder={t('fanbox.feeMin')}
                  className="w-24 bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text"
                />
                <input
                  type="number"
                  min="0"
                  value={fanboxFeeMax}
                  onChange={(e) => setFanboxFeeMax(e.target.value)}
                  placeholder={t('fanbox.feeMax')}
                  className="w-24 bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text"
                />
              </>
            )}
          </div>
        )}
        {supportsMediaPolicy && (
          <MediaPolicyFields value={mediaPolicy} onChange={setMediaPolicy} disabled={isEnqueuing} />
        )}
        {/* URL Recognition Badge */}
        {debouncedUrl.trim() && checkResult && (
          <div className="mt-2 flex items-center gap-2">
            {checkResult.supported ? (
              checkResult.source_id !== 'gallery_dl' ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-500/10 border border-green-500/30 text-green-400 text-xs font-medium">
                  <Globe size={12} />
                  {checkResult.name}
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 text-xs font-medium">
                  <Globe size={12} />
                  {t('queue.supportedViaGalleryDl')}
                </span>
              )
            ) : null}
          </div>
        )}
        {/* Download Preview */}
        {debouncedUrl.trim() && downloadPreview && !previewLoading && (
          <DownloadPreviewPanel preview={downloadPreview} />
        )}
        {debouncedUrl.trim() && previewLoading && (
          <div className="mt-3 flex items-center gap-2 text-xs text-vault-text-muted animate-pulse">
            <LoadingSpinner />
            <span>{t('queue.preview')}</span>
          </div>
        )}
      </div>

      {/* Supported Sites */}
      <div className="bg-vault-card border border-vault-border rounded-lg mb-6 overflow-hidden">
        <button
          onClick={() => setSitesOpen((o) => !o)}
          className="w-full flex items-center justify-between px-4 py-3 text-sm text-vault-text-muted hover:text-vault-text-secondary transition-colors"
        >
          <span className="flex items-center gap-2">
            <Globe size={14} />
            {t('queue.supportedSites')}
          </span>
          <ChevronRight
            size={14}
            className={`transition-transform ${sitesOpen ? 'rotate-90' : ''}`}
          />
        </button>
        {sitesOpen && sitesData?.categories && (
          <div className="px-4 pb-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(sitesData.categories).map(([category, sites]) => (
              <div key={category}>
                <h3 className="text-xs font-semibold text-vault-text-muted uppercase tracking-wide mb-2">
                  {t(`queue.category${category.charAt(0).toUpperCase() + category.slice(1)}`)}
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {sites.map((site) => (
                    <span
                      key={site.source_id}
                      className="inline-flex items-center px-2 py-0.5 rounded bg-vault-border/50 text-xs text-vault-text-secondary"
                    >
                      {site.name}
                    </span>
                  ))}
                </div>
              </div>
            ))}
            <div className="col-span-full text-xs text-vault-text-muted mt-1">
              {t('queue.moreViaGalleryDl')}
            </div>
          </div>
        )}
      </div>

      {isLoading && (
        <div className="flex justify-center py-16">
          <LoadingSpinner />
        </div>
      )}

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-4 text-red-400 text-sm">
          {error.message || t('common.failedToLoad')}
        </div>
      )}

      {/* WebSocket Fallback Warning */}
      {showFallbackWarning && (
        <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3 mb-4 flex items-center gap-2 text-yellow-400 text-sm">
          <WifiOff size={15} className="shrink-0" />
          {t('queue.wsFallback')}
        </div>
      )}

      {/* Active Jobs */}
      {!isLoading && (
        <div className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-vault-text-muted uppercase tracking-wide">
              {t('queue.active')} ({sortedActive.length})
            </h2>
            <span className="text-xs text-vault-text-muted">
              {connected ? t('queue.autoRefreshWs') : t('queue.autoRefresh')}
            </span>
          </div>

          {sortedActive.length === 0 ? (
            <EmptyState icon={Download} title={t('queue.noActive')} />
          ) : (
            <div className="space-y-2">
              {sortedActive.map((job) => (
                <JobRow
                  key={job.id}
                  job={job}
                  onStop={handleStop}
                  onDiscard={handleDiscard}
                  onPause={handlePause}
                  onRetry={handleRetry}
                  isStopping={stoppingIds.has(job.id)}
                  expandedJobId={expandedJobId}
                  onToggleExpand={(id) => setExpandedJobId((prev) => (prev === id ? null : id))}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Subscription Active Jobs */}
      {subActiveVisible && (
        <div id={SUBSCRIPTION_ACTIVE_ANCHOR} className="mb-6 scroll-mt-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-vault-text-muted uppercase tracking-wide">
              {t('queue.subscriptionActive')} ({subActiveTotal})
            </h2>
            {subActiveTotal > subActiveJobs.length && (
              <span className="text-xs text-vault-text-muted">
                {t('queue.subscriptionActiveTruncated', {
                  shown: String(subActiveJobs.length),
                  total: String(subActiveTotal),
                })}
              </span>
            )}
          </div>

          <div className="space-y-2">
            {subActiveJobs.map((job) => (
              <JobRow
                key={job.id}
                job={job}
                onStop={handleStop}
                onDiscard={handleDiscard}
                onPause={handlePause}
                onRetry={handleRetry}
                isStopping={stoppingIds.has(job.id)}
                expandedJobId={expandedJobId}
                onToggleExpand={(id) => setExpandedJobId((prev) => (prev === id ? null : id))}
              />
            ))}
          </div>
        </div>
      )}

      {/* Completed Jobs */}
      {!isLoading && sortedCompleted.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-vault-text-muted uppercase tracking-wide">
              {t('queue.completedFailed')} ({sortedCompleted.length})
            </h2>
            <button
              onClick={handleClear}
              disabled={isClearing || sortedCompleted.length === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-vault-card border border-vault-border hover:bg-red-500/10 hover:border-red-500/30 hover:text-red-400 text-vault-text-muted transition-colors disabled:opacity-40"
            >
              <Trash2 size={13} />
              {isClearing ? t('queue.clearing') : t('queue.clear')}
            </button>
          </div>

          <div className="space-y-2">
            {sortedCompleted.map((job) => (
              <JobRow
                key={job.id}
                job={job}
                onStop={handleStop}
                onDiscard={handleDiscard}
                onPause={handlePause}
                onRetry={handleRetry}
                isStopping={stoppingIds.has(job.id)}
                expandedJobId={expandedJobId}
                onToggleExpand={(id) => setExpandedJobId((prev) => (prev === id ? null : id))}
              />
            ))}
          </div>
        </div>
      )}

      {subscribedPrompt && (
        <SubscribedUrlDialog
          name={subscribedPrompt.hint.name || subscribedPrompt.url}
          canCheck={subscribedPrompt.hint.subscriptionId !== null}
          busy={subscribedBusy}
          onCheck={() => void handleCheckSubscribed()}
          onDownloadAnyway={() => void handleDownloadAnyway()}
          onClose={() => setSubscribedPrompt(null)}
        />
      )}
    </div>
  )
}
