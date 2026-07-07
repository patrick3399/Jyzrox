'use client'

import dynamic from 'next/dynamic'
import { useMemo } from 'react'
import { useRouter } from 'next/navigation'
import type { NovelGraph } from '@/lib/api'
import { buildGraph } from '@/lib/novels/graphModel'
import { novelNoteHref } from '@/lib/novels'

// Canvas/WebGL renderer — browser only; never SSR.
const ForceGraph2D = dynamic(() => import('react-force-graph-2d'), { ssr: false })

const NOTE_COLOR = '#7c9cff'
const CHAPTER_COLOR = '#9aa0aa'

// Supertype of the library's internal NodeObject (which carries an index
// signature) so the accessor callbacks type-check against it.
type GNode = { id?: string | number; type?: string; label?: string; [k: string]: unknown }

/** Interactive force-directed view of notes (worldview entities) and the chapters
 *  they appear in. Clicking an entity node opens its card. */
export function KnowledgeGraph({ data }: { data: NovelGraph }) {
  const router = useRouter()
  const graph = useMemo(() => buildGraph(data), [data])

  return (
    <ForceGraph2D
      graphData={graph}
      nodeRelSize={5}
      nodeLabel={(n: GNode) => n.label ?? ''}
      nodeColor={(n: GNode) => (n.type === 'note' ? NOTE_COLOR : CHAPTER_COLOR)}
      linkColor={() => 'rgba(150,150,150,0.28)'}
      linkWidth={0.6}
      cooldownTicks={100}
      onNodeClick={(n: GNode) => {
        if (n.type === 'note' && n.id != null) router.push(novelNoteHref(String(n.id)))
      }}
    />
  )
}
