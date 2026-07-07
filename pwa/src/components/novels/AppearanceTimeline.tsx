import { t } from '@/lib/i18n'
import type { NovelAppearance } from '@/lib/api'

function chapterName(path: string): string {
  return path.split('/').pop() ?? path
}

/** Vertical timeline of a note's mentions across chapters (chapter-ordered).
 *  The earliest chapter is flagged — this is the character's appearance order. */
export function AppearanceTimeline({ appearances }: { appearances: NovelAppearance[] }) {
  if (appearances.length === 0) {
    return <p className="text-sm text-vault-text-muted">{t('novels.noAppearances')}</p>
  }
  return (
    <ol className="relative space-y-3 border-l border-vault-border pl-5">
      {appearances.map((a, i) => (
        <li key={a.chapter_path} className="relative">
          <span className="absolute -left-[23px] top-1.5 size-2 rounded-full bg-vault-accent" />
          <div className="flex items-center justify-between gap-2">
            <span className="truncate font-medium text-vault-text">{chapterName(a.chapter_path)}</span>
            <span className="shrink-0 text-sm text-vault-text-muted">
              {t('novels.mentionCount', { count: a.mention_count })}
            </span>
          </div>
          {i === 0 && <span className="text-xs text-vault-accent">{t('novels.firstAppearance')}</span>}
        </li>
      ))}
    </ol>
  )
}
