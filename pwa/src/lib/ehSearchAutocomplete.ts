import type { TagItem } from '@/lib/types'

const NAMESPACE_PREFIXES: Record<string, string> = {
  a: 'artist',
  c: 'character',
  cos: 'cosplayer',
  f: 'female',
  g: 'group',
  l: 'language',
  m: 'male',
  o: 'other',
  p: 'parody',
  r: 'reclass',
  x: 'mixed',
}

export type EhAutocompleteFragment = {
  start: number
  query: string
  excluded: boolean
}

export function getEhAutocompleteFragment(value: string): EhAutocompleteFragment | null {
  let start = 0
  let quoted = false
  const tokenStarts = [0]
  for (let index = 0; index < value.length; index += 1) {
    const char = value[index]
    if (char === '"') quoted = !quoted
    if (/\s/.test(char) && !quoted && index + 1 < value.length && !/\s/.test(value[index + 1])) {
      start = index + 1
      tokenStarts.push(start)
    }
  }

  for (let index = tokenStarts.length - 2; index >= 0; index -= 1) {
    const candidateStart = tokenStarts[index]
    const candidateEnd = tokenStarts[index + 1] - 1
    const candidate = value.slice(candidateStart, candidateEnd)
    if (candidate.includes('$')) break
    if (candidate.includes(':')) {
      start = candidateStart
      break
    }
  }

  const raw = value.slice(start).trimStart()
  if (!raw || raw.endsWith('$') || raw.endsWith('$"')) return null
  const excluded = raw.startsWith('-')
  const token = excluded ? raw.slice(1) : raw
  if (!token) return null

  const colon = token.indexOf(':')
  if (colon === -1) {
    const query = token.replace(/["$]/g, '').trim()
    return query ? { start, query, excluded } : null
  }

  const rawNamespace = token.slice(0, colon).toLowerCase()
  const namespace = NAMESPACE_PREFIXES[rawNamespace] ?? rawNamespace
  const name = token
    .slice(colon + 1)
    .replace(/["$]/g, '')
    .trim()
  const query = `${namespace}:${name}`
  return { start, query, excluded }
}

export function applyEhAutocompleteSuggestion(
  value: string,
  fragment: EhAutocompleteFragment,
  tag: Pick<TagItem, 'namespace' | 'name'>,
): string {
  const exactName = tag.name.includes(' ') ? `"${tag.name}$"` : `${tag.name}$`
  const replacement = `${fragment.excluded ? '-' : ''}${tag.namespace}:${exactName}`
  return `${value.slice(0, fragment.start)}${replacement} `
}
