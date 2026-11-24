import { Plus, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { Container } from '@/components/Container'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { CollectionCard } from '../components/CollectionCard'
import { NewCollectionDialog } from '../components/NewCollectionDialog'
import { canSee, isMine, useCollections } from '../store'

/** Browse the collections: those of everybody, or only yours. */
export function CollectionsPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { collections } = useCollections()
  const [query, setQuery] = useState('')
  const [mine, setMine] = useState(false)
  const [sort, setSort] = useState<'likes' | 'updatedAt'>('likes')
  const [creating, setCreating] = useState(false)

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    return collections.filter((c) => canSee(c) && (!mine || isMine(c)) && (!q || `${c.owner} ${c.title} ${c.description}`.toLowerCase().includes(q)))
      .sort((a, b) => (sort === 'likes' ? b.likes - a.likes : b.updatedAt.localeCompare(a.updatedAt)))
  }, [collections, query, mine, sort])

  return (
    <Container className="max-w-6xl py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">{t('collections.title')}</h1>
          <p className="mt-1 text-muted-foreground">{t('collections.subtitle')}</p>
        </div>
        <Button onClick={() => setCreating(true)}><Plus />{t('collections.new')}</Button>
      </div>
      <div className="mt-6 space-y-4">
        <div className="flex flex-wrap gap-3">
          <div className="relative min-w-52 flex-1">
            <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input className="pl-8" placeholder={t('collections.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="flex gap-1">
            <Button size="sm" variant={mine ? 'default' : 'outline'} className="rounded-full" onClick={() => setMine(!mine)}>{t('collections.mine')}</Button>
            {(['likes', 'updatedAt'] as const).map((s) => <Button key={s} size="sm" variant={sort === s ? 'secondary' : 'ghost'} className={cn(sort === s && 'font-semibold')} onClick={() => setSort(s)}>{t(`collections.sort.${s}`)}</Button>)}
          </div>
        </div>
        {results.length ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{results.map((c) => <CollectionCard key={c.id} collection={c} />)}</div> : <p className="mt-10 text-center text-muted-foreground">{t('collections.none')}</p>}
      </div>
      {creating && <NewCollectionDialog open onOpenChange={(o) => !o && setCreating(false)} onCreated={(c) => navigate(`/collections/${c.owner}/${c.slug}`)} />}
    </Container>
  )
}
