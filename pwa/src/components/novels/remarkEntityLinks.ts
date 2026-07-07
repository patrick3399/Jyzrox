import { visit } from 'unist-util-visit'
import type { Root, Text } from 'mdast'
import type { Plugin } from 'unified'

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * remark plugin factory: link the first occurrence of each known entity name in
 * the prose to its card. A sibling of remarkWikilink for the knowledge layer —
 * this is the "read and click straight to the setting" path. Because the corpus
 * has ~no wikilinks, plain-text names are the primary hook.
 *
 * Skips nodes already transformed (e.g. by remarkWikilink) and never touches
 * inline code (a different mdast node type). Only the first occurrence per
 * document is linked, to avoid turning a frequent name into noise.
 */
export function remarkEntityLinks(
  names: string[],
  hrefFor: (name: string) => string,
): Plugin<[], Root> {
  const ordered = [...new Set(names.filter(Boolean))].sort((a, b) => b.length - a.length)
  return () => (tree) => {
    if (ordered.length === 0) return
    const pattern = new RegExp(ordered.map(escapeRegExp).join('|'), 'g')
    const linked = new Set<string>()
    visit(tree, 'text', (node: Text, index, parent) => {
      if (!parent || index === undefined) return
      if ((node as Text & { data?: { hName?: string } }).data?.hName) return
      const value = node.value
      const replacement: Text[] = []
      let last = 0
      let m: RegExpExecArray | null
      pattern.lastIndex = 0
      while ((m = pattern.exec(value)) !== null) {
        const name = m[0]
        if (linked.has(name)) continue // leave repeats as plain text
        linked.add(name)
        if (m.index > last) replacement.push({ type: 'text', value: value.slice(last, m.index) })
        replacement.push({
          type: 'text',
          value: name,
          data: {
            hName: 'a',
            hProperties: {
              href: hrefFor(name),
              className: 'text-vault-accent underline decoration-dotted',
              'data-entity': name,
            },
            hChildren: [{ type: 'text', value: name }],
          },
        } as Text)
        last = m.index + name.length
      }
      if (replacement.length === 0) return
      if (last < value.length) replacement.push({ type: 'text', value: value.slice(last) })
      parent.children.splice(index, 1, ...replacement)
      return index + replacement.length
    })
  }
}
