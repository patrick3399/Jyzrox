export type BrowseSurfaceIdentity = {
  surface: string
}

export type BrowseIdentityNormalizer<Identity extends BrowseSurfaceIdentity> = (
  identity: Identity,
) => unknown

type CanonicalValue =
  | null
  | boolean
  | number
  | string
  | CanonicalValue[]
  | { [key: string]: CanonicalValue }

function canonicalize(value: unknown): CanonicalValue {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return value
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (Array.isArray(value)) return value.map(canonicalize)
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    const result: Record<string, CanonicalValue> = {}
    for (const key of Object.keys(record).sort()) {
      const entry = record[key]
      if (entry !== undefined) result[key] = canonicalize(entry)
    }
    return result
  }
  return null
}

/** Serialize an identity with stable object-key ordering. Array order remains significant. */
export function canonicalIdentityKey(identity: unknown): string {
  return JSON.stringify(canonicalize(identity))
}

/** Apply only the normalizer registered for the identity's active surface. */
export function normalizeBrowseIdentity<Identity extends BrowseSurfaceIdentity>(
  identity: Identity,
  normalizers: Partial<Record<string, BrowseIdentityNormalizer<Identity>>>,
): Identity {
  const normalize = normalizers[identity.surface]
  if (!normalize) return identity
  return normalize(identity) as Identity
}
