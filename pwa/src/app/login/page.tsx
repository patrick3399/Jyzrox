'use client'

import { useState, FormEvent, useEffect } from 'react'
import { useRouter } from 'next/navigation'

function Logo() {
  return (
    <svg width="80" height="80" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Pinwheel petals — Immich-inspired colorful flower */}
      <path d="M50 50 C50 30, 65 15, 50 5 C35 15, 50 30, 50 50Z" fill="#F44336" />
      <path d="M50 50 C65 40, 85 40, 90 25 C75 25, 65 35, 50 50Z" fill="#FF9800" />
      <path d="M50 50 C65 55, 80 65, 90 55 C80 45, 65 45, 50 50Z" fill="#4CAF50" />
      <path d="M50 50 C55 65, 60 85, 50 95 C40 85, 45 65, 50 50Z" fill="#2196F3" />
      <path d="M50 50 C35 60, 20 65, 10 55 C20 45, 35 45, 50 50Z" fill="#E91E63" />
      <path d="M50 50 C35 40, 20 30, 10 40 C20 50, 35 50, 50 50Z" fill="#9C27B0" />
      <circle cx="50" cy="50" r="6" fill="#0a0a0a" />
    </svg>
  )
}

export default function LoginPage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/auth/needs-setup')
      .then((r) => r.json())
      .then((data) => {
        if (data.needs_setup) {
          router.replace('/setup')
        } else {
          setLoading(false)
        }
      })
      .catch(() => setLoading(false))
  }, [router])

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })

      if (res.ok) {
        window.location.href = '/'
      } else {
        const data = await res.json().catch(() => ({}))
        setError(data?.detail ?? 'Invalid credentials. Please try again.')
      }
    } catch {
      setError('Network error. Please check your connection.')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-[#4250af] border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="bg-[#0f1118] border border-[#1e2030] rounded-3xl px-8 py-10 shadow-2xl shadow-black/60">
          {/* Logo + title */}
          <div className="flex flex-col items-center mb-8">
            <Logo />
            <h1 className="mt-4 text-2xl font-semibold text-[#8ba4d6]">
              登入
            </h1>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <label htmlFor="username" className="text-sm text-[#9ca3af]">
                電子郵件
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
                className="w-full bg-[#1a1f2e] border border-[#2a2f3e] rounded-xl px-4 py-3 text-sm text-white placeholder-[#555] focus:outline-none focus:border-[#4250af] transition-colors disabled:opacity-50"
              />
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="password" className="text-sm text-[#9ca3af]">
                密碼
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                disabled={loading}
                className="w-full bg-[#1a1f2e] border border-[#2a2f3e] rounded-xl px-4 py-3 text-sm text-white placeholder-[#555] focus:outline-none focus:border-[#4250af] transition-colors disabled:opacity-50"
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
              className="mt-2 w-full bg-[#c5daf6] hover:bg-[#b0cdf0] active:bg-[#9ec0ea] disabled:opacity-40 disabled:cursor-not-allowed text-[#1a1a2e] font-semibold rounded-full py-3.5 text-sm transition-colors"
            >
              {loading ? '登入中…' : '登入'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
