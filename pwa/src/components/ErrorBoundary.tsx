'use client'

import React, { useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { t } from '@/lib/i18n'

interface Props {
  children: React.ReactNode
  fallback?: React.ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

// Watches for pathname changes and calls onPathnameChange when the route
// transitions away from the path that was active when an error occurred.
// Using useRef to track the previous pathname avoids triggering a reset on
// the initial mount (which would immediately clear a freshly caught error).
function PathnameReset({ onPathnameChange }: { onPathnameChange: () => void }) {
  const pathname = usePathname()
  const prevPathnameRef = useRef<string | undefined>(undefined)

  useEffect(() => {
    if (prevPathnameRef.current !== undefined && prevPathnameRef.current !== pathname) {
      onPathnameChange()
    }
    prevPathnameRef.current = pathname
  }, [pathname, onPathnameChange])

  return null
}

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
    this.reset = this.reset.bind(this)
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, errorInfo)
  }

  reset() {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      return (
        <>
          <PathnameReset onPathnameChange={this.reset} />
          <div className="flex flex-col items-center justify-center min-h-[50vh] gap-4 p-8">
            <div className="text-red-500 text-lg font-semibold">{t('common.errorOccurred')}</div>
            <p className="text-sm text-vault-text-secondary max-w-md text-center">
              {this.state.error?.message || 'An unexpected error occurred'}
            </p>
            <button
              onClick={this.reset}
              className="px-4 py-2 bg-vault-accent text-white rounded-lg hover:opacity-90 transition-opacity"
            >
              {t('common.retry')}
            </button>
          </div>
        </>
      )
    }
    return (
      <>
        <PathnameReset onPathnameChange={this.reset} />
        {this.props.children}
      </>
    )
  }
}
