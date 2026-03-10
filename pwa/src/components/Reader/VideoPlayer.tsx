'use client'

import React, { useCallback, useRef, useState } from 'react'
import { t } from '@/lib/i18n'
import type { ReaderImage } from './types'

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

interface VideoPlayerProps {
  image: ReaderImage
  className?: string
  style?: React.CSSProperties
  innerRef?: React.Ref<HTMLVideoElement>
  onLoad?: () => void
  onToggleOverlay?: () => void
  overlayVisible?: boolean
}

export default function VideoPlayer({ image, className, style, innerRef, onLoad, onToggleOverlay, overlayVisible }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(image.duration || 0)
  const [muted, setMuted] = useState(true)

  const setVideoRef = useCallback(
    (el: HTMLVideoElement | null) => {
      videoRef.current = el
      if (typeof innerRef === 'function') innerRef(el)
      else if (innerRef && 'current' in innerRef) (innerRef as React.MutableRefObject<HTMLVideoElement | null>).current = el
    },
    [innerRef],
  )

  const togglePlay = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    if (v.paused) { v.play(); setPlaying(true) }
    else { v.pause(); setPlaying(false) }
  }, [])

  const toggleMute = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    v.muted = !v.muted
    setMuted(v.muted)
  }, [])

  const handleTimeUpdate = useCallback(() => {
    const v = videoRef.current
    if (v) setCurrentTime(v.currentTime)
  }, [])

  const handleLoadedMetadata = useCallback(() => {
    const v = videoRef.current
    if (v) {
      setDuration(v.duration)
      onLoad?.()
    }
  }, [onLoad])

  const handleSeek = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const v = videoRef.current
    if (!v) return
    const time = parseFloat(e.target.value)
    v.currentTime = time
    setCurrentTime(time)
  }, [])

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ ...style, position: 'relative', width: '100%', height: '100%', cursor: 'pointer' }}
    >
      <video
        ref={setVideoRef}
        src={image.url}
        style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }}
        loop
        muted={muted}
        playsInline
        autoPlay
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
      />

      {/* Transparent tap overlay — toggles Reader overlay (same as image tap behavior) */}
      <div
        style={{ position: 'absolute', inset: 0, zIndex: 1 }}
        onClick={() => onToggleOverlay?.()}
      />

      {/* Controls overlay — visibility driven by Reader overlayVisible prop */}
      <div
        style={{
          position: 'absolute',
          bottom: overlayVisible ? 'calc(80px + env(safe-area-inset-bottom))' : '0px',
          left: 0,
          right: 0,
          zIndex: 2,
          background: 'linear-gradient(transparent, rgba(0,0,0,0.7))',
          padding: overlayVisible ? '24px 12px 8px' : '24px 12px calc(8px + env(safe-area-inset-bottom))',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
          opacity: overlayVisible ? 1 : 0,
          transition: 'opacity 0.3s, bottom 0.3s',
          pointerEvents: overlayVisible ? 'auto' : 'none',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Seek bar */}
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.1}
          value={currentTime}
          onChange={handleSeek}
          aria-label="Seek"
          style={{ width: '100%', height: '4px', cursor: 'pointer', accentColor: '#3b82f6' }}
        />

        {/* Bottom row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#fff', fontSize: '13px' }}>
          {/* Play/Pause */}
          <button
            onClick={togglePlay}
            aria-label={playing ? t('reader.videoPause') : t('reader.videoPlay')}
            style={{
              background: 'rgba(255,255,255,0.15)',
              border: 'none',
              color: '#fff',
              cursor: 'pointer',
              width: 32,
              height: 32,
              borderRadius: 6,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              padding: 0,
            }}
          >
            {playing ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="4" width="4" height="16" rx="1" />
                <rect x="14" y="4" width="4" height="16" rx="1" />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5v14l11-7z" />
              </svg>
            )}
          </button>

          {/* Time */}
          <span style={{ fontVariantNumeric: 'tabular-nums', minWidth: '80px' }}>
            {formatTime(currentTime)} / {formatTime(duration)}
          </span>

          <div style={{ flex: 1 }} />

          {/* Mute */}
          <button
            onClick={toggleMute}
            aria-label={muted ? t('reader.videoUnmute') : t('reader.videoMute')}
            style={{
              background: 'rgba(255,255,255,0.15)',
              border: 'none',
              color: '#fff',
              cursor: 'pointer',
              width: 32,
              height: 32,
              borderRadius: 6,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              padding: 0,
            }}
          >
            {muted ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z" />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z" />
              </svg>
            )}
          </button>

        </div>
      </div>
    </div>
  )
}
