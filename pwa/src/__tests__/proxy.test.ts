// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { NextRequest } from 'next/server'
import { proxy } from '@/proxy'

function request(path: string, session?: string): NextRequest {
  const req = new NextRequest(new URL(path, 'http://jyzrox.test'))
  if (session) req.cookies.set('vault_session', session)
  return req
}

function redirectTarget(res: Response): string | null {
  const location = res.headers.get('location')
  return location ? new URL(location).pathname : null
}

describe('proxy — login redirect for requests without a session cookie', () => {
  it('redirects an anonymous request for an app page to /login', () => {
    expect(redirectTarget(proxy(request('/library')))).toBe('/login')
  })

  it('lets /login and /setup through without a session', () => {
    expect(redirectTarget(proxy(request('/login')))).toBeNull()
    expect(redirectTarget(proxy(request('/setup')))).toBeNull()
  })

  // Regression: share links are for people without an account, and LayoutShell
  // already renders /share/ as a public page, but the proxy only exempted
  // /login and /setup. Opening a share link without a session cookie bounced
  // the recipient to the login page before the share page could load.
  it('lets an anonymous request for a share link through to the share page', () => {
    expect(redirectTarget(proxy(request('/share/abc123')))).toBeNull()
  })

  it('still redirects paths that only look like the share prefix', () => {
    expect(redirectTarget(proxy(request('/share')))).toBe('/login')
    expect(redirectTarget(proxy(request('/shared/abc123')))).toBe('/login')
  })

  it('does not redirect a request that carries a session cookie', () => {
    expect(redirectTarget(proxy(request('/library', '1:token')))).toBeNull()
  })
})
