import { NextRequest, NextResponse } from 'next/server'

const PUBLIC_PATHS = ['/login', '/setup']

export function proxy(request: NextRequest) {
  const session = request.cookies.get('vault_session')
  const { pathname } = request.nextUrl

  // No cookie → redirect to login (except public paths)
  if (!session && !PUBLIC_PATHS.includes(pathname)) {
    return NextResponse.redirect(new URL('/login', request.url))
  }
  // Don't redirect /login→/ based on cookie alone — the session may be
  // stale (revoked/expired in Redis). Let the login page validate instead.
  return NextResponse.next()
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon\\.ico|favicon-.*\\.png|icon-.*\\.png|apple-touch-icon\\.png|manifest\\.json|sw\\.js|icons).*)',
  ],
}
