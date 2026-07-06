import { visit } from 'unist-util-visit'
import type { Root, Text } from 'mdast'
import type { Plugin } from 'unified'

// [[Name]], [[Name|alias]], [[Name#anchor]] — mirror of the backend parser in
// services/novel_fs.py (parse_backlinks) and the reader's inline regex.
const WIKILINK = /\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]/g

/**
 * remark plugin: turn `[[Name]]` in text nodes into a highlighted span.
 *
 * Emits a synthetic node whose `data.hName`/`hProperties`/`hChildren` map it to
 * a `<span>` at hast time — Phase 1 will make these clickable entity cards. Only
 * inline text is split; block nodes keep their original source `position`, so
 * inline-edit line mapping is unaffected.
 */
export const remarkWikilink: Plugin<[], Root> = () => {
  return (tree) => {
    visit(tree, 'text', (node: Text, index, parent) => {
      if (!parent || index === undefined || !node.value.includes('[[')) return
      const value = node.value
      const replacement: Text[] = []
      let last = 0
      let m: RegExpExecArray | null
      WIKILINK.lastIndex = 0
      while ((m = WIKILINK.exec(value)) !== null) {
        if (m.index > last) {
          replacement.push({ type: 'text', value: value.slice(last, m.index) })
        }
        const name = m[1].trim()
        replacement.push({
          type: 'text',
          value: name,
          data: {
            hName: 'span',
            hProperties: {
              className: 'text-vault-accent underline decoration-dotted',
              'data-wikilink': name,
            },
            hChildren: [{ type: 'text', value: name }],
          },
        } as Text)
        last = m.index + m[0].length
      }
      if (replacement.length === 0) return
      if (last < value.length) {
        replacement.push({ type: 'text', value: value.slice(last) })
      }
      parent.children.splice(index, 1, ...replacement)
      return index + replacement.length
    })
  }
}
