import { Code2, ExternalLink } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import type { CodeRef } from '../types'

/**
 * The code a version points to. Only a pinned reference is a link to the exact tree: before that (not looked at yet,
 * private, not found) the badge says so, and a branch is never shown as if it were fixed.
 */
export function CodeReference({ code }: { code: CodeRef }) {
  const { t } = useTranslation()
  const written = code.ref ? `${code.url} @ ${code.ref}` : code.url
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <Code2 className="size-3.5 text-muted-foreground" />
      {code.state === 'pinned' && code.treeUrl && code.sha ? (
        <>
          <a href={code.treeUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-mono underline-offset-2 hover:underline" title={code.treeUrl}>
            {code.sha.slice(0, 12)}<ExternalLink className="size-3" />
          </a>
          <Badge variant="secondary">{t('models.code.pinned')}</Badge>
        </>
      ) : (
        <>
          <span className="break-all text-muted-foreground" title={written}>{written}</span>
          <Badge variant="outline" title={code.error ?? undefined}>{t(`models.code.${code.state}`)}</Badge>
        </>
      )}
    </div>
  )
}
