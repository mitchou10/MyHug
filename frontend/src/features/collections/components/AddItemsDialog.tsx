import { Box, Check, Database, Plus, Search } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { DATASETS } from '@/features/datasets/mockData'
import { useModelList } from '@/features/models/api/models'
import { NO_FILTERS } from '@/features/models/types'
import { addItem, hasItem, useCollections, type ItemType } from '../store'

/** Adds datasets and models to a collection: search, then add. */
export function AddItemsDialog({ collectionId, open, onOpenChange }: { collectionId: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const collection = useCollections().collections.find((c) => c.id === collectionId)
  const [type, setType] = useState<ItemType>('dataset')
  const [query, setQuery] = useState('')
  // Models are searched on the server: only the ones the person can see come back.
  const found = useModelList({ ...NO_FILTERS, q: useDeferredValue(query) }, type === 'model')
  if (!collection) return null

  const q = query.trim().toLowerCase()
  const rows = (type === 'dataset'
    ? DATASETS.map((d) => ({ ref: `${d.owner}/${d.name}`, text: d.description, tags: d.tags }))
    : found.items.filter((m) => m.visibility === 'public' || m.owner === collection.owner).map((m) => ({ ref: m.address, text: m.description, tags: m.tags }))
  ).filter((r) => !q || `${r.ref} ${r.text} ${r.tags.join(' ')}`.toLowerCase().includes(q))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('collections.addItems')}</DialogTitle>
          <DialogDescription>{collection.title}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap gap-2">
          {(['dataset', 'model'] as const).map((k) => (
            <Button key={k} size="sm" variant={type === k ? 'default' : 'outline'} className="rounded-full" onClick={() => setType(k)}>{k === 'dataset' ? <Database /> : <Box />}{t(k === 'dataset' ? 'datasets.title' : 'models.title')}</Button>
          ))}
          <div className="relative min-w-40 flex-1">
            <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input className="pl-8" aria-label={t('collections.searchItems')} placeholder={t('collections.searchItems')} value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
        </div>
        <ul className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
          {rows.map((r) => {
            const added = hasItem(collection, type, r.ref)
            return (
              <li key={r.ref} className="flex items-center gap-2 rounded-md border p-2.5 text-sm">
                <div className="min-w-0 flex-1"><div className="truncate font-medium">{r.ref}</div><div className="line-clamp-1 text-xs text-muted-foreground">{r.text}</div></div>
                <Button size="sm" variant={added ? 'ghost' : 'outline'} disabled={added} onClick={() => addItem(collection.id, { type, ref: r.ref })}>{added ? <><Check />{t('collections.added')}</> : <><Plus />{t('collections.addOne')}</>}</Button>
              </li>
            )
          })}
          {!rows.length && <li className="py-6 text-center text-sm text-muted-foreground">{t('models.none')}</li>}
        </ul>
      </DialogContent>
    </Dialog>
  )
}
