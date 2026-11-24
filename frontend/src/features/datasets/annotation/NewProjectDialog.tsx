import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { LabelsEditor, labelsValid } from './LabelsEditor'
import { AudioRegionOptions } from './AudioRegionOptions'
import { MultiLabelToggle } from './MultiLabelToggle'
import { emptyScale, ScaleForm, scaleValid as isScaleValid, toScale } from './ScaleForm'
import { addProject, CURRENT_USER, AUDIO_TASKS, DEFAULT_TRACKS, IMAGE_TASKS, TABULAR_TASKS, supportsMultiLabel, TEXT_TASKS, VIDEO_TASKS, type LabelDef, type TaskType } from './store'

/** Tasks that need a list of labels; `regression` needs a scale; `qa` needs nothing more. */
const needsLabels = (t: TaskType) => t !== 'qa' && t !== 'regression' && t !== 'image_caption' && t !== 'image_vqa' && t !== 'audio_transcription' && t !== 'audio_caption' && t !== 'video_caption'

/** Creates an annotation task in two steps (what, then how): everyone who can see the dataset will be able to annotate it. */
export function NewProjectDialog({ datasetKey, modality, open, onOpenChange }: { datasetKey: string; modality: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const TASKS: TaskType[] = modality === 'tabular' ? TABULAR_TASKS : modality === 'image' ? IMAGE_TASKS : modality === 'audio' ? AUDIO_TASKS : modality === 'video' ? VIDEO_TASKS : TEXT_TASKS
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [task, setTask] = useState<TaskType>(TASKS[0])
  const [labels, setLabels] = useState<LabelDef[]>([])
  const [multi, setMulti] = useState(false)
  const [sc, setSc] = useState(emptyScale)
  const [regions, setRegions] = useState(false)
  const [tracks, setTracks] = useState<string[]>(DEFAULT_TRACKS)

  const scale = toScale(sc)
  const scaleValid = isScaleValid(scale)
  // Sounds and videos are both timed: they share the regions and the tracks.
  const isTimed = modality === 'audio' || modality === 'video'
  const kind = task.replace(/^(audio|video)_/, '')
  /** Tracking has its own tool: no regions, no tracks to name. */
  const timedRegions = isTimed && task !== 'video_tracking'
  /** For audio, classification, description and regression can apply to the whole clip or to stretches of it. */
  const canChoose = timedRegions && (kind === 'classification' || kind === 'caption' || task === 'regression')
  const regionsMode = timedRegions && (canChoose ? regions : kind === 'segments' || kind === 'transcription')
  // Speakers are optional when transcribing: none, or at least two.
  const optionalLabels = task === 'audio_transcription'
  const hasStep2 = needsLabels(task) || task === 'regression' || timedRegions
  const labelsOk = needsLabels(task) ? labelsValid(labels) : optionalLabels ? labels.length === 0 || labelsValid(labels) : true
  const valid = !!name.trim() && labelsOk && (task !== 'regression' || scaleValid) && (!regionsMode || tracks.length > 0)

  const reset = () => { setStep(0); setName(''); setLabels([]); setMulti(false); setTask(TASKS[0]); setSc(emptyScale); setRegions(false); setTracks(DEFAULT_TRACKS) }
  const submit = () => {
    addProject({
      datasetKey, name: name.trim(), task, createdBy: CURRENT_USER, total: 0,
      labels: needsLabels(task) || optionalLabels ? labels.map((l) => ({ ...l, name: l.name.trim(), description: l.description.trim() })) : [],
      scale: task === 'regression' ? scale : undefined,
      multiLabel: supportsMultiLabel(task) && multi ? true : undefined,
      granularity: canChoose ? (regions ? 'regions' : 'clip') : undefined,
      tracks: regionsMode ? tracks : undefined,
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
        ) : (
          <div className="max-h-[55vh] space-y-4 overflow-y-auto pr-1">
            {timedRegions && <AudioRegionOptions canChoose={canChoose} regions={regionsMode} onRegions={setRegions} tracks={tracks} onTracks={setTracks} />}
            {(needsLabels(task) || optionalLabels) && (
              <div className="space-y-3">
                {optionalLabels && <p className="text-sm text-muted-foreground">{t('datasets.annotation.audio.speakersHint')}</p>}
                {task === 'image_keypoints' && <p className="text-sm text-muted-foreground">{t('datasets.annotation.image.keypointsHint')}</p>}
                {supportsMultiLabel(task) && <MultiLabelToggle value={multi} onChange={setMulti} />}
                <LabelsEditor labels={labels} onChange={setLabels} showKind={task === 'ner'} />
              </div>
            )}
            {task === 'regression' && <ScaleForm value={sc} onChange={setSc} />}
          </div>
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
