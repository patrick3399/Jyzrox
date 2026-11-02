/** The subscription a create was refused for (409 `{code: "subscription_exists"}`). */
export interface DuplicateSubscriptionHint {
  /** The stored, normalized URL; also stands in for a subscription without a name. */
  url: string
  name: string | null
}

/**
 * Read the "this URL already has a subscription" refusal out of an error thrown
 * by the API client. Anything else (a plain Error, a different 409) is not a hint.
 */
export function duplicateSubscriptionHint(err: unknown): DuplicateSubscriptionHint | null {
  if (typeof err !== 'object' || err === null) return null
  const detail = (err as { detail?: unknown }).detail
  if (typeof detail !== 'object' || detail === null) return null
  const body = detail as { code?: unknown; name?: unknown; url?: unknown }
  if (body.code !== 'subscription_exists' || typeof body.url !== 'string') return null
  return { url: body.url, name: typeof body.name === 'string' && body.name ? body.name : null }
}
