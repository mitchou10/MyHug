import { Upload, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ErrorNotice } from '@/components/ErrorNotice'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PartFailed, WrongFile } from '../api/upload'
import { useUpload } from '../api/useUpload'
import { useCreateCodeVersion, type CodeInput } from '../api/versions'
import { formatBytes, pathOf } from '../format'
import type { Model } from '../types'

interface Chosen { file: File; path: string }

/** The two kinds of failure that are not the API's: a part that did not arrive, and files that are not the announced ones. */
function Failure({ error }: { error: unknown }) {
  const { t } = useTranslation()
  if (error instanceof PartFailed) return <p role="alert" className="text-sm text-destructive">{t('models.upload.partFailed', { number: error.number, path: error.path })}</p>
  if (error instanceof WrongFile) return <p role="alert" className="text-sm text-destructive">{t('models.upload.wrongFile', { path: error.path })}</p>
  return <ErrorNotice error={error} />
}

/**
 * A new version: files (sent in parts straight to the storage, with a progress bar), a link to the code, or both. An
 * interrupted upload is found again after a reload: choose the same files and it goes on from the parts that arrived.
 */
export function UploadDialog({ model, open, onOpenChange }: { model: Model; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const upload = useUpload(model.owner, model.name)
  const codeOnly = useCreateCodeVersion(model.owner, model.name)
  const [files, setFiles] = useState<Chosen[]>([])
  const [message, setMessage] = useState('')
  const [url, setUrl] = useState('')
  const [ref, setRef] = useState('')
  const [path, setPath] = useState('')
  const [entrypoint, setEntrypoint] = useState('')
  const input = useRef<HTMLInputElement>(null)

  const { phase, pending } = upload
  const busy = phase.kind === 'sending' || phase.kind === 'completing' || codeOnly.isPending
  const code: CodeInput | undefined = url.trim() ? { url: url.trim(), ref: ref.trim() || undefined, path: path.trim() || undefined, entrypoint: entrypoint.trim() || undefined } : undefined
  const ready = files.length > 0 || !!code
  const resuming = !!pending && phase.kind !== 'sending' && phase.kind !== 'completing'

  const choose = (list: FileList | null) => {
    if (!list) return
    setFiles((old) => {
      const next = new Map(old.map((c) => [c.path, c]))
      Array.from(list).forEach((file) => next.set(pathOf(file), { file, path: pathOf(file) }))
      return [...next.values()]
    })
  }
  const close = () => { if (!busy) { upload.reset(); onOpenChange(false) } }
  const submit = () => {
    if (!files.length && code) return codeOnly.mutate({ code, message: message.trim() }, { onSuccess: () => onOpenChange(false) })
    void upload.start({ files, message: message.trim(), remove: [], code })
  }
  const percent = phase.kind === 'sending' && phase.progress.total ? Math.round((phase.progress.sent / phase.progress.total) * 100) : 0

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('models.upload.title')}</DialogTitle>
          <DialogDescription>{t('models.upload.hint')}</DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          {resuming && (
            <div role="status" className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:bg-amber-950/30">
              <p>{t('models.upload.interrupted', { count: pending.files.length })}</p>
              <ul className="text-xs text-muted-foreground">{pending.files.map((f) => <li key={f.id}>{f.path} · {formatBytes(f.size_bytes)}</li>)}</ul>
              <div className="flex gap-2">
                <Button size="sm" disabled={!files.length} onClick={() => void upload.resume(files)}>{t('models.upload.resume')}</Button>
                <Button size="sm" variant="ghost" onClick={() => void upload.cancel()}>{t('models.upload.giveUp')}</Button>
              </div>
              {!files.length && <p className="text-xs">{t('models.upload.chooseAgain')}</p>}
            </div>
          )}

          <div className="space-y-1.5">
            <Label>{t('models.upload.files')}</Label>
            <input ref={input} type="file" multiple hidden aria-label={t('models.upload.choose')} onChange={(e) => { choose(e.target.files); e.target.value = '' }} />
            <Button type="button" variant="outline" disabled={busy} onClick={() => input.current?.click()}><Upload />{t('models.upload.choose')}</Button>
            {files.length > 0 && (
              <ul className="divide-y rounded-lg border text-sm">
                {files.map((c) => (
                  <li key={c.path} className="flex items-center gap-2 px-3 py-1.5">
                    <span className="flex-1 break-all">{c.path}</span>
                    <span className="text-xs text-muted-foreground">{formatBytes(c.file.size)}</span>
                    <Button size="icon" variant="ghost" disabled={busy} aria-label={t('models.upload.remove', { path: c.path })} onClick={() => setFiles((old) => old.filter((x) => x.path !== c.path))}><X /></Button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <fieldset className="space-y-2 rounded-lg border p-3" disabled={busy || resuming}>
            <legend className="px-1 text-sm font-medium">{t('models.upload.code')}</legend>
            <p className="text-xs text-muted-foreground">{t('models.upload.codeHint')}</p>
            <Input aria-label={t('models.upload.codeUrl')} placeholder="https://github.com/owner/repository" value={url} onChange={(e) => setUrl(e.target.value)} />
            <div className="grid gap-2 sm:grid-cols-3">
              <Input aria-label={t('models.upload.codeRef')} placeholder={t('models.upload.codeRef')} value={ref} onChange={(e) => setRef(e.target.value)} />
              <Input aria-label={t('models.upload.codePath')} placeholder={t('models.upload.codePath')} value={path} onChange={(e) => setPath(e.target.value)} />
              <Input aria-label={t('models.upload.codeEntrypoint')} placeholder={t('models.upload.codeEntrypoint')} value={entrypoint} onChange={(e) => setEntrypoint(e.target.value)} />
            </div>
          </fieldset>

          <div className="space-y-1.5">
            <Label htmlFor="v-message">{t('models.upload.message')}</Label>
            <Input id="v-message" maxLength={500} value={message} disabled={busy || resuming} onChange={(e) => setMessage(e.target.value)} />
          </div>

          {phase.kind === 'sending' && (
            <div className="space-y-1">
              <div role="progressbar" aria-label={t('models.upload.progress')} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} className="h-2 overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-primary transition-all" style={{ width: `${percent}%` }} />
              </div>
              <p className="text-xs text-muted-foreground">{t('models.upload.sent', { sent: formatBytes(phase.progress.sent), total: formatBytes(phase.progress.total), percent })}</p>
            </div>
          )}
          {phase.kind === 'completing' && <p role="status" className="text-sm text-muted-foreground">{t('models.upload.completing')}</p>}
          {phase.kind === 'done' && <p role="status" className="text-sm font-medium">{t('models.upload.done', { n: phase.version })}</p>}
          {phase.kind === 'failed' && <Failure error={phase.error} />}
          <ErrorNotice error={codeOnly.error} />
        </div>

        <DialogFooter>
          {phase.kind === 'sending' || phase.kind === 'completing'
            ? <Button variant="outline" disabled={phase.kind === 'completing'} onClick={() => void upload.cancel()}>{t('models.upload.cancel')}</Button>
            : <Button variant="ghost" onClick={close}>{phase.kind === 'done' ? t('models.upload.close') : t('datasets.annotation.cancel')}</Button>}
          {phase.kind !== 'done' && !resuming && <Button disabled={!ready || busy} onClick={submit}>{t('models.upload.send')}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
