/**
 * Graph assembly + local-neighbourhood filtering for the novel knowledge graph.
 *
 * The BFS depth-filter is adapted from Quartz (jackyzha0/quartz, MIT) —
 * `quartz/components/scripts/graph.inline.ts` — reworked for our NovelGraph shape.
 * Attribution retained per the MIT licence.
 */
import type { NovelGraph } from '@/lib/api'

export interface GraphNode {
  id: string
  label: string
  type: 'note' | 'chapter'
}
export interface GraphLink {
  source: string | { id: string }
  target: string | { id: string }
  kind: 'link' | 'mention'
}
export interface GraphData {
  nodes: GraphNode[]
  links: GraphLink[]
}

export function buildGraph(data: NovelGraph): GraphData {
  return {
    nodes: data.nodes.map((n) => ({ id: n.id, label: n.label, type: n.type })),
    links: data.edges.map((e) => ({ source: e.src, target: e.dst, kind: e.kind })),
  }
}

/** react-force-graph mutates link.source/target into node objects after render. */
function linkEnd(x: string | { id: string }): string {
  return typeof x === 'string' ? x : x.id
}

/** Subgraph of every node within `depth` hops of `centerId` (undirected), and the edges among them. */
export function neighborhood(graph: GraphData, centerId: string, depth: number): GraphData {
  const adjacency = new Map<string, Set<string>>()
  const link = (id: string) => {
    if (!adjacency.has(id)) adjacency.set(id, new Set())
    return adjacency.get(id)!
  }
  for (const l of graph.links) {
    const s = linkEnd(l.source)
    const t = linkEnd(l.target)
    link(s).add(t)
    link(t).add(s)
  }
  const visible = new Set<string>([centerId])
  let frontier = [centerId]
  for (let d = 0; d < depth; d++) {
    const next: string[] = []
    for (const id of frontier) {
      for (const nb of adjacency.get(id) ?? []) {
        if (!visible.has(nb)) {
          visible.add(nb)
          next.push(nb)
        }
      }
    }
    frontier = next
  }
  return {
    nodes: graph.nodes.filter((n) => visible.has(n.id)),
    links: graph.links.filter(
      (l) => visible.has(linkEnd(l.source)) && visible.has(linkEnd(l.target)),
    ),
  }
}
