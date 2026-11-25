import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { ErrorNotice } from '@/components/ErrorNotice'
import { Badge } from '@/components/ui/badge'
import { useEvaluations, useMetrics } from '../api/evaluations'
import type { Evaluation, Metric, Model } from '../types'
import { EvaluationDialog } from './EvaluationDialog'

/** A value the way a table shows it: three decimals at most, no zeros at the end. */
export const formatValue = (value: number) => String(Number(value.toFixed(3)))

/** How many metrics of an evaluation the others do not see (for the people who can edit it: the ones not shown). */
export const notShown = (e: Evaluation) => (e.canEdit ? Object.keys(e.results).length - e.shown.length : e.hidden)

/** Where an evaluation comes from, always said: a result somebody sent is never taken for one the platform measured. */
export function SourceBadge({ evaluation: e }: { evaluation: Evaluation }) {
  const { t } = useTranslation()
  return (
    <Badge variant={e.source === 'submitted' ? 'outline' : 'secondary'} title={t(`models.eval.${e.source}Hint`, { user: e.createdByUsername })}>
      {t(`models.eval.source.${e.source}`)}
    </Badge>
  )
}

/** The evaluations of a model, task by task, with the metrics their authors chose to show. */
export function EvaluationsSection({ model }: { model: Model }) {
  const { t, i18n } = useTranslation()
  const list = useEvaluations(model)
  const metrics = useMetrics()
  const [open, setOpen] = useState<string | null>(null)

  if (list.isPending || metrics.isPending) return <p className="text-sm text-muted-foreground">{t('models.loading')}</p>
  if (list.isError || metrics.isError) return <ErrorNotice error={list.error ?? metrics.error} />

  const rows = list.data
  const opened = rows.find((e) => e.id === open)
  // The tasks of the model first, then any other an evaluation was sent for.
  const tasks = [...new Set([...model.tasks, ...rows.map((e) => e.task)])].filter((task) => rows.some((e) => e.task === task))

  return (
    <section className="space-y-4">
      <h2 className="text-sm font-medium">{t('models.eval.benchmarks')}</h2>
      {!rows.length && <p className="text-sm text-muted-foreground">{t('models.eval.none')}</p>}

      {tasks.map((task) => {
        const ofTask = rows.filter((e) => e.task === task)
        // The columns: the metrics that at least one evaluation of this task shows, in the order of the task.
        const columns = (metrics.data.get(task) ?? []).filter((x) => ofTask.some((e) => e.shown.includes(x.id) && x.id in e.results))
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
                    <th className="px-3 py-2 font-medium">{t('models.eval.origin')}</th>
                    {columns.map((x) => <th key={x.id} className="px-3 py-2 font-medium" title={t(`models.metrics.${x.id}`, { defaultValue: '' })}>{x.name}{!x.higher && ' ↓'}</th>)}
                    <th className="px-3 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {ofTask.map((e) => <Row key={e.id} e={e} columns={columns} locale={i18n.language} onOpen={() => setOpen(e.id)} />)}
                </tbody>
              </table>
            </div>
          </div>
        )
      })}
      {opened && <EvaluationDialog model={model} evaluation={opened} onClose={() => setOpen(null)} />}
    </section>
  )
}

function Row({ e, columns, locale, onOpen }: { e: Evaluation; columns: Metric[]; locale: string; onOpen: () => void }) {
  const { t } = useTranslation()
  const left = notShown(e)
  return (
    <tr className="cursor-pointer border-t hover:bg-muted/40" onClick={onOpen}>
      <td className="px-3 py-2">
        {e.dataset
          ? <Link className="underline-offset-2 hover:underline" to={`/datasets/${e.dataset}`} onClick={(ev) => ev.stopPropagation()}>{e.dataset}</Link>
          : <span className="text-muted-foreground" title={t('models.eval.noDatasetHint')}>—</span>}
      </td>
      <td className="px-3 py-2">{e.split ?? '—'}</td>
      <td className="px-3 py-2">{e.version}</td>
      <td className="px-3 py-2"><SourceBadge evaluation={e} /></td>
      {e.status === 'done' && columns.map((x) => (
        <td key={x.id} className={`px-3 py-2 font-mono ${x.primary ? 'font-semibold' : ''}`}>{e.shown.includes(x.id) && x.id in e.results ? formatValue(e.results[x.id]) : '·'}</td>
      ))}
      {e.status !== 'done' && (
        <td colSpan={columns.length} className="px-3 py-2"><Badge variant={e.status === 'failed' ? 'destructive' : 'secondary'}>{t(`models.eval.status.${e.status}`)}</Badge></td>
      )}
      <td className="px-3 py-2 text-right text-xs text-muted-foreground" title={new Date(e.createdAt).toLocaleDateString(locale)}>{left > 0 ? t('models.eval.moreMetrics', { n: left }) : ''}</td>
    </tr>
  )
}
