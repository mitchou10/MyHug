import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ErrorNotice } from '@/components/ErrorNotice'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { useDeleteEvaluation, useMetrics, useSetShown } from '../api/evaluations'
import type { Evaluation, Inference, Model } from '../types'
import { formatValue, SourceBadge } from './EvaluationsSection'

/** One evaluation. The people who can edit the model see every metric and choose which ones the others see. */
export function EvaluationDialog({ model, evaluation: e, onClose }: { model: Model; evaluation: Evaluation; onClose: () => void }) {
  const { t } = useTranslation()
  const metrics = useMetrics()
  const setShown = useSetShown(model)
  const remove = useDeleteEvaluation(model)
  const [confirming, setConfirming] = useState(false)

  const known = metrics.data?.get(e.task) ?? []
  // The metrics this person holds a value for, in the order of the task (any the platform does not list come last).
  const order = new Map(known.map((x, i) => [x.id, i]))
  const ids = Object.keys(e.results).sort((a, b) => (order.get(a) ?? 99) - (order.get(b) ?? 99))
  const toggle = (id: string) => setShown.mutate({ id: e.id, shown: e.shown.includes(id) ? e.shown.filter((s) => s !== id) : [...e.shown, id] })

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t(`datasets.annotation.tasks.${e.task}.title`)}{e.dataset ? ` · ${e.dataset}` : ''}</DialogTitle>
          <DialogDescription>
            {[e.split, `v${e.version}`, e.items !== null ? t('models.eval.items', { count: e.items }) : null].filter(Boolean).join(' · ')}
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <SourceBadge evaluation={e} />
            <span>{t(`models.eval.hint.${e.source}`, { user: e.createdByUsername })}</span>
          </div>
          {e.status !== 'done' && <Badge variant={e.status === 'failed' ? 'destructive' : 'secondary'}>{t(`models.eval.status.${e.status}`)}</Badge>}
          {e.error && <p role="alert" className="text-sm text-destructive">{e.error}</p>}
          {e.targetColumn && <p className="text-xs text-muted-foreground">{t('models.eval.target', { column: e.targetColumn })}</p>}
          {e.inference && <InferenceDetails inference={e.inference} />}
          {e.note && <p className="rounded-md border bg-muted/40 p-2 text-sm whitespace-pre-wrap">{e.note}</p>}

          <ul className="space-y-1.5">
            {ids.map((id) => {
              const x = known.find((m) => m.id === id)
              const on = e.shown.includes(id)
              return (
                <li key={id} className={cn('flex items-start gap-2.5 rounded-md border p-2 text-sm', !on && 'bg-muted/40')}>
                  {e.canEdit && (
                    <input type="checkbox" aria-label={t('models.eval.show', { metric: x?.name ?? id })} className="mt-1 size-4 accent-primary" checked={on} disabled={setShown.isPending} onChange={() => toggle(id)} />
                  )}
                  <div className="flex-1">
                    <div className="flex items-baseline gap-2">
                      <span className="font-medium">{x?.name ?? id}{x && !x.higher && ' ↓'}</span>
                      {x?.primary && <Badge variant="secondary">{t('models.eval.main')}</Badge>}
                      <span className="ml-auto font-mono">{formatValue(e.results[id])}</span>
                    </div>
                    <p className="text-xs text-muted-foreground">{t(`models.metrics.${id}`, { defaultValue: '' })}</p>
                  </div>
                </li>
              )
            })}
          </ul>
          {e.canEdit
            ? <p className="text-xs text-muted-foreground">{t('models.eval.mineHint')}</p>
            : e.hidden > 0 && <p className="text-xs text-muted-foreground">{t('models.eval.hiddenBy', { count: e.hidden, user: e.createdByUsername })}</p>}
          <ErrorNotice error={setShown.error ?? remove.error} />
        </div>
        <DialogFooter>
          {e.canEdit && (confirming
            ? <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate(e.id, { onSuccess: onClose })}>{t('models.eval.confirmDelete')}</Button>
            : <Button variant="ghost" className="text-destructive" onClick={() => setConfirming(true)} onBlur={() => setConfirming(false)}>{t('models.eval.delete')}</Button>)}
          <Button variant="outline" onClick={onClose}>{t('models.eval.close')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** How long the model took and on what it ran: told by the person who sent the predictions, or measured by the platform. */
function InferenceDetails({ inference: i }: { inference: Inference }) {
  const { t } = useTranslation()
  const h = i.hardware
  const lines = [
    i.seconds !== null && t('models.eval.inference.time', { seconds: Number(i.seconds.toFixed(2)) }),
    i.msPerItem !== null && t('models.eval.inference.perItem', { ms: Number(i.msPerItem.toFixed(2)) }),
    h && t(`models.eval.inference.device.${h.device}`),
    h?.cpu && (h.cpuCores ? `${h.cpu} · ${t('models.eval.inference.cores', { count: h.cpuCores })}` : h.cpu),
    h?.ramGb != null && t('models.eval.inference.ram', { gb: h.ramGb }),
    ...(h?.gpus.map((g) => (g.memoryGb != null ? `${g.name} · ${g.memoryGb} GB` : g.name)) ?? []),
    h?.os,
    h?.runtime,
  ].filter((line): line is string => typeof line === 'string' && line !== '')
  if (!lines.length) return null
  return (
    <section aria-label={t('models.eval.inference.title')} className="space-y-1 rounded-md border p-2 text-xs">
      <div className="flex items-center gap-2">
        <span className="font-medium">{t('models.eval.inference.title')}</span>
        <Badge variant="outline" title={t(`models.eval.inference.hint.${i.origin}`)}>{t(`models.eval.inference.origin.${i.origin}`)}</Badge>
      </div>
      <ul className="text-muted-foreground">{lines.map((line) => <li key={line}>{line}</li>)}</ul>
    </section>
  )
}
