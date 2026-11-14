'use client'

import { t } from '@/lib/i18n'

/** The search-syntax cheat sheet shown by the desktop panel and the phone filter sheet. */
export function LibrarySyntaxHelpLines() {
  return (
    <div className="mt-4 p-3 bg-vault-input border border-vault-border rounded-lg text-xs text-vault-text-secondary space-y-1 font-mono">
      <p>character:rem — {t('library.syntaxTagSearch')}</p>
      <p>rem — {t('library.syntaxNameOnly')}</p>
      <p>-general:sketch — {t('library.syntaxExclude')}</p>
      <p>title:&quot;re zero&quot; — {t('library.syntaxTitle')}</p>
      <p>source:ehentai — {t('library.syntaxSource')}</p>
      <p>rating:&gt;=4 — {t('library.syntaxRating')}</p>
      <p>favorited:true — {t('library.syntaxFavorited')}</p>
      <p>sort:rating — {t('library.syntaxSort')}</p>
      <p>collection:5 — {t('library.syntaxCollection')}</p>
      <p>artist_id:xxx — {t('library.syntaxArtistId')}</p>
      <p>category:doujinshi — {t('library.syntaxCategory')}</p>
      <p>category:manga category:cosplay — {t('library.syntaxMultiFacet')}</p>
      <p>-source:local:link — {t('library.syntaxExcludeFacet')}</p>
      <p>import:link — {t('library.syntaxImportMode')}</p>
      <p>rl:true — {t('library.syntaxReadingList')}</p>
    </div>
  )
}
