import { ArrowDown, ArrowLeft, ArrowUp, Heart, Lock, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router'
import { Container } from '@/components/Container'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { DatasetCard } from '@/features/datasets/components/DatasetCard'
import { formatCount } from '@/features/datasets/format'
import { getDataset } from '@/features/datasets/mockData'
import { ModelCard } from '@/features/models/components/ModelCard'
import { findModel, useModels } from '@/features/models/store'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { AddItemsDialog } from '../components/AddItemsDialog'
import { NewCollectionDialog } from '../components/NewCollectionDialog'
import { canSee, deleteCollection, findCollection, isMine, moveItem, removeItem, setNote, toggleLike, useCollections } from '../store'

/** One collection: what its author gathered and why. The author can edit it, reorder it and write a note on each item. */
export function CollectionDetailPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { owner, slug } = useParams()
  const { collections, liked } = useCollections()
  const { models } = useModels()
  const [editing, setEditing] = useState(false)
  const [adding, setAdding] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const c = findCollection(collections, owner, slug)
  if (!c || !canSee(c)) return <NotFoundPage />

  const mine = isMine(c)
  const isLiked = liked.has(c.id)

  return (
    <Container className="max-w-6xl py-6">
      <Link to="/collections" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />{t('collections.back')}</Link>
      <div className="mt-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">{c.title}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span>{c.owner}</span><span>·</span><span>{c.updatedAt}</span>
            {c.visibility === 'private' && <Badge variant="outline"><Lock />{t('models.private')}</Badge>}
          </div>
          {c.description && <p className="mt-3 max-w-3xl">{c.description}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant={isLiked ? 'default' : 'outline'} aria-pressed={isLiked} onClick={() => toggleLike(c.id)}><Heart />{formatCount(c.likes + (isLiked ? 1 : 0))}</Button>
          {mine && (
            <>
              <Button variant="outline" onClick={() => setAdding(true)}><Plus />{t('collections.addItems')}</Button>
              <Button variant="outline" onClick={() => setEditing(true)}><Pencil />{t('collections.edit')}</Button>
              {confirming
                ? <Button variant="destructive" onClick={() => { deleteCollection(c.id); navigate('/collections') }}>{t('datasets.annotation.pre.dialog.confirmDelete')}</Button>
                : <Button variant="ghost" onClick={() => setConfirming(true)} onBlur={() => setConfirming(false)}><Trash2 />{t('datasets.annotation.pre.dialog.delete')}</Button>}
            </>
          )}
        </div>
      </div>

      {!c.items.length && <p className="mt-10 rounded-lg border border-dashed py-10 text-center text-muted-foreground">{t('collections.empty')}</p>}

      <div className="mt-8 grid gap-6 sm:grid-cols-2 xl:grid-cols-3">
        {c.items.map((item, i) => {
          const [o, n] = item.ref.split('/')
          const dataset = item.type === 'dataset' ? getDataset(o, n) : undefined
          const model = item.type === 'model' ? findModel(models, o, n) : undefined
          return (
            <div key={`${item.type}:${item.ref}`} className="space-y-2">
              {dataset ? <DatasetCard dataset={dataset} /> : model ? <ModelCard model={model} /> : <div className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">{item.ref} · {t('collections.missing')}</div>}
              {mine ? (
                <div className="flex items-center gap-1">
                  <Input className="h-8" aria-label={t('collections.note')} placeholder={t('collections.note')} defaultValue={item.note ?? ''} onBlur={(e) => setNote(c.id, item.type, item.ref, e.target.value.trim())} />
                  <Button size="icon" variant="ghost" aria-label={t('collections.up')} disabled={i === 0} onClick={() => moveItem(c.id, i, -1)}><ArrowUp /></Button>
                  <Button size="icon" variant="ghost" aria-label={t('collections.down')} disabled={i === c.items.length - 1} onClick={() => moveItem(c.id, i, 1)}><ArrowDown /></Button>
                  <Button size="icon" variant="ghost" aria-label={t('collections.remove')} onClick={() => removeItem(c.id, item.type, item.ref)}><X /></Button>
                </div>
              ) : item.note ? <p className="px-1 text-sm text-muted-foreground italic">{item.note}</p> : null}
            </div>
          )
        })}
      </div>
      {editing && <NewCollectionDialog open collection={c} onOpenChange={(o) => !o && setEditing(false)} />}
      {adding && <AddItemsDialog collectionId={c.id} open onOpenChange={(o) => !o && setAdding(false)} />}
    </Container>
  )
}
