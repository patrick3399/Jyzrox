// Pages reachable without a session. proxy.ts (login redirect) and LayoutShell
// (no app chrome / WebSocket) must agree on this, so both read it from here.

/** Login and first-run setup — exact paths. */
export const AUTH_PATHS = ['/login', '/setup']

/** Anonymous share-link pages; the backend checks the token itself. */
export const PUBLIC_PATH_PREFIXES = ['/share/']

export function isAuthPath(pathname: string): boolean {
  return AUTH_PATHS.includes(pathname)
}

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix))
}
