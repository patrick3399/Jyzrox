import { describe, it, expect } from 'vitest'
import { buildGraph, neighborhood } from '@/lib/novels/graphModel'

const sample = {
  nodes: [
    { id: 'a', label: 'A', type: 'note' as const },
    { id: 'b', label: 'B', type: 'chapter' as const },
    { id: 'c', label: 'C', type: 'chapter' as const },
  ],
  edges: [
    { src: 'a', dst: 'b', kind: 'mention' as const },
    { src: 'b', dst: 'c', kind: 'mention' as const },
  ],
}

describe('graphModel', () => {
  it('buildGraph maps NovelGraph to force-graph nodes/links', () => {
    const g = buildGraph(sample)
    expect(g.nodes[0]).toEqual({ id: 'a', label: 'A', type: 'note' })
    expect(g.links[0]).toEqual({ source: 'a', target: 'b', kind: 'mention' })
  })

  it('neighborhood depth 1 returns center + direct neighbours', () => {
    const sub = neighborhood(buildGraph(sample), 'a', 1)
    expect(sub.nodes.map((n) => n.id).sort()).toEqual(['a', 'b'])
    expect(sub.links).toHaveLength(1)
  })

  it('neighborhood depth 2 reaches two hops', () => {
    const sub = neighborhood(buildGraph(sample), 'a', 2)
    expect(sub.nodes.map((n) => n.id).sort()).toEqual(['a', 'b', 'c'])
    expect(sub.links).toHaveLength(2)
  })

  it('neighborhood tolerates force-graph object-ified link ends', () => {
    const g = buildGraph(sample)
    // react-force-graph mutates source/target into node objects post-render
    g.links[0] = { source: { id: 'a' }, target: { id: 'b' }, kind: 'mention' } as never
    const sub = neighborhood(g, 'a', 1)
    expect(sub.nodes.map((n) => n.id).sort()).toEqual(['a', 'b'])
  })
})
