'use client'

import { useMemo } from 'react'

/** Render a unified diff string with add/remove/hunk highlighting (read-only). */
export function DiffView({ diff }: { diff: string }) {
  const lines = useMemo(() => diff.split('\n'), [diff])
  return (
    <pre
      data-testid="diff-view"
      className="max-h-[60vh] overflow-auto rounded-lg border border-vault-border bg-black/20 p-3 text-xs leading-relaxed"
    >
      {lines.map((line, i) => {
        let cls = 'text-vault-text-muted'
        if (line.startsWith('+') && !line.startsWith('+++')) cls = 'text-green-400'
        else if (line.startsWith('-') && !line.startsWith('---')) cls = 'text-red-400'
        else if (line.startsWith('@@')) cls = 'text-vault-accent'
        return (
          <div key={i} className={cls}>
            {line || ' '}
          </div>
        )
      })}
    </pre>
  )
}
