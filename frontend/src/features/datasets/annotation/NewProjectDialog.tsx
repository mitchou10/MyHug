import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { LabelsEditor, labelsValid } from './LabelsEditor'
import { emptyScale, ScaleForm, scaleValid as isScaleValid, toScale } from './ScaleForm'
import { addProject, CURRENT_USER, TABULAR_TASKS, TEXT_TASKS, type LabelDef, type TaskType } from './store'

/** Tasks that need a list of labels; `regression` needs a scale; `qa` needs nothing more. */
const needsLabels = (t: TaskType) => t !== 'qa' && t !== 'regression'

/** Creates an annotation task in two steps (what, then how): everyone who can see the dataset will be able to annotate it. */
export function NewProjectDialog({ datasetKey, modality, open, onOpenChange }: { datasetKey: string; modality: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const TASKS: TaskType[] = modality === 'tabular' ? TABULAR_TASKS : TEXT_TASKS
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [task, setTask] = useState<TaskType>(TASKS[0])
  const [labels, setLabels] = useState<LabelDef[]>([])
  const [sc, setSc] = useState(emptyScale)

  const scale = toScale(sc)
  const scaleValid = isScaleValid(scale)
  const hasStep2 = needsLabels(task) || task === 'regression'
  const valid = !!name.trim() && (!needsLabels(task) || labelsValid(labels)) && (task !== 'regression' || scaleValid)

  const reset = () => { setStep(0); setName(''); setLabels([]); setTask(TASKS[0]); setSc(emptyScale) }
  const submit = () => {
    addProject({
      datasetKey, name: name.trim(), task, createdBy: CURRENT_USER, total: 0,
      labels: needsLabels(task) ? labels.map((l) => ({ ...l, name: l.name.trim(), description: l.description.trim() })) : [],
      scale: task === 'regression' ? scale : undefined,
    })
    reset(); onOpenChange(false)
  }
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) reset(); onOpenChange(o) }}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('datasets.annotation.new')}</DialogTitle>
          <DialogDescription>{step === 0 ? t('datasets.annotation.newHint') : t(`datasets.annotation.step2.${task === 'regression' ? 'scale' : 'labels'}`)}</DialogDescription>
        </DialogHeader>

        {step === 0 ? (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="ap-name">{t('datasets.annotation.name')}</Label>
              <Input id="ap-name" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>{t('datasets.annotation.task')}</Label>
              <div className="grid gap-2 sm:grid-cols-2">
                {TASKS.map((k) => (
                  <button key={k} type="button" onClick={() => setTask(k)} className={cn('rounded-lg border p-3 text-left text-sm transition-colors hover:bg-muted/50', task === k && 'border-primary bg-muted/50')}>
                    <div className="font-medium">{t(`datasets.annotation.tasks.${k}.title`)}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">{t(`datasets.annotation.tasks.${k}.hint`)}</div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : needsLabels(task) ? (
          <div className="max-h-[55vh] overflow-y-auto pr-1"><LabelsEditor labels={labels} onChange={setLabels} showKind={task === 'ner'} /></div>
        ) : (
          <ScaleForm value={sc} onChange={setSc} />
        )}

        <DialogFooter className="items-center sm:justify-between">
          <span className="text-xs text-muted-foreground">{hasStep2 && t('datasets.annotation.step', { n: step + 1 })}</span>
          <div className="flex gap-2">
            {step === 0 ? <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('datasets.annotation.cancel')}</Button> : <Button variant="ghost" onClick={() => setStep(0)}>{t('datasets.annotation.back')}</Button>}
            {step === 0 && hasStep2 ? <Button disabled={!name.trim()} onClick={() => setStep(1)}>{t('datasets.annotation.next')}</Button> : <Button disabled={!valid} onClick={submit}>{t('datasets.annotation.create')}</Button>}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
