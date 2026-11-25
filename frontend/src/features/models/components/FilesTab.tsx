import { Download, FileText } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ErrorNotice } from '@/components/ErrorNotice'
import { downloadAddress, useVersionFiles, useVersions } from '../api/versions'
import { formatBytes } from '../format'
import type { Model } from '../types'

/** The files of one version (the latest by default), each downloadable through a signed address of the storage. */
export function FilesTab({ model }: { model: Model }) {
  const { t } = useTranslation()
  const versions = useVersions(model.owner, model.name)
  const [chosen, setChosen] = useState<number | null>(null)
  const number = chosen ?? versions.data?.[0]?.number ?? null
  const files = useVersionFiles(model.owner, model.name, number)

  if (versions.isPending) return <p className="text-sm text-muted-foreground">{t('models.loading')}</p>
  if (versions.isError) return <ErrorNotice error={versions.error} />
  if (number === null) return <p className="text-sm text-muted-foreground">{t('models.files.none')}</p>

  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">{t('models.files.version')}</span>
        <select className="h-8 rounded-md border bg-background px-2" value={number} onChange={(e) => setChosen(Number(e.target.value))} aria-label={t('models.files.version')}>
          {versions.data.map((v) => <option key={v.number} value={v.number}>v{v.number}</option>)}
        </select>
      </label>
      {files.isError && <ErrorNotice error={files.error} />}
      {files.data && !files.data.files.length && <p className="text-sm text-muted-foreground">{t('models.files.noneInVersion')}</p>}
      {files.data && files.data.files.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {files.data.files.map((f) => (
            <li key={f.path} className="flex items-center gap-2 px-4 py-2.5 text-sm">
              <FileText className="size-4 text-muted-foreground" />
              <span className="flex-1 break-all">{f.path}</span>
              <span className="text-muted-foreground">{formatBytes(f.sizeBytes)}</span>
              <a className="inline-flex items-center gap-1 text-xs underline-offset-2 hover:underline" href={downloadAddress(model.owner, model.name, f.path, number)} download aria-label={t('models.files.download', { path: f.path })}>
                <Download className="size-4" />
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
