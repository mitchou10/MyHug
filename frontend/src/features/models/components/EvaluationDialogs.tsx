import { Play } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { DATASETS } from '@/features/datasets/mockData'
import { cn } from '@/lib/utils'
import { deleteEvaluation, startEvaluation, stopEvaluation } from '../evaluate'
import { defaultShown, metricsFor, primaryOf } from '../metrics'
import { isLauncher, patchEvaluation, type Evaluation } from '../store'
import type { Model } from '../types'

/** A metric as a checkbox: its name, what it measures, and which way is better. */
function MetricChoice({ task, ids, onChange }: { task: Parameters<typeof metricsFor>[0]; ids: string[]; onChange: (ids: string[]) => void }) {
  const { t } = useTranslation()
  const all = metricsFor(task)
  const toggle = (id: string) => onChange(ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id])
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <Button type="button" size="sm" variant="outline" onClick={() => onChange(all.map((x) => x.id))}>{t('models.eval.all')}</Button>
        <Button type="button" size="sm" variant="outline" onClick={() => onChange([primaryOf(task).id])}>{t('models.eval.mainOnly')}</Button>
      </div>
      <ul className="space-y-1">
        {all.map((x) => (
          <li key={x.id}>
            <label className="flex cursor-pointer items-start gap-2.5 rounded-md border p-2 text-sm">
              <input type="checkbox" className="mt-0.5 size-4 accent-primary" checked={ids.includes(x.id)} onChange={() => toggle(x.id)} />
              <span>
                <span className="font-medium">{x.name}</span>{x.primary && <Badge variant="secondary" className="ml-2">{t('models.eval.main')}</Badge>}
                <span className="block text-xs text-muted-foreground">{t(`models.metrics.${x.id}`, { defaultValue: '' })} {x.higher ? t('models.eval.higher') : t('models.eval.lower')}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Launches an evaluation: which task, on which part of which dataset, and which of its metrics to show. */
export function StartEvaluationDialog({ model, open, onOpenChange }: { model: Model; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const sets = DATASETS.filter((d) => model.inputs.includes(d.modality))
  const [task, setTask] = useState(model.tasks[0])
  const [dataset, setDataset] = useState(sets[0] ? `${sets[0].owner}/${sets[0].name}` : '')
  const [split, setSplit] = useState<'test' | 'validation'>('test')
  const [shown, setShown] = useState<string[]>(model.tasks[0] ? defaultShown(model.tasks[0]) : [])

  const ready = !!task && !!dataset && shown.length > 0
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('models.eval.start.title')}</DialogTitle>
          <DialogDescription>{t('models.eval.start.hint')}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          <div className="space-y-1.5">
            <Label htmlFor="ev-task">{t('models.eval.start.task')}</Label>
            <select id="ev-task" value={task} onChange={(e) => { const k = e.target.value as typeof task; setTask(k); setShown(defaultShown(k)) }} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
              {model.tasks.map((k) => <option key={k} value={k}>{t(`datasets.annotation.tasks.${k}.title`)}</option>)}
            </select>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="ev-ds">{t('models.eval.dataset')}</Label>
              <select id="ev-ds" value={dataset} onChange={(e) => setDataset(e.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                {sets.map((d) => <option key={d.id} value={`${d.owner}/${d.name}`}>{d.owner}/{d.name}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ev-split">{t('models.eval.split')}</Label>
              <select id="ev-split" value={split} onChange={(e) => setSplit(e.target.value as 'test' | 'validation')} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                <option value="test">test</option><option value="validation">validation</option>
              </select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>{t('models.eval.start.metrics')}</Label>
            <p className="text-xs text-muted-foreground">{t('models.eval.start.metricsHint')}</p>
            {task && <MetricChoice task={task} ids={shown} onChange={setShown} />}
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('datasets.annotation.cancel')}</Button>
          <Button disabled={!ready} onClick={() => { startEvaluation({ modelId: model.address, version: String(model.version), task, dataset, split, shown }); onOpenChange(false) }}><Play />{t('models.eval.start.launch')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** One evaluation. The person who launched it sees every metric and chooses which ones the others see. */
export function EvaluationDialog({ evaluation: e, onClose }: { evaluation: Evaluation; onClose: () => void }) {
  const { t } = useTranslation()
  const mine = isLauncher(e)
  const all = metricsFor(e.task)
  const shownMetrics = all.filter((x) => e.shown.includes(x.id))
  const hidden = all.length - shownMetrics.length
  const rows = mine ? all : shownMetrics

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t(`datasets.annotation.tasks.${e.task}.title`)} · {e.dataset}</DialogTitle>
          <DialogDescription>{e.split} · v{e.version} · {t('models.eval.by', { user: e.startedBy })}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
          {e.status === 'running' && (
            <div>
              <div className="h-2 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary" style={{ width: `${(e.processed / e.total) * 100}%` }} /></div>
              <p className="mt-1 text-xs text-muted-foreground">{t('datasets.annotation.pre.dialog.progress', { done: e.processed, total: e.total })}</p>
            </div>
          )}
          {e.results && (
            <ul className="space-y-1.5">
              {rows.map((x) => {
                const on = e.shown.includes(x.id)
                return (
                  <li key={x.id} className={cn('flex items-start gap-2.5 rounded-md border p-2 text-sm', !on && 'bg-muted/40')}>
                    {mine && <input type="checkbox" aria-label={t('models.eval.show', { metric: x.name })} className="mt-1 size-4 accent-primary" checked={on}
                      onChange={() => patchEvaluation(e.id, { shown: on ? e.shown.filter((s) => s !== x.id) : [...e.shown, x.id] })} />}
                    <div className="flex-1">
                      <div className="flex items-baseline gap-2"><span className="font-medium">{x.name}{!x.higher && ' ↓'}</span>{x.primary && <Badge variant="secondary">{t('models.eval.main')}</Badge>}<span className="ml-auto font-mono">{e.results![x.id]}</span></div>
                      <p className="text-xs text-muted-foreground">{t(`models.metrics.${x.id}`, { defaultValue: '' })}</p>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
          {mine ? <p className="text-xs text-muted-foreground">{t('models.eval.mineHint')}</p> : hidden > 0 && <p className="text-xs text-muted-foreground">{t('models.eval.hiddenBy', { n: hidden, user: e.startedBy })}</p>}
        </div>
        <DialogFooter>
          {mine && e.status === 'running' && <Button variant="outline" onClick={() => stopEvaluation(e.id)}>{t('datasets.annotation.pre.dialog.stop')}</Button>}
          {mine && e.status !== 'running' && <Button variant="ghost" className="text-destructive" onClick={() => { deleteEvaluation(e.id); onClose() }}>{t('datasets.annotation.pre.dialog.delete')}</Button>}
          <Button variant="outline" onClick={onClose}>{t('models.eval.close')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
