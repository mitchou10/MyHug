import { Plus, Search } from 'lucide-react'
import { useDeferredValue, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Container } from '@/components/Container'
import { ErrorNotice } from '@/components/ErrorNotice'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { TASKS_BY_MODALITY } from '../tasks'
import { cn } from '@/lib/utils'
import { useModelList } from '../api/models'
import { ModelCard } from '../components/ModelCard'
import { NewModelDialog } from '../components/NewModelDialog'
import { INPUTS, NO_FILTERS, type ModelFilters } from '../types'

const SORTS = [['downloads', 'downloads'], ['likes', 'likes'], ['updated', 'updatedAt']] as const

/** Browse all models: search, filter by the kind of data and by the task, sort. All of it is done by the server. */
export function ModelsPage() {
  const { t } = useTranslation()
  const [filters, setFilters] = useState<ModelFilters>(NO_FILTERS)
  const [creating, setCreating] = useState(false)
  // The search goes to the server once the person stops typing for a moment, not at every key.
  const q = useDeferredValue(filters.q)
  const sent = useMemo(() => ({ ...filters, q }), [filters, q])
  const list = useModelList(sent)
  const change = (patch: Partial<ModelFilters>) => setFilters((old) => ({ ...old, ...patch }))

  const tasks = filters.modality ? TASKS_BY_MODALITY[filters.modality] : []

  return (
    <Container className="max-w-6xl py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">{t('models.title')}</h1>
          <p className="mt-1 text-muted-foreground">{list.isLoading ? t('models.loading') : t('models.count', { count: list.total })}</p>
        </div>
        <Button onClick={() => setCreating(true)}><Plus />{t('models.new')}</Button>
      </div>

      <div className="mt-6 space-y-4">
        <div className="flex flex-wrap gap-3">
          <div className="relative min-w-52 flex-1">
            <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input className="pl-8" placeholder={t('models.search')} aria-label={t('models.search')} value={filters.q} onChange={(e) => change({ q: e.target.value })} />
          </div>
          <div className="flex gap-1">
            {SORTS.map(([sort, label]) => (
              <Button key={sort} size="sm" variant={filters.sort === sort ? 'secondary' : 'ghost'} aria-pressed={filters.sort === sort} className={cn(filters.sort === sort && 'font-semibold')} onClick={() => change({ sort })}>{t(`datasets.sort.${label}`)}</Button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-sm text-muted-foreground">{t('models.reads')}</span>
          {INPUTS.map((i) => (
            <Button key={i} size="sm" variant={filters.modality === i ? 'default' : 'outline'} aria-pressed={filters.modality === i} className="rounded-full"
              onClick={() => change({ modality: filters.modality === i ? null : i, task: null })}>{t(`datasets.modalities.${i}`)}</Button>
          ))}
        </div>
        {tasks.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-sm text-muted-foreground">{t('models.does')}</span>
            {tasks.map((task) => (
              <Button key={task} size="sm" variant={filters.task === task ? 'default' : 'outline'} aria-pressed={filters.task === task} className="rounded-full"
                onClick={() => change({ task: filters.task === task ? null : task })}>{t(`datasets.annotation.tasks.${task}.title`)}</Button>
            ))}
          </div>
        )}

        {list.isError && <ErrorNotice error={list.error} />}
        {list.isLoading && <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40 rounded-xl" />)}</div>}
        {!list.isLoading && !list.isError && (list.items.length ? (
          <>
            <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{list.items.map((m) => <ModelCard key={m.id} model={m} />)}</div>
            {list.hasMore && <div className="flex justify-center"><Button variant="outline" disabled={list.loadingMore} onClick={list.loadMore}>{t('models.more', { count: list.total - list.items.length })}</Button></div>}
          </>
        ) : (
          <p className="mt-10 text-center text-muted-foreground">{t('models.none')}</p>
        ))}
      </div>
      <NewModelDialog open={creating} onOpenChange={setCreating} />
    </Container>
  )
}
