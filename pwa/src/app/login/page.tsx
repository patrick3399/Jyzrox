'use client'

import { useState, FormEvent, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'

import { api } from '@/lib/api'
import { t } from '@/lib/i18n'

export default function LoginPage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    // If we already have a valid session, go straight to dashboard
    api.auth
      .check()
      .then(() => {
        router.replace('/')
      })
      .catch(() => {
        // Session invalid or missing — check if first-run setup needed
        api.auth
          .needsSetup()
          .then((data) => {
            if (!mountedRef.current) return
            if (data.needs_setup) router.replace('/setup')
            else setLoading(false)
          })
          .catch(() => {
            if (mountedRef.current) setLoading(false)
          })
      })
  }, [router])

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await api.auth.login(username, password)
      window.location.href = '/'
    } catch (err) {
      setError(err instanceof Error ? err.message : t('login.invalidCredentials'))
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-vault-bg flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-vault-accent border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-vault-bg flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="bg-vault-card border border-vault-border rounded-3xl px-8 py-10 shadow-2xl">
          <div className="flex flex-col items-center mb-8">
            <img src="/icon-192x192.png" alt="Jyzrox" width={80} height={80} />
            <h1 className="mt-4 text-2xl font-semibold text-vault-accent">{t('login.title')}</h1>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <label htmlFor="username" className="text-sm text-vault-text-secondary">
                {t('login.accountOrEmail')}
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                required
                disabled={loading}
                className="w-full bg-vault-input border border-vault-border rounded-xl px-4 py-3 text-sm text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent transition-colors disabled:opacity-50"
              />
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="password" className="text-sm text-vault-text-secondary">
                {t('login.password')}
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                disabled={loading}
                className="w-full bg-vault-input border border-vault-border rounded-xl px-4 py-3 text-sm text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent transition-colors disabled:opacity-50"
              />
            </div>
            {error && (
              <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2.5">
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={loading || !username || !password}
              className="mt-2 w-full bg-vault-accent hover:bg-vault-accent/90 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold rounded-full py-3.5 text-sm transition-colors"
            >
              {loading ? t('login.submitting') : t('login.submit')}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
