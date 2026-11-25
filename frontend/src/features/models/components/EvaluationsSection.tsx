import { Play } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { metricsFor } from '../metrics'
import { useEvaluations, type Evaluation } from '../store'
import type { Model } from '../types'
import { EvaluationDialog, StartEvaluationDialog } from './EvaluationDialogs'

/** The evaluations of a model, task by task, with the metrics their authors chose to show. */
export function EvaluationsSection({ model: m }: { model: Model }) {
  const { t, i18n } = useTranslation()
  const { evaluations } = useEvaluations()
  const [starting, setStarting] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const mine = evaluations.filter((e) => e.modelId === m.address)
  const opened = mine.find((e) => e.id === open)

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-medium">{t('models.eval.benchmarks')}</h2>
        <Button size="sm" className="ml-auto" disabled={!m.tasks.length} onClick={() => setStarting(true)}><Play />{t('models.eval.start.title')}</Button>
      </div>
      {!mine.length && <p className="text-sm text-muted-foreground">{t('models.eval.none')}</p>}

      {m.tasks.map((task) => {
        const rows = mine.filter((e) => e.task === task)
        if (!rows.length) return null
        // The columns: the metrics that at least one evaluation of this task shows, in the order of the task.
        const columns = metricsFor(task).filter((x) => rows.some((e) => e.shown.includes(x.id)))
        return (
          <div key={task} className="space-y-1.5">
            <h3 className="text-xs font-medium text-muted-foreground">{t(`datasets.annotation.tasks.${task}.title`)}</h3>
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-left text-xs">
                  <tr>
                    <th className="px-3 py-2 font-medium">{t('models.eval.dataset')}</th>
                    <th className="px-3 py-2 font-medium">{t('models.eval.split')}</th>
                    <th className="px-3 py-2 font-medium">v</th>
                    {columns.map((x) => <th key={x.id} className="px-3 py-2 font-medium" title={t(`models.metrics.${x.id}`, { defaultValue: '' })}>{x.name}{!x.higher && ' ↓'}</th>)}
                    <th className="px-3 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((e) => <Row key={e.id} e={e} columns={columns} locale={i18n.language} onOpen={() => setOpen(e.id)} />)}
                </tbody>
              </table>
            </div>
          </div>
        )
      })}
      {starting && <StartEvaluationDialog key={m.id} model={m} open onOpenChange={(o) => !o && setStarting(false)} />}
      {opened && <EvaluationDialog evaluation={opened} onClose={() => setOpen(null)} />}
    </section>
  )
}

function Row({ e, columns, locale, onOpen }: { e: Evaluation; columns: ReturnType<typeof metricsFor>; locale: string; onOpen: () => void }) {
  const { t } = useTranslation()
  const hidden = metricsFor(e.task).length - e.shown.length
  return (
    <tr className="cursor-pointer border-t hover:bg-muted/40" onClick={onOpen}>
      <td className="px-3 py-2"><Link className="underline-offset-2 hover:underline" to={`/datasets/${e.dataset}`} onClick={(ev) => ev.stopPropagation()}>{e.dataset}</Link></td>
      <td className="px-3 py-2">{e.split}</td>
      <td className="px-3 py-2">{e.version}</td>
      {e.status === 'done' && columns.map((x) => <td key={x.id} className={`px-3 py-2 font-mono ${x.primary ? 'font-semibold' : ''}`}>{e.shown.includes(x.id) ? e.results?.[x.id] : '·'}</td>)}
      {e.status !== 'done' && (
        <td colSpan={columns.length} className="px-3 py-2">
          <Badge variant={e.status === 'running' ? 'default' : 'secondary'}>{t(`models.eval.status.${e.status}`)}</Badge> <span className="text-xs text-muted-foreground">{Math.round((e.processed / e.total) * 100)} %</span>
        </td>
      )}
      <td className="px-3 py-2 text-right text-xs text-muted-foreground" title={new Date(e.startedAt).toLocaleDateString(locale)}>{hidden > 0 ? t('models.eval.moreMetrics', { n: hidden }) : ''}</td>
    </tr>
  )
}
