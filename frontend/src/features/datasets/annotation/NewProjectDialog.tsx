import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { LabelsEditor, labelsValid } from './LabelsEditor'
import { addProject, CURRENT_USER, type LabelDef, type TaskType } from './store'

const TASKS: TaskType[] = ['classification', 'ner', 'qa']

/** Creates an annotation task: everyone who can see the dataset will be able to annotate it. */
export function NewProjectDialog({ datasetKey, open, onOpenChange }: { datasetKey: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [task, setTask] = useState<TaskType>('classification')
  const [labels, setLabels] = useState<LabelDef[]>([])

  const valid = name.trim() && (task === 'qa' || labelsValid(labels))

  const submit = () => {
    addProject({ datasetKey, name: name.trim(), task, labels: task === 'qa' ? [] : labels.map((l) => ({ ...l, name: l.name.trim(), description: l.description.trim() })), createdBy: CURRENT_USER, total: 0 })
    setName(''); setLabels([]); setTask('classification'); onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('datasets.annotation.new')}</DialogTitle>
          <DialogDescription>{t('datasets.annotation.newHint')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="ap-name">{t('datasets.annotation.name')}</Label>
            <Input id="ap-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>{t('datasets.annotation.task')}</Label>
            <div className="grid gap-2">
              {TASKS.map((k) => (
                <button key={k} type="button" onClick={() => setTask(k)} className={cn('rounded-lg border p-3 text-left text-sm transition-colors hover:bg-muted/50', task === k && 'border-primary bg-muted/50')}>
                  <div className="font-medium">{t(`datasets.annotation.tasks.${k}.title`)}</div>
                  <div className="text-muted-foreground">{t(`datasets.annotation.tasks.${k}.hint`)}</div>
                </button>
              ))}
            </div>
          </div>
          {task !== 'qa' && (
            <div className="space-y-2">
              <Label>{t('datasets.annotation.labels')}</Label>
              <LabelsEditor labels={labels} onChange={setLabels} showKind={task === 'ner'} />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('datasets.annotation.cancel')}</Button>
          <Button disabled={!valid} onClick={submit}>{t('datasets.annotation.create')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
