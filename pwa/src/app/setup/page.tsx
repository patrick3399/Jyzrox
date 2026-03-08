'use client'

import { useState, FormEvent, useEffect } from 'react'
import { useRouter } from 'next/navigation'

import { api } from '@/lib/api'
import { t } from '@/lib/i18n'

export default function SetupPage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.auth
      .needsSetup()
      .then((data) => {
        if (!data.needs_setup) router.replace('/login')
        else setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [router])

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError('')
    if (password !== confirm) {
      setError(t('setup.passwordMismatch'))
      return
    }
    if (password.length < 8) {
      setError(t('setup.passwordTooShort'))
      return
    }
    setLoading(true)
    try {
      await api.auth.setup(username, password)
      window.location.href = '/login'
    } catch (err) {
      setError(err instanceof Error ? err.message : t('setup.failed'))
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
            <h1 className="mt-4 text-2xl font-semibold text-vault-accent">{t('setup.title')}</h1>
            <p className="mt-2 text-sm text-vault-text-muted text-center">{t('setup.subtitle')}</p>
          </div>
          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <label htmlFor="username" className="text-sm text-vault-text-secondary">
                {t('setup.username')}
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
                placeholder="admin"
                className="w-full bg-vault-input border border-vault-border rounded-xl px-4 py-3 text-sm text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent transition-colors disabled:opacity-50"
              />
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="password" className="text-sm text-vault-text-secondary">
                {t('setup.password')}
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                required
                disabled={loading}
                placeholder={t('setup.passwordHint')}
                className="w-full bg-vault-input border border-vault-border rounded-xl px-4 py-3 text-sm text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent transition-colors disabled:opacity-50"
              />
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="confirm" className="text-sm text-vault-text-secondary">
                {t('setup.confirmPassword')}
              </label>
              <input
                id="confirm"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
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
              disabled={loading || !username || !password || !confirm}
              className="mt-2 w-full bg-vault-accent hover:bg-vault-accent/90 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold rounded-full py-3.5 text-sm transition-colors"
            >
              {loading ? t('setup.submitting') : t('setup.submit')}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
