import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { createCollection, updateCollection, type Collection } from '../store'

/** Creates a collection, or edits the title, the description and the visibility of one. */
export function NewCollectionDialog({ open, onOpenChange, collection, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; collection?: Collection; onCreated?: (c: Collection) => void }) {
  const { t } = useTranslation()
  const [title, setTitle] = useState(collection?.title ?? '')
  const [description, setDescription] = useState(collection?.description ?? '')
  const [priv, setPriv] = useState(collection?.visibility === 'private')

  const valid = title.trim().length > 0
  const submit = () => {
    const visibility = priv ? 'private' : 'public'
    if (collection) updateCollection(collection.id, { title: title.trim(), description: description.trim(), visibility })
    else { onCreated?.(createCollection({ title, description, visibility })); setTitle(''); setDescription(''); setPriv(false) }
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t(collection ? 'collections.edit' : 'collections.new')}</DialogTitle>
          <DialogDescription>{t('collections.newHint')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5"><Label htmlFor="c-title">{t('collections.fields.title')}</Label><Input id="c-title" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="c-desc">{t('collections.fields.description')}</Label><Textarea id="c-desc" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} /></div>
          <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border p-3 text-sm">
            <input type="checkbox" className="mt-0.5 size-4 accent-primary" checked={priv} onChange={(e) => setPriv(e.target.checked)} />
            <span><span className="font-medium">{t('collections.fields.private')}</span><span className="block text-xs text-muted-foreground">{t('collections.fields.privateHint')}</span></span>
          </label>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('datasets.annotation.cancel')}</Button>
          <Button disabled={!valid} onClick={submit}>{t(collection ? 'datasets.annotation.save' : 'datasets.annotation.create')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
