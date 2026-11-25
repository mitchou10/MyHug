import { Play, Square, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import type { Dataset } from '../mockData'
import { itemCount } from './preannotate'
import { getDataset } from '../mockData'
import { modelsFor } from './models'
import { deleteRun, resumeRun, startRun, stopRun } from './runs'
import { statsOf, useAnnotations, type AnnotationProject, type PreRun } from './store'

/** A model's name (it will link to the page of the model once the pre-annotation runs real models). */
function ModelLink({ name, className }: { name: string; className?: string }) {
  return <span className={className}>{name}</span>
}

/** Decisions needed before a model can be compared with the others. */
const MIN_DECISIONS = 10
const pct = (x: number) => `${Math.round(x * 100)} %`

/**
 * Starts, follows, stops and deletes the pre-annotations of a task, and compares the models by what humans did with
 * their proposals. What was decided stays even if a run is deleted: it is what tells which model to trust.
 */
export function PreannotationDialog({ project, dataset, open, onOpenChange }: { project: AnnotationProject; dataset: Dataset; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t, i18n } = useTranslation()
  const { runs, proposals, decisions, answers, projects } = useAnnotations()
  const available = modelsFor(project.task)
  const [model, setModel] = useState<string>(available[0]?.id ?? '')
  // The comparison covers this task, or every task of the same kind on the same kind of data.
  const [scope, setScope] = useState<'task' | 'kind'>('task')
  const [confirming, setConfirming] = useState<string | null>(null)

  const mine = runs.filter((r) => r.projectId === project.id)
  const live = mine.filter((r) => r.status !== 'deleted')
  const running = mine.some((r) => r.status === 'running')
  const pendingOf = (r: PreRun) => Object.values(proposals[project.id] ?? {}).filter((p) => p.runId === r.id).length
  const todo = itemCount(dataset) - Object.keys(answers[project.id] ?? {}).length
  const modalityOf = (p: AnnotationProject) => { const [o, n] = p.datasetKey.split('/'); return getDataset(o, n)?.modality }
  const sameKind = new Set(projects.filter((p) => p.task === project.task && modalityOf(p) === modalityOf(project)).map((p) => p.id))
  const taskDecisions = decisions.filter((d) => (scope === 'task' ? d.projectId === project.id : sameKind.has(d.projectId)))
  const models = [...new Set(taskDecisions.map((d) => d.model))].map((m) => ({ model: m, ...statsOf(taskDecisions.filter((d) => d.model === m)) })).sort((a, b) => b.score - a.score)
  const enough = models.filter((m) => m.decided >= MIN_DECISIONS)
  const fmt = (ts: number) => new Date(ts).toLocaleDateString(i18n.language)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('datasets.annotation.pre.dialog.title')} · {project.name}</DialogTitle>
          <DialogDescription>{t('datasets.annotation.pre.dialog.hint')}</DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-5 overflow-y-auto pr-1">
          {/* Start */}
          <section className="space-y-2">
            <h3 className="text-sm font-medium">{t('datasets.annotation.pre.dialog.start')}</h3>
            <div className="flex flex-wrap items-center gap-2">
              <select aria-label={t('datasets.annotation.pre.dialog.model')} value={model} onChange={(e) => setModel(e.target.value)} className="h-9 rounded-md border bg-background px-2 text-sm" disabled={!available.length}>
                {available.map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
              </select>
              <Button disabled={!available.length || running || todo <= 0} onClick={() => startRun(project.id, model)}><Play />{t('datasets.annotation.pre.dialog.launch')}</Button>
              <span className="text-xs text-muted-foreground">{running ? t('datasets.annotation.pre.dialog.oneAtATime') : t('datasets.annotation.pre.dialog.scope', { n: Math.max(0, todo) })}</span>
            </div>
            <p className="text-xs text-muted-foreground">
              {available.length ? t(`datasets.annotation.pre.models.${model}`, { defaultValue: '' }) : t('datasets.annotation.pre.dialog.noModel')}
              {available.length > 0 && ` ${t('datasets.annotation.pre.dialog.compatible', { task: t(`datasets.annotation.tasks.${project.task}.title`) })}`}
            </p>
          </section>

          {/* Runs */}
          <section className="space-y-2">
            {!live.length && <p className="text-sm text-muted-foreground">{t('datasets.annotation.pre.dialog.none')}</p>}
            {[...live].reverse().map((r) => {
              const st = statsOf(decisions.filter((d) => d.runId === r.id))
              const pending = pendingOf(r)
              return (
                <div key={r.id} className="space-y-2 rounded-lg border p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <ModelLink name={r.model} className="font-medium" />
                    <Badge variant={r.status === 'running' ? 'default' : 'secondary'}>{t(`datasets.annotation.pre.status.${r.status}`)}</Badge>
                    <span className="text-xs text-muted-foreground">{fmt(r.startedAt)}</span>
                    <div className="ml-auto flex gap-1.5">
                      {r.status === 'running' && <Button size="sm" variant="outline" onClick={() => stopRun(r.id)}><Square />{t('datasets.annotation.pre.dialog.stop')}</Button>}
                      {r.status === 'stopped' && <Button size="sm" variant="outline" onClick={() => resumeRun(r.id)}><Play />{t('datasets.annotation.pre.dialog.resume')}</Button>}
                      {confirming === r.id
                        ? <Button size="sm" variant="destructive" onClick={() => { deleteRun(r.id); setConfirming(null) }}>{t('datasets.annotation.pre.dialog.confirmDelete')}</Button>
                        : <Button size="sm" variant="ghost" onClick={() => setConfirming(r.id)} onBlur={() => setConfirming(null)}><Trash2 />{t('datasets.annotation.pre.dialog.delete')}</Button>}
                    </div>
                  </div>
                  <div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted"><div className={cn('h-full', r.status === 'running' ? 'bg-primary' : 'bg-primary/60')} style={{ width: `${r.total ? (r.processed / r.total) * 100 : 100}%` }} /></div>
                    <p className="mt-1 text-xs text-muted-foreground">{t('datasets.annotation.pre.dialog.progress', { done: r.processed, total: r.total })}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    <Badge variant="outline">{t('datasets.annotation.pre.counts.pending', { n: pending })}</Badge>
                    <Badge variant="outline">{t('datasets.annotation.pre.counts.accepted', { n: st.accepted })}</Badge>
                    <Badge variant="outline">{t('datasets.annotation.pre.counts.edited', { n: st.edited })}</Badge>
                    <Badge variant="outline">{t('datasets.annotation.pre.counts.rejected', { n: st.rejected })}</Badge>
                    {pending > 0 && <Button size="sm" className="ml-auto" render={<Link to={`/datasets/${project.datasetKey}/annotate/${project.id}`} />}>{t('datasets.annotation.pre.dialog.validate')}</Button>}
                  </div>
                </div>
              )
            })}
            {live.length > 0 && <p className="text-xs text-muted-foreground">{t('datasets.annotation.pre.dialog.deleteHint')}</p>}
          </section>

          {/* Comparison */}
          <section className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-medium">{t('datasets.annotation.pre.compare.title')}</h3>
              <div className="ml-auto flex gap-1">
                <Button size="sm" variant={scope === 'task' ? 'default' : 'outline'} onClick={() => setScope('task')}>{t('datasets.annotation.pre.compare.thisTask')}</Button>
                <Button size="sm" variant={scope === 'kind' ? 'default' : 'outline'} onClick={() => setScope('kind')}>{t('datasets.annotation.pre.compare.sameKind', { task: t(`datasets.annotation.tasks.${project.task}.title`), data: t(`datasets.modalities.${modalityOf(project) ?? 'text'}`) })}</Button>
              </div>
            </div>
            {!models.length ? <p className="text-sm text-muted-foreground">{t('datasets.annotation.pre.compare.empty')}</p> : (
              <>
                <div className="overflow-x-auto rounded-lg border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/50 text-left">
                      <tr>{(['model', 'decided', 'asIs', 'edited', 'rejected', 'conf', 'score'] as const).map((k) => <th key={k} className="px-2 py-1.5 font-medium">{t(`datasets.annotation.pre.compare.cols.${k}`)}</th>)}</tr>
                    </thead>
                    <tbody>
                      {models.map((m) => (
                        <tr key={m.model} className={cn('border-t', enough[0]?.model === m.model && 'bg-primary/5 font-medium')}>
                          <td className="px-2 py-1.5">{m.model}</td>
                          <td className="px-2 py-1.5">{m.decided}</td>
                          <td className="px-2 py-1.5">{pct(m.acceptRate)}</td>
                          <td className="px-2 py-1.5">{pct(m.decided ? m.edited / m.decided : 0)}</td>
                          <td className="px-2 py-1.5">{pct(m.decided ? m.rejected / m.decided : 0)}</td>
                          <td className="px-2 py-1.5">{m.confAccepted ? pct(m.confAccepted) : '—'} / {m.confRejected ? pct(m.confRejected) : '—'}</td>
                          <td className="px-2 py-1.5">{pct(m.score)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-xs text-muted-foreground">
                  {enough.length > 1 || (enough.length === 1 && models.length === 1)
                    ? t('datasets.annotation.pre.compare.best', { model: enough[0].model, score: Math.round(enough[0].score * 100) })
                    : t('datasets.annotation.pre.compare.notEnough', { n: MIN_DECISIONS })}
                </p>
                <p className="text-xs text-muted-foreground">{t('datasets.annotation.pre.compare.how')}</p>
              </>
            )}
          </section>
        </div>
      </DialogContent>
    </Dialog>
  )
}
