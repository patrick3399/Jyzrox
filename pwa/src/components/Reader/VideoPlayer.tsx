'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
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
}

export default function VideoPlayer({ image, className, style, innerRef, onLoad }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(image.duration || 0)
  const [muted, setMuted] = useState(true)
  const [volume, setVolume] = useState(1)
  const [showControls, setShowControls] = useState(true)

  const setVideoRef = useCallback(
    (el: HTMLVideoElement | null) => {
      videoRef.current = el
      if (typeof innerRef === 'function') innerRef(el)
      else if (innerRef && 'current' in innerRef) (innerRef as React.MutableRefObject<HTMLVideoElement | null>).current = el
    },
    [innerRef],
  )

  const resetHideTimer = useCallback(() => {
    if (hideTimer.current) clearTimeout(hideTimer.current)
    setShowControls(true)
    hideTimer.current = setTimeout(() => {
      if (playing) setShowControls(false)
    }, 3000)
  }, [playing])

  useEffect(() => {
    resetHideTimer()
    return () => { if (hideTimer.current) clearTimeout(hideTimer.current) }
  }, [playing, resetHideTimer])

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

  const handleVolumeChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const v = videoRef.current
    if (!v) return
    const vol = parseFloat(e.target.value)
    v.volume = vol
    setVolume(vol)
    if (vol > 0 && v.muted) { v.muted = false; setMuted(false) }
    if (vol === 0) { v.muted = true; setMuted(true) }
  }, [])

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ ...style, position: 'relative', cursor: 'pointer' }}
      onMouseMove={resetHideTimer}
      onTouchStart={resetHideTimer}
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
        onClick={togglePlay}
      />

      {/* Controls overlay */}
      <div
        style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          background: 'linear-gradient(transparent, rgba(0,0,0,0.7))',
          padding: '24px 12px 8px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
          opacity: showControls ? 1 : 0,
          transition: 'opacity 0.3s',
          pointerEvents: showControls ? 'auto' : 'none',
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
            style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', fontSize: '16px', padding: '2px 4px' }}
          >
            {playing ? '\u23F8' : '\u25B6'}
          </button>

          {/* Time */}
          <span style={{ fontVariantNumeric: 'tabular-nums', minWidth: '80px' }}>
            {formatTime(currentTime)} / {formatTime(duration)}
          </span>

          <div style={{ flex: 1 }} />

          {/* Volume */}
          <button
            onClick={toggleMute}
            aria-label={muted ? t('reader.videoUnmute') : t('reader.videoMute')}
            style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', fontSize: '16px', padding: '2px 4px' }}
          >
            {muted ? '\uD83D\uDD07' : '\uD83D\uDD0A'}
          </button>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={muted ? 0 : volume}
            onChange={handleVolumeChange}
            aria-label="Volume"
            style={{ width: '60px', height: '4px', cursor: 'pointer', accentColor: '#3b82f6' }}
          />
        </div>
      </div>
    </div>
  )
}
