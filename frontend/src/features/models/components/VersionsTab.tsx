import { ExternalLink, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ErrorNotice } from '@/components/ErrorNotice'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useDeleteVersion, useVersions } from '../api/versions'
import { formatBytes } from '../format'
import type { Model, ModelVersion } from '../types'
import { CodeReference } from './CodeReference'

/** What a person reads of the state of a version: a worker reads its files before it is `ready`. */
export function StatusBadge({ version }: { version: ModelVersion }) {
  const { t } = useTranslation()
  if (version.status === 'ready') return <Badge variant="secondary">{t('models.versions.status.ready')}</Badge>
  if (version.status === 'failed') return <Badge variant="destructive">{t('models.versions.status.failed')}</Badge>
  return <Badge variant="outline">{t('models.versions.status.checking')}</Badge>
}

/** The versions of a model, the newest first: its state, its files' size, the code it points to. */
export function VersionsTab({ model }: { model: Model }) {
  const { t, i18n } = useTranslation()
  const versions = useVersions(model.owner, model.name)
  const remove = useDeleteVersion(model.owner, model.name)
  const [confirming, setConfirming] = useState<number | null>(null)

  if (versions.isPending) return <p className="text-sm text-muted-foreground">{t('models.loading')}</p>
  if (versions.isError) return <ErrorNotice error={versions.error} />
  if (!versions.data.length) return <p className="text-sm text-muted-foreground">{t('models.versions.none')}</p>

  return (
    <div className="space-y-2">
      <ErrorNotice error={remove.error} />
      <ul className="divide-y rounded-lg border">
        {versions.data.map((v) => (
          <li key={v.number} className="space-y-1.5 px-4 py-3 text-sm">
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-mono font-medium">v{v.number}</span>
              {v.number === model.version && <Badge>{t('models.versions.current')}</Badge>}
              <StatusBadge version={v} />
              <span className="flex-1 text-muted-foreground">{v.message}</span>
              <span className="text-xs text-muted-foreground">{v.sizeBytes ? `${formatBytes(v.sizeBytes)} · ` : ''}{new Date(v.createdAt).toLocaleDateString(i18n.language)} · {v.createdByUsername}</span>
              {v.mlflowUrl && (
                <a href={v.mlflowUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs underline-offset-2 hover:underline">
                  MLflow<ExternalLink className="size-3" />
                </a>
              )}
              {model.canEdit && (confirming === v.number
                ? <Button size="sm" variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate(v.number, { onSettled: () => setConfirming(null) })}>{t('models.versions.confirmDelete')}</Button>
                : <Button size="icon" variant="ghost" aria-label={t('models.versions.delete', { n: v.number })} onClick={() => setConfirming(v.number)} onBlur={() => setConfirming(null)}><Trash2 /></Button>)}
            </div>
            {v.status === 'failed' && v.error && <p role="alert" className="text-xs text-destructive">{v.error}</p>}
            {v.code && <CodeReference code={v.code} />}
          </li>
        ))}
      </ul>
    </div>
  )
}
