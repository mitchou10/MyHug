import { Library, Plus } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { addItem, createCollection, hasItem, isMine, removeItem, useCollections, type ItemType } from '../store'

/** "Add to a collection": ticks the collections of the user that hold this dataset or model, and creates one on the spot. */
export function AddToCollection({ type, reference }: { type: ItemType; reference: string }) {
  const { t } = useTranslation()
  const { collections } = useCollections()
  const mine = collections.filter(isMine)
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const inCount = mine.filter((c) => hasItem(c, type, reference)).length

  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}><Library />{t('collections.add')}{inCount > 0 && <Badge variant="secondary" className="ml-1">{inCount}</Badge>}</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('collections.addTitle')}</DialogTitle>
            <DialogDescription>{reference}</DialogDescription>
          </DialogHeader>
          <ul className="max-h-64 space-y-1.5 overflow-y-auto">
            {mine.map((c) => {
              const on = hasItem(c, type, reference)
              return (
                <li key={c.id}>
                  <label className="flex cursor-pointer items-center gap-2.5 rounded-md border p-2.5 text-sm">
                    <input type="checkbox" className="size-4 accent-primary" checked={on} onChange={() => (on ? removeItem(c.id, type, reference) : addItem(c.id, { type, ref: reference }))} />
                    <span className="flex-1 truncate">{c.title}</span>
                    {c.visibility === 'private' && <Badge variant="outline">{t('models.private')}</Badge>}
                  </label>
                </li>
              )
            })}
            {!mine.length && <li className="text-sm text-muted-foreground">{t('collections.none')}</li>}
          </ul>
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (title.trim()) { createCollection({ title, description: '', visibility: 'public', items: [{ type, ref: reference }] }); setTitle('') } }}>
            <Input aria-label={t('collections.fields.title')} placeholder={t('collections.newInline')} value={title} onChange={(e) => setTitle(e.target.value)} />
            <Button type="submit" variant="outline" disabled={!title.trim()}><Plus />{t('datasets.annotation.create')}</Button>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
