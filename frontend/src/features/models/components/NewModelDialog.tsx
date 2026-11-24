import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { IMAGE_TASKS, AUDIO_TASKS, TABULAR_TASKS, TEXT_TASKS, TIMESERIES_TASKS, VIDEO_TASKS, CURRENT_USER, type TaskType } from '@/features/datasets/annotation/store'
import type { Modality } from '@/features/datasets/mockData'
import { cn } from '@/lib/utils'
import { INPUTS, type Model } from '../mockData'
import { addModel } from '../store'

const TASKS: Record<Modality, TaskType[]> = { text: TEXT_TASKS, image: IMAGE_TASKS, audio: AUDIO_TASKS, video: VIDEO_TASKS, tabular: TABULAR_TASKS, timeseries: TIMESERIES_TASKS }
const SLUG = /^[a-z0-9][a-z0-9._-]*$/

/** Declares a model: what it reads, what it does, its licence. The files will come with the backend. */
export function NewModelDialog({ open, onOpenChange, taken }: { open: boolean; onOpenChange: (o: boolean) => void; taken: string[] }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [input, setInput] = useState<Modality>('text')
  const [task, setTask] = useState<TaskType>('classification')
  const [description, setDescription] = useState('')
  const [license, setLicense] = useState('apache-2.0')
  const [languages, setLanguages] = useState('')
  const [priv, setPriv] = useState(false)

  const slug = name.trim()
  const exists = taken.includes(`${CURRENT_USER}/${slug}`)
  const valid = SLUG.test(slug) && !exists && TASKS[input].includes(task)

  const reset = () => { setName(''); setDescription(''); setLanguages(''); setPriv(false); setInput('text'); setTask('classification') }
  const submit = () => {
    const m: Model = {
      id: `${CURRENT_USER}/${slug}`, owner: CURRENT_USER, name: slug, description: description.trim() || undefined, tasks: [task], inputs: [input],
      languages: languages.split(',').map((l) => l.trim()).filter(Boolean), license: license.trim() || 'other', tags: [], paramsM: 0, sizeMb: 0, downloads: 0, likes: 0,
      updatedAt: new Date().toISOString().slice(0, 10), version: '0.1.0', versions: [{ version: '0.1.0', date: new Date().toISOString().slice(0, 10), sizeMb: 0, changelog: 'first' }],
      files: [{ path: 'README.md', sizeMb: 0.01 }], benchmarks: [], trainedOn: [], visibility: priv ? 'private' : 'public',
    }
    addModel(m); reset(); onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) reset(); onOpenChange(o) }}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('models.new')}</DialogTitle>
          <DialogDescription>{t('models.newHint')}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          <div className="space-y-1.5">
            <Label htmlFor="m-name">{t('models.fields.name')}</Label>
            <div className="flex items-center gap-1.5"><span className="text-sm text-muted-foreground">{CURRENT_USER} /</span><Input id="m-name" autoFocus value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!slug && !valid} /></div>
            {!!slug && !SLUG.test(slug) && <p className="text-xs text-destructive">{t('models.fields.nameHint')}</p>}
            {exists && <p className="text-xs text-destructive">{t('models.fields.nameTaken')}</p>}
          </div>
          <div className="space-y-1.5">
            <Label>{t('models.fields.input')}</Label>
            <div className="flex flex-wrap gap-1.5">
              {INPUTS.map((i) => (
                <Button key={i} type="button" size="sm" variant={input === i ? 'default' : 'outline'} className="rounded-full" onClick={() => { setInput(i); setTask(TASKS[i][0]) }}>{t(`datasets.modalities.${i}`)}</Button>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>{t('models.fields.task')}</Label>
            <div className="grid gap-2 sm:grid-cols-2">
              {TASKS[input].map((k) => (
                <button key={k} type="button" onClick={() => setTask(k)} className={cn('rounded-lg border p-2.5 text-left text-sm transition-colors hover:bg-muted/50', task === k && 'border-primary bg-muted/50')}>
                  <div className="font-medium">{t(`datasets.annotation.tasks.${k}.title`)}</div>
                  <div className="text-xs text-muted-foreground">{t(`datasets.annotation.tasks.${k}.hint`)}</div>
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="m-desc">{t('models.fields.description')}</Label>
            <Textarea id="m-desc" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5"><Label htmlFor="m-lic">{t('models.fields.license')}</Label><Input id="m-lic" value={license} onChange={(e) => setLicense(e.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="m-lang">{t('models.fields.languages')}</Label><Input id="m-lang" placeholder="fr, en" value={languages} onChange={(e) => setLanguages(e.target.value)} /></div>
          </div>
          <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border p-3 text-sm">
            <input type="checkbox" className="mt-0.5 size-4 accent-primary" checked={priv} onChange={(e) => setPriv(e.target.checked)} />
            <span><span className="font-medium">{t('models.fields.private')}</span><span className="block text-xs text-muted-foreground">{t('models.fields.privateHint')}</span></span>
          </label>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('datasets.annotation.cancel')}</Button>
          <Button disabled={!valid} onClick={submit}>{t('datasets.annotation.create')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
