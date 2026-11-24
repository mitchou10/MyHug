import { Plus, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Container } from '@/components/Container'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { DatasetCard } from '../components/DatasetCard'
import { DATASETS, MODALITIES, type Modality } from '../mockData'

type Sort = 'downloads' | 'likes' | 'updatedAt'

/** Browse all datasets: search, filter by modality, sort. */
export function DatasetsPage() {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [modality, setModality] = useState<Modality | null>(null)
  const [sort, setSort] = useState<Sort>('downloads')

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    return DATASETS.filter((d) => (!modality || d.modality === modality) && (!q || `${d.owner}/${d.name} ${d.description} ${d.tags.join(' ')}`.toLowerCase().includes(q))).sort((a, b) =>
      sort === 'updatedAt' ? b.updatedAt.localeCompare(a.updatedAt) : b[sort] - a[sort],
    )
  }, [query, modality, sort])

  return (
    <Container className="max-w-6xl py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">{t('datasets.title')}</h1>
          <p className="mt-1 text-muted-foreground">{t('datasets.count', { count: results.length })}</p>
        </div>
        <Button><Plus />{t('datasets.new')}</Button>
      </div>

      <div className="mt-6 space-y-4">
        <div className="flex flex-wrap gap-3">
          <div className="relative min-w-52 flex-1">
            <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input className="pl-8" placeholder={t('datasets.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="flex gap-1">
            {(['downloads', 'likes', 'updatedAt'] as const).map((s) => (
              <Button key={s} size="sm" variant={sort === s ? 'secondary' : 'ghost'} className={cn(sort === s && 'font-semibold')} onClick={() => setSort(s)}>
                {t(`datasets.sort.${s}`)}
              </Button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {MODALITIES.map((m) => (
            <Button key={m} size="sm" variant={modality === m ? 'default' : 'outline'} className="rounded-full" onClick={() => setModality(modality === m ? null : m)}>
              {t(`datasets.modalities.${m}`)}
            </Button>
          ))}
        </div>

        <div>
          {results.length ? (
            <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {results.map((d) => <DatasetCard key={d.id} dataset={d} />)}
            </div>
          ) : (
            <p className="mt-10 text-center text-muted-foreground">{t('datasets.none')}</p>
          )}
        </div>
      </div>
    </Container>
  )
}
