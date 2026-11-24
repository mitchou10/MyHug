import { Plus, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Container } from '@/components/Container'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { TaskType } from '@/features/datasets/annotation/store'
import type { Modality } from '@/features/datasets/mockData'
import { cn } from '@/lib/utils'
import { ModelCard } from '../components/ModelCard'
import { NewModelDialog } from '../components/NewModelDialog'
import { describe } from '../describe'
import { INPUTS } from '../mockData'
import { useModels } from '../store'

type Sort = 'downloads' | 'likes' | 'updatedAt'
/** What a model does, on which kind of data: "Detection" of images and "Segments" of sounds are different things. */
interface Job { task: TaskType; input: Modality }

/** Browse all models: search, filter by the kind of data they read, sort. */
export function ModelsPage() {
  const { t } = useTranslation()
  const { models } = useModels()
  const [query, setQuery] = useState('')
  const [input, setInput] = useState<Modality | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [sort, setSort] = useState<Sort>('downloads')
  const [creating, setCreating] = useState(false)

  // The jobs that exist in the catalogue, narrowed to the kind of data when one is chosen.
  const jobs = useMemo(() => {
    const seen = new Map<string, Job>()
    models.forEach((m) => m.tasks.forEach((task) => m.inputs.forEach((i) => seen.set(`${task}|${i}`, { task, input: i }))))
    return [...seen.values()].filter((j) => !input || j.input === input).sort((a, b) => INPUTS.indexOf(a.input) - INPUTS.indexOf(b.input))
  }, [models, input])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    return models
      .filter((m) => (!input || m.inputs.includes(input)) && (!job || (m.tasks.includes(job.task) && m.inputs.includes(job.input))) && (!q || `${m.owner}/${m.name} ${describe(m, t)} ${m.tags.join(' ')} ${m.tasks.map((k) => t(`datasets.annotation.tasks.${k}.title`)).join(' ')}`.toLowerCase().includes(q)))
      .sort((a, b) => (sort === 'updatedAt' ? b.updatedAt.localeCompare(a.updatedAt) : b[sort] - a[sort]))
  }, [models, query, input, job, sort, t])

  return (
    <Container className="max-w-6xl py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">{t('models.title')}</h1>
          <p className="mt-1 text-muted-foreground">{t('models.count', { count: results.length })}</p>
        </div>
        <Button onClick={() => setCreating(true)}><Plus />{t('models.new')}</Button>
      </div>

      <div className="mt-6 space-y-4">
        <div className="flex flex-wrap gap-3">
          <div className="relative min-w-52 flex-1">
            <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input className="pl-8" placeholder={t('models.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="flex gap-1">
            {(['downloads', 'likes', 'updatedAt'] as const).map((s) => (
              <Button key={s} size="sm" variant={sort === s ? 'secondary' : 'ghost'} className={cn(sort === s && 'font-semibold')} onClick={() => setSort(s)}>{t(`datasets.sort.${s}`)}</Button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-sm text-muted-foreground">{t('models.reads')}</span>
          {INPUTS.map((i) => (
            <Button key={i} size="sm" variant={input === i ? 'default' : 'outline'} className="rounded-full"
              onClick={() => { setInput(input === i ? null : i); if (job && job.input !== i) setJob(null) }}>{t(`datasets.modalities.${i}`)}</Button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-sm text-muted-foreground">{t('models.does')}</span>
          {input ? (
            // One kind of data: its few tasks fit on a line.
            jobs.map((j) => {
              const on = job?.task === j.task && job.input === j.input
              return <Button key={j.task} size="sm" variant={on ? 'default' : 'outline'} className="rounded-full" onClick={() => setJob(on ? null : j)}>{t(`datasets.annotation.tasks.${j.task}.title`)}</Button>
            })
          ) : (
            // All kinds of data: too many tasks to show at once, so they are in a menu, grouped by kind of data.
            <select aria-label={t('models.does')} value={job ? `${job.task}|${job.input}` : ''} className="h-8 rounded-md border bg-background px-2 text-sm"
              onChange={(e) => setJob(jobs.find((j) => `${j.task}|${j.input}` === e.target.value) ?? null)}>
              <option value="">{t('models.allTasks')}</option>
              {INPUTS.map((i) => (
                <optgroup key={i} label={t(`datasets.modalities.${i}`)}>
                  {jobs.filter((j) => j.input === i).map((j) => <option key={j.task} value={`${j.task}|${j.input}`}>{t(`datasets.annotation.tasks.${j.task}.title`)}</option>)}
                </optgroup>
              ))}
            </select>
          )}
        </div>

        {results.length ? (
          <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{results.map((m) => <ModelCard key={m.id} model={m} />)}</div>
        ) : (
          <p className="mt-10 text-center text-muted-foreground">{t('models.none')}</p>
        )}
      </div>
      <NewModelDialog open={creating} onOpenChange={setCreating} taken={models.map((m) => m.id)} />
    </Container>
  )
}
